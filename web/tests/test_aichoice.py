"""One AI must be enough (Janis, 15.11.2026): the standard AI, the fallback to the user's next AI, the agent runs for
every AI (package, reviewer on another AI, merge before the manager documents) and the board's buttons for tasks."""
import os
import tempfile
import time
import unittest
from pathlib import Path

from app import (agents, ai_link, aichoice, board, catalog, chat, claude_link, db, files, i18n, managerpage, memory,
                 projectpage, projects, rolepage, statusnote, ui, users)
from app.routes import ai as ai_routes
from app.routes import board as board_routes
from app.routes import chat as chat_routes

KEY = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.files_dir = files.FILES_DIR
        files.FILES_DIR = Path(self.tmp.name) / "files"
        ai_link._keys.clear()
        self.a = users.create_user("a@example.com", "Aaaa!pass12")
        self.b = users.create_user("b@example.com", "Bbbb!pass12")
        self.pa = projects.create_project(self.a.id, "Project of A")
        self.pb = projects.create_project(self.b.id, "Project of B")
        self.item = board.create_item(self.a.id, self.pa.id, "bug", "Fix the relay")

    def tearDown(self):
        files.FILES_DIR = self.files_dir
        self.tmp.cleanup()

    def claude(self, user):
        claude_link.begin(user.id)
        claude_link.complete(user.id, True)

    def mistral(self, user):
        ai_link.submit_key(user.id, "mistral", KEY)
        ai_link.take_keys()
        ai_link.complete(user.id, "mistral", True)

    def stage(self, result, report=""):
        job = agents.claim_next(can_mac=True)
        self.assertIsNotNone(job)
        change = {"change": ("relay.py | 1 +", "+ON"), "committed": True} if job.role == "programmer" else {}
        self.assertTrue(agents.finish_run(job.run_id, result, report, **change))
        return job


