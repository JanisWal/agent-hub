"""Questions of the manager and the roles to the user (KONZEPT-AGENTEN.md 9.4; Janis 19.11.2026: "waiting for you"
must let you write the answer yourself). Standard library only.

An AI asks with <ask kind="choice|text">Question<option>A</option>...</ask> (reply.parse). The hub keeps each question
under the project of the chat or task it came from (never one the AI names) and shows it in "waiting for you" with the
suggested answers as buttons and a free field. The answer goes back as information: a question of the manager chat as
the next chat message (or, while a question is running, with the next one), a question of a run with the next run of
its task. `status`: open, answered (waits to be passed on), delivered. Like every data module the user functions get
the `user_id`; a foreign question is None.
"""
import sqlite3
import time
from dataclasses import dataclass, field

from . import db, reply

MAX_OPEN = 10            # open questions per project; more are dropped (an AI that asks too much)
MAX_ANSWER = 1000


@dataclass
class Question:
    id: int
    project_id: int
    task_id: int | None
    role: str                # chef (the manager chat) or the role of a run
    text: str
    kind: str                # choice or text
    options: list[str] = field(default_factory=list)
    status: str = "open"
    answer: str = ""


def _question(row: sqlite3.Row) -> Question:
    return Question(row["id"], row["project_id"], row["task_id"], row["role"], row["text"], row["kind"],
                    [o for o in row["options"].split("\n") if o], row["status"], row["answer"])


def add(conn: sqlite3.Connection, project_id: int, role: str, ask: reply.Ask, task_id: int | None = None,
        now: int | None = None) -> int | None:
    """Keep a question (the caller knows the project is the user's: it comes from the job). None if the project has
    MAX_OPEN open questions already or the same question is open."""
    if conn.execute("SELECT COUNT(*) FROM questions WHERE project_id = ? AND status = 'open'",
                    (project_id,)).fetchone()[0] >= MAX_OPEN:
        return None
    if conn.execute("SELECT 1 FROM questions WHERE project_id = ? AND status = 'open' AND text = ?",
                    (project_id, ask.text)).fetchone():
        return None
    cur = conn.execute(
        "INSERT INTO questions (project_id, task_id, role, text, kind, options, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, task_id, role, ask.text, ask.kind, "\n".join(ask.options), int(now if now is not None else time.time())))
    return cur.lastrowid


def open_questions(user_id: int, project_id: int) -> list[Question]:
    """The open questions of the user's project, oldest first; empty for a foreign project."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT q.* FROM questions q JOIN projects p ON p.id = q.project_id WHERE q.project_id = ? AND p.user_id = ?"
            " AND q.status = 'open' ORDER BY q.id", (project_id, user_id)).fetchall()
    return [_question(r) for r in rows]


def answer(user_id: int, question_id: int, text: str, now: int | None = None) -> Question | None:
    """The user's answer to an open question of his. None if it is not his, not open, or the answer is empty."""
    text = " ".join((text or "").split())[:MAX_ANSWER]
    if not text:
        return None
    with db.connect() as conn:
        row = conn.execute("SELECT q.* FROM questions q JOIN projects p ON p.id = q.project_id"
                           " WHERE q.id = ? AND p.user_id = ? AND q.status = 'open'", (question_id, user_id)).fetchone()
        if row is None:
            return None
        conn.execute("UPDATE questions SET status = 'answered', answer = ?, answered_at = ? WHERE id = ?",
                     (text, int(now if now is not None else time.time()), question_id))
        row = conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
    return _question(row)


def mark_delivered(conn: sqlite3.Connection, question_id: int) -> None:
    conn.execute("UPDATE questions SET status = 'delivered' WHERE id = ? AND status = 'answered'", (question_id,))


def take_answers(conn: sqlite3.Connection, project_id: int, task_id: int | None) -> str:
    """The answers not passed on yet, for the next package of the manager chat (task_id None) or of a task, as a block
    of information; they count as delivered from now on. "" if there are none."""
    rows = conn.execute(
        "SELECT * FROM questions WHERE project_id = ? AND task_id IS ? AND status = 'answered' ORDER BY id",
        (project_id, task_id)).fetchall()
    for row in rows:
        mark_delivered(conn, row["id"])
    lines = [f"- You asked: {r['text']}\n  The user answered: {r['answer']}" for r in rows]
    return "<answers>\n" + "\n".join(lines) + "\n</answers>" if lines else ""
