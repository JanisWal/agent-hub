"""HTML of the role views of the project page: Programmer, Tester, Reviewer and "For you" (Janis, 15.11.2026: a first
version to work with; what exactly belongs there is decided later, PROJEKT.md 11a, Stufe 2).

A role view has two columns. Left: "Right now" (what the role is doing in this project, with its settings in the head:
code with internet, model and level) and its usage. Right: its runs, newest first, each with its report.
"For you" (Janis, 16.11.2026) is the user's own work list (todos.py): what he does himself, physically or technically,
and what he did. Decisions wait in the Manager view ("waiting for you", managerpage.py), not here.

Only data of the page's user is shown: the lists come from agents.role_runs and todos.list_todos, which check the
project. Parts that change during a run carry ids, so static/roles.js can swap them (AgentHub.swap) without a reload.
"""
import time

from . import agents, catalog, i18n, todos, ui
from .icons import icon
from .layout import esc, fill

ROLES = ("programmer", "tester", "reviewer")
VIEWS = ROLES + ("me",)
LIVE = ("queued", "running")          # runs shown under "Right now"; roles.js refreshes faster while there are any
MAX_REPORT_SHOWN = 8000               # characters of a report shown in a run row
MAX_THOUGHTS_SHOWN = 4000             # the newest characters of a run's thoughts shown
STAGE_OF = {"programmer": "coding", "tester": "testing", "reviewer": "reviewing"}


def _duration(lang: str, seconds: int) -> str:
    seconds = max(0, int(seconds))
    if seconds < 90:
        return i18n.t(lang, "dur_seconds", n=seconds)
    if seconds < 90 * 60:
        return i18n.t(lang, "dur_minutes", n=round(seconds / 60))
    return i18n.t(lang, "dur_hours", n=round(seconds / 3600, 1))


def _ago(lang: str, then: int | None, now: int) -> str:
    if not then:
        return ""
    return i18n.t(lang, "just_now") if now - then < 60 else i18n.t(lang, "ago", time=_duration(lang, now - then))


