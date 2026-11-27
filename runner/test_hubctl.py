"""The fixed actions on the server (runner/hubctl.py): backup, checking and putting back a backup, settings in .env.
Real files and real age encryption in throwaway folders; Docker Compose is replaced by a recorder.

    docker run --rm -v "$PWD/runner:/app/runner" agent-hub-hub-runner python -m unittest runner.test_hubctl
"""
import datetime
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import pyrage

from runner import hubctl


def make_db(path: Path, owner: str = "owner@example.com", projects: int = 2) -> None:
    conn = sqlite3.connect(path)
    conn.executescript("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, role TEXT, deleted_at INTEGER);"
                       "CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT);"
                       "CREATE TABLE files (id INTEGER PRIMARY KEY, is_folder INTEGER);")
    conn.execute("INSERT INTO users (email, role) VALUES (?, 'owner')", (owner,))
    conn.execute("INSERT INTO users (email, role) VALUES ('friend@example.com', 'user')")
    conn.executemany("INSERT INTO projects (name) VALUES (?)", [(f"p{i}",) for i in range(projects)])
    conn.execute("INSERT INTO files (is_folder) VALUES (0)")
    conn.commit()
    conn.close()


class HubctlTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.env = {"HUB_BASE_DIR": str(base), "HUB_APP_DIR": str(base / "app"), "HUB_DATA_DIR": str(base / "data"),
                    "HUB_CLAUDE_DIR": str(base / "claude"), "HUB_WORK_DIR": str(base / "work"),
                    "HUB_BACKUP_DIR": str(base / "backups"), "HUB_NAME": "agent-hub"}
        self.paths = hubctl.Paths(self.env)
        for folder in ("app", "data/files/1", "claude/1", "claude/keys", "work/repos/3.git", "work/tasks/9"):
            (base / folder).mkdir(parents=True)
        make_db(self.paths.data / "hub.db")
        (self.paths.data / "files" / "1" / "5").write_bytes(b"a picture")
        (self.paths.claude / "1" / "token.enc").write_bytes(b"sealed token")
        (self.paths.claude / "keys" / "mistral-1.enc").write_bytes(b"sealed key")
        (self.paths.work / "repos" / "3.git" / "HEAD").write_text("ref: refs/heads/main\n")
        (self.paths.work / "tasks" / "9" / "half.py").write_text("work in progress")
        (self.paths.app / ".env").write_text("# hub\nHUB_TOKEN_KEY=old-key\nRUNNER_TOKEN=device-token\n"
                                             "HUB_BASE_URL=https://hub.example.de\nHUB_PORT=8080\n")
        self.secret = pyrage.x25519.Identity.generate()
        self.calls = []
        patcher = mock.patch.object(hubctl, "compose", side_effect=lambda paths, *args: self.calls.append(args))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def backup(self) -> Path:
        made = hubctl.make_backup(self.paths, str(self.secret.to_public()), now=datetime.datetime(2026, 11, 27, 3, 15).timestamp())
        return self.paths.backups / made["name"]

    def upload(self, path: Path) -> Path:
        target = self.paths.data / "restore" / "upload.age"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        return target

    def change_everything(self) -> None:
        (self.paths.data / "hub.db").unlink()
        make_db(self.paths.data / "hub.db", owner="other@example.com", projects=7)
        (self.paths.data / "files" / "1" / "5").write_bytes(b"changed")
        (self.paths.claude / "1" / "token.enc").write_bytes(b"other token")
        (self.paths.app / ".env").write_text("HUB_TOKEN_KEY=new-key\nRUNNER_TOKEN=device-token\nHUB_PORT=8080\n")

    # --- backup
    def test_a_backup_is_an_encrypted_zip_with_the_fixed_layout(self):
        path = self.backup()
        self.assertEqual(path.name, "agent-hub-backup-2026-11-27-0315.zip.age")
        raw = path.read_bytes()
        self.assertFalse(raw.startswith(b"PK"))                           # not a readable ZIP on the drive
        for secret in (b"old-key", b"sealed token", b"a picture"):
            self.assertNotIn(secret, raw)
        out = Path(self.tmp.name) / "open.zip"
        pyrage.decrypt_file(str(path), str(out), [self.secret])             # = age -d -i key.txt
        with zipfile.ZipFile(out) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("manifest.json"))
            secrets_env = archive.read("secrets.env").decode()
        self.assertEqual(names, {"manifest.json", "database/hub.db", "files/1/5", "repos/3.git/HEAD", "logins/1/token.enc",
                                 "logins/keys/mistral-1.enc", "secrets.env"})
        self.assertEqual((manifest["format"], manifest["version"]), ("agent-hub-backup", 1))
        self.assertEqual(manifest["counts"], {"users": 2, "projects": 2, "files": 1})
        self.assertEqual(manifest["files"]["files/1/5"]["sha256"], hashlib.sha256(b"a picture").hexdigest())
        self.assertIn("HUB_TOKEN_KEY=old-key", secrets_env)
        self.assertNotIn("RUNNER_TOKEN", secrets_env)                       # belongs to the device
        self.assertNotIn("HUB_PORT", secrets_env)
        self.assertFalse(any(n.startswith("tasks/") or "half.py" in n for n in names))   # work in progress stays out
        self.assertEqual(list(self.paths.jobs.glob("backup*")), [])         # nothing unencrypted left behind

    def test_files_that_are_packed_already_are_only_stored(self):
        conn = sqlite3.connect(self.paths.data / "hub.db")
        conn.execute("ALTER TABLE files ADD COLUMN project_id INTEGER")
        conn.execute("ALTER TABLE files ADD COLUMN name TEXT")
        conn.execute("UPDATE files SET project_id = 1, name = 'Urlaub.JPG'")
        conn.execute("INSERT INTO files (id, is_folder, project_id, name) VALUES (6, 0, 1, 'notes.md')")
        conn.commit()
        conn.close()
        (self.paths.data / "files" / "1" / "1").write_bytes(b"\xff\xd8 a photo")
        (self.paths.data / "files" / "1" / "6").write_text("text " * 200)
        (self.paths.data / "files" / "1" / "1.thumb").write_bytes(b"small picture")
        out = Path(self.tmp.name) / "open.zip"
        pyrage.decrypt_file(str(self.backup()), str(out), [self.secret])
        with zipfile.ZipFile(out) as archive:
            kinds = {info.filename: info.compress_type for info in archive.infolist()}
            self.assertEqual(archive.read("files/1/1"), b"\xff\xd8 a photo")
        self.assertEqual(kinds["files/1/1"], zipfile.ZIP_STORED)        # by the real name, any case
        self.assertEqual(kinds["files/1/1.thumb"], zipfile.ZIP_STORED)
        self.assertEqual(kinds["files/1/6"], zipfile.ZIP_DEFLATED)
        self.assertEqual(kinds["database/hub.db"], zipfile.ZIP_DEFLATED)

    def test_no_key_no_backup(self):
        with self.assertRaises(hubctl.Failed) as failed:
            hubctl.make_backup(self.paths, "")
        self.assertEqual(str(failed.exception), "no_key")

    def test_old_backups_go_seven_days_and_four_sundays_stay(self):
        folder = self.paths.backups
        folder.mkdir()
        day = datetime.date(2026, 11, 30)
        for n in range(40):
            (folder / f"agent-hub-backup-{day - datetime.timedelta(days=n):%Y-%m-%d}-0315.zip.age").write_bytes(b"x")
        (folder / "hub-2026-11-01.tar.gz.gpg").write_bytes(b"old format")   # the old backups are not ours to delete
        hubctl.prune(folder)
        left = sorted(p.name for p in folder.glob("agent-hub-backup-*"))
        self.assertEqual(len(left), 11)
        sundays = [n for n in left[:-7] if datetime.date.fromisoformat(n[17:27]).isoweekday() == 7]
        self.assertEqual(len(sundays), 4)
        self.assertTrue((folder / "hub-2026-11-01.tar.gz.gpg").exists())

    # --- putting a backup back
    def test_a_backup_comes_back_exactly_and_the_state_before_is_kept(self):
        upload = self.upload(self.backup())
        self.change_everything()
        hubctl.check_restore(self.paths, f"# a comment\n{self.secret}\n", upload)
        summary = json.loads((self.paths.data / "restore" / "summary.json").read_text())
        self.assertEqual((summary["owner"], summary["counts"]["projects"]), ("owner@example.com", 2))
        self.assertNotIn("old-key", json.dumps(summary))                    # the page never sees a secret
        self.assertFalse(upload.exists())
        self.assertEqual(self.calls, [])                                    # checking changes nothing
        hubctl.apply_restore(self.paths, now=datetime.datetime(2026, 11, 28, 10, 0).timestamp())
        conn = sqlite3.connect(self.paths.data / "hub.db")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 2)
        conn.close()
        self.assertEqual((self.paths.data / "files" / "1" / "5").read_bytes(), b"a picture")
        self.assertEqual((self.paths.claude / "1" / "token.enc").read_bytes(), b"sealed token")
        self.assertTrue((self.paths.work / "repos" / "3.git" / "HEAD").exists())
        env = hubctl.read_env(self.paths.app / ".env")
        self.assertEqual(env["HUB_TOKEN_KEY"], "old-key")                   # opens the logins of the backup
        self.assertEqual(env["RUNNER_TOKEN"], "device-token")               # the device keeps its own
        self.assertEqual(env["HUB_PORT"], "8080")
        before = self.paths.base / "before-restore-2026-11-28-100000"
        self.assertEqual((before / "data" / "files" / "1" / "5").read_bytes(), b"changed")
        self.assertTrue((before / "work" / "tasks" / "9" / "half.py").exists())
        self.assertEqual(json.loads((self.paths.results / "restore.json").read_text())["ok"], True)
        self.assertEqual(self.calls[0], ("stop", *hubctl.SERVICES))
        self.assertEqual(self.calls[-1], ("up", "-d", "--no-build"))
        self.assertFalse(self.paths.staging.exists())
        self.assertEqual(oct((self.paths.claude / "1" / "token.enc").stat().st_mode & 0o777), oct(0o600))

    def test_a_backup_of_the_list_is_checked_where_it_lies_and_stays(self):
        path = self.backup()
        self.paths.jobs.mkdir(parents=True, exist_ok=True)
        (self.paths.jobs / "8.json").write_text(json.dumps({"action": "restore-check",
                                                            "payload": {"identity": str(self.secret), "source": path.name}}))
        self.assertEqual(hubctl.run(self.paths, 8), 0)
        self.assertTrue(path.exists())                                       # the server's backup is not used up
        self.assertTrue((self.paths.staging / ".checked").exists())
        (self.paths.jobs / "9.json").write_text(json.dumps({"action": "restore-check",
                                                            "payload": {"identity": str(self.secret), "source": "../app/.env"}}))
        self.assertEqual(hubctl.run(self.paths, 9), 1)                       # only names of backups

    def test_the_wrong_key_changes_nothing_and_the_upload_may_be_tried_again(self):
        upload = self.upload(self.backup())
        with self.assertRaises(hubctl.Failed) as failed:
            hubctl.check_restore(self.paths, str(pyrage.x25519.Identity.generate()), upload)
        self.assertEqual(str(failed.exception), "wrong_key")
        self.assertTrue(upload.exists())
        self.assertFalse(self.paths.staging.exists())
        with self.assertRaises(hubctl.Failed) as failed:
            hubctl.check_restore(self.paths, "no key at all", upload)
        self.assertEqual(str(failed.exception), "bad_key")

    def sealed(self, files: dict, manifest: dict | None = None) -> Path:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data)
            listed = {n: {"size": len(d), "sha256": hashlib.sha256(d).hexdigest()} for n, d in files.items()}
            archive.writestr("manifest.json", json.dumps(manifest or {"format": "agent-hub-backup", "version": 1, "files": listed}))
        plain = Path(self.tmp.name) / "plain.zip"
        plain.write_bytes(buffer.getvalue())
        sealed = Path(self.tmp.name) / "sealed.age"
        pyrage.encrypt_file(str(plain), str(sealed), [self.secret.to_public()])
        return sealed

    def test_paths_out_of_the_backup_are_refused(self):
        db_bytes = (self.paths.data / "hub.db").read_bytes()
        for evil in ("../evil", "files/../../evil", "/etc/evil", "other/x", "files/a\\b"):
            upload = self.upload(self.sealed({"database/hub.db": db_bytes, evil: b"x"}))
            with self.assertRaises(hubctl.Failed, msg=evil) as failed:
                hubctl.check_restore(self.paths, str(self.secret), upload)
            self.assertEqual(str(failed.exception), "damaged")
        self.assertFalse((Path(self.tmp.name).parent / "evil").exists())
        self.assertFalse(self.paths.staging.exists())

    def test_a_changed_file_or_a_newer_format_is_refused(self):
        db_bytes = (self.paths.data / "hub.db").read_bytes()
        listed = {"database/hub.db": {"size": len(db_bytes), "sha256": "0" * 64}}
        upload = self.upload(self.sealed({"database/hub.db": db_bytes},
                                         {"format": "agent-hub-backup", "version": 1, "files": listed}))
        with self.assertRaises(hubctl.Failed) as failed:
            hubctl.check_restore(self.paths, str(self.secret), upload)
        self.assertEqual(str(failed.exception), "damaged")
        upload = self.upload(self.sealed({"database/hub.db": db_bytes}, {"format": "agent-hub-backup", "version": 2, "files": {}}))
        with self.assertRaises(hubctl.Failed) as failed:
            hubctl.check_restore(self.paths, str(self.secret), upload)
        self.assertEqual(str(failed.exception), "newer")

    def test_a_put_back_that_breaks_goes_back_to_the_state_before(self):
        upload = self.upload(self.backup())
        self.change_everything()
        hubctl.check_restore(self.paths, str(self.secret), upload)
        with mock.patch.object(hubctl, "merge_env", side_effect=OSError("disk full")):
            with self.assertRaises(hubctl.Failed) as failed:
                hubctl.apply_restore(self.paths)
        self.assertEqual(str(failed.exception), "apply")
        self.assertEqual((self.paths.data / "files" / "1" / "5").read_bytes(), b"changed")
        self.assertEqual((self.paths.claude / "1" / "token.enc").read_bytes(), b"other token")
        self.assertTrue((self.paths.work / "tasks" / "9" / "half.py").exists())
        self.assertEqual(hubctl.read_env(self.paths.app / ".env")["HUB_TOKEN_KEY"], "new-key")
        self.assertEqual(self.calls[-1], ("up", "-d", "--no-build"))       # the hub runs again

    def test_nothing_is_put_back_without_a_check(self):
        with self.assertRaises(hubctl.Failed) as failed:
            hubctl.apply_restore(self.paths)
        self.assertEqual(str(failed.exception), "not_checked")
        self.assertEqual(self.calls, [])

    # --- .env
    def test_merge_env_keeps_the_rest_and_refuses_a_second_line(self):
        path = self.paths.app / ".env"
        hubctl.merge_env(path, {"HUB_BASE_URL": "https://new.example.de", "RUNNER_TOKEN": None, "MAIL_FROM": "a@b.de"})
        text = path.read_text()
        self.assertIn("# hub\n", text)
        self.assertIn("HUB_BASE_URL=https://new.example.de\n", text)
        self.assertNotIn("RUNNER_TOKEN", text)
        self.assertIn("MAIL_FROM=a@b.de\n", text)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        for bad in ({"HUB_BASE_URL": "x\nRUNNER_TOKEN=evil"}, {"bad key": "x"}, {"X": "\x00"}):
            with self.assertRaises(hubctl.Failed):
                hubctl.merge_env(path, bad)
        self.assertNotIn("evil", path.read_text())

    def test_settings_switch_the_tunnel_with_its_token(self):
        saved = []
        hubctl.apply_settings(self.paths, {"TUNNEL_TOKEN": "eyJ" + "a" * 60}, lambda: saved.append(1))
        env = hubctl.read_env(self.paths.app / ".env")
        self.assertEqual(env["COMPOSE_PROFILES"], "tunnel")
        self.assertEqual(saved, [1])
        self.assertEqual(self.calls[-1], ("up", "-d", "--no-build"))
        hubctl.apply_settings(self.paths, {"TUNNEL_TOKEN": ""})
        env = hubctl.read_env(self.paths.app / ".env")
        self.assertNotIn("TUNNEL_TOKEN", env)
        self.assertNotIn("COMPOSE_PROFILES", env)
        self.assertIn(("rm", "-sf", "tunnel"), self.calls)
        for bad in ({"RUNNER_TOKEN": "x"}, {"HUB_PORT": "1"}, {}):
            with self.assertRaises(hubctl.Failed):
                hubctl.apply_settings(self.paths, bad)

    # --- one job
    def test_a_job_reads_and_deletes_its_payload_and_answers_in_the_data_folder(self):
        self.paths.jobs.mkdir(parents=True)
        payload = self.paths.jobs / "4.json"
        payload.write_text(json.dumps({"action": "backup", "payload": {"recipient": str(self.secret.to_public())}}))
        self.assertEqual(hubctl.run(self.paths, 4), 0)
        self.assertFalse(payload.exists())
        answer = json.loads((self.paths.results / "4.json").read_text())
        self.assertTrue(answer["ok"])
        self.assertTrue(answer["name"].startswith("agent-hub-backup-"))
        payload.write_text(json.dumps({"action": "format-disk", "payload": {}}))
        self.assertEqual(hubctl.run(self.paths, 4), 1)
        self.assertEqual(json.loads((self.paths.results / "4.json").read_text()), {"ok": False, "reason": "unknown"})
        self.assertEqual(hubctl.run(self.paths, 99), 1)                     # no payload: a clean failure
        payload.write_text(json.dumps({"action": "restart", "payload": {}}))
        self.calls.clear()
        self.assertEqual(hubctl.run(self.paths, 4), 0)
        self.assertEqual(self.calls, [("restart",)])                        # the hub's containers, nothing else
        self.assertEqual(json.loads((self.paths.results / "99.json").read_text())["reason"], "no_job")


if __name__ == "__main__":
    unittest.main()
