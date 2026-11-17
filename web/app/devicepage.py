"""The devices of the Manager view (Janis, 17.11.2026; second round the same evening): the tile, the dialog for a new
device, the setup assistant and the device window.

- Tile: rows like the files (glass cards): a large pictogram (or the picture the user dropped on it), LED, name and
  kind; the three round glass buttons (shut down or switch on, restart, update) in the shared design of the small
  round controls (DESIGN.md 4). In a narrow tile they spread under the name.
- Setup assistant: one step at a time (back, next), opened after a new device and from the window, never by itself.
- Window: a sheet over the whole window like the file viewer. Left: the device (the three actions large, its state,
  the data as a quiet overview with a pencil to change it, access and connection in short, what the AI may ask for).
  Right: the segment slider of the file tile (shell, files, logs, log of the hub) and ONE "connect" with the
  password for shell, files and logs together.

Only markup with texts from i18n.py; behaviour in static/devices.js (tile), devwin.js (window), devsetup.js
(assistant). Nothing here holds a secret: the page only learns whether one is stored.
"""
from . import device_profiles, devices as devicestore, i18n, ui, vault
from .icons import icon
from .layout import esc, fill, static_url

FIELDS_NEW = """<label>%t.devices_name%<input name="name" required maxlength="%MAX_NAME%" autocomplete="off" placeholder="%t.devices_name_placeholder%"></label>
    <label class="setting has-select">
      <span class="setting-label">%t.devices_kind%</span>
      <select name="kind">%KINDS%</select>
      %CHEVRON%
    </label>
    <div class="dev-pair">
      <label>%t.devices_hostname%<input name="hostname" required maxlength="%MAX_HOSTNAME%" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="server.fritz.box"></label>
      <label>%t.devices_ip%<input name="ip" maxlength="%MAX_IP%" autocomplete="off" autocapitalize="off" spellcheck="false" inputmode="decimal" placeholder="192.168.178.20"></label>
    </div>
    <label>%t.devices_description%<input name="description" maxlength="%MAX_DESCRIPTION%" autocomplete="off"></label>"""

