"""Tasks and runs of the agents, stored in SQLite. Standard library only.

A *task* is one board item on its way through the chain (see workflow.py). Every stage of a task
has one *run*: a job for the runner (Claude Code on the Pi or the Mac). Two sides:

- User side (`start_task`, `decide`, `list_tasks`, ...): every function gets the `user_id` and
  checks that the project is his; foreign things are "not found" or "nothing done".
- Runner side (`claim_next`, `finish_run`): trusted code. The runner passes no user: user and project
  come from the task in the database, so a run can only ever touch its own user's data.

Rules (PROJEKT.md, "Trennung der Claude-Konten"): a run starts only when the user's own Claude is
connected (no fallback to somebody else), and the runner gets nothing but the job it claimed.
"""
import sqlite3
import time
from dataclasses import dataclass, field

from . import (ai_link, aichoice, board, catalog, credentials, db, failures, files, memory, models, prompts, questions,
               reply, serversettings, toolcheck, workflow)

# Models and effort levels are not fixed here: they come from catalog.py (Janis, 14.11.2026). A role without a
# choice gets the provider's default model and that model's default level. Since 15.11.2026 the choice is kept per
# role AND per AI ("model.<role>.<provider>"), so switching the standard AI (aichoice.py) and back finds it again;
# the older keys "model.<role>" / "effort.<role>" still count for the provider their model belongs to (no conversion).
NEEDS = ("any", "mac")
# How freely the manager decides (Janis, 07.11.2026): fully on its own, asks for big decisions, asks for small
# things too. It is a threshold, not a switch: the manager first tries to derive the answer from the project.
AUTONOMY = ("auto", "major", "all")
DEFAULT_AUTONOMY = "major"
# Web and code together (code has the open internet) or apart (web search, code without internet). Janis, 08.11.2026.
NET_MODES = ("together", "apart")
DEFAULT_NET = "together"
# Tester and reviewer check what is in /work and need no internet (20.11.2026): code they run can send nothing out.
ROLE_NET = {"tester": "apart", "reviewer": "apart"}
KIND_ORDER = ("bug", "minor", "major")   # the programmer works in this order
TASK_SECONDS = 2 * 3600                  # time limit per task, then it goes to the user
RUN_SECONDS = 20 * 60                    # a run that reports nothing for so long is dead
# How many AI containers run at once (chat answers and agent runs together) is a setting of the owner
# (serversettings.ai_parallel, Janis 15.11.2026): 1 on a small server, more or no limit on a big one.
MAX_REPORT = 20000                       # characters of a report that are kept
FOUND_MAX = 3                            # items a run may put on the board (prompts.FOUND)
MAX_DIFF = 60000                         # characters of a task's change kept (runner/workspace.py cuts it too)
MAX_TESTS = 6000                         # characters of the output of the project's tests kept
HUB_MODEL = "hub"                        # the "model" of a test run the hub made itself (no AI, no tokens)
ACTIVE = workflow.STAGES                 # stages in which a task is still moving
OPEN_STATUSES = ACTIVE + ("escalated",)  # a board item with such a task is "taken"


@dataclass
class Task:
    id: int
    project_id: int
    item_id: int | None
    title: str
    kind: str
    needs: str
    status: str
    round: int
    manual_check: bool
    note: str
    created_at: int
    deadline: int
    finished_at: int | None


@dataclass
class Run:
    id: int
    task_id: int
    role: str
    model: str
    status: str            # queued, running, done, failed, cancelled
    result: str | None
    report: str
    tokens_in: int
    tokens_out: int
    seconds: int


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
    round: int
    note: str                       # the user's remark from his last rejection (data, not an order)
    reports: list[tuple[str, str]]  # (role, report) of the earlier runs of this task (data)
    net: str = DEFAULT_NET          # web and code together (open internet) or apart, the role's switch
    effort: str = ""                # effort level of the model (catalog.py); empty = the program's own default
    provider: str = "claude"        # which AI does the run (aichoice.py); the runner picks the adapter by it
    prompt: str = ""                # the package for the AI (prompts.run): rules, memory, project, task
    mode: str = ""                  # "brief": one answer without tools and without /work (prompts.brief_run)
    route: dict = field(default_factory=dict)   # the own AI: its address and model name (ai_link.route_in)
    hub_tools: list = field(default_factory=list)   # the hub's tools this AI gets (toolcheck.hub_tools)
    credential: str = "plan"        # the user's plan or his API key (credentials.py)
    files: list = field(default_factory=list)   # the user's files for /files (files.for_agents): id, name, area, size
    links: list = field(default_factory=list)   # and the links: name, address
    images: bool = False            # the model sees pictures (catalog.sees_images): the adapter lets it look at them


def _task(row: sqlite3.Row) -> Task:
    return Task(row["id"], row["project_id"], row["item_id"], row["title"], row["kind"], row["needs"],
                row["status"], row["round"], bool(row["manual_check"]), row["note"],
                row["created_at"], row["deadline"], row["finished_at"])


