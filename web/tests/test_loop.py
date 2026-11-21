"""The agents' loop after the calculator test (Janis, 21.11.2026): what belongs to a task is done in it, a role puts only
bugs outside it and new features on the board, the environment never goes there, repeats are kept once, a task's
questions go with it, and a clean task merges by itself as the manager's autonomy allows."""
import os
import tempfile
import unittest

from app import agents, board, claude_link, db, projects, prompts, questions, reply, statusnote, users
from app.managerpage import _question_row

DIFF = ("calc.js | 2 ++\n 1 file changed", "diff --git a/calc.js b/calc.js\n+export const add = (a, b) => a + b;\n")


class SimilarTest(unittest.TestCase):
    def test_repeats_of_the_calculator_test(self):
        for a, b in (("Anzeige ans Ende scrollen", "app.js: Anzeige ans Ende scrollen"),
                     ("Anzeige bei langer Eingabe ans Ende scrollen", "Anzeige: bei langer Zahl zum Ende scrollen"),
                     ("Node in der Agent-Umgebung bereitstellen", "Node in der Agent-Umgebung installieren"),
                     ("Ziffern und Komma nach % sperren", "Nach % keine Ziffer/Komma zulassen")):
            self.assertTrue(reply.similar(a, b), (a, b))
        for a, b in (("Negative Zahlen per Eingabe ermöglichen", "Taste 0 über zwei Spalten (.wide)"),
                     ("Tastatureingabe", "Rechenlogik calc.js"), ("Login", "Logout")):
            self.assertFalse(reply.similar(a, b), (a, b))

    def test_env_marker(self):
        found = reply.parse("Fertig. <env>Kein Browser für die Sichtprüfung</env> <env>Kein Browser für die "
                            "Sichtprüfung</env>\nRESULT: done")
        self.assertEqual(found.envs, ["Kein Browser für die Sichtprüfung"])
        self.assertNotIn("<env>", found.text)

    def test_the_packages_say_it(self):
        self.assertIn("polish", prompts.ROLES["programmer"])
        self.assertIn("never a board item", prompts.ROLES["tester"])
        self.assertIn("<env>", prompts.FOUND)
        self.assertNotIn("minor", prompts.FOUND)
        self.assertIn("never plan a separate polish", prompts.BOARD)
        self.assertIn("env", prompts.ALLOWED[("programmer", "run")])


class LoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        statusnote._LAST_SCAN["at"] = 2 ** 40
        self.a = users.create_user("a@example.com", "Aaaa!pass12")
        self.pa = projects.create_project(self.a.id, "Rechner")
        claude_link.begin(self.a.id)
        claude_link.complete(self.a.id, True)

    def tearDown(self):
        self.tmp.cleanup()

    def start(self, kind="minor", title="Addieren"):
        item = board.create_item(self.a.id, self.pa.id, kind, title)
        return agents.start_item(self.a.id, item.id)

    def items(self):
        return {i.title: i for i in board.list_items(self.a.id, self.pa.id)}

    def to_review(self, report="Gebaut."):
        job = agents.claim_next(can_mac=False)
        agents.finish_run(job.run_id, "done", report, change=DIFF, tests=(0, "ok 1\n"))
        return agents.claim_next(can_mac=False)

    def test_a_role_puts_only_bugs_and_features_on_the_board_and_the_environment_never(self):
        self.start()
        job = agents.claim_next(can_mac=False)
        agents.finish_run(job.run_id, "done", "Gebaut.\n"
                          '<task kind="minor" title="Anzeige ans Ende scrollen">Feinschliff</task>\n'
                          '<task kind="bug" title="Löschen-Taste leert den Speicher nicht">in memory.js</task>\n'
                          '<task kind="major" title="Verlauf der Rechnungen">eine Liste</task>\n'
                          "<env>Kein Browser für die Sichtprüfung</env>", change=DIFF, tests=(0, "ok\n"))
        items = self.items()
        self.assertNotIn("Anzeige ans Ende scrollen", items)                         # part of the task: done in it
        self.assertEqual(items["Löschen-Taste leert den Speicher nicht"].status, "open")
        self.assertEqual(items["Verlauf der Rechnungen"].status, "proposed")         # waits for the user's yes
        [note] = questions.open_questions(self.a.id, self.pa.id)
        self.assertEqual((note.kind, note.text, note.task_id), ("note", "Kein Browser für die Sichtprüfung", None))
        self.assertIn("Erledigt", _question_row("de", note))
        self.assertNotIn("w-input", _question_row("de", note))
        done = questions.answer(self.a.id, note.id, "ok")
        self.assertEqual(done.status, "delivered")                                   # it goes to no AI

    def test_repeats_add_their_context_to_the_item_there_is(self):
        with db.connect() as conn:
            first = board.add_from_ai(conn, self.pa.id, "bug", "Anzeige ans Ende scrollen", "in app.js", True)
            self.assertIsNone(board.add_from_ai(conn, self.pa.id, "bug", "app.js: Anzeige ans Ende scrollen",
                                                "auch bei Ergebnissen", True))
            details = conn.execute("SELECT details FROM board_items WHERE id = ?", (first,)).fetchone()[0]
        self.assertIn("auch bei Ergebnissen", details)
        self.assertEqual(len(self.items()), 1)

    def test_a_similar_open_question_is_kept_once_and_a_tasks_questions_go_with_it(self):
        task = self.start()
        with db.connect() as conn:
            self.assertIsNotNone(questions.add(conn, self.pa.id, "programmer",
                                               reply.Ask("Soll die %-Taste bleiben?", "text", "small", []), task.id))
            self.assertIsNone(questions.add(conn, self.pa.id, "reviewer",
                                            reply.Ask("Soll die %-Taste bleiben oder weg?", "text", "small", []), task.id))
        agents.decide(self.a.id, task.id, "cancel")
        self.assertEqual(questions.open_questions(self.a.id, self.pa.id), [])

    def test_a_clean_improvement_merges_by_itself(self):
        task = self.start("minor")
        job = self.to_review()
        self.assertEqual(job.role, "reviewer")
        agents.finish_run(job.run_id, "ok", "Keine Einwände.")
        self.assertNotEqual(agents.get_task(self.a.id, task.id).status, "awaiting_approval")   # merged by itself

    def test_a_new_feature_waits(self):
        task = self.start("major", "Verlauf")
        agents.finish_run(self.to_review().run_id, "ok", "Keine Einwände.")
        self.assertEqual(agents.get_task(self.a.id, task.id).status, "awaiting_approval")

    def test_everything_waits_when_the_manager_asks_for_all(self):
        agents.configure(self.a.id, autonomy="all")
        task = self.start("bug", "Minus doppelt")
        agents.finish_run(self.to_review().run_id, "ok", "Keine Einwände.")
        self.assertEqual(agents.get_task(self.a.id, task.id).status, "awaiting_approval")

    def test_red_tests_or_an_open_question_keep_it_waiting(self):
        task = self.start("minor")
        job = self.to_review()
        with db.connect() as conn:
            questions.add(conn, self.pa.id, "reviewer", reply.Ask("Komma oder Punkt?", "text", "small", []), task.id)
        agents.finish_run(job.run_id, "ok", "Keine Einwände.")
        self.assertEqual(agents.get_task(self.a.id, task.id).status, "awaiting_approval")

if __name__ == "__main__":
    unittest.main()
