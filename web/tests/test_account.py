"""The account page (Janis, 18.11.2026): name, language, password, colour mode (placeholder) and deleting the own
account; the drawer only leads there."""
import dataclasses
import os
import re
import tempfile
import types
import unittest

from app import accountpage, db, i18n, projects, systempage, ui, users
from app.deps import COOKIE_NAME
from app.routes import account, auth


class AccountTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.owner = users.create_user("owner@example.com", "Own3r!pass", role="owner")
        self.user = users.add_user(self.owner, "user@example.com", "Start1234")
        users.change_own_password(self.user, "", "Mein!Pass12")
        self.user = users.get_by_id(self.user.id)

    def tearDown(self):
        self.tmp.cleanup()

    def request(self):
        return types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="203.0.113.9"))

    def test_the_page_in_both_languages(self):
        for lang, words in (("de", ("Konto", "Nutzername", "Passwort ändern", "Konto löschen")),
                            ("en", ("Account", "Username", "Change password", "Delete account"))):
            user = dataclasses.replace(self.user, language=lang)
            html = accountpage.render(user)
            for word in words:
                self.assertIn(word, html)
            self.assertIsNone(re.search(r"%[A-Za-z_.]+%", html), "placeholder left over")
            self.assertIn('action="/settings"', html)
            self.assertIn('action="/password"', html)
        self.assertIn("data-account-delete", accountpage.render(self.user))
        self.assertNotIn("data-account-delete", accountpage.render(self.owner))            # the owner hands on first
        self.assertNotIn("info-dot", accountpage.render(self.user))                        # nothing here needs an "i"

    def test_the_name_is_escaped(self):
        users.set_profile(self.user.id, '<b>x</b>"', "de")
        html = accountpage.render(users.get_by_id(self.user.id))
        self.assertNotIn("<b>x</b>", html)

    def test_the_drawer_leads_to_the_account_page(self):
        for who in (self.owner, self.user):
            bar = ui.settings_bar(who)
            self.assertIn('<a class="admin-btn" href="/account">Konto</a>', bar)
            for gone in ('name="display_name"', 'name="language"', 'class="primary save"', 'href="/password"'):
                self.assertNotIn(gone, bar)
        bar = ui.settings_bar(self.owner)
        order = ['id="claude-open"', 'id="chat-clear-open"', 'href="/account"', 'href="/admin"', 'action="/logout"']
        self.assertEqual([bar.index(p) for p in order], sorted(bar.index(p) for p in order))
        self.assertNotIn('href="/admin"', ui.settings_bar(self.user))

    def test_saving_name_and_language_goes_back_to_the_account_page(self):
        answer = auth.save_settings(self.user, "Neu", "en")
        self.assertEqual((answer.status_code, answer.headers["location"]), (303, "/account"))
        self.assertEqual(users.get_by_id(self.user.id).language, "en")

    def test_a_user_deletes_the_own_account_with_the_password(self):
        mine = projects.create_project(self.user.id, "Mine")
        token = users.create_session(self.user.id)
        self.assertEqual(account.delete_account(self.request(), "wrong", self.user).status_code, 403)
        self.assertIsNotNone(users.get_by_id(self.user.id))
        answer = account.delete_account(self.request(), "Mein!Pass12", self.user)
        self.assertEqual(answer.status_code, 200)
        self.assertIn(COOKIE_NAME + "=", answer.headers["set-cookie"])          # and this browser forgets the login
        self.assertIsNone(users.get_by_id(self.user.id))                        # locked
        self.assertIsNone(users.get_user(token))                                # signed out everywhere
        self.assertIsNone(users.check_login("user@example.com", "Mein!Pass12"))
        self.assertIsNotNone(projects.get_project(self.user.id, mine.id))      # kept for 30 days, like delete_user
        self.assertIsNotNone(users.get_by_id(self.owner.id))                    # nobody else is touched
        self.assertEqual(users.purge_deleted(now=10 ** 11), 1)                  # and gone for good after the time
        self.assertIsNone(projects.get_project(self.user.id, mine.id))

    def test_the_owner_can_not_delete_the_own_account(self):
        with self.assertRaises(users.UserError):
            users.delete_self(self.owner)
        answer = account.delete_account(self.request(), "Own3r!pass", self.owner)
        self.assertEqual(answer.status_code, 409)
        self.assertIn(i18n.t("de", "account_delete_owner"), answer.body.decode())
        self.assertIsNotNone(users.get_by_id(self.owner.id))

    def test_routes_need_a_login(self):
        from app.deps import api_user, page_user
        for route in account.router.routes:
            calls = {d.call for d in route.dependant.dependencies}
            self.assertTrue(calls & {api_user, page_user}, route.path)

    def test_skins_are_a_placeholder_in_the_system_block(self):
        html = systempage.render(self.owner)
        self.assertIn(f'disabled>{i18n.t("de", "sys_skins")}</button></div>', html)        # greyed out, no "i"


if __name__ == "__main__":
    unittest.main()
