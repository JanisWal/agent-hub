"""Kanban items of a project, stored in SQLite. Standard library only.

Columns (`kind`): bug, minor (small update), major (major update).
Status: open (agreed, shown on top), proposed (suggested by Claude, waiting for
accept or reject), trash (discarded, can be restored or deleted for good).
"""
import sqlite3
import time
from dataclasses import dataclass

from . import db

KINDS = ("bug", "minor", "major")
MAX_TITLE = 200


@dataclass
class Item:
    id: int
    project_id: int
    kind: str
    title: str
    source: str  # "user" or "claude"
    status: str  # "open", "proposed" or "trash"
    position: int


def _to_item(row: sqlite3.Row) -> Item:
    return Item(
        row["id"], row["project_id"], row["kind"], row["title"],
        row["source"], row["status"], row["position"],
    )


def _clean(kind: str, title: str) -> tuple[str, str]:
    title = title.strip()
    if kind not in KINDS:
        raise ValueError("Unbekannte Spalte")
    if not title:
        raise ValueError("Titel fehlt")
    if len(title) > MAX_TITLE:
        raise ValueError("Titel zu lang")
    return kind, title


def _owns_project(conn: sqlite3.Connection, user_id: int, project_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id)
    ).fetchone()
    return row is not None


def _owned_item(conn: sqlite3.Connection, user_id: int, item_id: int) -> sqlite3.Row | None:
    """The item row, only if its project belongs to the user."""
    return conn.execute(
        "SELECT b.* FROM board_items b JOIN projects p ON p.id = b.project_id"
        " WHERE b.id = ? AND p.user_id = ?",
        (item_id, user_id),
    ).fetchone()


def _edge_position(conn: sqlite3.Connection, project_id: int, kind: str, top: bool) -> int:
    """Position above (top) or below all open items of a column."""
    agg, step = ("MIN", -1) if top else ("MAX", 1)
    value = conn.execute(
        f"SELECT {agg}(position) FROM board_items"
        " WHERE project_id = ? AND kind = ? AND status = 'open'",
        (project_id, kind),
    ).fetchone()[0]
    return step if value is None else value + step


def list_items(user_id: int, project_id: int) -> list[Item]:
    """All items of a project (any status) in display order; empty if not the user's."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT b.* FROM board_items b JOIN projects p ON p.id = b.project_id"
            " WHERE b.project_id = ? AND p.user_id = ? ORDER BY b.position, b.id",
            (project_id, user_id),
        ).fetchall()
    return [_to_item(r) for r in rows]


def create_item(user_id: int, project_id: int, kind: str, title: str) -> Item:
    """Add an item by hand: it counts as agreed and goes to the top of its column.

    Raises ValueError for a bad kind or title, or if the project is not the user's.
    """
    kind, title = _clean(kind, title)
    with db.connect() as conn:
        if not _owns_project(conn, user_id, project_id):
            raise ValueError("Unbekanntes Projekt")
        position = _edge_position(conn, project_id, kind, top=True)
        cur = conn.execute(
            "INSERT INTO board_items (project_id, kind, title, source, status, position, created_at)"
            " VALUES (?, ?, ?, 'user', 'open', ?, ?)",
            (project_id, kind, title, position, int(time.time())),
        )
        row = conn.execute("SELECT * FROM board_items WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _to_item(row)


def create_suggestion(user_id: int, project_id: int, kind: str, title: str) -> Item:
    """Add a suggestion from Claude (used by the agents later). Waits for accept or reject.

    `user_id` is the user the agent works for; like everywhere, the project must be his
    (ValueError otherwise), so an agent can never write into somebody else's board.
    """
    kind, title = _clean(kind, title)
    with db.connect() as conn:
        if not _owns_project(conn, user_id, project_id):
            raise ValueError("Unbekanntes Projekt")
        cur = conn.execute(
            "INSERT INTO board_items (project_id, kind, title, source, status, position, created_at)"
            " VALUES (?, ?, ?, 'claude', 'proposed', 0, ?)",
            (project_id, kind, title, int(time.time())),
        )
        row = conn.execute("SELECT * FROM board_items WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _to_item(row)


def update_title(user_id: int, item_id: int, title: str) -> int | None:
    """Rename an item. Returns its project id, or None if it is not the user's.

    Raises ValueError for an empty or too long title.
    """
    _, title = _clean(KINDS[0], title)
    with db.connect() as conn:
        row = _owned_item(conn, user_id, item_id)
        if row is None:
            return None
        conn.execute("UPDATE board_items SET title = ? WHERE id = ?", (title, item_id))
    return row["project_id"]


def _move(user_id: int, item_id: int, allowed_from: tuple[str, ...], to_status: str) -> bool:
    """Change the status if the item is the user's and currently in `allowed_from`."""
    with db.connect() as conn:
        row = _owned_item(conn, user_id, item_id)
        if row is None or row["status"] not in allowed_from:
            return False
        position = row["position"]
        if to_status == "open":
            # Accepted items go below the agreed ones, restored manual items to the top.
            position = _edge_position(conn, row["project_id"], row["kind"], top=row["source"] == "user")
        conn.execute(
            "UPDATE board_items SET status = ?, position = ? WHERE id = ?",
            (to_status, position, item_id),
        )
    return True


def accept(user_id: int, item_id: int) -> bool:
    """Take over a Claude suggestion."""
    return _move(user_id, item_id, ("proposed",), "open")


def reject(user_id: int, item_id: int) -> bool:
    """Reject a Claude suggestion: it goes to the trash."""
    return _move(user_id, item_id, ("proposed",), "trash")


def discard(user_id: int, item_id: int) -> bool:
    """Put an agreed item into the trash."""
    return _move(user_id, item_id, ("open",), "trash")


def restore(user_id: int, item_id: int) -> bool:
    """Take an item out of the trash: Claude suggestions wait for a decision again."""
    with db.connect() as conn:
        row = _owned_item(conn, user_id, item_id)
    if row is None or row["status"] != "trash":
        return False
    return _move(user_id, item_id, ("trash",), "open" if row["source"] == "user" else "proposed")


def delete_item(user_id: int, item_id: int) -> bool:
    """Delete for good. Only items that are in the trash."""
    with db.connect() as conn:
        row = _owned_item(conn, user_id, item_id)
        if row is None or row["status"] != "trash":
            return False
        conn.execute("DELETE FROM board_items WHERE id = ?", (item_id,))
    return True


def empty_trash(user_id: int, project_id: int) -> int:
    """Delete everything in the trash of a project. Returns how many items were removed."""
    with db.connect() as conn:
        if not _owns_project(conn, user_id, project_id):
            return 0
        cur = conn.execute(
            "DELETE FROM board_items WHERE project_id = ? AND status = 'trash'", (project_id,)
        )
    return cur.rowcount


def reorder(user_id: int, kind: str, ids: list[int]) -> None:
    """Put the given open items into column `kind` in the given order.

    Used after dragging: the ids are the open items of the target column. An item
    that came from another column changes its column. Raises ValueError for a bad
    kind, duplicates, or ids that are not open items of the user.
    """
    if kind not in KINDS:
        raise ValueError("Unbekannte Spalte")
    if not ids:
        return
    if len(set(ids)) != len(ids):
        raise ValueError("Doppelte IDs")
    with db.connect() as conn:
        for item_id in ids:
            row = _owned_item(conn, user_id, item_id)
            if row is None or row["status"] != "open":
                raise ValueError("Unbekannter Punkt")
        for position, item_id in enumerate(ids):
            conn.execute(
                "UPDATE board_items SET kind = ?, position = ? WHERE id = ?",
                (kind, position, item_id),
            )
