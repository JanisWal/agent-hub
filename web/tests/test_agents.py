"""Claude connection, task queue and the whole chain on a real (temporary) database."""
import os
import tempfile
import unittest
from pathlib import Path

from app import agents, board, claude_link, db, projects, users


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        claude_link.BASE_DIR = Path(self.tmp.name) / "claude"
        self.a = users.create_user("a@example.com", "Aaaa!pass12")
        self.b = users.create_user("b@example.com", "Bbbb!pass12")
        self.project = projects.create_project(self.a.id, "Project of A")
        self.item = board.create_item(self.a.id, self.project.id, "bug", "Fix the thing")

    def tearDown(self):
        self.tmp.cleanup()

    def connect(self, user):
        claude_link.begin(user.id)
        claude_link.complete(user.id, True)


class ClaudeLinkTest(Base):
    def test_login_flow(self):
        self.assertEqual(claude_link.status(self.a.id), "none")
        self.assertTrue(claude_link.begin(self.a.id))
        self.assertFalse(claude_link.begin(self.a.id))            # a login is running already
        self.assertIsNone(claude_link.login_url(self.a.id))
        self.assertTrue(claude_link.set_login_url(self.a.id, "https://claude.ai/oauth/authorize?x=1"))
        self.assertEqual(claude_link.login_url(self.a.id), "https://claude.ai/oauth/authorize?x=1")
        self.assertTrue(claude_link.complete(self.a.id, True))
        self.assertTrue(claude_link.is_connected(self.a.id))
        self.assertIsNone(claude_link.login_url(self.a.id))
        self.assertFalse(claude_link.begin(self.a.id))            # connected already
        self.assertTrue(claude_link.mark_expired(self.a.id))
        self.assertEqual(claude_link.status(self.a.id), "expired")
        self.assertTrue(claude_link.begin(self.a.id))             # reconnect
        self.assertTrue(claude_link.disconnect(self.a.id))
        self.assertEqual(claude_link.status(self.a.id), "none")

    def test_failed_login_and_timeout(self):
        claude_link.begin(self.a.id, now=1000)
        self.assertEqual(claude_link.status(self.a.id, now=1000 + claude_link.CONNECT_TIMEOUT + 1), "none")
        self.assertFalse(claude_link.complete(self.a.id, True, now=1000 + claude_link.CONNECT_TIMEOUT + 1))
        claude_link.begin(self.a.id)
        claude_link.complete(self.a.id, False)
        self.assertEqual(claude_link.status(self.a.id), "none")

    def test_login_link_must_be_https_to_claude(self):
        claude_link.begin(self.a.id)
        for bad in ("http://claude.ai/x", "https://evil.example/claude.ai", "https://claude.ai.evil.com/x",
                    "javascript:alert(1)", ""):
            with self.assertRaises(ValueError, msg=bad):
                claude_link.set_login_url(self.a.id, bad)

    def test_config_dirs_are_per_user(self):
        self.assertNotEqual(claude_link.config_dir(self.a.id), claude_link.config_dir(self.b.id))
        self.assertEqual(claude_link.config_dir(self.a.id).parent, claude_link.config_dir(self.b.id).parent)

    def test_deleting_the_user_removes_the_connection(self):
        self.connect(self.a)
        with db.connect() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (self.a.id,))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM claude_connections").fetchone()[0], 0)