DIALOGS = """<dialog class="dialog device-dialog" id="device-dialog" %ERRS%>
  <form method="post" action="" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <h2>%t.devices_new%</h2>
    %FIELDS_NEW%
    <p class="error" role="alert" id="device-error" hidden></p>
    <div class="actions">
      <button type="button" data-close>%t.cancel%</button>
      <button class="primary" type="submit">%t.dev_create_setup%</button>
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
      <button class="primary" type="submit">%t.dev_pass_go%</button>
    </div>
  </form>
</dialog>

<dialog class="dialog device-wizard" id="device-wizard" aria-labelledby="wiz-title" %ERRS%
    data-step="%t.dev_wiz_step%" data-next="%t.dev_wiz_next%" data-finish="%t.dev_wiz_finish%"
    data-key-stored="%t.devices_key_stored%" data-pass-stored="%t.dev_pass_stored%" data-host-new="%t.dev_host_new%"
    data-host-same="%t.dev_host_same%" data-host-changed="%t.dev_host_changed%" data-host-trusted="%t.dev_host_trusted%"
    data-sudo-ok="%t.dev_sudo_ok%" data-sudo-no="%t.dev_sudo_no%" data-copied="%t.dev_copied%">
  <header class="wiz-head">
    <h2 id="wiz-title" tabindex="-1">%t.dev_setup%</h2>
    <button class="icon-button card-btn" type="button" data-close aria-label="%t.close%" data-tip="%t.close%">%CROSS%</button>
  </header>
  <div class="wiz-progress" aria-hidden="true"><ol class="wiz-dots" id="wiz-dots"></ol><span class="wiz-count" id="wiz-count"></span></div>
  <section class="wiz-step" data-step="system">
    <h3>%t.dev_wiz_system%</h3>
    <p class="wiz-text">%t.dev_wiz_system_text%</p>
    <label class="setting has-select">
      <span class="setting-label">%t.dev_system%</span>
      <select id="wiz-family">%FAMILIES%</select>
      %CHEVRON%
    </label>
    <div class="dev-pair dev-pair-small">
      <label>%t.dev_user%<input id="wiz-user" maxlength="64" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="agenthub"></label>
      <label>%t.dev_port%<input id="wiz-port" inputmode="numeric" maxlength="5" autocomplete="off" value="22"></label>
    </div>
  </section>
  <section class="wiz-step" data-step="guide" data-guide="ssh_on"></section>
  <section class="wiz-step" data-step="guide" data-guide="user"></section>
  <section class="wiz-step" data-step="access">
    <h3>%t.setup_title_key%</h3>
    <p class="wiz-text">%t.dev_wiz_access_text%</p>
    <div class="wiz-actions"><button type="button" class="primary" id="wiz-keygen">%t.dev_keygen%</button></div>
    <p class="wiz-state" id="wiz-key-state" role="status"></p>
    <div id="wiz-key-cmd"></div>
    <details class="wiz-more"><summary>%t.dev_wiz_use_password%</summary>
      <p class="wiz-text">%t.dev_wiz_password_text%</p>
      <div class="wiz-inline"><input type="password" id="wiz-pass" maxlength="256" autocomplete="new-password" aria-label="%t.dev_auth_password%" placeholder="%t.dev_auth_password%">
        <button type="button" id="wiz-pass-save">%t.save%</button></div>
    </details>
    <details class="wiz-more"><summary>%t.dev_paste%</summary>
      <p class="wiz-text">%t.dev_paste_note%</p>
      <textarea class="device-key" id="wiz-key" maxlength="%MAX_KEY%" autocomplete="off" autocapitalize="off" spellcheck="false" rows="4" placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"></textarea>
      <div class="wiz-inline"><button type="button" id="wiz-key-save">%t.save%</button></div>
    </details>
  </section>
  <section class="wiz-step" data-step="guide" data-guide="sudoers"></section>
  <section class="wiz-step" data-step="guide" data-guide="modules"></section>
  <section class="wiz-step" data-step="guide" data-guide="no_password"></section>
  <section class="wiz-step" data-step="hostkey">
    <h3>%t.dev_wiz_hostkey%</h3>
    <p class="wiz-text">%t.dev_connection_info%</p>
    <div class="wiz-actions"><button type="button" class="primary" id="wiz-hostkey">%t.dev_hostkey%</button></div>
    <p class="wiz-state" id="wiz-host-state" role="status"></p>
    <code class="wiz-fp" id="wiz-fp" hidden></code>
    <div class="wiz-actions"><button type="button" class="primary" id="wiz-trust" hidden>%t.dev_trust%</button></div>
  </section>
  <section class="wiz-step" data-step="test">
    <h3>%t.setup_title_test%</h3>
    <p class="wiz-text">%t.dev_wiz_test_text%</p>
    <div class="wiz-actions"><button type="button" class="primary" id="wiz-test">%t.dev_test%</button></div>
    <p class="wiz-state" id="wiz-test-state" role="status"></p>
  </section>
  <p class="error" role="alert" id="wiz-error" hidden></p>
  <div class="actions wiz-nav">
    <button type="button" id="wiz-back">%t.dev_wiz_back%</button>
    <button type="button" id="wiz-next">%t.dev_wiz_next%</button>
  </div>
  <span hidden id="dev-copy-icon">%COPY%</span>
</dialog>

<dialog class="dialog device-window" id="device-window" aria-labelledby="dw-name" %ERRS%
    data-saved="%t.dev_saved%" data-key-stored="%t.devices_key_stored%" data-key-own="%t.dev_key_own%" data-key-none="%t.dev_key_none%"
    data-pass-stored="%t.dev_pass_stored%" data-host-known="%t.dev_host_known_short%" data-host-none="%t.dev_host_none_short%"
    data-sudo-ok="%t.dev_sudo_ok_short%" data-sudo-no="%t.dev_sudo_no_short%" data-os-none="%t.dev_os_none_short%"
    data-led-on="%t.dev_led_on%" data-led-off="%t.dev_led_off%" data-led-busy="%t.dev_led_busy%" data-led-unknown="%t.dev_led_unknown%"
    data-updates="%t.dev_updates_waiting%" data-reboot-needed="%t.dev_reboot_needed%" data-found="%t.dev_updates_found%" data-none="%t.dev_updates_none%"
    data-copied="%t.dev_copied%" data-web-note="%t.dev_web_note%" data-shell-closed="%t.dev_shell_closed%"
    data-files-empty="%t.dev_files_empty%" data-files-folder="%t.dev_files_folder%" data-files-rename="%t.dev_files_rename%"
    data-files-drop="%t.dev_files_drop%" data-files-up="%t.dev_files_uploading%" data-files-done="%t.dev_files_uploaded%"
    data-history-empty="%t.dev_history_empty%" data-origin-ai="%t.dev_origin_ai%" data-picture-saved="%t.dev_picture_saved%"
    data-power-on="%t.dev_btn_wake%" data-power-off="%t.dev_btn_power%"
    data-xterm="%XTERM%" data-xterm-fit="%XTERM_FIT%" data-xterm-css="%XTERM_CSS%" %NAMES%>
  <div class="dw-sheet">
    <header class="dw-head">
      <span class="file-tile device-tile dw-pic" id="dw-icon" aria-hidden="true"></span>
      <div class="dw-title-box">
        <h2 id="dw-name" tabindex="-1"></h2>
        <p class="dw-sub"><span class="dev-led" id="dw-led"></span><span id="dw-state"></span></p>
      </div>
      <button class="icon-button card-btn" type="button" data-close aria-label="%t.close%" data-tip="%t.close%">%CROSS%</button>
    </header>
    <div class="dw-body">
      <section class="dw-side" aria-label="%t.dev_settings%">
        <div class="dw-card dw-actions">
          <button type="button" class="icon-button dev-btn big" data-btn="power" aria-label="%t.dev_btn_power%" data-tip="%t.dev_btn_power%">%POWER%</button>
          <button type="button" class="icon-button dev-btn big" data-btn="reboot" aria-label="%t.dev_btn_reboot%" data-tip="%t.dev_btn_reboot%">%REFRESH%</button>
          <button type="button" class="icon-button dev-btn big" data-btn="update" aria-label="%t.dev_btn_update%" data-tip="%t.dev_btn_update%">%UPDATE%<span class="dev-dot" aria-hidden="true"></span></button>
          <p class="dw-say" id="dw-say" role="status" aria-live="polite"></p>
        </div>

        <div class="dw-card dw-setup-card" id="dw-setup-card" hidden>
          <p>%t.dev_not_set_up_text%</p>
          <button type="button" class="primary" id="dw-setup">%t.dev_setup%</button>
        </div>

        <div class="dw-card">
          <header class="dw-card-head"><h3>%t.dev_overview%</h3>
            <button type="button" class="icon-button card-btn" id="dw-edit" aria-label="%t.dev_edit%" data-tip="%t.dev_edit%" aria-expanded="false">%PENCIL%</button></header>
          <dl class="dw-facts" id="dw-facts"></dl>
          <form id="dw-form" method="post" action="" novalidate hidden data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
            %FIELDS_NEW%
            <p class="dw-hint" id="dw-ip-line" hidden><span>%t.dev_ip_hint%:</span> <code id="dw-ip-hint"></code>
              <button type="button" class="link inline" id="dw-ip-take">%t.dev_ip_take%</button></p>
            <div class="dev-pair dev-pair-small">
              <label>%t.dev_user%<input name="ssh_user" maxlength="64" autocomplete="off" autocapitalize="off" spellcheck="false"></label>
              <label>%t.dev_port%<input name="ssh_port" inputmode="numeric" maxlength="5" autocomplete="off"></label>
            </div>
            <label>%t.dev_mac%<input name="mac" maxlength="17" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="aa:bb:cc:dd:ee:ff"></label>
            <p class="error" role="alert" id="dw-error" hidden></p>
            <div class="actions"><button type="button" id="dw-edit-cancel">%t.cancel%</button><button class="primary" type="submit">%t.save%</button></div>
          </form>
        </div>

        <div class="dw-card">
          <header class="dw-card-head"><h3>%t.dev_access%</h3>%ACCESS_INFO%</header>
          <dl class="dw-facts" id="dw-access"></dl>
          <div class="dw-public" id="dw-public" hidden>
            <code id="dw-public-key"></code>
            <button type="button" class="icon-button card-btn dw-copy" data-copy="dw-public-key" aria-label="%t.dev_copy%" data-tip="%t.dev_copy%">%COPY%</button>
          </div>
          <div class="dw-links">
            <button type="button" class="link inline" id="dw-test">%t.dev_test%</button>
            <button type="button" class="link inline" id="dw-setup-again">%t.dev_setup_again%</button>
            <button type="button" class="link inline" id="dw-forget" hidden>%t.dev_forget%</button>
          </div>
          <p class="error" role="alert" id="dw-conn-error" hidden></p>
        </div>

        <div class="dw-card">
          <header class="dw-card-head"><h3>%t.dev_ai%</h3>%AI_INFO%</header>
          <div class="dw-ai" id="dw-ai">%AI_CHOICES%</div>
          <label class="check-line" id="dw-ai-pass-box" hidden><input type="checkbox" id="dw-ai-pass"><span>%t.dev_ai_password%</span></label>
        </div>

        <button type="button" class="link danger-link" id="dw-delete">%t.devices_delete%</button>
      </section>

      <section class="dw-work" aria-label="%t.dev_work%">
        <div class="dw-work-head">
          <div class="file-tabs dw-tabs" role="tablist"><span class="file-thumb" aria-hidden="true"></span>
            <button class="file-tab" type="button" role="tab" data-seg data-panel="shell" aria-selected="true">%TERMINAL%<span class="file-tab-label">%t.dev_shell%</span></button>
            <button class="file-tab" type="button" role="tab" data-seg data-panel="files" aria-selected="false">%FOLDER%<span class="file-tab-label">%t.dev_files%</span></button>
            <button class="file-tab" type="button" role="tab" data-seg data-panel="logs" aria-selected="false">%LIST%<span class="file-tab-label">%t.dev_logs%</span></button>
            <button class="file-tab" type="button" role="tab" data-seg data-panel="history" aria-selected="false">%NOTE%<span class="file-tab-label">%t.dev_history%</span></button>
          </div>
          %SHELL_INFO%
        </div>
        <div class="dw-connect" id="dw-connect" hidden>
          <span class="dw-connect-icon" aria-hidden="true">%KEY%</span>
          <p>%t.dev_connect_text%</p>
          <form id="dw-connect-form" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
            <input type="password" name="password" required autocomplete="current-password" aria-label="%t.dev_pass_label%" placeholder="%t.dev_pass_label%">
            <button class="primary" type="submit">%t.dev_connect%</button>
          </form>
          <p class="error" role="alert" id="dw-connect-error" hidden></p>
        </div>
        <div class="dw-panel" data-panel="shell">
          <div class="dw-term" id="dw-term"></div>
        </div>
        <div class="dw-panel" data-panel="files" hidden>
          <div class="dw-files-head">
            <button type="button" class="icon-button card-btn" id="dw-up" aria-label="%t.dev_files_up%" data-tip="%t.dev_files_up%">%ARROW_LEFT%</button>
            <nav class="dw-crumbs" id="dw-crumbs" aria-label="%t.dev_files_path%"></nav>
            <button type="button" class="icon-button card-btn" id="dw-mkdir" aria-label="%t.dev_files_mkdir%" data-tip="%t.dev_files_mkdir%">%FOLDER%</button>
            <label class="icon-button m-add dw-upload" aria-label="%t.dev_files_upload%" data-tip="%t.dev_files_upload%">%PLUS%<input type="file" id="dw-upload" multiple hidden></label>
          </div>
          <div class="dw-files-cols" aria-hidden="true"><span>%t.dev_col_name%</span><span>%t.dev_col_size%</span><span>%t.dev_col_changed%</span><span></span></div>
          <ul class="dw-files" id="dw-files"></ul>
          <div class="dw-editor" id="dw-editor" hidden>
            <div class="dw-files-head"><code class="dw-editor-path" id="dw-editor-path"></code>
              <button type="button" id="dw-editor-close">%t.close%</button><button type="button" class="primary" id="dw-editor-save">%t.save%</button></div>
            <textarea id="dw-editor-text" spellcheck="false"></textarea>
          </div>
        </div>
        <div class="dw-panel" data-panel="logs" hidden>
          <div class="dw-files-head">
            <div class="file-tabs dw-sources" role="tablist"><span class="file-thumb" aria-hidden="true"></span>
              <button class="file-tab" type="button" role="tab" data-seg data-source="journal" aria-selected="true"><span class="file-tab-label">%t.dev_logs_journal%</span></button>
              <button class="file-tab" type="button" role="tab" data-seg data-source="kernel" aria-selected="false"><span class="file-tab-label">%t.dev_logs_kernel%</span></button>
            </div>
            <button type="button" class="icon-button card-btn" id="dw-logs-again" aria-label="%t.dev_logs_again%" data-tip="%t.dev_logs_again%">%REFRESH%</button>
          </div>
          <pre class="dw-log" id="dw-log"></pre>
        </div>
        <div class="dw-panel" data-panel="history" hidden>
          <ul class="dw-history" id="dw-history"></ul>
        </div>
        <p class="file-status dw-status" id="dw-status" role="status" aria-live="polite"></p>
      </section>
    </div>
  </div>
  <span hidden id="dw-icons" data-folder="%FOLDER_E%" data-file="%FILE_E%" data-pencil="%PENCIL_E%" data-trash="%TRASH_E%"></span>
</dialog>"""

