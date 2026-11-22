"""Tasks and runs of the agents, stored in SQLite (rebuilt 22.11.2026, KONZEPT-AGENTEN.md 10). Standard library only.

A *task* is one board item on its way through the chain (workflow.py). The board is the queue: per project one task at
a time (`take_next`, the only place a task is made), bugs first, then small and major updates in the order they were
made. When the programmer takes an item it leaves the board ("working") and comes back only as finished (archive) or
cancelled (trash). Every step of a task is a *run*, a job for the runner:

- work: the role of the task's stage does its part (programmer, tester, reviewer; the manager's documentation is "doc")
- result: the same AI is asked once more for the RESULT line its answer lacked (no tools, cheap)
- decide: the manager answers a role's question or writes it anew, in plain words, for the user (prompts.decide)
- explain: the manager explains a decision the user has to take and recommends a way (prompts.explain)

Two sides:
- User side (`settings`, `configure`, `answer_question`, `decide`, `cancel`, `check_todos`, `set_paused`, lists): every
  function gets the `user_id` and checks that the project is his; foreign things are "not found" or "nothing done".
- Runner side (`claim_next`, `alive`, `finish_run`, merges, clean-ups, `requeue_running`): trusted code. The runner
  passes no user: user and project come from the task in the database, so a run can only touch its own user's data.

A run starts only with one of the user's own AIs (aichoice.py); nobody else's connection is ever used.
"""
import re
import sqlite3
import time
from dataclasses import dataclass, field

from . import (ai_link, aichoice, board, catalog, credentials, db, failures, files, memory, models, prompts, questions,
               reply, serversettings, todos, toolcheck, workflow)
from . import usage as ledger   # the module; usage() below is this module's view for the roles' tabs

# Models and effort levels come from catalog.py (Janis, 14.11.2026), kept per role AND per AI ("model.<role>.<provider>"),
# so switching the standard AI and back finds them again. A role without a choice gets its AI's start for the role.
NEEDS = ("any", "mac")
# How freely the manager decides (Janis, 07.11.2026): fully on its own, asks for big decisions, asks for small ones too.
AUTONOMY = ("auto", "major", "all")
DEFAULT_AUTONOMY = "major"
# Web and code together (code has the open internet) or apart (web search, code without internet). Janis, 08.11.2026.
NET_MODES = ("together", "apart")
DEFAULT_NET = "together"
# Tester and reviewer check what is in /work and need no internet (20.11.2026): code they run can send nothing out.
ROLE_NET = {"tester": "apart", "reviewer": "apart"}
PURPOSES = ("work", "result", "decide", "explain", "doc")
MAC_ROLES = ("programmer", "tester")     # a task that needs a Mac runs these only on a runner that has one
MAX_REPORT = 20000                       # characters of a report that are kept
MAX_THOUGHTS = 20000                     # characters of a run's thoughts that are kept (the newest)
FOUND_MAX = 3                            # items a run may put on the board (prompts.FOUND)
MAX_DIFF = 60000                         # characters of a task's change kept (runner/workspace.py cuts it too)
MAX_TESTS = 6000                         # characters of the output of the project's tests kept
MAX_HINT = 1000
HUB_MODEL = "hub"                        # the "model" of a test run the hub made itself (no AI, no tokens)
# The runner tells about every run it has going every few seconds (runner.ALIVE_EVERY); a run it has not told about for
# this long has lost its runner (restart, crash) and counts as stopped.
DEAD_SECONDS = 300
OPEN = workflow.STAGES                   # stages of a task that is not over (with or without a hold)


@dataclass
class Task:
    id: int
    project_id: int
    item_id: int | None
    title: str
    kind: str
    needs: str
    stage: str
    hold: str
    hold_why: str
    advice: str
    advice_pick: str
    returns: int
    manual_check: bool
    hint: str
    created_at: int
    finished_at: int | None
    held_since: int | None = None


@dataclass
class Run:
    id: int
    task_id: int
    role: str
    purpose: str
    model: str
    status: str            # queued, running, done, failed, cancelled
    result: str | None
    report: str
    tokens_in: int
    tokens_out: int
    seconds: int
    thoughts: str = ""


@dataclass
class Job:
    """What the runner gets: everything it needs and nothing else."""
    run_id: int
    user_id: int
    project_id: int
    task_id: int
    role: str
    model: str
    branch: str
    title: str
    kind: str
    reports: list[tuple[str, str]]  # (role, report) of the earlier work runs of this task (data)
    net: str = DEFAULT_NET          # web and code together (open internet) or apart, the role's switch
    effort: str = ""                # effort level of the model (catalog.py); empty = the program's own default
    provider: str = "claude"        # which AI does the run (aichoice.py); the runner picks the adapter by it
    purpose: str = "work"
    prompt: str = ""                # the package for the AI (prompts.py)
    mode: str = ""                  # "brief": one answer without tools and without /work
    sync: bool = False              # the runner brings main into the task's branch first (the programmer's runs)
    conflict_note: str = ""         # what the runner adds when main brought conflicts ({files}: their names)
    route: dict = field(default_factory=dict)   # a further AI: its address and model name (ai_link.route_in)
    hub_tools: list = field(default_factory=list)   # the hub's tools this AI gets (toolcheck.hub_tools)
    credential: str = "plan"        # the user's plan or his API key (credentials.py)
    limits: dict = field(default_factory=lambda: serversettings.run_limits())   # the container (serversettings.py)
    files: list = field(default_factory=list)   # the user's files for /files (files.for_agents): id, name, area, size
    links: list = field(default_factory=list)   # and the links: name, address
    images: bool = False            # the model sees pictures (catalog.sees_images)


def _task(row: sqlite3.Row) -> Task:
    return Task(row["id"], row["project_id"], row["item_id"], row["title"], row["kind"], row["needs"], row["stage"],
                row["hold"], row["hold_why"], row["advice"], row["advice_pick"], row["returns"],
                bool(row["manual_check"]), row["hint"], row["created_at"], row["finished_at"], row["held_since"])


def _run(row: sqlite3.Row) -> Run:
    return Run(row["id"], row["task_id"], row["role"], row["purpose"], row["model"], row["status"], row["result"],
               row["report"], row["tokens_in"], row["tokens_out"], row["seconds"], row["thoughts"])


def branch_name(task_id: int) -> str:
    return f"agent/task-{int(task_id)}"


def _owner(conn: sqlite3.Connection, task_id: int) -> int | None:
    row = conn.execute("SELECT p.user_id FROM agent_tasks t JOIN projects p ON p.id = t.project_id WHERE t.id = ?",
                       (task_id,)).fetchone()
    return None if row is None else row["user_id"]


def _owned_task(conn: sqlite3.Connection, user_id: int, task_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT t.* FROM agent_tasks t JOIN projects p ON p.id = t.project_id"
                        " WHERE t.id = ? AND p.user_id = ?", (task_id, user_id)).fetchone()