class ChainTest(Base):
    def run_stage(self, result, report="", **kw):
        job = agents.claim_next(can_mac=True, **kw)
        self.assertIsNotNone(job)
        self.assertTrue(agents.finish_run(job.run_id, result, report, tokens_in=10, tokens_out=5, seconds=3))
        return job

    def test_nothing_starts_without_the_users_own_claude(self):
        agents.start_task(self.a.id, self.project.id, self.item.id)
        self.connect(self.b)                                      # somebody else's Claude does not help
        self.assertIsNone(agents.claim_next(can_mac=True))
        task = agents.list_tasks(self.a.id, self.project.id)[0]
        self.assertEqual(agents.waiting_reason(self.a.id, task), "no_claude")
        self.connect(self.a)
        self.assertEqual(agents.claim_next(can_mac=True).user_id, self.a.id)

    def test_whole_chain_with_one_round_back(self):
        self.connect(self.a)
        task = agents.start_task(self.a.id, self.project.id, self.item.id)
        job = self.run_stage("done", "coded")
        self.assertEqual((job.role, job.branch, job.model), ("programmer", f"agent/task-{task.id}", "sonnet"))
        self.assertEqual(self.run_stage("fail", "test x fails").role, "tester")
        job = self.run_stage("done", "fixed")
        self.assertEqual((job.role, job.round), ("programmer", 2))
        self.assertIn(("tester", "test x fails"), job.reports)    # the hub passes the report on
        self.run_stage("pass")
        self.assertEqual(self.run_stage("ok").role, "reviewer")
        self.assertEqual(agents.get_task(self.a.id, task.id).status, "awaiting_approval")
        self.assertIsNone(agents.claim_next(can_mac=True))        # waits for the user
        self.assertTrue(agents.decide(self.a.id, task.id, "approve"))
        self.assertEqual(self.run_stage("done", "documented").role, "documenter")
        done = agents.get_task(self.a.id, task.id)
        self.assertEqual((done.status, done.round), ("done", 2))
        self.assertEqual(agents.usage(self.a.id, self.project.id)["tokens_in"], 60)
        self.assertEqual(agents.usage(self.b.id), {"tokens_in": 0, "tokens_out": 0, "seconds": 0, "runs": 0})

    def test_three_rounds_then_the_user_decides(self):
        self.connect(self.a)
        task = agents.start_task(self.a.id, self.project.id, self.item.id)
        for _ in range(3):
            self.run_stage("done")
            self.run_stage("fail")
        self.assertEqual(agents.get_task(self.a.id, task.id).status, "escalated")
        self.assertIsNone(agents.claim_next(can_mac=True))
        self.assertFalse(agents.decide(self.a.id, task.id, "approve"))
        self.assertTrue(agents.decide(self.a.id, task.id, "reject", "try the other way"))
        job = agents.claim_next(can_mac=True)
        self.assertEqual((job.role, job.round, job.note), ("programmer", 1, "try the other way"))

    def test_one_run_at_a_time_and_stale_runs(self):
        self.connect(self.a)
        other = board.create_item(self.a.id, self.project.id, "minor", "Second")
        agents.start_task(self.a.id, self.project.id, self.item.id, now=1000)
        agents.start_task(self.a.id, self.project.id, other.id, now=1001)
        first = agents.claim_next(can_mac=True, now=1002)
        self.assertIsNone(agents.claim_next(can_mac=True, now=1003))          # the Pi runs one
        second = agents.claim_next(can_mac=True, now=1002 + agents.RUN_SECONDS + 1)
        self.assertIsNotNone(second)                                           # the silent run was dropped
        # the silent run failed: its task is with the user, the second task may start
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT status FROM agent_runs WHERE id = ?",
                                          (first.run_id,)).fetchone()[0], "failed")
        self.assertFalse(agents.finish_run(first.run_id, "done"))              # too late

    def test_deadline_sends_the_task_to_the_user(self):
        self.connect(self.a)
        task = agents.start_task(self.a.id, self.project.id, self.item.id, now=1000)
        self.assertIsNone(agents.claim_next(can_mac=True, now=1000 + agents.TASK_SECONDS + 1))
        self.assertEqual(agents.get_task(self.a.id, task.id).status, "escalated")

    def test_mac_tasks_wait_or_skip_the_test_by_strictness(self):
        self.connect(self.a)
        task = agents.start_task(self.a.id, self.project.id, self.item.id, needs="mac")
        self.assertIsNone(agents.claim_next(can_mac=False))                    # needs the Mac
        self.run_stage("done")                                                 # the Mac coded it
        self.assertIsNone(agents.claim_next(can_mac=False))                    # normal: a bug is tested
        self.assertEqual(agents.get_task(self.a.id, task.id).status, "testing")
        agents.configure(self.a.id, strictness="loose")                        # loose skips bug tests
        self.assertIsNone(agents.claim_next(can_mac=False))                    # the reviewer needs the Mac too
        done = agents.get_task(self.a.id, task.id)
        self.assertEqual((done.status, done.manual_check), ("reviewing", True))

    def test_disabled_tester_is_skipped(self):
        self.connect(self.a)
        agents.configure(self.a.id, "tester", enabled=False)
        task = agents.start_task(self.a.id, self.project.id, self.item.id)
        self.assertEqual(self.run_stage("done").role, "programmer")
        self.assertEqual(agents.claim_next(can_mac=True).role, "reviewer")
        self.assertTrue(agents.get_task(self.a.id, task.id).manual_check)

    def test_pick_next_order_and_taken_items(self):
        minor = board.create_item(self.a.id, self.project.id, "minor", "Small")
        major = board.create_item(self.a.id, self.project.id, "major", "Big")
        board.create_suggestion(self.a.id, self.project.id, "bug", "Only a suggestion")
        self.assertEqual(agents.pick_next(self.a.id, self.project.id).id, self.item.id)   # bug first
        agents.start_task(self.a.id, self.project.id, self.item.id)
        self.assertEqual(agents.pick_next(self.a.id, self.project.id).id, minor.id)
        agents.start_task(self.a.id, self.project.id, minor.id)
        self.assertEqual(agents.pick_next(self.a.id, self.project.id).id, major.id)
        with self.assertRaises(ValueError):
            agents.start_task(self.a.id, self.project.id, self.item.id)               # already taken

    def test_settings_validation(self):
        for call in (lambda: agents.configure(self.a.id, "programmer", enabled=False),
                     lambda: agents.configure(self.a.id, "tester", model="gpt"),
                     lambda: agents.configure(self.a.id, "janitor", enabled=True),
                     lambda: agents.configure(self.a.id, strictness="wild")):
            with self.assertRaises(ValueError):
                call()
        agents.configure(self.a.id, "reviewer", model="opus")
        self.assertEqual(agents.settings(self.a.id)["roles"]["reviewer"]["model"], "opus")
        self.assertEqual(agents.settings(self.b.id)["roles"]["reviewer"]["model"], "sonnet")

    def test_bad_results_are_refused(self):
        self.connect(self.a)
        agents.start_task(self.a.id, self.project.id, self.item.id)
        job = agents.claim_next(can_mac=True)
        with self.assertRaises(ValueError):
            agents.finish_run(job.run_id, "pass")        # a tester result for the programmer
        self.assertTrue(agents.finish_run(job.run_id, "done"))
        self.assertFalse(agents.finish_run(job.run_id, "done"))   # a run ends only once


if __name__ == "__main__":
    unittest.main()
