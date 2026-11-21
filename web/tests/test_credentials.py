"""An API key next to the plan of Claude and ChatGPT (Janis, 21.11.2026): used only as the user set it (credentials.py),
switched to only from the plan and never back, counted per day, strictly the user's own."""
import os
import tempfile
import time
import unittest

from app import agents, ai_link, aichoice, board, chat, claude_link, credentials, db, projects, statusnote, ui, users
from app.routes import ai as ai_routes

CLAUDE_KEY = "sk-ant-api03-" + "A1b2C3d4" * 5
OPENAI_KEY = "sk-proj-" + "Z9y8X7w6" * 5


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        ai_link._keys.clear()
        statusnote._LAST_SCAN["at"] = 2 ** 40
        self.a = users.create_user("a@example.com", "Aaaa!pass12")
        self.b = users.create_user("b@example.com", "Bbbb!pass12")
        self.pa = projects.create_project(self.a.id, "Rechner")

    def tearDown(self):
        self.tmp.cleanup()
        ai_link._keys.clear()

    def plan(self, user):
        claude_link.begin(user.id)
        claude_link.complete(user.id, True)

    def key(self, user, provider="claude", key=CLAUDE_KEY, **settings):
        form = {"mode": "fallback", "scope": "all", "daily": "0", **settings}
        answer = ai_routes.api_save(provider, key=key, user=user, **form)
        self.assertTrue(answer["ok"], answer)
        [item] = ai_link.take_keys()
        self.assertEqual(item["provider"], credentials.API_FOR[provider])
        self.assertTrue(ai_link.complete(user.id, credentials.API_FOR[provider], True))

    def ways(self, user, kind, provider="claude"):
        with db.connect() as conn:
            return credentials.order(conn, user.id, provider, kind)


class SettingsTest(Base):
    def test_defaults_and_checked_values(self):
        self.assertEqual(ai_routes.api_settings("claude", user=self.a),
                         {"ok": True, "status": "none", "connected": False, "mode": "fallback", "scope": "all",
                          "daily": 0, "spent": 0})
        self.assertEqual(ai_routes.api_settings("mistral", user=self.a).status_code, 404)   # no plan, no key beside
        for bad in ({"mode": "sometimes"}, {"scope": "nights"}, {"daily": "-1"}, {"daily": "ten"},
                    {"daily": str(credentials.MAX_DAILY + 1)}):
            form = {"mode": "fallback", "scope": "all", "daily": "0", **bad}
            answer = ai_routes.api_save("claude", key="", user=self.a, **form)
            self.assertEqual((answer.status_code, answer.body), (400, b'{"ok":false,"field":"settings"}'), bad)
        answer = ai_routes.api_save("claude", key="sk-not-a-key", mode="always", scope="all", daily="0", user=self.a)
        self.assertEqual((answer.status_code, answer.body), (400, b'{"ok":false,"field":"key"}'))
        answer = ai_routes.api_save("claude", key="", mode="always", scope="runs", daily="500", user=self.a)
        self.assertEqual((answer["mode"], answer["scope"], answer["daily"]), ("always", "runs", 500))

    def test_the_key_is_checked_by_the_runner_and_never_shown(self):
        self.key(self.a)
        answer = ai_routes.api_settings("claude", user=self.a)
        self.assertEqual(answer["status"], "connected")
        self.assertNotIn(CLAUDE_KEY, str(answer))
        self.assertNotIn(CLAUDE_KEY, ui.settings_bar(self.a))
        self.assertEqual(ai_routes.api_remove("claude", user=self.a), {"ok": True})
        self.assertEqual(ai_link.pending_wipes(), [(self.a.id, "claude-api")])     # the runner deletes the key
        self.assertEqual(ai_routes.api_settings("claude", user=self.a)["status"], "none")

    def test_the_key_and_the_settings_are_only_the_users(self):
        self.key(self.a, mode="always")
        self.assertEqual(ai_routes.api_settings("claude", user=self.b)["status"], "none")
        self.assertEqual(ai_routes.api_settings("claude", user=self.b)["mode"], "fallback")
        ai_routes.api_remove("claude", user=self.b)                                 # B can not remove A's key
        self.assertEqual(ai_routes.api_settings("claude", user=self.a)["status"], "connected")
        self.assertEqual(self.ways(self.b, "chat"), [])
        self.assertEqual(aichoice.connected(self.b.id), [])