def _task_row(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row:
    return conn.execute("SELECT * FROM agent_tasks WHERE id = ?", (task_id,)).fetchone()


# --- settings per user: model, AI and on/off per role, the manager's autonomy

def _setting(conn: sqlite3.Connection, user_id: int, key: str, default: str) -> str:
    row = conn.execute("SELECT value FROM agent_settings WHERE user_id = ? AND key = ?", (user_id, key)).fetchone()
    return default if row is None else row["value"]


def _put(conn: sqlite3.Connection, user_id: int, key: str, value: str) -> None:
    conn.execute("INSERT INTO agent_settings (user_id, key, value) VALUES (?, ?, ?)"
                 " ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (user_id, key, value))


def _choice(conn: sqlite3.Connection, user_id: int, role: str, provider: str | None = None) -> tuple[str, str]:
    """(model, effort) of a role for one AI (default: the user's standard), made valid against the current list
    (catalog.resolve) and against the models his account offers (models.allowed)."""
    provider = provider or aichoice.default_in(conn, user_id)
    model = _setting(conn, user_id, f"model.{role}.{provider}", "")
    effort = _setting(conn, user_id, f"effort.{role}.{provider}", "")
    if not model and (start := catalog.role_default(provider, role)):   # the AI's start for this role (catalog)
        model, effort = start[0], effort or start[1]
    ids = models.allowed(conn, user_id, provider)
    if ids is not None and model not in ids:   # not (any more) in his account's list: the role's start, the default, any
        start = catalog.role_default(provider, role)
        default = catalog.provider(provider).default_model
        model = next((m for m in ((start or ("",))[0], default) if m in ids), None) or sorted(ids)[0]
        effort = start[1] if start and start[0] == model else effort
    return catalog.resolve(model, effort, provider)


def model_in(conn: sqlite3.Connection, user_id: int, role: str) -> str:
    """The model of a role for this user, inside an open connection (the manager chat uses "chef")."""
    return _choice(conn, user_id, role, role_provider_in(conn, user_id, role))[0]


def effort_in(conn: sqlite3.Connection, user_id: int, role: str) -> str:
    """The effort level of a role for this user, inside an open connection."""
    return _choice(conn, user_id, role, role_provider_in(conn, user_id, role))[1]


def autonomy_in(conn: sqlite3.Connection, user_id: int) -> str:
    """How freely the manager decides (Janis, 07.11.2026), see AUTONOMY."""
    value = _setting(conn, user_id, "autonomy", DEFAULT_AUTONOMY)
    return value if value in AUTONOMY else DEFAULT_AUTONOMY


def net_in(conn: sqlite3.Connection, user_id: int, role: str) -> str:
    """Web and code together or apart for one role (NET_MODES), per agent like the model (Janis, 08.11.2026)."""
    return _setting(conn, user_id, f"net.{role}", ROLE_NET.get(role, DEFAULT_NET))


def role_provider_in(conn: sqlite3.Connection, user_id: int, role: str, chosen_only: bool = False) -> str | None:
    """The AI of a role (Janis, 22.11.2026: chosen in its tab): the one the user picked for it while it is connected,
    else the standard (or None with `chosen_only`)."""
    picked = _setting(conn, user_id, f"ai.role.{role}", "")
    if picked and aichoice.connected_in(conn, user_id, picked):
        return picked
    return None if chosen_only else aichoice.default_in(conn, user_id)


def settings(user_id: int) -> dict:
    """{"autonomy", "provider", "roles": {role: {"model", "effort", "net", "provider", "chosen"}},
    "models", "model_names"}, defaults filled in. A role's "provider" is the AI that answers now (aichoice.acting_in):
    while the chosen one's quota rests, "resting" names it and "rest_left" says for how many more seconds. "models": per AI the model ids his account offers (None = not known
    yet), for the drop-downs."""
    with db.connect() as conn:
        roles = {}
        for r in workflow.ROLES:
            mine = role_provider_in(conn, user_id, r)
            acting = aichoice.acting_in(conn, user_id, mine)   # while its quota rests, the AI standing in for it
            model, effort = _choice(conn, user_id, r, acting)
            roles[r] = {"model": model, "effort": effort, "net": net_in(conn, user_id, r),
                        "provider": acting, "chosen": role_provider_in(conn, user_id, r, chosen_only=True) or "",
                        "resting": mine if acting != mine else "",
                        "rest_left": aichoice.rest_left(conn, user_id, mine) if acting != mine else 0}
        return {"autonomy": autonomy_in(conn, user_id), "provider": aichoice.default_in(conn, user_id), "roles": roles,
                "models": {p: models.allowed(conn, user_id, p) for p in catalog.PROVIDERS},
                "model_names": {f"own-{r['slot']}": r["label"] for r in ai_link.custom_rows(conn, user_id)}}


def configure(user_id: int, role: str | None = None, *, model: str | None = None,
              autonomy: str | None = None, net: str | None = None, effort: str | None = None,
              provider: str | None = None) -> None:
    """Change a setting of this user (every role is always on). Raises ValueError for unknown values. Model
    and effort are checked against the list (catalog.py) and his account (models.py); `provider` is the AI of the role
    (one of his connected AIs; "" goes back to the standard)."""
    changes: list[tuple[str, str]] = []
    if (model is not None or net is not None or effort is not None or provider is not None) \
            and role not in workflow.ROLES:
        raise ValueError("Unbekannte Rolle")
    if provider is not None:
        if provider:
            with db.connect() as conn:
                if provider not in catalog.PROVIDERS or not aichoice.connected_in(conn, user_id, provider):
                    raise ValueError("Diese KI ist nicht verbunden")
        changes.append((f"ai.role.{role}", provider))
    if autonomy is not None:
        if autonomy not in AUTONOMY:
            raise ValueError("Unbekannte Selbstständigkeit")
        changes.append(("autonomy", autonomy))
    if net is not None:
        if net not in NET_MODES:
            raise ValueError("Unbekannter Netzmodus")
        changes.append((f"net.{role}", net))
    if model is not None or effort is not None:
        if model is None:
            with db.connect() as conn:
                model_for_effort = model_in(conn, user_id, role)
        else:
            model_for_effort = model
        try:
            catalog.check(model_for_effort, effort)
        except ValueError:
            raise ValueError("Unbekanntes Modell oder unbekannte Stufe") from None
        with db.connect() as conn:
            if model is not None and not models.permits(conn, user_id, model):
                raise ValueError("Modell nicht im Konto")
        owner_ai = catalog.provider_of(model_for_effort)     # kept per AI: switching back finds it again
        if model is not None:
            changes.append((f"model.{role}.{owner_ai}", model))
        if effort is not None:
            changes.append((f"effort.{role}.{owner_ai}", effort))
    with db.connect() as conn:
        for key, value in changes:
            _put(conn, user_id, key, value)


def review_focus(user_id: int, project_id: int) -> str | None:
    """What the reviewer of the project looks at (Janis, 22.11.2026; "" = correctness, security, structure). Markdown:
    the user types it, drops a file on the field or downloads it again; only the reviewer's package has it."""
    with db.connect() as conn:
        row = conn.execute("SELECT review_focus FROM projects WHERE id = ? AND user_id = ?",
                           (project_id, user_id)).fetchone()
    return None if row is None else row["review_focus"]


MAX_FOCUS = 6000
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_focus(text: str) -> str:
    """Markdown as it was written: lines kept, control characters, trailing blanks and runs of empty lines gone."""
    lines = [line.rstrip() for line in _CONTROL.sub("", (text or "").replace("\r\n", "\n").replace("\r", "\n")).split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()[:MAX_FOCUS]


def set_review_focus(user_id: int, project_id: int, text: str) -> bool:
    with db.connect() as conn:
        return conn.execute("UPDATE projects SET review_focus = ? WHERE id = ? AND user_id = ?",
                            (clean_focus(text), project_id, user_id)).rowcount == 1


# --- the emergency switch (Janis, 22.11.2026): "AIs pause" in the drawer freezes the user's agent runs where they are
# (the runner pauses their containers) and starts nothing of his until he goes on; nothing is stopped, the manager chat
# stays free. Kept in agent_settings ("agents.paused" = the moment).
PAUSED = "agents.paused"


def paused_in(conn: sqlite3.Connection, user_id: int) -> int:
    """Since when the user's agents are paused (unix time), 0 when they run."""
    return int(_setting(conn, user_id, PAUSED, "0") or 0)


def set_paused(user_id: int, on: bool, now: int | None = None) -> bool:
    """Pause the user's agents or let them go on. Returns whether they are paused now."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        since = paused_in(conn, user_id)
        if on and not since:
            _put(conn, user_id, PAUSED, str(now))
        elif not on and since:
            _put(conn, user_id, PAUSED, "0")
    return on


# --- the board is the queue: one task per project, made only here

def _open_task(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row | None:
    marks = ",".join("?" * len(OPEN))
    return conn.execute(f"SELECT * FROM agent_tasks WHERE project_id = ? AND stage IN ({marks}) ORDER BY id LIMIT 1",
                        (project_id, *OPEN)).fetchone()


def next_item(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row | None:
    """The item the programmer takes next: a bug first (in the order of the board), else of the small and the major
    updates the head of the column that was made first (Janis, 22.11.2026: the manager puts the pieces of a wish on
    the board in the order they build on each other; dragging inside a column still counts)."""
    def head(kind: str) -> sqlite3.Row | None:
        return conn.execute("SELECT * FROM board_items WHERE project_id = ? AND kind = ? AND status = 'open'"
                            " ORDER BY position, id LIMIT 1", (project_id, kind)).fetchone()
    bug = head("bug")
    if bug is not None:
        return bug
    heads = [row for row in (head("minor"), head("major")) if row is not None]
    return min(heads, key=lambda row: row["id"]) if heads else None


def take_next(conn: sqlite3.Connection, now: int) -> int:
    """For every project with nothing on its way and open items: the programmer takes the next item (it leaves the
    board). Only for a user with an AI connected and his agents not paused. Returns how many tasks started."""
    started = 0
    projects = conn.execute(
        "SELECT DISTINCT b.project_id, p.user_id FROM board_items b JOIN projects p ON p.id = b.project_id"
        " JOIN users u ON u.id = p.user_id WHERE b.status = 'open' AND u.deleted_at IS NULL").fetchall()
    for row in projects:
        if _open_task(conn, row["project_id"]) is not None:
            continue
        if not aichoice.connected_list(conn, row["user_id"]) or paused_in(conn, row["user_id"]):
            continue
        item = next_item(conn, row["project_id"])
        if item is None:
            continue
        # never the number of a deleted task whose work folder the runner has not deleted yet
        task_id = db.fresh_id(conn, "agent_tasks", "SELECT MAX(ref) FROM work_wipes WHERE kind = 'task'")
        needs = item["needs"] if item["needs"] in NEEDS else "any"
        conn.execute("INSERT INTO agent_tasks (id, project_id, item_id, title, kind, needs, stage, created_at)"
                     " VALUES (?, ?, ?, ?, ?, ?, 'coding', ?)",
                     (task_id, row["project_id"], item["id"], item["title"], item["kind"], needs, now))
        conn.execute("UPDATE board_items SET status = 'working' WHERE id = ?", (item["id"],))
        _queue(conn, row["user_id"], task_id, "programmer", "work", now)
        started += 1
    return started


# --- runs

def _run_provider(conn: sqlite3.Connection, user_id: int, task_id: int, role: str) -> str:
    """The AI of a new run: the one chosen for its role, else the standard. Without a choice the reviewer takes another
    of the user's AIs than the task's programmer when he has two (Janis: one model overlooks its own mistakes)."""
    picked = role_provider_in(conn, user_id, role, chosen_only=True)
    if picked:
        return picked
    order = aichoice.order_in(conn, user_id)
    if role == "reviewer" and len(order) > 1:
        row = conn.execute("SELECT provider FROM agent_runs WHERE task_id = ? AND role = 'programmer'"
                           " ORDER BY id DESC LIMIT 1", (task_id,)).fetchone()
        if row is not None:
            return next((p for p in order if p != row["provider"]), order[0])
    return order[0] if order else aichoice.default_in(conn, user_id)


def _queue(conn: sqlite3.Connection, user_id: int, task_id: int, role: str, purpose: str, now: int,
           ref: int | None = None, provider: str | None = None) -> int:
    provider = provider or _run_provider(conn, user_id, task_id, role)
    model, effort = _choice(conn, user_id, role, provider)
    return conn.execute(
        "INSERT INTO agent_runs (task_id, role, purpose, ref, model, effort, provider, status, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?)", (task_id, role, purpose, ref, model, effort, provider, now),
    ).lastrowid


def _queue_stage(conn: sqlite3.Connection, user_id: int, task: sqlite3.Row, now: int) -> None:
    """The run of the stage the task stands in (nothing for merging: the runner asks for merges itself)."""
    role = workflow.STAGE_ROLE.get(task["stage"])
    if role is not None:
        _queue(conn, user_id, task["id"], role, "doc" if role == "chef" else "work", now)


def _enter(conn: sqlite3.Connection, user_id: int, task_id: int, step: workflow.Step, now: int) -> None:
    """Put the task where the step says and queue what comes next: the run of the new stage, the manager's explanation
    of a decision, nothing while it waits for an answer or the user. Queued runs of before go; finished work moves
    the item into the archive, a cancelled task puts it into the trash."""
    old = _task_row(conn, task_id)
    ended = step.stage in workflow.ENDS
    decided = step.hold == "" and old["hold"] == "decision"      # the user decided: fresh counts
    fresh_stage = step.stage != old["stage"] or decided           # a new stage (or a decision) may be retried again
    conn.execute(
        "UPDATE agent_tasks SET stage = ?, hold = ?, hold_why = ?, returns = ?, manual_check = ?, finished_at = ?,"
        " held_since = ?, advice = '', advice_pick = '', retried = CASE WHEN ? THEN 0 ELSE retried END,"
        " asks = CASE WHEN ? THEN 0 ELSE asks END WHERE id = ?",
        (step.stage, step.hold, step.why if step.hold == "decision" else "", step.returns, int(step.manual_check),
         now if ended else None, now if step.hold else None, int(fresh_stage), int(decided), task_id))
    conn.execute("UPDATE agent_runs SET status = 'cancelled' WHERE task_id = ? AND status = 'queued'"
                 + ("" if ended else " AND purpose IN ('work', 'doc', 'result', 'explain')"), (task_id,))
    if ended:
        conn.execute("UPDATE agent_runs SET status = 'cancelled', finished_at = ? WHERE task_id = ? AND"
                     " status = 'running'", (now, task_id))   # the runner hears it at its next sign of life
        questions.drop_for_task(conn, task_id)
        conn.execute("UPDATE board_items SET status = ? WHERE id = ? AND status = 'working'",
                     ("archived" if step.stage == "done" else "trash", old["item_id"]))
        return
    if step.hold == "decision":                        # the manager explains it in plain words
        _queue(conn, user_id, task_id, "chef", "explain", now)
        return
    if step.hold:
        return
    _queue_stage(conn, user_id, _task_row(conn, task_id), now)


def slot_free(conn: sqlite3.Connection) -> bool:
    """May one more AI container start now? Counts the running agent runs (not the paused ones: they only hold their
    memory) and chat answers of all users against the owner's setting."""
    limit = serversettings.ai_parallel()
    if not limit:
        return True
    running = conn.execute(
        "SELECT COUNT(*) FROM agent_runs r JOIN agent_tasks t ON t.id = r.task_id JOIN projects p ON p.id = t.project_id"
        " WHERE r.status = 'running' AND NOT EXISTS (SELECT 1 FROM agent_settings s WHERE s.user_id = p.user_id"
        " AND s.key = ? AND s.value != '0')", (PAUSED,)).fetchone()[0]
    running += conn.execute("SELECT COUNT(*) FROM chat_messages WHERE status = 'running'").fetchone()[0]
    return running < limit


def _sweep_dead(conn: sqlite3.Connection, now: int) -> None:
    """Runs the runner stopped telling about (it restarted or broke): they count as stopped."""
    for row in conn.execute("SELECT id FROM agent_runs WHERE status = 'running' AND COALESCE(alive_at, started_at) < ?",
                            (now - DEAD_SECONDS,)).fetchall():
        _finish(conn, row["id"], "stopped", "The run stopped answering (the server lost it).", now=now)


def claim_next(can_mac: bool, now: int | None = None) -> Job | None:
    """Runner: take the oldest run that may start now, or None. Only as many AI containers as the owner allows.

    A run waits while its user's agents are paused, none of his AIs is connected, or it needs a Mac and `can_mac` is
    False. If the AI of the run is not connected any more or rests after a used-up quota, his next AI takes it."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        _sweep_dead(conn, now)
        take_next(conn, now)
        if not slot_free(conn):
            return None
        for run in conn.execute(
            "SELECT r.*, t.needs, t.project_id, t.hold, t.stage, t.title, t.kind FROM agent_runs r"
            " JOIN agent_tasks t ON t.id = r.task_id WHERE r.status = 'queued'"
            # the manager's short jobs first: they are small and what they bring (an answer) is wanted by the next run
            " ORDER BY r.purpose IN ('decide', 'explain') DESC, r.created_at, r.id"
        ).fetchall():
            user_id = _owner(conn, run["task_id"])
            if paused_in(conn, user_id):
                continue
            if run["purpose"] == "work" and run["needs"] == "mac" and run["role"] in MAC_ROLES and not can_mac:
                continue
            provider, model, effort = run["provider"], run["model"], run["effort"]
            if not aichoice.connected_in(conn, user_id, provider) or aichoice.resting(conn, user_id, provider):
                tried = set(run["tried"].split(",")) - {""}
                order = [p for p in aichoice.order_in(conn, user_id) if p not in tried] or aichoice.order_in(conn, user_id)
                if not order or not aichoice.connected_in(conn, user_id, order[0]):
                    continue                               # none of his AIs: the run waits
                if order[0] != provider:
                    provider = order[0]
                    model, effort = _choice(conn, user_id, run["role"], provider)
                api = run["credential"] == "api" and credentials.api_usable(conn, user_id, provider, "run")
                if aichoice.resting(conn, user_id, provider) and not api:
                    continue                               # all of his AIs are used up: it waits until one rested
            way = (run["credential"] if run["credential"] == "api" and credentials.api_usable(conn, user_id, provider, "run")
                   else credentials.first(conn, user_id, provider, "run"))
            conn.execute("UPDATE agent_runs SET status = 'running', started_at = ?, alive_at = ?, provider = ?,"
                         " model = ?, effort = ?, credential = ?, thoughts = '' WHERE id = ?",
                         (now, now, provider, model, effort, way, run["id"]))
            reports = [(r["role"], r["report"]) for r in conn.execute(
                "SELECT role, report FROM agent_runs WHERE task_id = ? AND purpose = 'work' AND status = 'done'"
                " AND report != '' ORDER BY id", (run["task_id"],))]
            job = Job(run["id"], user_id, run["project_id"], run["task_id"], run["role"], model,
                      branch_name(run["task_id"]), run["title"], run["kind"], reports, net_in(conn, user_id, run["role"]),
                      effort, provider, run["purpose"])
            job.route = ai_link.route_in(conn, user_id, provider, model)
            job.hub_tools = toolcheck.hub_tools(provider)
            job.credential = way
            job.images = catalog.sees_images(model)
            if run["purpose"] == "work":
                brief = prompts.brief_run(conn, job)
                job.mode = "brief" if brief else ""
                job.prompt = prompts.run(conn, job, brief=brief)
                job.sync = run["role"] == "programmer"
                job.conflict_note = prompts.CONFLICTS if job.sync else ""
                conn.execute("UPDATE agent_tasks SET resume = '' WHERE id = ?", (run["task_id"],))   # it is in the package
            else:
                job.mode = "brief"
                job.prompt = _brief_prompt(conn, job, run)
            if not job.mode:   # a run without tools reads no files
                job.files, job.links = files.for_agents(conn, user_id, run["project_id"])
            return job
    return None


def _brief_prompt(conn: sqlite3.Connection, job: Job, run: sqlite3.Row) -> str:
    if run["purpose"] == "doc":
        return prompts.run(conn, job, brief=True)
    if run["purpose"] == "result":
        parent = conn.execute("SELECT report FROM agent_runs WHERE id = ? AND task_id = ?",
                              (run["ref"], run["task_id"])).fetchone()
        return prompts.result_fix(job, parent["report"] if parent else "")
    if run["purpose"] == "decide":
        question = questions.get(conn, run["ref"], job.project_id)
        return prompts.decide(conn, job, question, autonomy_in(conn, job.user_id))
    return prompts.explain(conn, job)


def alive(run_id: int, thoughts: str = "", now: int | None = None) -> str:
    """Runner: a run is still going (every few seconds). Keeps what its AI wrote meanwhile (only shown, never context)
    and says what the run should do: "run", "pause" (its user paused the agents) or "stop" (the run is over for the
    hub: its task was cancelled or it was given up)."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        row = conn.execute("SELECT r.task_id FROM agent_runs r WHERE r.id = ? AND r.status = 'running'",
                           (run_id,)).fetchone()
        if row is None:
            return "stop"
        conn.execute("UPDATE agent_runs SET alive_at = ?, thoughts = substr(thoughts || ?, -?) WHERE id = ?",
                     (now, thoughts or "", MAX_THOUGHTS, run_id))
        return "pause" if paused_in(conn, _owner(conn, row["task_id"])) else "run"


def requeue_running(now: int | None = None) -> int:
    """Runner: it started again and has no container of before; its runs go back into the queue (nothing failed)."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        return conn.execute("UPDATE agent_runs SET status = 'queued', started_at = NULL, alive_at = NULL"
                            " WHERE status = 'running'").rowcount


# --- the end of a run

def _try_again(conn: sqlite3.Connection, run: sqlite3.Row, user_id: int, report: str, tokens_in: int,
               tokens_out: int) -> bool:
    """A run failed for its AI, not for its work (failures.py): the same run is queued again, with the user's API key
    when the plan ran out (only plan -> key, never back), else with his next AI that has not failed it yet (`tried`,
    so nothing goes round in circles). An AI whose quota ran out rests a while (aichoice.rest)."""
    kind = failures.kind(report)
    if kind not in failures.SWITCH:
        return False
    if kind == "limit":
        aichoice.rest(conn, user_id, run["provider"])
    used = (max(0, int(tokens_in)), max(0, int(tokens_out)))
    if run["credential"] == "plan" and kind in failures.EXHAUSTED:
        other = credentials.next_way(conn, user_id, run["provider"], "run", run["credential"])
        if other is not None:
            conn.execute("UPDATE agent_runs SET status = 'queued', credential = ?, tokens_in = tokens_in + ?,"
                         " tokens_out = tokens_out + ? WHERE id = ?", (other, *used, run["id"]))
            return True
    tried = [p for p in run["tried"].split(",") if p] + [run["provider"]]
    nxt = next((p for p in aichoice.order_in(conn, user_id)
                if p not in tried and aichoice.connected_in(conn, user_id, p)), None)
    if nxt is None:
        return False
    model, effort = _choice(conn, user_id, run["role"], nxt)
    conn.execute("UPDATE agent_runs SET status = 'queued', provider = ?, model = ?, effort = ?, credential = 'plan',"
                 " tried = ?, tokens_in = tokens_in + ?, tokens_out = tokens_out + ? WHERE id = ?",
                 (nxt, model, effort, ",".join(dict.fromkeys(tried)), *used, run["id"]))
    return True


def _wait_for_an_ai(conn: sqlite3.Connection, run: sqlite3.Row, report: str, tokens_in: int, tokens_out: int) -> bool:
    """Every AI of the user is used up (it rests, aichoice.rest) or signed out: the run waits in the queue until one can
    again, instead of failing the task (KONZEPT-AGENTEN.md 10.2). Only when resting really makes it wait."""
    kind = failures.kind(report)
    if not (kind == "auth" or (kind == "limit" and serversettings.ai_rest() > 0)):
        return False
    conn.execute("UPDATE agent_runs SET status = 'queued', started_at = NULL, alive_at = NULL, tried = '',"
                 " tokens_in = tokens_in + ?, tokens_out = tokens_out + ? WHERE id = ?",
                 (max(0, int(tokens_in)), max(0, int(tokens_out)), run["id"]))
    return True


def finish_run(run_id: int, result: str, report: str = "", tokens_in: int = 0, tokens_out: int = 0,
               seconds: int = 0, now: int | None = None, change: tuple[str, str] | None = None,
               tests: tuple[int, str] | None = None, committed: bool | None = None,
               markers: list[str] | None = None, cache: tuple[int, int] = (0, 0), partial: bool = False) -> bool:
    """Runner: a run is over. `result`: the value of its RESULT line, "none" (the answer had none), "failed" (the AI or
    its program failed; the report says why) or "stopped" (the runner ended it: no output for too long, or the longest
    time). `change` (stat, diff): what the task changed so far, after a run that commits; `committed`: that run's commit
    changed something; `tests` (exit code, output): the project's tests the hub ran after the programmer; `markers`:
    files that still have conflict markers. `cache` (read, written): the part of the input from the provider's cache;
    `partial`: the runner ended the run and counted what it saw. Every run goes into the usage ledger (usage.py), also a
    failed one before the next try. False if the run is not running any more (cancelled, given up)."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        done = _finish(conn, run_id, result, report or "", tokens_in, tokens_out, seconds, now, change, tests,
                       committed, markers or [], cache, partial)
    if isinstance(done, tuple):   # the manager's memory notes, after the transaction (files.py opens its own)
        owner, project_id, notes, edits, the_run = done
        for name, body in notes.items():
            memory.save_memory(owner, project_id, body, name)
        failed = memory.edit_failures(memory.apply_edits(owner, project_id, edits)) if edits else ""
        if failed:
            with db.connect() as conn:
                conn.execute("UPDATE agent_runs SET report = substr(report || ?, 1, ?) WHERE id = ?",
                             (f"\n\n{failed}", MAX_REPORT, the_run))
        return True
    return done


def _close(conn: sqlite3.Connection, run_id: int, result: str, report: str, tokens_in: int, tokens_out: int,
           seconds: int, now: int) -> None:
    conn.execute("UPDATE agent_runs SET status = 'done', result = ?, report = ?, tokens_in = tokens_in + ?,"
                 " tokens_out = tokens_out + ?, seconds = seconds + ?, finished_at = ? WHERE id = ?",
                 (result[:20], report[:MAX_REPORT], max(0, int(tokens_in)), max(0, int(tokens_out)),
                  max(0, int(seconds)), now, run_id))


def _finish(conn: sqlite3.Connection, run_id: int, result: str, report: str, tokens_in: int = 0, tokens_out: int = 0,
            seconds: int = 0, now: int = 0, change=None, tests=None, committed=None, markers=(), cache=(0, 0),
            partial: bool = False):
    run = conn.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    if run is None or (run["status"] != "running" and not (tokens_in or tokens_out)):
        return False
    task = _task_row(conn, run["task_id"])
    user_id = _owner(conn, task["id"])
    # What it used counts even when the hub closed the run meanwhile (cancelled, lost and given up): the AI worked.
    ledger.record(conn, user_id=user_id, project_id=task["project_id"], provider=run["provider"], model=run["model"],
                 credential=run["credential"], kind="run", role=run["role"], purpose=run["purpose"], ref=run_id,
                 tokens_in=tokens_in, tokens_out=tokens_out, cache_read=cache[0], cache_write=cache[1],
                 seconds=seconds, partial=partial, now=now)
    if run["status"] != "running":
        return False
    if result == "failed" and _try_again(conn, run, user_id, report, tokens_in, tokens_out):
        return True
    if result == "failed" and _wait_for_an_ai(conn, run, report, tokens_in, tokens_out):
        return True
    _close(conn, run_id, result, report, tokens_in, tokens_out, seconds, now)
    if task["stage"] in workflow.ENDS:
        return True
    purpose = run["purpose"]
    if purpose == "decide":
        _finish_decide(conn, run, task, user_id, result, report, now)
    elif purpose == "explain":
        _finish_explain(conn, task, result, report)
    elif purpose == "doc":
        return _finish_doc(conn, run, task, user_id, result, report, now)
    elif purpose == "result":
        _finish_result(conn, run, task, user_id, result, report, now)
    else:
        _finish_work(conn, run, task, user_id, result, report, now, change, tests, committed, markers)
    return True


def _again_or_decide(conn: sqlite3.Connection, task: sqlite3.Row, user_id: int, why: str, resume: str, now: int) -> None:
    """A run of the stage failed or was stopped: the stage runs once more, told where it stands (its work is saved);
    the second time the user decides (Janis, 22.11.2026: do not end early, but not forever either)."""
    if not task["retried"]:
        conn.execute("UPDATE agent_tasks SET retried = 1, resume = ? WHERE id = ?", (resume[:2000], task["id"]))
        _queue_stage(conn, user_id, task, now)
        return
    _enter(conn, user_id, task["id"], workflow.decision(task["stage"], task["returns"], bool(task["manual_check"]),
                                                        why), now)


def _finish_work(conn: sqlite3.Connection, run: sqlite3.Row, task: sqlite3.Row, user_id: int, result: str, report: str,
                 now: int, change, tests, committed, markers) -> None:
    if workflow.STAGE_ROLE.get(task["stage"]) != run["role"] or task["hold"]:
        return                                        # the task moved on meanwhile (cancelled, decided)
    if change is not None:
        conn.execute("UPDATE agent_tasks SET diff_stat = ?, diff = ? WHERE id = ?",
                     (change[0][:MAX_DIFF], change[1][:MAX_DIFF], task["id"]))
    if run["role"] == "programmer" and tests is None and result in ("done", "none"):
        conn.execute("UPDATE agent_tasks SET tests = '', tests_exit = NULL WHERE id = ?", (task["id"],))   # none now
    if tests is not None and run["role"] == "programmer":
        code, output = int(tests[0]), str(tests[1])[-MAX_TESTS:]
        conn.execute("UPDATE agent_tasks SET tests = ?, tests_exit = ? WHERE id = ?", (output, code, task["id"]))
        conn.execute("INSERT INTO agent_runs (task_id, role, purpose, model, status, result, report, created_at,"
                     " started_at, finished_at, provider) VALUES (?, 'tester', 'work', ?, 'done', ?, ?, ?, ?, ?, '')",
                     (task["id"], HUB_MODEL, "pass" if code == 0 else "fail", f"hub-test.sh: exit {code}\n{output}"[:MAX_REPORT],
                      now, now, now))
    if result == "stopped":
        _again_or_decide(conn, task, user_id, "failed", f"Your previous run on this task was ended ({report[:300]}). "
                         "What it changed is saved in /work: look at it and go on from there.", now)
        return
    if result == "failed":
        _again_or_decide(conn, task, user_id, "failed", f"Your previous run on this task failed ({report[:300]}). "
                         "What it changed is saved in /work: look at it and go on from there.", now)
        return
    if result == "none":                              # ask the same AI once for the line its answer lacked
        _queue(conn, user_id, task["id"], run["role"], "result", now, ref=run["id"], provider=run["provider"])
        return
    _apply(conn, run["role"], task, user_id, result, report, now, committed=committed, markers=markers,
           tests_exit=None if tests is None else int(tests[0]), run_id=run["id"])


def _apply(conn: sqlite3.Connection, role: str, task: sqlite3.Row, user_id: int, result: str, report: str, now: int,
           committed: bool | None = None, markers=(), tests_exit: int | None = None, run_id: int | None = None) -> None:
    """A role's valid answer moves the task: what it noticed goes on the board, into "For you" or to the manager, and
    the task goes on (workflow.after_run)."""
    if result not in workflow.RESULTS.get(role, ()):
        _enter(conn, user_id, task["id"], workflow.decision(task["stage"], task["returns"], bool(task["manual_check"]),
                                                            "format"), now)
        return
    found = reply.parse(report)
    if run_id is not None:                            # the report as the user reads it: without the markers
        conn.execute("UPDATE agent_runs SET report = ? WHERE id = ?", (found.text[:MAX_REPORT], run_id))
    # Only a bug outside the task (on the board at once) and a new feature (waits for the user) come from a role; a
    # "minor" is part of the task and is done in it (Janis, 21.11.2026: 29 improvements for one calculator).
    for item in [t for t in found.tasks if t.kind in ("bug", "major")][:FOUND_MAX]:
        board.add_from_ai(conn, task["project_id"], item.kind, item.title, item.body, approved=item.kind == "bug",
                          source="agent", needs=item.needs)
    for need in found.envs:                          # only the user can do it: "For you", never the board or a question
        todos.add_from_role(conn, task["project_id"], role, need, task["id"])
    if result == "not_testable":                     # the tester's steps to check it by hand
        todos.add_from_role(conn, task["project_id"], role, f"{task['title']}: {found.text}", task["id"], check=True)
    blocking = result == "question"
    asked = [questions.add(conn, task["project_id"], role, ask, task["id"], blocks=blocking) for ask in found.asks]
    asked = [q for q in asked if q is not None]
    if blocking and not questions.open_blocking(conn, task["id"]):
        result = "format" if not found.asks else result     # a question result without a question: nothing to wait for
    if result == "blocked" and not found.envs and not todos.open_for_task(conn, task["id"]):
        result = "format"
    if result == "format":
        step = workflow.decision(task["stage"], task["returns"], bool(task["manual_check"]), "format")
    elif blocking and task["asks"] + 1 > workflow.MAX_ASKS:
        step = workflow.decision(task["stage"], task["returns"], bool(task["manual_check"]), "asks")
    elif markers:                                     # conflicts with main left in the files: once more
        conn.execute("UPDATE agent_tasks SET resume = ? WHERE id = ?",
                     ("These files still have git conflict markers (<<<<<<<, =======, >>>>>>>): resolve them, keeping "
                      "what both sides need: " + ", ".join(markers)[:1500], task["id"]))
        step = workflow.back(task["returns"], bool(task["manual_check"]))
    else:
        diff = conn.execute("SELECT diff FROM agent_tasks WHERE id = ?", (task["id"],)).fetchone()["diff"]
        step = workflow.after_run(task["stage"], result, task["returns"], bool(task["manual_check"]),
                                  tests=None if tests_exit is None else tests_exit == 0,
                                  changed=bool(diff.strip()),
                                  stuck=role == "programmer" and task["returns"] > 0 and committed is False)
    if blocking and step.hold == "question":
        conn.execute("UPDATE agent_tasks SET asks = asks + 1 WHERE id = ?", (task["id"],))
    _enter(conn, user_id, task["id"], step, now)
    for question_id in asked:                         # the manager answers or asks the user (prompts.decide)
        _to_manager(conn, user_id, task["id"], question_id, now)


def _to_manager(conn: sqlite3.Connection, user_id: int, task_id: int, question_id: int, now: int) -> None:
    _queue(conn, user_id, task_id, "chef", "decide", now, ref=question_id)


def _finish_result(conn: sqlite3.Connection, run: sqlite3.Row, task: sqlite3.Row, user_id: int, result: str,
                   report: str, now: int) -> None:
    """The answer to "your report lacked its RESULT line": the line counts for the report asked about."""
    if workflow.STAGE_ROLE.get(task["stage"]) != run["role"] or task["hold"]:
        return
    parent = conn.execute("SELECT * FROM agent_runs WHERE id = ? AND task_id = ?", (run["ref"], task["id"])).fetchone()
    if parent is None or result not in workflow.RESULTS.get(run["role"], ()):
        _enter(conn, user_id, task["id"], workflow.decision(task["stage"], task["returns"], bool(task["manual_check"]),
                                                            "format"), now)
        return
    conn.execute("UPDATE agent_runs SET result = ? WHERE id = ?", (result, parent["id"]))
    tests_exit = task["tests_exit"] if run["role"] == "programmer" else None
    committed = bool(task["diff"].strip()) if run["role"] == "programmer" else None
    _apply(conn, run["role"], task, user_id, result, parent["report"], now, committed=committed, tests_exit=tests_exit,
           run_id=parent["id"])


def _finish_decide(conn: sqlite3.Connection, run: sqlite3.Row, task: sqlite3.Row, user_id: int, result: str,
                   report: str, now: int) -> None:
    """The manager on a role's question: he decided (the answer goes back, a waiting task goes on) or wrote it anew for
    the user. With "asks for everything" he never decides; anything unreadable goes to the user as it was asked."""
    question = questions.get(conn, run["ref"], task["project_id"])
    if question is None or question.status != "open" or question.via != "manager":
        return
    signals = reply.parse(report) if result not in ("failed", "stopped") else reply.Signals("")
    if signals.decide and autonomy_in(conn, user_id) != "all":
        questions.manager_answer(conn, question.id, signals.decide)
        _maybe_resume(conn, user_id, task["id"], "question", now)
    elif signals.asks:
        questions.rewrite(conn, question.id, signals.asks[0])
    else:
        questions.to_user(conn, question.id)


def _finish_explain(conn: sqlite3.Connection, task: sqlite3.Row, result: str, report: str) -> None:
    signals = reply.parse(report) if result not in ("failed", "stopped") else reply.Signals("")
    if signals.stuck is not None and task["hold"] == "decision":
        conn.execute("UPDATE agent_tasks SET advice = ?, advice_pick = ? WHERE id = ?",
                     (signals.stuck[1][:1500], signals.stuck[0], task["id"]))


def _finish_doc(conn: sqlite3.Connection, run: sqlite3.Row, task: sqlite3.Row, user_id: int, result: str, report: str,
                now: int):
    """The manager's documentation after the merge: the task is done either way; his memory notes are kept."""
    if task["stage"] != "documenting":
        return True
    notes, edits = {}, []
    if result == "done":
        parsed = memory.parse_answer(report)
        conn.execute("UPDATE agent_runs SET report = ? WHERE id = ?", (parsed.text[:MAX_REPORT], run["id"]))
        notes = dict(parsed.files or {})
        if parsed.memory:
            notes[memory.MEMORY_NAME] = parsed.memory
        edits = parsed.edits or []
    _enter(conn, user_id, task["id"], workflow.Step("done", "", task["returns"], bool(task["manual_check"])), now)
    return (user_id, task["project_id"], notes, edits, run["id"]) if (notes or edits) else True


def _maybe_resume(conn: sqlite3.Connection, user_id: int, task_id: int, hold: str, now: int) -> None:
    """A task that waited for answers or for the user's work goes on once nothing it waits for is open any more."""
    task = _task_row(conn, task_id)
    if task is None or task["hold"] != hold:
        return
    if hold == "question" and questions.open_blocking(conn, task_id):
        return
    if hold == "todo" and todos.open_for_task(conn, task_id):
        return
    _enter(conn, user_id, task_id, workflow.Step(task["stage"], "", task["returns"], bool(task["manual_check"])), now)


# --- the user's side of a task

def answer_question(user_id: int, question_id: int, text: str, now: int | None = None) -> bool:
    """The user's answer in "waiting for you": it goes to the role that asked (never into the manager chat), and a task
    that waited for it goes on. False if the question is not his or not open for him."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        question = questions.answer(conn, user_id, question_id, text)
        if question is None:
            return False
        if question.task_id is not None:
            _maybe_resume(conn, user_id, question.task_id, "question", now)
    return True


def check_todos(user_id: int, now: int | None = None) -> None:
    """Entries of "For you" were done or deleted: the user's tasks that waited for them go on once none they wait for is
    open (the notes of what he did are in their next package)."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        for row in conn.execute("SELECT t.id FROM agent_tasks t JOIN projects p ON p.id = t.project_id WHERE p.user_id = ?"
                                " AND t.hold = 'todo'", (user_id,)).fetchall():
            _maybe_resume(conn, user_id, row["id"], "todo", now)


