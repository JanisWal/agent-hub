"""The project's code as a ZIP to download (Janis, 21.11.2026: "I can not get at what is being programmed"). Standard
library only.

Only the runner can read the code (its repos stay apart from the web service). So the user asks here (`request`): the
main state of the project, or the branch of one of its tasks. The runner takes the waiting requests (`pending`), makes
the ZIP with `git archive` and hands it over (`deliver`, base64 in a form field, at most serversettings.export_mb). The
page asks how it goes (`state`) and then downloads the file (`path`). A file goes after KEEP_SECONDS, with its project
(the row goes by the foreign key, the file with `sweep`) and with the account (the projects go with it).
"""
import sqlite3
import time
from pathlib import Path

from . import agents, db, serversettings

KEEP_SECONDS = 3600          # a ZIP is kept this long for the download
WAIT_SECONDS = 180           # a request the runner did not answer in this time counts as failed


def limit() -> int:
    """The largest ZIP in bytes (serversettings.export_mb)."""
    return serversettings.export_mb() * 1024 * 1024


def folder() -> Path:
    """Next to the database, like the stored files (files.files_dir)."""
    return Path(db.DB_PATH).parent / "exports"


def _owned_project(conn: sqlite3.Connection, user_id: int, project_id: int) -> bool:
    return conn.execute("SELECT 1 FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id)).fetchone() is not None


def request(user_id: int, project_id: int, task_id: int | None = None, now: int | None = None) -> int:
    """Ask for a ZIP of the project's main state, or of one of its tasks. ValueError("project") for a project or task
    that is not the user's. A request of the same kind that is still waiting is reused."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        if not _owned_project(conn, user_id, project_id):
            raise ValueError("project")
        if task_id is not None and conn.execute("SELECT 1 FROM agent_tasks WHERE id = ? AND project_id = ?",
                                                (task_id, project_id)).fetchone() is None:
            raise ValueError("project")
        same = conn.execute("SELECT id FROM code_exports WHERE user_id = ? AND project_id = ? AND task_id IS ?"
                            " AND status = 'waiting' AND created_at > ?",
                            (user_id, project_id, task_id, now - WAIT_SECONDS)).fetchone()
        if same:
            return same["id"]
        return conn.execute("INSERT INTO code_exports (user_id, project_id, task_id, status, created_at)"
                            " VALUES (?, ?, ?, 'waiting', ?)", (user_id, project_id, task_id, now)).lastrowid


def pending(now: int | None = None) -> list[dict]:
    """Runner: the waiting requests, {id, project_id, ref} (ref: "main" or the task's branch)."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM code_exports WHERE status = 'waiting' AND created_at > ? ORDER BY id",
                            (now - WAIT_SECONDS,)).fetchall()
    return [{"id": r["id"], "project_id": r["project_id"],
             "ref": agents.branch_name(r["task_id"]) if r["task_id"] else "main"} for r in rows]


def deliver(export_id: int, data: bytes) -> bool:
    """Runner: the ZIP of a waiting request. False if it is not waiting; one that is no ZIP or too big counts as
    failed."""
    ok = data[:2] == b"PK" and 22 <= len(data) <= limit()   # a ZIP (an empty project: just its end record)
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM code_exports WHERE id = ? AND status = 'waiting'", (export_id,)).fetchone() is None:
            return False
        if ok:
            folder().mkdir(parents=True, exist_ok=True)
            target = folder() / f"{int(export_id)}.zip"
            target.write_bytes(data)
            target.chmod(0o600)
        conn.execute("UPDATE code_exports SET status = ?, size = ? WHERE id = ?",
                     ("ready" if ok else "failed", len(data) if ok else 0, export_id))
    return ok


def fail(export_id: int) -> None:
    """Runner: the ZIP could not be made (no such branch, too big)."""
    with db.connect() as conn:
        conn.execute("UPDATE code_exports SET status = 'failed' WHERE id = ? AND status = 'waiting'", (export_id,))


def state(user_id: int, project_id: int, export_id: int, now: int | None = None) -> str | None:
    """waiting, ready or failed for the user's own request; None for anything else."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM code_exports WHERE id = ? AND user_id = ? AND project_id = ?",
                           (export_id, user_id, project_id)).fetchone()
    if row is None:
        return None
    if row["status"] == "waiting" and now - row["created_at"] > WAIT_SECONDS:
        return "failed"
    return row["status"]


def path(user_id: int, project_id: int, export_id: int) -> Path | None:
    """The ZIP of the user's own ready request, or None."""
    if state(user_id, project_id, export_id) != "ready":
        return None
    target = folder() / f"{int(export_id)}.zip"
    return target if target.is_file() else None


def sweep(now: int | None = None) -> int:
    """Delete old requests and their files, and files whose request is gone (project or account deleted)."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        conn.execute("DELETE FROM code_exports WHERE created_at < ?", (now - KEEP_SECONDS,))
        keep = {r[0] for r in conn.execute("SELECT id FROM code_exports")}
    gone = 0
    if folder().is_dir():
        for item in folder().glob("*.zip"):
            if not item.stem.isdigit() or int(item.stem) not in keep:
                item.unlink(missing_ok=True)
                gone += 1
    return gone