ERROR_CODES = ("off", "target", "address_changed", "unreachable", "refused", "timeout", "auth", "host_key_unknown",
               "host_key_changed", "secret", "unsupported", "sudo", "busy", "not_allowed", "failed", "missing", "exists",
               "grant", "too_big", "picture")
FIELD_ERRORS = ("name", "kind", "ip", "hostname", "description", "key", "duplicate", "limit", "vault", "user", "port",
                "mac", "auth", "other")
HISTORY = ("trust", "forget_host", "test", "keygen", "secret", "shell", "file_get", "file_put", "file_rename",
           "file_delete", "file_mkdir", "file_write", "wake")
FACTS = ("kind", "hostname", "ip", "system", "user", "mac", "description", "login", "hostkey", "rights")


def _errs(lang: str) -> str:
    broker_errors = " ".join(f'data-e-{c.replace("_", "-")}="{esc(i18n.t(lang, "dev_e_" + c))}"' for c in ERROR_CODES)
    field_errors = " ".join(f'data-err-{c}="{esc(i18n.t(lang, "devices_err_" + c))}"' for c in FIELD_ERRORS)
    return broker_errors + " " + field_errors


def _names(lang: str) -> str:
    parts = []
    for a in device_profiles.ACTIONS:
        dash = a.replace("_", "-")
        parts += [f'data-a-{dash}="{esc(i18n.t(lang, "dev_action_" + a))}"',
                  f'data-busy-{dash}="{esc(i18n.t(lang, "dev_busy_" + a))}"',
                  f'data-h-{dash}="{esc(i18n.t(lang, "dev_action_" + a))}"']
    parts += [f'data-busy-wake="{esc(i18n.t(lang, "dev_busy_wake"))}"']
    parts += [f'data-h-{h.replace("_", "-")}="{esc(i18n.t(lang, "dev_h_" + h))}"' for h in HISTORY]
    parts += [f'data-kind-{k.replace("_", "-")}="{esc(i18n.t(lang, "device_kind_" + k))}"' for k in devicestore.KINDS]
    parts += [f'data-f-{k}="{esc(i18n.t(lang, "dev_f_" + k))}"' for k in FACTS]
    return " ".join(parts)