class StandardTest(Base):
    def test_the_standard_and_the_order(self):
        self.assertEqual((aichoice.default(self.a.id), aichoice.connected(self.a.id)), ("claude", []))
        self.mistral(self.a)
        self.assertEqual(aichoice.default(self.a.id), "mistral")              # the only one is the standard
        self.claude(self.a)
        self.assertEqual(aichoice.default(self.a.id), "claude")               # nothing chosen: catalog order
        self.assertTrue(aichoice.set_default(self.a.id, "mistral"))
        with db.connect() as conn:
            self.assertEqual(aichoice.order_in(conn, self.a.id), ["mistral", "claude"])
        ai_link.disconnect(self.a.id, "mistral")
        self.assertEqual(aichoice.default(self.a.id), "claude")               # a standard that is gone counts not
        self.assertFalse(aichoice.set_default(self.a.id, "mistral"))
        self.assertFalse(aichoice.set_default(self.a.id, "chatgpt"))

    def test_the_route(self):
        self.claude(self.a)
        self.mistral(self.a)
        self.assertEqual(ai_routes.make_default("mistral", user=self.a), {"ok": True, "standard": "mistral"})
        self.assertEqual(ai_routes.make_default("mistral", user=self.b).status_code, 400)   # B has no Mistral

    def test_the_menu_puts_the_standard_on_top(self):
        self.claude(self.a)
        bar = ui.settings_bar(self.a)
        self.assertNotIn("data-ai-default", bar)                              # one AI: nothing to choose
        self.mistral(self.a)
        bar = ui.settings_bar(self.a)
        top, folded = bar[:bar.index('id="ai-more"')], bar[bar.index('id="ai-more"'):bar.index('id="chat-clear-open"')]
        self.assertIn('id="claude-row"', top)
        self.assertIn('id="ai-toggle"', top)
        self.assertIn('id="claude-open" data-status="connected"', top)      # the standard keeps "disconnect"
        self.assertIn('class="ai-default" type="button" data-ai-default="mistral"', folded)   # the green star
        self.assertIn(i18n.t("de", "ai_default_short"), folded)
        self.assertIn('data-key-open="mistral" data-status="connected"', folded)    # "disconnect" stays
        self.assertIn("ChatGPT", folded)
        aichoice.set_default(self.a.id, "mistral")
        bar = ui.settings_bar(self.a)
        top, folded = bar[:bar.index('id="ai-more"')], bar[bar.index('id="ai-more"'):bar.index('id="chat-clear-open"')]
        self.assertIn('id="key-row-mistral"', top)
        self.assertIn('id="ai-toggle"', top)
        self.assertIn('data-key-open="mistral" data-status="connected"', top)
        self.assertIn('data-ai-default="claude"', folded)
        self.assertIn('id="claude-open" data-status="connected"', folded)
        self.assertNotIn("data-ai-default", top)                              # the standard has no star

    def test_the_picker_shows_only_the_standard_ais_models(self):
        self.claude(self.a)
        self.mistral(self.a)
        page = projectpage.render(self.a, self.pa, board.list_items(self.a.id, self.pa.id))
        self.assertIn('value="sonnet"', page)
        self.assertNotIn('value="mistral-small-2603"', page)
        aichoice.set_default(self.a.id, "mistral")
        page = projectpage.render(self.a, self.pa, board.list_items(self.a.id, self.pa.id))
        self.assertIn('value="mistral-small-2603"', page)
        self.assertNotIn('value="sonnet"', page)
        self.assertIn('data-ai="Mistral"', page)

    def test_choices_are_kept_per_ai(self):
        self.claude(self.a)
        agents.configure(self.a.id, "chef", model="opus", effort="max")
        chef = agents.settings(self.a.id)["roles"]["chef"]
        self.assertEqual((chef["model"], chef["effort"]), ("opus", "max"))
        self.mistral(self.a)
        aichoice.set_default(self.a.id, "mistral")
        self.assertEqual(agents.settings(self.a.id)["roles"]["chef"]["model"], "mistral-small-2603")
        aichoice.set_default(self.a.id, "claude")
        self.assertEqual(agents.settings(self.a.id)["roles"]["chef"]["model"], "opus")   # found again


