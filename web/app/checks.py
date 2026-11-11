"""Regular checks of a project (Manager view, Janis 07.11.2026): small recurring to-dos of the manager such as
"check that security is in order". They are not board items (neither bugs nor updates).

A check has a text, a cycle (daily, weekly, monthly, quarterly) and the time it was last done. It is due
when it was never done or when a whole cycle has passed since. Like every data module, each function gets
the `user_id` and the project must be his: foreign things are "not found" (None, False or ValueError).
Standard library only.
"""
import sqlite3
import time
from dataclasses import dataclass

from . import db

DAY = 86400
CYCLES = {"daily": DAY, "weekly": 7 * DAY, "monthly": 30 * DAY, "quarterly": 91 * DAY}   # cycle -> seconds
MAX_TEXT = 200
MAX_PER_PROJECT = 50


@dataclass
class Check:
    id: int
    project_id: int
    text: str
    cycle: str
    last_done: int | None
    created_at: int

    def is_due(self, now: int) -> bool:
        return is_due(self.cycle, self.last_done, now)


def is_due(cycle: str, last_done: int | None, now: int) -> bool:
    """Never done, or a whole cycle has passed since it was last done."""
    return last_done is None or now >= last_done + CYCLES[cycle]


def _to_check(row: sqlite3.Row) -> Check:
    return Check(row["id"], row["project_id"], row["text"], row["cycle"], row["last_done"], row["created_at"])


def _clean(text: str, cycle: str) -> tuple[str, str]:
    text = text.strip()
    if not text:
        raise ValueError("Text fehlt")
    if len(text) > MAX_TEXT:
        raise ValueError("Text zu lang")
    if cycle not in CYCLES:
        raise ValueError("Unbekannte Länge")
    return text, cycle


def _owned(conn: sqlite3.Connection, user_id: int, check_id: int) -> sqlite3.Row | None:
    """The check row, only if its project belongs to the user."""
    return conn.execute(
        "SELECT c.* FROM checks c JOIN projects p ON p.id = c.project_id WHERE c.id = ? AND p.user_id = ?",
        (check_id, user_id),
    ).fetchone()


def list_checks(user_id: int, project_id: int) -> list[Check]:
    """The checks of a project in the order they were made; empty if the project is not the user's."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT c.* FROM checks c JOIN projects p ON p.id = c.project_id"
            " WHERE c.project_id = ? AND p.user_id = ? ORDER BY c.id",
            (project_id, user_id),
        ).fetchall()
    return [_to_check(r) for r in rows]


def create(user_id: int, project_id: int, text: str, cycle: str, now: int | None = None) -> Check:
    """Add a check. Raises ValueError for a bad text or cycle, a project that is not the user's, or when
    the project already has MAX_PER_PROJECT checks."""
    text, cycle = _clean(text, cycle)
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id)).fetchone() is None:
            raise ValueError("Unbekanntes Projekt")
        if conn.execute("SELECT COUNT(*) FROM checks WHERE project_id = ?", (project_id,)).fetchone()[0] >= MAX_PER_PROJECT:
            raise ValueError("Zu viele Prüfungen")
        cur = conn.execute(
            "INSERT INTO checks (project_id, text, cycle, created_at) VALUES (?, ?, ?, ?)",
            (project_id, text, cycle, int(now if now is not None else time.time())),
        )
        row = conn.execute("SELECT * FROM checks WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _to_check(row)


def update(user_id: int, check_id: int, text: str, cycle: str) -> int | None:
    """Change text and cycle. Returns the project id, or None if the check is not the user's.
    Raises ValueError for a bad text or cycle."""
    text, cycle = _clean(text, cycle)
    with db.connect() as conn:
        row = _owned(conn, user_id, check_id)
        if row is None:
            return None
        conn.execute("UPDATE checks SET text = ?, cycle = ? WHERE id = ?", (text, cycle, check_id))
    return row["project_id"]


def mark_done(user_id: int, check_id: int, now: int | None = None) -> bool:
    """The check was done just now: it is not due again until a whole cycle has passed."""
    with db.connect() as conn:
        if _owned(conn, user_id, check_id) is None:
            return False
        conn.execute("UPDATE checks SET last_done = ? WHERE id = ?",
                     (int(now if now is not None else time.time()), check_id))
    return True


def delete(user_id: int, check_id: int) -> bool:
    with db.connect() as conn:
        if _owned(conn, user_id, check_id) is None:
            return False
        conn.execute("DELETE FROM checks WHERE id = ?", (check_id,))
    return True
