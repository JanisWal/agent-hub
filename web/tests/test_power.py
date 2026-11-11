"""Restart and shutdown of the Pi: who may ask, what the runner gets, what the page and routes do."""
import os
import tempfile
import time
import types
import unittest
from unittest import mock

from fastapi import HTTPException

from app import db, i18n, power, systempage, ui, users
from app.routes import runner, system


class PowerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.owner = users.create_user("owner@example.com", "Own3r!pass", role="owner")
        self.admin = users.create_user("admin@example.com", "Adm1n!pass", role="admin")
        self.user = users.add_user(self.owner, "user@example.com", "Start1234")

    def tearDown(self):
        self.tmp.cleanup()

    def request(self):
        return types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="203.0.113.7"))

    # --- the data module
    def test_only_the_owner_may_ask(self):
        for who in (self.admin, self.user):
            with self.assertRaises(PermissionError):
                power.request_action(who, "reboot")
        self.assertIsNone(power.claim_next())

    def test_unknown_actions_are_refused(self):
        for action in ("", "halt", "reboot; rm -rf /", "REBOOT"):
            with self.assertRaises(ValueError):
                power.request_action(self.owner, action)
        self.assertIsNone(power.claim_next())

    def test_a_request_is_handed_out_once(self):
        self.assertTrue(power.request_action(self.owner, "poweroff"))
        self.assertEqual(power.claim_next(), "poweroff")
        self.assertIsNone(power.claim_next())

    def test_a_second_request_waits_for_the_first(self):
        self.assertTrue(power.request_action(self.owner, "reboot"))
        self.assertFalse(power.request_action(self.owner, "poweroff"))
        self.assertEqual(power.claim_next(), "reboot")
        self.assertTrue(power.request_action(self.owner, "poweroff"))   # the first one is taken, a new one may follow
        self.assertEqual(power.claim_next(), "poweroff")

    def test_an_old_request_is_dropped_instead_of_firing_later(self):
        self.assertTrue(power.request_action(self.owner, "poweroff"))
        later = time.time() + power.FRESH_SECONDS + 5
        with mock.patch.object(power.time, "time", return_value=later):
            self.assertIsNone(power.claim_next())
            self.assertTrue(power.request_action(self.owner, "reboot"))   # the stale one does not block
            self.assertEqual(power.claim_next(), "reboot")

    # --- the routes
    def test_the_power_route(self):
        answer = system.power_action(self.request(), "reboot", "Own3r!pass", self.owner)
        self.assertEqual(answer, {"ok": True})
        self.assertEqual(runner.power_claim(), {"ok": True, "action": "reboot"})
        self.assertEqual(runner.power_claim(), {"ok": True, "action": None})

    def test_the_power_route_checks_who_what_and_the_password(self):
        self.assertEqual(system.power_action(self.request(), "reboot", "Adm1n!pass", self.admin).status_code, 403)
        self.assertEqual(system.power_action(self.request(), "halt", "Own3r!pass", self.owner).status_code, 400)
        self.assertEqual(system.power_action(self.request(), "reboot", "wrong", self.owner).status_code, 403)
        self.assertEqual(system.power_action(self.request(), "reboot", "", self.owner).status_code, 403)
        self.assertIsNone(power.claim_next())   # nothing was asked

    def test_a_second_request_gets_a_clear_answer(self):
        system.power_action(self.request(), "reboot", "Own3r!pass", self.owner)
        again = system.power_action(self.request(), "poweroff", "Own3r!pass", self.owner)
        self.assertEqual(again.status_code, 409)

    # --- the page and the menu
    def test_the_page_is_for_the_owner_only(self):
        self.assertIn("data-power=\"reboot\"", system.system_page(self.owner))
        for who in (self.admin, self.user):
            with self.assertRaises(HTTPException) as refused:
                system.system_page(who)
            self.assertEqual(refused.exception.status_code, 404)

    def test_the_page_has_both_actions_and_asks_for_the_password(self):
        html = systempage.render(self.owner)
        for part in ('data-power="reboot"', 'data-power="poweroff"', 'id="power-reboot-dialog"',
                     'dialog danger" id="power-poweroff-dialog"', 'name="confirm"', 'type="password"'):
            self.assertIn(part, html)
        self.assertNotIn("%t.", html)   # every text was filled in

    def test_only_the_owner_sees_the_menu_link(self):
        link = 'href="/system"'
        self.assertIn(link, ui.settings_bar(self.owner))
        self.assertNotIn(link, ui.settings_bar(self.admin))
        self.assertNotIn(link, ui.settings_bar(self.user))

    def test_texts_exist_in_both_languages(self):
        self.assertEqual(i18n.t("de", "system_title"), i18n.t("en", "system_title"))   # the same word in both
        for key in ("sys_reboot", "sys_reboot_hint", "sys_reboot_title", "sys_reboot_do",
                    "sys_reboot_done", "sys_poweroff", "sys_poweroff_hint", "sys_poweroff_title",
                    "sys_poweroff_do", "sys_poweroff_done", "err_power_busy"):
            self.assertNotEqual(i18n.t("de", key), i18n.t("en", key), key)


if __name__ == "__main__":
    unittest.main()
