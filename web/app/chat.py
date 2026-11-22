"""The manager chat of a project (Manager view, Janis 07.11.2026): the user's own Claude as the advising
manager of this project, hardware included.

One question and one answer at a time, in a container with the project's files and code read-only (/files, /code). What the manager knows
comes from the hub, built in `claim_next` from this user's data only (prompts.manager_chat): rules, memory, the state
of the project and the last questions and answers. It goes to the AI on stdin together with the question
(`ChatJob.prompt`), never on the command line, and it is marked as data, not instructions. The user picks the model per question (drop-down in the window).
The runner takes the questions from `claim_next` and reports the answers with `finish`; as everywhere,
the user comes from the database (the message), never from the runner's request. Every user keeps at
most MAX_STORED messages (the oldest go first) and can delete the history from the menu (`delete_all`).
"""
import sqlite3
import time
from dataclasses import dataclass, field

from . import (agents, ai_link, aichoice, autofolders, board, catalog, credentials, db, devices, failures, files, i18n,
               memory, models, prompts, questions, reply, serversettings, statusnote, toolcheck)

# The manager is the role "chef": model and effort level are settings of the user (agents.py, list in catalog.py).
# What the manager is told (rules, memory, project) is built in prompts.py, the same for every AI.
MAX_PROMPT = 2000
MAX_THOUGHTS = 20000      # characters of thoughts kept per question (what the AI showed while it thought)
MAX_ANSWER = 8000
KEEP = 10                # messages shown per project
MAX_STORED = 100         # messages kept per user, the oldest go first
# "all": web and code together, code with the open internet; "apart": web search, code without internet.
# Which one is the user's setting agents.net_in ("together"/"apart"). Old messages may still say "web".
MODES = ("all", "apart")   # what a user may choose; "brief" (no tools) is only for status rounds and folder plans (statusnote.py, autofolders.py)
NET_TO_MODE = {"together": "all", "apart": "apart"}
# Why a question failed, read from the reason the runner sent (Janis, 14.11.2026: show a short text, not what Claude
# Code says). The reason stays in the answer column for looking into problems; the page only gets the kind.
FAILURES = ("auth", "timeout", "steps", "limit", "server", "plan", "other")
# A question whose AI fails like this goes to the user's next AI (aichoice.order_in), Janis 15.11.2026; the kinds and
# their patterns are shared with the agent runs (failures.py).
FALLBACK_KINDS = failures.SWITCH


@dataclass
class Message:
    id: int
    project_id: int
    prompt: str
    status: str            # queued, running, done, failed
    answer: str
    created_at: int
    mode: str = "all"
    model: str = ""
    memory_saved: bool = False     # this answer updated the memory file
    effort: str = ""
    provider: str = "claude"       # the AI that answered (or is to answer)
    tried: str = ""                # AIs that could not answer it before, comma separated (the fallback)
    thoughts: str = ""             # what the AI thought on the way (add_thoughts), shown folded above the answer


@dataclass
class ChatJob:
    chat_id: int
    user_id: int
    model: str
    prompt: str            # what Claude reads on stdin: role, project context and the question
    mode: str = "all"
    effort: str = ""       # effort level; empty for questions from before levels existed (Claude Code decides)
    provider: str = "claude"   # which AI answers (catalog.PROVIDERS); the runner picks the adapter by it
    project_id: int = 0        # the runner mounts this project's files (/files) and code (/code) read-only
    files: list = field(default_factory=list)   # files.for_agents: id, name, area, size
    links: list = field(default_factory=list)
    images: bool = False       # the model sees pictures (catalog.sees_images): the adapter lets it look at them
    route: dict = field(default_factory=dict)   # the own AI: its address and model name (ai_link.route_in)
    hub_tools: list = field(default_factory=list)   # the hub's tools this AI gets (toolcheck.hub_tools)
    credential: str = "plan"   # the user's plan or his API key (credentials.py)
    limits: dict = field(default_factory=lambda: serversettings.run_limits())   # the container (serversettings.py)


def _message(row: sqlite3.Row) -> Message:
    return Message(row["id"], row["project_id"], row["prompt"], row["status"], row["answer"], row["created_at"],
                   row["mode"], row["model"], bool(row["memory_saved"]), row["effort"], row["provider"], row["tried"], row["thoughts"])


def failure_kind(reason: str) -> str:
    """auth (lost sign-in), limit, timeout, steps (the step limit was reached), server, plan or other (failures.py)."""
    return failures.kind(reason)

