"""HTML of the backup (27.11.2026): the recovery key, the nightly hour, the list, and putting a backup back.

The parts are shared: the set-up assistant (setuppage.py) shows the key and the restore part on its own pages, the
administration (systempage.py) shows all of them in one dialog. static/backup.js drives them; every text comes from here.
"""
import datetime
from html import escape as esc

from . import backups, hostjobs, i18n, serversettings
from .icons import icon
from .layout import fill
from .ui import copy_button


def size_text(lang: str, size: int) -> str:
    """Bytes as the page shows them: "820 KB", "3,4 MB", "1,2 GB"."""
    for unit, step in (("GB", 1e9), ("MB", 1e6)):
        if size >= step:
            text = f"{size / step:.1f}"
            return (text.replace(".", ",") if lang == "de" else text) + " " + unit
    return f"{max(1, round(size / 1000))} KB"


def _date(lang: str, stamp: int) -> str:
    when = datetime.datetime.fromtimestamp(stamp)
    return when.strftime("%d.%m.%Y" if lang == "de" else "%Y-%m-%d")


KEY = """<div class="bk-key" data-backup-key data-url="/backup/key" data-failed="%t.setup_failed%">
  <div data-step="ask">
    <p class="muted" data-key-state>%STATE%</p>
    %PASSWORD%
    <p class="error" role="alert" data-error hidden></p>
    <button class="%BUTTON_CLASS%" type="button" data-key-make>%BUTTON%</button>
  </div>
  <div data-step="show" hidden>
    <p class="muted">%t.bk_key_show%</p>
    <div class="copy-box bk-key-box"><code data-copy-text data-key-text></code>%COPY%</div>
    <button class="link inline" type="button" data-key-file>%t.bk_key_file%</button>
    <label class="bk-check"><input type="checkbox" data-key-saved> <span>%t.bk_key_saved%</span></label>
  </div>
</div>"""


def key_part(lang: str, setup: bool = False) -> str:
    """The recovery key: its state and a button to make one. Replacing a key needs the owner's password (older
    backups then need the old key); the first one in the set-up does not."""
    made = backups.key_made_at()
    state = i18n.t(lang, "bk_key_made", date=_date(lang, made)) if made else i18n.t(lang, "bk_key_none")
    if made:
        state += " " + i18n.t(lang, "bk_key_replace_hint")
    password = "" if not made else (   # shown only after the first click on "new key" (backup.js)
        f'<label hidden data-key-ask>{esc(i18n.t(lang, "your_password"))}<input type="password" name="confirm" '
        f'autocomplete="current-password" data-key-password></label>')
    return fill(KEY, lang, STATE=esc(state), PASSWORD=password, COPY=copy_button(lang),
                BUTTON=esc(i18n.t(lang, "bk_key_replace" if made else "bk_key_create")),
                BUTTON_CLASS="primary" if not made or setup else "sys-btn")


def hour_field(lang: str) -> str:
    options = "".join(f'<option value="{h}"{" selected" if h == backups.hour() else ""}>{h:02d}:00</option>'
                      for h in serversettings.CHOICES["backup_hour"])
    return (f'<label class="setting has-select bk-hour"><span class="setting-label">{esc(i18n.t(lang, "bk_hour"))}'
            f'</span><select name="value" data-backup-hour data-url="/backup/hour">{options}</select>'
            f'{icon("chevron_down")}</label>')


NOW = """<div class="bk-now" data-backup-now data-url="/backup/now" data-state="/backup/state" data-active="%ACTIVE%"
     data-running="%t.bk_running%" data-ok="%t.bk_ok%" data-failed="%t.bk_failed%" data-no-key="%t.bk_failed_no_key%"
     data-busy="%t.bk_busy%">
  <button class="sys-btn" type="button" data-backup-start>%t.bk_now%</button>
  <p class="muted bk-note" role="status" data-backup-note hidden></p>
</div>"""


def list_rows(lang: str) -> str:
    found = backups.listing()
    if not found:
        return f'<li class="bk-empty muted">{esc(i18n.t(lang, "bk_list_empty"))}</li>'
    rows = []
    for item in found[:12]:
        day = item["date"] if lang != "de" else ".".join(reversed(item["date"].split("-")))
        rows.append(f'<li class="bk-row"><span class="bk-when">{esc(day)} {esc(item["time"])}</span>'
                    f'<span class="bk-size">{esc(size_text(lang, item["size"]))}</span>'
                    f'<button class="link inline" type="button" data-backup-get="{esc(item["name"])}">'
                    f'{esc(i18n.t(lang, "bk_download"))}</button></li>')
    return "".join(rows)


