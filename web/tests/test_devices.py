"""Devices of a project (devices.py, vault.py): data rules, the encrypted key, the routes and the manager's context.
Needs the package `cryptography` (web image since the vault)."""
import os
import tempfile
import unittest

from app import chat, db, devices, projects, users, vault
from app.routes import devices as device_routes


class DevicesTest(unittest.TestCase):
    def setUp(self):
        from cryptography.fernet import Fernet
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.saved = os.environ.get("HUB_VAULT_KEY")
        os.environ["HUB_VAULT_KEY"] = Fernet.generate_key().decode()
        self.user = users.create_user("a@example.com", "Aaaa!pass12")
        self.project = projects.create_project(self.user.id, "Project")

    def tearDown(self):
        if self.saved is None:
            os.environ.pop("HUB_VAULT_KEY", None)
        else:
            os.environ["HUB_VAULT_KEY"] = self.saved
        self.tmp.cleanup()

    def make(self, name="Roadster", host="Roadster.local", description="Car", key=""):
        return devices.create(self.user.id, self.project.id, name, host, description, key)

    def stored(self, device_id):
        with db.connect() as conn:
            return conn.execute("SELECT key_enc FROM devices WHERE id = ?", (device_id,)).fetchone()[0]

    def test_a_device_has_name_hostname_and_description(self):
        d = self.make()
        self.assertEqual((d.name, d.hostname, d.description, d.has_key), ("Roadster", "roadster.local", "Car", False))
        self.assertEqual([x.id for x in devices.list_devices(self.user.id, self.project.id)], [d.id])

    def test_the_key_is_stored_encrypted_and_never_in_the_clear(self):
        secret = "-----BEGIN OPENSSH PRIVATE KEY-----\nabc123SECRET\n-----END OPENSSH PRIVATE KEY-----"
        d = self.make(key=secret)
        self.assertTrue(d.has_key)
        raw = self.stored(d.id)
        self.assertNotIn("SECRET", raw)
        self.assertNotIn("BEGIN", raw)
        self.assertEqual(vault.unseal(raw), secret + "\n")                  # opens with the master key, ends with a newline
        with db.connect() as conn:                                          # nowhere else in the database either
            dump = " ".join(str(tuple(r)) for r in conn.execute("SELECT * FROM devices"))
        self.assertNotIn("SECRET", dump)
        self.assertNotIn("SECRET", repr(devices.list_devices(self.user.id, self.project.id)))   # the objects do not carry it

    def test_without_a_master_key_a_key_is_refused_but_a_device_is_fine(self):
        os.environ["HUB_VAULT_KEY"] = ""
        self.assertFalse(vault.available())
        with self.assertRaises(ValueError) as ctx:
            self.make(key="secret")
        self.assertEqual(str(ctx.exception), "vault")
        self.assertEqual(devices.list_devices(self.user.id, self.project.id), [])   # nothing half-stored
        self.assertFalse(self.make().has_key)

    def test_a_wrong_master_key_does_not_open_a_key(self):
        from cryptography.fernet import Fernet
        raw = self.stored(self.make(key="secret").id)
        os.environ["HUB_VAULT_KEY"] = Fernet.generate_key().decode()
        with self.assertRaises(vault.VaultError):
            vault.unseal(raw)

    def test_update_keeps_replaces_or_removes_the_key(self):
        d = self.make(key="first")
        before = self.stored(d.id)
        devices.update(self.user.id, d.id, "Roadster", "roadster.local", "New text", key="")   # empty: keep
        self.assertEqual(self.stored(d.id), before)
        devices.update(self.user.id, d.id, "Roadster", "roadster.local", "x", key="second")
        self.assertEqual(vault.unseal(self.stored(d.id)), "second\n")
        devices.update(self.user.id, d.id, "Roadster", "roadster.local", "x", key="third", remove_key=True)
        self.assertEqual(self.stored(d.id), "")                                                # removing wins
        self.assertFalse(devices.list_devices(self.user.id, self.project.id)[0].has_key)

    def test_bad_input_is_refused(self):
        for args, code in ((("", "host"), "name"), (("N" * (devices.MAX_NAME + 1), "host"), "name"),
                           (("A", ""), "hostname"), (("A", "http://host"), "hostname"), (("A", "ho st"), "hostname"),
                           (("A", "host:22"), "hostname"), (("A", "-host"), "hostname")):
            with self.assertRaises(ValueError, msg=args) as ctx:
                devices.create(self.user.id, self.project.id, *args)
            self.assertEqual(str(ctx.exception), code)
        for kw, code in (({"description": "x" * (devices.MAX_DESCRIPTION + 1)}, "description"),
                         ({"key": "x" * (devices.MAX_KEY + 1)}, "key")):
            with self.assertRaises(ValueError) as ctx:
                devices.create(self.user.id, self.project.id, "A", "host", **kw)
            self.assertEqual(str(ctx.exception), code)
        self.assertEqual(devices.list_devices(self.user.id, self.project.id), [])

    def test_names_are_unique_per_project_and_the_list_is_limited(self):
        self.make("Roadster")
        with self.assertRaises(ValueError) as ctx:
            self.make("roadster", "other.local")
        self.assertEqual(str(ctx.exception), "duplicate")
        other = devices.create(self.user.id, self.project.id, "Heater", "heater.local")
        with self.assertRaises(ValueError):
            devices.update(self.user.id, other.id, "ROADSTER", "heater.local")
        for n in range(devices.MAX_PER_PROJECT - 2):
            devices.create(self.user.id, self.project.id, f"D{n}", "h.local")
        with self.assertRaises(ValueError) as ctx:
            self.make("One too many")
        self.assertEqual(str(ctx.exception), "limit")

    def test_delete(self):
        d = self.make()
        self.assertTrue(devices.delete(self.user.id, d.id))
        self.assertFalse(devices.delete(self.user.id, d.id))
        self.assertEqual(devices.list_devices(self.user.id, self.project.id), [])

    def test_deleting_the_project_deletes_its_devices_and_keys(self):
        d = self.make(key="secret")
        projects.delete_project(self.user.id, self.project.id)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0], 0)

    def test_routes_answer_with_codes_and_never_return_the_key(self):
        created = device_routes.create_device(self.project.id, "Heater", "heater.local", "Garage", "topsecret", self.user)
        self.assertTrue(created["ok"])
        self.assertNotIn("topsecret", str(created))
        bad = device_routes.create_device(self.project.id, "", "heater.local", "", "", self.user)
        self.assertEqual((bad.status_code, bad.body), (400, b'{"ok":false,"error":"name"}'))
        gone = device_routes.delete_device(created["id"] + 99, self.user)
        self.assertEqual(gone.status_code, 404)

    def test_the_manager_knows_the_devices_but_never_the_keys(self):
        self.make("Roadster", "roadster.local", "Car computer", key="topsecret")
        with db.connect() as conn:
            conn.execute("INSERT INTO chat_messages (user_id, project_id, prompt, status, created_at) VALUES (?, ?, 'hi', 'queued', 1)",
                         (self.user.id, self.project.id))
            row = conn.execute("SELECT * FROM chat_messages").fetchone()
            text = chat.build_input(conn, row)
        self.assertIn("Roadster (roadster.local): Car computer", text)
        self.assertNotIn("topsecret", text)
        self.assertNotIn(self.stored(1), text)


if __name__ == "__main__":
    unittest.main()
