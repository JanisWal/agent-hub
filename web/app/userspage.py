"""HTML of the user management block (owner and admins; it is part of the administration page, adminpage.py)
and of the password page."""
from . import i18n, ui
from .icons import icon
from .layout import esc, fill
from .users import User, can_manage

ROLE_LABEL = {"owner": "role_owner", "superadmin": "role_superadmin", "admin": "role_admin", "user": "role_user"}

USERS = """<section class="users-wrap" data-network="%t.err_network%" data-label-owner="%t.role_owner%" data-label-superadmin="%t.role_superadmin%" data-label-admin="%t.role_admin%" data-label-user="%t.role_user%">
  <header class="users-head">
    <h2>%t.users_title%</h2>
    <button class="primary" id="add-user" type="button">%t.add_user%</button>
  </header>
  <div class="users-list glass">
    %ROWS%
  </div>
</section>
<dialog class="dialog" id="add-dialog">
  <form novalidate data-url="/users/add" data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <h2>%t.add_user%</h2>
    <label>%t.email%<input type="email" name="email" required autocomplete="off"></label>
    <p class="muted">%t.invite_hint%</p>
    <p class="error" role="alert" data-error hidden></p>
    <div class="actions">
      <button type="button" data-close>%t.cancel%</button>
      <button class="primary" type="submit">%t.invite_send%</button>
    </div>
  </form>
</dialog>
<dialog class="dialog" id="reset-dialog">
  <form novalidate data-url="/users/{id}/reset" data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <h2>%t.reset_password%</h2>
    <p class="muted" data-email></p>
    <label>%t.new_start_password%<input type="text" name="password" required autocomplete="off" spellcheck="false"></label>
    <p class="muted">%t.start_password_hint%</p>
    <label>%t.your_password%<input type="password" name="confirm" required autocomplete="current-password"></label>
    <p class="error" role="alert" data-error hidden></p>
    <div class="actions">
      <button type="button" data-close>%t.cancel%</button>
      <button class="primary" type="submit">%t.save%</button>
    </div>
  </form>
</dialog>
<dialog class="dialog" id="owner-dialog">
  <form novalidate data-url="/users/{id}/owner" data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <h2>%t.owner_transfer_title%</h2>
    <p class="muted" data-email></p>
    <p>%t.owner_transfer_warning%</p>
    <label>%t.your_password%<input type="password" name="confirm" required autocomplete="current-password"></label>
    <p class="error" role="alert" data-error hidden></p>
    <div class="actions">
      <button type="button" data-close autofocus>%t.cancel%</button>
      <button class="primary" type="submit">%t.owner_transfer_do%</button>
    </div>
  </form>
</dialog>
<dialog class="dialog danger" id="delete-user-dialog">
  <form novalidate data-url="/users/{id}/delete" data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <h2>%t.confirm_delete_user%</h2>
    <p class="muted" data-email></p>
    <label>%t.your_password%<input type="password" name="confirm" required autocomplete="current-password"></label>
    <p class="error" role="alert" data-error hidden></p>
    <div class="actions">
      <button type="button" data-close autofocus>%t.cancel%</button>
      <button class="danger-btn" type="submit">%t.delete_now%</button>
    </div>
  </form>
</dialog>"""

PASSWORD = """<section class="glass">
  <h1>%t.pw_change_title%</h1>
  <p class="subtitle">%SUBTITLE%</p>
  %ERROR%
  <form method="post" action="/password" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    %OLD_FIELD%
    <label>%t.pw_new%<input type="password" name="new" required %NEW_FOCUS% autocomplete="new-password"></label>
    <label>%t.pw_repeat%<input type="password" name="repeat" required autocomplete="new-password"></label>
    <p class="muted">%t.err_pw_rules%</p>
    <button class="primary" type="submit">%t.save%</button>
  </form>
  %CANCEL%
</section>"""

# The current password is asked for only when somebody changes a password he already chose.
OLD_FIELD = '<label>%t.pw_old%<input type="password" name="old" required autofocus autocomplete="current-password"></label>'
# Somebody with a start password cannot go "back" (every page sends him here again): cancel logs him out.
CANCEL_LINK = '<a class="link" href="/">%t.cancel%</a>'
CANCEL_LOGOUT = '<form method="post" action="/logout"><button class="link" type="submit">%t.cancel%</button></form>'