def _fields(lang: str) -> str:
    return fill(FIELDS_NEW, lang, MAX_NAME=str(devicestore.MAX_NAME), MAX_HOSTNAME=str(devicestore.MAX_HOSTNAME),
                MAX_DESCRIPTION=str(devicestore.MAX_DESCRIPTION), MAX_IP=str(devicestore.MAX_IP),
                CHEVRON=icon("chevron_down"),
                KINDS="".join(f'<option value="{k}">{esc(i18n.t(lang, "device_kind_" + k))}</option>'
                              for k in devicestore.KINDS))


def dialogs(lang: str) -> str:
    """The dialog for a new device, the assistant and the window; outside the hidden Manager view."""
    ai = "".join(f'<label class="check-line"><input type="checkbox" name="actions" value="{a}">'
                 f'<span>{esc(i18n.t(lang, "dev_action_" + a))}</span></label>' for a in devicestore.AI_CHOICES)
    return fill(
        DIALOGS, lang, FIELDS_NEW=_fields(lang), ERRS=_errs(lang), NAMES=_names(lang), AI_CHOICES=ai,
        CHEVRON=icon("chevron_down"), CROSS=icon("cross"), COPY=icon("copy"), PENCIL=icon("pencil"), KEY=icon("key"),
        TERMINAL=icon("terminal"), FOLDER=icon("folder"), LIST=icon("list"), NOTE=icon("note"), PLUS=icon("plus"),
        ARROW_LEFT=icon("arrow_left"), REFRESH=icon("refresh"), POWER=icon("power"), UPDATE=icon("update"),
        FOLDER_E=esc(icon("folder")), FILE_E=esc(icon("file")), PENCIL_E=esc(icon("pencil")), TRASH_E=esc(icon("trash")),
        MAX_KEY=str(devicestore.MAX_KEY),
        FAMILIES="".join(f'<option value="{f}">{esc(device_profiles.PROFILES[f]["name"])}</option>'
                         for f in device_profiles.FAMILIES),
        XTERM=static_url("xterm.js"), XTERM_FIT=static_url("xterm-fit.js"), XTERM_CSS=static_url("xterm.css"),
        ACCESS_INFO=ui.info_dot(i18n.t(lang, "dev_access"), i18n.t(lang, "dev_login_info")),
        AI_INFO=ui.info_dot(i18n.t(lang, "dev_ai"), i18n.t(lang, "dev_ai_info")),
        SHELL_INFO=ui.info_dot(i18n.t(lang, "dev_work"), i18n.t(lang, "dev_shell_info")))


