import json
import os
import re
import tempfile
import unittest
import urllib.error
from unittest import mock

from app import db, mail, resetpages, resets, users
from app.routes import resets as reset_routes


class FakeResponse:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class ResetsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.user = users.create_user("me@example.com", "Start1234", must_change=True)

    def tearDown(self):
        self.tmp.cleanup()

    # --- tokens
    def test_token_works_once_and_sets_the_password(self):
        user, token = resets.create_token(" ME@example.com ")
        self.assertEqual(user.id, self.user.id)
        self.assertEqual(resets.user_for_token(token).id, self.user.id)
        session = users.create_session(self.user.id)
        self.assertTrue(resets.consume(token, "Neu!Pass12"))
        self.assertIsNone(users.get_user(session), "old sessions end")
        login = users.check_login("me@example.com", "Neu!Pass12")
        self.assertIsNotNone(login)
        self.assertFalse(login.must_change, "start password flag is gone")
        self.assertFalse(resets.consume(token, "Noch!Mal34"), "second use fails")
        self.assertIsNone(resets.user_for_token(token))

    def test_only_the_hash_is_stored(self):
        _, token = resets.create_token("me@example.com")
        with db.connect() as conn:
            stored = [row["token_hash"] for row in conn.execute("SELECT token_hash FROM password_resets")]
        self.assertEqual(len(stored), 1)
        self.assertNotIn(token, stored[0])

    def test_unknown_address_gives_none(self):
        self.assertIsNone(resets.create_token("nobody@example.com"))

    def test_second_request_within_cooldown_gives_none(self):
        self.assertIsNotNone(resets.create_token("me@example.com"))
        self.assertIsNone(resets.create_token("me@example.com"))

    def test_new_request_replaces_the_old_token(self):
        _, old = resets.create_token("me@example.com")
        with db.connect() as conn:
            conn.execute("UPDATE password_resets SET created_at = created_at - ?", (resets.COOLDOWN_SECONDS + 1,))
        _, new = resets.create_token("me@example.com")
        self.assertIsNone(resets.user_for_token(old))
        self.assertIsNotNone(resets.user_for_token(new))

    def test_expired_token_is_refused(self):
        _, token = resets.create_token("me@example.com")
        with db.connect() as conn:
            conn.execute("UPDATE password_resets SET expires_at = 1")
        self.assertIsNone(resets.user_for_token(token))
        self.assertFalse(resets.consume(token, "Neu!Pass12"))

    def test_weak_password_keeps_the_token(self):
        _, token = resets.create_token("me@example.com")
        with self.assertRaises(users.UserError) as problem:
            resets.consume(token, "weak")
        self.assertEqual(problem.exception.code, "short")
        with self.assertRaises(users.UserError) as problem:
            resets.consume(token, "alllowercase12")
        self.assertEqual(problem.exception.code, "policy")
        self.assertIsNotNone(resets.user_for_token(token))

    def test_unknown_token(self):
        self.assertIsNone(resets.user_for_token("nope"))
        self.assertFalse(resets.consume("nope", "Neu!Pass12"))

    def test_deleting_the_user_removes_the_tokens(self):
        resets.create_token("me@example.com")
        owner = users.create_user("owner@example.com", "Own3r!pass", role="owner")
        users.delete_user(owner, self.user.id)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM password_resets").fetchone()[0], 0)


class MailTest(unittest.TestCase):
    ENV = {"RESEND_API_KEY": "re_secret_key", "MAIL_FROM": "Agent-Hub <noreply@example.com>"}

    def test_not_configured_sends_nothing(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch("urllib.request.urlopen") as opened:
            self.assertFalse(mail.send_mail("a@example.com", "Hi", "Text"))
            opened.assert_not_called()

    def test_request_to_resend(self):
        with mock.patch.dict(os.environ, self.ENV), mock.patch("urllib.request.urlopen", return_value=FakeResponse()) as opened:
            self.assertTrue(mail.send_mail("a@example.com", "Hi", "Text"))
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.resend.com/emails")
        self.assertEqual(request.get_header("Authorization"), "Bearer re_secret_key")
        self.assertEqual(request.get_header("User-agent"), "agent-hub/1.0")
        self.assertEqual(
            json.loads(request.data),
            {"from": "Agent-Hub <noreply@example.com>", "to": ["a@example.com"], "subject": "Hi", "text": "Text"},
        )

    def test_failure_returns_false_and_never_logs_the_key(self):
        error = urllib.error.HTTPError(mail.API_URL, 403, "Forbidden", {}, None)
        error.read = lambda n=-1: b"domain not verified"
        with mock.patch.dict(os.environ, self.ENV), mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertLogs("agent-hub.mail", "WARNING") as logged:
                self.assertFalse(mail.send_mail("a@example.com", "Hi", "Text"))
        self.assertNotIn("re_secret_key", "\n".join(logged.output))
        with mock.patch.dict(os.environ, self.ENV), mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
            with self.assertLogs("agent-hub.mail", "WARNING"):
                self.assertFalse(mail.send_mail("a@example.com", "Hi", "Text"))

    def test_base_url(self):
        with mock.patch.dict(os.environ, {"HUB_BASE_URL": " https://hub.example.com/ "}):
            self.assertEqual(mail.base_url(), "https://hub.example.com")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(mail.base_url(), "")


class ResetMailTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.user = users.create_user("me@example.com", "Start1234")
        users.set_profile(self.user.id, "Jan", "en")
        self.user = users.get_by_id(self.user.id)

    def tearDown(self):
        self.tmp.cleanup()

    def test_mail_has_the_link_and_the_users_language(self):
        env = {"HUB_BASE_URL": "https://hub.example.com/"}
        with mock.patch.dict(os.environ, env), mock.patch.object(mail, "send_mail", return_value=True) as sent:
            self.assertTrue(reset_routes.send_reset_mail(self.user, "TOKEN123"))
        to, subject, body = sent.call_args.args
        self.assertEqual(to, "me@example.com")
        self.assertIn("reset your password", subject)
        self.assertIn("Hello Jan", body)
        self.assertIn("https://hub.example.com/reset/TOKEN123", body)
        self.assertIn("60 minutes", body)

    def test_no_base_url_no_mail(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(mail, "send_mail") as sent:
            with self.assertLogs("agent-hub.mail", "WARNING"):
                self.assertFalse(reset_routes.send_reset_mail(self.user, "TOKEN123"))
        sent.assert_not_called()


class ResetPagesTest(unittest.TestCase):
    def test_no_placeholder_is_left_over(self):
        pages = [
            resetpages.forgot_page(), resetpages.forgot_page("msg_email"), resetpages.sent_page(),
            resetpages.invalid_page(),
        ] + [resetpages.reset_page("abc-_123", lang, key) for lang in ("de", "en") for key in ("", "err_pw_mismatch")]
        for page in pages:
            self.assertIsNone(re.search(r"%[A-Za-z_.]+%", page))

    def test_reset_form_posts_to_the_token_url(self):
        self.assertIn('action="/reset/abc-_123"', resetpages.reset_page("abc-_123", "de"))