def _switch(attr: str, label: str, text: str, on: bool, lang: str, off: bool = False) -> str:
    """A round switch. `off` keeps its place in the column but hides it (static/users.js shows it when it fits)."""
    return (f'<button class="chip{" is-off" if off else ""}" type="button" role="switch" {attr} aria-checked="{str(on).lower()}" '
            f'aria-label="{esc(i18n.t(lang, label))}" data-tip="{esc(i18n.t(lang, label))}"'
            f'{" tabindex=-1 aria-hidden=true" if off else ""}>{esc(i18n.t(lang, text))}</button>')


def _row(actor: User, account: User, lang: str) -> str:
    """One account. Every action has a fixed place, so the columns line up from row to row (Janis, 16.11.2026):
    Superadmin (owner only), Admin, then crown or invitation link (never both: the crown needs a chosen password,
    the link a start password), key, trash. A place that does not apply stays empty."""
    you = f' <span class="you">({esc(i18n.t(lang, "you"))})</span>' if account.id == actor.id else ""
    buttons = []
    if actor.is_system_admin:
        free = account.rank < actor.rank
        if actor.role == "owner":   # Superadmin first: only the owner makes or removes superadmins, and only of an admin
            if free:
                buttons.append(_switch("data-superadmin", "superadmin_switch", "role_superadmin",
                                       account.role == "superadmin", lang, off=account.role == "user"))
            else:
                buttons.append('<span class="slot slot-super"></span>')
        if free:   # a superadmin keeps the Admin switch lit (static/users.js)
            buttons.append(_switch("data-admin", "admin_switch", "role_admin", account.role in ("admin", "superadmin"), lang))
        else:
            buttons.append('<span class="slot slot-admin"></span>')
    manage = can_manage(actor, account)
    slots = [
        ("data-owner", "crown", "owner_transfer") if actor.role == "owner" and account.role != "owner" and not account.must_change
        else ("data-invite", "link", "invite_resend") if manage and account.must_change else None,
        ("data-reset", "key", "reset_password") if manage else None,
        ("data-delete", "trash", "delete_user") if manage else None,
    ]
    for slot in slots:
        if slot is None:
            buttons.append('<span class="slot slot-icon"></span>')
            continue
        attr, icon_name, label = slot
        text = esc(i18n.t(lang, label))
        buttons.append(
            f'<button class="icon-button" type="button" {attr} aria-label="{text}" title="{text}">{icon(icon_name)}</button>'
        )
    return (
        f'<div class="user-row" data-id="{account.id}" data-email="{esc(account.email)}" data-role="{account.role}" data-rank="{account.rank}">'
        f'<div class="user-main"><span class="user-email">{esc(account.email)}</span>'
        f'<span class="user-role"><span data-role-label>{esc(i18n.t(lang, ROLE_LABEL[account.role]))}</span>{you}</span>'
        f'<span class="user-note" data-note role="status" hidden></span></div>'
        f'<div class="user-actions">{"".join(buttons)}</div></div>'
    )


def render(actor: User, accounts: list[User]) -> str:
    """The user management block with its dialogs (a part of /admin)."""
    lang = actor.language
    return fill(USERS, lang, ROWS="\n    ".join(_row(actor, account, lang) for account in accounts))


def password_page(user: User, error: str = "") -> str:
    """The page where somebody chooses a new password (forced after a start password)."""
    lang = user.language
    subtitle = i18n.t(lang, "pw_change_first" if user.must_change else "pw_change_sub")
    box = f'<p class="error" role="alert">{esc(error)}</p>' if error else ""
    body = fill(
        PASSWORD, lang, SUBTITLE=esc(subtitle), ERROR=box,
        OLD_FIELD="" if user.must_change else fill(OLD_FIELD, lang),
        NEW_FOCUS="autofocus" if user.must_change else "",
        CANCEL=fill(CANCEL_LOGOUT if user.must_change else CANCEL_LINK, lang),
    )
    return ui.logged_in_page(user, i18n.t(lang, "pw_change_title"), body)
