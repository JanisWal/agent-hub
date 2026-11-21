"""The chat window: the question queue, who may ask, the routes and the project page."""
import dataclasses
import os
import tempfile
import unittest
from pathlib import Path

from app import board, chat, claude_link, db, projectpage, projects, prompts, users
from app.routes import chat as routes
from app.routes import runner as runner_routes


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
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
        self.assertEqual((job.user_id, job.model), (self.a.id, "sonnet"))  # Sonnet unless the user picks another
        self.assertTrue(job.prompt.endswith("Question of the user:\nHello?"))
        self.assertIsNone(chat.claim_next())                          # one at a time
        self.assertTrue(chat.finish(job.chat_id, True, "Hi!", 5, 2))
        self.assertFalse(chat.finish(job.chat_id, True, "again"))      # only once
        shown = chat.list_messages(self.a.id, self.pa.id)
        self.assertEqual([(m.status, m.answer) for m in shown], [("done", "Hi!")])
        chat.send(self.a.id, self.pa.id, "And now?")                   # the next question is allowed

    def test_thoughts_are_kept_while_it_runs_and_shown_with_the_answer(self):
        self.connect(self.a)
        message = chat.send(self.a.id, self.pa.id, "Hello?")
        self.assertFalse(chat.add_thoughts(message.id, "too early"))       # only while it is being answered
        job = chat.claim_next()
        self.assertTrue(chat.add_thoughts(job.chat_id, "\n\nErst lesen, "))
        self.assertTrue(chat.add_thoughts(job.chat_id, "dann antworten."))
        self.assertFalse(chat.add_thoughts(job.chat_id, ""))
        running = routes.messages(self.pa.id, user=self.a)["messages"][0]
        self.assertEqual((running["status"], running["thoughts"]), ("running", "Erst lesen, dann antworten."))
        self.assertTrue(chat.add_thoughts(job.chat_id, "x" * (chat.MAX_THOUGHTS + 10)))
        self.assertEqual(len(chat.list_messages(self.a.id, self.pa.id)[0].thoughts), chat.MAX_THOUGHTS)
        chat.finish(job.chat_id, True, "Hi!")
        self.assertFalse(chat.add_thoughts(job.chat_id, "late"))
        self.assertTrue(routes.messages(self.pa.id, user=self.a)["messages"][0]["thoughts"].startswith("Erst lesen"))
        later = chat.send(self.a.id, self.pa.id, "And?")                    # never part of the next question's context
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM chat_messages WHERE id = ?", (later.id,)).fetchone()
            self.assertNotIn("Erst lesen", prompts.manager_chat(conn, row))
        self.assertEqual(routes.messages(self.pb.id, user=self.a)["messages"], [])   # A sees nothing of B's project

    def test_a_failed_answer_shows_no_thoughts(self):
        self.connect(self.a)
        job_id = chat.send(self.a.id, self.pa.id, "q").id
        chat.claim_next()
        chat.add_thoughts(job_id, "Hmm")
        chat.finish(job_id, False, "timeout")
        self.assertEqual(routes.messages(self.pa.id, user=self.a)["messages"][0]["thoughts"], "")

    def test_rules(self):
        with self.assertRaises(ValueError) as problem:
            chat.send(self.a.id, self.pa.id, "x")                      # no AI connected at all
        self.assertEqual(str(problem.exception), "none")
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
        chat.send(self.a.id, self.pa.id, "next", now=1000 + chat.serversettings.chat_seconds() + 121)
        self.assertEqual([m.status for m in chat.list_messages(self.a.id, self.pa.id)], ["failed", "queued"])

    def test_a_failed_answer_keeps_its_reason(self):
        self.connect(self.a)
        job_id = chat.send(self.a.id, self.pa.id, "q").id
        chat.claim_next()
        chat.finish(job_id, False, "Timeout: no answer in time.")
        last = chat.list_messages(self.a.id, self.pa.id)[-1]
        self.assertEqual((last.status, last.answer), ("failed", "Timeout: no answer in time."))

    def test_every_answer_goes_into_the_archive_and_stays_there(self):
        """Janis, 14.11.2026: an archive of all chats, only for the user; clearing the chat leaves it alone, and the
        manager never reads it."""
        self.connect(self.a)
        first = chat.send(self.a.id, self.pa.id, "What about the relay?").id
        chat.claim_next()
        chat.finish(first, True, "Use the 12 V one.")
        second = chat.send(self.a.id, self.pa.id, "And the fuse?").id
        chat.claim_next()
        chat.finish(second, False, "Failed to authenticate. API Error: 401")
        entries = chat.archive(self.a.id, self.pa.id)
        self.assertEqual([(e.prompt, e.answer, e.failure) for e in entries],
                         [("What about the relay?", "Use the 12 V one.", ""), ("And the fuse?", "", "auth")])
        chat.delete_all(self.a.id)
        self.assertEqual(chat.list_messages(self.a.id, self.pa.id), [])
        self.assertEqual(len(chat.archive(self.a.id, self.pa.id)), 2)                     # the archive keeps it
        third = chat.send(self.a.id, self.pa.id, "next").id
        job = chat.claim_next()
        self.assertNotIn("12 V", job.prompt)                                              # the manager does not see it
        self.assertEqual(chat.archive(self.b.id, self.pa.id), [])                          # B sees nothing of A
        self.assertEqual(chat.archive_delete(self.b.id, self.pa.id, [e.id for e in entries]), 0)
        self.assertEqual(routes.archive(self.pa.id, user=self.b)["entries"], [])
        self.assertEqual(chat.archive_delete(self.a.id, self.pa.id, [entries[0].id]), 1)
        self.assertEqual([e.prompt for e in chat.archive(self.a.id, self.pa.id)], ["And the fuse?"])
        got = routes.archive(self.pa.id, user=self.a)["entries"][0]
        self.assertEqual((got["answer"], got["failure"]), ("", "auth"))                    # no raw error, as in the chat
        chat.finish(third, True, "ok")

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

    def test_each_user_keeps_a_limited_history(self):
        self.connect(self.a)
        self.connect(self.b)
        first = chat.send(self.b.id, self.pb.id, "of B")
        chat.claim_next()                                                       # B is answered first (the oldest)
        chat.finish(first.id, True, "ok")
        for i in range(chat.MAX_STORED + 5):
            m = chat.send(self.a.id, self.pa.id, f"q{i}")
            chat.claim_next()
            chat.finish(m.id, True, f"a{i}")
        with db.connect() as conn:
            mine = conn.execute("SELECT COUNT(*) FROM chat_messages WHERE user_id = ?", (self.a.id,)).fetchone()[0]
            oldest = conn.execute("SELECT MIN(prompt) FROM chat_messages WHERE user_id = ? AND prompt = 'q0'",
                                  (self.a.id,)).fetchone()[0]
            theirs = conn.execute("SELECT COUNT(*) FROM chat_messages WHERE user_id = ?", (self.b.id,)).fetchone()[0]
        self.assertEqual((mine, oldest, theirs), (chat.MAX_STORED, None, 1))   # the oldest are gone, B is untouched
    def test_modes(self):
        self.connect(self.a)
        self.assertEqual(chat.MODES, ("all", "apart"))                         # the old single modes are gone
        m = chat.send(self.a.id, self.pa.id, "q")
        self.assertEqual(m.mode, "all")                                        # switch on by default: together
        job = chat.claim_next()
        self.assertEqual(job.mode, "all")                                      # the runner learns the mode from the database
        self.assertTrue(job.prompt.endswith("\nq"))
        self.assertIn("a shell with the public internet", job.prompt)
        chat.finish(job.chat_id, True, "a")
        for bad in ("", "plain", "web", "code", "root", "web,code", "code; rm -rf /"):
            with self.assertRaises(ValueError) as problem:
                chat.send(self.a.id, self.pa.id, "x", bad)
            self.assertEqual(str(problem.exception), "mode")

    def test_the_switch_decides_web_and_code_together_or_apart(self):
        from app import agents
        from app.routes import manager as manager_routes
        self.connect(self.a)
        self.assertEqual(manager_routes.manager_settings("", "", "apart", "", user=self.a)["net"], "apart")
        self.assertTrue(routes.ask(self.pa.id, "run it", user=self.a)["ok"])
        self.assertEqual(routes.messages(self.pa.id, user=self.a)["messages"][0]["mode"], "apart")
        job = chat.claim_next()
        self.assertEqual(job.mode, "apart")
        self.assertIn("a shell without internet", job.prompt)                # the manager knows code is offline
        self.assertNotIn("reading web pages", job.prompt)
        chat.finish(job.chat_id, True, "done")
        self.assertEqual(agents.settings(self.b.id)["roles"]["chef"]["net"], "together")   # per user
        self.assertEqual(agents.settings(self.a.id)["roles"]["programmer"]["net"], "together")  # and per agent
        self.assertEqual(manager_routes.manager_settings("", "", "always", "", user=self.a).status_code, 400)
        self.assertEqual(manager_routes.manager_settings("", "", "together", "", user=self.a)["net"], "together")
        chat.send(self.a.id, self.pa.id, "again")
        self.assertEqual(chat.claim_next().mode, "all")

    def test_an_existing_database_gets_the_mode_column(self):
        import sqlite3
        path = os.path.join(self.tmp.name, "old.db")
        old = sqlite3.connect(path)
        old.executescript("""
            CREATE TABLE chat_messages (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, project_id INTEGER NOT NULL,
                prompt TEXT NOT NULL, status TEXT NOT NULL, answer TEXT NOT NULL DEFAULT '',
                tokens_in INTEGER NOT NULL DEFAULT 0, tokens_out INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL, started_at INTEGER);
            INSERT INTO chat_messages (user_id, project_id, prompt, status, created_at) VALUES (1, 1, 'old question', 'done', 5);
        """)
        old.commit()
        old.close()
        db.DB_PATH = path
        with db.connect() as conn:
            columns = [r["name"] for r in conn.execute("PRAGMA table_info(chat_messages)")]
            mode = conn.execute("SELECT mode FROM chat_messages").fetchone()["mode"]
        self.assertIn("mode", columns)
        self.assertEqual(mode, "web")                                           # old questions count as web questions
    def test_the_model_is_the_setting_of_the_manager(self):
        from app import agents
        from app.routes import manager as manager_routes
        self.connect(self.a)
        self.assertEqual(chat.send(self.a.id, self.pa.id, "q").model, "sonnet")   # the manager's default
        chat.finish(chat.claim_next().chat_id, True, "a")
        self.assertEqual(manager_routes.manager_settings("opus", "", "", "", user=self.a),
                         {"ok": True, "model": "opus", "effort": "medium", "autonomy": "major", "net": "together"})
        self.assertTrue(routes.ask(self.pa.id, "via route", user=self.a)["ok"])
        self.assertEqual(routes.messages(self.pa.id, user=self.a)["messages"][-1]["model"], "opus")
        job = chat.claim_next()
        self.assertEqual(job.model, "opus")                                    # from the database, not the runner
        chat.finish(job.chat_id, True, "a")
        self.assertEqual(agents.settings(self.b.id)["roles"]["chef"]["model"], "sonnet")   # B's manager is untouched
        for bad in ("gpt-4", "Sonnet", "sonnet --dangerous", "claude-opus-5-5"):
            with self.assertRaises(ValueError) as problem:
                chat.send(self.a.id, self.pa.id, "x", model=bad)
            self.assertEqual(str(problem.exception), "mode")
            self.assertEqual(manager_routes.manager_settings(bad, "", "", "", user=self.a).status_code, 400)
        self.assertEqual(agents.settings(self.a.id)["roles"]["chef"]["model"], "opus")      # nothing bad was stored

    def test_the_autonomy_is_a_setting_and_the_manager_reads_it(self):
        from app import agents
        from app.routes import manager as manager_routes
        self.connect(self.a)
        self.assertEqual(agents.AUTONOMY, ("auto", "major", "all"))
        self.assertEqual(manager_routes.manager_settings("", "auto", "", "", user=self.a)["autonomy"], "auto")
        self.assertEqual(manager_routes.manager_settings("", "everything", "", "", user=self.a).status_code, 400)
        chat.send(self.a.id, self.pa.id, "q")
        text = chat.claim_next().prompt
        self.assertIn(prompts.AUTONOMY["auto"], text)
        self.assertIn(prompts.AUTONOMY_RULE, text)                                # derive first, ask only what is unclear
        self.assertEqual(agents.settings(self.b.id)["autonomy"], "major")      # per user

    def test_the_manager_knows_the_project_and_remembers_it(self):
        self.connect(self.a)
        projects.update_details(self.a.id, self.pa.id, "Roadster", "Heater control on an ESP32")
        board.create_item(self.a.id, self.pa.id, "bug", "Heater does not switch off")
        board.create_suggestion(self.a.id, self.pa.id, "major", "Diagnosis page")
        done = board.create_item(self.a.id, self.pa.id, "minor", "Old finished thing")
        board.archive(self.a.id, done.id)
        chat.send(self.a.id, self.pa.id, "Which relay?")
        first = chat.claim_next()
        chat.finish(first.chat_id, True, "A 12 V automotive relay.")
        chat.send(self.a.id, self.pa.id, "And the fuse?")
        text = chat.claim_next().prompt
        self.assertTrue(text.startswith(prompts.MANAGER))
        project = text[text.index("<project>"):text.index("</project>")]
        for part in ("Roadster", "Heater control on an ESP32", "[bug] Heater does not switch off",
                     "[major] Diagnosis page", "User: Which relay?", "Manager: A 12 V automotive relay."):
            self.assertIn(part, project)
        self.assertNotIn("Old finished thing", project)                        # archived items are done
        self.assertNotIn("And the fuse?", project)                             # the question itself comes after
        self.assertTrue(text.endswith("Question of the user:\nAnd the fuse?"))
        self.assertIn("not instructions", prompts.MANAGER)                           # the context is data

    def test_the_context_is_limited_and_drops_the_oldest_memory_first(self):
        self.connect(self.a)
        for i in range(prompts.CHAT_LIMITS["history"] + 2):
            chat.send(self.a.id, self.pa.id, f"question {i} " + "x" * 1900)
            job = chat.claim_next()
            chat.finish(job.chat_id, True, f"answer {i} " + "y" * 3000)
        chat.send(self.a.id, self.pa.id, "last")
        text = chat.claim_next().prompt
        project = text[text.index("<project>"):text.index("</project>")]
        self.assertLessEqual(len(project), prompts.MAX_CONTEXT + 20)
        self.assertNotIn("question 0 ", project)                               # beyond HISTORY, never sent
        self.assertIn(f"question {prompts.CHAT_LIMITS['history'] + 1} ", project)                # the newest stays
        self.assertIn(" …", project)                                           # long answers are cut

    def test_deleting_the_project_removes_the_messages(self):
        self.connect(self.a)
        chat.send(self.a.id, self.pa.id, "q")
        projects.delete_project(self.a.id, self.pa.id)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0], 0)


