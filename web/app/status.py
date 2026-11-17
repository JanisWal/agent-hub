"""Assessment of a project's state (Manager view, tile "Status"): how much is planned and done, how far the project is
from what was set out, and how work is going (running, active, quiet, stalled, idle), with a lamp in three levels
(Janis, 07.11.2026: runs; problems but manageable; intervention needed).

It is counted from the data, no AI is asked: the same numbers give the same answer and it costs nothing. The manager's
own written status (reply format `<status>`) can come later next to it.

Planned: the agreed board items (open) and what the agents took from them; done: finished tasks and archived items;
progress = done / (planned + done). Proposals, trash and the user's own "for you" list are not planned work.

Like every data module, the function gets the `user_id`; a foreign project gives None. Standard library only.
"""
import time
from dataclasses import dataclass, field

from . import checks, db

DAY = 86400
RECENT = 2 * DAY          # work this recently is "active"
STALL = 7 * DAY           # open work with nothing for so long is "stalled"
APPROVAL_WAIT = 3 * DAY   # a release that waits so long is a problem
FAILED_WITHIN = 3 * DAY   # a failed run this recently counts
BUSY_EVENTS = 6           # events in a week from which the project is "busy"
RUNNING = ("coding", "testing", "reviewing", "documenting")
LAMPS = ("none", "green", "yellow", "red")
ACTIVITIES = ("running", "busy", "active", "quiet", "stalled", "idle")


@dataclass
class Assessment:
    planned: int          # agreed, not yet taken by the agents
    in_progress: int      # tasks of the agents that are moving
    waiting: int          # tasks that wait for the user (release, escalation)
    done: int
    proposals: int
    todos_open: int
    checks_due: int
    progress: int         # per cent, 0 to 100
    activity: str         # one of ACTIVITIES
    events_week: int
    last_activity: int | None
    lamp: str             # one of LAMPS
    reasons: list = field(default_factory=list)   # codes that explain the lamp (translated by the page)

    @property
    def total(self) -> int:
        return self.planned + self.in_progress + self.waiting + self.done


def _one(conn, sql: str, *args) -> int:
    return conn.execute(sql, args).fetchone()[0] or 0