def _button(lang: str, name: str, picture: str, enabled: bool) -> str:
    label = esc(i18n.t(lang, "dev_btn_" + name))
    return (f'<button class="icon-button dev-btn" type="button" data-btn="{name}" aria-label="{label}" '
            f'data-tip="{label}"{"" if enabled else " disabled"}>{icon(picture)}'
            + ('<span class="dev-dot" aria-hidden="true"></span>' if name == "update" else "") + '</button>')


def picture(device: devicestore.Device) -> str:
    """The picture of a device: the one the user dropped on it, else its pictogram."""
    if device.picture:
        return f'<img class="dev-picture" src="{esc(device.picture)}" alt="">'
    return icon(device.icon)


def row(lang: str, device: devicestore.Device) -> str:
    acts = device.actions
    pending = devicestore.updates_pending(device)
    address = (f' · {esc(device.ip)}' if device.ip else
               f' · <span class="dev-hint" data-tip="{esc(i18n.t(lang, "dev_ip_hint"))}">{esc(device.ip_hint)}</span>'
               if device.ip_hint else "")
    return (
        f'<li class="file-row device-row{" has-updates" if pending else ""}" data-id="{device.id}" tabindex="0" '
        f'data-trusted="{1 if device.trusted else 0}" data-name="{esc(device.name)}">'
        f'<span class="file-tile device-tile" aria-hidden="true">{picture(device)}</span>'
        f'<span class="dev-text"><span class="dev-name"><span class="dev-led" role="img" '
        f'aria-label="{esc(i18n.t(lang, "dev_led_unknown"))}"></span><span class="dev-name-text">{esc(device.name)}</span></span>'
        f'<small>{esc(i18n.t(lang, "device_kind_" + device.kind))} · {esc(device.hostname)}{address}</small></span>'
        f'<span class="dev-buttons">'
        + _button(lang, "power", "power", "poweroff" in acts or device.can_wake)
        + _button(lang, "reboot", "refresh", "reboot" in acts)
        + _button(lang, "update", "update", "updates_check" in acts)
        + '</span></li>'
    )


