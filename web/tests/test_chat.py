"""TEMPORARY test chat: the question queue, who may ask, the routes and the project page."""
import dataclasses
import os
import tempfile
import unittest
from pathlib import Path

from app import board, chat, claude_link, db, projectpage, projects, users
from app.routes import chat as routes
from app.routes import runner as runner_routes


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        claude_link.BASE_DIR = Path(self.tmp.name) / "claude"
        self.a = users.create_user("a@example.com", "Aaaa!pass12")
        self.b = users.create_user("b@example.com", "Bbbb!pass12")
        self.pa = projects.create_project(self.a.id, "Project of A")
        self.pb = projects.create_project(self.b.id, "Project of B")

    def tearDown(self):
        self.tmp.cleanup()

    def connect(self, user):
        claude_link.begin(user.id)
        claude_link.complete(user.id, True)


class ChatQueueTest(Base):
    def test_question_and_answer(self):
        self.connect(self.a)
        message = chat.send(self.a.id, self.pa.id, "  Hello?  ")
        self.assertEqual((message.prompt, message.status), ("Hello?", "queued"))
        job = chat.claim_next()
        self.assertEqual((job.user_id, job.prompt, job.model), (self.a.id, "Hello?", "haiku"))
        self.assertIsNone(chat.claim_next())                          # one at a time
        self.assertTrue(chat.finish(job.chat_id, True, "Hi!", 5, 2))
        self.assertFalse(chat.finish(job.chat_id, True, "again"))      # only once
        shown = chat.list_messages(self.a.id, self.pa.id)
        self.assertEqual([(m.status, m.answer) for m in shown], [("done", "Hi!")])
        chat.send(self.a.id, self.pa.id, "And now?")                   # the next question is allowed

    def test_rules(self):
        with self.assertRaises(ValueError) as problem:
            chat.send(self.a.id, self.pa.id, "x")                      # Claude not connected
        self.assertEqual(str(problem.exception), "claude")
        self.connect(self.a)
        for bad in ("", "   ", "x" * (chat.MAX_PROMPT + 1)):
            with self.assertRaises(ValueError):
                chat.send(self.a.id, self.pa.id, bad)
        chat.send(self.a.id, self.pa.id, "first")
        with self.assertRaises(ValueError) as problem:
            chat.send(self.a.id, self.pa.id, "second")                 # first one is still open
        self.assertEqual(str(problem.exception), "busy")

    def test_stale_questions_fail_instead_of_blocking(self):
        self.connect(self.a)
        chat.send(self.a.id, self.pa.id, "lost", now=1000)
        chat.send(self.a.id, self.pa.id, "next", now=1000 + chat.RUN_SECONDS + 1)
        self.assertEqual([m.status for m in chat.list_messages(self.a.id, self.pa.id)], ["failed", "queued"])

    def test_a_failed_answer_keeps_its_reason(self):
        self.connect(self.a)
        job_id = chat.send(self.a.id, self.pa.id, "q").id
        chat.claim_next()
        chat.finish(job_id, False, "Timeout: no answer in time.")
        last = chat.list_messages(self.a.id, self.pa.id)[-1]
        self.assertEqual((last.status, last.answer), ("failed", "Timeout: no answer in time."))

    def test_nobody_else_s_claude_is_used(self):
        self.connect(self.a)
        self.connect(self.b)
        chat.send(self.b.id, self.pb.id, "from B")
        claude_link.disconnect(self.b.id)                              # B loses his connection, A keeps his
        self.assertIsNone(chat.claim_next())
        self.assertEqual(chat.list_messages(self.b.id, self.pb.id)[0].status, "queued")

    def test_only_the_last_messages_are_listed(self):
        self.connect(self.a)
        for i in range(chat.KEEP + 3):
            m = chat.send(self.a.id, self.pa.id, f"q{i}")
            chat.claim_next()
            chat.finish(m.id, True, f"a{i}")
        shown = chat.list_messages(self.a.id, self.pa.id)
        self.assertEqual((len(shown), shown[0].prompt, shown[-1].prompt), (chat.KEEP, "q3", f"q{chat.KEEP + 2}"))

    def test_users_are_separate(self):
        self.connect(self.a)
        self.connect(self.b)
        chat.send(self.a.id, self.pa.id, "private of A")
        for call in (lambda: chat.send(self.b.id, self.pa.id, "into A's project"),):
            with self.assertRaises(ValueError) as problem:
                call()
            self.assertEqual(str(problem.exception), "project")
        self.assertEqual(chat.list_messages(self.b.id, self.pa.id), [])
        chat.send(self.b.id, self.pb.id, "mine")                       # A's open question does not block B
        self.assertEqual(len(chat.list_messages(self.a.id, self.pa.id)), 1)

    def test_delete_all_removes_only_the_own_history(self):
        self.connect(self.a)
        self.connect(self.b)
        second = projects.create_project(self.a.id, "Second of A")
        for project in (self.pa, second):
            m = chat.send(self.a.id, project.id, "q")
            chat.claim_next()
            chat.finish(m.id, True, "a")
        chat.send(self.b.id, self.pb.id, "of B")
        self.assertEqual(chat.delete_all(self.a.id), 2)                 # both projects of A
        self.assertEqual(chat.list_messages(self.a.id, self.pa.id), [])
        self.assertEqual([m.prompt for m in chat.list_messages(self.b.id, self.pb.id)], ["of B"])
        self.assertEqual(chat.delete_all(self.a.id), 0)                 # nothing left, nothing breaks
        self.assertEqual(claude_link.status(self.a.id), "connected")    # the connection is not touched

    def test_late_answer_for_a_deleted_question_is_ignored(self):
        self.connect(self.a)
        m = chat.send(self.a.id, self.pa.id, "q")
        chat.claim_next()
        chat.delete_all(self.a.id)
        self.assertFalse(chat.finish(m.id, True, "late"))
        self.assertEqual(chat.list_messages(self.a.id, self.pa.id), [])

    def test_deleting_the_project_removes_the_messages(self):
        self.connect(self.a)
        chat.send(self.a.id, self.pa.id, "q")
        projects.delete_project(self.a.id, self.pa.id)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0], 0)


