"""Jobs on the server (hostjobs.py) and the backup around them (backups.py, routes/backup.py): one job at a time, the
payload is handed out once and cleared, answers come as files, the nightly backup, the recovery key, uploads in pieces,
downloads with the password, and who may do what."""
import json
import os
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from app import backups, db, hostjobs, serversettings, users
from app.routes import backup as routes, runner


def request(ip="192.168.1.20", **headers):
    return types.SimpleNamespace(headers=headers, client=types.SimpleNamespace(host=ip), cookies={})


class HostJobsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "hub.db")
        self.owner = users.create_user("owner@example.com", "Own3r!pass", role="owner")

    def tearDown(self):
        self.tmp.cleanup()

    def answer(self, job_id, **result):
        folder = hostjobs.results_dir()
        folder.mkdir(exist_ok=True)
        (folder / f"{job_id}.json").write_text(json.dumps(result))

    def test_a_job_is_handed_out_once_and_its_payload_is_cleared(self):
        job = hostjobs.request("restore-check", {"identity": "AGE-SECRET-KEY-1ABC"}, self.owner.id)
        claimed = hostjobs.claim_next()
        self.assertEqual(claimed, {"id": job, "action": "restore-check", "payload": {"identity": "AGE-SECRET-KEY-1ABC"}})
        self.assertIsNone(hostjobs.claim_next())
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT payload FROM host_jobs").fetchone()[0], "{}")   # the key is gone
        self.assertEqual(hostjobs.state(job_id=job)["state"], "running")

    def test_one_job_at_a_time_and_the_answer_comes_as_a_file(self):
        first = hostjobs.request("backup", {"recipient": "age1x"})
        self.assertIsNone(hostjobs.request("settings", {"values": {}}))
        hostjobs.claim_next()
        self.assertIsNone(hostjobs.request("backup"))
        self.answer(first, ok=True, name="agent-hub-backup-2026-11-27-0315.zip.age", size=1234)
        state = hostjobs.state(job_id=first)
        self.assertEqual((state["state"], state["detail"]["size"]), ("ok", 1234))
        self.assertFalse((hostjobs.results_dir() / f"{first}.json").exists())
        self.assertIsNotNone(hostjobs.request("settings", {"values": {}}))

    def test_jobs_that_nobody_took_or_that_never_answered_count_as_failed(self):
        job = hostjobs.request("backup")
        later = int(time.time()) + hostjobs.FRESH_SECONDS + 5
        self.assertEqual(hostjobs.state(job_id=job, now=later)["detail"], {"reason": "not_taken"})
        job = hostjobs.request("settings", now=later)
        hostjobs.claim_next(now=later)
        much_later = later + hostjobs.TIMEOUT["settings"] + 5
        self.assertEqual(hostjobs.state(job_id=job, now=much_later)["detail"], {"reason": "timeout"})
        self.assertFalse(hostjobs.busy(now=much_later))

    def test_unknown_actions_are_refused(self):
        for action in ("", "format", "backup; rm -rf /"):
            with self.assertRaises(ValueError):
                hostjobs.request(action)

    def test_the_runner_routes(self):
        job = hostjobs.request("backup", {"recipient": "age1x"})
        self.assertEqual(runner.host_claim()["job"]["id"], job)
        self.assertEqual(runner.host_claim(), {"ok": True, "job": None})
        self.assertEqual(runner.host_failed(job), {"ok": True})
        self.assertEqual(hostjobs.state(job_id=job)["detail"], {"reason": "not_started"})
        self.assertEqual(runner.host_failed(job).status_code, 409)

    # --- the nightly backup
    def test_the_nightly_backup_needs_a_key_and_comes_once_a_day_at_its_hour(self):
        night = time.mktime((2026, 11, 27, 2, 0, 0, 0, 0, -1))
        self.assertIsNone(hostjobs.claim_next(now=int(night) + 3600))     # no key: no backup
        backups.new_key()
        self.assertIsNone(hostjobs.claim_next(now=int(night)))            # 02:00, the hour is 03
        job = hostjobs.claim_next(now=int(night) + 3600)                   # 03:00
        self.assertEqual((job["action"], job["payload"]["recipient"]), ("backup", backups.recipient()))
        self.answer(job["id"], ok=True, size=1)
        self.assertIsNone(hostjobs.claim_next(now=int(night) + 7200))     # once a day
        self.assertIsNotNone(hostjobs.claim_next(now=int(night) + 86400 + 3600))   # the next night again
        self.assertTrue(hostjobs.state(action="backup")["auto"])
        serversettings.set_choice("backup_hour", 23, serversettings.CHOICES["backup_hour"])
        self.assertEqual(backups.hour(), 23)


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "hub.db")
        self.owner = users.create_user("owner@example.com", "Own3r!pass", role="owner")
        self.sup = users.create_user("super@example.com", "Sup3r!pass", role="superadmin")
        self.admin = users.create_user("admin@example.com", "Adm1n!pass", role="admin")
        self.user = users.create_user("user@example.com", "Us3r!pass1", role="user")
        self.folder = Path(self.tmp.name) / "backups"
        self.folder.mkdir()
        patcher = mock.patch.dict(os.environ, {"HUB_BACKUP_DIR": str(self.folder)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_recovery_key_keeps_only_its_public_half_on_the_server(self):
        text = backups.new_key()
        line = backups.key_line(text)
        self.assertTrue(line.startswith("AGE-SECRET-KEY-1"))
        self.assertTrue(backups.recipient().startswith("age1"))
        with db.connect() as conn:
            stored = " ".join(row[0] for row in conn.execute("SELECT value FROM server_settings"))
        self.assertNotIn(line, stored)
        self.assertEqual(backups.key_line("# only a comment\nAGE-SECRET-KEY-1NOTREAL"), "")
        self.assertEqual(backups.key_line(f"# my key\n  {line}  \n"), line)

    def test_only_the_owner_makes_a_key_and_replacing_one_asks_for_the_password(self):
        for who in (self.sup, self.admin, self.user):
            self.assertEqual(routes.make_key(request(), "", who).status_code, 403)
        first = routes.make_key(request(), "", self.owner)
        self.assertTrue(first["ok"] and "AGE-SECRET-KEY-1" in first["key"])
        self.assertEqual(routes.make_key(request(), "wrong", self.owner).status_code, 403)
        self.assertEqual(backups.key_line(first["key"]), backups.key_line(first["key"]))
        second = routes.make_key(request(), "Own3r!pass", self.owner)
        self.assertNotEqual(backups.key_line(second["key"]), backups.key_line(first["key"]))

    def test_back_up_now_needs_a_key_and_is_for_owner_and_superadmin(self):
        self.assertEqual(routes.backup_now(self.owner).status_code, 409)       # no key yet
        backups.new_key()
        for who in (self.admin, self.user):
            self.assertEqual(routes.backup_now(who).status_code, 403)
        self.assertEqual(routes.backup_now(self.sup), {"ok": True})
        self.assertEqual(routes.backup_now(self.owner).status_code, 409)       # one at a time
        self.assertEqual(routes.backup_state(self.owner)["job"]["state"], "running")
        self.assertEqual(routes.backup_state(self.user).status_code, 403)

    def test_a_download_needs_the_password_and_works_once(self):
        name = "agent-hub-backup-2026-11-27-0315.zip.age"
        (self.folder / name).write_bytes(b"sealed")
        (self.folder / "notes.txt").write_text("not a backup")
        self.assertEqual([item["name"] for item in backups.listing()], [name])
        self.assertEqual(routes.ask_download(request(), name, "wrong", self.owner).status_code, 403)
        self.assertEqual(routes.ask_download(request(), "notes.txt", "Own3r!pass", self.owner).status_code, 404)
        self.assertEqual(routes.ask_download(request(), name, "Adm1n!pass", self.admin).status_code, 403)
        url = routes.ask_download(request(), name, "Own3r!pass", self.owner)["url"]
        token = url.split("t=", 1)[1]
        self.assertEqual(Path(routes.download(token, self.owner).path).name, name)
        with self.assertRaises(routes.HTTPException):
            routes.download(token, self.owner)                                   # once

    def test_an_upload_comes_in_order_and_needs_room(self):
        self.assertEqual(backups.receive(0, b"abc", 6), "more")
        with self.assertRaises(ValueError) as wrong:
            backups.receive(5, b"x", 6)
        self.assertEqual(str(wrong.exception), "offset")
        with self.assertRaises(ValueError):
            backups.receive(3, b"defg", 6)                                       # more than said
        self.assertEqual(backups.receive(3, b"def", 6), "done")
        self.assertTrue(backups.uploaded())
        self.assertEqual((backups.restore_dir() / "upload.age").read_bytes(), b"abcdef")
        with mock.patch.object(backups.shutil, "disk_usage", return_value=types.SimpleNamespace(free=10)):
            with self.assertRaises(ValueError) as full:
                backups.receive(0, b"a", 6)
        self.assertEqual(str(full.exception), "size")

    def test_a_backup_from_a_newer_hub_is_recognised(self):
        with db.connect() as conn:
            ours = {row[0]: [c[1] for c in conn.execute(f'PRAGMA table_info("{row[0]}")')]
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}
        self.assertFalse(backups.newer_than_us({"schema": ours}))
        older = dict(ours, users=[c for c in ours["users"] if c != "deleted_at"])
        self.assertFalse(backups.newer_than_us({"schema": older}))               # db.py adds what is missing
        self.assertTrue(backups.newer_than_us({"schema": dict(ours, users=ours["users"] + ["future"])}))
        self.assertTrue(backups.newer_than_us({"schema": dict(ours, future_table=["id"])}))

    def test_putting_back_is_the_owners_and_never_through_the_tunnel(self):
        owner_req = request()
        with mock.patch.object(routes.setup, "open_for", return_value=False):
            for who in (self.sup, self.admin, self.user, None):
                owner_req.cookies = {routes.COOKIE_NAME: users.create_session(who.id)} if who else {}
                with self.assertRaises(routes.HTTPException):
                    routes.restorer(owner_req)
            owner_req.cookies = {routes.COOKIE_NAME: users.create_session(self.owner.id)}
            self.assertEqual(routes.restorer(owner_req).id, self.owner.id)

    def test_checking_needs_a_valid_key_and_an_upload_and_applying_a_checked_backup(self):
        self.assertEqual(routes.check(request(), "nonsense", self.owner).status_code, 400)
        key = backups.key_line(backups.new_key())
        self.assertEqual(routes.check(request(), key, self.owner).status_code, 409)   # nothing uploaded
        backups.receive(0, b"abc", 3)
        job = routes.check(request(), key, self.owner)["job"]
        self.assertEqual(routes.state(request(), job, self.owner), {"ok": True, "stage": "checking"})
        self.assertEqual(routes.apply(request(), "Own3r!pass", self.owner).status_code, 409)   # not checked
        hostjobs.end_open("restore-check", "x")
        summary = {"created": "2026-11-27T03:15:00", "owner": "owner@example.com", "size": 2048,
                   "counts": {"users": 2, "projects": 3, "files": 4}, "schema": {}, "tunnel": True}
        (backups.restore_dir() / "summary.json").write_text(json.dumps(summary))
        shown = routes.state(request(), 0, self.owner)
        self.assertEqual((shown["stage"], shown["summary"]["created"], shown["summary"]["projects"]),
                         ("summary", "27.11.2026 03:15", 3))
        self.assertNotIn("schema", shown["summary"])
        self.assertEqual(routes.apply(request(), "wrong", self.owner).status_code, 403)
        self.assertTrue(routes.apply(request(), "Own3r!pass", self.owner)["ok"])
        self.assertEqual(hostjobs.claim_next()["action"], "restore-apply")

    def test_the_end_of_a_put_back_is_told_without_a_login_but_only_for_an_hour(self):
        self.assertEqual(routes.done(), {"ok": True, "done": None})
        folder = hostjobs.results_dir()
        folder.mkdir()
        (folder / "restore.json").write_text(json.dumps({"ok": True, "at": time.time(), "before": "before-restore-x"}))
        self.assertEqual(routes.done(), {"ok": True, "done": True, "reason": ""})
        (folder / "restore.json").write_text(json.dumps({"ok": True, "at": time.time() - 4000}))
        self.assertEqual(routes.done(), {"ok": True, "done": None})


if __name__ == "__main__":
    unittest.main()