def decide(user_id: int, task_id: int, choice: str, hint: str = "", now: int | None = None) -> bool:
    """The user's decision on a task that waits for one (workflow.after_decision): again (with an optional hint for the
    programmer), accept (merged as it is, checked by hand), cancel. False if it is not his or waits for nothing."""
    if choice not in workflow.CHOICES:
        raise ValueError("Unbekannte Entscheidung")
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        task = _owned_task(conn, user_id, task_id)
        if task is None or task["hold"] != "decision" or task["stage"] in workflow.ENDS:
            return False
        if choice == "again":
            conn.execute("UPDATE agent_tasks SET hint = ? WHERE id = ?", (" ".join((hint or "").split())[:MAX_HINT],
                                                                         task_id))
        step = workflow.after_decision(choice, task["stage"], task["returns"], bool(task["manual_check"]),
                                       bool(task["diff"].strip()))
        _enter(conn, user_id, task_id, step, now)   # merging needs no run: the runner asks for merges
    return True


def cancel(user_id: int, task_id: int, now: int | None = None) -> bool:
    """Stop a task at any time (its item goes into the trash; a running container is stopped by the runner)."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        task = _owned_task(conn, user_id, task_id)
        if task is None or task["stage"] in workflow.ENDS:
            return False
        _enter(conn, user_id, task_id, workflow.Step("cancelled", "", task["returns"], bool(task["manual_check"])), now)
    return True


# --- what the pages show

def list_tasks(user_id: int, project_id: int) -> list[Task]:
    """Newest first; empty if the project is not the user's."""
    with db.connect() as conn:
        rows = conn.execute("SELECT t.* FROM agent_tasks t JOIN projects p ON p.id = t.project_id"
                            " WHERE t.project_id = ? AND p.user_id = ? ORDER BY t.id DESC", (project_id, user_id)).fetchall()
    return [_task(r) for r in rows]