class ChatRoutesTest(Base):
    def test_ask_and_poll(self):
        self.connect(self.a)
        self.assertEqual(routes.messages(self.pa.id, user=self.a), {"ok": True, "messages": []})
        sent = routes.ask(self.pa.id, "Hello", user=self.a)
        self.assertTrue(sent["ok"])
        got = routes.messages(self.pa.id, user=self.a)["messages"]
        self.assertEqual([(m["prompt"], m["status"]) for m in got], [("Hello", "queued")])
        busy = routes.ask(self.pa.id, "again", user=self.a)
        self.assertEqual(busy.status_code, 409)
        self.assertIn("Frage", busy.body.decode())                     # message in the user's language

    def test_problems_are_answered_not_raised(self):
        self.assertEqual(routes.ask(self.pa.id, "x", user=self.a).status_code, 409)      # not connected
        self.connect(self.a)
        self.assertEqual(routes.ask(self.pa.id, "  ", user=self.a).status_code, 400)
        self.assertEqual(routes.ask(self.pb.id, "x", user=self.a).status_code, 404)      # B's project
        english = dataclasses.replace(self.b, language="en")
        self.assertIn("not connected", routes.ask(self.pb.id, "x", user=english).body.decode())  # B has no Claude

    def test_delete_history_route(self):
        self.connect(self.a)
        routes.ask(self.pa.id, "Hello", user=self.a)
        self.assertEqual(routes.delete_history(user=self.a), {"ok": True, "deleted": 1})
        self.assertEqual(routes.messages(self.pa.id, user=self.a)["messages"], [])
        self.assertEqual(routes.delete_history(user=self.b), {"ok": True, "deleted": 0})   # B has nothing, A's is gone

    def test_routes_need_a_login(self):
        from app.deps import api_user
        for route in routes.router.routes:
            self.assertTrue(any(d.call is api_user for d in route.dependant.dependencies), route.path)

    def test_runner_side_routes(self):
        self.connect(self.a)
        chat.send(self.a.id, self.pa.id, "Hi")
        job = runner_routes.chat_claim()["job"]
        self.assertEqual(sorted(job), ["chat_id", "model", "prompt", "user_id"])
        self.assertEqual(runner_routes.chat_finish(job["chat_id"], "1", "Hello back", 3, 4), {"ok": True})
        self.assertEqual(runner_routes.chat_finish(job["chat_id"], "1", "again", 0, 0).status_code, 409)
        self.assertEqual(chat.list_messages(self.a.id, self.pa.id)[0].answer, "Hello back")
        for route in runner_routes.router.routes:                       # the new routes hang on the token, too
            self.assertTrue(any(d.call is runner_routes.runner_only for d in route.dependant.dependencies), route.path)


class ChatPanelTest(Base):
    def test_panel_is_on_the_project_page_in_both_languages(self):
        for lang, title in (("de", "Claude testen"), ("en", "Test Claude")):
            html = projectpage.render(dataclasses.replace(self.a, language=lang), self.pa, [])
            self.assertIn('id="chat"', html)
            self.assertIn(title, html)
            self.assertNotIn("%t.", html)
        self.assertIn("chat.js", projectpage.SCRIPTS)

    def test_script_has_no_texts_and_never_uses_innerhtml(self):
        script = (Path(__file__).parent.parent / "app" / "static" / "chat.js").read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", script)
        for text in ("Claude testen", "Senden", "Fehlgeschlagen", "Du "):
            self.assertNotIn(text, script)


if __name__ == "__main__":
    unittest.main()