class FallbackTest(Base):
    def test_a_lost_standard_hands_the_question_to_the_next_ai(self):
        self.claude(self.a)
        self.mistral(self.a)
        chat.send(self.a.id, self.pa.id, "Hello")
        claude_link.mark_expired(self.a.id)                                   # gone before the runner took it
        job = chat.claim_next()
        self.assertEqual((job.provider, job.model), ("mistral", "mistral-small-2603"))
        self.assertTrue(chat.finish(job.chat_id, True, "Hi"))
        shown = chat_routes.messages(self.pa.id, user=self.a)["messages"][-1]
        self.assertEqual((shown["via"], shown["instead"]), ("Mistral", "Claude"))

    def test_the_status_is_the_one_button_of_a_row_and_a_refused_one_can_be_disconnected(self):
        """23.11.2026: no underlined links beside the status; every state opens the dialog of its AI, which offers
        "disconnect" next to "renew" for a refused or expired connection."""
        self.claude(self.a)
        self.mistral(self.a)
        page = ui.settings_bar(self.a)
        self.assertNotIn('class="link inline"', page)
        self.assertIn('<button class="status status-open" type="button" id="claude-open"', page)
        self.assertIn('<button class="status status-open" type="button" data-key-open="mistral" data-status="connected"', page)
        self.assertIn('<button class="status status-open" type="button" data-key-open="chatgpt" data-status="none"', page)
        self.assertGreaterEqual(page.count("data-to-disconnect"), 4)            # claude, key dialogs, device dialog
        from app import ai_link
        ai_link.mark_expired(self.a.id, "mistral")
        self.assertIn('data-key-open="mistral" data-status="expired"', ui.settings_bar(self.a))

    def test_a_waiting_question_names_the_ai_it_is_with(self):
        self.claude(self.a)
        self.mistral(self.a)
        chat.send(self.a.id, self.pa.id, "Hello")
        self.assertEqual(chat_routes.messages(self.pa.id, user=self.a)["messages"][-1]["ai"], "Claude")
        claude_link.mark_expired(self.a.id)
        chat.claim_next()                                                     # handed on to the next AI
        self.assertEqual(chat_routes.messages(self.pa.id, user=self.a)["messages"][-1]["ai"], "Mistral")

    def test_a_model_of_another_ai_moves_the_role_to_that_ai(self):
        self.claude(self.a)
        self.mistral(self.a)
        agents.configure(self.a.id, "chef", model="mistral-small-2603")        # the manager's list holds all AIs
        mine = agents.settings(self.a.id)["roles"]["chef"]
        self.assertEqual((mine["provider"], mine["model"]), ("mistral", "mistral-small-2603"))
        agents.configure(self.a.id, "chef", provider="claude")                 # back by the AI: its own model returns
        self.assertEqual(agents.settings(self.a.id)["roles"]["chef"]["provider"], "claude")

    def test_a_used_up_quota_tries_the_next_ai_once(self):
        self.claude(self.a)
        self.mistral(self.a)
        chat.send(self.a.id, self.pa.id, "Hello")
        job = chat.claim_next()
        self.assertEqual(job.provider, "claude")
        self.assertTrue(chat.finish(job.chat_id, False, "Claude AI usage limit reached"))
        job = chat.claim_next()
        self.assertEqual(job.provider, "mistral")                             # asked again, of Mistral
        self.assertTrue(chat.finish(job.chat_id, False, "Mistral: too many requests or no credit left (429)"))
        message = chat.list_messages(self.a.id, self.pa.id)[-1]
        self.assertEqual((message.status, chat.failure_kind(message.answer)), ("failed", "limit"))   # no third try

    def test_a_used_up_ai_hands_over_for_a_while_and_the_tabs_show_it(self):
        # Janis, 22.11.2026: the next question tried Claude again and the programmer's pill stayed on Claude.
        self.claude(self.a)
        self.mistral(self.a)
        chat.send(self.a.id, self.pa.id, "Hello")
        chat.finish(chat.claim_next().chat_id, False, "Claude AI usage limit reached")
        with db.connect() as conn:
            self.assertEqual(aichoice.acting_in(conn, self.a.id, "claude"), "mistral")
            self.assertGreater(aichoice.rest_left(conn, self.a.id, "claude"), 0)
            self.assertEqual(aichoice.acting_in(conn, self.b.id, "claude"), "claude")   # only his
        mine = agents.settings(self.a.id)["roles"]["programmer"]
        self.assertEqual((mine["provider"], mine["resting"]), ("mistral", "claude"))
        self.assertEqual(catalog.provider_of(agents.settings(self.a.id)["roles"]["chef"]["model"]), "mistral")
        page = rolepage.render_role("de", "programmer", agents.settings(self.a.id), [], {}, ("claude", "mistral"))
        self.assertIn('class="p-ai resting"', page)
        self.assertIn('class="p-ai on" type="button" data-role-ai="mistral"', page)
        later = int(time.time()) + 3 * 3600                                    # the rest is over: Claude again
        with db.connect() as conn:
            self.assertEqual(aichoice.acting_in(conn, self.a.id, "claude", later), "claude")

    def test_with_one_ai_nothing_else_is_tried(self):
        self.claude(self.a)
        self.mistral(self.b)                                                  # B's Mistral never helps A
        chat.send(self.a.id, self.pa.id, "Hello")
        job = chat.claim_next()
        self.assertTrue(chat.finish(job.chat_id, False, "401 authentication failed"))
        self.assertEqual(chat.list_messages(self.a.id, self.pa.id)[-1].status, "failed")
        self.assertIsNone(chat.claim_next())