def _drop_stale(conn: sqlite3.Connection, now: int) -> None:
    """A question that got no answer in time fails. While all AI slots are taken (serversettings.ai_parallel), a
    waiting question keeps waiting instead: only one that is being answered can run out."""
    busy = not agents.slot_free(conn)
    statuses = "'running'" if busy else "'queued', 'running'"
    conn.execute(f"UPDATE chat_messages SET status = 'failed', answer = 'timeout'"
                 f" WHERE status IN ({statuses}) AND created_at < ?", (now - serversettings.chat_seconds() - 120,))


def send(user_id: int, project_id: int, prompt: str, mode: str | None = None, now: int | None = None,
         model: str | None = None, effort: str | None = None) -> Message:
    """Ask the manager something. The user's standard AI answers (aichoice.py); raises ValueError("none") if he has
    no AI connected at all, ValueError(provider) if `model` names an AI of his that is not connected,
    ValueError("busy") while an earlier question of his is still open, ValueError("prompt") for an
    empty or too long text, ValueError("mode") for an unknown mode, model or level and ValueError("project")
    if the project is not his. `mode`, `model` and `effort` default to the user's settings of the manager
    (switch "web and code together" -> "all" or "apart"; model and level of the role "chef")."""
    prompt = prompt.strip()
    now = int(now if now is not None else time.time())
    if not prompt or len(prompt) > MAX_PROMPT:
        raise ValueError("prompt")
    if mode is not None and mode not in MODES:
        raise ValueError("mode")
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id)).fetchone() is None:
            raise ValueError("project")
        if not aichoice.connected_list(conn, user_id):
            raise ValueError("none")
        model = model or agents.model_in(conn, user_id, "chef")
        if effort is None:
            effort = catalog.resolve(model, agents.effort_in(conn, user_id, "chef"))[1]
        try:
            catalog.check(model, effort)
        except ValueError:
            raise ValueError("mode") from None
        if not models.permits(conn, user_id, model):   # not in the list of his account (models.py)
            raise ValueError("mode")
        mode = mode or NET_TO_MODE.get(agents.net_in(conn, user_id, "chef"), "apart")
        provider = catalog.provider_of(model)
        if not aichoice.connected_in(conn, user_id, provider):
            raise ValueError(provider)
        _drop_stale(conn, now)
        if conn.execute("SELECT 1 FROM chat_messages WHERE user_id = ? AND kind = 'chat' AND status IN"
                        " ('queued', 'running')", (user_id,)).fetchone():
            raise ValueError("busy")
        cur = conn.execute(
            "INSERT INTO chat_messages (user_id, project_id, prompt, mode, model, effort, provider, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?)", (user_id, project_id, prompt, mode, model, effort, provider, now),
        )
        conn.execute(
            "DELETE FROM chat_messages WHERE user_id = ? AND kind = 'chat' AND id NOT IN"
            " (SELECT id FROM chat_messages WHERE user_id = ? AND kind = 'chat' ORDER BY id DESC LIMIT ?)",
            (user_id, user_id, MAX_STORED),
        )
        row = conn.execute("SELECT * FROM chat_messages WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _message(row)


def list_messages(user_id: int, project_id: int) -> list[Message]:
    """The latest messages of this project, oldest first; empty if the project is not the user's."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM (SELECT * FROM chat_messages WHERE user_id = ? AND project_id = ? AND kind = 'chat'"
            " ORDER BY id DESC LIMIT ?) ORDER BY id", (user_id, project_id, KEEP),
        ).fetchall()
    return [_message(r) for r in rows]


def delete_all(user_id: int) -> int:
    """Delete every question and answer of this user (all projects), for good. Returns how many.
    A question that is just being answered is dropped, too; the runner's late answer finds nothing."""
    with db.connect() as conn:
        return conn.execute("DELETE FROM chat_messages WHERE user_id = ?", (user_id,)).rowcount


def _next_ai(conn: sqlite3.Connection, row: sqlite3.Row, failed: str | None = None) -> str | None:
    """The user's next AI for this question that has not failed it yet (the fallback), or None."""
    tried = {p for p in row["tried"].split(",") if p} | ({failed} if failed else set())
    return next((p for p in aichoice.order_in(conn, row["user_id"])
                 if p not in tried and aichoice.connected_in(conn, row["user_id"], p)), None)


def _switch(conn: sqlite3.Connection, row: sqlite3.Row, provider: str, failed: str) -> None:
    """Give the question to another AI of the same user: its model and level for the manager, the failed AI noted."""
    if row["kind"] == "status":   # a status round stays on the cheapest model of the other AI
        model, effort = catalog.light(provider)
    else:
        model, effort = agents._choice(conn, row["user_id"], "chef", provider)
    tried = ",".join(p for p in dict.fromkeys([*row["tried"].split(","), failed]) if p)
    conn.execute("UPDATE chat_messages SET provider = ?, model = ?, effort = ?, tried = ? WHERE id = ?",
                 (provider, model, effort, tried, row["id"]))


def claim_next(now: int | None = None) -> ChatJob | None:
    """Runner: the oldest open question that one of its user's own AIs can answer: the AI it was asked of, else his
    next one (the fallback, noted in `tried`). Nobody else's AI is ever used."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        _drop_stale(conn, now)
        statusnote.scan(conn, now)   # the written status of projects that changed (statusnote.py), every minute or so
        # As many AI containers at once as the owner allows (agent runs included); a status round is small and runs
        # beside them anyway (Janis, 22.11.2026: the status must not wait for a run of twenty minutes).
        free = agents.slot_free(conn)
        kinds = "" if free else " AND kind = 'status'"
        # a question of the user before a status round (it waits for the next poll, seconds)
        for row in conn.execute(f"SELECT * FROM chat_messages WHERE status = 'queued'{kinds}"
                                " ORDER BY kind = 'status', id").fetchall():
            gone = not aichoice.connected_in(conn, row["user_id"], row["provider"])
            if gone or aichoice.resting(conn, row["user_id"], row["provider"]):   # resting: its quota ran out
                other = _next_ai(conn, row, row["provider"])
                if other is not None and (gone or not aichoice.resting(conn, row["user_id"], other)):
                    _switch(conn, row, other, row["provider"])
                elif gone:
                    continue                                # none of his AIs can: the question waits
                row = conn.execute("SELECT * FROM chat_messages WHERE id = ?", (row["id"],)).fetchone()
            # a question sent on with the key after the plan ran out keeps it while the user allows it (no way back)
            way = (row["credential"] if row["credential"] == "api"
                   and credentials.api_usable(conn, row["user_id"], row["provider"], "chat")
                   else credentials.first(conn, row["user_id"], row["provider"], "chat"))
            conn.execute("UPDATE chat_messages SET status = 'running', started_at = ?, credential = ? WHERE id = ?",
                         (now, way, row["id"]))
            route = ai_link.route_in(conn, row["user_id"], row["provider"], row["model"])
            extra = toolcheck.hub_tools(row["provider"])
            if way != "plan":   # the job carries its way (the runner takes the key instead of the plan)
                extra_way = {"credential": way}
            else:
                extra_way = {}
            if row["kind"] == "status":   # no files and no code: the digest is all it reads
                return ChatJob(row["id"], row["user_id"], row["model"],
                               statusnote.prompt_for(conn, row["user_id"], row["project_id"], now), "brief",
                               row["effort"], row["provider"], 0, route=route, hub_tools=extra, **extra_way)
            if row["kind"] == autofolders.KIND:   # the list on stdin; with "include contents" the files, too
                contents = row["mode"] != "brief"
                stored, links = files.for_agents(conn, row["user_id"], row["project_id"]) if contents else ([], [])
                return ChatJob(row["id"], row["user_id"], row["model"],
                               autofolders.prompt_for(conn, row["user_id"], row["project_id"], contents), row["mode"],
                               row["effort"], row["provider"], row["project_id"] if contents else 0, stored, links,
                               contents and catalog.sees_images(row["model"]), route, extra, **extra_way)
            stored, links = files.for_agents(conn, row["user_id"], row["project_id"])
            return ChatJob(row["id"], row["user_id"], row["model"], prompts.manager_chat(conn, row), row["mode"],
                           row["effort"], row["provider"], row["project_id"], stored, links,
                           catalog.sees_images(row["model"]), route, extra, **extra_way)
    return None


def add_thoughts(chat_id: int, text: str) -> bool:
    """Runner: more of what the AI thinks while it answers (Janis, 18.11.2026: show the thoughts in the chat). Added to
    a question that is running, up to MAX_THOUGHTS characters; False if it is not running any more. The thoughts are
    only shown; they never go into the manager's context or into the archive."""
    if not text:
        return False
    with db.connect() as conn:
        cur = conn.execute("UPDATE chat_messages SET thoughts = substr(thoughts || ?, 1, ?)"
                           " WHERE id = ? AND status = 'running'", (text, MAX_THOUGHTS, chat_id))
    return cur.rowcount == 1


def finish(chat_id: int, ok: bool, answer: str, tokens_in: int = 0, tokens_out: int = 0,
           tools: tuple[list, list | None] | None = None) -> bool:
    """Runner: the answer (or the reason for failure). False if the question is not running any more.

    A good answer is read for two things (memory.py). A new memory file inside <memory> is saved as the project's
    MEMORY.md and cut out of the answer. If the manager asks for files with <read>, the question is put back in
    the queue with their contents (at most READ_ROUNDS times, the tokens of every round are added up) and the
    user only sees the final answer. The user and the project come from the question, never from the runner."""
    tokens_in, tokens_out = max(0, int(tokens_in)), max(0, int(tokens_out))
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM chat_messages WHERE id = ? AND status = 'running'", (chat_id,)).fetchone()
        if row is None:
            return False
    if tools is not None:   # the tools the program named at its start (toolcheck.py)
        toolcheck.record(row["provider"], tools[0], tools[1])
    with db.connect() as conn:
        # quota or sign-in of the plan: the user's key first, if he allows it (only plan -> key, never back: no loop)
        if not ok and row["credential"] == "plan" and failure_kind(answer) in ("limit", "auth"):
            other_way = credentials.next_way(conn, row["user_id"], row["provider"], "chat", row["credential"])
            if other_way is not None:
                conn.execute("UPDATE chat_messages SET status = 'queued', credential = ?, tokens_in = tokens_in + ?,"
                             " tokens_out = tokens_out + ?, created_at = ? WHERE id = ?",
                             (other_way, tokens_in, tokens_out, int(time.time()), chat_id))
                return True
        if not ok and failure_kind(answer) == "limit":            # its quota ran out: other AIs go first a while
            aichoice.rest(conn, row["user_id"], row["provider"])
        if not ok and failure_kind(answer) in FALLBACK_KINDS:      # lost sign-in or quota: the user's next AI
            other = _next_ai(conn, row, row["provider"])
            if other is not None:
                _switch(conn, row, other, row["provider"])
                conn.execute("UPDATE chat_messages SET status = 'queued', tokens_in = tokens_in + ?,"
                             " tokens_out = tokens_out + ?, created_at = ? WHERE id = ?",
                             (tokens_in, tokens_out, int(time.time()), chat_id))
                return True
        if row["kind"] == "status":   # a status round: its note is kept apart, the message itself goes
            statusnote.save(conn, row, ok, answer)
            conn.execute("DELETE FROM chat_messages WHERE id = ?", (chat_id,))
            return True
        if row["kind"] == autofolders.KIND:   # a plan for the folders: it waits for the user's "Apply"
            autofolders.save(conn, row, ok, answer, tokens_in, tokens_out)
            return True
        parsed = memory.parse_answer(answer) if ok else None
        failed = (memory.edit_failures(memory.check_edits(row["user_id"], row["project_id"], parsed.edits))
                  if parsed is not None and parsed.edits else "")
        if parsed is not None and (parsed.reads or failed) and row["rounds"] < memory.READ_ROUNDS:
            # files it asked for, or edits that did not fit: the same question again, nothing of this answer is kept
            asked = memory.contents(conn, row["user_id"], row["project_id"], parsed.reads) if parsed.reads else ""
            note = (f"<edit-failed-note>Nothing of your last answer was saved; these memory edits did not fit, "
                    f"answer again with them fixed:\n{failed}</edit-failed-note>") if failed else ""
            extra = (row["extra"] + "\n\n" if row["extra"] else "") + "\n\n".join(x for x in (asked, note) if x)
            conn.execute(
                "UPDATE chat_messages SET status = 'queued', extra = ?, rounds = rounds + 1,"
                " tokens_in = tokens_in + ?, tokens_out = tokens_out + ?, created_at = ? WHERE id = ?",
                (extra[:memory.MAX_REQUESTED * 2], tokens_in, tokens_out, int(time.time()), chat_id),
            )
            return True
    saved = False
    text = answer
    asks = []
    tasks: list = []
    edits: list = []
    open_asks: list = []
    if parsed is not None:
        text, asks = reply.device_asks(parsed.text)
        signals = reply.parse(text)
        text, tasks, edits, open_asks = signals.text, signals.tasks, signals.edits, signals.asks
        if parsed.memory:
            saved = memory.save_memory(row["user_id"], row["project_id"], parsed.memory)
        for name, body in (parsed.files or {}).items():   # the other memory files it wrote (memory folder)
            saved = memory.save_memory(row["user_id"], row["project_id"], body, name) or saved
        if parsed.edits:                                     # targeted changes; what does not fit is left out
            saved = any(r.ok for r in memory.apply_edits(row["user_id"], row["project_id"], parsed.edits)) or saved
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE chat_messages SET status = ?, answer = ?, tokens_in = tokens_in + ?, tokens_out = tokens_out + ?,"
            " memory_saved = ? WHERE id = ? AND status = 'running'",
            ("done" if ok else "failed", text[:MAX_ANSWER], tokens_in, tokens_out, int(saved), chat_id),
        )
        if cur.rowcount == 1:   # the archive keeps it for looking up later; the manager never reads it
            conn.execute(
                "INSERT INTO chat_archive (user_id, project_id, prompt, answer, status, model, effort, created_at,"
                " answered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (row["user_id"], row["project_id"], row["prompt"], text[:MAX_ANSWER], "done" if ok else "failed",
                 row["model"], row["effort"], row["created_at"], int(time.time())),
            )
            for name, action, reason in asks:   # they wait for the user's yes in "waiting for you" (devices.py)
                devices.request_action(conn, row["user_id"], row["project_id"], name, action, reason)
            for ask in open_asks:   # they wait for the user's answer in "waiting for you" (questions.py)
                questions.add(conn, row["project_id"], "chef", ask)
            for task in tasks:   # on the board of the question's project; the user's request goes to the programmer
                # what the user asked for starts at once, also when the manager read on the web for it (Janis,
                # 22.11.2026: an injected instruction would hardly reach the programmer clearly); its own ideas wait
                approved = task.origin == "user" or task.kind == "bug"
                board.add_from_ai(conn, row["project_id"], task.kind, task.title, task.body, approved=approved,
                                  source="manager")
            late = [e for e in edits if not board.edit_from_ai(conn, row["project_id"], e.item_id, e.kind, e.title, e.body)]
            notes = [("chat_edit_late", len(late))] if late else []
            if notes:   # the programmer was faster, or items wait because the web was read: the user reads why
                lang = (conn.execute("SELECT language FROM users WHERE id = ?", (row["user_id"],)).fetchone() or {"language": "de"})["language"]
                lang = lang if lang in ("de", "en") else "de"
                note = "".join("\n\n" + i18n.t(lang, key, n=n) for key, n in notes)
                conn.execute("UPDATE chat_messages SET answer = substr(answer || ?, 1, ?) WHERE id = ?",
                             (note, MAX_ANSWER, chat_id))
    return cur.rowcount == 1


