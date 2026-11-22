"""Kanban items of a project, stored in SQLite. Standard library only.

Columns (`kind`): bug, minor (small update), major (major update).
Status (22.11.2026, KONZEPT-AGENTEN.md 10): open (agreed: it waits in the queue, the programmer takes it by itself,
agents.take_next), proposed (a suggestion of the manager or a role: accept or reject), working (the programmer took
it: it is off the board while its task is on its way), archived (finished), trash (rejected, discarded or cancelled;
can be restored or deleted for good).

The title is a short bullet, `details` holds the context behind it (what exactly, why, decisions from the chat,
acceptance criteria) for the programmer. `needs`: "mac" when only an Apple device can build or test it.
"""
import sqlite3
import time
from dataclasses import dataclass

from . import db, reply

KINDS = ("bug", "minor", "major")
MAX_TITLE = 200
MAX_DETAILS = 4000
SOURCES = ("user", "agent", "manager")    # by hand, found by an agent in a run, the manager in the chat (no AI names)


@dataclass
class Item:
    id: int
    project_id: int
    kind: str
    title: str
    source: str  # "user", "agent" (a role in a run) or "manager" (the manager chat); "claude" until 19.11.2026
    status: str  # "open", "proposed", "working", "archived" or "trash"
    position: int
    details: str = ""     # the context behind the bullet
    needs: str = "any"