class AgentRunTest(Base):
    def test_the_package_and_the_reviewer_on_another_ai(self):
        self.claude(self.a)
        self.mistral(self.a)
        memory.ensure_skeleton(self.a.id, self.pa.id, "de")
        job = agents.claim_next(can_mac=True)
        self.assertEqual((job.role, job.provider), ("programmer", "claude"))
        for part in ("You are the programmer", "<rules>", 'name="RULES.md"', "# Design", "Title: Fix the relay",
                     "Allowed results: done, question, blocked, failed", "RESULT: <value>", "hub-test.sh"):
            self.assertIn(part, job.prompt)
        self.assertNotIn('name="MEMORY.md"', job.prompt)                     # the programmer needs the rules only
        agents.finish_run(job.run_id, "done", "built it", change=("a | 1 +", "+a"), committed=True)
        job = agents.claim_next(can_mac=True)
        self.assertEqual(job.role, "tester")
        self.assertNotIn("skipped", job.prompt)                               # the hub's own result
        self.assertIn('<report role="programmer">\nbuilt it', job.prompt)
        agents.finish_run(job.run_id, "pass", "fine")
        job = agents.claim_next(can_mac=True)
        self.assertEqual((job.role, job.provider), ("reviewer", "mistral"))   # not the programmer's AI

    def test_a_run_of_a_lost_ai_goes_to_the_next(self):
        self.mistral(self.a)
        self.claude(self.a)
        claude_link.mark_expired(self.a.id)
        job = agents.claim_next(can_mac=True)
        self.assertEqual((job.provider, job.model), ("mistral", "mistral-small-2603"))

    def test_merge_and_the_managers_notes_without_approval(self):
        self.mistral(self.a)
        self.stage("done", "built")
        self.stage("pass")
        self.stage("ok")
        task = agents.list_tasks(self.a.id, self.pa.id)[0]
        self.assertIsNone(agents.claim_next(can_mac=True))                    # waits for the merge
        self.assertTrue(agents.merge_done(task.id, True))
        job = agents.claim_next(can_mac=True)
        self.assertEqual((job.role, job.purpose), ("chef", "doc"))
        self.assertIn("the reviewer agreed and the hub merged it", job.prompt)
        agents.finish_run(job.run_id, "done", 'Noted.<memory file="ARCHIVE.md">- Verworfen: 24 V. Grund: Sicherheit</memory>')
        self.assertEqual(agents.get_task(self.a.id, task.id).stage, "done")
        archive = next(f for f in files.list_files(self.a.id, self.pa.id) if f.name == "ARCHIVE.md")
        self.assertIn("24 V", files.read_text(self.a.id, archive.id))
        self.assertEqual(agents.finished_tasks(), [task.id])                  # its folder can go

    def test_a_merge_conflict_goes_back_to_the_programmer(self):
        self.mistral(self.a)
        self.stage("done")
        self.stage("pass")
        self.stage("ok")
        task = agents.list_tasks(self.a.id, self.pa.id)[0]
        self.assertTrue(agents.merge_done(task.id, False))
        self.assertEqual(agents.get_task(self.a.id, task.id).stage, "coding")
        self.assertEqual(agents.pending_merges(), [])


