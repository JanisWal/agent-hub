"""HTML of the owner's system page."""
from html import escape as esc

from . import db, i18n, netaddresses, serversettings, sysstats, users
from .icons import icon
from .layout import fill
from .ui import info_dot
from .users import User


def _upload_field(lang: str, name: str, label_key: str, choices: tuple, current: int, unit: str,
                  zero: str = "", text=None) -> str:
    """One choice of the server settings: a compact drop-down in our own style (core.js `.has-select`). `zero` is the
    text of the value 0 ("no limit"); `text` names a value itself (sizes in MB or GB, on and off)."""
    label = esc(i18n.t(lang, label_key))
    def shown(value: int) -> str:
        if text is not None:
            return esc(text(value))
        return esc(zero) if value == 0 and zero else f"{value}{unit}"
    options = "".join(f'<option value="{value}"{" selected" if value == current else ""}>{shown(value)}</option>'
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
    %STATS%
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
    %LIMITS%
    %ADDRESSES%
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
</dialog>
%ADDRESS_DIALOG%"""

# Addresses in the server's network that further AIs may use (netaddresses.py, Janis 21.11.2026): a list and a form to
# add one, in a dialog behind the row "Freigegebene Adressen" (system.js). Only the owner sees both.
ADDRESS_DIALOG = """<dialog class="dialog wide" id="addresses-dialog">
  <h2>%t.sys_addresses%</h2>
  <p class="muted">%t.addr_text%</p>
  <ul class="addr-list" id="addr-list">%LIST%</ul>
  <form id="addr-form" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%"
        data-address="%t.addr_bad%" data-user="%t.addr_bad_user%" data-full="%t.addr_full%" data-failed="%t.err_network%">
    <div class="addr-fields">
      <label class="setting"><span class="setting-label">%t.addr_address%</span><input type="text" name="address" required maxlength="260" placeholder="192.168.1.20:11434" autocomplete="off" spellcheck="false"></label>
      <label class="setting has-select"><span class="setting-label">%t.addr_for%</span><select name="user">%USERS%</select>%CHEVRON%</label>
      <label class="setting"><span class="setting-label">%t.addr_note%</span><input type="text" name="note" maxlength="60" autocomplete="off" placeholder="%t.addr_note_hint%"></label>
    </div>
    <p class="error" role="alert" data-error hidden></p>
    <div class="actions">
      <button type="button" data-close>%t.close%</button>
      <button class="primary" type="submit">%t.addr_add%</button>
    </div>
  </form>
</dialog>"""


def _gb(lang: str, value: float) -> str:
    text = f"{value:.1f}"
    return text.replace(".", ",") if lang == "de" else text


def _level(pct: float, warn: float, high: float) -> str:
    return "high" if pct >= high else "warn" if pct >= warn else "ok"


def meters(lang: str, stats: dict) -> list[dict]:
    """The live numbers as the page shows them (Janis, 23.11.2026), texts in the user's language: [{"key", "label",
    "pct" (how full the bar is), "text", "level" (ok / warn / high)}]. The same list draws the first view and answers
    /system/stats, so a number is never formatted in two places. Temperature has no total: its bar is the share of 85 °C,
    where the Raspberry Pi slows itself down; a value the machine does not tell is left out."""
    t = lambda key, **kw: i18n.t(lang, key, **kw)   # noqa: E731
    mem, cpu, temp, disk = stats["memory"], stats["cpu"], stats["temp_c"], stats["disk"]
    rows = [
        {"key": "memory", "label": t("sys_stat_memory"), "pct": mem["used_pct"], "level": _level(mem["used_pct"], 80, 92),
         "text": t("sys_stat_free_of", free=_size(mem["free_mb"]), total=_size(mem["total_mb"]))},
        {"key": "cpu", "label": t("sys_stat_cpu"), "pct": cpu["used_pct"], "level": _level(cpu["used_pct"], 75, 90),
         "text": t("sys_stat_busy", pct=cpu["used_pct"], cores=cpu["cores"])},
    ]
    if temp is not None:
        rows.append({"key": "temp", "label": t("sys_stat_temp"), "pct": min(100, round(100 * temp / 85)),
                     "level": _level(temp, 70, 80), "text": f"{temp:.0f} °C"})
    if disk is not None:
        rows.append({"key": "disk", "label": t("sys_stat_disk"), "pct": disk["used_pct"],
                     "level": _level(disk["used_pct"], 80, 92),
                     "text": t("sys_stat_free_of", free=_gb(lang, disk["free_gb"]) + " GB",
                               total=_gb(lang, disk["total_gb"]) + " GB")})
    return rows


def _stats(lang: str) -> str:
    """The row of live numbers at the top of the system block (static/system.js keeps it current)."""
    cells = "".join(
        f'<div class="sys-meter" data-key="{m["key"]}" data-level="{m["level"]}" data-pct="{m["pct"]}">'
        f'<span class="sys-label">{esc(m["label"])}</span><span class="sys-val">{esc(m["text"])}</span>'
        f'<div class="sys-bar"><i></i></div></div>' for m in meters(lang, sysstats.read()))
    return f'<div class="sys-row sys-stats" id="sys-stats" data-url="/system/stats">{cells}</div>'


def _size(mb: int) -> str:
    return f"{mb // 1024} GB" if mb >= 1024 and mb % 1024 == 0 else (f"{mb / 1000:g} GB" if mb >= 1000 else f"{mb} MB")


# The settings a small server needs and a big one does not (serversettings.CHOICES, Janis 21.11.2026): one row per pair,
# like "Upload" and "AI runs"; all go to /system/limits, saved as soon as a choice changes (system.js).
LIMIT_ROWS = (
    ("sys_run", (("run_memory_mb", "sys_run_memory", "size"), ("run_cpus", "sys_run_cpus", ""))),
    ("sys_run_more", (("run_pids", "sys_run_pids", ""), ("view_mb", "sys_run_files", "size"))),
    ("sys_times", (("run_silence_minutes", "sys_time_silence", "min"), ("run_max_hours", "sys_time_max", "h"))),
    ("sys_times_more", (("test_minutes", "sys_time_tests", "min"), ("chat_minutes", "sys_time_chat", "min"))),
    ("sys_tools", (("agent_browser", "sys_browser", "onoff"), ("export_mb", "sys_export", "size"))),
    ("sys_rest", (("ai_rest", "sys_rest_short", "min0"),)),
)


def _limit_rows(lang: str) -> str:
    t = lambda key, **kw: i18n.t(lang, key, **kw)   # noqa: E731
    texts = {"size": _size, "min": lambda v: f"{v} min", "h": lambda v: f"{v} h", "": str,
             "onoff": lambda v: t("sys_on") if v else t("sys_off"),
             "min0": lambda v: f"{v} min" if v else t("sys_rest_never")}
    rows = []
    for row_key, fields in LIMIT_ROWS:
        html = "".join(_upload_field(lang, key, label, serversettings.CHOICES[key], serversettings.get(key), "",
                                     text=texts[kind]) for key, label, kind in fields)
        rows.append(f'<div class="sys-row sys-upload" data-url="/system/limits"><span class="sys-name">'
                    f'{esc(t(row_key))}</span><div class="sys-fields">{html}</div>'
                    f'{info_dot(t(row_key), t(row_key + "_info"))}</div>')
    return "\n    ".join(rows)


def address_list(lang: str) -> str:
    """The rows of the list (sent again after each change): address, for whom, note, "remove"."""
    with db.connect() as conn:
        items = netaddresses.entries(conn)
    if not items:
        return f'<li class="addr-empty muted">{esc(i18n.t(lang, "addr_empty"))}</li>'
    rows = []
    for item in items:
        who = item["email"] or i18n.t(lang, "addr_all")
        note = f'<span class="addr-note">{esc(item["note"])}</span>' if item["note"] else ""
        rows.append(f'<li class="addr-row"><code class="addr-host">{esc(item["host"])}:{item["port"]}</code>'
                    f'<span class="addr-who">{esc(who)}</span>{note}'
                    f'<button class="link" type="button" data-addr-remove="{item["id"]}">'
                    f'{esc(i18n.t(lang, "addr_remove"))}</button></li>')
    return "".join(rows)


def _addresses(user: User) -> tuple[str, str]:
    """Row and dialog of the listed addresses: only the owner (it opens his server's network; a superadmin does not
    see it)."""
    if user.role != "owner":
        return "", ""
    lang = user.language
    accounts = "".join(f'<option value="{u.id}">{esc(u.email)}</option>' for u in users.list_users(user))
    options = f'<option value="">{esc(i18n.t(lang, "addr_all"))}</option>{accounts}'
    dialog = fill(ADDRESS_DIALOG, lang, LIST=address_list(lang), USERS=options, CHEVRON=icon("chevron_down"))
    return _action(lang, "sys_addresses", "data-addresses"), dialog


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
    row, dialog = _addresses(user)
    return fill(SYSTEM, lang, STATS=_stats(lang), UPLOAD_FIELDS=fields, ADDRESSES=row, ADDRESS_DIALOG=dialog, LIMITS=_limit_rows(lang),
                UPLOAD_INFO=info_dot(t("sys_upload"), upload_info),
                AI_FIELD=ai_field, AI_INFO=info_dot(t("sys_ai"), t("sys_ai_info")),
                BACKUP=_action(lang, "sys_backup", "data-backup"),
                SKINS=_action(lang, "sys_skins", "disabled", info=False),   # placeholder (Janis, 18.11.2026): comes later
                REBOOT=_action(lang, "sys_reboot", 'data-power="reboot"'),
                POWEROFF=_action(lang, "sys_poweroff", 'data-power="poweroff"'))
