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

    def test_the_token_lasts_a_year_and_can_be_renewed_in_time(self):
        """Since 14.11.2026: the one-year token of setup-token; the last RENEW_DAYS the menu offers "renew"."""
        day, year = 86400, claude_link.TOKEN_DAYS * 86400
        claude_link.begin(self.a.id, now=1000)
        claude_link.complete(self.a.id, True, now=1000)
        self.assertEqual(claude_link.status(self.a.id, now=1000 + year - 31 * day), "connected")
        expiring = 1000 + year - 10 * day
        self.assertEqual(claude_link.status(self.a.id, now=expiring), "expiring")
        self.assertEqual(claude_link.status(self.a.id, now=1000 + year), "expired")
        self.assertTrue(claude_link.begin(self.a.id, now=expiring))          # renew while it still works
        claude_link.complete(self.a.id, False, now=expiring + 60)              # the renewal did not go through ...
        self.assertEqual(claude_link.status(self.a.id, now=expiring + 60), "expiring")   # ... the old token stays
        claude_link.begin(self.a.id, now=expiring + 120)
        self.assertEqual(claude_link.status(self.a.id, now=expiring + 120 + claude_link.CONNECT_TIMEOUT + 1),
                         "expiring")                                           # a renewal left alone: the same
        claude_link.complete(self.a.id, True, now=expiring + 180)
        self.assertEqual(claude_link.status(self.a.id, now=expiring + 180 + year - 31 * day), "connected")

    def test_expired_tokens_are_listed_for_deleting(self):
        day, year = 86400, claude_link.TOKEN_DAYS * 86400
        for user in (self.a, self.b):
            claude_link.begin(user.id, now=1000)
            claude_link.complete(user.id, True, now=1000)
        self.assertEqual(claude_link.expired_users(now=2000), [])
        self.assertEqual(claude_link.expired_users(now=1000 + year - 5 * day), [])        # expiring still works
        self.assertEqual(sorted(claude_link.expired_users(now=1000 + year)), sorted([self.a.id, self.b.id]))
        claude_link.begin(self.b.id, now=1000 + year)                                    # B links again
        self.assertEqual(claude_link.expired_users(now=1000 + year + 1), [self.a.id])

    def test_an_old_login_becomes_expired_once(self):
        """Logins from before the setup token (Claude Code's own files) are not used any more: link again."""
        with db.connect() as conn:
            conn.execute("INSERT INTO claude_connections (user_id, status, updated_at) VALUES (?, 'connected', 1)",
                         (self.a.id,))
            conn.execute("ALTER TABLE claude_connections DROP COLUMN expires_at")
        db._ready.discard(db.DB_PATH)
        self.assertEqual(claude_link.status(self.a.id), "expired")
        self.connect(self.a)
        db._ready.discard(db.DB_PATH)                                          # the next start changes nothing
        self.assertEqual(claude_link.status(self.a.id), "connected")

    def test_login_link_must_be_https_to_claude(self):
        claude_link.begin(self.a.id)
        for bad in ("http://claude.ai/x", "https://evil.example/claude.ai", "https://claude.ai.evil.com/x",
                    "javascript:alert(1)", ""):
            with self.assertRaises(ValueError, msg=bad):
                claude_link.set_login_url(self.a.id, bad)

    def test_disconnect_wipes_before_the_row_is_forgotten(self):
        self.connect(self.a)
        self.assertTrue(claude_link.disconnect(self.a.id))
        self.assertEqual(claude_link.status(self.a.id), "none")        # for the user it is over at once
        self.assertFalse(claude_link.is_connected(self.a.id))
        self.assertEqual(claude_link.pending_wipes(), [self.a.id])     # the runner deletes the folder
        self.assertFalse(claude_link.mark_expired(self.a.id))
        self.assertTrue(claude_link.wiped(self.a.id))
        self.assertEqual(claude_link.pending_wipes(), [])
        self.assertFalse(claude_link.wiped(self.a.id))
        self.connect(self.a)                                           # a new login started before the wipe
        claude_link.disconnect(self.a.id)
        claude_link.begin(self.a.id)
        self.assertFalse(claude_link.wiped(self.a.id))                 # must not forget the running login
        self.assertEqual(claude_link.status(self.a.id), "connecting")

    def test_deleting_an_account_queues_the_deletion_of_his_claude_folder(self):
        owner = users.create_user("o@example.com", "Oooo!pass12", role="owner")
        self.connect(self.a)
        self.connect(self.b)
        users.delete_user(owner, self.a.id)
        self.assertEqual(claude_link.status(self.a.id), "none")        # row gone with the account ...
        self.assertEqual(claude_link.pending_wipes(), [self.a.id])     # ... but the folder is still to be deleted
        self.assertTrue(claude_link.is_connected(self.b.id))           # nobody else is touched
        self.assertTrue(claude_link.wiped(self.a.id))
        self.assertEqual(claude_link.pending_wipes(), [])
        self.assertFalse(claude_link.wiped(self.a.id))
        self.assertTrue(claude_link.is_connected(self.b.id))

    def test_deleting_the_user_removes_the_connection(self):
        self.connect(self.a)
        with db.connect() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (self.a.id,))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM claude_connections").fetchone()[0], 0)


