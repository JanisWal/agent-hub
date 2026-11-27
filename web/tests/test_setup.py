"""The set-up assistant (setup.py, setuppage.py, routes/setup.py): open only before there is an owner, only in the home
network and only for an hour; the owner's steps write .env through a host job; the start page sends the owner back only
on a hub that was set up with the assistant."""
import os
import re
import tempfile
import time
import types
import unittest
from unittest import mock

from fastapi import HTTPException

from app import db, deps, hostjobs, i18n, setup, setuppage, throttle, users
from app.routes import auth, projects, setup as routes


def request(cookies=None, ip="192.168.1.20", **headers):
    headers.setdefault("accept-language", "de")
    return types.SimpleNamespace(headers=headers, client=types.SimpleNamespace(host=ip), cookies=cookies or {})


class SetupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "hub.db")
        patcher = mock.patch.object(setup, "STARTED", time.time())
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def make_owner(self, password="Own3r!pass12"):
        return routes.make_owner(request(), "owner@example.com", password, password, "de")

    # --- before there is an owner
    def test_open_only_without_owner_not_through_the_tunnel_and_for_an_hour(self):
        self.assertTrue(setup.open_for(request()))
        self.assertFalse(setup.open_for(request(**{"cf-connecting-ip": "203.0.113.9"})))
        self.assertFalse(setup.open_for(request(), now=setup.STARTED + setup.WINDOW_SECONDS + 1))
        users.create_user("someone@example.com", "Own3r!pass12", role="owner")
        self.assertFalse(setup.open_for(request()))

    def test_the_first_page_checks_the_server_and_offers_both_ways(self):
        html = routes.setup_page(request())
        self.assertIn("setup-checks", html)
        self.assertIn('data-go="/setup?step=account"', html)
        self.assertIn('data-go="/setup?step=restore"', html)
        self.assertNotIn("%t.", html)
        self.assertIn("data-restore", routes.setup_page(request(), "restore"))
        self.assertIn('action="/setup/owner"', routes.setup_page(request(), "account"))
        with self.assertRaises(HTTPException) as refused:
            routes.setup_page(request(**{"cf-connecting-ip": "203.0.113.9"}))
        self.assertEqual(refused.exception.status_code, 404)
        with mock.patch.object(setup, "STARTED", time.time() - setup.WINDOW_SECONDS - 5):
            closed = routes.setup_page(request())
        self.assertEqual(closed.status_code, 403)
        self.assertIn(i18n.t("de", "setup_closed_title"), closed.body.decode())

    def test_the_login_page_leads_to_the_set_up_while_there_is_no_owner(self):
        self.assertEqual(auth.login_form(request()).headers["location"], "/setup")
        self.assertEqual(auth.login_form(request(**{"cf-connecting-ip": "203.0.113.9"}))[:15], "<!doctype html>")

    def test_making_the_owner_logs_him_in_and_closes_the_window(self):
        answer = self.make_owner()
        self.assertEqual((answer.status_code, answer.headers["location"]), (303, "/setup?step=access"))
        self.assertIn("session=", answer.headers["set-cookie"])
        owner = users.check_login("owner@example.com", "Own3r!pass12")
        self.assertEqual(owner.role, "owner")
        self.assertTrue(routes.started())
        self.assertFalse(setup.open_for(request()))
        with self.assertRaises(HTTPException):
            self.make_owner()                                                  # a second owner never

    def test_a_bad_account_is_refused_with_a_message(self):
        differ = routes.make_owner(request(), "a@example.com", "Own3r!pass12", "Own3r!pass13", "de")
        self.assertEqual(differ.status_code, 400)
        self.assertIn(i18n.t("de", "setup_password_differ"), differ.body.decode())
        weak = routes.make_owner(request(), "a@example.com", "short", "short", "en")
        self.assertIn(i18n.t("en", "err_pw_rules"), weak.body.decode())
        self.assertFalse(users.owner_exists())

    # --- the owner's steps
    def test_the_owners_steps_need_his_login(self):
        self.make_owner()
        self.assertEqual(routes.setup_page(request()).headers["location"], "/login")
        owner = users.check_login("owner@example.com", "Own3r!pass12")
        cookies = {deps.COOKIE_NAME: users.create_session(owner.id)}
        for step in setup.OWNER_STEPS:
            html = routes.setup_page(request(cookies), step)
            self.assertIn(f'data-step="{step}"', html, step)
            self.assertNotIn("%t.", html)
            self.assertIsNone(re.search(r"%[A-Z_]+%", html), step)
        self.assertIn("data-backup-key", routes.setup_page(request(cookies), "backup"))
        admin = users.create_user("admin@example.com", "Adm1n!pass12", role="admin")
        with self.assertRaises(HTTPException):
            routes.setup_page(request({deps.COOKIE_NAME: users.create_session(admin.id)}), "access")

    def test_settings_go_into_a_host_job_and_odd_values_are_refused(self):
        self.make_owner()
        owner = users.check_login("owner@example.com", "Own3r!pass12")
        token = "eyJ" + "a" * 80
        answer = routes.save_settings("access", "https://hub.example.de/", token, "", "", owner)
        self.assertTrue(answer["ok"])
        job = hostjobs.claim_next()
        self.assertEqual(job["payload"], {"values": {"HUB_BASE_URL": "https://hub.example.de", "TUNNEL_TOKEN": token}})
        hostjobs.end_open("settings", "x")
        for kind, values in (("access", ("http://hub.example.de", "", "", "")), ("access", ("https://a b", "", "", "")),
                             ("access", ("", "short", "", "")), ("mail", ("", "", "sk-123", "")),
                             ("mail", ("", "", "", "no address")), ("mail", ("", "", "", "a@b.de\nBcc: x")),
                             ("nope", ("", "", "", ""))):
            self.assertEqual(routes.save_settings(kind, *values, owner).status_code, 400, (kind, values))
        self.assertIsNone(hostjobs.claim_next())
        kept = routes.save_settings("mail", "", "", "", "Agent-Hub <noreply@example.de>", owner)
        self.assertTrue(kept["ok"])
        self.assertEqual(hostjobs.claim_next()["payload"], {"values": {"MAIL_FROM": "Agent-Hub <noreply@example.de>"}})
        admin = users.create_user("admin@example.com", "Adm1n!pass12", role="admin")
        self.assertEqual(routes.save_settings("access", "", "", "", "", admin).status_code, 403)

    def test_the_start_page_sends_the_owner_back_until_the_set_up_is_finished(self):
        self.make_owner()
        owner = users.check_login("owner@example.com", "Own3r!pass12")
        self.assertEqual(projects.index("1", owner).headers["location"], "/setup")
        self.assertEqual(routes.finish(owner), {"ok": True})
        self.assertIn("<!doctype html>", projects.index("1", owner))

    def test_a_hub_from_before_the_assistant_is_never_sent_there(self):
        owner = users.create_user("owner@example.com", "Own3r!pass12", role="owner")
        self.assertFalse(routes.started())
        self.assertIn("<!doctype html>", projects.index("1", owner))

    def test_the_kind_of_disk(self):
        card = "29 1 179:2 / /data rw,relatime - ext4 /dev/mmcblk0p2 rw\n"
        ssd = "29 1 8:2 / /data rw,relatime - ext4 /dev/sda2 rw\n"
        self.assertEqual(setup.storage(card), "card")
        self.assertEqual(setup.storage(ssd), "disk")
        self.assertEqual(setup.storage("29 1 0:5 / /other rw - tmpfs tmpfs rw\n"), "")

    def test_texts_in_both_languages(self):
        for key in i18n.STRINGS["de"]:
            if key.startswith(("setup_", "bk_", "rs_")):
                self.assertIn(key, i18n.STRINGS["en"], key)


