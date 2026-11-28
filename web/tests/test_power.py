"""Restart and stop of the hub (28.11.2026): only the hub's own containers, never the server; who may ask, the job the
runner gets, what the page and routes do."""
import os
import tempfile
import types
import unittest

from fastapi import HTTPException

from app import adminpage, db, hostjobs, i18n, systempage, users
from app.routes import admin as admin_routes, system


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

    def test_restart_and_stop_touch_only_the_hubs_containers(self):
        """Janis, 27./28.11.2026: on a shared server or a VM the server keeps running; the gate shows the maintenance
        page meanwhile."""
        for action, job in (("reboot", "restart"), ("poweroff", "stop")):
            self.assertEqual(system.power_action(self.request(), action, "Own3r!pass", self.owner), {"ok": True})
            claimed = hostjobs.claim_next()
            self.assertEqual((claimed["action"], claimed["payload"]), (job, {}))
            hostjobs.end_open(job, "x")

    def test_one_at_a_time(self):
        self.assertEqual(system.power_action(self.request(), "reboot", "Own3r!pass", self.owner), {"ok": True})
        self.assertEqual(system.power_action(self.request(), "poweroff", "Own3r!pass", self.owner).status_code, 409)

    def test_who_what_and_the_password(self):
        self.assertEqual(system.power_action(self.request(), "reboot", "Adm1n!pass", self.admin).status_code, 403)
        self.assertEqual(system.power_action(self.request(), "reboot", "Start1234", self.user).status_code, 403)
        for bad in ("halt", "backup", "restart", "reboot; rm -rf /", ""):
            self.assertEqual(system.power_action(self.request(), bad, "Own3r!pass", self.owner).status_code, 400, bad)
        self.assertEqual(system.power_action(self.request(), "reboot", "wrong", self.owner).status_code, 403)
        self.assertEqual(system.power_action(self.request(), "reboot", "", self.owner).status_code, 403)
        self.assertIsNone(hostjobs.claim_next())   # nothing was asked

    def test_a_superadmin_may_ask_too(self):
        sup = users.get_by_id(users.create_user("super@example.com", "Sup3r!pass", role="superadmin").id)
        self.assertEqual(system.power_action(self.request(), "reboot", "wrong", sup).status_code, 403)   # password still asked
        self.assertEqual(system.power_action(self.request(), "reboot", "Sup3r!pass", sup), {"ok": True})
        self.assertIn("data-power", adminpage.render(sup, users.list_users(sup)))
        self.assertEqual(admin_routes.system_old_address(sup).status_code, 303)

    # --- the page and the menu
    def test_the_old_address_leads_to_the_administration_page_for_the_owner_only(self):
        answer = admin_routes.system_old_address(self.owner)
        self.assertEqual((answer.status_code, answer.headers["location"]), (303, "/admin"))
        for who in (self.admin, self.user):
            with self.assertRaises(HTTPException) as refused:
                admin_routes.system_old_address(who)
            self.assertEqual(refused.exception.status_code, 404)

    def test_the_page_has_the_backup_dialog_and_asks_for_the_password_for_both_power_actions(self):
        html = systempage.render(self.owner)
        self.assertEqual(html.count("data-backup-open"), 1)                 # the row that opens the backup dialog
        self.assertLess(html.index("data-backup-open"), html.index('data-power="reboot"'))   # the harmless one first
        for part in ('id="backup-dialog"', 'id="sys-power-note"', "data-setup-open",
                     'data-power="reboot"', 'data-power="poweroff"', 'id="power-reboot-dialog"',
                     'dialog danger" id="power-poweroff-dialog"', 'name="confirm"', 'type="password"'):
            self.assertIn(part, html)
        self.assertNotIn("%t.", html)   # every text was filled in

    def test_only_the_owner_gets_the_system_block_on_the_administration_page(self):
        self.assertIn('data-power="reboot"', adminpage.render(self.owner, users.list_users(self.owner)))
        self.assertNotIn("data-power", adminpage.render(self.admin, users.list_users(self.admin)))
        self.assertIn("data-backup-open", adminpage.render(self.owner, users.list_users(self.owner)))
        self.assertNotIn("data-backup", adminpage.render(self.admin, users.list_users(self.admin)))

    def test_texts_exist_in_both_languages(self):
        self.assertEqual(i18n.t("de", "system_title"), i18n.t("en", "system_title"))   # the same word in both
        for key in ("bk_open_hint", "bk_now", "bk_running", "bk_failed",
                    "sys_reboot", "sys_reboot_hint", "sys_reboot_title", "sys_reboot_do",
                    "sys_reboot_done", "sys_poweroff", "sys_poweroff_hint", "sys_poweroff_title",
                    "sys_poweroff_do", "sys_poweroff_done", "err_power_busy"):
            self.assertNotEqual(i18n.t("de", key), i18n.t("en", key), key)


if __name__ == "__main__":
    unittest.main()