CHANGE = ("app.py | 2 +-", "diff --git a/app.py b/app.py\n+print(1)\n")


class ChainTest(Base):
    """The chain as Janis describes it (KONZEPT-AGENTEN.md 10): the board is the queue, the item leaves it when the
    programmer takes it, programmer -> tests -> tester -> reviewer until all agree, then merge and documentation."""

    def run_stage(self, result, report="", change=True, can_mac=True, **kw):
        """Claim the next run and finish it; a programmer's run changes something unless `change` is False."""
        job = agents.claim_next(can_mac=can_mac, **{k: v for k, v in kw.items() if k == "now"})
        self.assertIsNotNone(job)
        extra = {k: v for k, v in kw.items() if k != "now"}
        if job.role == "programmer" and job.purpose == "work" and change:
            extra.setdefault("change", CHANGE)
            extra.setdefault("committed", True)
        self.assertTrue(agents.finish_run(job.run_id, result, report, tokens_in=10, tokens_out=5, seconds=3, **extra))
        return job

    def task(self):
        return agents.list_tasks(self.a.id, self.project.id)[0]

    def item_status(self, item_id):
        return next(i.status for i in board.list_items(self.a.id, self.project.id) if i.id == item_id)

    def test_the_item_leaves_the_board_and_the_whole_chain_runs(self):
        self.connect(self.a)
        job = self.run_stage("done", "coded")
        self.assertEqual((job.role, job.purpose, job.sync), ("programmer", "work", True))
        self.assertEqual(self.item_status(self.item.id), "working")          # off the board while it is worked on
        self.assertIn("RESULT: question", job.prompt)                        # the role knows how to ask
        self.assertEqual(self.run_stage("pass", "works").role, "tester")
        self.assertEqual(self.run_stage("ok", "fine").role, "reviewer")
        task = self.task()
        self.assertEqual((task.stage, task.hold), ("merging", ""))            # no approval: the reviewer's ok merges
        self.assertIsNone(agents.claim_next(can_mac=True))                    # the runner merges first
        self.assertEqual([m["task_id"] for m in agents.pending_merges()], [task.id])
        self.assertTrue(agents.merge_done(task.id, True))
        job = self.run_stage("done", "documented")
        self.assertEqual((job.role, job.purpose, job.mode), ("chef", "doc", "brief"))
        self.assertEqual(self.task().stage, "done")
        self.assertEqual(self.item_status(self.item.id), "archived")
        self.assertEqual(agents.usage(self.a.id, self.project.id)["tokens_in"], 40)
        self.assertEqual(agents.usage(self.b.id), {"tokens_in": 0, "tokens_out": 0, "seconds": 0, "runs": 0})

    def test_after_every_return_the_whole_chain_runs_again(self):
        self.connect(self.a)
        self.run_stage("done")
        self.run_stage("fail", "button x does nothing")
        job = self.run_stage("done", "fixed")
        self.assertEqual(job.role, "programmer")
        self.assertIn(("tester", "button x does nothing"), job.reports)     # the hub passes the report on
        self.assertEqual(self.run_stage("pass").role, "tester")             # the tester again, then the reviewer
        self.run_stage("objections", "unsafe input")
        self.assertEqual(self.task().returns, 2)
        self.assertEqual(agents.claim_next(can_mac=True).role, "programmer")

    def test_the_projects_tests_decide_before_the_tester(self):
        self.connect(self.a)
        self.run_stage("done", tests=(1, "FAIL: test_add"))
        self.assertEqual((self.task().stage, self.task().returns), ("coding", 1))   # red: back without an AI tester
        job = agents.claim_next(can_mac=True)
        self.assertIn("hub-test.sh: exit 1", "\n".join(r for _, r in job.reports))
        agents.finish_run(job.run_id, "done", change=CHANGE, committed=True, tests=(0, "OK"))
        job = agents.claim_next(can_mac=True)
        self.assertEqual(job.role, "tester")                                 # green: the tester checks the behaviour
        self.assertIn("hub-test.sh passed", job.prompt)

    def test_one_task_per_project_bugs_first_then_the_order_they_were_made(self):
        self.connect(self.a)
        board.discard(self.a.id, self.item.id)
        major = board.create_item(self.a.id, self.project.id, "major", "Sums and filter")   # made first ...
        minor = board.create_item(self.a.id, self.project.id, "minor", "Bars")              # ... builds on it
        self.run_stage("done")
        self.assertEqual(self.task().item_id, major.id)                      # not small before big (task 20)
        self.assertEqual(self.item_status(minor.id), "open")                 # waits on the board
        self.assertEqual(len(agents.list_tasks(self.a.id, self.project.id)), 1)
        bug = board.create_item(self.a.id, self.project.id, "bug", "Crash")
        for result in ("pass", "ok"):
            self.run_stage(result)
        agents.merge_done(self.task().id, True)
        self.run_stage("done")
        self.run_stage("done")
        self.assertEqual(self.task().item_id, bug.id)                        # a bug goes before the waiting update

    def test_nothing_starts_without_the_users_own_ai_or_while_paused(self):
        self.connect(self.b)                                                 # somebody else's AI does not help
        self.assertIsNone(agents.claim_next(can_mac=True))
        self.assertEqual(agents.list_tasks(self.a.id, self.project.id), [])
        self.connect(self.a)
        agents.set_paused(self.a.id, True)
        self.assertIsNone(agents.claim_next(can_mac=True))
        agents.set_paused(self.a.id, False)
        self.assertEqual(agents.claim_next(can_mac=True).user_id, self.a.id)

    def test_pausing_freezes_a_running_run_and_frees_its_place(self):
        self.connect(self.a)
        job = agents.claim_next(can_mac=True)
        self.assertEqual(agents.alive(job.run_id, "thinking ..."), "run")
        with db.connect() as conn:
            self.assertFalse(agents.slot_free(conn))
        agents.set_paused(self.a.id, True)
        self.assertEqual(agents.alive(job.run_id), "pause")                 # frozen, not stopped
        with db.connect() as conn:
            self.assertTrue(agents.slot_free(conn))                          # the chat may run beside it
        self.assertEqual(agents.where(self.a.id, self.project.id)[1], "paused")
        agents.set_paused(self.a.id, False)
        self.assertEqual(agents.alive(job.run_id), "run")
        self.assertTrue(agents.finish_run(job.run_id, "done", change=CHANGE, committed=True))   # nothing was lost
        self.assertIn("thinking", agents.task_runs(self.a.id, self.task().id)[0].thoughts)

    def test_a_stopped_or_lost_run_goes_on_once_then_the_user_decides(self):
        self.connect(self.a)
        first = agents.claim_next(can_mac=True, now=1000)
        second = agents.claim_next(can_mac=True, now=1000 + agents.DEAD_SECONDS + 1)   # the runner lost it
        self.assertNotEqual(first.run_id, second.run_id)
        self.assertEqual(second.role, "programmer")
        self.assertIn("<where-it-stands>", second.prompt)                    # told that its work is saved
        self.assertFalse(agents.finish_run(first.run_id, "done"))            # too late
        self.assertTrue(agents.finish_run(second.run_id, "stopped", "Ended: the AI wrote nothing for 15 minutes."))
        task = self.task()
        self.assertEqual((task.hold, task.hold_why), ("decision", "failed"))
        explain = agents.claim_next(can_mac=True)
        self.assertEqual((explain.role, explain.purpose), ("chef", "explain"))
        self.assertTrue(agents.finish_run(explain.run_id, "done",
                                          '<stuck recommend="again">Der Lauf hing zweimal.</stuck>'))
        task = self.task()
        self.assertEqual((task.advice, task.advice_pick), ("Der Lauf hing zweimal.", "again"))
        self.assertTrue(agents.decide(self.a.id, task.id, "again", "Kleiner anfangen"))
        job = agents.claim_next(can_mac=True)
        self.assertEqual(job.role, "programmer")
        self.assertIn("Kleiner anfangen", job.prompt)                        # the user's hint
        self.assertEqual(self.task().hold, "")

    def test_a_missing_result_line_is_asked_for_once(self):
        self.connect(self.a)
        job = agents.claim_next(can_mac=True)
        agents.finish_run(job.run_id, "none", "Alles gebaut, 42 Tests grün.", change=CHANGE, committed=True)
        fix = agents.claim_next(can_mac=True)
        self.assertEqual((fix.purpose, fix.mode, fix.provider), ("result", "brief", job.provider))
        self.assertIn("42 Tests", fix.prompt)
        self.assertTrue(agents.finish_run(fix.run_id, "done"))
        self.assertEqual(self.task().stage, "testing")                      # the line counts for the report asked about
        job = agents.claim_next(can_mac=True)
        agents.finish_run(job.run_id, "none", "hm")
        fix = agents.claim_next(can_mac=True)
        agents.finish_run(fix.run_id, "none", "still nothing")
        self.assertEqual((self.task().hold, self.task().hold_why), ("decision", "format"))

    def test_a_question_goes_to_the_manager_who_asks_the_user_in_plain_words(self):
        from app import questions
        self.connect(self.a)
        job = agents.claim_next(can_mac=True)
        agents.finish_run(job.run_id, "question", 'Stuck.\n<ask kind="choice">SQLite oder JSON?<option>SQLite</option>'
                          '<option>JSON</option></ask>', change=CHANGE, committed=True)
        self.assertEqual(self.task().hold, "question")
        self.assertEqual(questions.open_questions(self.a.id, self.project.id), [])   # first the manager
        decide = agents.claim_next(can_mac=True)
        self.assertEqual((decide.role, decide.purpose, decide.mode), ("chef", "decide", "brief"))
        self.assertIn("SQLite oder JSON?", decide.prompt)
        agents.finish_run(decide.run_id, "done", '<ask kind="choice">Sollen die Daten in einer Datei liegen?'
                          '<option>Nein, Datenbank</option><option recommended>Ja, eine Datei</option></ask>')
        asked = questions.open_questions(self.a.id, self.project.id)
        self.assertEqual(len(asked), 1)
        self.assertEqual((asked[0].text, asked[0].recommended), ("Sollen die Daten in einer Datei liegen?", 1))
        self.assertEqual(questions.open_questions(self.b.id, self.project.id), [])
        self.assertFalse(agents.answer_question(self.b.id, asked[0].id, "Ja"))   # not his
        self.assertTrue(agents.answer_question(self.a.id, asked[0].id, "Ja, eine Datei"))
        job = agents.claim_next(can_mac=True)
        self.assertEqual((job.role, self.task().hold), ("programmer", ""))
        self.assertIn("Ja, eine Datei", job.prompt)                          # the answer, never via the chat
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0], 0)

    def test_the_manager_decides_small_questions_himself_unless_told_not_to(self):
        from app import questions
        self.connect(self.a)
        job = agents.claim_next(can_mac=True)
        agents.finish_run(job.run_id, "question", '<ask kind="text">Knöpfe links oder rechts?</ask>', change=CHANGE,
                          committed=True)
        decide = agents.claim_next(can_mac=True)
        agents.finish_run(decide.run_id, "done", "<decide>Rechts, wie in RULES.md.</decide>")
        job = agents.claim_next(can_mac=True)
        self.assertEqual(job.role, "programmer")
        self.assertIn("Rechts, wie in RULES.md.", job.prompt)
        agents.configure(self.a.id, autonomy="all")                          # asks for everything: never decides
        agents.finish_run(job.run_id, "question", '<ask kind="text">Welche Farbe?</ask>', change=CHANGE, committed=True)
        decide = agents.claim_next(can_mac=True)
        agents.finish_run(decide.run_id, "done", "<decide>Blau.</decide>")
        self.assertEqual([q.text for q in questions.open_questions(self.a.id, self.project.id)], ["Welche Farbe?"])
        self.assertEqual(self.task().hold, "question")

    def test_what_only_the_user_can_do_goes_to_for_you(self):
        from app import todos
        self.connect(self.a)
        job = agents.claim_next(can_mac=True)
        agents.finish_run(job.run_id, "blocked", "<env>skizze.png hochladen, für das Aussehen</env>", change=CHANGE,
                          committed=True)
        self.assertEqual(self.task().hold, "todo")
        entry = todos.list_todos(self.a.id, self.project.id)[0]
        self.assertEqual((entry.source, entry.task_id), ("programmer", self.task().id))
        self.assertIsNone(agents.claim_next(can_mac=True))                   # waits for the user
        todos.finish(self.a.id, entry.id, "liegt unter Medien")
        agents.check_todos(self.a.id)
        job = agents.claim_next(can_mac=True)
        self.assertEqual(job.role, "programmer")
        self.assertIn("liegt unter Medien", job.prompt)
        agents.finish_run(job.run_id, "done", "<env>Echte CSV fehlt noch</env>", change=CHANGE, committed=True)
        self.assertEqual(self.task().stage, "testing")                      # not blocked: it goes on, the entry waits
        self.assertEqual(sum(1 for t in todos.list_todos(self.a.id, self.project.id) if not t.done), 1)

    def test_not_testable_leaves_steps_to_check_by_hand(self):
        from app import todos
        self.connect(self.a)
        self.run_stage("done")
        self.run_stage("not_testable", "1. Relais einschalten\n2. LED prüfen")
        self.assertTrue(self.task().manual_check)
        self.assertIn("Relais einschalten", todos.list_todos(self.a.id, self.project.id)[0].text)

    def test_unchanged_or_stuck_work_and_markers(self):
        self.connect(self.a)
        self.run_stage("done", change=False)
        self.assertEqual(self.task().hold_why, "nothing")
        agents.decide(self.a.id, self.task().id, "again")
        self.run_stage("done")
        self.run_stage("fail", "still broken")
        job = agents.claim_next(can_mac=True)
        agents.finish_run(job.run_id, "done", change=CHANGE, committed=False)   # sent back, changed nothing
        self.assertEqual(self.task().hold_why, "stuck")
        agents.decide(self.a.id, self.task().id, "again")
        job = agents.claim_next(can_mac=True)
        agents.finish_run(job.run_id, "done", change=CHANGE, committed=True, markers=["app.py"])
        task = self.task()
        self.assertEqual((task.stage, task.returns), ("coding", 1))
        self.assertIn("app.py", agents.claim_next(can_mac=True).prompt)      # told which files still conflict

    def test_too_many_returns_then_accept_or_cancel(self):
        self.connect(self.a)
        for _ in range(agents.workflow.MAX_RETURNS + 1):
            self.run_stage("done")
            self.run_stage("fail")
        task = self.task()
        self.assertEqual((task.hold, task.hold_why), ("decision", "returns"))
        self.assertFalse(agents.decide(self.b.id, task.id, "accept"))
        self.assertTrue(agents.decide(self.a.id, task.id, "accept"))
        task = self.task()
        self.assertEqual((task.stage, task.manual_check), ("merging", True))
        other = board.create_item(self.a.id, self.project.id, "minor", "Next")
        agents.merge_done(task.id, True)
        self.run_stage("done")                                               # the documentation (explain was dropped)
        self.run_stage("done")
        self.assertEqual(self.task().item_id, other.id)
        self.assertTrue(agents.cancel(self.a.id, self.task().id))
        self.assertEqual(self.item_status(other.id), "trash")

    def test_cancelling_stops_a_running_run(self):
        self.connect(self.a)
        job = agents.claim_next(can_mac=True)
        self.assertFalse(agents.cancel(self.b.id, self.task().id))
        self.assertTrue(agents.cancel(self.a.id, self.task().id))
        self.assertEqual(agents.alive(job.run_id), "stop")                   # the runner ends the container
        self.assertFalse(agents.finish_run(job.run_id, "done"))
        self.assertEqual(self.item_status(self.item.id), "trash")

    def test_a_restarted_runner_gets_its_runs_again(self):
        self.connect(self.a)
        job = agents.claim_next(can_mac=True)
        self.assertEqual(agents.requeue_running(), 1)
        self.assertEqual(agents.claim_next(can_mac=True).run_id, job.run_id)

    def test_a_merge_conflict_goes_back_to_the_programmer(self):
        self.connect(self.a)
        for result in ("done", "pass", "ok"):
            self.run_stage(result)
        self.assertTrue(agents.merge_done(self.task().id, False))
        task = self.task()
        self.assertEqual((task.stage, task.hold, task.returns), ("coding", "", 1))
        job = agents.claim_next(can_mac=True)
        self.assertTrue(job.sync)                                           # main comes into the branch first
        self.assertIn("main changed", job.prompt)

    def test_mac_tasks_wait_for_a_mac_for_coding_and_testing(self):
        self.connect(self.a)
        board.discard(self.a.id, self.item.id)
        with db.connect() as conn:
            board.add_from_ai(conn, self.project.id, "major", "iOS app", approved=True, source="manager", needs="mac")
        self.assertIsNone(agents.claim_next(can_mac=False))
        self.assertEqual(agents.where(self.a.id, self.project.id)[1], "mac")
        self.run_stage("done", can_mac=True)
        self.assertIsNone(agents.claim_next(can_mac=False))                  # the tester needs it too
        self.run_stage("pass", can_mac=True)
        self.assertEqual(self.run_stage("ok", can_mac=False).role, "reviewer")   # the reviewer runs on the server

    def test_the_reviewer_looks_at_what_the_project_says(self):
        self.connect(self.a)
        focus = "# Prüfen\r\n\r\n\r\n\r\n- Sicherheit der Eingaben\n- keine Zugangsdaten im Code   \x07"
        self.assertTrue(agents.set_review_focus(self.a.id, self.project.id, focus))
        self.assertFalse(agents.set_review_focus(self.b.id, self.project.id, "x"))
        self.assertEqual(agents.review_focus(self.a.id, self.project.id),
                         "# Prüfen\n\n- Sicherheit der Eingaben\n- keine Zugangsdaten im Code")   # Markdown kept, cleaned
        programmer = agents.claim_next(can_mac=True)
        self.assertNotIn("Sicherheit der Eingaben", programmer.prompt)            # only the reviewer gets it
        agents.finish_run(programmer.run_id, "done", change=CHANGE, committed=True)
        self.run_stage("pass")
        reviewer = agents.claim_next(can_mac=True)
        self.assertIn("<review-focus>\n# Prüfen\n\n- Sicherheit der Eingaben", reviewer.prompt)

    def test_the_review_focus_downloads_as_markdown(self):
        from app.routes import roles as role_routes
        agents.set_review_focus(self.a.id, self.project.id, "- Sicherheit")
        answer = role_routes.review_focus_file(self.project.id, user=self.a)
        self.assertEqual((answer.body, answer.media_type), (b"- Sicherheit\n", "text/markdown; charset=utf-8"))
        self.assertIn("Worauf-achten.md", answer.headers["content-disposition"])
        self.assertEqual(role_routes.review_focus_file(self.project.id, user=self.b).status_code, 404)

    def test_settings_validation(self):
        for call in (lambda: agents.configure(self.a.id, "tester", model="gpt"),
                     lambda: agents.configure(self.a.id, "janitor", net="apart"),
                     lambda: agents.configure(self.a.id, autonomy="wild")):
            with self.assertRaises(ValueError):
                call()
        agents.configure(self.a.id, "reviewer", model="opus")
        self.assertEqual(agents.settings(self.a.id)["roles"]["reviewer"]["model"], "opus")
        self.assertEqual(agents.settings(self.b.id)["roles"]["reviewer"]["model"], "sonnet")

    def test_each_agent_has_its_own_web_and_code_switch(self):
        self.connect(self.a)
        agents.configure(self.a.id, "programmer", net="apart")
        roles = agents.settings(self.a.id)["roles"]
        self.assertEqual((roles["programmer"]["net"], roles["chef"]["net"], roles["tester"]["net"]),
                         ("apart", "together", "apart"))
        self.assertEqual(agents.settings(self.b.id)["roles"]["programmer"]["net"], "together")   # per user
        self.assertEqual(agents.claim_next(can_mac=True).net, "apart")        # the run learns the switch of its role
        for call in (lambda: agents.configure(self.a.id, "tester", net="open"),
                     lambda: agents.configure(self.a.id, None, net="apart")):
            with self.assertRaises(ValueError):
                call()

    def test_a_result_that_does_not_fit_the_role_waits_for_a_decision(self):
        self.connect(self.a)
        job = agents.claim_next(can_mac=True)
        self.assertTrue(agents.finish_run(job.run_id, "pass", change=CHANGE, committed=True))
        self.assertEqual((self.task().hold, self.task().hold_why), ("decision", "format"))
        self.assertFalse(agents.finish_run(job.run_id, "done"))              # a run ends only once

    def test_the_manager_run_edits_the_memory_and_reports_what_did_not_fit(self):
        from app import files, memory
        files.FILES_DIR, old = Path(self.tmp.name) / "files", (files.FILES_DIR, files.free_bytes)
        files.free_bytes = lambda: 10 * 1024 ** 3
        self.addCleanup(lambda: setattr(files, "FILES_DIR", old[0]) or setattr(files, "free_bytes", old[1]))
        memory.save_memory(self.a.id, self.project.id, "# Stand\n- Relais: offen")
        self.connect(self.a)
        for result in ("done", "pass", "ok"):
            self.run_stage(result)
        agents.merge_done(self.task().id, True)
        report = ('Doku nachgeführt.\n<memory-edit file="MEMORY.md"><section title="Stand">- Relais: eingebaut</section>'
                  '</memory-edit><memory-edit file="ROADMAP.md"><section title="x">y</section></memory-edit>')
        self.assertEqual(self.run_stage("done", report).role, "chef")
        memo = next(f for f in files.list_files(self.a.id, self.project.id) if f.name == "MEMORY.md")
        self.assertEqual(files.read_text(self.a.id, memo.id), "# Stand\n- Relais: eingebaut\n")
        with db.connect() as conn:
            stored = conn.execute("SELECT report FROM agent_runs WHERE purpose = 'doc'").fetchone()["report"]
        self.assertTrue(stored.startswith("Doku nachgeführt."))
        self.assertIn('<edit-failed file="ROADMAP.md">', stored)              # there is no ROADMAP.md here


if __name__ == "__main__":
    unittest.main()
