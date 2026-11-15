"""HTML of the role views of the project page: Programmer, Tester, Reviewer and "For you" (Janis, 15.11.2026: a first
version to work with; what exactly belongs there is decided later, PROJEKT.md 11a, Stufe 2).

A role view has two columns. Left: "Right now" (what the role is doing in this project, with its settings in the head:
on or off, code with internet, model and level) and its usage. Right: its runs, newest first, each with its report.
"For you" lists the tasks that wait for the user (approval, or they need him) with their last report; the buttons to
decide stay on the board card (DESIGN.md section 1: one control, one area), the view only leads there.

Only data of the page's user is shown: the lists come from agents.role_runs / agents.waiting_tasks, which check the
project. Parts that change during a run carry ids, so static/roles.js can swap them (AgentHub.swap) without a reload.
"""
import time

from . import agents, catalog, i18n, ui
from .icons import icon
from .layout import esc

ROLES = ("programmer", "tester", "reviewer")
VIEWS = ROLES + ("me",)
LIVE = ("queued", "running")          # runs shown under "Right now"; roles.js refreshes faster while there are any
MAX_REPORT_SHOWN = 8000               # characters of a report shown in a run row


def _duration(lang: str, seconds: int) -> str:
    seconds = max(0, int(seconds))
    if seconds < 90:
        return i18n.t(lang, "dur_seconds", n=seconds)
    if seconds < 90 * 60:
        return i18n.t(lang, "dur_minutes", n=round(seconds / 60))
    return i18n.t(lang, "dur_hours", n=round(seconds / 3600, 1))


def _ago(lang: str, then: int | None, now: int) -> str:
    return "" if not then else i18n.t(lang, "ago", time=_duration(lang, now - then))


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


def _provider_name(provider: str) -> str:
    return catalog.provider(provider).name if provider in catalog.PROVIDERS else provider


def _run_row(lang: str, item: agents.RoleRun, now: int) -> str:
    run = item.run
    label, tone = _result(lang, item)
    facts = [_ago(lang, item.finished_at or item.started_at or item.created_at, now)]
    if run.seconds:
        facts.append(_duration(lang, run.seconds))
    if run.tokens_in or run.tokens_out:
        facts.append(i18n.t(lang, "role_tokens", tin=_tokens(run.tokens_in), tout=_tokens(run.tokens_out)))
    found = catalog.find(run.model)
    facts.append(" ".join(x for x in (_provider_name(item.provider), found[1].name if found else run.model) if x))
    head = (f'<summary><span class="r-title">{esc(item.task_title)}</span>'
            f'<span class="r-result {tone}">{esc(label)}</span>'
            f'<small class="r-facts">{esc(" · ".join(f for f in facts if f))}</small></summary>')
    report = run.report[:MAX_REPORT_SHOWN].strip()
    body = (f'<div class="r-report">{esc(report)}</div>' if report
            else f'<p class="muted r-report">{esc(i18n.t(lang, "role_no_report"))}</p>')
    return f'<li><details class="r-run">{head}{body}</details></li>'


def _now(lang: str, runs: list[agents.RoleRun], now: int) -> str:
    live = [r for r in runs if r.run.status in LIVE]
    if not live:
        return f'<p class="muted">{esc(i18n.t(lang, "role_idle"))}</p>'
    lines = []
    for item in reversed(live):     # oldest first: the one that started first
        if item.run.status == "running":
            text = i18n.t(lang, "role_running", title=item.task_title, time=_duration(lang, now - (item.started_at or now)))
        else:
            text = i18n.t(lang, "role_queued", title=item.task_title)
        lines.append(f'<p class="r-now {item.run.status}"><span class="r-dot" aria-hidden="true"></span>{esc(text)}</p>')
    return "".join(lines)


def _usage(lang: str, usage: dict) -> str:
    if not usage.get("runs"):
        return f'<p class="muted">{esc(i18n.t(lang, "role_usage_none"))}</p>'
    line = i18n.t(lang, "role_usage_line", runs=usage["runs"], tin=_tokens(usage["tokens_in"]),
                  tout=_tokens(usage["tokens_out"]), time=_duration(lang, usage["seconds"]))
    return f"<p>{esc(line)}</p>"