def assess(user_id: int, project_id: int, now: int | None = None) -> Assessment | None:
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id)).fetchone() is None:
            return None
        taken = _one(conn, "SELECT COUNT(DISTINCT t.item_id) FROM agent_tasks t JOIN board_items b ON b.id = t.item_id"
                     " WHERE t.project_id = ? AND b.status = 'open'"
                     " AND t.status IN ('coding','testing','reviewing','awaiting_approval','documenting','escalated')",
                     project_id)
        open_items = _one(conn, "SELECT COUNT(*) FROM board_items WHERE project_id = ? AND status = 'open'", project_id)
        in_progress = _one(conn, "SELECT COUNT(*) FROM agent_tasks WHERE project_id = ? AND status IN"
                           " ('coding','testing','reviewing','documenting')", project_id)
        waiting = _one(conn, "SELECT COUNT(*) FROM agent_tasks WHERE project_id = ? AND status IN"
                       " ('awaiting_approval','escalated')", project_id)
        done = _one(conn, "SELECT COUNT(*) FROM board_items WHERE project_id = ? AND status = 'archived'", project_id) \
            + _one(conn, "SELECT COUNT(*) FROM agent_tasks t WHERE t.project_id = ? AND t.status = 'done' AND"
                   " (t.item_id IS NULL OR NOT EXISTS (SELECT 1 FROM board_items b WHERE b.id = t.item_id"
                   " AND b.status = 'archived'))", project_id)
        proposals = _one(conn, "SELECT COUNT(*) FROM board_items WHERE project_id = ? AND status = 'proposed'", project_id)
        todos_open = _one(conn, "SELECT COUNT(*) FROM todos WHERE project_id = ? AND done_at IS NULL", project_id)
        escalated = _one(conn, "SELECT COUNT(*) FROM agent_tasks WHERE project_id = ? AND status = 'escalated'", project_id)
        # waiting since the last run of the task ended (that is when it came to the user), not since it was made
        old_release = _one(conn, "SELECT COUNT(*) FROM agent_tasks t WHERE t.project_id = ? AND t.status = 'awaiting_approval'"
                           " AND COALESCE((SELECT MAX(r.finished_at) FROM agent_runs r WHERE r.task_id = t.id), t.created_at) < ?",
                           project_id, now - APPROVAL_WAIT)
        failed = _one(conn, "SELECT COUNT(*) FROM agent_runs r JOIN agent_tasks t ON t.id = r.task_id WHERE t.project_id = ?"
                      " AND r.status = 'failed' AND r.finished_at > ? AND t.status IN"
                      " ('coding','testing','reviewing','documenting','awaiting_approval')", project_id, now - FAILED_WITHIN)
        running_now = _one(conn, "SELECT COUNT(*) FROM agent_runs r JOIN agent_tasks t ON t.id = r.task_id"
                           " WHERE t.project_id = ? AND r.status IN ('queued','running')", project_id)
        week = now - 7 * DAY
        # one row per kind of event: (newest time, number in the last week). Only what a person or an agent did counts:
        # the memory files the hub makes itself (memory.py) are not activity (17.11.2026: they made every project
        # "busy"), the AI's written status neither, and an upload of many files counts once per hour, not per file.
        stamps = []
        for sql in (
            "SELECT MAX(created_at), SUM(created_at > :w) FROM board_items WHERE project_id = :p",
            "SELECT MAX(COALESCE(finished_at, created_at)), SUM(COALESCE(finished_at, created_at) > :w) FROM agent_tasks WHERE project_id = :p",
            "SELECT MAX(COALESCE(r.finished_at, r.created_at)), SUM(COALESCE(r.finished_at, r.created_at) > :w) FROM agent_runs r"
            " JOIN agent_tasks t ON t.id = r.task_id WHERE t.project_id = :p",
            "SELECT MAX(created_at), SUM(created_at > :w) FROM chat_messages WHERE project_id = :p AND kind = 'chat'",
            "SELECT MAX(created_at), COUNT(DISTINCT CASE WHEN created_at > :w THEN created_at / 3600 END) FROM files"
            " WHERE project_id = :p AND category != 'memory' AND trashed_at IS NULL",
            "SELECT MAX(COALESCE(done_at, created_at)), SUM(COALESCE(done_at, created_at) > :w) FROM todos WHERE project_id = :p",
        ):
            stamps.append(conn.execute(sql, {"w": week, "p": project_id}).fetchone())
    due = sum(1 for c in checks.list_checks(user_id, project_id) if c.is_due(now))
    newest = [s[0] for s in stamps if s[0]]
    last = max(newest) if newest else None
    events = sum(s[1] or 0 for s in stamps)

    planned = max(0, open_items - taken)
    unfinished = planned + in_progress + waiting
    total = unfinished + done
    progress = round(100 * done / total) if total else 0

    if running_now or in_progress:
        activity = "running"
    elif unfinished and (last is None or now - last > STALL):
        activity = "stalled"
    elif events >= BUSY_EVENTS:
        activity = "busy"
    elif last is not None and now - last <= RECENT:
        activity = "active"
    elif unfinished or (last is not None and now - last <= STALL):
        activity = "quiet"
    else:
        activity = "idle"

    reasons = []
    if escalated:
        reasons.append("escalated")
    if failed:
        reasons.append("failed")
    if old_release:
        reasons.append("release_old")
    if activity == "stalled":
        reasons.append("stalled")
    if escalated or failed:
        lamp = "red"
    elif old_release or activity == "stalled":
        lamp = "yellow"
    elif total == 0 and last is None:
        lamp = "none"
    else:
        lamp = "green"
    return Assessment(planned, in_progress, waiting, done, proposals, todos_open, due, progress, activity, events,
                      last, lamp, reasons)
