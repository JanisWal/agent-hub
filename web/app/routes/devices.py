"""Devices of the Manager view and the device window (17.11.2026). Sent with fetch (static/devices.js, devwin.js); the
secret is only ever received, never sent back. Errors answer 400 with a code in `error`, a foreign device is 404.

Who may what (CLAUDE.md "Geräte und Geheimnisse"): every route checks the user and the device's owner (devices.py).
- Without a password: the list, the state (online, job), reading the host key, trusting it, the connection test,
  making a key, searching updates, the settings of the device.
- With the user's password each time (deps.reauth): restart, shut down, installing updates, forgetting the host key.
- Shell, files and the device's logs: after the password once, for GRANT_SECONDS on this device and this login
  (`grant`). The shell is a WebSocket that checks the session, the origin (HUB_BASE_URL) and the grant.
Nothing here is reachable with the runner's token or a run's ticket: these are browser routes (cookies) only.
"""
import asyncio
import base64
import hashlib
import json
import os
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse

from .. import broker, devices, device_profiles, i18n, users
from ..deps import COOKIE_NAME, api_user, fail, ok, reauth

router = APIRouter()
GRANT_SECONDS = 15 * 60
ONLINE_CACHE = 45
PENDING_KEYS = 600          # a read host key may be trusted within this time
MAX_UPLOAD = 200 * 1024 * 1024
_grants: dict[tuple[str, int], float] = {}
_online: dict[int, tuple[float, bool]] = {}
_pending: dict[int, tuple[float, str, str, str]] = {}   # device -> (time, key, fingerprint, address)
_seen_jobs: set[tuple[int, int]] = set()
BUTTONS = {"power": "poweroff", "reboot": "reboot"}
WITH_PASSWORD = ("reboot", "poweroff", "updates_install")