class ProxyTest(unittest.TestCase):
    """Where the hub's port is open in the home network, a made-up CF-Connecting-IP must not dodge the lock."""

    def test_the_forwarded_address_counts_only_from_the_tunnel(self):
        fake = request(ip="192.168.1.50", **{"cf-connecting-ip": "203.0.113.1"})
        with mock.patch.object(throttle, "TRUSTED_PROXY", "tunnel"), \
                mock.patch.object(throttle.socket, "gethostbyname", return_value="172.20.0.5"), \
                mock.patch.dict(throttle._proxy_ip, {"ip": None, "at": 0.0}):
            self.assertEqual(throttle.client_ip(fake), "192.168.1.50")
            real = request(ip="172.20.0.5", **{"cf-connecting-ip": "203.0.113.1"})
            self.assertEqual(throttle.client_ip(real), "203.0.113.1")
        with mock.patch.object(throttle, "TRUSTED_PROXY", ""):
            self.assertEqual(throttle.client_ip(fake), "203.0.113.1")        # the first hub: as before

    def test_the_cookie_is_secure_over_https_only_in_auto_mode(self):
        tunnel = request(ip="172.20.0.5", **{"cf-connecting-ip": "203.0.113.1", "x-forwarded-proto": "https"})
        home = request(ip="192.168.1.50")
        with mock.patch.object(deps, "SECURE_MODE", "auto"), mock.patch.object(deps, "COOKIE_SECURE", False), \
                mock.patch.object(throttle, "TRUSTED_PROXY", ""):
            self.assertTrue(deps.cookie_secure(tunnel))
            self.assertFalse(deps.cookie_secure(home))
        with mock.patch.object(deps, "COOKIE_SECURE", True):
            self.assertTrue(deps.cookie_secure(home))


if __name__ == "__main__":
    unittest.main()
