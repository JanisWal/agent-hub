"""HTML of the owner's system page."""
from html import escape as esc

from . import i18n, serversettings
from .icons import icon
from .layout import fill
from .ui import info_dot
from .users import User


def _upload_field(lang: str, name: str, label_key: str, choices: tuple, current: int, unit: str,
                  zero: str = "", texts: dict | None = None) -> str:
    """One choice of the server settings: a compact drop-down in our own style (core.js `.has-select`). `zero` is the
    text of the value 0 ("no limit"); `texts` names every value (an on/off choice)."""
    label = esc(i18n.t(lang, label_key))
    def text(value: int) -> str:
        if texts:
            return esc(texts[value])
        return esc(zero) if value == 0 and zero else f"{value}{unit}"
    options = "".join(f'<option value="{value}"{" selected" if value == current else ""}>{text(value)}</option>'
                      for value in choices)
    return (f'<label class="setting has-select sys-field"><span class="setting-label">{label}</span>'
            f'<select name="{name}">{options}</select>{icon("chevron_down")}</label>')


def _action(lang: str, key: str, attr: str, info: bool = True) -> str:
    """A row that is one action (Janis, 14.11.2026): the button says what it does, the "i" next to it says the rest.
    No title above it that only repeats the button. `info`: only where the action needs explaining (Janis, 18.11.2026)."""
    dot = info_dot(i18n.t(lang, key), i18n.t(lang, key + "_hint")) if info else ""
    return (f'<div class="sys-row sys-action"><button type="button" class="sys-btn" {attr}>{esc(i18n.t(lang, key))}</button>'
            f'{dot}</div>')


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
    %HOME%
    %SKINS%
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


def _home_row(user: User) -> str:
    """Only the owner (Janis, 21.11.2026): may his further AIs be in this server's home network? It opens his network
    to them, so a superadmin does not see it."""
    if user.role != "owner":
        return ""
    lang = user.language
    t = lambda key: i18n.t(lang, key)   # noqa: E731
    field = _upload_field(lang, "value", "sys_ai_home_short", (0, 1), int(serversettings.ai_home_network()), "",
                          texts={0: t("sys_ai_home_off"), 1: t("sys_ai_home_on")})
    return (f'<div class="sys-row sys-upload" data-url="/system/ai-home"><span class="sys-name">'
            f'{esc(t("sys_ai_home"))}</span><div class="sys-fields">{field}</div>'
            f'{info_dot(t("sys_ai_home"), t("sys_ai_home_info"))}</div>')


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
    return fill(SYSTEM, lang, UPLOAD_FIELDS=fields, HOME=_home_row(user), UPLOAD_INFO=info_dot(t("sys_upload"), upload_info),
                AI_FIELD=ai_field, AI_INFO=info_dot(t("sys_ai"), t("sys_ai_info")),
                BACKUP=_action(lang, "sys_backup", "data-backup"),
                SKINS=_action(lang, "sys_skins", "disabled", info=False),   # placeholder (Janis, 18.11.2026): comes later
                REBOOT=_action(lang, "sys_reboot", 'data-power="reboot"'),
                POWEROFF=_action(lang, "sys_poweroff", 'data-power="poweroff"'))
