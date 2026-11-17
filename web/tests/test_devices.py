"""Devices of a project (devices.py, vault.py, device_profiles.py, routes/devices.py): data rules, the sealed secret,
the broker's side with a fake broker, the password and the grant, the AI's limits, the owner's approval, the manager's
inventory. Needs the package `pyrage` (web image)."""
import base64
import os
import re
import tempfile
import unittest
from types import SimpleNamespace

import pyrage

from app import broker, chat, db, device_profiles, devicepage, devices, projects, users, vault
from app.routes import devices as R


class FakeRequest:
    def __init__(self, token="cookie-a"):
        self.cookies = {"session": token}
        self.headers = {}
        self.client = SimpleNamespace(host="10.0.0.9")


class DevicesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.identity = pyrage.x25519.Identity.generate()
        self.saved = os.environ.get("HUB_VAULT_PUBLIC")
        os.environ["HUB_VAULT_PUBLIC"] = str(self.identity.to_public())
        self.user = users.create_user("a@example.com", "Aaaa!pass12")
        self.project = projects.create_project(self.user.id, "Project")
        self.calls = []
        self.answers = {}
        self._call = broker.call
        broker.call = self.fake_call
        os.environ["HUB_BROKER_URL"], os.environ["HUB_BROKER_TOKEN"] = "broker:7000", "t"
        R._grants.clear(); R._pending.clear(); R._online.clear(); R._seen_jobs.clear()

    def tearDown(self):
        broker.call = self._call
        for name in ("HUB_BROKER_URL", "HUB_BROKER_TOKEN"):
            os.environ.pop(name, None)
        if self.saved is None:
            os.environ.pop("HUB_VAULT_PUBLIC", None)
        else:
            os.environ["HUB_VAULT_PUBLIC"] = self.saved
        self.tmp.cleanup()

    def fake_call(self, op, device=None, origin="human", **args):
        self.calls.append((op, device, args))
        answer = self.answers.get(op, {})
        if isinstance(answer, Exception):
            raise answer
        return {"ok": True, **answer}

    def make(self, name="Roadster", host="Roadster.local", description="Car", key="", **kw):
        return devices.create(self.user.id, self.project.id, name, host, description, key, **kw)

    def stored(self, device_id):
        with db.connect() as conn:
            return conn.execute("SELECT key_enc FROM devices WHERE id = ?", (device_id,)).fetchone()[0]

    def opened(self, sealed):
        self.assertTrue(sealed.startswith("age:"))
        return pyrage.decrypt(base64.b64decode(sealed[4:]), [self.identity]).decode()

    # --- data ---------------------------------------------------------------------------------------------------------
    def test_a_device_has_name_hostname_description_login(self):
        d = self.make(ssh_user="pi", ssh_port="2222")
        self.assertEqual((d.name, d.hostname, d.description, d.has_key, d.ssh_user, d.ssh_port, d.auth),
                         ("Roadster", "roadster.local", "Car", False, "pi", 2222, "key"))
        self.assertEqual([x.id for x in devices.list_devices(self.user.id, self.project.id)], [d.id])
        for bad, code in (({"ssh_user": "a b"}, "user"), ({"ssh_port": "70000"}, "port"), ({"ssh_port": "x"}, "port"),
                          ({"auth": "token"}, "auth"), ({"kind": "toaster"}, "kind"), ({"ip": "999.1.1.1"}, "ip")):
            with self.assertRaises(ValueError) as ctx:
                devices.create(self.user.id, self.project.id, "X", "x.local", **bad)
            self.assertEqual(str(ctx.exception), code)

    def test_pictures_by_kind_and_by_what_it_is_for(self):
        self.assertEqual(devices.icon_for("raspberry_pi"), "dev_pi")
        self.assertEqual(devices.icon_for("microcontroller"), "dev_chip")
        self.assertEqual(devices.icon_for("linux_server"), "dev_server_linux")
        self.assertEqual(devices.icon_for("windows_server"), "dev_server_windows")
        self.assertEqual(devices.icon_for("windows_pc"), "dev_pc_windows")
        self.assertEqual(devices.icon_for("linux_pc"), "dev_linux")
        self.assertEqual(devices.icon_for("raspberry_pi", "Küche", "wird mein Display"), "dev_display")   # its use wins
        self.assertEqual(devices.icon_for("other", "Backup server"), "dev_server_linux")
        self.assertEqual(devices.icon_for("other", "Thing"), "dev_box")
        from app import icons
        for kind in devices.KINDS:
            self.assertIn(devices.KIND_ICON[kind], icons.ICONS)
        for _, picture in devices.CONTEXT_ICON:
            self.assertIn(picture, icons.ICONS)

    def test_the_secret_is_sealed_with_the_public_key_only(self):
        secret = "-----BEGIN OPENSSH PRIVATE KEY-----\nabc123SECRET\n-----END OPENSSH PRIVATE KEY-----"
        d = self.make(key=secret)
        raw = self.stored(d.id)
        self.assertNotIn("SECRET", raw)
        self.assertEqual(self.opened(raw), secret + "\n")       # only the broker's private key opens it
        self.assertFalse(hasattr(vault, "unseal"))                # the web service can not open anything
        with db.connect() as conn:
            dump = " ".join(str(tuple(r)) for r in conn.execute("SELECT * FROM devices"))
        self.assertNotIn("SECRET", dump)
        self.assertNotIn("SECRET", repr(devices.list_devices(self.user.id, self.project.id)))
        p = devices.create(self.user.id, self.project.id, "Box", "box.local", key="pass word!", auth="password")
        self.assertEqual(self.opened(self.stored(p.id)), "pass word!")
        with self.assertRaises(ValueError):
            devices.create(self.user.id, self.project.id, "Box2", "box.local", key="two\nlines", auth="password")

    def test_without_a_public_key_nothing_secret_is_stored(self):
        os.environ["HUB_VAULT_PUBLIC"] = ""
        self.assertFalse(vault.available())
        with self.assertRaises(ValueError) as ctx:
            self.make(key="secret")
        self.assertEqual(str(ctx.exception), "vault")
        self.assertFalse(self.make().has_key)

    def test_update_keeps_replaces_removes_and_forgets_the_host_key_on_a_new_address(self):
        d = self.make(key="first")
        before = self.stored(d.id)
        devices.update(self.user.id, d.id, "Roadster", "roadster.local", "New", key="")
        self.assertEqual(self.stored(d.id), before)
        devices.trust_host(self.user.id, d.id, "ssh-ed25519 AAAA", "SHA256:abc", "192.168.1.5")
        devices.update(self.user.id, d.id, "Roadster", "roadster.local", "x", key="second")
        self.assertEqual(self.opened(self.stored(d.id)), "second\n")
        self.assertTrue(devices.get(self.user.id, d.id).trusted)                 # same address: still trusted
        devices.update(self.user.id, d.id, "Roadster", "other.local", "x")
        self.assertFalse(devices.get(self.user.id, d.id).trusted)                # new address: confirm again
        devices.update(self.user.id, d.id, "Roadster", "other.local", "x", auth="password")
        self.assertEqual(self.stored(d.id), "")                                  # a key is no password
        devices.update(self.user.id, d.id, "Roadster", "other.local", "x", key="pw", auth="password")
        devices.update(self.user.id, d.id, "Roadster", "other.local", "x", remove_key=True)
        self.assertEqual(self.stored(d.id), "")

    def test_names_unique_list_limited_delete_and_project_deletion(self):
        self.make("Roadster")
        with self.assertRaises(ValueError) as ctx:
            self.make("roadster", "other.local")
        self.assertEqual(str(ctx.exception), "duplicate")
        d = self.make("Heater", key="secret")
        devices.log(d.id, self.user.id, "test", "ok")
        projects.delete_project(self.user.id, self.project.id)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM device_log").fetchone()[0], 0)

    # --- the AI and the owner -------------------------------------------------------------------------------------------
    def test_the_ai_only_what_was_ticked_and_a_password_only_when_allowed(self):
        d = self.make(ssh_user="pi")
        devices.trust_host(self.user.id, d.id, "ssh-ed25519 AAAA", "SHA256:abc", "192.168.1.5")
        devices.set_system(self.user.id, d.id, "debian", "Debian 13", True)
        self.assertFalse(devices.ai_may(self.user.id, d.id, "reboot"))          # nothing ticked
        devices.set_ai(self.user.id, d.id, ["reboot", "shell", "updates_check"], False)
        self.assertEqual(devices.get(self.user.id, d.id).ai_actions, ("reboot", "updates_check"))   # no "shell"
        self.assertTrue(devices.ai_may(self.user.id, d.id, "reboot"))
        self.assertFalse(devices.ai_may(self.user.id, d.id, "poweroff"))
        devices.update(self.user.id, d.id, "Roadster", "roadster.local", "Car", key="pw", auth="password")
        self.assertFalse(devices.ai_may(self.user.id, d.id, "reboot"))          # a password is for the human
        self.assertIsNone(devices.payload(self.user.id, d.id, "ai"))
        devices.set_ai(self.user.id, d.id, ["reboot"], True)
        self.assertTrue(devices.ai_may(self.user.id, d.id, "reboot"))           # ... unless the user allowed it
        self.assertIsNotNone(devices.payload(self.user.id, d.id, "ai"))

    def test_home_network_only_for_the_owners_devices(self):
        owner = users.create_user("o@example.com", "Oooo!pass12", role="owner")
        mine = devices.create(owner.id, projects.create_project(owner.id, "O").id, "Pi", "pi.local")
        self.assertTrue(mine.lan_ok)                                           # the owner's own devices
        self.assertFalse(self.make().lan_ok)                                   # nobody else's

    def test_the_manager_knows_the_inventory_but_never_keys_or_logins(self):
        d = self.make("Roadster", "roadster.local", "Car computer", key="topsecret", kind="raspberry_pi", ssh_user="pi")
        devices.trust_host(self.user.id, d.id, "ssh-ed25519 HOSTKEYAAAA", "SHA256:fingerprint", "192.168.1.5")
        devices.set_ip_hint(self.user.id, d.id, "192.168.1.5")
        devices.set_system(self.user.id, d.id, "debian", "Raspberry Pi OS", True)
        with db.connect() as conn:
            conn.execute("INSERT INTO chat_messages (user_id, project_id, prompt, status, created_at) VALUES (?, ?, 'hi', 'queued', 1)",
                         (self.user.id, self.project.id))
            text = chat.build_input(conn, conn.execute("SELECT * FROM chat_messages").fetchone())
        self.assertIn("- Roadster: raspberry pi, host roadster.local, IP 192.168.1.5 (found for the hostname), runs "
                      "Raspberry Pi OS; Car computer", text)
        for secret in ("topsecret", self.stored(d.id), "HOSTKEY", "fingerprint"):
            self.assertNotIn(secret, text)

    # --- profiles ---------------------------------------------------------------------------------------------------------
    def test_profiles_detect_sudoers_and_guide(self):
        self.assertEqual(device_profiles.detect('Linux\nID=raspbian\nID_LIKE=debian\nPRETTY_NAME="Raspbian 12"\n')[0], "debian")
        self.assertEqual(device_profiles.detect('Linux\nID=rocky\nPRETTY_NAME="Rocky 9"\n'), ("fedora", "Rocky 9"))
        self.assertEqual(device_profiles.detect("Darwin\nProductVersion:\t15.1\n"), ("macos", "macOS 15.1"))
        self.assertEqual(device_profiles.detect("x", "Microsoft Windows [Version 10.0.22631]")[0], "windows")
        self.assertEqual(device_profiles.detect("Linux\nID=gentoo\n")[0], "")         # unknown: no buttons
        rule = device_profiles.sudoers("debian", "pi")
        self.assertTrue(rule.startswith("pi ALL=(root) NOPASSWD: /usr/bin/systemctl reboot, "))
        self.assertIn(r"Dpkg\:\:Options\:\:\=--force-confdef", rule)               # sudoers specials escaped
        self.assertEqual(device_profiles.sudoers("debian", "bad user"), "")
        self.assertEqual(device_profiles.supported("windows"), ("reboot", "poweroff"))
        self.assertEqual(device_profiles.count_updates("x\nAGENTHUB_UPDATES=7\n"), 7)
        steps = dict(device_profiles.guide("debian", "pi", "ssh-ed25519 AAAAC3Nz agent-hub", "pi.local"))
        self.assertIn("ssh-ed25519 AAAAC3Nz agent-hub", steps["key"])
        self.assertIn("visudo -c", steps["sudoers"])
        self.assertEqual(dict(device_profiles.guide("debian", "pi", "ssh-ed25519 AA; rm -rf /", "x"))["key"], "")   # no odd keys
        for family in device_profiles.FAMILIES:   # every command of a button is in the sudoers rule
            for action in ("reboot", "poweroff", "updates_install"):
                command = device_profiles.command(family, action)
                if command and "{sudo}" in command and device_profiles.PROFILES[family]["sudo"]:
                    first = re.split(r" 2>| \||&&|;", command.split("{sudo}")[1])[0].strip()
                    self.assertIn(first, device_profiles.PROFILES[family]["sudo"], (family, action))

    # --- routes with the fake broker ----------------------------------------------------------------------------------------
    def ready(self, **kw):
        d = self.make(ssh_user="pi", **kw)
        devices.trust_host(self.user.id, d.id, "ssh-ed25519 AAAA", "SHA256:abc", "192.168.1.5")
        devices.set_system(self.user.id, d.id, "debian", "Debian", True)
        return d

    def test_routes_answer_with_codes_and_never_return_the_secret(self):
        created = R.create_device(self.project.id, "Heater", "heater.local", "Garage", "topsecret", "other", "", user=self.user)
        self.assertTrue(created["ok"])
        bad = R.create_device(self.project.id, "", "heater.local", "", "", "other", "", user=self.user)
        self.assertEqual((bad.status_code, bad.body), (400, b'{"ok":false,"error":"name"}'))
        info = R.device_info(created["id"], user=self.user)["device"]
        self.assertTrue(info["has_key"])
        self.assertNotIn("topsecret", str(info))
        self.assertNotIn(self.stored(created["id"]), str(info))
        self.assertEqual(R.delete_device(created["id"] + 99, self.user).status_code, 404)

    def test_host_key_is_read_then_trusted_only_as_read(self):
        d = self.make()
        self.answers["hostkey"] = {"key": "ssh-ed25519 KEY", "fingerprint": "SHA256:good", "address": "192.168.1.5"}
        answer = R.device_hostkey(d.id, user=self.user)
        self.assertEqual((answer["fingerprint"], answer["same"]), ("SHA256:good", False))
        self.assertEqual(R.device_trust(d.id, "SHA256:evil", user=self.user).status_code, 400)
        self.assertTrue(R.device_trust(d.id, "SHA256:good", user=self.user)["ok"])
        d = devices.get(self.user.id, d.id)
        self.assertEqual((d.host_fp, d.pinned_ip, d.ip_hint), ("SHA256:good", "192.168.1.5", "192.168.1.5"))
        self.assertEqual(R.device_trust(d.id, "SHA256:good", user=self.user).status_code, 400)   # used once

    def test_test_keeps_the_system_and_keygen_shows_only_the_public_part(self):
        d = self.ready()
        self.answers["test"] = {"family": "debian", "name": "Raspberry Pi OS", "sudo": False}
        self.assertTrue(R.device_test(d.id, user=self.user)["ok"])
        self.assertEqual(devices.get(self.user.id, d.id).sudo_ok, False)
        sealed = vault.seal("PRIVATE")
        self.answers["keygen"] = {"sealed": sealed, "public": "ssh-ed25519 AAAAPUB agent-hub"}
        self.assertEqual(R.device_keygen(d.id, user=self.user)["public"], "ssh-ed25519 AAAAPUB agent-hub")
        self.assertEqual(self.stored(d.id), sealed)
        self.answers["keygen"] = {"sealed": "PLAINTEXT", "public": "ssh-ed25519 AAAA"}
        self.assertEqual(R.device_keygen(d.id, user=self.user).status_code, 400)           # never stores clear text

    def test_the_buttons_need_no_password(self):
        d = self.ready()
        self.assertTrue(R.device_action(FakeRequest(), d.id, "reboot", "", user=self.user)["ok"])
        self.assertTrue(R.device_action(FakeRequest(), d.id, "update", "", user=self.user)["ok"])
        self.assertEqual(self.calls[-1][2]["action"], "updates_check")
        devices.set_updates(self.user.id, d.id, found=3)
        self.assertEqual(R.device_action(FakeRequest(), d.id, "update", "", user=self.user)["action"], "updates_install")
        self.assertEqual(R.device_action(FakeRequest(), d.id, "toast", "", user=self.user).status_code, 400)

    def test_state_takes_a_finished_job_over_once(self):
        d = self.ready()
        self.answers["online"] = {"online": True}
        self.answers["job"] = {"state": "done", "action": "updates_check", "result": {"count": 4}, "started": 10, "finished": 20}
        state = R.device_state(d.id, user=self.user)
        self.assertEqual((state["online"], state["updates"]), (True, 4))
        R.device_state(d.id, user=self.user)
        self.assertEqual(len(devices.history(self.user.id, d.id)), 1)                    # logged once

    def test_shell_files_and_logs_need_the_grant(self):
        d = self.ready()
        self.answers["logs"] = {"text": "boot ok"}
        self.answers["ls"] = {"path": "/home/pi", "entries": []}
        denied = R.device_logs(FakeRequest(), d.id, "journal", user=self.user)
        self.assertEqual((denied.status_code, denied.body), (403, b'{"ok":false,"error":"grant"}'))
        self.assertEqual(R.device_grant(FakeRequest(), d.id, "nope", user=self.user).status_code, 403)
        self.assertTrue(R.device_grant(FakeRequest(), d.id, "Aaaa!pass12", user=self.user)["ok"])
        self.assertEqual(R.device_logs(FakeRequest(), d.id, "journal", user=self.user)["text"], "boot ok")
        self.assertEqual(R.device_files(FakeRequest(), d.id, "", user=self.user)["path"], "/home/pi")
        self.assertEqual(R.device_logs(FakeRequest("other-login"), d.id, "journal", user=self.user).status_code, 403)
        self.assertEqual(R.device_file_op(FakeRequest(), d.id, "chmod", user=self.user).status_code, 404)

    def test_the_shell_socket_checks_the_origin(self):
        os.environ["HUB_BASE_URL"] = "https://hub.example.com"
        try:
            self.assertTrue(R._origin_ok("https://hub.example.com", "x"))
            self.assertFalse(R._origin_ok("https://evil.example.com", "hub.example.com"))
            self.assertFalse(R._origin_ok(None, "hub.example.com"))
        finally:
            os.environ.pop("HUB_BASE_URL")
        self.assertTrue(R._origin_ok("http://127.0.0.1:8000", "127.0.0.1:8000"))

    def test_the_tile_shows_led_buttons_and_the_suggested_address(self):
        d = self.ready()
        devices.set_ip_hint(self.user.id, d.id, "192.168.1.5")
        html = devicepage.tile("de", devices.list_devices(self.user.id, self.project.id))
        self.assertIn('class="dev-led"', html)
        self.assertIn('data-btn="power"', html)
        self.assertIn('<span class="dev-hint"', html)
        self.assertNotIn('data-btn="update" aria-label="Updates" data-tip="Updates" disabled', html)
        plain = self.make("Plain", "plain.local")
        html = devicepage.row("de", devices.get(self.user.id, plain.id))
        self.assertIn("disabled", html)                                                  # nothing works before trust
        self.assertIn("Diesen Namen", devicepage.dialogs("de"))


if __name__ == "__main__":
    unittest.main()