def _run(row: sqlite3.Row) -> Run:
    return Run(row["id"], row["task_id"], row["role"], row["model"], row["status"], row["result"],
               row["report"], row["tokens_in"], row["tokens_out"], row["seconds"])


def branch_name(task_id: int) -> str:
    return f"agent/task-{int(task_id)}"


def _owner(conn: sqlite3.Connection, task_id: int) -> int | None:
    row = conn.execute(
        "SELECT p.user_id FROM agent_tasks t JOIN projects p ON p.id = t.project_id WHERE t.id = ?",
        (task_id,),
    ).fetchone()
    return None if row is None else row["user_id"]


def _owned_task(conn: sqlite3.Connection, user_id: int, task_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT t.* FROM agent_tasks t JOIN projects p ON p.id = t.project_id"
        " WHERE t.id = ? AND p.user_id = ?", (task_id, user_id),
    ).fetchone()


# --- settings per user: model and on/off per role, strictness of the chief

def _setting(conn: sqlite3.Connection, user_id: int, key: str, default: str) -> str:
    row = conn.execute(
        "SELECT value FROM agent_settings WHERE user_id = ? AND key = ?", (user_id, key)
    ).fetchone()
    return default if row is None else row["value"]


def _enabled(conn: sqlite3.Connection, user_id: int) -> frozenset[str]:
    roles = {r for r in workflow.ROLES if _setting(conn, user_id, f"enabled.{r}", "1") == "1"}
    return frozenset(roles | {"programmer"})   # without the programmer nothing happens at all


def _choice(conn: sqlite3.Connection, user_id: int, role: str, provider: str | None = None) -> tuple[str, str]:
    """(model, effort) of a role for one AI (default: the user's standard), made valid against the current list
    (catalog.resolve): a model that left the list becomes the default model, a missing level the model's default."""
    provider = provider or aichoice.default_in(conn, user_id)
    model = _setting(conn, user_id, f"model.{role}.{provider}", "")
    effort = _setting(conn, user_id, f"effort.{role}.{provider}", "")
    if not model:                                  # a choice from before 15.11.2026, if it is one of this AI
        old = _setting(conn, user_id, f"model.{role}", "")
        if old and catalog.provider_of(old) == provider and catalog.find(old):
            model, effort = old, effort or _setting(conn, user_id, f"effort.{role}", "")
    if not model and (start := catalog.role_default(provider, role)):   # the AI's start for this role (catalog)
        model, effort = start[0], effort or start[1]
    ids = models.allowed(conn, user_id, provider)
    if ids is not None and model not in ids:   # not (any more) in his account's list: the role's start, the default, any
        start = catalog.role_default(provider, role)
        default = catalog.provider(provider).default_model
        model = next((m for m in ((start or ("",))[0], default) if m in ids), None) or sorted(ids)[0]
        effort = start[1] if start and start[0] == model else effort
    return catalog.resolve(model, effort, provider)


def _model(conn: sqlite3.Connection, user_id: int, role: str) -> str:
    return _choice(conn, user_id, role)[0]


def effort_in(conn: sqlite3.Connection, user_id: int, role: str) -> str:
    """The effort level of a role for this user, inside an open connection (the manager chat uses "chef")."""
    return _choice(conn, user_id, role)[1]


def _strictness(conn: sqlite3.Connection, user_id: int) -> str:
    return _setting(conn, user_id, "strictness", "normal")


def model_in(conn: sqlite3.Connection, user_id: int, role: str) -> str:
    """The model of a role for this user, inside an open connection (the manager chat uses "chef")."""
    return _model(conn, user_id, role)


def autonomy_in(conn: sqlite3.Connection, user_id: int) -> str:
    """How freely the manager decides (Janis, 07.11.2026), see AUTONOMY."""
    return _setting(conn, user_id, "autonomy", DEFAULT_AUTONOMY)


def net_in(conn: sqlite3.Connection, user_id: int, role: str) -> str:
    """Web and code together or apart for one role (see NET_MODES). Per agent, like the model (Janis, 08.11.2026):
    the switch in the manager chat is the manager's ("chef"), the others come with the tabs of their roles."""
    return _setting(conn, user_id, f"net.{role}", ROLE_NET.get(role, DEFAULT_NET))


def settings(user_id: int) -> dict:
    """{"strictness", "autonomy", "provider", "roles": {role: {"enabled", "model", "effort", "net"}}, "models"}, defaults
    filled in. Model and effort are those of the standard AI ("provider"). "models": per AI the model ids his account
    offers (models.allowed; None = not known yet), for the drop-downs."""
    with db.connect() as conn:
        enabled = _enabled(conn, user_id)
        provider = aichoice.default_in(conn, user_id)
        roles = {}
        for r in workflow.ROLES:
            model, effort = _choice(conn, user_id, r, provider)
            roles[r] = {"enabled": r in enabled, "model": model, "effort": effort, "net": net_in(conn, user_id, r)}
        return {"strictness": _strictness(conn, user_id), "autonomy": autonomy_in(conn, user_id),
                "provider": provider, "roles": roles,
                "models": {p: models.allowed(conn, user_id, p) for p in catalog.PROVIDERS},
                "model_names": {f"own-{r['slot']}": r["label"] for r in ai_link.custom_rows(conn, user_id)}}


