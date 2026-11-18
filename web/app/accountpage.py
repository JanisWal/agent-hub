"""HTML of the account page (Janis, 18.11.2026): everything about one's own account in one place, for every user.
Name and language, the password, the colour mode for red-green weakness (a placeholder) and deleting the account.
It uses the rows of the system block (system.css), so it looks like the administration page."""
from html import escape as esc

from . import i18n
from .icons import icon
from .layout import fill
from .ui import info_dot
from .users import User

ACCOUNT = """<div class="admin-wrap one acc-wrap">
  <a class="link back" href="/" data-back-last>%t.back%</a>
  <h1 class="admin-title">%t.account_title%</h1>
  <section class="sys-wrap" data-network="%t.err_network%">
    <div class="sys-list glass">
      <form class="sys-row acc-profile" method="post" action="/settings" novalidate
            data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
        <div class="sys-fields">
          <label class="setting sys-field">
            <span class="setting-label">%t.display_name%</span>
            <input name="display_name" maxlength="40" value="%NAME_VALUE%" placeholder="%NAME_SHOWN%" autocomplete="nickname">
          </label>
          <label class="setting has-select sys-field">
            <span class="setting-label">%t.language%</span>
            <select name="language">
              <option value="de" %DE%>Deutsch</option>
              <option value="en" %EN%>English</option>
            </select>%CHEVRON%
          </label>
        </div>
        %PROFILE_INFO%
      </form>
      <form class="sys-row sys-action" method="get" action="/password">
        <button type="submit" class="sys-btn">%t.change_password%</button>%PASSWORD_INFO%
      </form>
      <div class="sys-row sys-action">
        <button type="button" class="sys-btn" disabled>%t.account_colors%</button>%COLORS_INFO%
      </div>
      <div class="sys-row sys-action">
        <button type="button" class="sys-btn danger-btn" data-account-delete %DELETE_OFF%>%t.account_delete%</button>%DELETE_INFO%
      </div>
    </div>
  </section>
</div>
<dialog class="dialog danger" id="account-delete-dialog">
  <form novalidate data-url="/account/delete" data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <h2>%t.account_delete_title%</h2>
    <p class="muted">%t.account_delete_text%</p>
    <label>%t.your_password%<input type="password" name="confirm" required autocomplete="current-password"></label>
    <p class="error" role="alert" data-error hidden></p>
    <div class="actions">
      <button type="button" data-close autofocus>%t.cancel%</button>
      <button class="danger-btn" type="submit">%t.account_delete%</button>
    </div>
  </form>
</dialog>"""


def render(user: User) -> str:
    """Body of /account. The owner can not delete the account until he hands the role on (users.delete_self)."""
    lang = user.language
    t = lambda key: i18n.t(lang, key)   # noqa: E731
    owner = user.role == "owner"
    return fill(
        ACCOUNT, lang,
        NAME_VALUE=esc(user.display_name or ""), NAME_SHOWN=esc(user.name),
        DE="selected" if lang == "de" else "", EN="selected" if lang == "en" else "",
        CHEVRON=icon("chevron_down"),
        PROFILE_INFO=info_dot(t("account_profile"), t("account_profile_hint")),
        PASSWORD_INFO=info_dot(t("change_password"), t("account_password_hint")),
        COLORS_INFO=info_dot(t("account_colors"), t("account_colors_hint")),
        DELETE_OFF="disabled" if owner else "",
        DELETE_INFO=info_dot(t("account_delete"), t("account_delete_owner" if owner else "account_delete_hint")),
    )
