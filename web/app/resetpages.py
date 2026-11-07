"""HTML of the pages around a forgotten password (no login yet, so no settings drawer)."""
from . import i18n
from .layout import esc, fill, page

FORGOT = """<section class="glass">
  <h1>%t.forgot_title%</h1>
  <p class="subtitle">%t.forgot_sub%</p>
  %ERROR%
  <form method="post" action="/forgot" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <label>%t.email%<input type="email" name="email" required autofocus autocomplete="username" placeholder="%t.email_placeholder%"></label>
    <button class="primary" type="submit">%t.forgot_send%</button>
  </form>
  <a class="link" href="/login">%t.back_to_login%</a>
</section>"""

SENT = """<section class="glass">
  <h1>%t.forgot_sent_title%</h1>
  <p class="subtitle">%t.forgot_sent%</p>
  <a class="link" href="/login">%t.back_to_login%</a>
</section>"""

RESET = """<section class="glass">
  <h1>%t.reset_title%</h1>
  <p class="subtitle">%t.reset_sub%</p>
  %ERROR%
  <form method="post" action="/reset/%TOKEN%" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <label>%t.pw_new%<input type="password" name="new" required autofocus autocomplete="new-password"></label>
    <label>%t.pw_repeat%<input type="password" name="repeat" required autocomplete="new-password"></label>
    <p class="muted">%t.err_pw_rules%</p>
    <button class="primary" type="submit">%t.save%</button>
  </form>
  <a class="link" href="/login">%t.cancel%</a>
</section>"""

INVALID = """<section class="glass">
  <h1>%t.reset_invalid_title%</h1>
  <p class="subtitle">%t.reset_invalid%</p>
  <a class="link" href="/forgot">%t.forgot_again%</a>
</section>"""


def _error(text: str) -> str:
    return f'<p class="error" role="alert">{esc(text)}</p>' if text else ""


def forgot_page(error_key: str = "", **values) -> str:
    """Ask for the e-mail address (German, the user is not known yet, like the login page).
    `values` fill the placeholders of the error text (e.g. minutes)."""
    error = _error(i18n.t("de", error_key, **values)) if error_key else ""
    return page(i18n.t("de", "forgot_title"), fill(FORGOT, "de", ERROR=error), "de")


def sent_page() -> str:
    """Same answer for every address, whether it has an account or not."""
    return page(i18n.t("de", "forgot_sent_title"), fill(SENT, "de"), "de")


def reset_page(token: str, lang: str, error_key: str = "") -> str:
    """Choose a new password. `token` is URL-safe (letters, digits, - and _), so it needs no escaping,
    but it is escaped anyway."""
    error = _error(i18n.t(lang, error_key)) if error_key else ""
    return page(i18n.t(lang, "reset_title"), fill(RESET, lang, ERROR=error, TOKEN=esc(token)), lang)


def invalid_page() -> str:
    """The link is unknown, expired or already used."""
    return page(i18n.t("de", "reset_invalid_title"), fill(INVALID, "de"), "de")
