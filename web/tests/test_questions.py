"""Questions of the manager and the roles, answered in "waiting for you", and deciding about tasks there
(questions.py, routes/manager.py; Janis 19.11.2026)."""
import os
import tempfile
import unittest

from app import agents, board, chat, claude_link, db, i18n, managerpage, projects, questions, statusnote, users
from app.routes import manager as manager_routes

ASK = ('Welche Spannung hat das Relais?<ask kind="choice">Welche Spannung hat das Relais?<option>12 V</option>'
       '<option>24 V</option></ask>')


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

    def chat_answer(self, text, prompt="Wie geht es weiter?"):
        chat.send(self.a.id, self.pa.id, prompt)
        job = chat.claim_next()
        self.assertTrue(chat.finish(job.chat_id, True, text))
        return job

    def test_the_manager_asks_and_the_answer_goes_on_as_a_chat_message(self):
        job = self.chat_answer(ASK)
        self.assertIn("<ask kind=", job.prompt)                               # the rule is in his package
        self.assertNotIn("<ask", chat.list_messages(self.a.id, self.pa.id)[-1].answer)
        [q] = questions.open_questions(self.a.id, self.pa.id)
        self.assertEqual((q.role, q.kind, q.options, q.task_id), ("chef", "choice", ["12 V", "24 V"], None))
        self.assertEqual(manager_routes.answer_question(q.id, "12 V", user=self.b).status_code, 404)   # not B's
        self.assertEqual(manager_routes.answer_question(q.id, "  ", user=self.a).status_code, 404)    # nothing said
        self.assertEqual(manager_routes.answer_question(q.id, "12 V", user=self.a), {"ok": True, "sent": True})
        self.assertEqual(questions.open_questions(self.a.id, self.pa.id), [])
        message = chat.list_messages(self.a.id, self.pa.id)[-1]
        self.assertEqual(message.prompt, i18n.t("de", "w_answer_prompt", question="Welche Spannung hat das Relais?",
                                                 answer="12 V"))
        self.assertNotIn("<answers>\n- You asked", chat.claim_next().prompt)               # sent as a message, not twice

    def test_while_a_question_runs_the_answer_comes_with_the_next_one(self):
        self.chat_answer(ASK)
        [q] = questions.open_questions(self.a.id, self.pa.id)
        chat.send(self.a.id, self.pa.id, "Noch etwas")                          # runs now
        self.assertEqual(manager_routes.answer_question(q.id, "24 V", user=self.a), {"ok": True, "sent": False})
        job = chat.claim_next()
        self.assertIn("<answers>\n- You asked: Welche Spannung hat das Relais?\n  The user answered: 24 V", job.prompt)
        chat.finish(job.chat_id, True, "Danke.")
        chat.send(self.a.id, self.pa.id, "Und jetzt?")
        self.assertNotIn("<answers>\n- You asked", chat.claim_next().prompt)               # delivered once

    def test_a_role_asks_in_a_run_and_the_answer_comes_with_the_next_run(self):
        item = board.create_item(self.a.id, self.pa.id, "minor", "Relais schalten")
        job = agents.claim_next(can_mac=False)                                  # made by hand: it starts by itself
        self.assertEqual(job.title, "Relais schalten")
        self.assertIn("<ask kind=", job.prompt)
        self.assertTrue(agents.finish_run(job.run_id, "done", "Gebaut mit 12 V.\n" + ASK.split("?", 1)[1]))
        [q] = questions.open_questions(self.a.id, self.pa.id)
        self.assertEqual((q.role, q.task_id), ("programmer", agents.item_task(self.a.id, item.id).id))
        self.assertEqual(manager_routes.answer_question(q.id, "24 V", user=self.a), {"ok": True, "sent": False})
        tester = agents.claim_next(can_mac=False)
        self.assertEqual(tester.role, "tester")
        self.assertIn("The user answered: 24 V", tester.prompt)
        self.assertEqual(chat.list_messages(self.a.id, self.pa.id), [])          # nothing went to the chat

    def test_deciding_in_the_tile_with_a_remark(self):
        item = board.create_item(self.a.id, self.pa.id, "minor", "Relais schalten")
        for result in ("done", "pass", "ok"):
            job = agents.claim_next(can_mac=False)
            agents.finish_run(job.run_id, result, "Bericht")
        task = agents.item_task(self.a.id, item.id)
        self.assertEqual(task.status, "awaiting_approval")
        self.assertEqual(manager_routes.decide_task(task.id, "approve", "", user=self.b).status_code, 404)
        self.assertEqual(manager_routes.decide_task(task.id, "nonsense", "", user=self.a).status_code, 400)
        self.assertEqual(manager_routes.decide_task(task.id, "reject", "Bitte 24 V nehmen.", user=self.a), {"ok": True})
        again = agents.get_task(self.a.id, task.id)
        self.assertEqual((again.status, again.note), ("coding", "Bitte 24 V nehmen."))
        self.assertIn("Bitte 24 V nehmen.", agents.claim_next(can_mac=False).prompt)   # the programmer reads it

    def test_the_tile_shows_questions_and_decisions_with_their_fields(self):
        self.chat_answer(ASK)
        item = board.create_item(self.a.id, self.pa.id, "minor", "Relais schalten")
        for result in ("done", "pass", "ok"):
            job = agents.claim_next(can_mac=False)
            agents.finish_run(job.run_id, result, "Bericht")
        waiting = [(t, agents.last_report(self.a.id, t.id)) for t in agents.waiting_tasks(self.a.id, self.pa.id)]
        tile = managerpage._waiting_tile("de", "", waiting, [], questions.open_questions(self.a.id, self.pa.id))
        self.assertIn("Der Manager fragt", tile)
        self.assertIn('data-reply="12 V"', tile)
        self.assertIn('class="w-input"', tile)
        self.assertIn('data-decide="approve"', tile)
        self.assertIn('data-decide="reject"', tile)
        self.assertIn("Bemerkung für den Programmierer", tile)
        self.assertIn('<span class="count">2</span>', tile)
        self.assertTrue(item.id)

    def test_too_many_or_the_same_question_are_dropped(self):
        from app import reply
        with db.connect() as conn:
            ask = reply.Ask("Frage?", "text", "small")
            self.assertIsNotNone(questions.add(conn, self.pa.id, "chef", ask))
            self.assertIsNone(questions.add(conn, self.pa.id, "chef", ask))        # the same one is open
            for n in range(questions.MAX_OPEN - 1):
                questions.add(conn, self.pa.id, "chef", reply.Ask(f"Frage {n}?", "text", "small"))
            self.assertIsNone(questions.add(conn, self.pa.id, "chef", reply.Ask("Eine zu viel?", "text", "small")))
        self.assertEqual(questions.open_questions(self.b.id, self.pa.id), [])   # nothing for another user


if __name__ == "__main__":
    unittest.main()