def get_task(user_id: int, task_id: int) -> Task | None:
    with db.connect() as conn:
        row = _owned_task(conn, user_id, task_id)
    return None if row is None else _task(row)


def task_runs(user_id: int, task_id: int) -> list[Run]:
    """All runs of a task in order; empty if the task is not the user's."""
    with db.connect() as conn:
        if _owned_task(conn, user_id, task_id) is None:
            return []
        rows = conn.execute("SELECT * FROM agent_runs WHERE task_id = ? ORDER BY id", (task_id,)).fetchall()
    return [_run(r) for r in rows]


def current_task(user_id: int, project_id: int) -> tuple[Task, str] | None:
    """The task of the project that is on its way (one at a time) and the context of its board item; None if nothing
    is on its way or the project is not his."""
    marks = ",".join("?" * len(OPEN))
    with db.connect() as conn:
        row = conn.execute(
            "SELECT t.*, COALESCE(b.details, '') AS details FROM agent_tasks t JOIN projects p ON p.id = t.project_id"
            f" LEFT JOIN board_items b ON b.id = t.item_id WHERE t.project_id = ? AND p.user_id = ? AND t.stage IN ({marks})"
            " ORDER BY t.id DESC LIMIT 1", (project_id, user_id, *OPEN)).fetchone()
    return None if row is None else (_task(row), row["details"])


