"""The "For you" list of a project (Janis, 16.11.2026): work the user does himself, physically or technically
(hardware, fitting, errands, the tester's checklists). An entry is done once, and the user writes down what he did.
Decisions are not here: they wait in "waiting for you" in the Manager view.

Like every data module, each function gets the `user_id` and the project must be his: foreign things are "not
found" (None or False). `source` says who made the entry: the user, or a role that needs something only the user can
do (22.11.2026: upload files, connect a device, check by hand; <env> in a run, agents.py). An entry of a role names its
task: a task that waits for it goes on when it is done (agents.check_todos), and the user's note goes into its next
package. Standard library only.
"""
import sqlite3
import time
from dataclasses import dataclass

from . import db

SOURCES = ("user", "programmer", "tester", "reviewer", "manager")
ROLE_SOURCES = ("programmer", "tester", "reviewer")
MAX_TEXT = 500
MAX_NOTE = 4000
MAX_PER_PROJECT = 200


@dataclass
class Todo:
    id: int
    project_id: int
    text: str
    note: str
    source: str
    task_id: int | None
    created_at: int
    done_at: int | None

    @property
    def done(self) -> bool:
        return self.done_at is not None


def _to_todo(row: sqlite3.Row) -> Todo:
    return Todo(row["id"], row["project_id"], row["text"], row["note"], row["source"], row["task_id"],
                row["created_at"], row["done_at"])


def _text(text: str) -> str | None:
    text = text.strip()
    return text if text and len(text) <= MAX_TEXT else None


def _owned(conn: sqlite3.Connection, user_id: int, todo_id: int) -> sqlite3.Row | None:
    """The entry, only if its project belongs to the user."""
    return conn.execute(
        "SELECT t.* FROM todos t JOIN projects p ON p.id = t.project_id WHERE t.id = ? AND p.user_id = ?",
        (todo_id, user_id),
    ).fetchone()


def list_todos(user_id: int, project_id: int) -> list[Todo]:
    """Open entries first (oldest first), then the done ones (last done first); empty for a foreign project."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT t.* FROM todos t JOIN projects p ON p.id = t.project_id WHERE t.project_id = ? AND p.user_id = ?"
            " ORDER BY t.done_at IS NOT NULL, t.done_at DESC, t.id",
            (project_id, user_id),
        ).fetchall()
    return [_to_todo(r) for r in rows]


def open_count(user_id: int, project_id: int) -> int:
    return sum(1 for t in list_todos(user_id, project_id) if not t.done)


def create(user_id: int, project_id: int, text: str, source: str = "user", task_id: int | None = None,
           now: int | None = None) -> int | None:
    """Add an entry; its id, or None for an empty or too long text, an unknown source, a foreign project or task,
    or a full list."""
    text = _text(text)
    if text is None or source not in SOURCES:
        return None
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id)).fetchone() is None:
            return None
        if task_id is not None and conn.execute(
                "SELECT 1 FROM agent_tasks WHERE id = ? AND project_id = ?", (task_id, project_id)).fetchone() is None:
            return None
        if conn.execute("SELECT COUNT(*) FROM todos WHERE project_id = ?", (project_id,)).fetchone()[0] >= MAX_PER_PROJECT:
            return None
        cur = conn.execute(
            "INSERT INTO todos (project_id, text, source, task_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (project_id, text, source, task_id, int(now if now is not None else time.time())),
        )
    return cur.lastrowid


def add_from_role(conn: sqlite3.Connection, project_id: int, role: str, text: str, task_id: int,
                  check: bool = False, now: int | None = None) -> int | None:
    """What a role needs from the user (the caller knows project and task are the user's: they come from the job).
    `check`: the tester's steps to check something by hand. None when the same entry of the task is open already, the
    text is empty or the list is full."""
    from . import i18n, reply   # reply imports nothing of this module
    text = " ".join((text or "").split())
    if not text or role not in ROLE_SOURCES:
        return None
    if check:
        lang = (conn.execute("SELECT u.language FROM users u JOIN projects p ON p.user_id = u.id WHERE p.id = ?",
                             (project_id,)).fetchone() or {"language": "de"})["language"]
        text = i18n.t(lang if lang in ("de", "en") else "de", "todo_check", text=text)
    text = text[:MAX_TEXT]
    for row in conn.execute("SELECT text FROM todos WHERE project_id = ? AND task_id IS ? AND done_at IS NULL",
                            (project_id, task_id)).fetchall():
        if reply.similar(row["text"], text):
            return None
    if conn.execute("SELECT COUNT(*) FROM todos WHERE project_id = ?", (project_id,)).fetchone()[0] >= MAX_PER_PROJECT:
        return None
    return conn.execute("INSERT INTO todos (project_id, text, source, task_id, created_at) VALUES (?, ?, ?, ?, ?)",
                        (project_id, text, role, task_id, int(now if now is not None else time.time()))).lastrowid


def open_for_task(conn: sqlite3.Connection, task_id: int) -> int:
    """How many entries a task waits for."""
    return conn.execute("SELECT COUNT(*) FROM todos WHERE task_id = ? AND done_at IS NULL", (task_id,)).fetchone()[0]


def notes_for(conn: sqlite3.Connection, project_id: int, task_id: int) -> str:
    """What the user did for a task (done entries with his notes), as information for its next runs; "" if nothing."""
    rows = conn.execute("SELECT text, note FROM todos WHERE project_id = ? AND task_id = ? AND done_at IS NOT NULL"
                        " ORDER BY done_at", (project_id, task_id)).fetchall()
    lines = [f"- {r['text']}\n  Done by the user" + (f": {r['note']}" if r["note"] else ".") for r in rows]
    return "<done-by-user>\n" + "\n".join(lines) + "\n</done-by-user>" if lines else ""


def update(user_id: int, todo_id: int, text: str) -> bool:
    text = _text(text)
    with db.connect() as conn:
        if text is None or _owned(conn, user_id, todo_id) is None:
            return False
        conn.execute("UPDATE todos SET text = ? WHERE id = ?", (text, todo_id))
    return True


def finish(user_id: int, todo_id: int, note: str, now: int | None = None) -> bool:
    """Done, with what the user did (may be empty). Done again only changes the note, not the time."""
    note = note.strip()
    if len(note) > MAX_NOTE:
        return False
    with db.connect() as conn:
        row = _owned(conn, user_id, todo_id)
        if row is None:
            return False
        done_at = row["done_at"] if row["done_at"] is not None else int(now if now is not None else time.time())
        conn.execute("UPDATE todos SET note = ?, done_at = ? WHERE id = ?", (note, done_at, todo_id))
    return True


def reopen(user_id: int, todo_id: int) -> bool:
    """Open again; the note stays, so nothing written is lost."""
    with db.connect() as conn:
        if _owned(conn, user_id, todo_id) is None:
            return False
        conn.execute("UPDATE todos SET done_at = NULL WHERE id = ?", (todo_id,))
    return True


def delete(user_id: int, todo_id: int) -> bool:
    with db.connect() as conn:
        if _owned(conn, user_id, todo_id) is None:
            return False
        conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
    return True
