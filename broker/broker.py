"""The broker (Vermittler, PROJEKT.md 11a, Stufe 4; 17.11.2026): the only part of the hub that opens SSH connections to
devices and the only one that can decrypt their secrets.

Where it sits: its own container in its own Docker network `devices`, shared only with the web service. No published
port, no database, no Docker socket, not in the network of the AI runs (they can not reach it). It reaches the home
network because its network is a normal bridge with a way out.

How it is asked: the web service connects over TCP (port 7000), sends one JSON line {"token", "op", "device", "args"}
and reads JSON lines back. The token is HUB_BROKER_TOKEN (both containers have it from the .env). The web service
checked the user and the ownership; it sends exactly the one device with its sealed secret. The broker decrypts the
secret with its age identity (HUB_VAULT_IDENTITY, only here; the web service has only the public key) for this one
connection and forgets it after.

Rules it keeps itself (a second wall behind the web service):
- Targets: never loopback, link-local, multicast, the Docker networks it is in or their gateway (the server's own
  services); private addresses (home network) only for devices the owner approved (`lan_ok`). The address is resolved
  once and that address is connected to, so DNS can not switch it in between. A device with a pinned address whose
  name now resolves elsewhere is refused (`address_changed`).
- Host keys: no connection without the trusted host key of the device; `hostkey` only reads the key so the user can
  compare and confirm it. A changed key is refused (`host_key_changed`).
- Origin: "ai" may only run fixed actions (never shell, files, logs or key making), and with a password login only if
  the user allowed the password for the AI (`ai_password`). The web service checks the same.
- Commands only from device_profiles.py; no text of a user or an AI ever reaches a command line.

Ops: hostkey, test, online, start (an action as a job), job, logs, keygen, shell, ls, get, put, rename, delete,
mkdir, read, write. Errors are {"ok": false, "error": code}; codes are listed in ERRORS.
"""
import asyncio
import base64
import hmac
import ipaddress
import json
import os
import socket
import stat
import time

import asyncssh
import pyrage

from . import device_profiles as profiles

PORT = int(os.environ.get("HUB_BROKER_PORT", "7000"))
MAX_LINE = 256 * 1024                # one JSON line (a file chunk is 128 KB before base64)
CHUNK = 96 * 1024
MAX_TEXT = 512 * 1024                # a text file opened in the editor
MAX_LOG = 64 * 1024
CONNECT_TIMEOUT = 8
ACTION_TIMEOUT = {"reboot": 30, "poweroff": 30, "updates_check": 300, "updates_install": 3600}
JOB_KEEP = 3600                      # finished jobs are kept this long for the web to read
SHELL_IDLE = 15 * 60                 # a shell without input is closed after this
MAX_SHELLS = 4
ERRORS = ("token", "bad", "target", "address_changed", "unreachable", "refused", "timeout", "auth", "host_key_unknown",
          "host_key_changed", "secret", "unsupported", "sudo", "busy", "not_allowed", "failed", "missing", "exists")
CGNAT = ipaddress.ip_network("100.64.0.0/10")   # Tailscale addresses count as public here
HUMAN_ONLY = ("shell", "ls", "get", "put", "rename", "delete", "mkdir", "read", "write", "logs", "keygen", "test")

JOBS: dict[str, dict] = {}
_shells = {"open": 0}
_ssh_slots = asyncio.Semaphore(4)


class BrokerError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code if code in ERRORS else "failed"


# --- secrets -----------------------------------------------------------------------------------------------------
def _identity():
    text = os.environ.get("HUB_VAULT_IDENTITY", "").strip()
    if not text:
        raise BrokerError("secret")
    try:
        return pyrage.x25519.Identity.from_str(text)
    except Exception:
        raise BrokerError("secret") from None


