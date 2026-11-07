"""TEMPORARY test chat: lets a user talk to his own Claude from a project page, to see that the
connection works end to end (login -> runner -> container -> answer). Remove it (this module,
routes/chat.py, the panel in projectpage.py, chat.js, the table) once the agents run for real.

Not an agent: no tools, no project files, one question and one answer at a time. The runner takes the
questions from `claim_next` and reports the answers with `finish`; as everywhere, the user comes from
the database (the message), never from the runner's request.
"""
import sqlite3
import time
from dataclasses import dataclass

from . import claude_link, db

MODEL = "haiku"          # the cheapest model is enough for a connection test
MAX_PROMPT = 2000
MAX_ANSWER = 8000
RUN_SECONDS = 300        # a question the runner does not answer in this time has failed
KEEP = 10                # messages shown per project


@dataclass
class Message:
    id: int
    project_id: int
    prompt: str
    status: str            # queued, running, done, failed
    answer: str
    created_at: int


@dataclass
class ChatJob:
    chat_id: int
    user_id: int
    model: str
    prompt: str


def _message(row: sqlite3.Row) -> Message:
    return Message(row["id"], row["project_id"], row["prompt"], row["status"], row["answer"], row["created_at"])


def _drop_stale(conn: sqlite3.Connection, now: int) -> None:
    conn.execute(
        "UPDATE chat_messages SET status = 'failed', answer = 'timeout'"
        " WHERE status IN ('queued', 'running') AND created_at < ?", (now - RUN_SECONDS,),
    )


def send(user_id: int, project_id: int, prompt: str, now: int | None = None) -> Message:
    """Ask Claude something. Raises ValueError("claude") if the user's Claude is not connected,
    ValueError("busy") while an earlier question of his is still open, ValueError("prompt") for an
    empty or too long text and ValueError("project") if the project is not his."""
    prompt = prompt.strip()
    now = int(now if now is not None else time.time())
    if not prompt or len(prompt) > MAX_PROMPT:
        raise ValueError("prompt")
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id)).fetchone() is None:
            raise ValueError("project")
        if not claude_link.connected_in(conn, user_id):
            raise ValueError("claude")
        _drop_stale(conn, now)
        if conn.execute("SELECT 1 FROM chat_messages WHERE user_id = ? AND status IN ('queued', 'running')",
                        (user_id,)).fetchone():
            raise ValueError("busy")
        cur = conn.execute(
            "INSERT INTO chat_messages (user_id, project_id, prompt, status, created_at)"
            " VALUES (?, ?, ?, 'queued', ?)", (user_id, project_id, prompt, now),
        )
        row = conn.execute("SELECT * FROM chat_messages WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _message(row)


def list_messages(user_id: int, project_id: int) -> list[Message]:
    """The latest messages of this project, oldest first; empty if the project is not the user's."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM (SELECT * FROM chat_messages WHERE user_id = ? AND project_id = ?"
            " ORDER BY id DESC LIMIT ?) ORDER BY id", (user_id, project_id, KEEP),
        ).fetchall()
    return [_message(r) for r in rows]


def claim_next(now: int | None = None) -> ChatJob | None:
    """Runner: the oldest open question whose user has his Claude connected (nobody else's is used)."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        _drop_stale(conn, now)
        if conn.execute("SELECT 1 FROM chat_messages WHERE status = 'running'").fetchone():
            return None   # the Pi answers one at a time
        for row in conn.execute("SELECT * FROM chat_messages WHERE status = 'queued' ORDER BY id").fetchall():
            if claude_link.connected_in(conn, row["user_id"]):
                conn.execute("UPDATE chat_messages SET status = 'running', started_at = ? WHERE id = ?", (now, row["id"]))
                return ChatJob(row["id"], row["user_id"], MODEL, row["prompt"])
    return None


def finish(chat_id: int, ok: bool, answer: str, tokens_in: int = 0, tokens_out: int = 0) -> bool:
    """Runner: the answer (or the reason for failure). False if the question is not running any more."""
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE chat_messages SET status = ?, answer = ?, tokens_in = ?, tokens_out = ?"
            " WHERE id = ? AND status = 'running'",
            ("done" if ok else "failed", answer[:MAX_ANSWER], max(0, int(tokens_in)), max(0, int(tokens_out)), chat_id),
        )
    return cur.rowcount == 1