def configure(user_id: int, role: str | None = None, *, enabled: bool | None = None,
              model: str | None = None, strictness: str | None = None, autonomy: str | None = None,
              net: str | None = None, effort: str | None = None) -> None:
    """Change a setting of this user. Raises ValueError for unknown values or for switching the
    programmer off. Model and effort are checked against the list (catalog.py); an effort is checked against the
    model sent with it, or the role's current model. A new model alone keeps the saved level where the model has
    it, otherwise its default level counts (catalog.resolve)."""
    changes: list[tuple[str, str]] = []
    if strictness is not None:
        if strictness not in workflow.STRICTNESS:
            raise ValueError("Unbekannte Strenge")
        changes.append(("strictness", strictness))
    if autonomy is not None:
        if autonomy not in AUTONOMY:
            raise ValueError("Unbekannte Selbstständigkeit")
        changes.append(("autonomy", autonomy))
    if enabled is not None or model is not None or net is not None or effort is not None:
        if role not in workflow.ROLES:
            raise ValueError("Unbekannte Rolle")
        if net is not None:
            if net not in NET_MODES:
                raise ValueError("Unbekannter Netzmodus")
            changes.append((f"net.{role}", net))
        if enabled is not None:
            if role == "programmer" and not enabled:
                raise ValueError("Der Programmierer bleibt immer an")
            changes.append((f"enabled.{role}", "1" if enabled else "0"))
        if model is not None or effort is not None:
            if model is None:
                with db.connect() as conn:
                    model_for_effort = _model(conn, user_id, role)
            else:
                model_for_effort = model
            try:
                catalog.check(model_for_effort, effort)
            except ValueError:
                raise ValueError("Unbekanntes Modell oder unbekannte Stufe") from None
            with db.connect() as conn:
                if model is not None and not models.permits(conn, user_id, model):
                    raise ValueError("Modell nicht im Konto")
            provider = catalog.provider_of(model_for_effort)     # kept per AI: switching back finds it again
            if model is not None:
                changes.append((f"model.{role}.{provider}", model))   # the saved level stays (resolve on reading)
            if effort is not None:
                changes.append((f"effort.{role}.{provider}", effort))
    with db.connect() as conn:
        for key, value in changes:
            conn.execute(
                "INSERT INTO agent_settings (user_id, key, value) VALUES (?, ?, ?)"
                " ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
                (user_id, key, value),
            )


# --- the chief picks, the user starts

def _taken(conn: sqlite3.Connection, item_id: int) -> bool:
    marks = ",".join("?" * len(OPEN_STATUSES))
    return conn.execute(
        f"SELECT 1 FROM agent_tasks WHERE item_id = ? AND status IN ({marks})",
        (item_id, *OPEN_STATUSES),
    ).fetchone() is not None


def pick_next(user_id: int, project_id: int) -> board.Item | None:
    """The next agreed item for the programmer: bugs, then small, then major updates, each in the
    order of the board. Items that already have an unfinished task are skipped."""
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM projects WHERE id = ? AND user_id = ?",
                        (project_id, user_id)).fetchone() is None:
            return None
        for kind in KIND_ORDER:
            for row in conn.execute(
                "SELECT * FROM board_items WHERE project_id = ? AND kind = ? AND status = 'open'"
                " ORDER BY position, id", (project_id, kind),
            ):
                if not _taken(conn, row["id"]):
                    return board._to_item(row)
    return None


def _run_provider(conn: sqlite3.Connection, user_id: int, task_id: int, role: str) -> str:
    """The AI of a new run: the standard. The reviewer takes another of the user's AIs than the programmer of this
    task when he has two (Janis: one model overlooks its own mistakes)."""
    order = aichoice.order_in(conn, user_id)
    if role == "reviewer" and len(order) > 1:
        row = conn.execute("SELECT provider FROM agent_runs WHERE task_id = ? AND role = 'programmer'"
                           " ORDER BY id DESC LIMIT 1", (task_id,)).fetchone()
        if row is not None:
            return next((p for p in order if p != row["provider"]), order[0])
    return order[0]


def _queue(conn: sqlite3.Connection, user_id: int, task_id: int, status: str, now: int) -> None:
    """Create the run for the stage the task has just entered (nothing for the user's own stage)."""
    role = workflow.STAGE_ROLE.get(status)
    if role is not None:
        provider = _run_provider(conn, user_id, task_id, role)
        model, effort = _choice(conn, user_id, role, provider)
        conn.execute(
            "INSERT INTO agent_runs (task_id, role, model, effort, provider, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'queued', ?)", (task_id, role, model, effort, provider, now),
        )