def unseal(sealed: str) -> str:
    """The clear text of a secret sealed by the web service (vault.py: "age:" + base64 of an age file)."""
    if not sealed or not sealed.startswith("age:"):
        raise BrokerError("secret")
    try:
        return pyrage.decrypt(base64.b64decode(sealed[4:]), [_identity()]).decode("utf-8")
    except BrokerError:
        raise
    except Exception:
        raise BrokerError("secret") from None


def seal(text: str) -> str:
    recipient = _identity().to_public()
    return "age:" + base64.b64encode(pyrage.encrypt(text.encode("utf-8"), [recipient])).decode("ascii")


# --- targets -----------------------------------------------------------------------------------------------------
def own_networks() -> list:
    """The networks this container is directly in (the Docker networks) and their gateways: the server's own
    services. Read from /proc/net/route (IPv4), standard library only."""
    nets = []
    try:
        with open("/proc/net/route") as routes:
            next(routes)
            for line in routes:
                fields = line.split()
                dest, gateway, mask = (socket.inet_ntoa(int(f, 16).to_bytes(4, "little")) for f in (fields[1], fields[2], fields[7]))
                if dest != "0.0.0.0":
                    nets.append(ipaddress.ip_network(f"{dest}/{mask}", strict=False))
                if gateway != "0.0.0.0":
                    nets.append(ipaddress.ip_network(f"{gateway}/32"))
    except (OSError, StopIteration, ValueError):
        pass
    return nets


def allowed(address: str, lan_ok: bool, networks: list | None = None) -> bool:
    """May the broker connect to this address? (rules in the module text)"""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return False
    for net in networks if networks is not None else own_networks():
        if ip.version == net.version and ip in net:
            return False
    if ip.version == 4 and ip in CGNAT:
        return True
    if ip.is_private:
        return bool(lan_ok)
    return ip.is_global


async def target(device: dict) -> str:
    """The checked address to connect to (see the module text)."""
    fixed = (device.get("ip") or "").strip()
    if fixed:
        address = fixed
    else:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(device.get("host", ""), None, type=socket.SOCK_STREAM)
        except OSError:
            raise BrokerError("unreachable") from None
        found = list(dict.fromkeys(info[4][0] for info in infos))
        pinned = device.get("pinned_ip") or ""
        if pinned and pinned not in found:
            raise BrokerError("address_changed")
        address = pinned or found[0]
    if not allowed(address, bool(device.get("lan_ok"))):
        raise BrokerError("target")
    return address


def _port(device: dict) -> int:
    port = int(device.get("port") or 22)
    if not 0 < port < 65536:
        raise BrokerError("bad")
    return port


# --- connections ---------------------------------------------------------------------------------------------------
def _check_origin(op: str, device: dict, origin: str) -> None:
    if origin not in ("human", "ai"):
        raise BrokerError("bad")
    if origin == "ai":
        if op in HUMAN_ONLY:
            raise BrokerError("not_allowed")
        if device.get("auth") == "password" and not device.get("ai_password"):
            raise BrokerError("not_allowed")   # a password is for the human unless the user allowed it for the AI


async def connect(device: dict) -> tuple[asyncssh.SSHClientConnection, str]:
    """An SSH connection with the trusted host key and the device's own login. Returns (connection, secret) where
    the secret is the password (for sudo -S) or "" for a key."""
    if not device.get("host_key"):
        raise BrokerError("host_key_unknown")
    try:
        trusted = asyncssh.import_public_key(device["host_key"])
    except (ValueError, asyncssh.KeyImportError):
        raise BrokerError("host_key_unknown") from None
    address = await target(device)
    secret = unseal(device.get("secret", "")) if device.get("secret") else ""
    options = {"username": device.get("user") or None, "known_hosts": ([trusted], [], []),
               "connect_timeout": CONNECT_TIMEOUT, "keepalive_interval": 30, "agent_path": None,
               "client_keys": [], "password": None, "kbdint_auth": False}
    if device.get("auth") == "password":
        options["password"] = secret or None
    elif secret:
        try:
            options["client_keys"] = [asyncssh.import_private_key(secret)]
        except (ValueError, asyncssh.KeyImportError):
            raise BrokerError("secret") from None
        secret = ""
    try:
        conn = await asyncssh.connect(address, _port(device), **options)
    except asyncssh.HostKeyNotVerifiable:
        raise BrokerError("host_key_changed") from None
    except asyncssh.PermissionDenied:
        raise BrokerError("auth") from None
    except (asyncio.TimeoutError, TimeoutError):
        raise BrokerError("timeout") from None
    except ConnectionRefusedError:
        raise BrokerError("refused") from None
    except (OSError, asyncssh.Error):
        raise BrokerError("unreachable") from None
    return conn, secret