def _bad(code: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": code}, status_code=status)


def _given(value, default=None):
    """A form value as sent; the default when the route is called without it (FastAPI fills it in for a request)."""
    return value if isinstance(value, str) else default


def _session_key(token: str | None) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def _granted(request_cookies, device_id: int) -> bool:
    key = (_session_key(request_cookies.get(COOKIE_NAME)), device_id)
    until = _grants.get(key, 0)
    if until < time.time():
        _grants.pop(key, None)
        return False
    return True


def _device(user: users.User, device_id: int):
    device = devices.get(user.id, device_id)
    return device, devices.payload(user.id, device_id) if device else None


def suggest_ip(user_id: int, device_id: int) -> None:
    """Find the address of the hostname (by the broker, after the answer was sent) as a suggestion for the IP field.
    Quietly nothing if the broker is off or the name does not resolve to an address it may reach."""
    payload = devices.payload(user_id, device_id)
    if payload is None or not broker.available():
        return
    try:
        devices.set_ip_hint(user_id, device_id, broker.call("resolve", payload).get("address", ""))
    except broker.BrokerError:
        devices.set_ip_hint(user_id, device_id, "")


# --- the list and the settings ------------------------------------------------------------------------------------
@router.post("/projects/{project_id}/devices")
def create_device(project_id: int, name: str = Form(""), hostname: str = Form(""),
                  description: str = Form(""), key: str = Form(""), kind: str = Form("other"), ip: str = Form(""),
                  ssh_user: str = Form(""), ssh_port: str = Form("22"), auth: str = Form("key"),
                  user: users.User = Depends(api_user), background: BackgroundTasks = None):
    try:
        device = devices.create(user.id, project_id, name, hostname, description, key, kind, ip,
                                ssh_user=_given(ssh_user, ""), ssh_port=_given(ssh_port) or 22,
                                auth=_given(auth, "key"))
    except ValueError as exc:
        return _bad(str(exc))
    if device is None:
        return fail(404)
    if background is not None:
        background.add_task(suggest_ip, user.id, device.id)
    return ok(id=device.id)


@router.post("/devices/{device_id}")
def change_device(device_id: int, name: str = Form(""), hostname: str = Form(""), description: str = Form(""),
                  key: str = Form(""), remove_key: str = Form(""), kind: str = Form("other"), ip: str = Form(""),
                  ssh_user: str | None = Form(None), ssh_port: str | None = Form(None), auth: str | None = Form(None),
                  user: users.User = Depends(api_user), background: BackgroundTasks = None):
    try:
        project_id = devices.update(user.id, device_id, name, hostname, description, key, remove_key == "1", kind, ip,
                                    ssh_user=_given(ssh_user), ssh_port=_given(ssh_port), auth=_given(auth))
    except ValueError as exc:
        return _bad(str(exc))
    if project_id is None:
        return fail(404)
    _online.pop(device_id, None)
    if background is not None:
        background.add_task(suggest_ip, user.id, device_id)
    return ok()


@router.post("/devices/{device_id}/delete")
def delete_device(device_id: int, user: users.User = Depends(api_user)):
    return ok() if devices.delete(user.id, device_id) else fail(404)


@router.post("/devices/{device_id}/ai")
def device_ai(device_id: int, actions: list[str] = Form([]), ai_password: str = Form(""),
              user: users.User = Depends(api_user)):
    """What the AI may trigger on the device (default nothing), and whether it may use a stored password."""
    return ok() if devices.set_ai(user.id, device_id, actions, ai_password == "1") else fail(404)


def _info(device: devices.Device, lang: str) -> dict:
    now = int(time.time())
    return {"id": device.id, "name": device.name, "kind": device.kind, "hostname": device.hostname, "ip": device.ip,
            "description": device.description, "ip_hint": device.ip_hint, "ssh_user": device.ssh_user, "ssh_port": device.ssh_port,
            "auth": device.auth, "has_key": device.has_key, "public_key": device.public_key,
            "host_fp": device.host_fp, "pinned_ip": device.pinned_ip, "os_family": device.os_family,
            "os_name": device.os_name, "sudo_ok": device.sudo_ok, "lan_ok": device.lan_ok,
            "ai_actions": list(device.ai_actions), "ai_password": device.ai_password,
            "actions": list(device.actions), "updates": devices.updates_pending(device, now),
            "reboot_needed": device.reboot_needed, "checked_at": device.checked_at,
            "sudoers": device_profiles.sudoers(device.os_family, device.ssh_user) if device.os_family else "",
            "broker": broker.available()}


@router.get("/devices/{device_id}/info")
def device_info(device_id: int, user: users.User = Depends(api_user)):
    device = devices.get(user.id, device_id)
    return fail(404) if device is None else ok(device=_info(device, user.language))


@router.get("/devices/{device_id}/setup")
def device_setup(device_id: int, family: str = "", user: users.User = Depends(api_user)):
    """The steps of "set up on the device" for its system (or the one chosen in the dialog), with its values put in."""
    device = devices.get(user.id, device_id)
    if device is None:
        return fail(404)
    family = family if family in device_profiles.FAMILIES else (device.os_family or "debian")
    lang = user.language
    steps = []
    for step, command in device_profiles.guide(family, device.ssh_user, device.public_key, device.hostname):
        text = i18n.STRINGS.get(lang, i18n.STRINGS["de"]).get(f"setup_{step}_{family}") or i18n.t(lang, f"setup_{step}")
        steps.append({"step": step, "title": i18n.t(lang, f"setup_title_{step}"), "text": text, "command": command})
    return ok(family=family, steps=steps, families=[{"id": f, "name": device_profiles.PROFILES[f]["name"]}
                                                   for f in device_profiles.FAMILIES])


# --- the broker: host key, test, key, state, actions ----------------------------------------------------------------
def _broker(op: str, payload: dict | None, **args) -> dict | JSONResponse:
    try:
        return broker.call(op, payload, **args)
    except broker.BrokerError as exc:
        return _bad(exc.code, 502 if exc.code == "off" else 400)


@router.post("/devices/{device_id}/hostkey")
def device_hostkey(device_id: int, user: users.User = Depends(api_user)):
    """Read the host key the device shows now (no login), for the user to compare with the device and trust."""
    device, payload = _device(user, device_id)
    if device is None:
        return fail(404)
    answer = _broker("hostkey", payload)
    if isinstance(answer, JSONResponse):
        return answer
    _pending[device_id] = (time.time(), answer["key"], answer["fingerprint"], answer["address"])
    devices.set_ip_hint(user.id, device_id, answer["address"])
    return ok(fingerprint=answer["fingerprint"], address=answer["address"], known=device.host_fp,
              same=answer["fingerprint"] == device.host_fp)


@router.post("/devices/{device_id}/trust")
def device_trust(device_id: int, fingerprint: str = Form(""), user: users.User = Depends(api_user)):
    """Trust exactly the key read just before (by its fingerprint), never one the browser sends."""
    pending = _pending.get(device_id)
    if devices.get(user.id, device_id) is None:
        return fail(404)
    if pending is None or time.time() - pending[0] > PENDING_KEYS or pending[2] != fingerprint:
        return _bad("host_key_unknown")
    _pending.pop(device_id, None)
    devices.trust_host(user.id, device_id, pending[1], pending[2], pending[3])
    devices.log(device_id, user.id, "trust", "ok", pending[2])
    return ok()


@router.post("/devices/{device_id}/forget-host")
def device_forget(request: Request, device_id: int, password: str = Form(""), user: users.User = Depends(api_user)):
    if devices.get(user.id, device_id) is None:
        return fail(404)
    refused = reauth(request, user, password)
    if refused is not None:
        return refused
    devices.forget_host(user.id, device_id)
    devices.log(device_id, user.id, "forget_host", "ok")
    return ok()


@router.post("/devices/{device_id}/test")
def device_test(device_id: int, user: users.User = Depends(api_user)):
    """Log in, find the system, check sudo; the result is kept on the device (buttons follow from it)."""
    device, payload = _device(user, device_id)
    if device is None:
        return fail(404)
    answer = _broker("test", payload)
    if isinstance(answer, JSONResponse):
        devices.log(device_id, user.id, "test", json.loads(answer.body).get("error", "failed"))
        return answer
    devices.set_system(user.id, device_id, answer.get("family", ""), answer.get("name", ""), answer.get("sudo"))
    devices.log(device_id, user.id, "test", "ok", answer.get("name", ""))
    _online[device_id] = (time.time(), True)
    return ok(family=answer.get("family", ""), name=answer.get("name", ""), sudo=answer.get("sudo"))


@router.post("/devices/{device_id}/keygen")
def device_keygen(device_id: int, user: users.User = Depends(api_user)):
    """A new key pair made by the broker: the private part is sealed there, only the public line comes here."""
    if devices.get(user.id, device_id) is None:
        return fail(404)
    answer = _broker("keygen", None)
    if isinstance(answer, JSONResponse):
        return answer
    if not devices.set_generated_key(user.id, device_id, answer.get("sealed", ""), answer.get("public", "")):
        return _bad("failed")
    devices.log(device_id, user.id, "keygen", "ok")
    return ok(public=answer["public"])


def _job_key(device_id: int) -> str:
    return f"d{device_id}"


def _read_job(user: users.User, device: devices.Device) -> dict:
    """The broker's job of this device; a finished one is taken over once (updates, log)."""
    try:
        job = broker.call("job", None, key=_job_key(device.id))
    except broker.BrokerError:
        return {"state": "none"}
    started = int(job.get("started") or 0)
    if job.get("state") in ("done", "failed") and (device.id, started) not in _seen_jobs:
        _seen_jobs.add((device.id, started))
        action, result = job.get("action", ""), job.get("result") or {}
        if job["state"] == "done" and action == "updates_check":
            devices.set_updates(user.id, device.id, found=result.get("count", 0))
        elif job["state"] == "done" and action == "updates_install":
            devices.set_updates(user.id, device.id, found=0, reboot=bool(result.get("reboot")))
        elif job["state"] == "done" and action == "reboot":
            devices.set_updates(user.id, device.id, reboot=False)
        devices.log(device.id, user.id, action, job["state"] if job["state"] == "done" else job.get("error", "failed"),
                    seconds=int(job.get("finished") or started) - started)
        if action in ("reboot", "poweroff"):
            _online.pop(device.id, None)
    return {"state": job.get("state", "none"), "action": job.get("action", ""), "error": job.get("error", ""),
            "result": job.get("result") or {}, "finished": job.get("finished") or 0}


@router.get("/devices/{device_id}/state")
def device_state(device_id: int, user: users.User = Depends(api_user)):
    """LED and buttons: online (TCP to the SSH port, by the broker, cached), the running job, found updates."""
    device, payload = _device(user, device_id)
    if device is None:
        return fail(404)
    online = None
    if broker.available() and device.trusted:
        cached = _online.get(device_id)
        if cached and time.time() - cached[0] < ONLINE_CACHE:
            online = cached[1]
        else:
            try:
                online = bool(broker.call("online", payload).get("online"))
            except broker.BrokerError:
                online = None
            if online is not None:
                _online[device_id] = (time.time(), online)
    job = _read_job(user, device) if broker.available() else {"state": "none"}
    device = devices.get(user.id, device_id)
    return ok(online=online, job=job, updates=devices.updates_pending(device), reboot_needed=device.reboot_needed,
              actions=list(device.actions))


@router.post("/devices/{device_id}/action")
def device_action(request: Request, device_id: int, button: str = Form(""), password: str = Form(""),
                  user: users.User = Depends(api_user)):
    """A button: power (shut down), reboot, update (searches; when updates were found, installs them)."""
    device, payload = _device(user, device_id)
    if device is None:
        return fail(404)
    if button == "update":
        action = "updates_install" if devices.updates_pending(device) else "updates_check"
    else:
        action = BUTTONS.get(button, "")
    if action not in device.actions:
        return _bad("unsupported")
    if action in WITH_PASSWORD:
        refused = reauth(request, user, password)
        if refused is not None:
            return refused
    answer = _broker("start", payload, action=action, key=_job_key(device_id))
    if isinstance(answer, JSONResponse):
        return answer
    devices.log(device_id, user.id, action, "started")
    return ok(action=action)


# --- shell, files and logs: for the human, after the password ------------------------------------------------------
@router.post("/devices/{device_id}/grant")
def device_grant(request: Request, device_id: int, password: str = Form(""), user: users.User = Depends(api_user)):
    """The password once for shell, files and logs of this device, valid GRANT_SECONDS for this login."""
    if devices.get(user.id, device_id) is None:
        return fail(404)
    refused = reauth(request, user, password)
    if refused is not None:
        return refused
    _grants[(_session_key(request.cookies.get(COOKIE_NAME)), device_id)] = time.time() + GRANT_SECONDS
    return ok(seconds=GRANT_SECONDS)


def _guarded(request: Request, user: users.User, device_id: int):
    """(device, payload) if the user owns the device and has the grant, else the answer to send."""
    device, payload = _device(user, device_id)
    if device is None:
        return fail(404)
    if not _granted(request.cookies, device_id):
        return _bad("grant", 403)
    return device, payload


@router.get("/devices/{device_id}/logs")
def device_logs(request: Request, device_id: int, source: str = "journal", user: users.User = Depends(api_user)):
    guarded = _guarded(request, user, device_id)
    if isinstance(guarded, JSONResponse):
        return guarded
    answer = _broker("logs", guarded[1], source=source if source in device_profiles.LOG_SOURCES else "journal")
    return answer if isinstance(answer, JSONResponse) else ok(text=answer.get("text", ""))


@router.get("/devices/{device_id}/history")
def device_history(device_id: int, user: users.User = Depends(api_user)):
    entries = devices.history(user.id, device_id)
    if entries is None:
        return fail(404)
    return ok(entries=[e.__dict__ for e in entries])


@router.get("/devices/{device_id}/files")
def device_files(request: Request, device_id: int, path: str = "", user: users.User = Depends(api_user)):
    guarded = _guarded(request, user, device_id)
    if isinstance(guarded, JSONResponse):
        return guarded
    answer = _broker("ls", guarded[1], path=path or ".")
    return answer if isinstance(answer, JSONResponse) else ok(path=answer["path"], entries=answer["entries"])


@router.post("/devices/{device_id}/files/{op}")
def device_file_op(request: Request, device_id: int, op: str, path: str = Form(""), to: str = Form(""),
                   text: str = Form(""), user: users.User = Depends(api_user)):
    """rename, delete (a file or an empty folder), mkdir, read (a text file), write (a text file)."""
    if op not in ("rename", "delete", "mkdir", "read", "write"):
        return fail(404)
    guarded = _guarded(request, user, device_id)
    if isinstance(guarded, JSONResponse):
        return guarded
    args = {"path": path}
    if op == "rename":
        args["to"] = to
    if op == "write":
        args["text"] = text
    answer = _broker(op, guarded[1], **args)
    if isinstance(answer, JSONResponse):
        return answer
    if op != "read":
        devices.log(device_id, user.id, f"file_{op}", "ok", path[-200:])
    return ok(text=answer.get("text", "")) if op == "read" else ok()


@router.get("/devices/{device_id}/files/get")
def device_file_get(request: Request, device_id: int, path: str = "", user: users.User = Depends(api_user)):
    """Download a file of the device: it passes through the hub and is not stored here."""
    guarded = _guarded(request, user, device_id)
    if isinstance(guarded, JSONResponse):
        return guarded
    try:
        first, lines = broker.stream("get", guarded[1], path=path)
    except broker.BrokerError as exc:
        return _bad(exc.code)
    devices.log(device_id, user.id, "file_get", "ok", f"{path[-200:]} ({first.get('size', 0)} B)")

    def body():
        for message in lines:
            if "data" in message:
                yield base64.b64decode(message["data"])
    name = path.rstrip("/").rsplit("/", 1)[-1] or "file"
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)[:120] or "file"
    return StreamingResponse(body(), media_type="application/octet-stream", headers={
        "Content-Disposition": f'attachment; filename="{safe}"', "Content-Length": str(first.get("size", 0)),
        "X-Content-Type-Options": "nosniff"})


