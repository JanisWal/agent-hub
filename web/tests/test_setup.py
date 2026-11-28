"""The set-up assistant (setup.py, setuppage.py, routes/setup.py): open only before there is an owner, only in the home
network and only for an hour; the owner's steps write .env through a host job; the start page sends the owner back only
on a hub that was set up with the assistant."""
import json
import os
import re
import urllib.error
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
        # Also from a public address for now (Janis, 28.11.2026; limiting it is noted for later, Merkliste 3v)
        self.assertTrue(setup.open_for(request(ip="93.184.216.34")))
        self.assertFalse(setup.open_for(request(**{"cf-connecting-ip": "93.184.216.34"})))
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
        self.assertIn('value="http://192.168.1.20:8080"', routes.setup_page(request(cookies, host="192.168.1.20:8080"), "access"))
        self.assertNotIn("evil", routes.setup_page(request(cookies, host='x"evil'), "access"))
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
        for kind, values in (("access", ("ftp://hub.example.de", "", "", "")), ("access", ("https://a b", "", "", "")),
                             ("access", ("", "short", "", "")), ("mail", ("", "", "sk-123", "")),
                             ("mail", ("", "", "", "no address")), ("mail", ("", "", "", "a@b.de\nBcc: x")),
                             ("nope", ("", "", "", ""))):
            self.assertEqual(routes.save_settings(kind, *values, owner).status_code, 400, (kind, values))
        self.assertIsNone(hostjobs.claim_next())
        self.assertTrue(routes.save_settings("access", "http://192.168.1.20:8080", "", "", "", owner)["ok"])   # no domain
        self.assertEqual(hostjobs.claim_next()["payload"], {"values": {"HUB_BASE_URL": "http://192.168.1.20:8080"}})
        hostjobs.end_open("settings", "x")
        kept = routes.save_settings("mail", "", "", "", "Agent-Hub <noreply@example.de>", owner)
        self.assertTrue(kept["ok"])
        self.assertEqual(hostjobs.claim_next()["payload"], {"values": {"MAIL_FROM": "Agent-Hub <noreply@example.de>"}})
        admin = users.create_user("admin@example.com", "Adm1n!pass12", role="admin")
        self.assertEqual(routes.save_settings("access", "", "", "", "", admin).status_code, 403)

    def test_the_three_ways_to_reach_the_hub(self):
        self.make_owner()
        owner = users.check_login("owner@example.com", "Own3r!pass12")
        save = lambda way, base, token="": routes.save_settings("access", base, token, "", "", owner, way)   # noqa: E731
        token = "eyJ" + "b" * 80
        self.assertEqual(save("home", "").status_code, 400)                          # the address is needed
        self.assertTrue(save("home", "http://192.168.1.20:8080")["ok"])
        self.assertEqual(hostjobs.claim_next()["payload"]["values"],
                         {"HUB_BASE_URL": "http://192.168.1.20:8080", "TUNNEL_TOKEN": ""})   # a tunnel set before stops
        hostjobs.end_open("settings", "x")
        self.assertEqual(save("tunnel", "http://hub.example.de", token).status_code, 400)   # from outside only https
        self.assertEqual(save("tunnel", "https://hub.example.de").status_code, 400)          # no token saved yet
        self.assertTrue(save("tunnel", "https://hub.example.de", token)["ok"])
        self.assertEqual(hostjobs.claim_next()["payload"]["values"], {"HUB_BASE_URL": "https://hub.example.de",
                                                                       "TUNNEL_TOKEN": token})
        hostjobs.end_open("settings", "x")
        self.assertEqual(save("own", "http://203.0.113.5:8080").status_code, 400)
        self.assertEqual(save("own", "https://hub.example.de").status_code, 400)   # the certificate comes with it (OwnAddressTest)
        html = routes.setup_page(request({deps.COOKIE_NAME: users.create_session(owner.id)}), "access")
        for way in ("home", "tunnel", "own"):
            self.assertIn(f'value="{way}"', html)
        self.assertIn("setup-guide", html)
        self.assertIn(i18n.t("de", "setup_later"), html)                              # a way out of the first set-up
        setup.finish()
        self.assertIn('href="/admin"', routes.setup_page(request({deps.COOKIE_NAME: users.create_session(owner.id)}), "mail"))

    def test_the_test_mail_says_why_it_did_not_go_out(self):
        self.make_owner()
        owner = users.check_login("owner@example.com", "Own3r!pass12")
        with mock.patch.object(routes.mailtext, "send_test_mail", return_value=(False, "no_address")):
            self.assertEqual(routes.probe_mail(owner)["text"], i18n.t("de", "setup_mail_no_address"))
        with mock.patch.object(routes.mailtext, "send_test_mail",
                               return_value=(False, "HTTP 403: The example.de domain is not verified.")):
            self.assertIn("is not verified", routes.probe_mail(owner)["text"])
        with mock.patch.object(routes.mailtext, "send_test_mail", return_value=(True, "")):
            self.assertTrue(routes.probe_mail(owner)["found"])

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
                mock.patch.dict(throttle._found, clear=True):
            self.assertEqual(throttle.client_ip(fake), "192.168.1.50")
            real = request(ip="172.20.0.5", **{"cf-connecting-ip": "203.0.113.1"})
            self.assertEqual(throttle.client_ip(real), "203.0.113.1")
        with mock.patch.object(throttle, "TRUSTED_PROXY", ""):
            self.assertEqual(throttle.client_ip(fake), "203.0.113.1")        # the first hub: as before

    def test_behind_the_gate_the_peer_it_names_counts_and_nobody_can_name_one_himself(self):
        """28.11.2026: every request comes through the gate (gate/nginx.conf), which sets X-Hub-Peer itself."""
        names = {"gate": "172.20.0.2", "tunnel": "172.21.0.3"}
        with mock.patch.object(throttle, "GATE", "gate"), mock.patch.object(throttle, "TRUSTED_PROXY", "tunnel"), \
                mock.patch.object(throttle.socket, "gethostbyname", side_effect=lambda n: names[n]), \
                mock.patch.dict(throttle._found, clear=True):
            home = request(ip="172.20.0.2", **{"x-hub-peer": "192.168.1.50"})
            self.assertEqual(throttle.client_ip(home), "192.168.1.50")
            tunnel = request(ip="172.20.0.2", **{"x-hub-peer": "172.21.0.3", "cf-connecting-ip": "203.0.113.1"})
            self.assertEqual(throttle.client_ip(tunnel), "203.0.113.1")
            faked = request(ip="172.20.0.2", **{"x-hub-peer": "192.168.1.50", "cf-connecting-ip": "203.0.113.1"})
            self.assertEqual(throttle.client_ip(faked), "192.168.1.50")          # not from the tunnel: header ignored
            direct = request(ip="172.20.0.9", **{"x-hub-peer": "1.2.3.4"})
            self.assertEqual(throttle.client_ip(direct), "172.20.0.9")           # not the gate: its header counts not

    def test_the_cookie_is_secure_over_https_only_in_auto_mode(self):
        tunnel = request(ip="172.20.0.5", **{"cf-connecting-ip": "203.0.113.1", "x-forwarded-proto": "https"})
        home = request(ip="192.168.1.50")
        with mock.patch.object(deps, "SECURE_MODE", "auto"), mock.patch.object(deps, "COOKIE_SECURE", False), \
                mock.patch.object(throttle, "TRUSTED_PROXY", ""):
            self.assertTrue(deps.cookie_secure(tunnel))
            self.assertFalse(deps.cookie_secure(home))
        with mock.patch.object(deps, "COOKIE_SECURE", True):
            self.assertTrue(deps.cookie_secure(home))