def _enter(conn: sqlite3.Connection, user_id: int, task_id: int, step: workflow.Step,
           now: int, note: str | None = None) -> None:
    finished = now if step.status in ("done", "escalated", "cancelled") else None
    conn.execute(
        "UPDATE agent_tasks SET status = ?, round = ?, manual_check = ?, finished_at = ?"
        + (", note = ?" if note is not None else "") + " WHERE id = ?",
        (step.status, step.round, int(step.manual_check), finished,
         *([note] if note is not None else []), task_id),
    )
    if step.status in ("done", "escalated", "cancelled"):
        conn.execute("UPDATE agent_runs SET status = 'cancelled' WHERE task_id = ? AND status = 'queued'",
                     (task_id,))
    if step.status == "cancelled":   # the user stopped it: the item stays on the board, but never starts by itself again
        conn.execute("UPDATE board_items SET auto = 0 WHERE id = (SELECT item_id FROM agent_tasks WHERE id = ?)",
                     (task_id,))
    if step.status == "done":
        # Finished work is not deleted: its board item moves into the archive (Janis, 07.11.2026).
        conn.execute("UPDATE board_items SET status = 'archived'"
                     " WHERE id = (SELECT item_id FROM agent_tasks WHERE id = ?) AND status = 'open'", (task_id,))
    _queue(conn, user_id, task_id, step.status, now)


def start_task(user_id: int, project_id: int, item_id: int, needs: str = "any",
               now: int | None = None) -> Task:
    """Give an agreed board item to the programmer. Raises ValueError if the item is not an open
    item of one of the user's projects, already has an unfinished task, or `needs` is unknown."""
    if needs not in NEEDS:
        raise ValueError("Unbekannte Anforderung")
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        item = conn.execute(
            "SELECT b.* FROM board_items b JOIN projects p ON p.id = b.project_id"
            " WHERE b.id = ? AND b.project_id = ? AND p.user_id = ? AND b.status = 'open'",
            (item_id, project_id, user_id),
        ).fetchone()
        if item is None:
            raise ValueError("Unbekannter Punkt")
        if _taken(conn, item_id):
            raise ValueError("Punkt ist schon in Arbeit")
        task_id = _start(conn, user_id, item, needs, now)
        row = conn.execute("SELECT * FROM agent_tasks WHERE id = ?", (task_id,)).fetchone()
    return _task(row)


def _start(conn: sqlite3.Connection, user_id: int, item: sqlite3.Row, needs: str, now: int) -> int:
    """The task of an open board item and its first run (the caller checked owner and item)."""
    # never the number of a deleted task whose work folder the runner has not deleted yet
    new_id = db.fresh_id(conn, "agent_tasks", "SELECT MAX(ref) FROM work_wipes WHERE kind = 'task'")
    conn.execute(
        "INSERT INTO agent_tasks (id, project_id, item_id, title, kind, needs, status, round,"
        " created_at, deadline) VALUES (?, ?, ?, ?, ?, ?, 'coding', 1, ?, ?)",
        (new_id, item["project_id"], item["id"], item["title"], item["kind"], needs, now, now + TASK_SECONDS),
    )
    _queue(conn, user_id, new_id, "coding", now)
    return new_id


def autostart(conn: sqlite3.Connection, now: int) -> int:
    """Start the next item that goes to the programmer by itself (board_items.auto: the manager put it on the board
    from the user's request, or the user accepted a suggestion; Janis 19.11.2026). Per project at most one task on its
    way at a time (they build on each other and share one repository), bugs first, then small, then major updates,
    each in the order of the board; only for a user with an AI connected. Returns how many started."""
    started = 0
    projects = conn.execute(
        "SELECT DISTINCT b.project_id, p.user_id FROM board_items b JOIN projects p ON p.id = b.project_id"
        " JOIN users u ON u.id = p.user_id WHERE b.auto = 1 AND b.status = 'open' AND u.deleted_at IS NULL").fetchall()
    marks = ",".join("?" * len(ACTIVE))
    for row in projects:
        if conn.execute(f"SELECT 1 FROM agent_tasks WHERE project_id = ? AND status IN ({marks})",
                        (row["project_id"], *ACTIVE)).fetchone():
            continue
        # A piece that went to the user stops the ones after it: they may build on it (20.11.2026). Only tasks of
        # items that started by themselves count, so an old escalated task does not hold up the board.
        if conn.execute("SELECT 1 FROM agent_tasks t JOIN board_items b ON b.id = t.item_id WHERE t.project_id = ?"
                        " AND t.status = 'escalated' AND b.auto = 1", (row["project_id"],)).fetchone():
            continue
        if not aichoice.connected_list(conn, row["user_id"]):
            continue
        for kind in KIND_ORDER:
            item = next((i for i in conn.execute(
                "SELECT * FROM board_items WHERE project_id = ? AND kind = ? AND status = 'open' AND auto = 1"
                " ORDER BY position, id", (row["project_id"], kind)) if not _taken(conn, i["id"])), None)
            if item is not None:
                _start(conn, row["user_id"], item, "any", now)
                started += 1
                break
    return started