def _with_sudo(cmd: str, secret: str) -> tuple[str, str | None]:
    """Put the sudo prefix into a profile command: with a password it is read from stdin (human only)."""
    if secret:
        return cmd.replace("{sudo}", "sudo -S -p '' "), secret + "\n"
    return cmd.replace("{sudo}", "sudo -n "), None


async def run(conn, cmd: str, secret: str, timeout: int) -> tuple[int, str]:
    cmd, stdin = _with_sudo(cmd, secret)
    try:
        done = await asyncio.wait_for(conn.run(cmd, input=stdin, check=False), timeout)
    except (asyncio.TimeoutError, TimeoutError):
        raise BrokerError("timeout") from None
    out = (done.stdout or "") + (done.stderr or "")
    if isinstance(out, bytes):
        out = out.decode("utf-8", "replace")
    return done.exit_status if done.exit_status is not None else 255, out


def _sudo_refused(out: str) -> bool:
    lowered = out.lower()
    return "a password is required" in lowered or "not allowed to execute" in lowered or "sudo: a terminal" in lowered


# --- ops -----------------------------------------------------------------------------------------------------------
async def op_hostkey(device: dict, args: dict) -> dict:
    """Read the device's host key (no login), for the user to compare and trust."""
    address = await target(device)
    try:
        key = await asyncio.wait_for(asyncssh.get_server_host_key(address, _port(device)), CONNECT_TIMEOUT + 2)
    except (asyncio.TimeoutError, TimeoutError):
        raise BrokerError("timeout") from None
    except ConnectionRefusedError:
        raise BrokerError("refused") from None
    except (OSError, asyncssh.Error):
        raise BrokerError("unreachable") from None
    if key is None:
        raise BrokerError("unreachable")
    return {"key": key.export_public_key("openssh").decode().strip(), "fingerprint": key.get_fingerprint("sha256"),
            "address": address}


async def op_resolve(device: dict, args: dict) -> dict:
    """The address the hostname has now (a suggestion for the IP field), only if the broker could reach it at all
    (the same target rules: a home address only with the owner's approval). No connection is made."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(device.get("host", ""), None, type=socket.SOCK_STREAM)
    except OSError:
        raise BrokerError("unreachable") from None
    for address in dict.fromkeys(info[4][0] for info in infos):
        if allowed(address, bool(device.get("lan_ok"))):
            return {"address": address}
    raise BrokerError("target")


async def op_online(device: dict, args: dict) -> dict:
    """Is the SSH port open? A TCP connection only, no login."""
    address = await target(device)
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(address, _port(device)), 3)
        writer.close()
        return {"online": True}
    except (OSError, asyncio.TimeoutError, TimeoutError):
        return {"online": False}


async def op_test(device: dict, args: dict) -> dict:
    """Log in, find out the operating system and whether sudo allows the buttons' commands."""
    conn, secret = await connect(device)
    async with conn:
        code, out = await run(conn, profiles.DETECT, "", 20)
        windows = ""
        if "Linux" not in out and "Darwin" not in out:
            _, windows = await run(conn, profiles.DETECT_WINDOWS, "", 20)
        family, name = profiles.detect(out, windows)
        sudo = None
        if family and family != "windows":
            if secret:
                code, out = await run(conn, "{sudo}true", secret, 20)
            else:
                code, out = await run(conn, profiles.SUDO_TEST, "", 20)
            sudo = code == 0
    return {"family": family, "name": name, "sudo": sudo}