class ProbeTest(unittest.TestCase):
    """Why the public address does not lead to the hub (28.11.2026: a proxied A record gave Cloudflare's 521 and the
    page said only "not reachable")."""

    def answer(self, outcome):
        def opener(url, timeout):
            if isinstance(outcome, int):
                raise urllib.error.HTTPError(url, outcome, "x", {}, None)
            if outcome == "net":
                raise urllib.error.URLError("no such host")
            return _Answer(outcome)
        return mock.patch("urllib.request.urlopen", opener)

    def test_each_failure_has_its_reason(self):
        cases = {b'{"status":"ok"}': ("", 200), 521: ("origin", 521), 522: ("origin", 522), 530: ("tunnel", 530),
                 404: ("other", 404), b"<html>other site</html>": ("other", 200), "net": ("net", 0)}
        for outcome, expected in cases.items():
            with self.answer(outcome):
                self.assertEqual(setup.probe("https://hub2.example.de"), expected, outcome)
        self.assertEqual(setup.probe("hub2.example.de"), ("net", 0))
        for reason in ("origin", "tunnel", "other", "net"):
            for lang in ("de", "en"):
                self.assertTrue(i18n.t(lang, f"setup_probe_{reason}", address="x", code=521))


class _Answer:
    def __init__(self, body):
        self.status, self.body = 200, body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size=-1):
        return self.body[:size] if size > 0 else self.body


CERT = "-----BEGIN CERTIFICATE-----\n" + "A" * 300 + "\n-----END CERTIFICATE-----"
KEY = "-----BEGIN PRIVATE KEY-----\n" + "B" * 300 + "\n-----END PRIVATE KEY-----"