def list_tasks(user_id: int, project_id: int) -> list[Task]:
    """Newest first; empty if the project is not the user's."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT t.* FROM agent_tasks t JOIN projects p ON p.id = t.project_id"
            " WHERE t.project_id = ? AND p.user_id = ? ORDER BY t.id DESC", (project_id, user_id),
        ).fetchall()
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


def waiting_reason(user_id: int, task: Task) -> str | None:
    """How a task at a role's stage stands: "no_ai" (none of his AIs is connected), "running" (a role works on it now)
    or None (its run waits to be picked up, the user's stage, or finished)."""
    if task.status in ACTIVE and task.status in workflow.STAGE_ROLE:
        with db.connect() as conn:
            if not aichoice.connected_list(conn, user_id):
                return "no_ai"
            row = conn.execute("SELECT status FROM agent_runs WHERE task_id = ? ORDER BY id DESC LIMIT 1",
                               (task.id,)).fetchone()
            if row is not None:
                return "running" if row["status"] == "running" else None
    return None


def usage(user_id: int, project_id: int | None = None, role: str | None = None) -> dict:
    """Tokens and seconds used by this user's runs (of one project, or of all; of one role, or of all)."""
    sql = ("SELECT COALESCE(SUM(r.tokens_in), 0) AS tokens_in, COALESCE(SUM(r.tokens_out), 0) AS tokens_out,"
           " COALESCE(SUM(r.seconds), 0) AS seconds, COUNT(r.id) AS runs FROM agent_runs r"
           " JOIN agent_tasks t ON t.id = r.task_id JOIN projects p ON p.id = t.project_id"
           " WHERE p.user_id = ? AND r.status IN ('done', 'failed')")
    args: list = [user_id]
    if project_id is not None:
        sql += " AND p.id = ?"
        args.append(project_id)
    if role is not None:
        sql += " AND r.role = ?"
        args.append(role)
    with db.connect() as conn:
        return dict(conn.execute(sql, args).fetchone())


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


def current_task(user_id: int, project_id: int) -> tuple[Task, str] | None:
    """The task the roles of the user's project work on now (one at a time per project, autostart) and the context
    of its board item, for the programmer's tab; None if nothing is on its way or the project is not his."""
    marks = ",".join("?" * len(ACTIVE))
    with db.connect() as conn:
        row = conn.execute(
            "SELECT t.*, COALESCE(b.details, '') AS details FROM agent_tasks t JOIN projects p ON p.id = t.project_id"
            f" LEFT JOIN board_items b ON b.id = t.item_id WHERE t.project_id = ? AND p.user_id = ? AND t.status IN ({marks})"
            " ORDER BY t.id DESC LIMIT 1", (project_id, user_id, *ACTIVE)).fetchone()
    return None if row is None else (_task(row), row["details"])


def role_runs(user_id: int, project_id: int, role: str, limit: int = ROLE_RUNS) -> list[RoleRun]:
    """The newest runs of one role in one project, newest first; empty if the project is not the user's."""
    if role not in workflow.ROLES:
        return []
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT r.*, t.title AS task_title FROM agent_runs r JOIN agent_tasks t ON t.id = r.task_id"
            " JOIN projects p ON p.id = t.project_id WHERE p.id = ? AND p.user_id = ? AND r.role = ?"
            " ORDER BY r.id DESC LIMIT ?", (project_id, user_id, role, max(1, min(int(limit), 200))),
        ).fetchall()
    return [RoleRun(_run(r), r["task_title"], r["provider"] or "", r["created_at"], r["started_at"], r["finished_at"])
            for r in rows]


WAITS_FOR_USER = ("awaiting_approval", "escalated")


def waiting_tasks(user_id: int, project_id: int) -> list[Task]:
    """Tasks of the project that wait for the user (approval, or they need him), oldest first."""
    return sorted((t for t in list_tasks(user_id, project_id) if t.status in WAITS_FOR_USER), key=lambda t: t.id)


def decide(user_id: int, task_id: int, decision: str, note: str = "", now: int | None = None) -> bool:
    """The user's decision. `approve` (task awaits approval), `reject` (awaits approval or
    escalated: a new cycle with his note), `cancel` (any unfinished task). False if it does not fit."""
    if decision not in ("approve", "reject", "cancel"):
        raise ValueError("Unbekannte Entscheidung")
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        row = _owned_task(conn, user_id, task_id)
        if row is None:
            return False
        status, mc, rnd = row["status"], bool(row["manual_check"]), row["round"]
        if decision == "approve" and status == "awaiting_approval":
            step = workflow.after_approval(rnd, mc, _enabled(conn, user_id))
            note_value = None
            # The time the task waited for the user does not count: the manager's documentation gets a fresh limit
            # (19.11.2026: approved a day later, the task went past its deadline at once and the documentation was cut).
            conn.execute("UPDATE agent_tasks SET deadline = ? WHERE id = ?", (now + TASK_SECONDS, task_id))
        elif decision == "reject" and status in ("awaiting_approval", "escalated"):
            step = workflow.after_rejection(mc)
            note_value = note.strip()[:1000]
            conn.execute("UPDATE agent_tasks SET deadline = ?, merged = 0 WHERE id = ?", (now + TASK_SECONDS, task_id))
        elif decision == "cancel" and status in OPEN_STATUSES:
            step, note_value = workflow.Step("cancelled", rnd, mc), None
        else:
            return False
        _enter(conn, user_id, task_id, step, now, note_value)
    return True