def tile(lang: str, items: list) -> str:
    """The devices of the project: rows like the files; a click opens the device window, a picture dropped on a row
    becomes its picture."""
    add = esc(i18n.t(lang, "devices_add"))
    body = (f'<ul class="file-list device-list">{"".join(row(lang, d) for d in items)}</ul>' if items
            else f'<p class="muted">{esc(i18n.t(lang, "manager_devices_hint"))}</p>')
    return (
        f'<section class="mtile glass m-devices m-grow" id="devices" data-vault="{1 if vault.available() else 0}" '
        f'data-led-on="{esc(i18n.t(lang, "dev_led_on"))}" data-led-off="{esc(i18n.t(lang, "dev_led_off"))}" '
        f'data-led-busy="{esc(i18n.t(lang, "dev_led_busy"))}" data-led-unknown="{esc(i18n.t(lang, "dev_led_unknown"))}" '
        f'data-found="{esc(i18n.t(lang, "dev_updates_found", n="{n}"))}" data-none="{esc(i18n.t(lang, "dev_updates_none"))}" '
        f'data-power-on="{esc(i18n.t(lang, "dev_btn_wake"))}" data-power-off="{esc(i18n.t(lang, "dev_btn_power"))}" '
        f'data-picture-saved="{esc(i18n.t(lang, "dev_picture_saved"))}" {_errs(lang)} {_names(lang)}>'
        f'<header><h2>{esc(i18n.t(lang, "manager_devices"))}</h2>'
        f'{ui.info_dot(i18n.t(lang, "manager_devices"), i18n.t(lang, "devices_info"))}'
        f'<span class="count">{len(items)}</span>'
        f'<button class="icon-button m-add" id="device-add" type="button" aria-label="{add}" data-tip="{add}">'
        f'{icon("plus")}</button></header>{body}'
        f'<p class="file-status dev-say" id="dev-say" role="status" aria-live="polite"></p></section>'
    )
