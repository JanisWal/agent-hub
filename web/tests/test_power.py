"""Restart and shutdown of the Pi: who may ask, what the runner gets, what the page and routes do."""
import os
import tempfile
import time
import types
import unittest
from unittest import mock

from fastapi import HTTPException

from app import adminpage, db, i18n, power, systempage, users
from app.routes import admin as admin_routes, runner, system


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
        job = power.claim_next()
        self.assertEqual(job[1], "poweroff")
        self.assertIsNone(power.claim_next())

    def test_a_second_request_waits_for_the_first(self):
        self.assertTrue(power.request_action(self.owner, "reboot"))
        self.assertFalse(power.request_action(self.owner, "poweroff"))
        self.assertEqual(power.claim_next()[1], "reboot")
        self.assertTrue(power.request_action(self.owner, "poweroff"))   # the first one is taken, a new one may follow
        self.assertEqual(power.claim_next()[1], "poweroff")

    def test_an_old_request_is_dropped_instead_of_firing_later(self):
        self.assertTrue(power.request_action(self.owner, "poweroff"))
        later = time.time() + power.FRESH_SECONDS + 5
        with mock.patch.object(power.time, "time", return_value=later):
            self.assertIsNone(power.claim_next())
            self.assertTrue(power.request_action(self.owner, "reboot"))   # the stale one does not block
            self.assertEqual(power.claim_next()[1], "reboot")

    # --- the manual backup
    def test_a_backup_goes_through_the_states_none_running_ok(self):
        self.assertEqual(power.backup_state(), "none")
        self.assertTrue(power.request_action(self.owner, "backup"))
        self.assertEqual(power.backup_state(), "running")                  # asked, not fetched yet
        request_id, action = power.claim_next()
        self.assertEqual(action, "backup")
        self.assertEqual(power.backup_state(), "running")                  # fetched, running
        self.assertTrue(power.finish(request_id, True))
        self.assertEqual(power.backup_state(), "ok")
        self.assertFalse(power.finish(request_id, False))                  # one result only
        self.assertEqual(power.backup_state(), "ok")

    def test_a_failed_backup_says_so(self):
        power.request_action(self.owner, "backup")
        request_id, _ = power.claim_next()
        self.assertTrue(power.finish(request_id, False))
        self.assertEqual(power.backup_state(), "failed")

    def test_a_backup_nobody_fetched_or_nobody_reported_counts_as_failed(self):
        power.request_action(self.owner, "backup")
        with mock.patch.object(power.time, "time", return_value=time.time() + power.FRESH_SECONDS + 5):
            self.assertEqual(power.backup_state(), "failed")                # the runner did not come
        power.claim_next()
        with mock.patch.object(power.time, "time", return_value=time.time() + power.BACKUP_SECONDS + 5):
            self.assertEqual(power.backup_state(), "failed")                # it started and never reported

    def test_only_a_taken_backup_can_be_finished(self):
        power.request_action(self.owner, "backup")
        self.assertFalse(power.finish(1, True))                             # not fetched yet
        self.assertFalse(power.finish(999, True))                           # unknown
        power.claim_next()
        power.request_action(self.owner, "reboot")
        reboot_id, _ = power.claim_next()
        self.assertFalse(power.finish(reboot_id, True))                     # not a backup: nothing to report

    def test_a_newer_backup_replaces_the_state_of_the_older_one(self):
        power.request_action(self.owner, "backup")
        first, _ = power.claim_next()
        power.finish(first, False)
        power.request_action(self.owner, "backup")
        self.assertEqual(power.backup_state(), "running")

    # --- the routes
    def test_the_power_route(self):
        answer = system.power_action(self.request(), "reboot", "Own3r!pass", self.owner)
        self.assertEqual(answer, {"ok": True})
        claimed = runner.power_claim()
        self.assertEqual((claimed["ok"], claimed["action"]), (True, "reboot"))
        self.assertIsInstance(claimed["id"], int)
        self.assertEqual(runner.power_claim(), {"ok": True, "id": None, "action": None})

    def test_the_power_route_checks_who_what_and_the_password(self):
        self.assertEqual(system.power_action(self.request(), "reboot", "Adm1n!pass", self.admin).status_code, 403)
        self.assertEqual(system.power_action(self.request(), "halt", "Own3r!pass", self.owner).status_code, 400)
        self.assertEqual(system.power_action(self.request(), "reboot", "wrong", self.owner).status_code, 403)
        self.assertEqual(system.power_action(self.request(), "reboot", "", self.owner).status_code, 403)
        self.assertIsNone(power.claim_next())   # nothing was asked

    def test_a_backup_needs_no_password_but_the_owner(self):
        self.assertEqual(system.power_action(self.request(), "backup", "", self.admin).status_code, 403)
        self.assertEqual(system.power_action(self.request(), "backup", "", self.user).status_code, 403)
        self.assertIsNone(power.claim_next())
        self.assertEqual(system.power_action(self.request(), "backup", "", self.owner), {"ok": True})
        self.assertEqual(system.backup_status(self.owner), {"ok": True, "state": "running"})
        request_id, action = power.claim_next()
        self.assertEqual(action, "backup")
        self.assertEqual(runner.power_result(request_id, "1"), {"ok": True})
        self.assertEqual(system.backup_status(self.owner), {"ok": True, "state": "ok"})
        self.assertEqual(runner.power_result(request_id, "1").status_code, 409)   # reported once

    def test_the_backup_status_is_for_the_owner_only(self):
        for who in (self.admin, self.user):
            self.assertEqual(system.backup_status(who).status_code, 403)
        self.assertEqual(system.backup_status(self.owner), {"ok": True, "state": "none"})

    def test_a_second_request_gets_a_clear_answer(self):
        system.power_action(self.request(), "reboot", "Own3r!pass", self.owner)
        again = system.power_action(self.request(), "poweroff", "Own3r!pass", self.owner)
        self.assertEqual(again.status_code, 409)

    # --- the page and the menu
    def test_the_old_address_leads_to_the_administration_page_for_the_owner_only(self):
        answer = admin_routes.system_old_address(self.owner)
        self.assertEqual((answer.status_code, answer.headers["location"]), (303, "/admin"))
        for who in (self.admin, self.user):
            with self.assertRaises(HTTPException) as refused:
                admin_routes.system_old_address(who)
            self.assertEqual(refused.exception.status_code, 404)

    def test_the_page_has_three_actions_and_asks_for_the_password_for_two(self):
        html = systempage.render(self.owner)
        self.assertEqual(html.count("data-backup"), 1)                      # a button without a dialog
        self.assertLess(html.index("data-backup"), html.index('data-power="reboot"'))   # the harmless one first
        for part in ('id="sys-backup-note"', 'id="sys-power-note"',
                     'data-power="reboot"', 'data-power="poweroff"', 'id="power-reboot-dialog"',
                     'dialog danger" id="power-poweroff-dialog"', 'name="confirm"', 'type="password"'):
            self.assertIn(part, html)
        self.assertNotIn("%t.", html)   # every text was filled in

    def test_only_the_owner_gets_the_system_block_on_the_administration_page(self):
        self.assertIn('data-power="reboot"', adminpage.render(self.owner, users.list_users(self.owner)))
        self.assertNotIn("data-power", adminpage.render(self.admin, users.list_users(self.admin)))
        self.assertIn("data-backup", adminpage.render(self.owner, users.list_users(self.owner)))
        self.assertNotIn("data-backup", adminpage.render(self.admin, users.list_users(self.admin)))

    def test_texts_exist_in_both_languages(self):
        self.assertEqual(i18n.t("de", "system_title"), i18n.t("en", "system_title"))   # the same word in both
        for key in ("sys_backup", "sys_backup_hint", "sys_backup_running", "sys_backup_ok", "sys_backup_failed",
                    "sys_reboot", "sys_reboot_hint", "sys_reboot_title", "sys_reboot_do",
                    "sys_reboot_done", "sys_poweroff", "sys_poweroff_hint", "sys_poweroff_title",
                    "sys_poweroff_do", "sys_poweroff_done", "err_power_busy"):
            self.assertNotEqual(i18n.t("de", key), i18n.t("en", key), key)


if __name__ == "__main__":
    unittest.main()