def _enabled_select(lang: str, role: str, enabled: bool) -> str:
    """On or off for tester and reviewer, in our own drop-down (core.js); the programmer is always on."""
    label = esc(i18n.t(lang, "role_switch"))
    options = "".join(
        f'<option value="{value}"{" selected" if (value == "1") == enabled else ""}>{esc(i18n.t(lang, key))}</option>'
        for value, key in (("1", "role_on"), ("0", "role_off")))
    return (f'<label class="m-select has-select"><select name="enabled" data-setting="enabled" id="role-{role}-enabled" '
            f'aria-label="{label}">{options}</select>{icon("chevron_down")}</label>')


def _net_pill(lang: str, role: str, current: str) -> str:
    """The same round globe button as the manager's (managerpage._net_switch), for this role."""
    label, tip = esc(i18n.t(lang, "net_together")), esc(i18n.t(lang, "net_together_tip"))
    pressed = "true" if current == "together" else "false"
    return (f'<button type="button" class="m-pill" id="role-{role}-net" data-setting="net" data-on="together" '
            f'data-off="apart" aria-pressed="{pressed}" aria-label="{label}" data-tip="{label}. {tip}">{icon("globe")}</button>')


def render_role(lang: str, role: str, settings: dict, runs: list[agents.RoleRun], usage: dict,
                ais: tuple[str, ...] = (catalog.DEFAULT_PROVIDER,), now: int | None = None) -> str:
    """One role's view. `settings` is agents.settings(user_id); `runs` agents.role_runs(...) for this project."""
    now = int(now if now is not None else time.time())
    mine = settings["roles"][role]
    picker = ui.model_picker(lang, f"role-{role}", mine["model"], mine.get("effort", ""), providers=ais)
    switch = "" if role == "programmer" else _enabled_select(lang, role, mine["enabled"])
    tools = f'<span class="m-chat-tools">{switch}{_net_pill(lang, role, mine["net"])}{picker}</span>'
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
        f'<div id="role-{role}-now">{_now(lang, runs, now)}</div></section>'
        f'<section class="mtile glass"><header><h2>{esc(i18n.t(lang, "role_usage"))}</h2></header>'
        f'<div id="role-{role}-usage">{_usage(lang, usage)}</div></section>'
        f'</div><div class="mcol">'
        f'<section class="mtile glass m-grow"><header><h2>{esc(i18n.t(lang, "role_runs"))}</h2>'
        f'<span class="count" id="role-{role}-count">{len(runs)}</span></header>'
        f'<div class="r-scroll" id="role-{role}-runs">{runs_html}</div></section>'
        f'</div></section>'
    )


def render_me(lang: str, waiting: list[tuple[agents.Task, str]]) -> str:
    """ "For you": the tasks that wait for the user, each with its state and last report, and the way to the board."""
    rows = "".join(
        f'<li><details class="r-run"><summary><span class="r-title">{esc(task.title)}</span>'
        f'<span class="r-result {"go" if task.status == "awaiting_approval" else "stop"}">'
        f'{esc(i18n.t(lang, f"task_{task.status}"))}</span></summary>'
        f'<div class="r-report">{esc(report[:MAX_REPORT_SHOWN].strip() or i18n.t(lang, "role_no_report"))}</div>'
        f'</details></li>'
        for task, report in waiting
    )
    body = (f'<ol class="r-runs">{rows}</ol>' if rows else f'<p class="muted">{esc(i18n.t(lang, "me_empty"))}</p>')
    board = esc(i18n.t(lang, "me_to_board"))
    return (
        f'<section class="manager role-view me-view" id="view-me" data-view-panel="me" '
        f'aria-label="{esc(i18n.t(lang, "station_me"))}" hidden>'
        f'<div class="mcol"><section class="mtile glass m-grow"><header><h2>{esc(i18n.t(lang, "me_title"))}</h2>'
        f'{ui.info_dot(i18n.t(lang, "me_title"), i18n.t(lang, "me_hint"))}'
        f'<span class="count" id="me-count">{len(waiting)}</span>'
        f'<a class="link inline" href="#board" data-goto="board">{board}</a></header>'
        f'<div class="r-scroll" id="me-list">{body}</div></section></div></section>'
    )
