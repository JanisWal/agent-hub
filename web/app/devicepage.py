"""The devices of the Manager view (Janis, 17.11.2026): the tile with one row per device (pictogram, name, LED, three
round glass buttons: shut down, restart, update), the dialog for a new device, and the device window (settings on
the left; shell, files, logs and the hub's log on the right), the setup guide and the password dialog.

Only markup with texts from i18n.py; the behaviour is in static/devices.js (tile, buttons, LED) and static/devwin.js
(the window). Nothing here ever holds a secret: the page only learns whether one is stored.
"""
from . import device_profiles, devices as devicestore, i18n, ui, vault
from .icons import icon
from .layout import esc, fill
from .layout import static_url

NEW_DIALOG = """<dialog class="dialog device-dialog" id="device-dialog"
        data-err-name="%t.devices_err_name%" data-err-kind="%t.devices_err_other%" data-err-ip="%t.devices_err_ip%" data-err-hostname="%t.devices_err_hostname%" data-err-description="%t.devices_err_description%"
        data-err-key="%t.devices_err_key%" data-err-duplicate="%t.devices_err_duplicate%" data-err-limit="%t.devices_err_limit%"
        data-err-vault="%t.devices_err_vault%" data-err-user="%t.devices_err_user%" data-err-port="%t.devices_err_port%" data-err-other="%t.devices_err_other%">
  <form method="post" action="" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <h2>%t.devices_new%</h2>
    %FIELDS%
    <p class="error" role="alert" id="device-error" hidden></p>
    <div class="actions">
      <button type="button" data-close>%t.cancel%</button>
      <button class="primary" type="submit">%t.create%</button>
    </div>
  </form>
</dialog>
<dialog class="dialog danger" id="device-confirm" data-device="%t.devices_confirm_delete%" data-file="%t.dev_files_confirm%">
  <h2>%t.devices_confirm_delete%</h2>
  <div class="actions">
    <button type="button" data-close autofocus>%t.cancel%</button>
    <button class="danger-btn" type="button" id="device-confirm-yes">%t.yes%</button>
  </div>
</dialog>
<dialog class="dialog" id="device-pass">
  <form method="post" action="" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <h2 id="device-pass-title">%t.dev_pass_title%</h2>
    <p class="muted" id="device-pass-text"></p>
    <label>%t.dev_pass_label%<input type="password" name="password" required autocomplete="current-password"></label>
    <p class="error" role="alert" id="device-pass-error" hidden></p>
    <div class="actions">
      <button type="button" data-close>%t.cancel%</button>
      <button class="primary" type="submit" id="device-pass-go">%t.dev_pass_go%</button>
    </div>
  </form>
</dialog>"""

FIELDS = """<label>%t.devices_name%<input name="name" required maxlength="%MAX_NAME%" autocomplete="off" placeholder="%t.devices_name_placeholder%"></label>
    <label class="setting has-select">
      <span class="setting-label">%t.devices_kind%</span>
      <select name="kind">%KINDS%</select>
      %CHEVRON%
    </label>
    <div class="dev-pair">
      <label>%t.devices_hostname%<input name="hostname" required maxlength="%MAX_HOSTNAME%" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="roadster.fritz.box"></label>
      <label>%t.devices_ip%<input name="ip" maxlength="%MAX_IP%" autocomplete="off" autocapitalize="off" spellcheck="false" inputmode="decimal" placeholder="192.168.178.20"></label>
    </div>
    <div class="dev-pair dev-pair-small">
      <label>%t.dev_user%<input name="ssh_user" maxlength="64" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="agenthub"></label>
      <label>%t.dev_port%<input name="ssh_port" inputmode="numeric" maxlength="5" autocomplete="off" value="22"></label>
    </div>
    <label>%t.devices_description%<input name="description" maxlength="%MAX_DESCRIPTION%" autocomplete="off"></label>"""

