"""Questions of the roles: first to the manager, then, written anew, to the user in "waiting for you"; decisions on
tasks that stopped; nothing goes into the manager chat (questions.py, routes/manager.py; Janis 22.11.2026)."""
import os
import tempfile
import unittest

from app import agents, board, chat, claude_link, db, managerpage, projects, questions, reply, statusnote, users
from app.routes import manager as manager_routes

ASK = '<ask kind="choice">Welche Spannung hat das Relais?<option>12 V</option><option>24 V</option></ask>'
CHANGE = ("relay.py | 1 +", "+ON = 1\n")


class QuestionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.a = users.create_user("a@example.com", "Aaaa!pass12")
        self.b = users.create_user("b@example.com", "Bbbb!pass12")
        self.pa = projects.create_project(self.a.id, "Heizung")
        statusnote._LAST_SCAN["at"] = 2 ** 40
        claude_link.begin(self.a.id)
        claude_link.complete(self.a.id, True)

    def tearDown(self):
        self.tmp.cleanup()

    def task(self):
        return agents.list_tasks(self.a.id, self.pa.id)[0]

    def test_the_manager_chat_asks_in_the_chat_itself(self):
        chat.send(self.a.id, self.pa.id, "Wie geht es weiter?")
        job = chat.claim_next()
        self.assertNotIn("<ask kind=", job.prompt)                            # no question marker in his package
        self.assertTrue(chat.finish(job.chat_id, True, "Kurz gefragt:" + ASK))
        answer = chat.list_messages(self.a.id, self.pa.id)[-1].answer
        self.assertIn("Welche Spannung hat das Relais?", answer)              # a marked question stays as text
        self.assertIn("- 12 V", answer)
        self.assertEqual(questions.open_questions(self.a.id, self.pa.id), [])   # never in "waiting for you"

    def test_a_role_asks_the_manager_writes_it_anew_and_the_user_answers_in_the_tile(self):
        board.create_item(self.a.id, self.pa.id, "minor", "Relais schalten")
        job = agents.claim_next(can_mac=False)
        self.assertTrue(agents.finish_run(job.run_id, "question", "Ich brauche die Spannung.\n" + ASK, change=CHANGE,
                                          committed=True))
        decide = agents.claim_next(can_mac=False)
        self.assertEqual(decide.purpose, "decide")
        agents.finish_run(decide.run_id, "done", '<ask kind="choice">Mit welcher Spannung läuft die Heizung?'
                                                 '<option recommended>12 V, wie das Bordnetz</option><option>24 V</option></ask>')
        [q] = questions.open_questions(self.a.id, self.pa.id)
        self.assertEqual((q.role, q.task_id, q.via, q.blocks, q.recommended), ("programmer", self.task().id, "user",
                                                                               True, 0))
        tile = managerpage._waiting_tile("de", "", [], [], [q])
        self.assertIn('class="sq-btn go rec" type="button" data-reply="12 V, wie das Bordnetz"', tile)   # suggestion first
        self.assertIn('data-reply="24 V"', tile)
        self.assertIn('class="w-input"', tile)
        self.assertEqual(manager_routes.answer_question(q.id, "12 V", user=self.b).status_code, 404)   # not B's
        self.assertEqual(manager_routes.answer_question(q.id, "  ", user=self.a).status_code, 404)    # nothing said
        self.assertEqual(manager_routes.answer_question(q.id, "12 V, wie das Bordnetz", user=self.a), {"ok": True})
        job = agents.claim_next(can_mac=False)
        self.assertEqual(job.role, "programmer")
        self.assertIn("Answer of the user: 12 V, wie das Bordnetz", job.prompt)
        self.assertEqual(chat.list_messages(self.a.id, self.pa.id), [])         # nothing went to the chat

    def test_a_question_that_does_not_hold_the_task_comes_with_a_later_run(self):
        board.create_item(self.a.id, self.pa.id, "minor", "Relais schalten")
        job = agents.claim_next(can_mac=False)
        agents.finish_run(job.run_id, "done", "Gebaut mit 12 V.\n" + ASK, change=CHANGE, committed=True)
        self.assertEqual((self.task().stage, self.task().hold), ("testing", ""))   # it goes on
        decide = agents.claim_next(can_mac=False)                             # the manager's question job first (older)
        self.assertEqual(decide.purpose, "decide")
        agents.finish_run(decide.run_id, "done", "<decide>12 V, das Bordnetz hat 12 V.</decide>")
        tester = agents.claim_next(can_mac=False)
        self.assertEqual(tester.role, "tester")
        self.assertIn("Answer of the manager: 12 V, das Bordnetz hat 12 V.", tester.prompt)

    def test_deciding_in_the_tile(self):
        board.create_item(self.a.id, self.pa.id, "minor", "Relais schalten")
        job = agents.claim_next(can_mac=False)
        agents.finish_run(job.run_id, "done", "Gebaut", change=None)          # changed nothing: the user decides
        task = self.task()
        tile = managerpage._waiting_tile("de", "", [(task, "Gebaut")], [], [])
        for choice in ("again", "accept", "cancel"):
            self.assertIn(f'data-decide="{choice}"', tile)
        self.assertIn("hat aber nichts geändert", tile)                        # the hub's reason until the manager wrote
        self.assertEqual(manager_routes.decide_task(task.id, "again", "", user=self.b).status_code, 404)
        self.assertEqual(manager_routes.decide_task(task.id, "approve", "", user=self.a).status_code, 400)
        self.assertEqual(manager_routes.decide_task(task.id, "again", "Bitte 24 V nehmen.", user=self.a), {"ok": True})
        again = self.task()
        self.assertEqual((again.stage, again.hold, again.hint), ("coding", "", "Bitte 24 V nehmen."))
        self.assertIn("Bitte 24 V nehmen.", agents.claim_next(can_mac=False).prompt)   # the programmer reads it

    def test_too_many_or_the_same_question_are_dropped(self):
        board.create_item(self.a.id, self.pa.id, "minor", "Relais schalten")
        agents.claim_next(can_mac=False)
        task_id = self.task().id
        with db.connect() as conn:
            ask = reply.Ask("Frage?", "text", "small")
            self.assertIsNotNone(questions.add(conn, self.pa.id, "tester", ask, task_id))
            self.assertIsNone(questions.add(conn, self.pa.id, "tester", ask, task_id, blocks=True))   # the same one ...
            self.assertEqual(questions.open_blocking(conn, task_id), 1)                              # ... now holds it
            for n in range(questions.MAX_OPEN - 1):
                questions.add(conn, self.pa.id, "tester", reply.Ask(f"Frage {n}?", "text", "small"), task_id)
            self.assertIsNone(questions.add(conn, self.pa.id, "tester", reply.Ask("Eine zu viel?", "text", "small"),
                                            task_id))
        self.assertEqual(questions.open_questions(self.b.id, self.pa.id), [])   # nothing for another user


if __name__ == "__main__":
    unittest.main()
