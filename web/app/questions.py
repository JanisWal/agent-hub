"""Questions of the roles during a task (KONZEPT-AGENTEN.md 10.1; Janis, 22.11.2026). Standard library only.

A role asks with <ask kind="choice|text">Question<option>A</option>...</ask> (reply.parse). The question goes to the
manager first (`via` "manager", agents.py queues his "decide" run): he answers it himself, as the user's autonomy
allows, or writes it anew in plain words with his suggestion (`recommended`) and it waits for the user in "waiting for
you" (`via` "user"). The answer goes back as information to the next run of the task, never into the manager chat.
`blocks`: the task waits for the answer. The manager chat has no questions here: he asks in the chat itself.
`status`: open, answered, dropped. Like every data module the user functions get the `user_id`; a foreign question is
None.
"""
import sqlite3
import time
from dataclasses import dataclass, field

from . import db, reply

MAX_OPEN = 10            # open questions per project; more are dropped (an AI that asks too much)
MAX_ANSWER = 1000
ANSWERS_SHOWN = 10       # answers of a task that go into its next package (the newest)


@dataclass
class Question:
    id: int
    project_id: int
    task_id: int | None
    role: str
    text: str
    kind: str                # choice or text
    options: list[str] = field(default_factory=list)
    recommended: int = -1    # the option the manager suggests
    status: str = "open"
    answer: str = ""
    via: str = "user"        # who is to answer it now: manager or user
    blocks: bool = False
    answered_by: str = ""


def _question(row: sqlite3.Row) -> Question:
    options = [o for o in row["options"].split("\n") if o]
    pick = row["recommended"] if 0 <= row["recommended"] < len(options) else -1
    return Question(row["id"], row["project_id"], row["task_id"], row["role"], row["text"], row["kind"], options, pick,
                    row["status"], row["answer"], row["via"], bool(row["blocks"]), row["answered_by"])


def add(conn: sqlite3.Connection, project_id: int, role: str, ask: reply.Ask, task_id: int | None, blocks: bool = False,
        now: int | None = None) -> int | None:
    """Keep a role's question for the manager (the caller knows the project is the user's: it comes from the job).
    None when the same question of the task is open already (it then holds the task too, if this one does) or the
    project has MAX_OPEN open questions."""
    for row in conn.execute("SELECT id, text FROM questions WHERE project_id = ? AND task_id IS ? AND status = 'open'",
                            (project_id, task_id)).fetchall():
        if reply.similar(row["text"], ask.text):
            if blocks:
                conn.execute("UPDATE questions SET blocks = 1 WHERE id = ?", (row["id"],))
            return None
    if conn.execute("SELECT COUNT(*) FROM questions WHERE project_id = ? AND status = 'open'",
                    (project_id,)).fetchone()[0] >= MAX_OPEN:
        return None
    return conn.execute(
        "INSERT INTO questions (project_id, task_id, role, text, kind, options, recommended, via, blocks, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, 'manager', ?, ?)",
        (project_id, task_id, role, ask.text, ask.kind, "\n".join(ask.options), ask.recommended, int(blocks),
         int(now if now is not None else time.time()))).lastrowid


def get(conn: sqlite3.Connection, question_id: int | None, project_id: int) -> Question | None:
    """A question of this project (the caller's job names it)."""
    row = conn.execute("SELECT * FROM questions WHERE id = ? AND project_id = ?", (question_id, project_id)).fetchone()
    return None if row is None else _question(row)


def manager_answer(conn: sqlite3.Connection, question_id: int, text: str, now: int | None = None) -> None:
    """The manager decided it himself (agents._finish_decide)."""
    conn.execute("UPDATE questions SET status = 'answered', answer = ?, answered_by = 'manager', answered_at = ?"
                 " WHERE id = ? AND status = 'open'", (" ".join(text.split())[:MAX_ANSWER],
                                                       int(now if now is not None else time.time()), question_id))


def rewrite(conn: sqlite3.Connection, question_id: int, ask: reply.Ask) -> None:
    """The manager wrote the question anew for the user, with his suggestion: it waits in "waiting for you"."""
    conn.execute("UPDATE questions SET text = ?, kind = ?, options = ?, recommended = ?, via = 'user'"
                 " WHERE id = ? AND status = 'open'",
                 (ask.text, ask.kind, "\n".join(ask.options), ask.recommended, question_id))


def to_user(conn: sqlite3.Connection, question_id: int) -> None:
    """The question goes to the user as the role asked it (no manager, or his answer could not be read)."""
    conn.execute("UPDATE questions SET via = 'user' WHERE id = ? AND status = 'open'", (question_id,))


def drop_for_task(conn: sqlite3.Connection, task_id: int) -> None:
    """The task is over: its open questions are no decision any more and leave "waiting for you"."""
    conn.execute("UPDATE questions SET status = 'dropped' WHERE task_id = ? AND status = 'open'", (task_id,))


def open_blocking(conn: sqlite3.Connection, task_id: int) -> int:
    """How many open questions hold the task."""
    return conn.execute("SELECT COUNT(*) FROM questions WHERE task_id = ? AND status = 'open' AND blocks = 1",
                        (task_id,)).fetchone()[0]


def open_questions(user_id: int, project_id: int) -> list[Question]:
    """The questions of the user's project that wait for him, oldest first; empty for a foreign project."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT q.* FROM questions q JOIN projects p ON p.id = q.project_id WHERE q.project_id = ? AND p.user_id = ?"
            " AND q.status = 'open' AND q.via = 'user' ORDER BY q.id", (project_id, user_id)).fetchall()
    return [_question(r) for r in rows]


def answer(conn: sqlite3.Connection, user_id: int, question_id: int, text: str, now: int | None = None) -> Question | None:
    """The user's answer to a question that waits for him. None if it is not his, not open for him, or empty."""
    text = " ".join((text or "").split())[:MAX_ANSWER]
    if not text:
        return None
    row = conn.execute("SELECT q.* FROM questions q JOIN projects p ON p.id = q.project_id WHERE q.id = ? AND"
                       " p.user_id = ? AND q.status = 'open' AND q.via = 'user'", (question_id, user_id)).fetchone()
    if row is None:
        return None
    conn.execute("UPDATE questions SET status = 'answered', answer = ?, answered_by = 'user', answered_at = ?"
                 " WHERE id = ?", (text, int(now if now is not None else time.time()), question_id))
    return _question(conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone())


def answers_for(conn: sqlite3.Connection, project_id: int, task_id: int) -> str:
    """The answered questions of a task, as a block of information for each of its next runs; "" if there are none."""
    rows = conn.execute("SELECT * FROM questions WHERE project_id = ? AND task_id = ? AND status = 'answered'"
                        " ORDER BY id DESC LIMIT ?", (project_id, task_id, ANSWERS_SHOWN)).fetchall()[::-1]
    lines = [f"- The {r['role']} asked: {r['text']}\n  Answer of the {'manager' if r['answered_by'] == 'manager' else 'user'}:"
             f" {r['answer']}" for r in rows]
    return "<answers>\n" + "\n".join(lines) + "\n</answers>" if lines else ""