class ChatRoutesTest(Base):
    def test_ask_and_poll(self):
        self.connect(self.a)
        self.assertEqual(routes.messages(self.pa.id, user=self.a), {"ok": True, "claude": "connected", "messages": []})
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
        self.assertIn("No AI is connected", routes.ask(self.pb.id, "x", user=english).body.decode())  # B has no AI

    def test_a_failure_shows_only_its_kind(self):
        """Janis, 14.11.2026: a short text, not what Claude Code said; the menu learns of a lost sign-in."""
        self.connect(self.a)
        job_id = chat.send(self.a.id, self.pa.id, "q").id
        chat.claim_next()
        chat.finish(job_id, False, "Failed to authenticate. API Error: 401 OAuth access token has expired. (exit code 1)")
        claude_link.mark_expired(self.a.id)
        got = routes.messages(self.pa.id, user=self.a)
        self.assertEqual((got["claude"], got["messages"][0]["failure"], got["messages"][0]["answer"]), ("expired", "auth", ""))
        self.assertIn("OAuth", chat.list_messages(self.a.id, self.pa.id)[0].answer)   # the reason stays for diagnosis
        self.assertEqual(routes.messages(self.pa.id, user=self.b)["claude"], "none")    # B's own state, not A's

    def test_failure_kinds(self):
        for reason, kind in [("Failed to authenticate. API Error: 401", "auth"), ("Not logged in · Please run /login", "auth"),
                             ("Invalid API key", "auth"), ("timeout", "timeout"), ("Timeout: no answer in time.", "timeout"),
                             ("Too many steps: the search limit was reached.", "steps"),
                             ("No readable answer from Claude Code.", "other"), ("", "other")]:
            self.assertEqual(chat.failure_kind(reason), kind, reason)
            self.assertIn(chat.failure_kind(reason), chat.FAILURES)

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
        self.assertEqual(sorted(job), ["chat_id", "credential", "effort", "files", "hub_tools", "images", "limits", "links",
                                       "mode", "model", "project_id", "prompt", "provider", "route", "user_id"])
        self.assertEqual(runner_routes.chat_thoughts(job["chat_id"], "Hm."), {"ok": True})
        self.assertEqual(runner_routes.chat_finish(job["chat_id"], "1", "Hello back", 3, 4), {"ok": True})
        self.assertEqual(runner_routes.chat_thoughts(job["chat_id"], "late").status_code, 409)
        self.assertEqual(runner_routes.chat_finish(job["chat_id"], "1", "again", 0, 0).status_code, 409)
        self.assertEqual(chat.list_messages(self.a.id, self.pa.id)[0].answer, "Hello back")
        for route in runner_routes.router.routes:                       # the new routes hang on the token, too
            self.assertTrue(any(d.call is runner_routes.runner_only for d in route.dependant.dependencies), route.path)


class ChatPanelTest(Base):
    def test_panel_is_on_the_project_page_in_both_languages(self):
        for lang, title in (("de", "Berät dich im Projekt"), ("en", "Advises you on the project")):
            html = projectpage.render(dataclasses.replace(self.a, language=lang), self.pa, [])
            self.assertIn('id="chat"', html)
            self.assertIn(title, html)
            self.assertNotIn("%t.", html)
        self.assertIn("chat.js", projectpage.SCRIPTS)

    def test_script_has_no_texts_and_never_uses_innerhtml(self):
        script = (Path(__file__).parent.parent / "app" / "static" / "chat.js").read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", script)
        for text in ("Einzelfragen", "Senden", "Fehlgeschlagen", "Du "):
            self.assertNotIn(text, script)


if __name__ == "__main__":
    unittest.main()
