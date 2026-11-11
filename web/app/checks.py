"""Regular checks of a project (Manager view, Janis 07.11.2026): small recurring to-dos of the manager such as
"check that security is in order". They are not board items (neither bugs nor updates).

A check has a text, a cycle (daily, weekly, monthly, quarterly) and the time it was last done. Weekly and longer
cycles are due when it was never done or a whole cycle has passed since. A daily check also has weekdays
(`days`, Janis 11.11.2026): seven characters, Monday first, "1" = this day counts ("1010101" = Mon, Wed, Fri,
Sun). It is due when it was never done or when one of its days has come since the day it was last done; a day
that was missed keeps it due until it is done. Days follow the clock of the server. Like every data module, each
function gets the `user_id` and the project must be his: foreign things are "not found" (None, False or
ValueError). Standard library only.
"""
import datetime
import sqlite3
import time
from dataclasses import dataclass

from . import db

DAY = 86400
CYCLES = {"daily": DAY, "weekly": 7 * DAY, "monthly": 30 * DAY, "quarterly": 91 * DAY}   # cycle -> seconds
ALL_DAYS = "1111111"
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")   # for the manager's context (English)
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
    days: str = ALL_DAYS

    def is_due(self, now: int) -> bool:
        return is_due(self.cycle, self.last_done, now, self.days)


def days_string(selected) -> str:
    """The `days` value for the numbers 0 (Monday) to 6 (Sunday) that were ticked."""
    chosen = {int(n) for n in selected}
    return "".join("1" if n in chosen else "0" for n in range(7))


def day_numbers(days: str) -> list[int]:
    return [n for n, mark in enumerate(days) if mark == "1"]


def _date(timestamp: int) -> datetime.date:
    return datetime.date.fromtimestamp(timestamp)


def is_due(cycle: str, last_done: int | None, now: int, days: str = ALL_DAYS) -> bool:
    """Never done, or (daily) one of the days has come since the day it was done, or (longer cycles) a whole
    cycle has passed since it was last done."""
    if last_done is None:
        return True
    if cycle != "daily":
        return now >= last_done + CYCLES[cycle]
    last, today = _date(last_done).toordinal(), _date(now).toordinal()
    for ordinal in range(last + 1, min(today, last + 7) + 1):   # a week covers every weekday once
        if days[datetime.date.fromordinal(ordinal).weekday()] == "1":
            return True
    return False


def _to_check(row: sqlite3.Row) -> Check:
    return Check(row["id"], row["project_id"], row["text"], row["cycle"], row["last_done"], row["created_at"],
                 row["days"])


def _clean(text: str, cycle: str, days: str) -> tuple[str, str, str]:
    text = text.strip()
    if not text:
        raise ValueError("Text fehlt")
    if len(text) > MAX_TEXT:
        raise ValueError("Text zu lang")
    if cycle not in CYCLES:
        raise ValueError("Unbekannte Länge")
    if len(days) != 7 or set(days) - {"0", "1"}:
        raise ValueError("Unbekannte Tage")
    if cycle != "daily":
        days = ALL_DAYS                      # weekdays only mean something for a daily check
    elif "1" not in days:
        raise ValueError("Kein Tag gewählt")
    return text, cycle, days


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


def create(user_id: int, project_id: int, text: str, cycle: str, days: str = ALL_DAYS,
           now: int | None = None) -> Check:
    """Add a check. Raises ValueError for a bad text, cycle or days, a project that is not the user's, or when
    the project already has MAX_PER_PROJECT checks."""
    text, cycle, days = _clean(text, cycle, days)
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id)).fetchone() is None:
            raise ValueError("Unbekanntes Projekt")
        if conn.execute("SELECT COUNT(*) FROM checks WHERE project_id = ?", (project_id,)).fetchone()[0] >= MAX_PER_PROJECT:
            raise ValueError("Zu viele Prüfungen")
        cur = conn.execute(
            "INSERT INTO checks (project_id, text, cycle, days, created_at) VALUES (?, ?, ?, ?, ?)",
            (project_id, text, cycle, days, int(now if now is not None else time.time())),
        )
        row = conn.execute("SELECT * FROM checks WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _to_check(row)


def update(user_id: int, check_id: int, text: str, cycle: str, days: str = ALL_DAYS) -> int | None:
    """Change text, cycle and days. Returns the project id, or None if the check is not the user's.
    Raises ValueError for a bad text, cycle or days."""
    text, cycle, days = _clean(text, cycle, days)
    with db.connect() as conn:
        row = _owned(conn, user_id, check_id)
        if row is None:
            return None
        conn.execute("UPDATE checks SET text = ?, cycle = ?, days = ? WHERE id = ?", (text, cycle, days, check_id))
    return row["project_id"]


def mark_done(user_id: int, check_id: int, now: int | None = None) -> bool:
    """The check was done just now: it is not due again until its next day (daily) or a whole cycle has passed."""
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
