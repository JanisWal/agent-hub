"""HTML of the owner's system page."""
from html import escape as esc

from . import i18n, serversettings
from .icons import icon
from .layout import fill
from .ui import info_dot
from .users import User


def _upload_field(lang: str, name: str, label_key: str, choices: tuple, current: int, unit: str,
                  zero: str = "") -> str:
    """One choice of the server settings: a compact drop-down in our own style (core.js `.has-select`). `zero` is the
    text of the value 0 ("no limit")."""
    label = esc(i18n.t(lang, label_key))
    options = "".join(f'<option value="{value}"{" selected" if value == current else ""}>'
                      f'{esc(zero) if value == 0 and zero else f"{value}{unit}"}</option>' for value in choices)
    return (f'<label class="setting has-select sys-field"><span class="setting-label">{label}</span>'
            f'<select name="{name}">{options}</select>{icon("chevron_down")}</label>')


def _action(lang: str, key: str, attr: str) -> str:
    """A row that is one action (Janis, 14.11.2026): the button says what it does, the "i" next to it says the rest.
    No title above it that only repeats the button."""
    return (f'<div class="sys-row sys-action"><button type="button" class="sys-btn" {attr}>{esc(i18n.t(lang, key))}</button>'
            f'{info_dot(i18n.t(lang, key), i18n.t(lang, key + "_hint"))}</div>')


SYSTEM = """<section class="sys-wrap" data-network="%t.err_network%">
  <header class="sys-head"><h2>%t.system_title%</h2></header>
  <div class="sys-list glass">
    %BACKUP%
    <div class="sys-row sys-upload" data-url="/system/upload">
      <span class="sys-name">%t.sys_upload%</span>
      <div class="sys-fields">%UPLOAD_FIELDS%</div>
      %UPLOAD_INFO%
    </div>
    <div class="sys-row sys-upload" data-url="/system/ai">
      <span class="sys-name">%t.sys_ai%</span>
      <div class="sys-fields">%AI_FIELD%</div>
      %AI_INFO%
    </div>
    %REBOOT%
    %POWEROFF%
  </div>
  <p class="sys-note" id="sys-upload-note" role="status" hidden data-failed="%t.sys_upload_failed%"></p>
  <p class="sys-note" id="sys-backup-note" role="status" hidden
     data-running="%t.sys_backup_running%" data-ok="%t.sys_backup_ok%" data-failed="%t.sys_backup_failed%"></p>
  <p class="sys-note" id="sys-power-note" role="status" hidden
     data-done-reboot="%t.sys_reboot_done%" data-done-poweroff="%t.sys_poweroff_done%"></p>
</section>
<dialog class="dialog" id="power-reboot-dialog">
  <form novalidate data-url="/system/power" data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <h2>%t.sys_reboot_title%</h2>
    <p class="muted">%t.sys_reboot_hint%</p>
    <input type="hidden" name="action" value="reboot">
    <label>%t.your_password%<input type="password" name="confirm" required autocomplete="current-password"></label>
    <p class="error" role="alert" data-error hidden></p>
    <div class="actions">
      <button type="button" data-close autofocus>%t.cancel%</button>
      <button class="primary" type="submit">%t.sys_reboot_do%</button>
    </div>
  </form>
</dialog>
<dialog class="dialog danger" id="power-poweroff-dialog">
  <form novalidate data-url="/system/power" data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <h2>%t.sys_poweroff_title%</h2>
    <p class="muted">%t.sys_poweroff_hint%</p>
    <input type="hidden" name="action" value="poweroff">
    <label>%t.your_password%<input type="password" name="confirm" required autocomplete="current-password"></label>
    <p class="error" role="alert" data-error hidden></p>
    <div class="actions">
      <button type="button" data-close autofocus>%t.cancel%</button>
      <button class="danger-btn" type="submit">%t.sys_poweroff_do%</button>
    </div>
  </form>
</dialog>"""


def render(user: User) -> str:
    """The system block with its dialogs (a part of /admin, only for the owner; adminpage.py checks that)."""
    lang = user.language
    parallel, request_mb = serversettings.upload()
    fields = (_upload_field(lang, "parallel", "sys_upload_parallel", serversettings.PARALLEL, parallel, "")
              + _upload_field(lang, "request_mb", "sys_upload_size", serversettings.REQUEST_MB, request_mb, " MB"))
    t = lambda key: i18n.t(lang, key)   # noqa: E731
    upload_info = " ".join((t("sys_upload_hint"), f'{t("sys_upload_parallel")}: {t("sys_upload_parallel_info")}',
                            f'{t("sys_upload_size")}: {t("sys_upload_size_info")}'))
    ai_field = _upload_field(lang, "value", "sys_upload_parallel", serversettings.AI_PARALLEL,
                             serversettings.ai_parallel(), "", t("sys_ai_unlimited"))
    return fill(SYSTEM, lang, UPLOAD_FIELDS=fields, UPLOAD_INFO=info_dot(t("sys_upload"), upload_info),
                AI_FIELD=ai_field, AI_INFO=info_dot(t("sys_ai"), t("sys_ai_info")),
                BACKUP=_action(lang, "sys_backup", "data-backup"),
                REBOOT=_action(lang, "sys_reboot", 'data-power="reboot"'),
                POWEROFF=_action(lang, "sys_poweroff", 'data-power="poweroff"'))