def where(user_id: int, project_id: int) -> tuple[Task, str] | None:
    """How the project's task stands, for the line above the board and the roles' tabs: (task, state) with state one of
    working (a role works now), queued (its run waits for a free place), paused, no_ai, mac (waits for a Mac), merging,
    question, todo, decision; None when nothing is on its way."""
    current = current_task(user_id, project_id)
    if current is None:
        return None
    task = current[0]
    if task.hold:
        return task, task.hold
    with db.connect() as conn:
        if paused_in(conn, user_id):
            return task, "paused"
        if not aichoice.connected_list(conn, user_id):
            return task, "no_ai"
        row = conn.execute("SELECT status FROM agent_runs WHERE task_id = ? AND status IN ('queued', 'running')"
                           " ORDER BY status = 'running' DESC, id LIMIT 1", (task.id,)).fetchone()
    if task.stage == "merging":
        return task, "merging"
    if row is not None and row["status"] == "running":
        return task, "working"
    if task.needs == "mac" and workflow.STAGE_ROLE.get(task.stage) in MAC_ROLES:
        return task, "mac"
    return task, "queued"


def decisions(user_id: int, project_id: int) -> list[Task]:
    """Tasks of the project that wait for the user's decision ("waiting for you"), oldest first."""
    return sorted((t for t in list_tasks(user_id, project_id) if t.hold == "decision" and t.stage in OPEN),
                  key=lambda t: t.id)


