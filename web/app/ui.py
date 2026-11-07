"""Parts shared by several pages: the login page and the logged-in frame with its settings drawer."""
from . import i18n
from .icons import icon
from .layout import esc, fill, page
from .users import User

from . import claude_link

# Other AI accounts (name): placeholders until they exist. Claude has its own row with a real state.
PLACEHOLDER_SERVICES = ("ChatGPT",)

LOGIN = """<section class="glass">
  <h1>%t.login%</h1>
  <p class="subtitle">%t.login_welcome%</p>
  %ERROR%
  <form method="post" action="/login" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <label>%t.email%<input type="email" name="email" required autofocus autocomplete="username" placeholder="%t.email_placeholder%"></label>
    <label>%t.password%<input type="password" name="password" required autocomplete="current-password" placeholder="••••••••"></label>
    <button class="primary" type="submit">%t.login%</button>
  </form>
  <a class="link" href="/forgot">%t.forgot_password%</a>
</section>"""


def login_page(failed: bool = False, locked_minutes: int = 0) -> str:
    """The login page (German until the user is known, see DESIGN.md)."""
    text = i18n.t("de", "login_locked", minutes=locked_minutes) if locked_minutes else i18n.t("de", "login_failed")
    error = f'<p class="error" role="alert">{esc(text)}</p>' if failed or locked_minutes else ""
    return page(i18n.t("de", "login"), fill(LOGIN, "de", ERROR=error), "de")


# Closed: only the gear and the arrow show at the top right. Open: the box slides out of
# the corner and the handle rides along on its left edge (see app.css).
SETTINGS = """<div class="drawer" id="settings" data-theme-saved="%THEME%">
  %DRAWER_EXTRAS%
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
    %ACCOUNT_LINKS%
    <form method="post" action="/logout"><button class="link" type="submit">%t.logout%</button></form>
  </div>
</div>
%CLAUDE_DIALOG%"""

# The dialog of the Claude connection. claude.js shows one step at a time; all texts are here,
# translated by the server, none in the script.
CLAUDE_DIALOG = """<dialog class="dialog" id="claude-dialog">
  <h2>%t.claude_title%</h2>
  <div data-step="wait">
    <p class="muted">%t.claude_wait%</p>
    <div class="actions"><button type="button" data-cancel>%t.cancel%</button></div>
  </div>
  <form data-step="link" hidden novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <p class="muted">%t.claude_steps%</p>
    <a class="primary" id="claude-link" href="#" target="_blank" rel="noopener noreferrer">%t.claude_open%</a>
    <label>%t.claude_code%<input name="code" required maxlength="2000" autocomplete="off" spellcheck="false"></label>
    <div class="actions">
      <button type="button" data-cancel>%t.cancel%</button>
      <button class="primary" type="submit">%t.claude_confirm%</button>
    </div>
  </form>
  <div data-step="check" hidden><p class="muted">%t.claude_checking%</p></div>
  <div data-step="done" hidden>
    <p class="muted">%t.claude_done%</p>
    <div class="actions"><button class="primary" type="button" data-finish>%t.close%</button></div>
  </div>
  <div data-step="failed" hidden>
    <p class="error" role="alert">%t.claude_failed%</p>
    <div class="actions"><button type="button" data-finish>%t.close%</button></div>
  </div>
  <div data-step="stuck" hidden>
    <p class="error" role="alert">%t.claude_stuck%</p>
    <div class="actions"><button type="button" data-cancel>%t.close%</button></div>
  </div>
  <div data-step="disconnect" hidden>
    <p class="muted">%t.claude_disconnect_text%</p>
    <div class="actions">
      <button type="button" data-finish-keep autofocus>%t.cancel%</button>
      <button class="danger-btn" type="button" data-disconnect>%t.claude_disconnect%</button>
    </div>
  </div>
</dialog>
<dialog class="dialog danger" id="chat-clear-dialog">
  <h2>%t.chat_clear_title%</h2>
  <p class="muted">%t.chat_clear_text%</p>
  <div class="actions">
    <button type="button" data-close autofocus>%t.cancel%</button>
    <button class="danger-btn" type="button" id="chat-clear-yes">%t.chat_clear_yes%</button>
  </div>
</dialog>"""