def _to_item(row: sqlite3.Row) -> Item:
    return Item(
        row["id"], row["project_id"], row["kind"], row["title"],
        row["source"], row["status"], row["position"], row["details"], row["needs"],
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


def create_item(user_id: int, project_id: int, kind: str, title: str, details: str = "") -> Item:
    """Add an item by hand, with the context behind it if given: it counts as agreed, goes to the top of its column
    and to the programmer by itself.

    Raises ValueError for a bad kind or title, or if the project is not the user's.
    """
    kind, title = _clean(kind, title)
    with db.connect() as conn:
        if not _owns_project(conn, user_id, project_id):
            raise ValueError("Unbekanntes Projekt")
        position = _edge_position(conn, project_id, kind, top=True)
        cur = conn.execute(   # agreed by hand: it goes to the programmer by itself (Janis, 19.11.2026)
            "INSERT INTO board_items (project_id, kind, title, source, status, position, created_at, details)"
            " VALUES (?, ?, ?, 'user', 'open', ?, ?, ?)",
            (project_id, kind, title, position, int(time.time()), (details or "").strip()[:MAX_DETAILS]),
        )
        row = conn.execute("SELECT * FROM board_items WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _to_item(row)


def create_suggestion(user_id: int, project_id: int, kind: str, title: str, details: str = "") -> Item:
    """Add an item found by an agent. Small and major updates wait for accept or reject; a bug
    needs no approval (Janis, 07.11.2026): it goes straight to the top of the bug column, marked
    as coming from an agent, and starts by itself.

    `user_id` is the user the agent works for; like everywhere, the project must be his
    (ValueError otherwise), so an agent can never write into somebody else's board.
    """
    kind, title = _clean(kind, title)
    with db.connect() as conn:
        if not _owns_project(conn, user_id, project_id):
            raise ValueError("Unbekanntes Projekt")
        item_id = add_from_ai(conn, project_id, kind, title, details, approved=kind == "bug", source="agent")
        if item_id is None:
            raise ValueError("Gibt es schon")
        row = conn.execute("SELECT * FROM board_items WHERE id = ?", (item_id,)).fetchone()
    return _to_item(row)


def add_from_ai(conn: sqlite3.Connection, project_id: int, kind: str, title: str, details: str = "",
                approved: bool = False, source: str = "agent", needs: str = "any") -> int | None:
    """An item the manager or an agent put on the board (the caller knows the project is the user's: it comes from the
    job, never from the AI). `approved`: agreed at once, it goes into the queue; else a suggestion that waits for the
    user. None for a bad kind or title, an unknown source, or when an item on the board or being worked on says the
    same already (reply.similar, Janis 21.11.2026: six bullets for one fix): then its context is added to that item."""
    try:
        kind, title = _clean(kind, title)
    except ValueError:
        return None
    if source not in SOURCES:
        return None
    for row in conn.execute("SELECT id, title, details FROM board_items WHERE project_id = ?"
                            " AND status IN ('open', 'proposed', 'working')", (project_id,)):
        if reply.similar(row["title"], title):
            extra = (details or "").strip()
            if extra and extra not in row["details"]:   # what the repeat adds is kept with the item there is
                conn.execute("UPDATE board_items SET details = ? WHERE id = ?",
                             ((row["details"] + "\n\n" + extra).strip()[:MAX_DETAILS], row["id"]))
            return None
    status = "open" if approved else "proposed"
    position = _edge_position(conn, project_id, kind, top=kind == "bug") if approved else 0   # a bug goes on top
    cur = conn.execute(
        "INSERT INTO board_items (project_id, kind, title, source, status, position, created_at, details, needs)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (project_id, kind, title, source, status, position, int(time.time()), (details or "").strip()[:MAX_DETAILS],
         needs if needs in ("any", "mac") else "any"))
    return cur.lastrowid


def edit_from_ai(conn: sqlite3.Connection, project_id: int, item_id: int, kind: str = "", title: str = "",
                 details: str = "") -> bool:
    """The manager corrects an item after a misunderstanding (Janis, 19.11.2026): kind, title and context, each only
    if given. Only an open or proposed item of this project (it comes from the question, never from the AI) that the
    programmer has not started; False otherwise, or for a title another item of the project has."""
    row = conn.execute("SELECT * FROM board_items WHERE id = ? AND project_id = ? AND status IN ('open', 'proposed')",
                       (item_id, project_id)).fetchone()
    if row is None:                                    # taken by the programmer already ("working"), or gone
        return False
    new_kind = kind if kind in KINDS else row["kind"]
    new_title = title.strip()[:MAX_TITLE] if title.strip() else row["title"]
    if conn.execute("SELECT 1 FROM board_items WHERE project_id = ? AND id != ? AND status IN ('open', 'proposed')"
                    " AND lower(title) = lower(?)", (project_id, item_id, new_title)).fetchone():
        return False
    position = row["position"]
    if new_kind != row["kind"] and row["status"] == "open":   # into another column: below what is agreed there
        position = _edge_position(conn, project_id, new_kind, top=False)
    conn.execute("UPDATE board_items SET kind = ?, title = ?, details = ?, position = ? WHERE id = ?",
                 (new_kind, new_title, details.strip()[:MAX_DETAILS] if details.strip() else row["details"], position,
                  item_id))
    return True


def update_title(user_id: int, item_id: int, title: str, details: str | None = None) -> int | None:
    """Rename an item and, if given, change the context behind it. Returns its project id, or None if it is not the
    user's.

    Raises ValueError for an empty or too long title.
    """
    _, title = _clean(KINDS[0], title)
    with db.connect() as conn:
        row = _owned_item(conn, user_id, item_id)
        if row is None:
            return None
        text = row["details"] if details is None else details.strip()[:MAX_DETAILS]
        conn.execute("UPDATE board_items SET title = ?, details = ? WHERE id = ?", (title, text, item_id))
    return row["project_id"]


def _move(user_id: int, item_id: int, allowed_from: tuple[str, ...], to_status: str,
          top: bool | None = None) -> bool:
    """Change the status if the item is the user's and currently in `allowed_from`."""
    with db.connect() as conn:
        row = _owned_item(conn, user_id, item_id)
        if row is None or row["status"] not in allowed_from:
            return False
        position = row["position"]
        if to_status == "open":
            # Accepted items go below the agreed ones, restored manual items to the top.
            if top is None:
                top = row["source"] == "user"
            position = _edge_position(conn, row["project_id"], row["kind"], top=top)
        conn.execute(
            "UPDATE board_items SET status = ?, position = ? WHERE id = ?",
            (to_status, position, item_id),
        )
    return True


def accept(user_id: int, item_id: int) -> bool:
    """Take over a suggestion of the manager or an agent: it is agreed and goes to the programmer by itself."""
    return _move(user_id, item_id, ("proposed",), "open")


def reject(user_id: int, item_id: int) -> bool:
    """Reject a Claude suggestion: it goes to the trash."""
    return _move(user_id, item_id, ("proposed",), "trash")


def discard(user_id: int, item_id: int) -> bool:
    """Put an agreed item into the trash."""
    return _move(user_id, item_id, ("open",), "trash")


def archive(user_id: int, item_id: int) -> bool:
    """A finished item moves into the archive (the agents do this when a task is done)."""
    return _move(user_id, item_id, ("open",), "archived")


def restore(user_id: int, item_id: int) -> bool:
    """Take an item out of the trash or the archive. From the trash, a suggested small or major
    update (of the manager or an agent, never agreed) waits for a decision again; everything else, and anything from
    the archive, is agreed again and goes to the top of its column."""
    with db.connect() as conn:
        row = _owned_item(conn, user_id, item_id)
    if row is None or row["status"] not in ("trash", "archived"):
        return False
    waits = row["status"] == "trash" and row["source"] != "user" and row["kind"] != "bug"
    return _move(user_id, item_id, ("trash", "archived"), "proposed" if waits else "open",
                 top=not waits)


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