def last_report(user_id: int, task_id: int) -> str:
    """The newest report of a work run of the task; "" if none or not the user's."""
    runs = [r for r in task_runs(user_id, task_id) if r.report and r.purpose == "work"]
    return runs[-1].report if runs else ""


def usage(user_id: int, project_id: int | None = None, role: str | None = None) -> dict:
    """What this user's agent runs used (of one project, or of all; of one role, or of all), from the usage ledger
    (usage.py, so also runs that were ended or switched to another AI): runs, tokens in (with the cache part) and out,
    seconds."""
    sums = ledger.totals(user_id, project_id=project_id, role=role, kind="run")
    return {"runs": sums["calls"], "tokens_in": sums["tokens_in"], "tokens_out": sums["tokens_out"],
            "cache_read": sums["cache_read"], "seconds": sums["seconds"]}


@dataclass
class RoleRun:
    """One run of a role as its tab shows it (rolepage.py): the run and what it belongs to."""
    run: Run
    task_title: str
    provider: str
    created_at: int
    started_at: int | None
    finished_at: int | None


ROLE_RUNS = 30            # runs a role's tab shows at most (newest)


def role_runs(user_id: int, project_id: int, role: str, limit: int = ROLE_RUNS) -> list[RoleRun]:
    """The newest runs of one role in one project, newest first; empty if the project is not the user's."""
    if role not in workflow.ROLES:
        return []
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT r.*, t.title AS task_title FROM agent_runs r JOIN agent_tasks t ON t.id = r.task_id"
            " JOIN projects p ON p.id = t.project_id WHERE p.id = ? AND p.user_id = ? AND r.role = ?"
            " AND r.status != 'cancelled' ORDER BY r.id DESC LIMIT ?",
            (project_id, user_id, role, max(1, min(int(limit), 200)))).fetchall()
    return [RoleRun(_run(r), r["task_title"], r["provider"] or "", r["created_at"], r["started_at"], r["finished_at"])
            for r in rows]


