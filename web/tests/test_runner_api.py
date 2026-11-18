"""The runner interface: only the runner gets in, and it can only do what a runner may."""
import hashlib
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

from app import agents, board, claude_link, db, projects, throttle, users
from app.routes import runner

TOKEN = "runner-secret-for-tests"


def request(token=TOKEN, cf_ip=None, host="172.18.0.7"):
    headers = {}
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    if cf_ip:
        headers["cf-connecting-ip"] = cf_ip
    return types.SimpleNamespace(headers=headers, client=types.SimpleNamespace(host=host))


class RunnerApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        claude_link._codes.clear()
        patcher = mock.patch.dict(os.environ, {runner.TOKEN_HASH_ENV: hashlib.sha256(TOKEN.encode()).hexdigest()})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.a = users.create_user("a@example.com", "Aaaa!pass12")
        self.project = projects.create_project(self.a.id, "Project")
        self.item = board.create_item(self.a.id, self.project.id, "bug", "Fix")

    def tearDown(self):
        self.tmp.cleanup()

    def status(self, **kw):
        try:
            runner.runner_only(request(**kw))
        except HTTPException as error:
            return error.status_code
        return 200

    def test_access(self):
        self.assertEqual(self.status(), 200)
        self.assertEqual(self.status(token="wrong"), 401)
        self.assertEqual(self.status(token=None), 401)
        self.assertEqual(self.status(token=""), 401)
        self.assertEqual(self.status(cf_ip="203.0.113.9"), 404)     # came through the tunnel: not even with the token
        with mock.patch.dict(os.environ, {runner.TOKEN_HASH_ENV: ""}):
            self.assertEqual(self.status(), 404)                    # interface switched off

    def test_wrong_tokens_lock_the_ip(self):
        for _ in range(throttle.MAX_FAILURES):
            self.assertEqual(self.status(token="guess"), 401)
        self.assertEqual(self.status(), 429)                        # even the right token waits
        self.assertEqual(self.status(host="172.18.0.99"), 200)      # another address is not affected
        self.assertEqual(throttle.seconds_locked("172.18.0.7"), 0)  # and the password counter is separate

    def test_every_route_is_protected(self):
        for route in runner.router.routes:
            self.assertTrue(any(d.call is runner.runner_only for d in route.dependant.dependencies),
                            route.path)

    def test_job_and_result_flow(self):
        claude_link.begin(self.a.id)
        claude_link.complete(self.a.id, True)
        agents.start_task(self.a.id, self.project.id, self.item.id)
        job = runner.claim(can_mac="1")["job"]
        self.assertEqual((job["user_id"], job["role"], job["model"]), (self.a.id, "programmer", "sonnet"))
        self.assertEqual(sorted(job), sorted([
            "run_id", "user_id", "project_id", "task_id", "role", "model", "branch", "title", "kind",
            "round", "note", "reports", "net", "effort", "provider", "prompt", "files", "links", "images"]))
        self.assertEqual(job["effort"], "high")                         # Sonnet's default level
        self.assertIsNone(runner.claim(can_mac="1")["job"])         # one run at a time
        self.assertEqual(runner.finish(job["run_id"], "pass").status_code, 400)   # wrong for the programmer
        self.assertEqual(runner.finish(job["run_id"], "done", "ok", 5, 6, 7), {"ok": True})
        self.assertEqual(runner.finish(job["run_id"], "done").status_code, 409)   # only once
        self.assertEqual(runner.claim()["job"]["role"], "tester")

    def test_login_channel(self):
        claude_link.begin(self.a.id)
        self.assertEqual(runner.logins()["logins"], [{"user_id": self.a.id, "login_url": None}])
        self.assertEqual(runner.login_url(self.a.id, "http://evil.example/x").status_code, 400)
        self.assertEqual(runner.login_url(self.a.id, "https://claude.ai/login?x=1"), {"ok": True})
        self.assertEqual(runner.logins()["logins"][0]["login_url"], "https://claude.ai/login?x=1")
        self.assertIsNone(runner.login_code(self.a.id)["code"])
        self.assertTrue(claude_link.submit_code(self.a.id, "  code-123 "))
        self.assertEqual(runner.login_code(self.a.id)["code"], "code-123")
        self.assertIsNone(runner.login_code(self.a.id)["code"])     # handed over once
        self.assertEqual(runner.login_done(self.a.id, "1"), {"ok": True})
        self.assertTrue(claude_link.is_connected(self.a.id))
        self.assertEqual(runner.logins()["logins"], [])
        self.assertEqual(runner.login_expired(self.a.id), {"ok": True})
        self.assertEqual(claude_link.status(self.a.id), "expired")


class CodeChannelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        claude_link._codes.clear()
        self.a = users.create_user("a@example.com", "Aaaa!pass12")

    def tearDown(self):
        self.tmp.cleanup()

    def test_code_rules(self):
        self.assertFalse(claude_link.submit_code(self.a.id, "abc"))          # no login running
        claude_link.begin(self.a.id)
        self.assertFalse(claude_link.submit_code(self.a.id, "abc"))          # no link shown yet
        claude_link.set_login_url(self.a.id, "https://claude.ai/x")
        for bad in ("", "   ", "x" * (claude_link.MAX_CODE + 1)):
            with self.assertRaises(ValueError):
                claude_link.submit_code(self.a.id, bad)
        self.assertTrue(claude_link.submit_code(self.a.id, "abc", now=1000))
        self.assertIsNone(claude_link.take_code(self.a.id, now=1000 + claude_link.CODE_SECONDS + 1))  # expired
        claude_link.submit_code(self.a.id, "abc")
        claude_link.complete(self.a.id, False)
        self.assertIsNone(claude_link.take_code(self.a.id))                  # forgotten with the login

    def test_the_code_is_never_stored(self):
        claude_link.begin(self.a.id)
        claude_link.set_login_url(self.a.id, "https://claude.ai/x")
        claude_link.submit_code(self.a.id, "super-secret-code")
        with db.connect() as conn:
            dump = " ".join(str(tuple(r)) for t in ("claude_connections", "agent_tasks", "agent_runs")
                            for r in conn.execute(f"SELECT * FROM {t}"))
        self.assertNotIn("super-secret-code", dump)


class CleanupTest(unittest.TestCase):
    """Deleted projects and accounts: the runner gets their folders to delete, and the note goes when it is done."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.owner = users.create_user("o@example.com", "Oooo!pass12", role="owner")
        self.a = users.create_user("a@example.com", "Aaaa!pass12")
        self.project = projects.create_project(self.a.id, "P")
        item = board.create_item(self.a.id, self.project.id, "bug", "x")
        self.task = agents.start_task(self.a.id, self.project.id, item.id)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_deleted_project_queues_its_code_and_task_folders(self):
        self.assertEqual(runner.cleanups()["wipes"], [])
        projects.delete_project(self.a.id, self.project.id)
        wipes = runner.cleanups()["wipes"]
        self.assertCountEqual(wipes, [{"kind": "project", "ref": self.project.id}, {"kind": "task", "ref": self.task.id}])
        self.assertEqual(runner.cleanup_done("folder", 1).status_code, 400)
        self.assertTrue(runner.cleanup_done("project", self.project.id)["ok"])
        self.assertEqual(runner.cleanup_done("project", self.project.id).status_code, 409)   # reported already
        self.assertTrue(runner.cleanup_done("task", self.task.id)["ok"])
        self.assertEqual(runner.cleanups()["wipes"], [])

    def test_an_account_deleted_long_ago_goes_when_the_runner_asks(self):
        users.delete_user(self.owner, self.a.id)
        self.assertEqual(runner.cleanups()["wipes"], [])                       # still inside its time
        with db.connect() as conn:
            conn.execute("UPDATE users SET deleted_at = 1000 WHERE id = ?", (self.a.id,))
        kinds = sorted(w["kind"] for w in runner.cleanups()["wipes"])
        self.assertEqual(kinds, ["project", "task"])
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM users WHERE id = ?", (self.a.id,)).fetchone()[0], 0)
        self.assertIn(self.a.id, claude_link.pending_wipes())                  # whatever is left of his Claude folder


if __name__ == "__main__":
    unittest.main()
