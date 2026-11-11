"""HTML of the Manager view: the second view of the project page (station "Manager").

Janis, 07.11.2026: a click on "Manager" hides the board; the stations on the left stay and the main
window shows the manager's things. Layout from his sketch, three columns. Left: the status and the
devices (tall). Middle: the regular checks and the files (they take the free space). Right, where the
old chat window used to sit: the manager chat (big) above "waiting for you". The project name and
description are not here but in the drop-down at the pencil next to the title (projectpage.title_html).
The manager chat works (chat.py); status and "waiting for you" are empty, devices, checks and files announced.
"""
import time

from . import checks, i18n
from .icons import icon
from .layout import esc, fill

MANAGER = """<section class="manager" id="manager-view" aria-label="%t.station_manager%" hidden>
  <div class="mcol">
    <section class="mtile glass m-status">
      <header><h2>%t.manager_status%</h2><span class="m-lamp" title="%t.manager_status_none%"></span></header>
      <p class="muted">%t.manager_status_empty%</p>
    </section>
    %DEVICES%
  </div>
  <div class="mcol">
    %CHECKS%
    %FILES%
  </div>
  <div class="mcol">
    %CHAT%
    <section class="mtile glass m-waiting">
      <header><h2>%t.manager_waiting%</h2>%AUTONOMY%<span class="count">0</span></header>
      <p class="muted">%t.manager_waiting_empty%</p>
    </section>
  </div>
</section>"""


# The manager chat (web/app/chat.py, static/chat.js): it replaced the slim single-question window at the right
# edge. Web search and code are always there (no switches, Janis 07.11.2026); the model drop-down is a setting of
# the manager, so it holds for everything the manager does (static/manager.js saves it).
CHAT = """<section class="mtile glass m-chat" id="chat" data-you="%t.chat_you%" data-claude="%t.station_manager%"
             data-waiting="%t.chat_waiting%" data-failed="%t.chat_failed%">
      <header><h2>%t.manager_chat%</h2>%MODEL%</header>
      <div class="m-chat-sub"><p class="muted">%t.manager_chat_hint%</p>%NET%</div>
      <ol class="chat-log" id="chat-log" aria-live="polite"></ol>
      <p class="error" id="chat-error" role="alert" hidden></p>
      <form class="chat-form" id="chat-form" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
        <label><input name="prompt" required maxlength="2000" autocomplete="off" placeholder="%t.chat_placeholder%"></label>
        <button type="submit" id="chat-send">%t.chat_send%</button>
      </form>
    </section>"""

MODELS = (("haiku", "model_haiku"), ("sonnet", "model_sonnet"), ("opus", "model_opus"))
AUTONOMY = (("auto", "autonomy_auto"), ("major", "autonomy_major"), ("all", "autonomy_all"))


def _select(lang: str, name: str, label_key: str, options: tuple, current: str) -> str:
    """A setting of the manager as a drop-down in our own style (core.js `.has-select` builds the list)."""
    label = esc(i18n.t(lang, label_key))
    items = "".join(
        f'<option value="{value}"{" selected" if value == current else ""}>{esc(i18n.t(lang, key))}</option>'
        for value, key in options
    )
    return (
        f'<label class="m-select has-select"><select name="{name}" data-setting="{name}" id="manager-{name}" '
        f'aria-label="{label}">{items}</select>{icon("chevron_down")}</label>'   # no title: its tip would cover the list
    )


def _soon(lang: str, title: str, hint: str, css: str = "") -> str:
    """A tile that is announced but not built: title, one line, and the "later" tag."""
    later = esc(i18n.t(lang, "coming_soon"))
    return (
        f'<section class="mtile glass m-soon {css}"><header><h2>{esc(i18n.t(lang, title))}</h2>'
        f'<span class="m-tag">{later}</span></header>'
        f'<p class="muted">{esc(i18n.t(lang, hint))}</p></section>'
    )


CYCLES = (("daily", "cycle_daily"), ("weekly", "cycle_weekly"), ("monthly", "cycle_monthly"),
          ("quarterly", "cycle_quarterly"))

CHECK_DIALOGS = """<dialog class="dialog" id="check-dialog" data-title-new="%t.checks_new%" data-title-edit="%t.checks_edit%"
        data-btn-new="%t.create%" data-btn-edit="%t.save%">
  <form method="post" action="" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <h2 id="check-dialog-title">%t.checks_new%</h2>
    <label>%t.checks_text%<input name="text" required maxlength="%MAX_TEXT%" autocomplete="off" placeholder="%t.checks_placeholder%"></label>
    <label class="setting has-select">
      <span class="setting-label">%t.checks_cycle%</span>
      <select name="cycle">%CYCLES%</select>
      %CHEVRON%
    </label>
    <div class="setting check-days" id="check-days" role="group" aria-label="%t.checks_days%">
      <span class="setting-label">%t.checks_days%</span>
      <div class="check-days-row">%DAYS%</div>
    </div>
    <p class="error" role="alert" id="check-days-error" hidden>%t.checks_days_none%</p>
    <button class="link" type="button" id="check-dialog-done" hidden>%t.checks_mark_done%</button>
    <div class="actions">
      <button type="button" data-close>%t.cancel%</button>
      <button class="primary" type="submit" id="check-dialog-button">%t.create%</button>
    </div>
  </form>
</dialog>
<dialog class="dialog danger" id="check-confirm">
  <h2>%t.checks_confirm_delete%</h2>
  <div class="actions">
    <button type="button" data-close autofocus>%t.cancel%</button>
    <button class="danger-btn" type="button" id="check-confirm-yes">%t.yes%</button>
  </div>
</dialog>"""


