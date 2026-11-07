"""Projects of a user, laid out on pages of tiles. Standard library only.

A page holds up to PAGE_SIZE projects. Every project stores its page and its
position on that page. Pages may be only partly filled; empty slots are simply
the end of the page. Pages without projects do not exist.
"""
import sqlite3
import time
from dataclasses import dataclass

from . import db

MAX_NAME = 60
PAGE_SIZE = 6


@dataclass
class Project:
    id: int
    name: str
    position: int
    page: int


def _to_project(row: sqlite3.Row) -> Project:
    return Project(row["id"], row["name"], row["position"], row["page"])


def _ordered(conn: sqlite3.Connection, user_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, name, position, page FROM projects WHERE user_id = ?"
        " ORDER BY page, position, id",
        (user_id,),
    ).fetchall()


def _pages(rows: list[sqlite3.Row]) -> list[list[sqlite3.Row]]:
    """Group ordered rows by their stored page number (gaps in the numbers do not matter)."""
    grouped: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(row["page"], []).append(row)
    return list(grouped.values())


def layout(user_id: int) -> list[list[Project]]:
    """The user's projects as pages (display order). Only pages that hold projects."""
    with db.connect() as conn:
        rows = _ordered(conn, user_id)
    return [[_to_project(r) for r in page] for page in _pages(rows)]


def get_project(user_id: int, project_id: int) -> Project | None:
    """One project, only if it belongs to the user."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT id, name, position, page FROM projects WHERE id = ? AND user_id = ?",
            (project_id, user_id),
        ).fetchone()
    return _to_project(row) if row else None


def display_page(user_id: int, project_id: int) -> int | None:
    """Number (1, 2, ...) of the page the project is shown on."""
    for number, page in enumerate(layout(user_id), start=1):
        if any(p.id == project_id for p in page):
            return number
    return None


def create_project(user_id: int, name: str) -> Project:
    """Add a project on the first page with a free slot, else on a new last page.

    Raises ValueError for an empty or too long name. Also marks the user as having
    used the first tile (users.had_project), which is never reset, so the start hint
    does not come back after deleting.
    """
    name = name.strip()
    if not name:
        raise ValueError("Projektname fehlt")
    if len(name) > MAX_NAME:
        raise ValueError("Projektname zu lang")
    with db.connect() as conn:
        pages = _pages(_ordered(conn, user_id))
        free = next((p for p in pages if len(p) < PAGE_SIZE), None)
        if free is not None:
            page, position = free[0]["page"], free[-1]["position"] + 1
        else:
            page, position = (pages[-1][0]["page"] + 1 if pages else 1), 0
        cur = conn.execute(
            "INSERT INTO projects (user_id, name, position, page, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (user_id, name, position, page, int(time.time())),
        )
        conn.execute("UPDATE users SET had_project = 1 WHERE id = ?", (user_id,))
    return Project(cur.lastrowid, name, position, page)


def delete_project(user_id: int, project_id: int) -> bool:
    """Delete for good. False if the project does not exist or is not the user's."""
    with db.connect() as conn:
        cur = conn.execute(
            "DELETE FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id)
        )
    return cur.rowcount > 0


def _spill_over(pages: list[list[int]]) -> None:
    """A page with too many projects pushes its last one to the start of the next page."""
    i = 0
    while i < len(pages):
        while len(pages[i]) > PAGE_SIZE:
            if i + 1 == len(pages):
                pages.append([])
            pages[i + 1].insert(0, pages[i].pop())
        i += 1


def move(user_id: int, project_id: int, page: int, index: int) -> int:
    """Put a project on display page `page` (1, 2, ...) at position `index` (0 = first).

    A page number one past the last page opens a new page. If the target page is
    full, its last project moves on to the next page, like apps on a phone. Pages
    left empty disappear. Returns the display page the project ends up on.
    Raises ValueError if the project is not the user's.
    """
    with db.connect() as conn:
        pages = [[r["id"] for r in p] for p in _pages(_ordered(conn, user_id))]
        if not any(project_id in p for p in pages):
            raise ValueError("Unbekanntes Projekt")
        for p in pages:
            if project_id in p:
                p.remove(project_id)
        target = max(0, min(page - 1, len(pages)))
        if target == len(pages):
            pages.append([])
        pages[target].insert(max(0, min(index, len(pages[target]))), project_id)
        _spill_over(pages)
        pages = [p for p in pages if p]
        for number, ids in enumerate(pages, start=1):
            for position, pid in enumerate(ids):
                conn.execute(
                    "UPDATE projects SET page = ?, position = ? WHERE id = ? AND user_id = ?",
                    (number, position, pid, user_id),
                )
    return next(number for number, ids in enumerate(pages, start=1) if project_id in ids)
