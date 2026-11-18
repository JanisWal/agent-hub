"""The administration page (owner: System and Users side by side, admin: Users only, user: nothing) and the
rebuilt settings drawer (folded list of the other AIs, arrows in the same place, one quiet button)."""
import os
import re
import tempfile
import unittest

from fastapi import HTTPException

from app import adminpage, db, i18n, ui, users
from app.routes import admin as admin_routes


class AdministrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.owner = users.create_user("owner@example.com", "Own3r!pass", role="owner")
        self.admin = users.create_user("admin@example.com", "Adm1n!pass", role="admin")
        self.user = users.add_user(self.owner, "user@example.com", "Start1234")
        self.user = users.get_by_id(self.user.id)

    def tearDown(self):
        self.tmp.cleanup()

    def page(self, who):
        return admin_routes.admin_page(who)

    # --- who gets the page
    def test_owner_and_admin_get_the_page_a_normal_user_gets_404(self):
        for who in (self.owner, self.admin):
            self.assertIn("<h1", self.page(who))
        with self.assertRaises(HTTPException) as refused:
            self.page(self.user)
        self.assertEqual(refused.exception.status_code, 404)

    def test_the_old_user_address_leads_to_the_new_page(self):
        for who in (self.owner, self.admin):
            answer = admin_routes.users_old_address(who)
            self.assertEqual((answer.status_code, answer.headers["location"]), (303, "/admin"))
        with self.assertRaises(HTTPException):
            admin_routes.users_old_address(self.user)

    # --- what is on it
    def test_the_owner_sees_system_left_and_users_right(self):
        html = adminpage.render(self.owner, users.list_users(self.owner))
        self.assertIn('class="admin-wrap two"', html)
        self.assertLess(html.index('class="sys-wrap"'), html.index('class="users-wrap"'))
        self.assertIn('data-power="reboot"', html)
        self.assertIn('data-power="poweroff"', html)
        self.assertIn('id="add-user"', html)
        self.assertEqual(html.count('id="add-user"'), 1)     # the one main button of the page itself

    def test_an_admin_sees_only_users_in_the_middle(self):
        html = adminpage.render(self.admin, users.list_users(self.admin))
        self.assertIn('class="admin-wrap one"', html)
        self.assertNotIn("sys-wrap", html)
        self.assertNotIn("data-power", html)
        self.assertNotIn("power-reboot-dialog", html)
        self.assertIn('class="users-wrap"', html)

    def test_both_languages_are_filled_and_the_title_differs(self):
        for lang, title in (("de", "Verwaltung"), ("en", "Administration")):
            users.set_profile(self.owner.id, "", lang)
            html = adminpage.render(users.get_by_id(self.owner.id), users.list_users(self.owner))
            self.assertIsNone(re.search(r"%[A-Za-z_.]+%", html), "placeholder left over")
            self.assertIn(f">{title}</h1>", html)
        self.assertNotEqual(i18n.t("de", "admin_title"), i18n.t("en", "admin_title"))

    # --- the drawer
    def test_the_other_ais_sit_in_a_folded_list_under_the_claude_block(self):
        bar = ui.settings_bar(self.user)
        self.assertIn('id="ai-toggle" aria-expanded="false" aria-controls="ai-more"', bar)
        self.assertIn('<div class="ai-more" id="ai-more" hidden>', bar)
        folded = bar[bar.index('id="ai-more"'):]
        folded = folded[:folded.index('id="chat-clear-open"')]
        self.assertIn("ChatGPT", folded)
        self.assertNotIn("ChatGPT", bar[:bar.index('id="ai-more"')])           # not in the open part
        self.assertLess(bar.index('id="claude-open"'), bar.index('id="ai-more"'))
        self.assertLess(bar.index('id="ai-more"'), bar.index('id="chat-clear-open"'))

    def test_the_drawer_order(self):
        bar = ui.settings_bar(self.admin)
        parts = ['id="claude-open"', 'id="chat-clear-open"', 'href="/account"', 'href="/admin"', 'action="/logout"']
        positions = [bar.index(part) for part in parts]
        self.assertEqual(positions, sorted(positions))

    def test_the_toggle_has_a_label_in_both_languages(self):
        for lang, text in (("de", "Weitere KIs anzeigen"), ("en", "Show more AIs")):
            users.set_profile(self.user.id, "", lang)
            self.assertIn(f'aria-label="{text}"', ui.settings_bar(users.get_by_id(self.user.id)))


if __name__ == "__main__":
    unittest.main()
