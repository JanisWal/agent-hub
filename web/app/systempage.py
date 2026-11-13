"""HTML of the owner's system page."""
from html import escape as esc

from . import i18n, serversettings
from .icons import icon
from .layout import fill
from .users import User


def _upload_field(lang: str, name: str, label_key: str, info_key: str, choices: tuple, current: int, unit: str) -> str:
    """One choice of the upload settings: a drop-down in our own style (core.js `.has-select`) and an "i" whose tip
    explains it. The "i" sits next to the box, not in it, so clicking it never opens the list."""
    label, info = esc(i18n.t(lang, label_key)), esc(i18n.t(lang, info_key))
    options = "".join(f'<option value="{value}"{" selected" if value == current else ""}>{value}{unit}</option>'
                      for value in choices)
    return (
        f'<div class="sys-field"><label class="setting has-select"><span class="setting-label">{label}</span>'
        f'<select name="{name}">{options}</select>{icon("chevron_down")}</label>'
        f'<button type="button" class="info-dot" data-tip="{info}" aria-label="{label}: {info}">{icon("info")}</button></div>'
    )

SYSTEM = """<section class="sys-wrap" data-network="%t.err_network%">
  <header class="sys-head"><h2>%t.system_title%</h2></header>
  <div class="sys-list glass">
    <div class="sys-row">
      <div class="sys-main"><span class="sys-name">%t.sys_backup%</span><span class="sys-hint">%t.sys_backup_hint%</span></div>
      <button type="button" data-backup>%t.sys_backup%</button>
    </div>
    <div class="sys-row sys-upload" data-url="/system/upload">
      <div class="sys-main"><span class="sys-name">%t.sys_upload%</span><span class="sys-hint">%t.sys_upload_hint%</span></div>
      <div class="sys-fields">%UPLOAD_FIELDS%</div>
    </div>
    <div class="sys-row">
      <div class="sys-main"><span class="sys-name">%t.sys_reboot%</span><span class="sys-hint">%t.sys_reboot_hint%</span></div>
      <button type="button" data-power="reboot">%t.sys_reboot%</button>
    </div>
    <div class="sys-row">
      <div class="sys-main"><span class="sys-name">%t.sys_poweroff%</span><span class="sys-hint">%t.sys_poweroff_hint%</span></div>
      <button type="button" data-power="poweroff">%t.sys_poweroff%</button>
    </div>
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
    fields = (_upload_field(lang, "parallel", "sys_upload_parallel", "sys_upload_parallel_info",
                            serversettings.PARALLEL, parallel, "")
              + _upload_field(lang, "request_mb", "sys_upload_size", "sys_upload_size_info",
                              serversettings.REQUEST_MB, request_mb, " MB"))
    return fill(SYSTEM, lang, UPLOAD_FIELDS=fields)