# --- the runner

def _escalate_late(conn: sqlite3.Connection, now: int) -> None:
    """Tasks past their deadline and runs that went silent go to the user."""
    for run in conn.execute(
        "SELECT r.id, r.task_id FROM agent_runs r WHERE r.status = 'running' AND r.started_at < ?",
        (now - RUN_SECONDS,),
    ).fetchall():
        conn.execute("UPDATE agent_runs SET status = 'failed', result = 'failed', finished_at = ? WHERE id = ?",
                     (now, run["id"]))
        task = conn.execute("SELECT * FROM agent_tasks WHERE id = ?", (run["task_id"],)).fetchone()
        if task["status"] in ACTIVE:
            _enter(conn, _owner(conn, task["id"]), task["id"],
                   workflow.Step("escalated", task["round"], bool(task["manual_check"])), now)
    for task in conn.execute(
        "SELECT * FROM agent_tasks WHERE status IN ('coding','testing','reviewing','documenting')"
        " AND deadline < ?", (now,),
    ).fetchall():
        _enter(conn, _owner(conn, task["id"]), task["id"],
               workflow.Step("escalated", task["round"], bool(task["manual_check"])), now)


def _skip_waiting_tests(conn: sqlite3.Connection, can_mac: bool, now: int) -> None:
    """No Mac and a test that needs it: the chief skips it if the user's strictness allows."""
    if can_mac:
        return
    for run in conn.execute(
        "SELECT r.id, t.id AS task_id, t.kind, t.round, t.manual_check FROM agent_runs r"
        " JOIN agent_tasks t ON t.id = r.task_id"
        " WHERE r.status = 'queued' AND r.role = 'tester' AND t.needs = 'mac' AND t.status = 'testing'"
    ).fetchall():
        user_id = _owner(conn, run["task_id"])
        if workflow.test_may_be_skipped(_strictness(conn, user_id), run["kind"]):
            conn.execute("UPDATE agent_runs SET status = 'done', result = 'skipped', finished_at = ?,"
                         " report = 'Test uebersprungen: Mac nicht erreichbar.' WHERE id = ?", (now, run["id"]))
            step = workflow.advance("testing", run["round"], bool(run["manual_check"]), "skipped",
                                    _enabled(conn, user_id))
            _enter(conn, user_id, run["task_id"], step, now)


def slot_free(conn: sqlite3.Connection) -> bool:
    """May one more AI container start now? Counts the running agent runs and chat answers of all users."""
    limit = serversettings.ai_parallel()
    if not limit:
        return True
    running = (conn.execute("SELECT COUNT(*) FROM agent_runs WHERE status = 'running'").fetchone()[0]
               + conn.execute("SELECT COUNT(*) FROM chat_messages WHERE status = 'running'").fetchone()[0])
    return running < limit


def claim_next(can_mac: bool, now: int | None = None) -> Job | None:
    """Runner: take the oldest run that may start now, or None. Only as many AI containers as the owner allows.

    A run is skipped (it keeps waiting) when none of its user's AIs is connected or it needs the Mac and `can_mac` is
    False. If the AI of the run is not connected any more, the user's next AI takes it (aichoice.order_in); nobody
    else's connection is ever used. The chef's run after an approval waits until the runner merged the branch.
    """
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        _escalate_late(conn, now)
        _skip_waiting_tests(conn, can_mac, now)
        autostart(conn, now)
        if not slot_free(conn):
            return None
        for run in conn.execute(
            "SELECT r.*, t.needs FROM agent_runs r JOIN agent_tasks t ON t.id = r.task_id"
            " WHERE r.status = 'queued' ORDER BY r.created_at, r.id"
        ).fetchall():
            if run["needs"] == "mac" and not can_mac:
                continue
            user_id = _owner(conn, run["task_id"])
            task = conn.execute("SELECT * FROM agent_tasks WHERE id = ?", (run["task_id"],)).fetchone()
            if run["role"] == "chef" and not task["merged"]:
                continue                                   # the runner merges the approved branch first
            provider, model, effort = run["provider"], run["model"], run["effort"]
            if not aichoice.connected_in(conn, user_id, provider) or aichoice.resting(conn, user_id, provider):
                tried = set(run["tried"].split(",")) - {""}
                order = [p for p in aichoice.order_in(conn, user_id) if p not in tried] or aichoice.order_in(conn, user_id)
                if not aichoice.connected_in(conn, user_id, order[0]):
                    continue                               # none of his AIs: the run waits
                if order[0] != provider:                   # its AI is gone or resting after a used-up quota
                    provider = order[0]
                    model, effort = _choice(conn, user_id, run["role"], provider)
            way = (run["credential"] if run["credential"] == "api" and credentials.api_usable(conn, user_id, provider, "run")
                   else credentials.first(conn, user_id, provider, "run"))
            conn.execute("UPDATE agent_runs SET status = 'running', started_at = ?, provider = ?, model = ?, effort = ?,"
                         " credential = ? WHERE id = ?", (now, provider, model, effort, way, run["id"]))
            reports = [(r["role"], r["report"]) for r in conn.execute(
                "SELECT role, report FROM agent_runs WHERE task_id = ? AND status = 'done' AND report != ''"
                " ORDER BY id", (task["id"],))]
            job = Job(run["id"], user_id, task["project_id"], task["id"], run["role"], model,
                      branch_name(task["id"]), task["title"], task["kind"], task["round"],
                      task["note"], reports, net_in(conn, user_id, run["role"]), effort, provider)
            job.mode = "brief" if prompts.brief_run(conn, job) else ""
            job.route = ai_link.route_in(conn, user_id, provider, model)
            job.hub_tools = toolcheck.hub_tools(provider)
            job.credential = way
            job.prompt = prompts.run(conn, job, brief=job.mode == "brief")
            if not job.mode:   # a brief run reads no files
                job.files, job.links = files.for_agents(conn, user_id, task["project_id"])
            job.images = catalog.sees_images(model)
            return job
    return None