@router.post("/devices/{device_id}/upload")
def device_file_put(request: Request, device_id: int, path: str = Form(""), file: UploadFile = File(...),
                    user: users.User = Depends(api_user)):
    guarded = _guarded(request, user, device_id)
    if isinstance(guarded, JSONResponse):
        return guarded
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size > MAX_UPLOAD:
        return _bad("too_big")
    target = path.rstrip("/") + "/" + (file.filename or "upload").replace("/", "_")

    def chunks():
        while True:
            data = file.file.read(96 * 1024)
            if not data:
                return
            yield data
    try:
        broker.upload(guarded[1], target, size, chunks())
    except broker.BrokerError as exc:
        return _bad(exc.code)
    devices.log(device_id, user.id, "file_put", "ok", f"{target[-200:]} ({size} B)")
    return ok()


def _origin_ok(origin: str | None, host: str | None) -> bool:
    """The WebSocket comes from our own page (no other site can open it with the user's cookie): its origin is the
    hub's address (HUB_BASE_URL), or, without one set (tests, local), the host it was asked on."""
    if not origin:
        return False
    got = urlsplit(origin)
    base = os.environ.get("HUB_BASE_URL", "").strip()
    if base:
        want = urlsplit(base)
        return (got.scheme, got.netloc) == (want.scheme, want.netloc)
    return bool(host) and got.netloc == host