class OwnAddressTest(unittest.TestCase):
    """The way "own" with the gate's HTTPS door (28.11.2026): Cloudflare's origin certificate, its key and the port."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.owner = users.get_by_id(users.create_user("owner@example.com", "Own3r!pass", role="owner").id)

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, **fields):
        args = dict(kind="access", base_url="https://hub2.example.de", tunnel_token="", resend_key="", mail_from="",
                    user=self.owner, way="own", tls_cert="", tls_key="", tls_port="")
        args.update(fields)
        return routes.save_settings(**args)

    def payload(self):
        job = hostjobs.claim_next()
        hostjobs.end_open("settings", "x")
        return job["payload"]

    def field(self, answer):
        return json.loads(answer.body)["field"]

    def test_the_certificate_goes_to_the_server_with_its_port(self):
        self.assertTrue(self.save(tls_cert=CERT + "\r\n", tls_key=KEY, tls_port="8443")["ok"])
        sent = self.payload()
        self.assertEqual(sent["tls"], {"cert": CERT + "\n", "key": KEY + "\n", "port": 8443})
        self.assertEqual(sent["values"]["TUNNEL_TOKEN"], "")              # a tunnel set before stops
        self.assertTrue(self.save(tls_cert=CERT, tls_key=KEY)["ok"])
        self.assertEqual(self.payload()["tls"]["port"], 443)              # 443 when nothing is said

    def test_what_can_not_be_right_is_refused(self):
        self.assertEqual(self.field(self.save()), "tls_cert")              # the first time it is needed
        self.assertEqual(self.field(self.save(tls_cert=CERT)), "tls_key")
        self.assertEqual(self.field(self.save(tls_cert="hello", tls_key=KEY)), "tls_cert")
        for port in ("0", "70000", "44a", "-1"):
            self.assertEqual(self.field(self.save(tls_cert=CERT, tls_key=KEY, tls_port=port)), "tls_port", port)
        self.assertIsNone(hostjobs.claim_next())

    def test_saved_once_it_is_kept_and_other_ways_switch_it_off(self):
        with mock.patch.dict(os.environ, {"HUB_TLS_PORT": "443"}):
            self.assertTrue(self.save()["ok"])
            self.assertNotIn("tls", self.payload())                       # kept as it is
            self.assertTrue(self.save(tls_port="8443")["ok"])
            self.assertEqual(self.payload()["tls"], {"port": 8443, "keep": True})   # the saved pair moves along
            self.assertTrue(self.save(way="home", base_url="http://192.168.1.20:8080")["ok"])
            self.assertEqual(self.payload()["tls"], "off")
            page = setuppage.access_content("de")
            self.assertIn('name="tls_cert"', page)
            self.assertIn(i18n.t("de", "setup_tls_kept"), page)

    def test_a_wrong_field_says_what_is_wrong(self):
        answer = self.save(tls_cert="hello", tls_key=KEY)
        self.assertEqual(json.loads(answer.body)["message"], i18n.t("de", "setup_bad_tls_cert"))

    def test_the_sender_in_both_forms_and_bare_brackets_go(self):
        """Resend takes "a@b.de" and "Name <a@b.de>"; "<a@b.de>" alone it refused with 422 (28.11.2026)."""
        for given, saved in (("noreply@example.de", "noreply@example.de"),
                             ("Agent-Hub <noreply@example.de>", "Agent-Hub <noreply@example.de>"),
                             ("<noreply@example.de>", "noreply@example.de"), ("  ", "")):
            self.assertEqual(routes._sender(given), saved, given)
        for bad in ("noreply", "a@b", "Hub <a@b.de", "<a@b.de> Hub", "x <y> <a@b.de>", "a b@c.de"):
            self.assertIsNone(routes._sender(bad), bad)
        answer = routes.save_settings(kind="mail", base_url="", tunnel_token="", resend_key="", mail_from="noreply",
                                      user=self.owner)
        self.assertEqual(json.loads(answer.body)["field"], "mail_from")

    def test_the_guides_sit_beside_the_step_with_the_hubs_arrow(self):
        html = setuppage.owner_page(self.owner, "access")
        self.assertIn('class="setup-aside"', html)
        self.assertIn('class="setup-guide-head"', html)
        self.assertNotIn("<details", html)                                  # no browser triangle
        self.assertIn('class="setup-radio"', html)

    def test_only_the_gate_says_https(self):
        gate = types.SimpleNamespace(client=types.SimpleNamespace(host="10.0.0.5"), headers={"x-hub-https": "1"})
        other = types.SimpleNamespace(client=types.SimpleNamespace(host="203.0.113.9"), headers={"x-hub-https": "1"})
        with mock.patch.object(throttle, "GATE", "gate"), mock.patch.object(throttle, "_address_of", return_value="10.0.0.5"), \
                mock.patch.object(deps, "SECURE_MODE", "auto"), mock.patch.object(deps, "COOKIE_SECURE", False):
            self.assertTrue(throttle.gate_https(gate))
            self.assertTrue(deps.is_https(gate))
            self.assertFalse(throttle.gate_https(other))                  # a visitor can not claim it
            self.assertFalse(deps.is_https(other))
            gate.headers = {}
            self.assertFalse(deps.is_https(gate))


if __name__ == "__main__":
    unittest.main()