def _try_again(conn: sqlite3.Connection, run: sqlite3.Row, user_id: int, report: str, tokens_in: int,
               tokens_out: int) -> bool:
    """A run failed for its AI, not for its work (failures.py): the same run is queued again, with the user's API key
    when the plan ran out (only plan -> key, never back), else with his next AI that has not failed it yet (noted in
    `tried`, so nothing goes round in circles). An AI whose quota ran out rests a while (aichoice.rest). False when
    there is no other way: then the run fails as before."""
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


def finish_run(run_id: int, result: str, report: str = "", tokens_in: int = 0, tokens_out: int = 0,
               seconds: int = 0, now: int | None = None, change: tuple[str, str] | None = None,
               tests: tuple[int, str] | None = None) -> bool:
    """Runner: a run is over. `result` must fit the role (workflow.RESULTS). The task moves on
    (or goes back, or to the user) and the next run is queued. False if the run is not running
    any more (cancelled, timed out) or its task has moved on. Raises ValueError for a bad result.

    `change` (stat, diff): what the task changed so far, after a run that commits. `tests` (exit code, output): the
    project's own tests the hub ran after the programmer (20.11.2026). They decide instead of an AI tester: green goes
    on to the reviewer, red back to the programmer; the hub notes them as the tester's run (model "hub")."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        run = conn.execute("SELECT * FROM agent_runs WHERE id = ? AND status = 'running'", (run_id,)).fetchone()
        if run is None:
            return False
        task = conn.execute("SELECT * FROM agent_tasks WHERE id = ?", (run["task_id"],)).fetchone()
        if workflow.STAGE_ROLE.get(task["status"]) != run["role"]:
            return False
        user_id = _owner(conn, task["id"])
        if result == "failed" and _try_again(conn, run, user_id, report or "", tokens_in, tokens_out):
            return True
        if result not in workflow.RESULTS.get(run["role"], ()) or result == "skipped":   # skipped: the hub's own
            report = (report + f"\n\n(The run gave the result {result[:20]!r}, which this role does not have.)").strip()
            result = "failed"
        if run["role"] == "chef" and result == "done":    # the manager keeps the memory files up after the work
            parsed = memory.parse_answer(report)
            report = parsed.text
            notes = dict(parsed.files or {})
            if parsed.memory:
                notes[memory.MEMORY_NAME] = parsed.memory
            pending_notes = (user_id, task["project_id"], notes, parsed.edits or [])
        else:
            pending_notes = None
        enabled = _enabled(conn, user_id)
        step = workflow.advance(task["status"], task["round"], bool(task["manual_check"]), result,
                                enabled)                  # raises ValueError for a result that does not fit
        if change is not None:
            conn.execute("UPDATE agent_tasks SET diff_stat = ?, diff = ? WHERE id = ?",
                         (change[0][:MAX_DIFF], change[1][:MAX_DIFF], task["id"]))
        if run["role"] == "programmer" and result == "done" and tests is not None:
            code, output = int(tests[0]), str(tests[1])[-MAX_TESTS:]
            verdict = "pass" if code == 0 else "fail"
            conn.execute("UPDATE agent_tasks SET tests = ?, tests_exit = ? WHERE id = ?", (output, code, task["id"]))
            conn.execute(
                "INSERT INTO agent_runs (task_id, role, model, status, result, report, created_at, started_at,"
                " finished_at, provider) VALUES (?, 'tester', ?, 'done', ?, ?, ?, ?, ?, ?)",
                (task["id"], HUB_MODEL, verdict, f"hub-test.sh: exit {code}\n{output}"[:MAX_REPORT], now, now, now, ""))
            step = workflow.advance("testing", task["round"], bool(task["manual_check"]), verdict,
                                    enabled | {"tester"})
        found = reply.parse(report)                       # what the role noticed outside its task (prompts.FOUND)
        report = found.text
        may = prompts.ALLOWED.get((run["role"], "doc" if run["role"] == "chef" else "run"), frozenset())
        if "task" not in may:                             # the manager's documentation puts nothing on the board
            found.tasks, found.asks = [], []
        for item in found.tasks[:FOUND_MAX]:              # a bug goes on the board at once, an addition waits
            board.add_from_ai(conn, task["project_id"], item.kind, item.title, item.body,
                              approved=item.kind == "bug", source="agent")
        for ask in found.asks:                            # the answer comes with the next run of this task
            questions.add(conn, task["project_id"], run["role"], ask, task["id"])
        conn.execute(
            "UPDATE agent_runs SET status = 'done', result = ?, report = ?, tokens_in = ?, tokens_out = ?,"
            " seconds = ?, finished_at = ? WHERE id = ?",
            (result, report[:MAX_REPORT], max(0, int(tokens_in)), max(0, int(tokens_out)),
             max(0, int(seconds)), now, run_id),
        )
        _enter(conn, user_id, task["id"], step, now)
    if pending_notes:                                     # after the transaction: files.py opens its own connection
        owner, project_id, notes, edits = pending_notes
        for name, body in notes.items():
            memory.save_memory(owner, project_id, body, name)
        failed = memory.edit_failures(memory.apply_edits(owner, project_id, edits)) if edits else ""
        if failed:                                        # the user sees in the report what was not changed
            with db.connect() as conn:
                conn.execute("UPDATE agent_runs SET report = substr(report || ?, 1, ?) WHERE id = ?",
                             (f"\n\n{failed}", MAX_REPORT, run_id))
    return True


# --- merging approved work and cleaning up (the runner does the git side: runner/workspace.py)
CLEAN_DAYS = 7            # finished tasks whose folders the runner may still have to delete


def pending_merges() -> list[dict]:
    """Runner: approved tasks (documenting or done) whose branch is not merged into the project's main yet."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT t.id, t.project_id, p.user_id FROM agent_tasks t JOIN projects p ON p.id = t.project_id"
            " WHERE t.status IN ('documenting', 'done') AND t.merged = 0 ORDER BY t.id").fetchall()
    return [{"task_id": r["id"], "project_id": r["project_id"], "user_id": r["user_id"],
             "branch": branch_name(r["id"])} for r in rows]