def _tokens(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def _result(lang: str, item: agents.RoleRun) -> tuple[str, str]:
    """(label, tone) of a run: its result when it is over, else its state. Tone: go, stop or quiet (project.css)."""
    run = item.run
    if run.status in ("queued", "running", "cancelled"):
        return i18n.t(lang, f"run_{run.status}"), "quiet"
    result = run.result or "failed"
    tone = "go" if result in ("done", "pass", "ok") else "stop" if result in ("failed", "fail", "objections") else "quiet"
    return i18n.t(lang, f"result_{result}"), tone


def _run_row(lang: str, item: agents.RoleRun, now: int) -> str:
    run = item.run
    label, tone = _result(lang, item)
    facts = [_ago(lang, item.finished_at or item.started_at or item.created_at, now)]
    if run.seconds:
        facts.append(_duration(lang, run.seconds))
    if run.tokens_in or run.tokens_out:
        facts.append(i18n.t(lang, "role_tokens", tin=_tokens(run.tokens_in), tout=_tokens(run.tokens_out)))
    found = catalog.find(run.model)
    model = "" if found and found[0].id == "custom" else (found[1].name if found else run.model)   # own AI: its name says it
    facts.append(" ".join(x for x in (ui.ai_name(lang, item.provider) if item.provider else "", model) if x))
    head = (f'<summary><span class="r-title">{esc(item.task_title)}</span>'
            f'<span class="r-result {tone}">{esc(label)}</span>'
            f'<small class="r-facts">{esc(" · ".join(f for f in facts if f))}</small></summary>')
    report = run.report[:MAX_REPORT_SHOWN].strip()
    body = (f'<div class="r-report">{esc(report)}</div>' if report
            else f'<p class="muted r-report">{esc(i18n.t(lang, "role_no_report"))}</p>')
    return f'<li><details class="r-run">{head}{body}</details></li>'


def _cancel(lang: str, task) -> str:
    label = esc(i18n.t(lang, "task_cancel"))
    return f'<button class="sq-btn stop r-cancel" type="button" data-cancel-task="{task.id}">{label}</button>'


def _thoughts(lang: str, run) -> str:
    """What the AI of a run wrote meanwhile (only shown, never context), the newest part."""
    text = (run.thoughts or "").strip()
    if not text:
        return ""
    return f'<pre class="r-thoughts">{esc(text[-MAX_THOUGHTS_SHOWN:])}</pre>'


def _now(lang: str, role: str, runs: list[agents.RoleRun], now: int, where=None) -> str:
    """What the role does in this project now: its running run (with its thoughts) or the one that waits, else where the
    project's task stands when it is with this role (waiting for an answer, for the user, for a decision), else where
    it is (it wanders programmer -> tester -> reviewer, Janis 22.11.2026) or nothing."""
    live = [r for r in runs if r.run.status in LIVE and r.run.purpose in ("work", "result")]
    mine = where is not None and where[0].stage == STAGE_OF.get(role)
    lines = []
    for item in reversed(live):     # oldest first
        if item.run.status == "running":
            text = i18n.t(lang, "role_running", title=item.task_title, time=_duration(lang, now - (item.started_at or now)))
            paused = where is not None and where[1] == "paused"
            lines.append(f'<p class="r-now {"paused" if paused else "running"}"><span class="r-dot" aria-hidden="true">'
                         f'</span>{esc(text)}{(" · " + esc(i18n.t(lang, "role_paused"))) if paused else ""}</p>'
                         + ("" if role == "programmer" else _thoughts(lang, item.run)))   # his have their own tile
        else:
            lines.append(f'<p class="r-now queued"><span class="r-dot" aria-hidden="true"></span>'
                         f'{esc(i18n.t(lang, "role_queued", title=item.task_title))}</p>')
    if not lines and where is not None:
        task, state = where
        role_name = i18n.t(lang, f"station_{workflow_role(task.stage)}")
        lines.append(f'<p class="r-now idle"><span class="r-dot" aria-hidden="true"></span>'
                     f'{esc(i18n.t(lang, "bs_" + state, role=role_name, title=task.title))}</p>')
    if not lines:
        return f'<p class="muted">{esc(i18n.t(lang, "role_idle"))}</p>'
    if mine and role != "programmer":                  # the programmer's task tile has it already
        lines.append(f'<div class="r-actions">{_cancel(lang, where[0])}</div>')
    return "".join(lines)


def workflow_role(stage: str) -> str:
    return {"coding": "programmer", "testing": "tester", "reviewing": "reviewer"}.get(stage, "manager")


def _usage(lang: str, usage: dict) -> str:
    if not usage.get("runs"):
        return f'<p class="muted">{esc(i18n.t(lang, "role_usage_none"))}</p>'
    line = i18n.t(lang, "role_usage_line", runs=usage["runs"], tin=_tokens(usage["tokens_in"]),
                  tout=_tokens(usage["tokens_out"]), time=_duration(lang, usage["seconds"]))
    return f"<p>{esc(line)}</p>"


def _net_pill(lang: str, role: str, current: str) -> str:
    """The same round globe button as the manager's (managerpage._net_switch), for this role."""
    label, tip = esc(i18n.t(lang, "net_together")), esc(i18n.t(lang, "net_together_tip"))
    pressed = "true" if current == "together" else "false"
    return (f'<button type="button" class="m-pill m-globe" id="role-{role}-net" data-setting="net" data-on="together" '
            f'data-off="apart" aria-pressed="{pressed}" aria-label="{label}" data-tip="{label}. {tip}">{icon("globe")}</button>')


def _soon(lang: str, title_key: str, hint_key: str, body: str, css: str = "") -> str:
    """A tile that is only a placeholder yet (Janis, 19.11.2026: all parts in, to get a feeling): its title, an "i"
    with what it will do, the mark "coming later" and an example of its content, greyed and not usable."""
    title = i18n.t(lang, title_key)
    return (f'<section class="mtile glass p-soon {css}"><header><h2>{esc(title)}</h2>'
            f'{ui.info_dot(title, i18n.t(lang, hint_key))}<span class="p-badge">{esc(i18n.t(lang, "coming_soon"))}</span>'
            f'</header><div class="p-sample" aria-hidden="true">{body}</div></section>')


def _soon_button(lang: str, key: str) -> str:
    label = esc(i18n.t(lang, key))
    return f'<button class="pill-btn quiet" type="button" disabled data-tip="{esc(i18n.t(lang, "coming_soon"))}">{label}</button>'


def _ai_pills(lang: str, role: str, active: str, ais: tuple[str, ...]) -> str:
    """The AIs of the role (Janis, 22.11.2026): the connected ones first, in their rank (aichoice.ranked, as in the
    drawer), as buttons that choose the role's AI; the one it uses is marked. Then the ones not connected, dashed and
    not clickable. One line that scrolls sideways (wheel, the side wheel of a mouse, or dragging: static/hscroll.js)."""
    connected = [p for p in ais if p in catalog.PROVIDERS]
    pills = "".join(
        f'<button class="p-ai{" on" if p == active else ""}" type="button" data-role-ai="{p}" data-role="{role}" '
        f'aria-pressed="{"true" if p == active else "false"}">{esc(ui.ai_name(lang, p))}</button>' for p in connected)
    rest = "".join(f'<span class="p-ai off">{esc(ui.ai_name(lang, p))}</span>'
                   for p in catalog.PROVIDERS if p not in connected)
    return pills + rest + f'<span class="p-ai off">{esc(i18n.t(lang, "p_more_ais"))}</span>'


def _code_tile(lang: str, current) -> str:
    """The project's code to download and try oneself (Janis, 21.11.2026): the merged state, and the state of the task
    being worked on (its branch). The runner makes the ZIP (exports.py, static/export.js); a note says how it goes."""
    title = i18n.t(lang, "p_code")
    t = lambda key: esc(i18n.t(lang, key))   # noqa: E731
    task = (f'<button type="button" data-export="{current[0].id}">{t("p_export_task")}</button>'
            if current is not None else "")
    return (f'<section class="mtile glass p-code"><header><h2>{esc(title)}</h2>'
            f'{ui.info_dot(title, i18n.t(lang, "p_code_hint"))}</header>'
            f'<div class="p-export"><button type="button" data-export="">{t("p_export_main")}</button>{task}</div>'
            f'<p class="p-export-note muted" role="status" data-export-note hidden data-wait="{t("p_export_wait")}" '
            f'data-failed="{t("p_export_failed")}"></p></section>')


def _task_tile(lang: str, current, where=None) -> str:
    """The task on its way and the context behind it, read only (tasks are given to the manager, who puts them on the
    board; here you follow them), with where it stands and "cancel"."""
    head = f'<header><h2>{esc(i18n.t(lang, "p_task"))}</h2>{ui.info_dot(i18n.t(lang, "p_task"), i18n.t(lang, "p_task_hint"))}</header>'
    if current is None:
        return (f'<section class="mtile glass p-task" id="role-programmer-task">{head}'
                f'<p class="muted">{esc(i18n.t(lang, "p_task_none"))}</p></section>')
    task, details = current
    state = where[1] if where is not None and where[0].id == task.id else "queued"
    facts = [i18n.t(lang, "bs_" + state, role=i18n.t(lang, f"station_{workflow_role(task.stage)}"), title=task.title)]
    if task.returns:
        facts.append(i18n.t(lang, "p_returns", n=task.returns))
    hint = (f'<p class="p-note"><strong>{esc(i18n.t(lang, "p_hint"))}:</strong> {esc(task.hint)}</p>' if task.hint else "")
    context = (f'<div class="p-context">{esc(details)}</div>' if details
               else f'<p class="muted">{esc(i18n.t(lang, "p_context_none"))}</p>')
    return (f'<section class="mtile glass p-task" id="role-programmer-task">{head}<p class="p-title">{esc(task.title)}</p>'
            f'<small class="p-facts">{esc(" · ".join(facts))}</small>{hint}{context}'
            f'<div class="r-actions">{_cancel(lang, task)}</div></section>')


def _trail(lang: str, runs: list[agents.RoleRun]) -> str:
    """The programmer's thoughts and steps (list item 3b, Janis 16.11.2026): of his running run, else of his last one."""
    title = i18n.t(lang, "p_trail")
    run = next((r.run for r in runs if r.run.status == "running" and r.run.purpose == "work"), None) \
        or next((r.run for r in runs if r.run.purpose == "work" and r.run.thoughts), None)
    body = (_thoughts(lang, run) if run is not None else "") \
        or f'<p class="muted">{esc(i18n.t(lang, "p_trail_empty"))}</p>'
    return (f'<section class="mtile glass m-grow p-trail-tile"><header><h2>{esc(title)}</h2>'
            f'{ui.info_dot(title, i18n.t(lang, "p_trail_hint"))}</header>'
            f'<div class="r-scroll" id="role-programmer-trail">{body}</div></section>')


def _focus_tile(lang: str, focus: str) -> str:
    """What the reviewer looks at in this project (Janis, 22.11.2026), saved as it is typed (roles.js)."""
    title = i18n.t(lang, "r_focus")
    return (f'<section class="mtile glass r-focus"><header><h2>{esc(title)}</h2>'
            f'{ui.info_dot(title, i18n.t(lang, "r_focus_hint"))}</header>'
            f'<textarea class="field-text" id="review-focus" rows="3" maxlength="{agents.MAX_FOCUS}" '
            f'placeholder="{esc(i18n.t(lang, "r_focus_placeholder"))}" aria-label="{esc(title)}">{esc(focus)}</textarea>'
            f'<p class="muted r-focus-state" id="review-focus-state" role="status" data-saved="{esc(i18n.t(lang, "r_focus_saved"))}">'
            f'</p></section>')


def _programmer(lang: str, settings: dict, runs: list[agents.RoleRun], usage: dict, ais: tuple[str, ...], now: int,
                current, where=None) -> str:
    """The programmer's tab as the documentation wants it (PROJEKT.md 11a, list items 3a, 3b, 3c, 3f and 4; Janis
    19.11.2026: every part in, what does not work yet as a placeholder): left what he does now with his settings and
    the task with its context, then the usage; in the middle the trail of his thoughts and steps and the preview; right
    the project's code, the changes for the approval and his runs."""
    mine = settings["roles"]["programmer"]
    picker = ui.model_picker(lang, "role-programmer", mine["model"], mine.get("effort", ""), providers=(mine["provider"],),
                             allowed=settings.get("models"), names=settings.get("model_names"))
    tools = f'<span class="m-chat-tools">{_net_pill(lang, "programmer", mine["net"])}{picker}</span>'
    name = i18n.t(lang, "station_programmer")
    listed = "".join(_run_row(lang, r, now) for r in runs)
    runs_html = (f'<ol class="r-runs">{listed}</ol>' if listed
                 else f'<p class="muted">{esc(i18n.t(lang, "role_runs_empty"))}</p>')
    others = _ai_pills(lang, "programmer", mine["provider"], ais)
    diff = ('<p class="p-stat"><span class="add">+12</span> <span class="del">−3</span> · '
            + esc(i18n.t(lang, "p_sample_files")) + '</p><pre class="p-diff"><span class="del">-    print(*primes)</span>\n'
            '<span class="add">+    print(", ".join(map(str, primes)))</span></pre>'
            f'<div class="p-row">{_soon_button(lang, "p_whole_diff")}</div>')
    preview = f'<div class="p-frame">{icon("photo")}<small>{esc(i18n.t(lang, "p_preview_empty"))}</small></div>'
    return (
        f'<section class="manager role-view p-view" id="view-programmer" data-view-panel="programmer" data-role="programmer" '
        f'data-settings-url="/roles/programmer/settings" aria-label="{esc(name)}" hidden>'
        f'<div class="mcol">'
        f'<section class="mtile glass r-head"><header><h2>{esc(i18n.t(lang, "role_now"))}</h2>'
        f'{ui.info_dot(name, i18n.t(lang, "role_hint_programmer"))}{tools}</header>'
        f'<div id="role-programmer-now">{_now(lang, "programmer", runs, now, where)}</div>'
        f'<div class="p-ais" data-hscroll><small>{esc(i18n.t(lang, "p_other_ais"))}</small>{others}</div></section>'
        f'{_task_tile(lang, current, where)}'
        f'<section class="mtile glass"><header><h2>{esc(i18n.t(lang, "role_usage"))}</h2></header>'
        f'<div id="role-programmer-usage">{_usage(lang, usage)}</div></section>'
        f'</div><div class="mcol">'
        f'{_trail(lang, runs)}'
        f'{_soon(lang, "p_preview", "p_preview_hint", preview)}'
        f'</div><div class="mcol">'
        f'{_code_tile(lang, current)}'
        f'{_soon(lang, "p_diff", "p_diff_hint", diff)}'
        f'<section class="mtile glass m-grow"><header><h2>{esc(i18n.t(lang, "role_runs"))}</h2>'
        f'<span class="count" id="role-programmer-count">{len(runs)}</span></header>'
        f'<div class="r-scroll" id="role-programmer-runs">{runs_html}</div></section>'
        f'</div></section>'
    )


def render_role(lang: str, role: str, settings: dict, runs: list[agents.RoleRun], usage: dict,
                ais: tuple[str, ...] = (catalog.DEFAULT_PROVIDER,), now: int | None = None, current=None, where=None,
                focus: str = "") -> str:
    """One role's view. `settings` is agents.settings(user_id); `runs` agents.role_runs(...) for this project;
    `current` agents.current_task(...), `where` agents.where(...) for this project; `focus` the reviewer's focus."""
    now = int(now if now is not None else time.time())
    if role == "programmer":
        return _programmer(lang, settings, runs, usage, ais, now, current, where)
    mine = settings["roles"][role]
    picker = ui.model_picker(lang, f"role-{role}", mine["model"], mine.get("effort", ""), providers=(mine["provider"],),
                             allowed=settings.get("models"), names=settings.get("model_names"))
    tools = f'<span class="m-chat-tools">{_net_pill(lang, role, mine["net"])}{picker}</span>'
    name = i18n.t(lang, f"station_{role}")
    listed = "".join(_run_row(lang, r, now) for r in runs)
    runs_html = (f'<ol class="r-runs">{listed}</ol>' if listed
                 else f'<p class="muted">{esc(i18n.t(lang, "role_runs_empty"))}</p>')
    return (
        f'<section class="manager role-view" id="view-{role}" data-view-panel="{role}" data-role="{role}" '
        f'data-settings-url="/roles/{role}/settings" aria-label="{esc(name)}" hidden>'
        f'<div class="mcol">'
        f'<section class="mtile glass r-head"><header><h2>{esc(i18n.t(lang, "role_now"))}</h2>'
        f'{ui.info_dot(name, i18n.t(lang, f"role_hint_{role}"))}{tools}</header>'
        f'<div id="role-{role}-now">{_now(lang, role, runs, now, where)}</div></section>'
        f'{_focus_tile(lang, focus) if role == "reviewer" else ""}'
        f'<section class="mtile glass"><header><h2>{esc(i18n.t(lang, "role_usage"))}</h2></header>'
        f'<div id="role-{role}-usage">{_usage(lang, usage)}</div></section>'
        f'</div><div class="mcol">'
        f'<section class="mtile glass"><header><h2>{esc(i18n.t(lang, "role_runs"))}</h2>'
        f'<span class="count" id="role-{role}-count">{len(runs)}</span></header>'
        f'<div class="r-scroll" id="role-{role}-runs">{runs_html}</div></section>'
        f'</div></section>'
    )


def _todo_button(lang: str, action: str, key: str, name: str, css: str = "") -> str:
    label = esc(i18n.t(lang, key))
    return (f'<button class="icon-button card-btn{css}" type="button" data-todo="{action}" aria-label="{label}" '
            f'title="{label}">{icon(name)}</button>')


def _todo_row(lang: str, todo: todos.Todo, now: int) -> str:
    """One entry. Open: done (with a note), change, delete. Done: its note, open again, change the note, delete."""
    if todo.done:
        when = i18n.t(lang, "todo_done_when", time=_ago(lang, todo.done_at, now))
        note = f'<span class="todo-note">{esc(todo.note)}</span>' if todo.note else ""
        buttons = (_todo_button(lang, "reopen", "todo_reopen", "undo")
                   + _todo_button(lang, "note", "todo_note_edit", "pencil"))
    else:
        when = _ago(lang, todo.created_at, now)
        note = ""
        buttons = (_todo_button(lang, "done", "todo_finish", "check", " yes")
                   + _todo_button(lang, "edit", "todo_edit", "pencil"))
    source = "" if todo.source == "user" else i18n.t(lang, f"todo_from_{todo.source}") + " · "
    return (
        f'<li class="check-row todo-row{" done" if todo.done else ""}" data-id="{todo.id}">'
        f'<span class="check-text"><span class="check-title">{esc(todo.text)}</span>'
        f'<small>{esc(source + when)}</small>{note}</span>'
        f'{buttons}{_todo_button(lang, "delete", "todo_delete", "trash", " no")}'
        f'<textarea class="todo-raw" hidden>{esc(todo.note)}</textarea></li>'
    )


def render_me(lang: str, entries: list[todos.Todo], now: int | None = None) -> str:
    """ "For you" (Janis, 16.11.2026): the work the user does himself. Open entries first, below them the done ones
    with what he did. Decisions are not here: they wait in the Manager view ("waiting for you")."""
    now = int(now if now is not None else time.time())
    open_ = [t for t in entries if not t.done]
    done = [t for t in entries if t.done]
    parts = []
    if open_:
        parts.append(f'<ul class="check-list todo-list">{"".join(_todo_row(lang, t, now) for t in open_)}</ul>')
    else:
        parts.append(f'<p class="muted">{esc(i18n.t(lang, "me_empty"))}</p>')
    if done:
        parts.append(f'<h3 class="todo-head">{esc(i18n.t(lang, "todo_done_title"))}</h3>'
                     f'<ul class="check-list todo-list">{"".join(_todo_row(lang, t, now) for t in done)}</ul>')
    title, add = i18n.t(lang, "me_title"), esc(i18n.t(lang, "todo_add"))
    return (
        f'<section class="manager role-view me-view" id="view-me" data-view-panel="me" '
        f'aria-label="{esc(i18n.t(lang, "station_me"))}" hidden>'
        f'<div class="mcol"><section class="mtile glass" id="todos"><header><h2>{esc(title)}</h2>'
        f'{ui.info_dot(title, i18n.t(lang, "me_hint"))}'
        f'<span class="count" id="me-count">{len(open_)}</span>'
        f'<button class="icon-button m-add" id="todo-add" type="button" aria-label="{add}" title="{add}">'
        f'{icon("plus")}</button></header>'
        f'<div class="r-scroll" id="me-list">{"".join(parts)}</div></section></div></section>'
    )


DIALOGS = """<dialog class="dialog" id="todo-dialog" data-title-new="%t.todo_new%" data-title-edit="%t.todo_edit%"
        data-btn-new="%t.create%" data-btn-edit="%t.save%">
  <form method="post" action="" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <h2 id="todo-dialog-title">%t.todo_new%</h2>
    <label>%t.todo_text%<input name="text" required maxlength="%MAX_TEXT%" autocomplete="off" placeholder="%t.todo_placeholder%"></label>
    <div class="actions">
      <button type="button" data-close>%t.cancel%</button>
      <button class="primary" type="submit" id="todo-dialog-button">%t.create%</button>
    </div>
  </form>
</dialog>
<dialog class="dialog" id="todo-done-dialog">
  <form method="post" action="" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <h2>%t.todo_note_title%</h2>
    <label>%t.todo_note%<textarea name="note" rows="5" maxlength="%MAX_NOTE%" placeholder="%t.todo_note_placeholder%"></textarea></label>
    <div class="actions">
      <button type="button" data-close>%t.cancel%</button>
      <button class="primary" type="submit">%t.save%</button>
    </div>
  </form>
</dialog>
<dialog class="dialog danger" id="todo-confirm">
  <h2>%t.todo_confirm_delete%</h2>
  <div class="actions">
    <button type="button" data-close autofocus>%t.cancel%</button>
    <button class="danger-btn" type="button" id="todo-confirm-yes">%t.yes%</button>
  </div>
</dialog>"""


def dialogs(lang: str) -> str:
    """The dialogs of "For you"; outside the view, like the manager's (a modal inside a hidden element would not show)."""
    return fill(DIALOGS, lang, MAX_TEXT=str(todos.MAX_TEXT), MAX_NOTE=str(todos.MAX_NOTE))
