"""Parts shared by several pages: the login page and the logged-in frame with its settings drawer."""
from . import i18n
from .icons import icon
from .layout import esc, fill, page
from .users import User

# Linked AI accounts (name, connected). The real state comes with the runner (phase 2).
SERVICES = (("Claude", False), ("ChatGPT", False))

LOGIN = """<section class="glass">
  <h1>%t.login%</h1>
  <p class="subtitle">%t.login_welcome%</p>
  %ERROR%
  <form method="post" action="/login" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <label>%t.email%<input type="email" name="email" required autofocus autocomplete="username" placeholder="%t.email_placeholder%"></label>
    <label>%t.password%<input type="password" name="password" required autocomplete="current-password" placeholder="••••••••"></label>
    <button class="primary" type="submit">%t.login%</button>
  </form>
  <!-- Placeholder: password reset by e-mail is a later module. -->
  <button class="link" type="button" disabled title="%t.coming_soon%">%t.forgot_password%</button>
</section>"""


def login_page(failed: bool = False, locked_minutes: int = 0) -> str:
    """The login page (German until the user is known, see DESIGN.md)."""
    text = i18n.t("de", "login_locked", minutes=locked_minutes) if locked_minutes else i18n.t("de", "login_failed")
    error = f'<p class="error" role="alert">{esc(text)}</p>' if failed or locked_minutes else ""
    return page(i18n.t("de", "login"), fill(LOGIN, "de", ERROR=error), "de")


# Closed: only the gear and the arrow show at the top right. Open: the box slides out of
# the corner and the handle rides along on its left edge (see app.css).
SETTINGS = """<div class="drawer" id="settings">
  <button class="drawer-handle" id="settings-toggle" type="button"
          aria-expanded="false" aria-controls="settings-panel" aria-label="%t.settings_toggle%">%GEAR%%ARROW%</button>
  <div class="drawer-box glass" id="settings-panel">
    <form method="post" action="/settings" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
      <label class="setting">
        <span class="setting-label">%t.display_name%</span>
        <input name="display_name" maxlength="40" value="%NAME_VALUE%" placeholder="%NAME_SHOWN%" autocomplete="nickname">
      </label>
      <label class="setting has-select">
        <span class="setting-label">%t.language%</span>
        <select name="language">
          <option value="de" %DE%>Deutsch</option>
          <option value="en" %EN%>English</option>
        </select>%CHEVRON%
      </label>
      %SERVICES%
      <button class="primary save" type="submit">%t.save%</button>
    </form>
    <form method="post" action="/logout"><button class="link" type="submit">%t.logout%</button></form>
  </div>
</div>"""


def _service_rows(lang: str) -> str:
    rows = []
    for name, connected in SERVICES:
        status = esc(i18n.t(lang, "connected" if connected else "not_connected"))
        action = "" if connected else (
            f'<button class="link inline" type="button" disabled title="{esc(i18n.t(lang, "coming_soon"))}">'
            f'{esc(i18n.t(lang, "connect"))}</button>'
        )
        rows.append(
            f'<div class="setting service{" on" if connected else ""}">'
            f'<span class="setting-label">{name}</span>'
            f'<span class="service-line"><span class="status">{status}</span>{action}</span></div>'
        )
    return "\n      ".join(rows)


def settings_bar(user: User) -> str:
    """Settings drawer for the top right corner of every logged-in page."""
    lang = user.language
    return fill(
        SETTINGS,
        lang,
        GEAR=icon("gear"),
        ARROW=icon("arrow_left", "drawer-arrow"),
        CHEVRON=icon("chevron_down"),
        NAME_VALUE=esc(user.display_name or ""),
        NAME_SHOWN=esc(user.name),
        DE="selected" if lang == "de" else "",
        EN="selected" if lang == "en" else "",
        SERVICES=_service_rows(lang),
    )


def logged_in_page(
    user: User,
    title: str,
    body: str,
    *,
    scripts: tuple[str, ...] = (),
    styles: tuple[str, ...] = (),
    body_class: str = "",
) -> str:
    """A page with the settings drawer in the corner, in the language of the user."""
    return page(
        title, body, user.language,
        top_right=settings_bar(user), scripts=scripts, styles=styles, body_class=body_class,
    )
