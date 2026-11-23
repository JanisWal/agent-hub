"""The usage ledger (usage.py, KONZEPT-AGENTEN.md 10.10): every call of an AI counts once, also an ended or cancelled
run and every answer of the manager, per AI and per role, only for its own user, and nothing goes with the chat."""
import os
import tempfile
import unittest

from app import agents, board, chat, claude_link, db, projects, statusnote, ui, usage, users

CHANGE = ("a.py | 1 +", "+a\n")


class UsageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        statusnote._LAST_SCAN["at"] = 2 ** 40
        self.a = users.create_user("a@example.com", "Aaaa!pass12")
        self.b = users.create_user("b@example.com", "Bbbb!pass12")
        self.pa = projects.create_project(self.a.id, "Rechner")
        claude_link.begin(self.a.id)
        claude_link.complete(self.a.id, True)

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self):
        with db.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM ai_usage ORDER BY id")]

    def test_a_chat_answer_counts_with_its_cache_part_and_stays_when_the_chat_is_cleared(self):
        chat.send(self.a.id, self.pa.id, "Hallo")
        job = chat.claim_next()
        self.assertTrue(chat.finish(job.chat_id, True, "Hi", 1200, 30, cache=(1000, 100)))
        [row] = self.rows()
        self.assertEqual((row["kind"], row["provider"], row["role"], row["tokens_in"], row["tokens_out"],
                          row["cache_read"], row["cache_write"], row["partial"]), ("chat", "claude", "chef", 1200, 30,
                                                                                 1000, 100, 0))
        chat.delete_all(self.a.id)
        self.assertEqual(len(self.rows()), 1)                                 # the ledger keeps it
        self.assertEqual(usage.totals(self.a.id, kind="chat")["tokens_out"], 30)

    def test_an_answer_that_ran_out_of_time_counts_what_was_seen(self):
        chat.send(self.a.id, self.pa.id, "Hallo")
        job = chat.claim_next()
        chat.finish(job.chat_id, False, "Timeout: no answer in time.", 500, 0, partial=True)
        self.assertEqual((self.rows()[0]["tokens_in"], self.rows()[0]["partial"]), (500, 1))

    def test_every_run_counts_also_one_that_failed_for_its_ai_or_was_cancelled(self):
        board.create_item(self.a.id, self.pa.id, "minor", "Addieren")
        job = agents.claim_next(can_mac=False)
        agents.finish_run(job.run_id, "failed", "You've hit your usage limit", 800, 20)   # it waits for a rested AI
        self.assertEqual(len(self.rows()), 1)
        with db.connect() as conn:
            conn.execute("DELETE FROM agent_settings WHERE key LIKE 'ai.rest.%'")
        job = agents.claim_next(can_mac=False)
        agents.alive(job.run_id)
        agents.cancel(self.a.id, agents.list_tasks(self.a.id, self.pa.id)[0].id)
        self.assertFalse(agents.finish_run(job.run_id, "stopped", "Cancelled.", 300, 10, partial=True))
        rows = self.rows()
        self.assertEqual([(r["kind"], r["role"], r["tokens_in"], r["partial"]) for r in rows],
                         [("run", "programmer", 800, 0), ("run", "programmer", 300, 1)])   # the cancelled one counts
        self.assertEqual(agents.usage(self.a.id, self.pa.id, "programmer")["runs"], 2)
        self.assertFalse(agents.finish_run(job.run_id, "stopped", "again"))    # no numbers: nothing more

    def test_a_call_that_used_nothing_is_not_kept(self):
        with db.connect() as conn:
            usage.record(conn, user_id=self.a.id, project_id=self.pa.id, provider="claude", model="sonnet",
                         credential="plan", kind="run", tokens_in=0, tokens_out=0)
        self.assertEqual(self.rows(), [])

    def test_per_ai_today_and_seven_days_only_for_the_own_user(self):
        now = 1_800_000_000
        with db.connect() as conn:
            for provider, model, tin, at in (("claude", "sonnet", 1000, now - 60), ("claude", "opus", 500, now - 3 * 86400),
                                             ("custom", "own-3", 70, now - 60), ("mistral", "m", 9, now - 9 * 86400)):
                usage.record(conn, user_id=self.a.id, project_id=self.pa.id, provider=provider, model=model,
                             credential="plan", kind="chat", tokens_in=tin, tokens_out=0, now=at)
            usage.record(conn, user_id=self.b.id, project_id=None, provider="claude", model="sonnet", credential="plan",
                         kind="chat", tokens_in=5, tokens_out=0, now=now - 60)
        spent = usage.by_ai(self.a.id, now=now)
        today = now - now % 86400
        self.assertEqual(spent["claude"]["week"], 1500)
        self.assertEqual(spent["claude"]["today"], 1000 if now - 60 >= today else 0)
        self.assertEqual(spent["custom-3"]["week"], 70)                        # a further AI by its place
        self.assertEqual((spent["mistral"]["week"], spent["mistral"]["total"]), (0, 9))   # older than a week: only in all
        self.assertEqual(spent["claude"]["total"], 1500)
        self.assertNotIn("project", spent["claude"])                           # no project asked for
        self.assertEqual(usage.by_ai(self.b.id, now=now)["claude"]["week"], 5)   # each only his own

    def test_the_drawer_shows_what_an_ai_used(self):
        with db.connect() as conn:
            usage.record(conn, user_id=self.a.id, project_id=self.pa.id, provider="claude", model="sonnet",
                         credential="plan", kind="chat", tokens_in=12000, tokens_out=345)
        self.assertIn("Verbrauch: 12,3 Tsd. Token", ui.settings_bar(self.a))                      # all projects on the board
        other = projects.create_project(self.a.id, "Uhr")
        with db.connect() as conn:
            usage.record(conn, user_id=self.a.id, project_id=other.id, provider="claude", model="sonnet",
                         credential="plan", kind="chat", tokens_in=5000, tokens_out=0)
        self.assertIn("Verbrauch: 17,3 Tsd. Token", ui.settings_bar(self.a))
        self.assertIn("Verbrauch: 12,3 Tsd. Token", ui.settings_bar(self.a, project_id=self.pa.id))   # only this project
        self.assertNotIn("Verbrauch:", ui.settings_bar(self.b))

    def test_a_project_has_its_own_number_and_never_another_users(self):
        other = projects.create_project(self.a.id, "Uhr")
        theirs = projects.create_project(self.b.id, "Fremd")
        with db.connect() as conn:
            for user, project, tin in ((self.a, self.pa, 100), (self.a, other, 40), (self.b, theirs, 7)):
                usage.record(conn, user_id=user.id, project_id=project.id, provider="claude", model="sonnet",
                             credential="plan", kind="chat", tokens_in=tin, tokens_out=0)
        spent = usage.by_ai(self.a.id, project_id=self.pa.id)["claude"]
        self.assertEqual((spent["total"], spent["project"]), (140, 100))        # all projects of his, and this one
        self.assertEqual(usage.by_ai(self.a.id, project_id=theirs.id)["claude"]["project"], 0)   # not his project: nothing

    def test_the_usage_window_has_a_block_per_ai_and_the_sum_only_with_two(self):
        with db.connect() as conn:
            usage.record(conn, user_id=self.a.id, project_id=self.pa.id, provider="claude", model="sonnet",
                         credential="plan", kind="chat", tokens_in=1000, tokens_out=0)
        page = ui.settings_bar(self.a, project_id=self.pa.id)
        self.assertIn('data-usage="claude"', page)                              # the button of its row
        self.assertIn('id="usage-dialog"', page)
        self.assertIn('data-usage-for="claude"', page)
        for text in ("Heute", "Letzte 7 Tage", "Dieses Projekt", "Alle Projekte"):               # this project first, all quiet
            self.assertIn(text, page)
        self.assertNotIn("Alle KIs zusammen", page)                             # one AI: no sum
        self.assertNotIn("Dieses Projekt", ui.settings_bar(self.a))             # not on a project page
        with db.connect() as conn:
            usage.record(conn, user_id=self.a.id, project_id=self.pa.id, provider="mistral", model="m",
                         credential="plan", kind="chat", tokens_in=500, tokens_out=0)
        page = ui.settings_bar(self.a, project_id=self.pa.id)
        self.assertIn('data-usage-for="all"', page)
        self.assertIn("Alle KIs zusammen", page)
        self.assertIn("grober Überblick", page)                                 # the "i" says tokens differ

    def test_the_split_by_day_role_model_and_way_and_the_projects_on_the_board(self):
        now = 1_800_000_000
        other = projects.create_project(self.a.id, "Uhr")
        theirs = projects.create_project(self.b.id, "Fremd")
        with db.connect() as conn:
            for project, role, model, way, tin, at in (
                    (self.pa, "programmer", "sonnet", "plan", 300, now - 60), (self.pa, "chef", "sonnet", "api", 100, now - 60),
                    (self.pa, "reviewer", "opus", "plan", 50, now - 2 * 86400), (other, "programmer", "sonnet", "plan", 40, now - 60),
                    (self.pa, "programmer", "sonnet", "plan", 9, now - 20 * 86400)):
                usage.record(conn, user_id=self.a.id, project_id=project.id, provider="claude", model=model, credential=way,
                             kind="run", role=role, tokens_in=tin, tokens_out=0, now=at)
            usage.record(conn, user_id=self.b.id, project_id=theirs.id, provider="claude", model="sonnet", credential="plan",
                         kind="run", role="tester", tokens_in=7000, tokens_out=0, now=now - 60)
        board = usage.detail(self.a.id, now=now)["claude"]                         # no project: everything of his
        self.assertEqual((board["scope"], board["total"], len(board["days"])), (499, 499, 7))
        self.assertEqual(board["days"][6], 440)                                    # today last
        self.assertEqual(board["days"][4], 50)                                     # two days before
        self.assertEqual(board["roles"], {"programmer": 349, "chef": 100, "reviewer": 50})
        self.assertEqual(board["ways"], {"plan": 399, "api": 100})
        self.assertEqual(list(board["projects"]), ["Rechner", "Uhr"])              # the biggest first, only his own
        mine = usage.detail(self.a.id, now=now, project_id=self.pa.id)["claude"]   # one project: only its numbers
        self.assertEqual((mine["scope"], mine["total"], mine["project"]), (459, 499, 459))
        self.assertEqual(mine["projects"], {})                                     # the split by project is the board's
        self.assertNotIn("Fremd", str(usage.detail(self.a.id, now=now)))

    def test_the_window_names_the_roles_and_the_board_goes_into_more_detail(self):
        with db.connect() as conn:
            for role, tin in (("programmer", 3000), ("chef", 1000)):
                usage.record(conn, user_id=self.a.id, project_id=self.pa.id, provider="claude", model="sonnet",
                             credential="api" if role == "chef" else "plan", kind="run", role=role, tokens_in=tin, tokens_out=0)
        board = ui.settings_bar(self.a)
        for text in ("Nach Rolle", "Programmierer", "Manager", "Nach Modell", "Abo oder Schlüssel", "API-Schlüssel", "Nach Projekt",
                     "usage-block big"):
            self.assertIn(text, board)
        self.assertIn('class="usage-day now"', board)                              # today's bar
        self.assertIn('data-pct="100"', board)                                     # the highest bar is full
        page = ui.settings_bar(self.a, project_id=self.pa.id)                      # a project: its own, the rest quiet
        self.assertIn("usage-quiet", page)
        self.assertNotIn("Nach Projekt", page)
        self.assertNotIn("usage-block big", page)

    def test_it_goes_with_the_account_and_stays_without_its_project(self):
        with db.connect() as conn:
            usage.record(conn, user_id=self.a.id, project_id=self.pa.id, provider="claude", model="sonnet",
                         credential="plan", kind="chat", tokens_in=10, tokens_out=1)
        projects.delete_project(self.a.id, self.pa.id)
        self.assertEqual([(r["project_id"], r["tokens_in"]) for r in self.rows()], [(None, 10)])
        owner = users.create_user("o@example.com", "Oooo!pass12", role="owner")
        users.delete_user(owner, self.a.id, now=1000)
        users.purge_deleted(now=1000 + (users.DELETED_DAYS + 1) * 86400)
        self.assertEqual(self.rows(), [])


if __name__ == "__main__":
    unittest.main()
