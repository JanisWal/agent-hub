import json
import os
import re
import tempfile
import unittest
import urllib.error
from unittest import mock

from app import adminpage, db, i18n, mail, mailtext, resetpages, resets, ui, userspage, users
from app.routes import accounts


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
        _, token = resets.create_token("me@example.com")
        owner = users.create_user("owner@example.com", "Own3r!pass", role="owner")
        users.delete_user(owner, self.user.id)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM password_resets").fetchone()[0], 0)
        self.assertIsNone(resets.user_for_token(token))
        self.assertIsNone(resets.create_token("me@example.com", ))            # a deleted account gets no reset link


class MailTest(unittest.TestCase):
    ENV = {"RESEND_API_KEY": "re_secret_key", "MAIL_FROM": "Agent-Hub <noreply@example.com>"}

    def test_not_configured_sends_nothing(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch("urllib.request.urlopen") as opened:
            self.assertFalse(mail.send_mail("a@example.com", "Hi", "Text"))
            opened.assert_not_called()

    def test_request_to_resend(self):
        with mock.patch.dict(os.environ, self.ENV), mock.patch("urllib.request.urlopen", return_value=FakeResponse()) as opened:
            self.assertTrue(mail.send_mail("a@example.com", "Hi", "Text", "<p>Hi</p>"))
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.resend.com/emails")
        self.assertEqual(request.get_header("Authorization"), "Bearer re_secret_key")
        self.assertEqual(request.get_header("User-agent"), "agent-hub/1.0")
        self.assertEqual(
            json.loads(request.data),
            {"from": "Agent-Hub <noreply@example.com>", "to": ["a@example.com"], "subject": "Hi",
             "text": "Text", "html": "<p>Hi</p>"},
        )

    def test_text_only_mail_has_no_html_part(self):
        with mock.patch.dict(os.environ, self.ENV), mock.patch("urllib.request.urlopen", return_value=FakeResponse()) as opened:
            mail.send_mail("a@example.com", "Hi", "Text")
        self.assertNotIn("html", json.loads(opened.call_args.args[0].data))

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


class LinkMailTest(unittest.TestCase):
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
            self.assertTrue(mailtext.send_link_mail("reset", self.user, "TOKEN123", resets.TOKEN_SECONDS))
        to, subject, text, html = sent.call_args.args
        self.assertEqual(to, "me@example.com")
        self.assertIn("choose a new password", subject)
        for part in (text, html):
            self.assertIn("Hello Jan,", part)
            self.assertIn("https://hub.example.com/reset/TOKEN123", part)
            self.assertIn("one hour", part)

    def test_invitation_text_and_duration(self):
        subject, text, html = mailtext.build("invite", self.user, "https://x/reset/T", resets.INVITE_SECONDS)
        self.assertIn("Welcome", subject)
        self.assertIn("7 days", text)
        self.assertIn("7 days", html)

    def test_german_mail(self):
        users.set_profile(self.user.id, "", "de")
        german = users.get_by_id(self.user.id)
        subject, text, _ = mailtext.build("invite", german, "https://x/reset/T", resets.INVITE_SECONDS)
        self.assertEqual(subject, "Willkommen im Agent-Hub")
        self.assertIn("Hallo me,", text)
        self.assertIn("7 Tage", text)

    def test_html_is_filled_and_escaped(self):
        hostile = users.create_user("x@example.com", "Start1234")
        users.set_profile(hostile.id, "<b>Jan</b>", "de")
        hostile = users.get_by_id(hostile.id)
        for kind in mailtext.KINDS:
            html = mailtext.build(kind, hostile, "https://x/reset/T?a=1&b=2", 3600)[2]
            self.assertIsNone(re.search(r"%[A-Z_]+%", html))
            self.assertNotIn("<b>Jan</b>", html)
            self.assertIn("&lt;b&gt;Jan", html)
            self.assertIn("a=1&amp;b=2", html)

    def html(self, kind="reset"):
        return mailtext.build(kind, self.user, "https://x/reset/T", 3600)[2]

    def test_no_pictures_at_all(self):
        """Rule 1: Yahoo's dark mode leaves cells with (background) pictures light, programs block pictures."""
        for kind in mailtext.KINDS:
            html = self.html(kind)
            self.assertNotIn("<img", html)
            self.assertNotIn("url(", html)
            self.assertNotIn(" background=", html)

    def test_light_is_inline_and_dark_comes_only_through_the_schemes(self):
        """Rule 3: the reader's mail program decides between light and dark, not the style saved on the site."""
        html = self.html()
        body = html.split("<body", 1)[1]
        for key in ("page", "card", "text", "muted", "accent", "on_accent"):
            self.assertIn(mailtext.LIGHT[key], body)
        for key in ("page", "card", "text", "muted"):
            self.assertNotIn(mailtext.DARK[key], body)
            self.assertIn(mailtext.DARK[key], mailtext.STYLE_SCHEMES)
        self.assertIn('name="color-scheme" content="light dark"', html)
        self.assertIn("color-scheme:light dark", html)

    @staticmethod
    def contrast(first, second):
        def luminance(colour):
            channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
        high, low = sorted((luminance(first), luminance(second)), reverse=True)
        return (high + 0.05) / (low + 0.05)

    def test_colours_are_readable_in_every_style(self):
        """Rule 4: also the button, which keeps light text on a darker orange where programs recolour by themselves."""
        for colours in (mailtext.LIGHT, mailtext.DARK):
            for text, ground in (("text", "card"), ("muted", "card"), ("muted", "page"), ("on_accent", "accent")):
                self.assertGreaterEqual(self.contrast(colours[text], colours[ground]), 4.5, (colours, text, ground))
        site = mailtext.SITE_BUTTON
        self.assertGreaterEqual(self.contrast(site["on_accent"], site["accent"]), 4.5)
        self.assertGreater(self.contrast(mailtext.LIGHT["on_accent"], "#3A2A20"), 4.5)   # light text, not dark

    def test_no_pure_white_or_black(self):
        html = self.html().upper()
        for colour in ("#FFFFFF", "#FFF;", "#000000", "#000;", ":WHITE", ":BLACK"):
            self.assertNotIn(colour, html)

    def test_css_follows_the_rules_of_the_weakest_programs(self):
        """Rule 7, and rule 5: gradients only behind `[class~=...]`, which Yahoo does not match."""
        html = self.html()
        styles = re.findall(r"<style>(.*?)</style>", html, re.S)
        self.assertGreaterEqual(len(styles), 4)
        for style in styles:
            self.assertNotIn("/*", style)
            self.assertLess(len(style.encode()), 16 * 1024)
            self.assertIsNone(re.search(r"\S!important", style))
            self.assertEqual(style.count("!important"), style.lower().count("!important"))   # lower case only
            self.assertIsNone(re.search(r"rgba?\([^)]*/", style))
            for selector, rules in re.findall(r"([^{}]+)\{([^{}]*)\}", style):
                if "gradient(" in rules:
                    self.assertTrue(selector.strip().startswith('[class~="'), selector)
        self.assertLess(len(html.encode()), 102 * 1024)

    def test_button_text_in_a_span_preview_text_and_outlook_parts(self):
        html = self.html("invite")
        self.assertIn('<span class="bt"', html)
        self.assertIn("mso-padding-alt", html)
        self.assertIn("<!--[if mso]>", html)
        for rule in ("[data-ogsc] .t", "[data-ogsb] .card"):
            self.assertIn(rule, html)
        preview = html.split('mso-hide:all;">', 1)[1].split("&#8199;", 1)[0]
        self.assertEqual(preview, i18n.t("en", "mail_invite_body"))

    def test_unknown_kind(self):
        with self.assertRaises(ValueError):
            mailtext.build("nope", self.user, "x", 3600)

    def test_both_languages_have_every_mail_text(self):
        for lang in ("de", "en"):
            for kind in mailtext.KINDS:
                for part in ("subject", "body", "button", "note"):
                    i18n.t(lang, f"mail_{kind}_{part}", duration="x")

    def test_no_base_url_no_mail(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(mail, "send_mail") as sent:
            with self.assertLogs("agent-hub.mail", "WARNING"):
                self.assertFalse(mailtext.send_link_mail("reset", self.user, "TOKEN123", 3600))
        sent.assert_not_called()


class InviteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.owner = users.create_user("owner@example.com", "Own3r!pass", role="owner")
        self.plain = users.create_user("plain@example.com", "Plain!pass12")

    def tearDown(self):
        self.tmp.cleanup()

    def invite(self, actor, email, sent=True):
        with mock.patch.object(mailtext, "send_link_mail", return_value=sent) as send:
            answer = accounts.add_user(email, actor)
        return answer, send

    def test_invitation_creates_the_account_and_mails_a_link(self):
        answer, send = self.invite(self.owner, "New@Example.com")
        self.assertEqual(answer, {"ok": True})
        kind, account, token, seconds = send.call_args.args
        self.assertEqual((kind, account.email, seconds), ("invite", "new@example.com", resets.INVITE_SECONDS))
        self.assertTrue(account.must_change)
        self.assertEqual(resets.user_for_token(token).id, account.id)
        # the person chooses a password through the link and can log in
        self.assertTrue(resets.consume(token, "Mein!Pass12"))
        self.assertFalse(users.check_login("new@example.com", "Mein!Pass12").must_change)

    def test_invitation_token_lasts_a_week(self):
        _, send = self.invite(self.owner, "new@example.com")
        with db.connect() as conn:
            left = conn.execute("SELECT expires_at - created_at FROM password_resets").fetchone()[0]
        self.assertEqual(left, resets.INVITE_SECONDS)

    def test_failed_mail_removes_the_account_again(self):
        answer, _ = self.invite(self.owner, "new@example.com", sent=False)
        self.assertEqual(answer.status_code, 502)
        self.assertIsNone(users.check_login("new@example.com", "x"))
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM users WHERE email = 'new@example.com'").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM password_resets").fetchone()[0], 0)

    def resend(self, actor, account, sent=True):
        with mock.patch.object(mailtext, "send_link_mail", return_value=sent) as send:
            answer = accounts.resend_invitation(account.id, actor)
        return answer, send

    def test_invitation_can_be_sent_again_until_the_password_is_chosen(self):
        account = users.add_user(self.owner, "new@example.com", "Start1234")
        answer, send = self.resend(self.owner, account)
        self.assertEqual(answer["ok"], True)
        self.assertIn("message", answer)
        kind, target, token, seconds = send.call_args.args
        self.assertEqual((kind, target.id, seconds), ("invite", account.id, resets.INVITE_SECONDS))
        self.assertEqual(resets.user_for_token(token).id, account.id)
        self.assertTrue(resets.consume(token, "Mein!Pass12"))
        answer, send = self.resend(self.owner, users.get_by_id(account.id))   # now he has chosen one
        self.assertEqual(answer.status_code, 400)
        send.assert_not_called()

    def test_new_link_replaces_the_old_one_and_mails_wait_a_minute(self):
        account = users.add_user(self.owner, "new@example.com", "Start1234")
        _, first = self.resend(self.owner, account)
        old = first.call_args.args[2]
        answer, second = self.resend(self.owner, account)
        self.assertEqual(answer.status_code, 429)                              # cooldown, no second mail
        second.assert_not_called()
        with db.connect() as conn:
            conn.execute("UPDATE password_resets SET created_at = created_at - ?", (resets.COOLDOWN_SECONDS + 1,))
        _, third = self.resend(self.owner, account)
        self.assertIsNone(resets.user_for_token(old))
        self.assertIsNotNone(resets.user_for_token(third.call_args.args[2]))

    def test_resend_needs_rights_over_the_account(self):
        account = users.add_user(self.owner, "new@example.com", "Start1234")
        answer, send = self.resend(self.plain, account)                       # a normal user is no admin
        self.assertEqual(answer.status_code, 403)
        admin = users.add_user(self.owner, "admin@example.com", "Admin!pass12")
        users.set_admin(self.owner, admin.id, True)
        other = users.add_user(self.owner, "other@example.com", "Start1234")
        users.set_admin(self.owner, other.id, True)                           # an admin manages no other admin
        answer, send = self.resend(users.get_by_id(admin.id), users.get_by_id(other.id))
        self.assertEqual(answer.status_code, 403)
        send.assert_not_called()
        self.assertEqual(self.resend(self.owner, type("Gone", (), {"id": 9999})())[0].status_code, 400)

    def test_failed_resend_keeps_the_account(self):
        account = users.add_user(self.owner, "new@example.com", "Start1234")
        answer, _ = self.resend(self.owner, account, sent=False)
        self.assertEqual(answer.status_code, 502)
        self.assertEqual(users.get_by_id(account.id).email, "new@example.com")

    def test_resend_button_only_for_accounts_without_their_own_password(self):
        pending = users.add_user(self.owner, "new@example.com", "Start1234")
        html = userspage.render(self.owner, [self.owner, self.plain, users.get_by_id(pending.id)])
        rows = html.split('<div class="user-row"')[1:]
        self.assertEqual([("data-invite" in row) for row in rows], [False, False, True])
        self.assertIn("Einladungslink erneut senden", rows[2])

    def test_failed_mail_for_an_account_that_came_back_keeps_its_data(self):
        from app import projects
        account = users.add_user(self.owner, "old@example.com", "Start1234")
        projects.create_project(account.id, "Mine")
        users.delete_user(self.owner, account.id)
        answer, _ = self.invite(self.owner, "old@example.com", sent=False)
        self.assertEqual(answer.status_code, 502)
        with db.connect() as conn:                                             # deleted again, not removed
            row = conn.execute("SELECT id, deleted_at FROM users WHERE email = 'old@example.com'").fetchone()
            self.assertEqual(row["id"], account.id)
            self.assertIsNotNone(row["deleted_at"])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM projects WHERE user_id = ?", (account.id,)).fetchone()[0], 1)
        answer, _ = self.invite(self.owner, "old@example.com")                 # the next invitation brings it back
        self.assertEqual(users.get_by_id(account.id).email, "old@example.com")

    def test_errors_and_permissions(self):
        self.assertEqual(self.invite(self.owner, "plain@example.com")[0].status_code, 400)  # taken
        self.assertEqual(self.invite(self.owner, "nonsense")[0].status_code, 400)
        answer, send = self.invite(self.plain, "new@example.com")
        self.assertEqual(answer.status_code, 403)
        send.assert_not_called()


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

    def test_reset_page_can_be_cancelled(self):
        self.assertIn('<a class="link" href="/login">Abbrechen</a>', resetpages.reset_page("t", "de"))


class PasswordPageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        owner = users.create_user("owner@example.com", "Own3r!pass", role="owner")
        self.fresh = users.add_user(owner, "new@example.com", "Start1234")   # must change
        self.settled = users.create_user("old@example.com", "Plain!pass12")

    def tearDown(self):
        self.tmp.cleanup()

    def test_start_password_page_has_no_old_password_field_and_cancel_logs_out(self):
        page = userspage.password_page(self.fresh)
        self.assertNotIn('name="old"', page)
        self.assertIn('name="new" required autofocus', page)
        self.assertIn('<form method="post" action="/logout"><button class="link" type="submit">Abbrechen</button></form>', page)

    def test_normal_page_asks_for_the_old_password_and_cancel_goes_home(self):
        page = userspage.password_page(self.settled)
        self.assertIn('name="old"', page)
        self.assertNotIn('name="new" required autofocus', page)
        self.assertIn('<a class="link" href="/">Abbrechen</a>', page)

    def test_start_password_user_chooses_without_the_old_one(self):
        users.change_own_password(self.fresh, "", "Mein!Pass12")
        login = users.check_login("new@example.com", "Mein!Pass12")
        self.assertFalse(login.must_change)

    def test_start_password_user_still_follows_the_rules_and_cannot_keep_it(self):
        for new, code in (("weak", "short"), ("alllowercase12", "policy"), ("Start1234", "policy")):
            with self.assertRaises(users.UserError) as problem:
                users.change_own_password(self.fresh, "", new)
            self.assertEqual(problem.exception.code, code)
        keep = users.add_user(users.get_by_id(1), "keep@example.com", "Keep!pass12")  # a start password that follows the rules
        with self.assertRaises(users.UserError) as problem:
            users.change_own_password(keep, "", "Keep!pass12")
        self.assertEqual(problem.exception.code, "same")

    def test_normal_user_still_needs_the_old_password(self):
        with self.assertRaises(users.UserError) as problem:
            users.change_own_password(self.settled, "", "Mein!Pass12")
        self.assertEqual(problem.exception.code, "wrong_password")

    def test_administration_page_back_button(self):
        owner = users.get_by_id(1)
        self.assertIn(">Zurück</a>", adminpage.render(owner, users.list_users(owner)))
