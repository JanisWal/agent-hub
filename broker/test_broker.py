"""The broker (broker.py) against a real SSH server made with asyncssh in the test: host key, login with key and
password, the system test, actions as jobs, logs, files over SFTP, the shell, and the rules (targets, origin, token).
Runs in the broker image: python -m unittest broker.test_broker"""
import asyncio
import base64
import json
import os
import tempfile
import unittest

import asyncssh
import pyrage

from . import broker as B

OS_RELEASE = 'Linux\nPRETTY_NAME="Debian GNU/Linux 13"\nID=debian\n'


class FakeServer(asyncssh.SSHServer):
    def begin_auth(self, username):
        return True

    def password_auth_supported(self):
        return True

    def validate_password(self, username, password):
        return username == "pi" and password == "pw"


async def handle(process: asyncssh.SSHServerProcess):
    command = process.command or ""
    COMMANDS.append(command)
    if command is None or command == "":
        process.stdout.write("$ ")
        data = await process.stdin.read(5)
        process.stdout.write(f"got:{data}")
        process.exit(0)
        return
    if command.startswith("uname"):
        process.stdout.write(OS_RELEASE)
    elif "updates" in command or "upgradable" in command:
        process.stdout.write("AGENTHUB_UPDATES=3\n")
    elif "journalctl" in command:
        process.stdout.write("boot ok\n")
    elif command.startswith("sudo -S"):
        password = (await process.stdin.readline()).strip()
        if password != "pw":
            process.stderr.write("sudo: a password is required\n")
            process.exit(1)
            return
    process.exit(0)


COMMANDS: list[str] = []


class BrokerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.identity = pyrage.x25519.Identity.generate()
        os.environ["HUB_VAULT_IDENTITY"] = str(self.identity)
        os.environ["HUB_BROKER_TOKEN"] = "token-1"
        self.host_key = asyncssh.generate_private_key("ssh-ed25519")
        self.client_key = asyncssh.generate_private_key("ssh-ed25519")
        authorized = asyncssh.import_authorized_keys(self.client_key.export_public_key().decode())
        root = self.tmp.name
        self.server = await asyncssh.create_server(
            FakeServer, "127.0.0.1", 0, server_host_keys=[self.host_key], authorized_client_keys=authorized,
            process_factory=handle, sftp_factory=lambda chan: asyncssh.SFTPServer(chan, chroot=root))
        self.port = self.server.sockets[0].getsockname()[1]
        self.saved_allowed = B.allowed
        B.allowed = lambda address, lan_ok, networks=None: True    # the test server is on loopback
        COMMANDS.clear()
        B.JOBS.clear()

    async def asyncTearDown(self):
        B.allowed = self.saved_allowed
        self.server.close()
        self.tmp.cleanup()

    def device(self, **kw):
        d = {"id": 1, "host": "127.0.0.1", "ip": "127.0.0.1", "port": self.port, "user": "pi", "auth": "key",
             "secret": B.seal(self.client_key.export_private_key().decode()),
             "host_key": self.host_key.export_public_key().decode(), "pinned_ip": "", "lan_ok": True,
             "family": "debian", "ai_password": False}
        d.update(kw)
        return d

    async def ask(self, op, device=None, origin="human", token="token-1", follow=(), **args):
        """One request through the real server loop; returns all answer lines."""
        server = await asyncio.start_server(B.handle, "127.0.0.1", 0, limit=B.MAX_LINE + 1024)
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port, limit=B.MAX_LINE + 1024)
        writer.write(json.dumps({"token": token, "op": op, "device": device or {}, "origin": origin,
                                 "args": args}).encode() + b"\n")
        for line in follow:
            writer.write(json.dumps(line).encode() + b"\n")
        await writer.drain()
        lines = []
        while True:
            line = await asyncio.wait_for(reader.readline(), 20)
            if not line:
                break
            lines.append(json.loads(line))
        writer.close()
        server.close()
        return lines

    async def test_the_token_is_needed(self):
        self.assertEqual((await self.ask("online", self.device(), token="wrong"))[0], {"ok": False, "error": "token"})

    async def test_hostkey_reads_the_key_without_login(self):
        answer = (await self.ask("hostkey", self.device(host_key="")))[0]
        self.assertTrue(answer["ok"])
        self.assertEqual(answer["fingerprint"], self.host_key.get_fingerprint("sha256"))
        self.assertEqual(COMMANDS, [])

    async def test_no_connection_without_or_with_a_wrong_host_key(self):
        self.assertEqual((await self.ask("test", self.device(host_key="")))[0]["error"], "host_key_unknown")
        other = asyncssh.generate_private_key("ssh-ed25519").export_public_key().decode()
        self.assertEqual((await self.ask("test", self.device(host_key=other)))[0]["error"], "host_key_changed")

    async def test_the_test_finds_the_system_with_a_key_and_with_a_password(self):
        answer = (await self.ask("test", self.device()))[0]
        self.assertEqual((answer["family"], answer["name"], answer["sudo"]), ("debian", "Debian GNU/Linux 13", True))
        answer = (await self.ask("test", self.device(auth="password", secret=B.seal("pw"))))[0]
        self.assertTrue(answer["ok"])
        self.assertTrue(any(c.startswith("sudo -S -p ''") for c in COMMANDS))     # the password goes on stdin
        self.assertEqual((await self.ask("test", self.device(auth="password", secret=B.seal("bad"))))[0]["error"], "auth")

    async def test_an_action_runs_as_a_job_with_the_profile_command(self):
        self.assertTrue((await self.ask("start", self.device(), action="updates_check", key="d1"))[0]["ok"])
        for _ in range(50):
            job = (await self.ask("job", key="d1"))[0]
            if job["state"] != "running":
                break
            await asyncio.sleep(0.1)
        self.assertEqual((job["state"], job["result"]), ("done", {"count": 3}))
        self.assertTrue(any(c.startswith("sudo -n /usr/bin/apt-get update -qq") for c in COMMANDS))
        self.assertEqual((await self.ask("start", self.device(), action="rm -rf /", key="d1"))[0]["error"], "bad")

    async def test_the_ai_never_gets_shell_files_logs_or_a_password(self):
        for op in ("shell", "ls", "get", "logs", "keygen", "test"):
            self.assertEqual((await self.ask(op, self.device(), origin="ai"))[0]["error"], "not_allowed", op)
        device = self.device(auth="password", secret=B.seal("pw"))
        self.assertEqual((await self.ask("start", device, origin="ai", action="reboot", key="d2"))[0]["error"], "not_allowed")
        device["ai_password"] = True
        self.assertTrue((await self.ask("start", device, origin="ai", action="reboot", key="d2"))[0]["ok"])

    async def test_logs_files_and_shell(self):
        self.assertEqual((await self.ask("logs", self.device(), source="journal"))[0]["text"], "boot ok\n")
        self.assertTrue((await self.ask("write", self.device(), path="/note.txt", text="hello"))[0]["ok"])
        listing = (await self.ask("ls", self.device(), path="/"))[0]
        self.assertIn({"name": "note.txt", "kind": "file", "size": 5}, [{k: e[k] for k in ("name", "kind", "size")} for e in listing["entries"]])
        self.assertEqual((await self.ask("read", self.device(), path="/note.txt"))[0]["text"], "hello")
        lines = await self.ask("get", self.device(), path="/note.txt")
        self.assertEqual(base64.b64decode(lines[1]["data"]), b"hello")
        data = base64.b64encode(b"abc").decode()
        put = await self.ask("put", self.device(), path="/up.bin", size=3, follow=({"data": data}, {"end": True}))
        self.assertEqual(put[-1], {"ok": True, "size": 3})
        self.assertTrue((await self.ask("mkdir", self.device(), path="/d"))[0]["ok"])
        self.assertTrue((await self.ask("delete", self.device(), path="/d"))[0]["ok"])
        self.assertEqual((await self.ask("delete", self.device(), path="/nothing"))[0]["error"], "missing")
        shell = await self.ask("shell", self.device(), size=[80, 24],
                               follow=({"in": base64.b64encode(b"hello").decode()},))
        self.assertTrue(shell[0]["ok"])
        out = b"".join(base64.b64decode(m["out"]) for m in shell if "out" in m)
        self.assertIn(b"got:hello", out)
        self.assertIn("exit", shell[-1])

    async def test_keygen_seals_the_private_part(self):
        answer = (await self.ask("keygen"))[0]
        self.assertTrue(answer["public"].startswith("ssh-ed25519 "))
        self.assertIn("PRIVATE KEY", B.unseal(answer["sealed"]))
        self.assertNotIn("PRIVATE", json.dumps(answer).replace(answer["sealed"], ""))


class RulesTest(unittest.TestCase):
    def test_targets(self):
        import ipaddress
        nets = [ipaddress.ip_network("172.18.0.0/16"), ipaddress.ip_network("172.18.0.1/32")]
        allowed = lambda a, lan=False: B.allowed(a, lan, nets)
        self.assertFalse(allowed("127.0.0.1", True))
        self.assertFalse(allowed("::1", True))
        self.assertFalse(allowed("169.254.1.1", True))
        self.assertFalse(allowed("172.18.0.5", True))            # the Docker network of the services
        self.assertFalse(allowed("224.0.0.1", True))
        self.assertFalse(allowed("192.168.178.20"))              # home network without the owner's approval
        self.assertTrue(allowed("192.168.178.20", True))
        self.assertTrue(allowed("100.101.1.2"))                  # Tailscale
        self.assertTrue(allowed("8.8.8.8"))
        self.assertFalse(allowed("::ffff:127.0.0.1", True))
        self.assertFalse(allowed("not an ip", True))

    def test_pinned_address_and_bad_secret(self):
        async def run():
            device = {"host": "localhost", "pinned_ip": "10.9.9.9", "lan_ok": True}
            with self.assertRaises(B.BrokerError) as ctx:
                await B.target(device)
            self.assertEqual(ctx.exception.code, "address_changed")
        asyncio.run(run())
        os.environ["HUB_VAULT_IDENTITY"] = str(pyrage.x25519.Identity.generate())
        with self.assertRaises(B.BrokerError):
            B.unseal("plain text")


if __name__ == "__main__":
    unittest.main()