# Claude row: status text, the style class that colours the dot, and the text of the link.
CLAUDE_STATES = {
    "connected": ("ok", "connected", "claude_disconnect"),
    "connecting": ("pending", "claude_pending", "claude_continue"),
    "expired": ("expired", "claude_expired", "claude_renew"),
}


def _claude_row(lang: str, state: str) -> str:
    style, text_key, action_key = CLAUDE_STATES.get(state, ("", "not_connected", "connect"))
    return (
        f'<div class="setting service {style}">'
        f'<span class="setting-label">Claude</span>'
        f'<span class="service-line"><span class="status">{esc(i18n.t(lang, text_key))}</span>'
        f'<button class="link inline" type="button" id="claude-open" data-status="{esc(state)}">'
        f'{esc(i18n.t(lang, action_key))}</button></span></div>'
    )


def _service_rows(lang: str, claude_state: str) -> str:
    # The chat history button sits directly under the Claude box (type="button": it never submits the form).
    clear = (f'<button class="clear-btn" type="button" id="chat-clear-open">'
             f'{esc(i18n.t(lang, "chat_clear"))}</button>')
    rows = [_claude_row(lang, claude_state), clear]
    for name in PLACEHOLDER_SERVICES:
        rows.append(
            '<div class="setting service">'
            f'<span class="setting-label">{name}</span>'
            f'<span class="service-line"><span class="status">{esc(i18n.t(lang, "not_connected"))}</span>'
            f'<button class="link inline" type="button" disabled title="{esc(i18n.t(lang, "coming_soon"))}">'
            f'{esc(i18n.t(lang, "connect"))}</button></span></div>'
        )
    return "\n      ".join(rows)


def _account_links(user: User) -> str:
    """Links under the save button: user management (owner and admins) and the own password."""
    lang = user.language
    links = [("/password", "change_password")]
    if user.is_admin:
        links.insert(0, ("/users", "manage_users"))
    return "\n    ".join(f'<a class="link" href="{href}">{esc(i18n.t(lang, key))}</a>' for href, key in links)


def settings_bar(user: User, extras: str = "") -> str:
    """Settings drawer for the top right corner of every logged-in page. `extras` (HTML) are small
    buttons to the left of the gear that ride along when the drawer slides out (project page)."""
    lang = user.language
    return fill(
        SETTINGS,
        lang,
        DRAWER_EXTRAS=extras,
        THEME=esc(user.theme),
        GEAR=icon("gear"),
        ARROW=icon("arrow_left", "drawer-arrow"),
        CHEVRON=icon("chevron_down"),
        NAME_VALUE=esc(user.display_name or ""),
        NAME_SHOWN=esc(user.name),
        DE="selected" if lang == "de" else "",
        EN="selected" if lang == "en" else "",
        SERVICES=_service_rows(lang, claude_link.status(user.id)),
        ACCOUNT_LINKS=_account_links(user),
        CLAUDE_DIALOG=fill(CLAUDE_DIALOG, lang),
    )


def logged_in_page(
    user: User,
    title: str,
    body: str,
    *,
    scripts: tuple[str, ...] = (),
    styles: tuple[str, ...] = (),
    body_class: str = "",
    top_center: str = "",
    top_left: str = "",
    drawer_extras: str = "",
) -> str:
    """A page with the settings drawer in the corner, in the language of the user."""
    return page(
        title, body, user.language,
        top_right=settings_bar(user, drawer_extras), top_center=top_center, top_left=top_left,
        scripts=("claude.js", *scripts), styles=styles, body_class=body_class,
    )