async def _action(device: dict, action: str) -> dict:
    command = profiles.command(device.get("family", ""), action)
    if not command:
        raise BrokerError("unsupported")
    conn, secret = await connect(device)
    async with conn:
        try:
            code, out = await run(conn, command, secret, ACTION_TIMEOUT[action])
        except (asyncssh.ConnectionLost, asyncssh.DisconnectError, BrokenPipeError):
            if action in ("reboot", "poweroff"):
                return {"done": True}        # the device went down while answering: that is the point
            raise BrokerError("unreachable") from None
    if action in ("reboot", "poweroff"):
        if code not in (0, 255, -1) and _sudo_refused(out):
            raise BrokerError("sudo")
        return {"done": True}
    if _sudo_refused(out):
        raise BrokerError("sudo")
    if action == "updates_check":
        found = profiles.count_updates(out)
        if found is None:
            raise BrokerError("failed")
        return {"count": found}
    return {"done": code == 0, "reboot": profiles.REBOOT_MARK in out, "tail": out[-2000:]}


async def _job(key: str, device: dict, action: str) -> None:
    job = JOBS[key]
    try:
        async with _ssh_slots:
            job["result"] = await _action(device, action)
        job["state"] = "done"
    except BrokerError as exc:
        job["state"], job["error"] = "failed", exc.code
    except Exception:
        job["state"], job["error"] = "failed", "failed"
    job["finished"] = int(time.time())


async def op_start(device: dict, args: dict) -> dict:
    """Start an action as a job (it may take long: updates); the web reads it with `job`."""
    action, key = args.get("action"), str(args.get("key", ""))
    if action not in profiles.ACTIONS or not key or len(key) > 40:
        raise BrokerError("bad")
    now = int(time.time())
    for old in [k for k, j in JOBS.items() if j.get("finished") and now - j["finished"] > JOB_KEEP]:
        JOBS.pop(old, None)
    if JOBS.get(key, {}).get("state") == "running":
        raise BrokerError("busy")
    JOBS[key] = {"action": action, "state": "running", "started": now}
    asyncio.get_running_loop().create_task(_job(key, device, action))
    return {"state": "running"}


async def op_job(device: dict, args: dict) -> dict:
    job = JOBS.get(str(args.get("key", "")))
    if job is None:
        return {"state": "none"}
    return {k: v for k, v in job.items() if k in ("action", "state", "result", "error", "started", "finished")}


async def op_logs(device: dict, args: dict) -> dict:
    command = profiles.log_command(device.get("family", ""), args.get("source", ""))
    if not command:
        raise BrokerError("unsupported")
    conn, _ = await connect(device)
    async with conn:
        _, out = await run(conn, command, "", 30)
    return {"text": out[-MAX_LOG:]}


async def op_keygen(device: dict, args: dict) -> dict:
    """A new ed25519 key pair: the private part sealed at once, only the public line goes out."""
    key = asyncssh.generate_private_key("ssh-ed25519", comment="agent-hub")
    private = key.export_private_key("openssh").decode()
    public = key.export_public_key("openssh").decode().strip()
    return {"sealed": seal(private), "public": public}


def _clean_path(path) -> str:
    if not isinstance(path, str) or not path or len(path) > 4096 or "\x00" in path:
        raise BrokerError("bad")
    return path


def _sftp_error(exc: Exception) -> BrokerError:
    if isinstance(exc, (asyncssh.SFTPNoSuchFile, FileNotFoundError)):
        return BrokerError("missing")
    if isinstance(exc, (asyncssh.SFTPPermissionDenied, PermissionError)):
        return BrokerError("not_allowed")
    if isinstance(exc, (asyncssh.SFTPFileAlreadyExists, FileExistsError)):
        return BrokerError("exists")
    return BrokerError("failed")