class OrderTest(Base):
    def test_plan_first_the_key_after_it_or_instead_or_not_at_all(self):
        self.plan(self.a)
        self.assertEqual(self.ways(self.a, "chat"), ["plan"])
        self.key(self.a)
        self.assertEqual(self.ways(self.a, "chat"), ["plan", "api"])
        ai_routes.api_save("claude", key="", mode="always", scope="all", daily="0", user=self.a)
        self.assertEqual(self.ways(self.a, "run"), ["api", "plan"])
        ai_routes.api_save("claude", key="", mode="off", scope="all", daily="0", user=self.a)
        self.assertEqual(self.ways(self.a, "run"), ["plan"])

    def test_scope_and_daily_limit(self):
        self.plan(self.a)
        self.key(self.a, scope="runs", daily="2")
        self.assertEqual(self.ways(self.a, "chat"), ["plan"])
        self.assertEqual(self.ways(self.a, "run"), ["plan", "api"])
        now = int(time.time())
        with db.connect() as conn:
            conn.execute("INSERT INTO chat_messages (user_id, project_id, prompt, answer, status, provider, model,"
                         " credential, tokens_in, tokens_out, created_at) VALUES (?, ?, 'q', 'a', 'done', 'claude',"
                         " 'sonnet', 'api', 1500, 600, ?)", (self.a.id, self.pa.id, now))
            conn.execute("INSERT INTO chat_messages (user_id, project_id, prompt, answer, status, provider, model,"
                         " credential, tokens_in, tokens_out, created_at) VALUES (?, ?, 'q', 'a', 'done', 'claude',"
                         " 'sonnet', 'plan', 90000, 0, ?)", (self.a.id, self.pa.id, now))    # the plan's: not counted
            self.assertEqual(credentials.spent_today(conn, self.a.id, "claude"), 2100)
            self.assertEqual(credentials.spent_today(conn, self.b.id, "claude"), 0)
        self.assertEqual(self.ways(self.a, "run"), ["plan"])                       # 2 thousand reached: until tomorrow

    def test_a_key_alone_makes_the_ai_usable(self):
        self.key(self.a, "chatgpt", OPENAI_KEY)
        self.assertEqual(aichoice.connected(self.a.id), ["chatgpt"])
        self.assertEqual(self.ways(self.a, "chat", "chatgpt"), ["api"])


class SwitchTest(Base):
    def test_a_used_up_plan_goes_on_with_the_key_and_never_back(self):
        self.plan(self.a)
        self.key(self.a)
        chat.send(self.a.id, self.pa.id, "Hallo")
        job = chat.claim_next()
        self.assertEqual(job.credential, "plan")
        self.assertTrue(chat.finish(job.chat_id, False, "Claude usage limit reached", 10, 0))
        job = chat.claim_next()
        self.assertEqual((job.provider, job.credential), ("claude", "api"))       # the same question, with the key
        self.assertTrue(chat.finish(job.chat_id, False, "API Error: 429 rate limit", 0, 0))
        self.assertIsNone(chat.claim_next())                                       # no way back to the plan: no loop
        [message] = chat.list_messages(self.a.id, self.pa.id)
        self.assertEqual(message.status, "failed")

    def test_without_permission_the_key_is_not_touched(self):
        self.plan(self.a)
        self.key(self.a, mode="off")
        chat.send(self.a.id, self.pa.id, "Hallo")
        job = chat.claim_next()
        chat.finish(job.chat_id, False, "Claude usage limit reached", 0, 0)
        self.assertIsNone(chat.claim_next())

    def test_an_agent_run_switches_the_same_way(self):
        self.plan(self.a)
        self.key(self.a, scope="runs")
        item = board.create_item(self.a.id, self.pa.id, "minor", "Addieren")
        agents.start_item(self.a.id, item.id)
        run = agents.claim_next(can_mac=False)
        self.assertEqual(run.credential, "plan")
        self.assertTrue(agents.finish_run(run.run_id, "failed", "You've hit your usage limit"))
        again = agents.claim_next(can_mac=False)
        self.assertEqual((again.run_id, again.credential), (run.run_id, "api"))


class DialogTest(Base):
    def test_both_halves_in_both_languages(self):
        for lang, plan, costs in (("de", "Mit Abo anmelden", "Kann Zusatzkosten verursachen"),
                                  ("en", "Sign in with your plan", "May cause extra costs")):
            users.set_profile(self.a.id, "", lang)
            page = ui.settings_bar(users.get_by_id(self.a.id))
            self.assertEqual(page.count('class="link-split"'), 2)                   # Claude and ChatGPT
            self.assertIn(plan, page)
            self.assertIn(costs, page)
            self.assertNotIn("%t.", page)
            self.assertNotIn("%API%", page)

    def test_connected_opens_the_dialog_with_both_halves_as_they_are(self):
        page = ui.settings_bar(self.a)
        self.assertNotIn('data-manage="claude"', page)                              # nothing connected: "Verknüpfen"
        self.key(self.a)                                                            # only the key
        page = ui.settings_bar(self.a)
        row = page[page.index('id="claude-row"'):page.index('id="claude-row"') + 900]
        self.assertIn('data-manage="claude" data-plan="none"', row)                 # shown as connected
        self.assertIn(">Verknüpft<", row)
        self.assertIn('name="key" maxlength="300" autocomplete="off" spellcheck="false" disabled', page)   # greyed
        self.assertIn("Anmeldung und API-Schlüssel werden getrennt", page)       # "disconnect" takes both
        self.plan(self.a)
        page = ui.settings_bar(self.a)
        self.assertIn('data-manage="claude" data-plan="connected"', page)
        self.assertIn('data-step="plan-on"', page)
        self.assertIn("data-plan-off", page)                                         # the plan on its own

    def test_codes_copy_with_one_click(self):
        page = ui.settings_bar(self.a)
        self.assertIn('<template id="copy-tpl"><button class="icon-button card-btn copy-btn"', page)
        device = page[page.index('id="key-dialog-chatgpt"'):]
        self.assertIn('class="copy-box copy-click device-copy"', device)
        self.assertIn("data-device-code data-copy-text", device)
        self.assertIn('data-done="Kopiert"', device)

    def test_the_row_says_how_the_key_is_used(self):
        self.plan(self.a)
        self.key(self.a, mode="always")
        self.assertIn("API: Immer statt Abo", ui.settings_bar(self.a))


if __name__ == "__main__":
    unittest.main()