class ParallelTest(Base):
    """Janis, 15.11.2026: how many AI runs go at once is the owner's setting (1 on a small server)."""

    def setUp(self):
        super().setUp()
        statusnote._LAST_SCAN["at"] = 2 ** 40   # no status round in between (it ran only when another test set this)
        self.claude(self.a)
        self.claude(self.b)

    def test_one_at_a_time_by_default_more_when_the_owner_says_so(self):
        from app import serversettings
        self.assertEqual(serversettings.ai_parallel(), 1)
        self.assertIsNotNone(agents.claim_next(can_mac=True))                 # an agent run takes the slot
        chat.send(self.b.id, self.pb.id, "Hello", now=10**10)
        self.assertIsNone(chat.claim_next(now=10**10))                        # the question waits ...
        self.assertEqual(chat.list_messages(self.b.id, self.pb.id)[-1].status, "queued")   # ... and does not run out
        serversettings.set_ai_parallel(2)
        self.assertIsNotNone(chat.claim_next(now=10**10))
        serversettings.set_ai_parallel(0)                                     # no limit
        with db.connect() as conn:
            self.assertTrue(agents.slot_free(conn))
        with self.assertRaises(ValueError):
            serversettings.set_ai_parallel(7)

    def test_the_owners_page_and_route(self):
        from app import serversettings, systempage
        from app.routes import system as system_routes
        owner = users.create_user("owner@example.com", "Own3r!pass", role="owner")
        html = systempage.render(owner)
        self.assertIn('data-url="/system/ai"', html)
        self.assertIn(i18n.t("de", "sys_ai_unlimited"), html)
        self.assertEqual(system_routes.ai_settings(3, user=owner), {"ok": True})
        self.assertEqual(serversettings.ai_parallel(), 3)
        self.assertEqual(system_routes.ai_settings(9, user=owner).status_code, 400)
        self.assertEqual(system_routes.ai_settings(1, user=self.a).status_code, 403)   # only the owner
        self.assertEqual(serversettings.ai_parallel(), 3)


class DesignRuleTest(Base):
    def test_the_design_lives_in_the_rules(self):
        memory.ensure_skeleton(self.a.id, self.pa.id, "de")
        rules = next(f for f in files.list_files(self.a.id, self.pa.id) if f.name == "RULES.md")
        self.assertIn("# Design", files.read_text(self.a.id, rules.id))
        self.claude(self.a)
        chat.send(self.a.id, self.pa.id, "Hello")
        self.assertIn("its heading Design for the look", chat.claim_next().prompt)


class BoardTest(Base):
    def html(self):
        return projectpage.render(self.a, self.pa, board.list_items(self.a.id, self.pa.id))

    def test_the_item_leaves_the_board_and_the_line_says_where_it_is(self):
        self.mistral(self.a)
        self.assertIn('data-id="%d"' % self.item.id, self.html())             # waits on the board
        self.assertNotIn('data-action="agent-start"', self.html())          # no start by hand
        job = agents.claim_next(can_mac=True)
        page = self.html()
        board_part = page[page.index('id="board"'):page.index('id="board"') + 4000]
        self.assertNotIn('data-id="%d"' % self.item.id, board_part)          # taken: off the board
        self.assertIn("Programmierer arbeitet an „Fix the relay“", page)
        agents.finish_run(job.run_id, "done", "built the relay switch", change=("relay.py | 1 +", "+ON"), committed=True)
        self.assertIsNotNone(agents.claim_next(can_mac=True))
        self.assertIn("Tester arbeitet an „Fix the relay“", self.html())

    def test_no_ai_says_so_above_the_board(self):
        self.mistral(self.a)
        agents.claim_next(can_mac=True)
        ai_link.disconnect(self.a.id, "mistral")
        self.assertIn("„Fix the relay“ wartet: keine KI verknüpft", self.html())

    def test_every_new_text_in_both_languages(self):
        for key in ("chat_err_none", "chat_fail_limit", "chat_fallback", "ai_default_short", "ai_default_hint",
                    "sys_ai", "sys_ai_unlimited", "sys_ai_info",
                    "bs_working", "bs_queued", "bs_paused", "bs_no_ai", "bs_mac", "bs_merging", "bs_question",
                    "bs_todo", "bs_decision", "w_again", "w_accept", "w_cancel", "w_decide", "w_hint", "task_cancel",
                    *(f"w_why_{why}" for why in agents.workflow.WHY)):
            self.assertIn(key, i18n.STRINGS["de"])
            self.assertIn(key, i18n.STRINGS["en"])


if __name__ == "__main__":
    unittest.main()