def merge_done(task_id: int, ok: bool, now: int | None = None) -> bool:
    """Runner: the merge went through (the chef's run may start), or not (a conflict: the task goes to the user)."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        task = conn.execute("SELECT * FROM agent_tasks WHERE id = ? AND status IN ('documenting', 'done')"
                            " AND merged = 0", (task_id,)).fetchone()
        if task is None:
            return False
        if ok:
            conn.execute("UPDATE agent_tasks SET merged = 1 WHERE id = ?", (task_id,))
        else:
            conn.execute("UPDATE agent_tasks SET merged = -1 WHERE id = ?", (task_id,))
            _enter(conn, _owner(conn, task_id), task_id,
                   workflow.Step("escalated", task["round"], bool(task["manual_check"])), now,
                   "merge conflict with main: send it back for another round")
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
    """Runner: tasks of the last CLEAN_DAYS that are over (done and merged, or cancelled): their folders can go."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        return [r["id"] for r in conn.execute(
            "SELECT id FROM agent_tasks WHERE finished_at > ? AND (status = 'cancelled' OR (status = 'done' AND merged = 1))"
            " ORDER BY id", (now - CLEAN_DAYS * 86400,))]


# --- the board's view of tasks (Janis, 15.11.2026: an agreed item goes to the agents from its card)

def tasks_by_item(user_id: int, project_id: int) -> dict[int, Task]:
    """The newest task of every board item of the project (only the user's own)."""
    found: dict[int, Task] = {}
    for task in list_tasks(user_id, project_id):           # newest first
        if task.item_id is not None and task.item_id not in found:
            found[task.item_id] = task
    return found


def last_report(user_id: int, task_id: int) -> str:
    """The newest report of the task (for the card's tip); "" if none or not the user's."""
    runs = [r for r in task_runs(user_id, task_id) if r.report]
    return runs[-1].report if runs else ""


def item_task(user_id: int, item_id: int) -> Task | None:
    """The newest task of one board item, if the item is the user's."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT t.* FROM agent_tasks t JOIN projects p ON p.id = t.project_id"
            " WHERE t.item_id = ? AND p.user_id = ? ORDER BY t.id DESC LIMIT 1", (item_id, user_id)).fetchone()
    return None if row is None else _task(row)


def start_item(user_id: int, item_id: int, now: int | None = None) -> Task:
    """Give a board item of the user to the agents (its project comes from the item). ValueError if not possible."""
    with db.connect() as conn:
        row = conn.execute("SELECT b.project_id FROM board_items b JOIN projects p ON p.id = b.project_id"
                           " WHERE b.id = ? AND p.user_id = ?", (item_id, user_id)).fetchone()
    if row is None:
        raise ValueError("Unbekannter Punkt")
    return start_task(user_id, row["project_id"], item_id, now=now)