# --- the chat archive (Janis, 14.11.2026): every question and answer of a project, only for the user. Clearing the
# chat (delete_all) leaves it alone; the manager's context (prompts.manager_chat) never reads it.
ARCHIVE_SHOWN = 2000      # entries a project's archive shows at most (newest)


@dataclass
class Archived:
    id: int
    prompt: str
    answer: str            # empty for a failed question: only its kind is shown, as in the chat
    failure: str           # chat.FAILURES or ""
    model: str
    created_at: int


def archive(user_id: int, project_id: int) -> list[Archived]:
    """The archive of a project, oldest first (the page groups it by day); empty if the project is not the user's."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT a.* FROM chat_archive a JOIN projects p ON p.id = a.project_id"
            " WHERE a.project_id = ? AND p.user_id = ? AND a.user_id = ? ORDER BY a.created_at DESC, a.id DESC LIMIT ?",
            (project_id, user_id, user_id, ARCHIVE_SHOWN),
        ).fetchall()
    return [Archived(r["id"], r["prompt"], "" if r["status"] == "failed" else r["answer"],
                     failure_kind(r["answer"]) if r["status"] == "failed" else "", r["model"], r["created_at"])
            for r in reversed(rows)]


def archive_delete(user_id: int, project_id: int, ids: list[int]) -> int:
    """Delete entries of the archive for good (a day, chosen on the page). Only the user's own; returns how many."""
    ids = [i for i in ids if isinstance(i, int) and i > 0][:ARCHIVE_SHOWN]
    if not ids:
        return 0
    with db.connect() as conn:
        marks = ",".join("?" * len(ids))
        return conn.execute(
            f"DELETE FROM chat_archive WHERE user_id = ? AND project_id = ? AND id IN ({marks})",
            (user_id, project_id, *ids)).rowcount