WINDOW = """<dialog class="dialog device-window" id="device-window" aria-labelledby="dw-name"
    data-err-name="%t.devices_err_name%" data-err-ip="%t.devices_err_ip%" data-err-hostname="%t.devices_err_hostname%" data-err-description="%t.devices_err_description%"
    data-err-key="%t.devices_err_key%" data-err-duplicate="%t.devices_err_duplicate%" data-err-vault="%t.devices_err_vault%"
    data-err-user="%t.devices_err_user%" data-err-port="%t.devices_err_port%" data-err-other="%t.devices_err_other%"
    %ERRORS%
    data-saved="%t.dev_saved%" data-key-stored="%t.devices_key_stored%" data-key-none="%t.dev_key_none%"
    data-pass-stored="%t.dev_pass_stored%" data-pass-none="%t.dev_pass_none%"
    data-host-none="%t.dev_host_none%" data-host-known="%t.dev_host_known%" data-host-new="%t.dev_host_new%" data-host-same="%t.dev_host_same%" data-host-changed="%t.dev_host_changed%"
    data-os-none="%t.dev_os_none%" data-sudo-ok="%t.dev_sudo_ok%" data-sudo-no="%t.dev_sudo_no%" data-tested="%t.dev_tested%"
    data-copied="%t.dev_copied%" data-web-note="%t.dev_web_note%" data-shell-closed="%t.dev_shell_closed%"
    data-files-empty="%t.dev_files_empty%" data-files-delete="%t.dev_files_delete%" data-files-folder="%t.dev_files_folder%" data-files-rename="%t.dev_files_rename%"
    data-history-empty="%t.dev_history_empty%" data-origin-ai="%t.dev_origin_ai%" data-reboot-needed="%t.dev_reboot_needed%"
    data-xterm="%XTERM%" data-xterm-fit="%XTERM_FIT%" data-xterm-css="%XTERM_CSS%" %ACTION_NAMES%>
  <div class="dw-sheet">
    <header class="dw-head">
      <span class="file-tile device-tile" id="dw-icon" aria-hidden="true"></span>
      <h2 id="dw-name"></h2>
      <span class="dev-led" id="dw-led" role="img"></span>
      <button class="icon-button card-btn" type="button" data-close aria-label="%t.close%" data-tip="%t.close%">%CROSS%</button>
    </header>
    <div class="dw-body">
      <section class="dw-settings" aria-label="%t.dev_settings%">
        <form id="dw-form" method="post" action="" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
          %FIELDS%
          <p class="dw-line dw-small" id="dw-ip-line" hidden><span class="muted" id="dw-ip-hint-text">%t.dev_ip_hint%</span>
            <button type="button" class="dw-link" id="dw-ip-take">%t.dev_ip_take%</button></p>
          <p class="error" role="alert" id="dw-error" hidden></p>
          <div class="actions dw-save"><span class="muted dw-said" id="dw-said" role="status"></span><button class="primary" type="submit">%t.save%</button></div>
        </form>

        <h3>%t.dev_login% %LOGIN_INFO%</h3>
        <label class="setting has-select">
          <span class="setting-label">%t.dev_auth%</span>
          <select id="dw-auth"><option value="key">%t.dev_auth_key%</option><option value="password">%t.dev_auth_password%</option></select>
          %CHEVRON%
        </label>
        <div id="dw-key-part">
          <p class="dw-line"><span id="dw-key-state"></span></p>
          <div class="dw-buttons"><button type="button" class="primary" id="dw-keygen">%t.dev_keygen%</button> %KEYGEN_INFO%</div>
          <div class="dw-public" id="dw-public" hidden>
            <span class="setting-label">%t.dev_public%</span>
            <code id="dw-public-key"></code>
            <button type="button" class="icon-button card-btn dw-copy" data-copy="dw-public-key" aria-label="%t.dev_copy%" data-tip="%t.dev_copy%">%COPY%</button>
          </div>
          <details class="dw-paste"><summary>%t.dev_paste%</summary>
            <textarea class="device-key" id="dw-key" maxlength="%MAX_KEY%" autocomplete="off" autocapitalize="off" spellcheck="false" rows="4" placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"></textarea>
            <p class="muted dw-small">%t.dev_paste_note%</p>
            <div class="dw-buttons"><button type="button" id="dw-key-save">%t.save%</button></div>
          </details>
        </div>
        <div id="dw-pass-part" hidden>
          <p class="dw-line"><span id="dw-pass-state"></span></p>
          <label>%t.dev_auth_password%<input type="password" id="dw-pass" maxlength="256" autocomplete="new-password"></label>
          <div class="dw-buttons"><button type="button" id="dw-pass-save">%t.save%</button></div>
        </div>
        <label class="check-line" id="dw-remove-box"><input type="checkbox" id="dw-remove"><span>%t.dev_remove_secret%</span></label>

        <h3>%t.dev_connection% %HOST_INFO%</h3>
        <p class="dw-line" id="dw-host"></p>
        <p class="dw-line dw-fp" id="dw-fp" hidden><code id="dw-fp-text"></code></p>
        <div class="dw-buttons">
          <button type="button" id="dw-hostkey">%t.dev_hostkey%</button>
          <button type="button" class="primary" id="dw-trust" hidden>%t.dev_trust%</button>
          <button type="button" id="dw-test">%t.dev_test%</button>
          <button type="button" id="dw-setup">%t.dev_setup%</button>
        </div>
        <p class="dw-line" id="dw-os"></p>
        <p class="dw-line" id="dw-sudo"></p>
        <p class="error" role="alert" id="dw-conn-error" hidden></p>
        <button type="button" class="dw-link" id="dw-forget" hidden>%t.dev_forget%</button>

        <h3>%t.dev_ai% %AI_INFO%</h3>
        <div class="dw-ai" id="dw-ai">%AI_CHOICES%</div>
        <label class="check-line" id="dw-ai-pass-box"><input type="checkbox" id="dw-ai-pass"><span>%t.dev_ai_password%</span> %AI_PASS_INFO%</label>
        <p class="muted dw-small" id="dw-lan" hidden>%t.dev_lan_wait%</p>

        <button type="button" class="dw-link danger-link" id="dw-delete">%t.devices_delete%</button>
      </section>

      <section class="dw-work" aria-label="%t.dev_work%">
        <div class="dw-tabs" role="tablist">
          <button type="button" role="tab" class="dw-tab" data-panel="shell" aria-selected="true">%TERMINAL% <span>%t.dev_shell%</span></button>
          <button type="button" role="tab" class="dw-tab" data-panel="files" aria-selected="false">%FOLDER% <span>%t.dev_files%</span></button>
          <button type="button" role="tab" class="dw-tab" data-panel="logs" aria-selected="false">%LIST% <span>%t.dev_logs%</span></button>
          <button type="button" role="tab" class="dw-tab" data-panel="history" aria-selected="false">%NOTE% <span>%t.dev_history%</span></button>
        </div>
        <div class="dw-grant" id="dw-grant" hidden>
          <p>%t.dev_grant_text%</p>
          <form id="dw-grant-form" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
            <input type="password" name="password" required autocomplete="current-password" aria-label="%t.dev_pass_label%" placeholder="%t.dev_pass_label%">
            <button class="primary" type="submit">%t.dev_grant_go%</button>
          </form>
          <p class="error" role="alert" id="dw-grant-error" hidden></p>
        </div>
        <div class="dw-panel" data-panel="shell">
          <div class="dw-panel-head"><h3>%t.dev_shell% %SHELL_INFO%</h3><button type="button" class="primary" id="dw-shell-go">%t.dev_shell_go%</button></div>
          <div class="dw-term" id="dw-term"></div>
        </div>
        <div class="dw-panel" data-panel="files" hidden>
          <div class="dw-panel-head">
            <button type="button" class="icon-button card-btn" id="dw-up" aria-label="%t.dev_files_up%" data-tip="%t.dev_files_up%">%ARROW_UP%</button>
            <code class="dw-path" id="dw-path"></code>
            <button type="button" class="icon-button card-btn" id="dw-mkdir" aria-label="%t.dev_files_mkdir%" data-tip="%t.dev_files_mkdir%">%FOLDER%</button>
            <label class="icon-button card-btn dw-upload" aria-label="%t.dev_files_upload%" data-tip="%t.dev_files_upload%">%PLUS%<input type="file" id="dw-upload" hidden></label>
          </div>
          <ul class="dw-files" id="dw-files"></ul>
          <div class="dw-editor" id="dw-editor" hidden>
            <div class="dw-panel-head"><code id="dw-editor-path"></code><button type="button" id="dw-editor-close">%t.close%</button><button type="button" class="primary" id="dw-editor-save">%t.save%</button></div>
            <textarea id="dw-editor-text" spellcheck="false"></textarea>
          </div>
        </div>
        <div class="dw-panel" data-panel="logs" hidden>
          <div class="dw-panel-head">
            <button type="button" class="dw-src" data-source="journal" aria-pressed="true">%t.dev_logs_journal%</button>
            <button type="button" class="dw-src" data-source="kernel" aria-pressed="false">%t.dev_logs_kernel%</button>
            <button type="button" class="icon-button card-btn" id="dw-logs-again" aria-label="%t.dev_logs_again%" data-tip="%t.dev_logs_again%">%REFRESH%</button>
          </div>
          <pre class="dw-log" id="dw-log"></pre>
        </div>
        <div class="dw-panel" data-panel="history" hidden>
          <ul class="dw-history" id="dw-history"></ul>
        </div>
        <p class="error" role="alert" id="dw-work-error" hidden></p>
      </section>
    </div>
  </div>
</dialog>
<dialog class="dialog device-setup" id="device-setup">
  <h2>%t.dev_setup% %SETUP_INFO%</h2>
  <label class="setting has-select">
    <span class="setting-label">%t.dev_system%</span>
    <select id="setup-family">%FAMILIES%</select>
    %CHEVRON%
  </label>
  <ol class="setup-steps" id="setup-steps"></ol>
  <span hidden id="dw-copy-icon">%COPY%</span><span hidden id="dw-trash-icon">%TRASH%</span><span hidden id="dw-pencil-icon">%PENCIL%</span>
  <div class="actions"><button type="button" class="primary" data-close>%t.close%</button></div>
</dialog>"""


