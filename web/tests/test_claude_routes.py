"""The Claude connection as the user sees it: routes of the settings drawer and the drawer itself."""
import dataclasses
import os
import tempfile
import unittest
from pathlib import Path

from app import claude_link, db, i18n, ui, users
from app.routes import claude as routes


class ClaudeRoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        claude_link._codes.clear()
        self.a = users.create_user("a@example.com", "Aaaa!pass12")
        self.b = users.create_user("b@example.com", "Bbbb!pass12")

    def tearDown(self):
        self.tmp.cleanup()

    def test_whole_login_as_the_user_does_it(self):
        self.assertEqual(routes.status(user=self.a), {"ok": True, "status": "none", "login_url": None})
        self.assertEqual(routes.code("abc", user=self.a).status_code, 409)         # nothing waits for a code
        self.assertEqual(routes.connect(user=self.a)["status"], "connecting")
        self.assertIsNone(routes.status(user=self.a)["login_url"])                 # runner has not answered yet
        claude_link.set_login_url(self.a.id, "https://claude.ai/oauth?x=1")        # the runner does this
        self.assertEqual(routes.status(user=self.a)["login_url"], "https://claude.ai/oauth?x=1")
        self.assertEqual(routes.connect(user=self.a)["login_url"], "https://claude.ai/oauth?x=1")  # resume
        self.assertEqual(routes.code("   ", user=self.a).status_code, 400)
        self.assertEqual(routes.code("the-code", user=self.a), {"ok": True})
        self.assertEqual(claude_link.take_code(self.a.id), "the-code")             # what the runner fetches
        claude_link.complete(self.a.id, True)
        self.assertEqual(routes.status(user=self.a)["status"], "connected")
        self.assertEqual(routes.connect(user=self.a)["status"], "connected")       # nothing is restarted
        self.assertEqual(routes.disconnect(user=self.a), {"ok": True})
        self.assertEqual(routes.status(user=self.a)["status"], "none")

    def test_cancel_a_running_login(self):
        routes.connect(user=self.a)
        routes.disconnect(user=self.a)
        self.assertEqual(routes.status(user=self.a)["status"], "none")

    def test_users_never_touch_each_other(self):
        routes.connect(user=self.a)
        claude_link.set_login_url(self.a.id, "https://claude.ai/oauth?x=1")
        self.assertEqual(routes.status(user=self.b), {"ok": True, "status": "none", "login_url": None})
        self.assertEqual(routes.code("stolen", user=self.b).status_code, 409)
        routes.disconnect(user=self.b)                                             # B cannot cancel A's login
        self.assertEqual(routes.status(user=self.a)["status"], "connecting")
        self.assertIsNone(claude_link.take_code(self.a.id))                        # and planted no code

    def test_every_route_needs_a_login(self):
        from app.deps import api_user
        for route in routes.router.routes:
            self.assertTrue(any(d.call is api_user for d in route.dependant.dependencies), route.path)


class DrawerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.a = users.create_user("a@example.com", "Aaaa!pass12")

    def tearDown(self):
        self.tmp.cleanup()

    def row(self, lang="de"):
        html = ui.settings_bar(dataclasses.replace(self.a, language=lang))
        start = html.index('class="setting service')
        return html[start:html.index("</div>", start)], html

    def test_each_state_has_its_style_and_text(self):
        expected = {
            "none": ("service ", "Nicht verknüpft"),
            "connected": ("service ok", "Verknüpft"),
            "connecting": ("service pending", "Wird verknüpft"),
            "expired": ("service expired", "Abgelaufen"),
        }
        for state, (cls, status) in expected.items():
            with db.connect() as conn:
                conn.execute("DELETE FROM claude_connections")
                if state != "none":
                    conn.execute("INSERT INTO claude_connections (user_id, status, updated_at)"
                                 " VALUES (?, ?, strftime('%s','now'))", (self.a.id, state))
            row, _ = self.row()
            self.assertIn(cls, row, state)
            self.assertIn(status, row, state)
            self.assertNotIn("link inline", row, state)                     # the status is the button (23.11.2026)
            self.assertIn(f'id="claude-open" data-status="{state}"', row)

    def test_dialog_is_in_the_drawer_in_both_languages(self):
        for lang, title in (("de", "Claude verknüpfen"), ("en", "Connect Claude")):
            _, html = self.row(lang)
            self.assertIn('id="claude-dialog"', html)
            self.assertIn(title, html)
            self.assertNotIn("%t.", html)                                         # every text was translated

    def test_chatgpt_can_be_connected_and_the_page_loads_the_script(self):
        _, html = self.row()
        self.assertIn('data-key-open="chatgpt"', html[html.index("ChatGPT"):])
        page = ui.logged_in_page(self.a, "Title", "<p>x</p>")
        self.assertIn("claude.js", page)

    def test_menu_has_its_own_button_for_deleting_the_chat_history(self):
        for lang, label, yes in (("de", "Chatverlauf löschen", "Chat leeren"),          # the archive keeps it (14.11.2026)
                                 ("en", "Delete chat history", "Clear chat")):
            _, html = self.row(lang)
            self.assertIn('class="clear-btn" type="button" id="chat-clear-open"', html)   # a button, no longer a link
            self.assertIn(label, html)
            self.assertIn('id="chat-clear-dialog"', html)
            self.assertIn('class="dialog danger"', html)
            self.assertIn(yes, html)
            self.assertNotIn("%t.", html)
        # The button sits under the Claude box and its folded list of other AIs (11.11.2026), inside the form but
        # never submitting it
        self.assertLess(html.index('id="claude-open"'), html.index("ChatGPT"))
        self.assertLess(html.index("ChatGPT"), html.index('id="chat-clear-open"'))
        self.assertLess(html.index('id="chat-clear-open"'), html.index('href="/account"'))
        # Cancel is the default focus, the red button is the only one that deletes
        dialog = html[html.index('id="chat-clear-dialog"'):]
        self.assertLess(dialog.index("autofocus"), dialog.index('id="chat-clear-yes"'))

    def test_no_texts_in_the_script(self):
        script = (Path(__file__).parent.parent / "app" / "static" / "claude.js").read_text(encoding="utf-8")
        for german_or_english in ("Verknüpf", "Claude ist", "Please", "Bitte"):
            self.assertNotIn(german_or_english, script)

    def test_texts_exist_in_both_languages(self):
        for key in ("claude_title", "claude_wait", "claude_steps", "claude_open", "claude_failed", "claude_stuck"):
            self.assertTrue(i18n.t("de", key) and i18n.t("en", key))
            self.assertNotEqual(i18n.t("de", key), i18n.t("en", key))


if __name__ == "__main__":
    unittest.main()