def _kind(attrs) -> str:
    mode = attrs.permissions or 0
    return "dir" if stat.S_ISDIR(mode) else "link" if stat.S_ISLNK(mode) else "file"


async def op_files(op: str, device: dict, args: dict, reader, writer) -> dict | None:
    conn, _ = await connect(device)
    async with conn:
        try:
            async with conn.start_sftp_client() as sftp:
                if op == "ls":
                    path = await sftp.realpath(args.get("path") or ".")
                    entries = []
                    for name in await sftp.readdir(path):
                        if name.filename in (".", ".."):
                            continue
                        a = name.attrs
                        entries.append({"name": name.filename, "kind": _kind(a), "size": a.size or 0,
                                        "mtime": int(a.mtime or 0)})
                    entries.sort(key=lambda e: (e["kind"] != "dir", e["name"].lower()))
                    return {"path": path, "entries": entries[:2000]}
                path = _clean_path(args.get("path"))
                if op == "read":
                    attrs = await sftp.stat(path)
                    if (attrs.size or 0) > MAX_TEXT:
                        raise BrokerError("bad")
                    async with sftp.open(path, "rb") as f:
                        data = await f.read()
                    return {"text": data.decode("utf-8", "replace")}
                if op == "write":
                    text = args.get("text", "")
                    if not isinstance(text, str) or len(text) > MAX_TEXT:
                        raise BrokerError("bad")
                    async with sftp.open(path, "wb") as f:
                        await f.write(text.encode("utf-8"))
                    return {}
                if op == "rename":
                    await sftp.rename(path, _clean_path(args.get("to")))
                    return {}
                if op == "delete":
                    if _kind(await sftp.lstat(path)) == "dir":
                        await sftp.rmdir(path)    # only empty folders: nothing is deleted by accident
                    else:
                        await sftp.remove(path)
                    return {}
                if op == "mkdir":
                    await sftp.mkdir(path)
                    return {}
                if op == "get":
                    attrs = await sftp.stat(path)
                    await _send(writer, {"ok": True, "size": attrs.size or 0})
                    async with sftp.open(path, "rb") as f:
                        while True:
                            data = await f.read(CHUNK)
                            if not data:
                                break
                            await _send(writer, {"data": base64.b64encode(data).decode("ascii")})
                    await _send(writer, {"end": True})
                    return None
                if op == "put":
                    size, written = int(args.get("size", 0)), 0
                    async with sftp.open(path, "wb") as f:
                        await _send(writer, {"ok": True, "ready": True})
                        while True:
                            message = await _read(reader)
                            if message is None or message.get("abort"):
                                raise BrokerError("failed")
                            if message.get("end"):
                                break
                            data = base64.b64decode(message.get("data", ""))
                            written += len(data)
                            if written > size:
                                raise BrokerError("bad")
                            await f.write(data)
                    return {"size": written}
        except (asyncssh.SFTPError, OSError) as exc:
            raise _sftp_error(exc) from None
    raise BrokerError("bad")


