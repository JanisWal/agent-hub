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
from dataclasses import dataclass

from . import board, claude_link, db, workflow

MODELS = ("haiku", "sonnet", "opus")     # aliases of Claude Code, they follow the newest version
DEFAULT_MODEL = {"chef": "sonnet", "programmer": "sonnet", "tester": "sonnet",
                 "reviewer": "sonnet"}
NEEDS = ("any", "mac")
# How freely the manager decides (Janis, 07.11.2026): fully on its own, asks for big decisions, asks for small
# things too. It is a threshold, not a switch: the manager first tries to derive the answer from the project.
AUTONOMY = ("auto", "major", "all")
DEFAULT_AUTONOMY = "major"
# Web and code together (code has the open internet) or apart (web search, code without internet). Janis, 08.11.2026.
NET_MODES = ("together", "apart")
DEFAULT_NET = "together"
KIND_ORDER = ("bug", "minor", "major")   # the programmer works in this order
TASK_SECONDS = 2 * 3600                  # time limit per task, then it goes to the user
RUN_SECONDS = 20 * 60                    # a run that reports nothing for so long is dead
MAX_RUNNING = 1                          # the Pi has 1 GB: one Claude Code at a time
MAX_REPORT = 20000                       # characters of a report that are kept
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


def _model(conn: sqlite3.Connection, user_id: int, role: str) -> str:
    return _setting(conn, user_id, f"model.{role}", DEFAULT_MODEL[role])


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
    return _setting(conn, user_id, f"net.{role}", DEFAULT_NET)


def settings(user_id: int) -> dict:
    """{"strictness", "autonomy", "roles": {role: {"enabled": bool, "model": str, "net": str}}}, defaults filled in."""
    with db.connect() as conn:
        enabled = _enabled(conn, user_id)
        return {
            "strictness": _strictness(conn, user_id),
            "autonomy": autonomy_in(conn, user_id),
            "roles": {r: {"enabled": r in enabled, "model": _model(conn, user_id, r), "net": net_in(conn, user_id, r)}
                      for r in workflow.ROLES},
        }


def configure(user_id: int, role: str | None = None, *, enabled: bool | None = None,
              model: str | None = None, strictness: str | None = None, autonomy: str | None = None,
              net: str | None = None) -> None:
    """Change a setting of this user. Raises ValueError for unknown values or for switching the
    programmer off."""
    changes: list[tuple[str, str]] = []
    if strictness is not None:
        if strictness not in workflow.STRICTNESS:
            raise ValueError("Unbekannte Strenge")
        changes.append(("strictness", strictness))
    if autonomy is not None:
        if autonomy not in AUTONOMY:
            raise ValueError("Unbekannte Selbstständigkeit")
        changes.append(("autonomy", autonomy))
    if enabled is not None or model is not None or net is not None:
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
        if model is not None:
            if model not in MODELS:
                raise ValueError("Unbekanntes Modell")
            changes.append((f"model.{role}", model))
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


