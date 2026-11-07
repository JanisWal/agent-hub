"""Projects of a user, stored in SQLite next to the users. Standard library only."""
import time
from dataclasses import dataclass

from . import users

MAX_NAME = 60


@dataclass
class Project:
    id: int
    name: str
    position: int


def list_projects(user_id: int) -> list[Project]:
    """All projects of a user in display order."""
    with users.connect() as db:
        rows = db.execute(
            "SELECT id, name, position FROM projects WHERE user_id = ?"
            " ORDER BY position, id",
            (user_id,),
        ).fetchall()
    return [Project(r["id"], r["name"], r["position"]) for r in rows]


def get_project(user_id: int, project_id: int) -> Project | None:
    """One project, only if it belongs to the user."""
    with users.connect() as db:
        row = db.execute(
            "SELECT id, name, position FROM projects WHERE id = ? AND user_id = ?",
            (project_id, user_id),
        ).fetchone()
    return Project(row["id"], row["name"], row["position"]) if row else None


def create_project(user_id: int, name: str) -> Project:
    """Append a project. Raises ValueError for an empty or too long name.

    Also marks the user as having used the first tile (users.had_project),
    which is never reset, so the start hint does not come back after deleting.
    """
    name = name.strip()
    if not name:
        raise ValueError("Projektname fehlt")
    if len(name) > MAX_NAME:
        raise ValueError("Projektname zu lang")
    with users.connect() as db:
        position = db.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM projects WHERE user_id = ?",
            (user_id,),
        ).fetchone()[0]
        cur = db.execute(
            "INSERT INTO projects (user_id, name, position, created_at)"
            " VALUES (?, ?, ?, ?)",
            (user_id, name, position, int(time.time())),
        )
        db.execute("UPDATE users SET had_project = 1 WHERE id = ?", (user_id,))
    return Project(cur.lastrowid, name, position)


def delete_project(user_id: int, project_id: int) -> bool:
    """Delete for good. False if the project does not exist or is not the user's."""
    with users.connect() as db:
        cur = db.execute(
            "DELETE FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id)
        )
    return cur.rowcount > 0


def reorder(user_id: int, ids: list[int]) -> None:
    """Put the given projects in the given order.

    The ids are the tiles of one page after dragging. They take over the positions
    that these projects held before, so projects on other pages keep their place.
    Raises ValueError for duplicates or ids that are not the user's.
    """
    if not ids:
        return
    if len(set(ids)) != len(ids):
        raise ValueError("Doppelte Projekt-IDs")
    marks = ",".join("?" * len(ids))
    with users.connect() as db:
        rows = db.execute(
            f"SELECT id, position FROM projects WHERE user_id = ? AND id IN ({marks})",
            (user_id, *ids),
        ).fetchall()
        if len(rows) != len(ids):
            raise ValueError("Unbekanntes Projekt")
        positions = sorted(row["position"] for row in rows)
        for position, project_id in zip(positions, ids):
            db.execute(
                "UPDATE projects SET position = ? WHERE id = ? AND user_id = ?",
                (position, project_id, user_id),
            )