HISTORY = ("trust", "forget_host", "test", "keygen", "shell", "file_get", "file_put", "file_rename", "file_delete",
           "file_mkdir", "file_write")


def _errors(lang: str) -> str:
    codes = ("off", "target", "address_changed", "unreachable", "refused", "timeout", "auth", "host_key_unknown",
             "host_key_changed", "secret", "unsupported", "sudo", "busy", "not_allowed", "failed", "missing", "exists",
             "grant", "too_big")
    return " ".join(f'data-e-{c.replace("_", "-")}="{esc(i18n.t(lang, "dev_e_" + c))}"' for c in codes)


def _fields(lang: str) -> str:
    return fill(FIELDS, lang, MAX_NAME=str(devicestore.MAX_NAME), MAX_HOSTNAME=str(devicestore.MAX_HOSTNAME),
                MAX_DESCRIPTION=str(devicestore.MAX_DESCRIPTION), MAX_IP=str(devicestore.MAX_IP),
                CHEVRON=icon("chevron_down"),
                KINDS="".join(f'<option value="{k}">{esc(i18n.t(lang, "device_kind_" + k))}</option>'
                              for k in devicestore.KINDS))


def dialogs(lang: str) -> str:
    """The dialogs and the window; outside the hidden Manager view (managerpage.dialogs)."""
    names = " ".join(f'data-a-{a.replace("_", "-")}="{esc(i18n.t(lang, "dev_action_" + a))}" '
                     f'data-busy-{a.replace("_", "-")}="{esc(i18n.t(lang, "dev_busy_" + a))}" '
                     f'data-h-{a.replace("_", "-")}="{esc(i18n.t(lang, "dev_action_" + a))}"'
                     for a in device_profiles.ACTIONS)
    names += " " + " ".join(f'data-h-{h.replace("_", "-")}="{esc(i18n.t(lang, "dev_h_" + h))}"' for h in HISTORY)
    ai = "".join(f'<label class="check-line"><input type="checkbox" name="actions" value="{a}">'
                 f'<span>{esc(i18n.t(lang, "dev_action_" + a))}</span></label>' for a in devicestore.AI_CHOICES)
    return fill(NEW_DIALOG, lang, FIELDS=_fields(lang)) + "\n" + fill(
        WINDOW, lang, FIELDS=_fields(lang), CHEVRON=icon("chevron_down"), CROSS=icon("cross"), COPY=icon("copy"),
        TERMINAL=icon("terminal"), FOLDER=icon("folder"), LIST=icon("list"), NOTE=icon("note"), PLUS=icon("plus"),
        ARROW_UP=icon("arrow_up"), REFRESH=icon("refresh"), MAX_KEY=str(devicestore.MAX_KEY), ERRORS=_errors(lang),
        ACTION_NAMES=names, AI_CHOICES=ai, TRASH=icon("trash"), PENCIL=icon("pencil"),
        FAMILIES="".join(f'<option value="{f}">{esc(device_profiles.PROFILES[f]["name"])}</option>'
                         for f in device_profiles.FAMILIES),
        XTERM=static_url("xterm.js"), XTERM_FIT=static_url("xterm-fit.js"), XTERM_CSS=static_url("xterm.css"),
        LOGIN_INFO=ui.info_dot(i18n.t(lang, "dev_login"), i18n.t(lang, "dev_login_info")),
        KEYGEN_INFO=ui.info_dot(i18n.t(lang, "dev_keygen"), i18n.t(lang, "dev_keygen_info")),
        HOST_INFO=ui.info_dot(i18n.t(lang, "dev_connection"), i18n.t(lang, "dev_connection_info")),
        AI_INFO=ui.info_dot(i18n.t(lang, "dev_ai"), i18n.t(lang, "dev_ai_info")),
        AI_PASS_INFO=ui.info_dot(i18n.t(lang, "dev_ai_password"), i18n.t(lang, "dev_ai_password_info")),
        SHELL_INFO=ui.info_dot(i18n.t(lang, "dev_shell"), i18n.t(lang, "dev_shell_info")),
        SETUP_INFO=ui.info_dot(i18n.t(lang, "dev_setup"), i18n.t(lang, "dev_setup_info")))