# --- merging and cleaning up (the runner does the git side: runner/workspace.py)
CLEAN_DAYS = 7            # finished tasks whose folders the runner may still have to delete


def pending_merges() -> list[dict]:
    """Runner: tasks whose reviewer said ok (or the user accepted them): their branch goes into the project's main."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT t.id, t.project_id, p.user_id FROM agent_tasks t JOIN projects p ON p.id = t.project_id"
            " WHERE t.stage = 'merging' AND t.hold = '' ORDER BY t.id").fetchall()
    return [{"task_id": r["id"], "project_id": r["project_id"], "user_id": r["user_id"],
             "branch": branch_name(r["id"])} for r in rows]


def merge_done(task_id: int, ok: bool, now: int | None = None) -> bool:
    """Runner: the merge went through (on to the documentation), or main had moved and conflicts (back to the
    programmer, whose next run brings main into the branch first)."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        task = conn.execute("SELECT * FROM agent_tasks WHERE id = ? AND stage = 'merging' AND hold = ''",
                            (task_id,)).fetchone()
        if task is None:
            return False
        user_id = _owner(conn, task_id)
        if not ok:
            conn.execute("UPDATE agent_tasks SET resume = ? WHERE id = ?",
                         ("The project's main changed while you worked; the hub brings it into your branch now. "
                          "Resolve any conflict markers and check that everything still works.", task_id))
        _enter(conn, user_id, task_id, workflow.after_merge(ok, task["returns"], bool(task["manual_check"])), now)
    return True