RESTORE = """<div class="restore" data-restore data-owner="%OWNER%" data-base="/restore"
     data-uploading="%t.rs_uploading%" data-failed="%t.setup_failed%" data-err-wrong_key="%t.rs_err_wrong_key%"
     data-err-bad_key="%t.rs_err_bad_key%" data-err-damaged="%t.rs_err_damaged%" data-err-size="%t.rs_err_size%"
     data-err-apply="%t.rs_err_apply%" data-err-newer="%t.rs_newer%" data-de="%DE%">
  <div data-step="pick">
    <p class="muted">%t.rs_text%</p>
    <input type="file" accept=".age" hidden data-restore-file>
    <button class="primary" type="button" data-restore-pick>%t.rs_pick%</button>
    <div class="rs-progress" hidden data-restore-progress><div class="rs-bar"><i></i></div><p class="muted" data-restore-count></p></div>
  </div>
  <div data-step="key" hidden>
    <p class="muted">%t.rs_key_text%</p>
    <textarea class="field-text rs-key" name="key" rows="3" spellcheck="false" autocomplete="off"
              placeholder="AGE-SECRET-KEY-1…" data-restore-key></textarea>
    <input type="file" accept=".txt,text/plain" hidden data-restore-keyfile>
    <button class="link inline" type="button" data-restore-keypick>%t.rs_key_file%</button>
    <p class="error" role="alert" data-error hidden></p>
    <div class="actions">
      <button type="button" data-restore-cancel>%t.cancel%</button>
      <button class="primary" type="button" data-restore-check>%t.rs_check%</button>
    </div>
  </div>
  <div data-step="checking" hidden>
    <p class="muted" role="status">%t.rs_checking%<span class="loading-dots" aria-hidden="true"><i></i><i></i><i></i></span></p>
  </div>
  <div data-step="summary" hidden>
    <h3 class="rs-head">%t.rs_found%</h3>
    <dl class="rs-facts">
      <dt>%t.rs_created%</dt><dd data-fact="created"></dd>
      <dt>%t.rs_owner%</dt><dd data-fact="owner"></dd>
      <dt>%t.rs_accounts%</dt><dd data-fact="users"></dd>
      <dt>%t.rs_projects%</dt><dd data-fact="projects"></dd>
      <dt>%t.rs_files%</dt><dd data-fact="files"></dd>
      <dt>%t.rs_size%</dt><dd data-fact="size"></dd>
    </dl>
    <p class="muted rs-warn">%t.rs_replace_warn%</p>
    <p class="muted rs-warn" data-restore-tunnel hidden>%t.rs_tunnel_warn%</p>
    %PASSWORD%
    <p class="error" role="alert" data-error hidden></p>
    <div class="actions">
      <button type="button" data-restore-cancel>%t.cancel%</button>
      <button class="danger-btn" type="button" data-restore-apply>%t.rs_apply%</button>
    </div>
  </div>
  <div data-step="applying" hidden>
    <p class="muted" role="status">%t.rs_applying%<span class="loading-dots" aria-hidden="true"><i></i><i></i><i></i></span></p>
  </div>
  <div data-step="done" hidden>
    <p class="muted">%t.rs_done%</p>
    <a class="primary" href="/login">%t.rs_login%</a>
  </div>
  <div data-step="failed" hidden>
    <p class="error" role="alert" data-restore-why></p>
    <button class="primary" type="button" data-restore-again>%t.rs_again%</button>
  </div>
</div>"""


def restore_part(lang: str, owner: bool) -> str:
    """Putting a backup back. In the administration the owner confirms with his password; in the set-up there is no
    account yet."""
    password = "" if not owner else (
        f'<label>{esc(i18n.t(lang, "your_password"))}<input type="password" name="confirm" '
        f'autocomplete="current-password" data-restore-password></label>')
    return fill(RESTORE, lang, OWNER="1" if owner else "0", PASSWORD=password, DE="1" if lang == "de" else "0")


DIALOG = """<dialog class="dialog wide" id="backup-dialog">
  <h2>%t.bk_title%</h2>
  <div class="bk-grid">
    <section class="bk-col">
      <h3 class="link-head">%t.bk_key%</h3>
      %KEY%
      <div class="bk-line">%HOUR%%NOW%</div>
      <h3 class="link-head">%t.bk_list%</h3>
      <ul class="bk-list" id="backup-list" data-url="/backup/state">%LIST%</ul>
      <p class="error" role="alert" data-download-error hidden></p>
      <div class="bk-download" data-download hidden data-url="/backup/download">
        <p class="muted">%t.bk_download_text%</p>
        <label>%t.your_password%<input type="password" name="confirm" autocomplete="current-password" data-download-password></label>
        <div class="actions">
          <button type="button" data-download-cancel>%t.cancel%</button>
          <button class="primary" type="button" data-download-go>%t.bk_download%</button>
        </div>
      </div>
    </section>
    <section class="bk-col bk-restore">
      <h3 class="link-head">%t.rs_title%</h3>
      %RESTORE%
    </section>
  </div>
  <div class="actions"><button type="button" data-close>%t.close%</button></div>
</dialog>"""


def dialog(lang: str, owner: bool) -> str:
    """The whole backup in one dialog of the administration. The key and putting a backup back are the owner's; a
    superadmin sees the hour, "back up now" and the list."""
    return fill(DIALOG, lang, KEY=key_part(lang) if owner else "", HOUR=hour_field(lang),
                NOW=now_part(lang), LIST=list_rows(lang),
                RESTORE=restore_part(lang, True) if owner else "")


def now_part(lang: str) -> str:
    """ "Back up now"; a backup that runs already (also the nightly one) shows at once and is followed (backup.js)."""
    return fill(NOW, lang, ACTIVE="1" if hostjobs.state(action="backup")["state"] in ("waiting", "running") else "")


def job_text(lang: str) -> dict:
    """The newest backup job for the page: {"state", "text"}."""
    job = hostjobs.state(action="backup")
    if job["state"] in ("waiting", "running"):
        return {"state": "running", "text": i18n.t(lang, "bk_running")}
    if job["state"] == "ok":
        return {"state": "ok", "text": i18n.t(lang, "bk_ok", size=size_text(lang, int(job["detail"].get("size", 0))))}
    if job["state"] == "failed":
        reason = job["detail"].get("reason")
        return {"state": "failed", "text": i18n.t(lang, "bk_failed_no_key" if reason == "no_key" else "bk_failed")}
    return {"state": "none", "text": ""}
