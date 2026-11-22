"""The chain with the hub's own checks: the change (diff) goes to tester and reviewer, the project's own tests
(hub-test.sh) send a red change straight back, and a task that waits for the user stops the pieces after it."""
import os
import tempfile
import unittest

from app import agents, board, claude_link, db, projects, statusnote, users

DIFF = ("calc.js | 2 ++\n 1 file changed", "diff --git a/calc.js b/calc.js\n+export const add = (a, b) => a + b;\n")


class AgentFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.a = users.create_user("a@example.com", "Aaaa!pass12")
        self.b = users.create_user("b@example.com", "Bbbb!pass12")
        self.pa = projects.create_project(self.a.id, "Rechner")
        self.pb = projects.create_project(self.b.id, "Of B")
        statusnote._LAST_SCAN["at"] = 2 ** 40
        claude_link.begin(self.a.id)
        claude_link.complete(self.a.id, True)

    def tearDown(self):
        self.tmp.cleanup()

    def task(self):
        return agents.list_tasks(self.a.id, self.pa.id)[0]

    def test_green_tests_go_to_the_tester_then_the_reviewer_reads_the_change(self):
        board.create_item(self.a.id, self.pa.id, "minor", "Addieren")
        job = agents.claim_next(can_mac=False)
        self.assertIn("hub-test.sh", job.prompt)                                  # the programmer keeps the tests
        self.assertTrue(agents.finish_run(job.run_id, "done", "Gebaut.", change=DIFF, committed=True,
                                          tests=(0, "ok 1 - add\n")))
        job = agents.claim_next(can_mac=False)
        self.assertEqual(job.role, "tester")                                      # the behaviour is still checked
        self.assertIn("+export const add", job.prompt)
        agents.finish_run(job.run_id, "pass", "Läuft.")
        job = agents.claim_next(can_mac=False)
        self.assertEqual(job.role, "reviewer")
        self.assertIn("<change>", job.prompt)
        self.assertIn("hub-test.sh passed", job.prompt)
        runs = agents.task_runs(self.a.id, self.task().id)
        hub = [r for r in runs if r.model == agents.HUB_MODEL][0]
        self.assertEqual((hub.role, hub.result, hub.tokens_in), ("tester", "pass", 0))

    def test_red_tests_send_it_back_to_the_programmer_with_their_output(self):
        board.create_item(self.a.id, self.pa.id, "minor", "Addieren")
        job = agents.claim_next(can_mac=False)
        agents.finish_run(job.run_id, "done", "Gebaut.", change=DIFF, committed=True, tests=(1, "not ok 1 - add\nFAIL"))
        job = agents.claim_next(can_mac=False)
        self.assertEqual(job.role, "programmer")
        self.assertIn("not ok 1 - add", job.prompt)                               # the report of the hub's test run
        self.assertEqual((self.task().stage, self.task().returns), ("coding", 1))

    def test_without_tests_the_ai_tester_gets_the_change(self):
        board.create_item(self.a.id, self.pa.id, "minor", "Addieren")
        job = agents.claim_next(can_mac=False)
        agents.finish_run(job.run_id, "done", "Gebaut.", change=DIFF, committed=True)
        job = agents.claim_next(can_mac=False)
        self.assertEqual(job.role, "tester")
        self.assertIn("+export const add", job.prompt)
        self.assertNotIn("<tests>", job.prompt)

    def test_a_piece_that_waits_for_the_user_stops_the_pieces_after_it(self):
        with db.connect() as conn:
            board.add_from_ai(conn, self.pa.id, "minor", "Schritt 1", "Grundgerüst", approved=True, source="manager")
            board.add_from_ai(conn, self.pa.id, "minor", "Schritt 2", "baut auf Schritt 1", approved=True, source="manager")
        job = agents.claim_next(can_mac=False)
        self.assertEqual(job.title, "Schritt 1")
        agents.finish_run(job.run_id, "failed", "Ging nicht.")                    # once more, it may have been bad luck
        job = agents.claim_next(can_mac=False)
        self.assertEqual(job.title, "Schritt 1")
        agents.finish_run(job.run_id, "failed", "Ging wieder nicht.")             # now the user decides
        explain = agents.claim_next(can_mac=False)
        self.assertEqual(explain.purpose, "explain")
        agents.finish_run(explain.run_id, "failed", "no answer")                  # without an explanation it waits too
        self.assertIsNone(agents.claim_next(can_mac=False))                       # step 2 waits
        self.assertTrue(agents.decide(self.a.id, self.task().id, "cancel"))       # the user decides ...
        self.assertEqual(agents.claim_next(can_mac=False).title, "Schritt 2")     # ... then it goes on


if __name__ == "__main__":
    unittest.main()