def _queue(conn: sqlite3.Connection, user_id: int, task_id: int, status: str, now: int) -> None:
    """Create the run for the stage the task has just entered (nothing for the user's own stage)."""
    role = workflow.STAGE_ROLE.get(status)
    if role is not None:
        conn.execute(
            "INSERT INTO agent_runs (task_id, role, model, status, created_at)"
            " VALUES (?, ?, ?, 'queued', ?)", (task_id, role, _model(conn, user_id, role), now),
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
        cur = conn.execute(
            "INSERT INTO agent_tasks (project_id, item_id, title, kind, needs, status, round,"
            " created_at, deadline) VALUES (?, ?, ?, ?, ?, 'coding', 1, ?, ?)",
            (project_id, item_id, item["title"], item["kind"], needs, now, now + TASK_SECONDS),
        )
        _queue(conn, user_id, cur.lastrowid, "coding", now)
        row = conn.execute("SELECT * FROM agent_tasks WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _task(row)


# --- what the user sees

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
    """Why a task does not move: "no_claude" (his Claude is not connected) or None."""
    if task.status in ACTIVE and task.status in workflow.STAGE_ROLE:
        with db.connect() as conn:
            if not claude_link.connected_in(conn, user_id):
                return "no_claude"
    return None


def usage(user_id: int, project_id: int | None = None) -> dict:
    """Tokens and seconds used by this user's runs (of one project, or of all)."""
    sql = ("SELECT COALESCE(SUM(r.tokens_in), 0) AS tokens_in, COALESCE(SUM(r.tokens_out), 0) AS tokens_out,"
           " COALESCE(SUM(r.seconds), 0) AS seconds, COUNT(r.id) AS runs FROM agent_runs r"
           " JOIN agent_tasks t ON t.id = r.task_id JOIN projects p ON p.id = t.project_id"
           " WHERE p.user_id = ? AND r.status IN ('done', 'failed')")
    args: list = [user_id]
    if project_id is not None:
        sql += " AND p.id = ?"
        args.append(project_id)
    with db.connect() as conn:
        return dict(conn.execute(sql, args).fetchone())


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
        elif decision == "reject" and status in ("awaiting_approval", "escalated"):
            step = workflow.after_rejection(mc)
            note_value = note.strip()[:1000]
            conn.execute("UPDATE agent_tasks SET deadline = ? WHERE id = ?", (now + TASK_SECONDS, task_id))
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


def claim_next(can_mac: bool, now: int | None = None) -> Job | None:
    """Runner: take the oldest run that may start now, or None. Only MAX_RUNNING runs at a time.

    A run is skipped (it keeps waiting) when its user's Claude is not connected or it needs the Mac
    and `can_mac` is False. There is no stand-in: nobody else's connection is ever used.
    """
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        _escalate_late(conn, now)
        _skip_waiting_tests(conn, can_mac, now)
        if conn.execute("SELECT COUNT(*) FROM agent_runs WHERE status = 'running'").fetchone()[0] >= MAX_RUNNING:
            return None
        for run in conn.execute(
            "SELECT r.*, t.needs FROM agent_runs r JOIN agent_tasks t ON t.id = r.task_id"
            " WHERE r.status = 'queued' ORDER BY r.created_at, r.id"
        ).fetchall():
            if run["needs"] == "mac" and not can_mac:
                continue
            user_id = _owner(conn, run["task_id"])
            if not claude_link.connected_in(conn, user_id):
                continue
            conn.execute("UPDATE agent_runs SET status = 'running', started_at = ? WHERE id = ?", (now, run["id"]))
            task = conn.execute("SELECT * FROM agent_tasks WHERE id = ?", (run["task_id"],)).fetchone()
            reports = [(r["role"], r["report"]) for r in conn.execute(
                "SELECT role, report FROM agent_runs WHERE task_id = ? AND status = 'done' AND report != ''"
                " ORDER BY id", (task["id"],))]
            return Job(run["id"], user_id, task["project_id"], task["id"], run["role"], run["model"],
                       branch_name(task["id"]), task["title"], task["kind"], task["round"],
                       task["note"], reports, net_in(conn, user_id, run["role"]))
    return None


def finish_run(run_id: int, result: str, report: str = "", tokens_in: int = 0, tokens_out: int = 0,
               seconds: int = 0, now: int | None = None) -> bool:
    """Runner: a run is over. `result` must fit the role (workflow.RESULTS). The task moves on
    (or goes back, or to the user) and the next run is queued. False if the run is not running
    any more (cancelled, timed out) or its task has moved on. Raises ValueError for a bad result."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        run = conn.execute("SELECT * FROM agent_runs WHERE id = ? AND status = 'running'", (run_id,)).fetchone()
        if run is None:
            return False
        task = conn.execute("SELECT * FROM agent_tasks WHERE id = ?", (run["task_id"],)).fetchone()
        if workflow.STAGE_ROLE.get(task["status"]) != run["role"]:
            return False
        user_id = _owner(conn, task["id"])
        step = workflow.advance(task["status"], task["round"], bool(task["manual_check"]), result,
                                _enabled(conn, user_id))
        conn.execute(
            "UPDATE agent_runs SET status = 'done', result = ?, report = ?, tokens_in = ?, tokens_out = ?,"
            " seconds = ?, finished_at = ? WHERE id = ?",
            (result, report[:MAX_REPORT], max(0, int(tokens_in)), max(0, int(tokens_out)),
             max(0, int(seconds)), now, run_id),
        )
        _enter(conn, user_id, task["id"], step, now)
    return True