def _button(lang: str, name: str, picture: str, enabled: bool) -> str:
    label = esc(i18n.t(lang, "dev_btn_" + name))
    return (f'<button class="icon-button dev-btn" type="button" data-btn="{name}" aria-label="{label}" '
            f'data-tip="{label}"{"" if enabled else " disabled"}>{icon(picture)}'
            + ('<span class="dev-dot" aria-hidden="true"></span>' if name == "update" else "") + '</button>')


def row(lang: str, device: devicestore.Device) -> str:
    acts = device.actions
    pending = devicestore.updates_pending(device)
    return (
        f'<li class="file-row device-row{" has-updates" if pending else ""}" data-id="{device.id}" tabindex="0" '
        f'data-trusted="{1 if device.trusted else 0}">'
        f'<span class="file-tile device-tile" aria-hidden="true">{icon(device.icon)}</span>'
        f'<span class="check-text"><span class="check-title"><span class="dev-led" role="img" '
        f'aria-label="{esc(i18n.t(lang, "dev_led_unknown"))}"></span>{esc(device.name)}</span>'
        f'<small>{esc(i18n.t(lang, "device_kind_" + device.kind))} · {esc(device.hostname)}'
        + (f' · {esc(device.ip)}' if device.ip else
           f' · <span class="dev-hint" data-tip="{esc(i18n.t(lang, "dev_ip_hint"))}">{esc(device.ip_hint)}</span>'
           if device.ip_hint else "")
        + '</small></span>'
        f'<span class="dev-buttons">'
        + _button(lang, "power", "power", "poweroff" in acts)
        + _button(lang, "reboot", "refresh", "reboot" in acts)
        + _button(lang, "update", "update", "updates_check" in acts)
        + '</span></li>'
    )