async def op_shell(device: dict, args: dict, reader, writer) -> None:
    """A terminal on the device for the human: the PTY runs there, here only the bytes pass. Lines from the web:
    {"in": base64} and {"size": [cols, rows]}; to the web: {"out": base64} and at the end {"exit": code}."""
    if _shells["open"] >= MAX_SHELLS:
        raise BrokerError("busy")
    cols, rows = (int(x) for x in (args.get("size") or [80, 24])[:2])
    conn, _ = await connect(device)
    _shells["open"] += 1
    try:
        async with conn:
            process = await conn.create_process(term_type="xterm-256color", term_size=(max(10, min(cols, 500)),
                                                max(4, min(rows, 200))), encoding=None)
            await _send(writer, {"ok": True})

            async def device_to_web():
                while True:
                    data = await process.stdout.read(8192)
                    if not data:
                        break
                    await _send(writer, {"out": base64.b64encode(data).decode("ascii")})

            async def web_to_device():
                while True:
                    try:
                        message = await asyncio.wait_for(_read(reader), SHELL_IDLE)
                    except (asyncio.TimeoutError, TimeoutError):
                        break
                    if message is None:
                        break
                    if "in" in message:
                        process.stdin.write(base64.b64decode(message["in"]))
                    elif "size" in message:
                        c, r = (int(x) for x in message["size"][:2])
                        process.change_terminal_size(max(10, min(c, 500)), max(4, min(r, 200)))

            tasks = [asyncio.ensure_future(device_to_web()), asyncio.ensure_future(web_to_device())]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in tasks:
                task.cancel()
            process.close()
            await _send(writer, {"exit": process.exit_status if process.exit_status is not None else 0})
    finally:
        _shells["open"] -= 1


SIMPLE = {"hostkey": op_hostkey, "resolve": op_resolve, "online": op_online, "test": op_test, "start": op_start, "job": op_job,
          "logs": op_logs, "keygen": op_keygen}
FILES = ("ls", "get", "put", "rename", "delete", "mkdir", "read", "write")


# --- the server ----------------------------------------------------------------------------------------------------
async def _read(reader) -> dict | None:
    line = await reader.readline()
    if not line:
        return None
    if len(line) > MAX_LINE:
        raise BrokerError("bad")
    try:
        message = json.loads(line)
    except ValueError:
        raise BrokerError("bad") from None
    if not isinstance(message, dict):
        raise BrokerError("bad")
    return message


async def _send(writer, message: dict) -> None:
    writer.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")
    await writer.drain()


def _token_ok(given) -> bool:
    expected = os.environ.get("HUB_BROKER_TOKEN", "")
    return bool(expected) and isinstance(given, str) and hmac.compare_digest(given.encode(), expected.encode())


async def handle(reader, writer) -> None:
    try:
        request = await asyncio.wait_for(_read(reader), 10)
        if request is None:
            return
        if not _token_ok(request.get("token")):
            await _send(writer, {"ok": False, "error": "token"})
            return
        op, device, args = request.get("op"), request.get("device") or {}, request.get("args") or {}
        if not isinstance(device, dict) or not isinstance(args, dict):
            raise BrokerError("bad")
        _check_origin(op, device, request.get("origin", "human"))
        if op in SIMPLE:
            result = await (SIMPLE[op](device, args) if op in ("start", "job", "keygen")
                            else _limited(SIMPLE[op], device, args))
            await _send(writer, {"ok": True, **result})
        elif op in FILES:
            result = await op_files(op, device, args, reader, writer)
            if result is not None:
                await _send(writer, {"ok": True, **result})
        elif op == "shell":
            await op_shell(device, args, reader, writer)
        else:
            raise BrokerError("bad")
    except BrokerError as exc:
        try:
            await _send(writer, {"ok": False, "error": exc.code})
        except OSError:
            pass
    except (asyncio.TimeoutError, TimeoutError, ConnectionError, ValueError, TypeError, KeyError):
        try:
            await _send(writer, {"ok": False, "error": "failed"})
        except OSError:
            pass
    finally:
        try:
            writer.close()
        except OSError:
            pass


async def _limited(function, device, args):
    async with _ssh_slots:
        return await function(device, args)


async def main() -> None:
    if not os.environ.get("HUB_BROKER_TOKEN") or not os.environ.get("HUB_VAULT_IDENTITY"):
        print("broker: HUB_BROKER_TOKEN and HUB_VAULT_IDENTITY are needed", flush=True)
    server = await asyncio.start_server(handle, "0.0.0.0", PORT, limit=MAX_LINE + 1024)
    print(f"broker: listening on {PORT}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