@router.websocket("/devices/{device_id}/shell")
async def device_shell(websocket: WebSocket, device_id: int):
    """The shell: browser <-> this WebSocket <-> broker <-> SSH on the device. Text frames from the browser are JSON:
    {"in": text} or {"size": [cols, rows]}; to the browser binary frames (terminal output) and a last {"exit": n}."""
    user = users.get_user(websocket.cookies.get(COOKIE_NAME))
    if user is None or user.must_change or not _origin_ok(websocket.headers.get("origin"), websocket.headers.get("host")):
        await websocket.close(code=4401)
        return
    device = devices.get(user.id, device_id)
    if device is None or not _granted(websocket.cookies, device_id):
        await websocket.close(code=4403)
        return
    payload = devices.payload(user.id, device_id)
    await websocket.accept()
    started = time.time()
    try:
        cols = int(websocket.query_params.get("cols", "80"))
        rows = int(websocket.query_params.get("rows", "24"))
        reader, writer = await broker.open_shell(payload, cols, rows)
    except (broker.BrokerError, ValueError) as exc:
        await websocket.send_text(json.dumps({"error": getattr(exc, "code", "bad")}))
        await websocket.close()
        return
    devices.log(device_id, user.id, "shell", "open")

    async def device_to_browser():
        while True:
            line = await reader.readline()
            if not line:
                break
            message = json.loads(line)
            if "out" in message:
                await websocket.send_bytes(base64.b64decode(message["out"]))
            elif "exit" in message or message.get("ok") is False:
                await websocket.send_text(json.dumps({"exit": message.get("exit", 1), "error": message.get("error", "")}))
                break

    async def browser_to_device():
        while True:
            text = await websocket.receive_text()
            message = json.loads(text)
            if "in" in message and isinstance(message["in"], str):
                data = message["in"].encode("utf-8")[:65536]
                writer.write(json.dumps({"in": base64.b64encode(data).decode("ascii")}).encode() + b"\n")
            elif "size" in message:
                writer.write(json.dumps({"size": [int(x) for x in message["size"][:2]]}).encode() + b"\n")
            await writer.drain()

    tasks = [asyncio.ensure_future(device_to_browser()), asyncio.ensure_future(browser_to_device())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except (WebSocketDisconnect, ValueError, OSError):
        pass
    finally:
        for task in tasks:
            task.cancel()
        writer.close()
        devices.log(device_id, user.id, "shell", "closed", seconds=int(time.time() - started))
        try:
            await websocket.close()
        except RuntimeError:
            pass


# --- the owner: home network for other users' devices ---------------------------------------------------------------
@router.post("/admin/devices/{device_id}/lan")
def device_lan(device_id: int, allowed: str = Form("0"), user: users.User = Depends(api_user)):
    return ok() if devices.set_lan(user.id, device_id, allowed == "1") else fail(404)