def tile(lang: str, items: list) -> str:
    """The devices of the project: rows like the files; a click on a row opens the device window."""
    add = esc(i18n.t(lang, "devices_add"))
    body = (f'<ul class="file-list device-list">{"".join(row(lang, d) for d in items)}</ul>' if items
            else f'<p class="muted">{esc(i18n.t(lang, "manager_devices_hint"))}</p>')
    return (
        f'<section class="mtile glass m-devices m-grow" id="devices" data-vault="{1 if vault.available() else 0}" '
        f'data-led-on="{esc(i18n.t(lang, "dev_led_on"))}" data-led-off="{esc(i18n.t(lang, "dev_led_off"))}" '
        f'data-led-busy="{esc(i18n.t(lang, "dev_led_busy"))}" data-led-unknown="{esc(i18n.t(lang, "dev_led_unknown"))}" '
        f'data-found="{esc(i18n.t(lang, "dev_updates_found", n="{n}"))}" data-none="{esc(i18n.t(lang, "dev_updates_none"))}" '
        f'data-power-off="{esc(i18n.t(lang, "dev_power_off"))}" {_errors(lang)}>'
        f'<header><h2>{esc(i18n.t(lang, "manager_devices"))}</h2>'
        f'{ui.info_dot(i18n.t(lang, "manager_devices"), i18n.t(lang, "devices_info"))}'
        f'<span class="count">{len(items)}</span>'
        f'<button class="icon-button m-add" id="device-add" type="button" aria-label="{add}" data-tip="{add}">'
        f'{icon("plus")}</button></header>{body}'
        f'<p class="file-status dev-say" id="dev-say" role="status" aria-live="polite"></p></section>'
    )