def dialogs(lang: str) -> str:
    """The dialogs of the Manager view. They sit outside the view: a modal dialog inside a hidden element
    would not show (projectpage puts them next to the other dialogs)."""
    options = "".join(
        f'<option value="{value}">{esc(i18n.t(lang, key))}</option>' for value, key in CYCLES
    )
    days = "".join(   # seven circles with two letters; the box is hidden and the circle shows the state
        f'<label class="check-day"><input type="checkbox" name="day" value="{n}" checked '
        f'aria-label="{esc(i18n.t(lang, f"day_full_{n}"))}">'
        f'<span aria-hidden="true">{esc(i18n.t(lang, f"day_short_{n}"))}</span></label>'
        for n in range(7)
    )
    return fill(CHECK_DIALOGS, lang, MAX_TEXT=str(checks.MAX_TEXT), CYCLES=options, DAYS=days,
                CHEVRON=icon("chevron_down"))


def _ago(lang: str, last_done: int, now: int) -> str:
    days = max(0, (now - last_done) // checks.DAY)
    if days == 0:
        return i18n.t(lang, "checks_done_today")
    if days == 1:
        return i18n.t(lang, "checks_done_yesterday")
    return i18n.t(lang, "checks_done_days", n=days)


def _check_row(lang: str, check: checks.Check, now: int) -> str:
    cycle = i18n.t(lang, "cycle_" + check.cycle)
    if check.cycle == "daily" and check.days != checks.ALL_DAYS:   # "Mo, Mi, Fr" instead of "Täglich"
        cycle = ", ".join(i18n.t(lang, f"day_short_{n}") for n in checks.day_numbers(check.days))
    due = check.is_due(now)
    state = i18n.t(lang, "checks_due") if due else _ago(lang, check.last_done, now)
    edit_label = esc(i18n.t(lang, "checks_edit"))
    delete_label = esc(i18n.t(lang, "checks_delete"))
    flag = " due" if due else ""
    return (
        f'<li class="check-row{flag}" data-id="{check.id}" data-cycle="{check.cycle}" data-days="{check.days}">'
        f'<span class="check-text"><span class="check-title">{esc(check.text)}</span>'
        f'<small>{esc(cycle)} · {esc(state)}</small></span>'
        f'<button class="icon-button card-btn" type="button" data-check="edit" aria-label="{edit_label}" '
        f'title="{edit_label}">{icon("pencil")}</button>'
        f'<button class="icon-button card-btn no" type="button" data-check="delete" aria-label="{delete_label}" '
        f'title="{delete_label}">{icon("trash")}</button></li>'
    )


def _checks_tile(lang: str, regular: list, now: int) -> str:
    """The regular checks: a list with the plus in the header (Janis, 07.11.2026); due ones are marked."""
    add = esc(i18n.t(lang, "checks_add"))
    if regular:
        body = f'<ul class="check-list">{"".join(_check_row(lang, c, now) for c in regular)}</ul>'
    else:
        body = f'<p class="muted">{esc(i18n.t(lang, "manager_checks_hint"))}</p>'
    return (
        f'<section class="mtile glass m-checks" id="checks"><header><h2>{esc(i18n.t(lang, "manager_checks"))}</h2>'
        f'<span class="count">{len(regular)}</span>'
        f'<button class="icon-button m-add" id="check-add" type="button" aria-label="{add}" title="{add}">'
        f'{icon("plus")}</button></header>{body}</section>'
    )


def _net_switch(lang: str, current: str) -> str:
    """The switch "web and code together" (on: code has the open internet; off: web search, code offline)."""
    label = esc(i18n.t(lang, "net_together"))
    checked = " checked" if current == "together" else ""
    return (
        f'<label class="m-switch"><input type="checkbox" role="switch" id="manager-net" data-setting="net" '
        f'data-on="together" data-off="apart"{checked}><span class="m-switch-track" aria-hidden="true"></span>'
        f'<span class="m-switch-label">{label}</span></label>'
    )


def render(lang: str, settings: dict, regular_checks: list | None = None, now: int | None = None) -> str:
    """`settings` is agents.settings(user_id): the manager is the role "chef". `regular_checks` are the
    project's checks (checks.list_checks)."""
    model = _select(lang, "model", "chat_model", MODELS, settings["roles"]["chef"]["model"])
    autonomy = _select(lang, "autonomy", "autonomy", AUTONOMY, settings["autonomy"])
    return fill(
        MANAGER,
        lang,
        DEVICES=_soon(lang, "manager_devices", "manager_devices_hint", "m-grow"),
        CHECKS=_checks_tile(lang, regular_checks or [], int(now if now is not None else time.time())),
        FILES=_soon(lang, "manager_files", "manager_files_hint", "m-grow"),
        CHAT=fill(CHAT, lang, MODEL=model, NET=_net_switch(lang, settings["roles"]["chef"]["net"])),
        AUTONOMY=autonomy,
    )
