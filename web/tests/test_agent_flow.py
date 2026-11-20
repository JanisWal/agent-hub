"""The chain with the hub's own checks (20.11.2026): the change (diff) goes to tester and reviewer, the project's own
tests (hub-test.sh) decide instead of an AI tester, and a piece that went to the user stops the pieces after it."""
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

    def start(self, title="Addieren"):
        item = board.create_item(self.a.id, self.pa.id, "minor", title)
        return agents.start_item(self.a.id, item.id)

    def test_green_tests_go_to_the_reviewer_who_reads_the_change(self):
        task = self.start()
        job = agents.claim_next(can_mac=False)
        self.assertIn("hub-test.sh", job.prompt)                                  # the programmer keeps the tests
        self.assertTrue(agents.finish_run(job.run_id, "done", "Gebaut.", change=DIFF, tests=(0, "ok 1 - add\n")))
        job = agents.claim_next(can_mac=False)
        self.assertEqual(job.role, "reviewer")                                    # no AI tester: the tests decided
        self.assertIn("<change>", job.prompt)
        self.assertIn("+export const add", job.prompt)
        self.assertIn("hub-test.sh passed", job.prompt)
        runs = agents.task_runs(self.a.id, task.id)
        tester = [r for r in runs if r.role == "tester"][0]
        self.assertEqual((tester.model, tester.result, tester.tokens_in), (agents.HUB_MODEL, "pass", 0))

    def test_red_tests_send_it_back_to_the_programmer_with_their_output(self):
        task = self.start()
        job = agents.claim_next(can_mac=False)
        agents.finish_run(job.run_id, "done", "Gebaut.", change=DIFF, tests=(1, "not ok 1 - add\nFAIL"))
        job = agents.claim_next(can_mac=False)
        self.assertEqual((job.role, job.round), ("programmer", 2))
        self.assertIn("not ok 1 - add", job.prompt)                               # the report of the hub's test run
        self.assertEqual(agents.get_task(self.a.id, task.id).status, "coding")

    def test_without_tests_the_ai_tester_gets_the_change(self):
        self.start()
        job = agents.claim_next(can_mac=False)
        agents.finish_run(job.run_id, "done", "Gebaut.", change=DIFF)
        job = agents.claim_next(can_mac=False)
        self.assertEqual(job.role, "tester")
        self.assertIn("+export const add", job.prompt)
        self.assertNotIn("<tests>", job.prompt)

    def test_a_result_the_role_does_not_have_is_a_failed_run(self):
        task = self.start()
        job = agents.claim_next(can_mac=False)
        self.assertTrue(agents.finish_run(job.run_id, "pass", "Fertig."))      # a tester's word from the programmer
        self.assertEqual(agents.get_task(self.a.id, task.id).status, "escalated")
        self.assertIn("does not have", agents.task_runs(self.a.id, task.id)[0].report)

    def test_an_escalated_piece_stops_the_pieces_after_it(self):
        with db.connect() as conn:
            one = board.add_from_ai(conn, self.pa.id, "minor", "Schritt 1", "Grundgerüst", approved=True, source="manager")
            board.add_from_ai(conn, self.pa.id, "minor", "Schritt 2", "baut auf Schritt 1", approved=True, source="manager")
        job = agents.claim_next(can_mac=False)
        self.assertEqual(job.title, "Schritt 1")
        agents.finish_run(job.run_id, "failed", "Ging nicht.")                    # to the user
        self.assertIsNone(agents.claim_next(can_mac=False))                       # step 2 waits
        task = agents.item_task(self.a.id, one)
        self.assertTrue(agents.decide(self.a.id, task.id, "cancel"))              # the user decides ...
        self.assertEqual(agents.claim_next(can_mac=False).title, "Schritt 2")     # ... then it goes on


if __name__ == "__main__":
    unittest.main()