def queue_wipes(conn: sqlite3.Connection, project_id: int) -> None:
    """A project is being deleted (projects.delete_project, users.purge_deleted; same transaction, before the rows
    go): the runner has to delete its code repository and the work folders of its tasks."""
    now = int(time.time())
    conn.execute("INSERT OR IGNORE INTO work_wipes (kind, ref, created_at) VALUES ('project', ?, ?)", (project_id, now))
    conn.execute("INSERT OR IGNORE INTO work_wipes (kind, ref, created_at)"
                 " SELECT 'task', id, ? FROM agent_tasks WHERE project_id = ?", (now, project_id))


WIPE_KINDS = ("project", "task")


def pending_wipes() -> list[dict]:
    """Runner: the folders of deleted projects that are still to be deleted, as {"kind", "ref"}."""
    with db.connect() as conn:
        return [{"kind": r["kind"], "ref": r["ref"]} for r in conn.execute(
            "SELECT kind, ref FROM work_wipes ORDER BY created_at, kind, ref LIMIT 200")]


def wipe_done(kind: str, ref: int) -> bool:
    """Runner: the folder is gone; the note about it goes too."""
    with db.connect() as conn:
        return conn.execute("DELETE FROM work_wipes WHERE kind = ? AND ref = ?", (kind, ref)).rowcount == 1


def finished_tasks(now: int | None = None) -> list[int]:
    """Runner: tasks of the last CLEAN_DAYS that are over: their folders can go (the branch stays in the project)."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        return [r["id"] for r in conn.execute(
            "SELECT id FROM agent_tasks WHERE finished_at > ? AND stage IN ('done', 'cancelled') ORDER BY id",
            (now - CLEAN_DAYS * 86400,))]
