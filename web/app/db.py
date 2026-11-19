"""SQLite access: path, schema, migrations and the `connect()` context manager.

Standard library only. Every other data module opens the database with `db.connect()`.
"""
import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

DB_PATH = os.environ.get("HUB_DB", "/data/hub.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    position   INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    page       INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS projects_by_user ON projects (user_id, position);
CREATE TABLE IF NOT EXISTS board_items (
    id         INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    title      TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'user',
    status     TEXT NOT NULL DEFAULT 'open',
    position   INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS board_items_by_project
    ON board_items (project_id, kind, status, position);
CREATE TABLE IF NOT EXISTS password_resets (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS login_attempts (
    ip           TEXT PRIMARY KEY,
    failures     INTEGER NOT NULL,
    window_start INTEGER NOT NULL,
    locked_until INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS claude_connections (
    user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    status     TEXT NOT NULL,
    login_url  TEXT,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_settings (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key     TEXT NOT NULL,
    value   TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);
CREATE TABLE IF NOT EXISTS agent_tasks (
    id            INTEGER PRIMARY KEY,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    item_id       INTEGER REFERENCES board_items(id) ON DELETE SET NULL,
    title         TEXT NOT NULL,
    kind          TEXT NOT NULL,
    needs         TEXT NOT NULL DEFAULT 'any',
    status        TEXT NOT NULL,
    round         INTEGER NOT NULL DEFAULT 1,
    manual_check  INTEGER NOT NULL DEFAULT 0,
    note          TEXT NOT NULL DEFAULT '',
    created_at    INTEGER NOT NULL,
    deadline      INTEGER NOT NULL,
    finished_at   INTEGER
);
CREATE INDEX IF NOT EXISTS agent_tasks_by_project ON agent_tasks (project_id, status);
CREATE TABLE IF NOT EXISTS agent_runs (
    id          INTEGER PRIMARY KEY,
    task_id     INTEGER NOT NULL REFERENCES agent_tasks(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,
    model       TEXT NOT NULL,
    status      TEXT NOT NULL,
    result      TEXT,
    report      TEXT NOT NULL DEFAULT '',
    tokens_in   INTEGER NOT NULL DEFAULT 0,
    tokens_out  INTEGER NOT NULL DEFAULT 0,
    seconds     INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL,
    started_at  INTEGER,
    finished_at INTEGER
);
CREATE INDEX IF NOT EXISTS agent_runs_by_status ON agent_runs (status, created_at);
CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    prompt     TEXT NOT NULL,
    mode       TEXT NOT NULL DEFAULT 'web',
    model      TEXT NOT NULL DEFAULT 'haiku',
    status     TEXT NOT NULL,
    answer     TEXT NOT NULL DEFAULT '',
    tokens_in  INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    started_at INTEGER
);
CREATE INDEX IF NOT EXISTS chat_by_project ON chat_messages (user_id, project_id, id);
-- Regular checks of the manager (checks.py): text, cycle and when it was last done.
CREATE TABLE IF NOT EXISTS checks (
    id         INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    text       TEXT NOT NULL,
    cycle      TEXT NOT NULL,
    last_done  INTEGER,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS checks_by_project ON checks (project_id, id);
-- Devices of a project (devices.py, Janis 07.11.2026): name (what it is), kind, hostname, optional ip, description. `key_enc` is the key encrypted by
-- vault.py ('' = none); it is never shown again and no AI reads it.
CREATE TABLE IF NOT EXISTS devices (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'other',
    hostname    TEXT NOT NULL,
    ip          TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    key_enc     TEXT NOT NULL DEFAULT '',
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS devices_by_project ON devices (project_id, id);
-- What happened on a device (devices.log, 17.11.2026): connections, shell sessions with their length, actions and
-- file transfers, who did it and whether a human or the AI asked. Never what was typed. Goes with the device.
CREATE TABLE IF NOT EXISTS device_log (
    id         INTEGER PRIMARY KEY,
    device_id  INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    user_id    INTEGER,
    origin     TEXT NOT NULL DEFAULT 'human',
    action     TEXT NOT NULL,
    result     TEXT NOT NULL DEFAULT '',
    detail     TEXT NOT NULL DEFAULT '',
    seconds    INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS device_log_by_device ON device_log (device_id, id);
-- What the manager asks to do on a device (devices.request_action, Janis 17.11.2026): it never happens on its own,
-- it waits in "waiting for you" until the user says yes or no. Goes with the device.
CREATE TABLE IF NOT EXISTS device_requests (
    id         INTEGER PRIMARY KEY,
    device_id  INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    action     TEXT NOT NULL,
    reason     TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'open',
    created_at INTEGER NOT NULL,
    decided_at INTEGER
);
CREATE INDEX IF NOT EXISTS device_requests_open ON device_requests (status, device_id);
-- Switching a device on (Wake-on-LAN): written by the web service, sent once by the runner from the server's own
-- network (a broadcast does not leave the broker's Docker network). Only the address, nothing else.
CREATE TABLE IF NOT EXISTS device_wakes (
    id         INTEGER PRIMARY KEY,
    mac        TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    taken_at   INTEGER
);
-- "For you" (todos.py, Janis 16.11.2026): work the user does himself (hardware, fitting, errands), done once,
-- with a note of what he did. Decisions are not here but in "waiting for you" (Manager view).
CREATE TABLE IF NOT EXISTS todos (
    id         INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    text       TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    source     TEXT NOT NULL DEFAULT 'user',
    task_id    INTEGER REFERENCES agent_tasks(id) ON DELETE SET NULL,
    created_at INTEGER NOT NULL,
    done_at    INTEGER
);
CREATE INDEX IF NOT EXISTS todos_by_project ON todos (project_id, id);
-- Earlier versions of the memory files (memory.py, Janis 16.11.2026): before a memory file is replaced, its old text is
-- kept here (at most memory.MAX_VERSIONS per file); the user sees and restores them in the archive of the Manager view.
-- The AIs never read them. `author`: who replaced it ('manager' or 'user').
CREATE TABLE IF NOT EXISTS memory_versions (
    id         INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    text       TEXT NOT NULL,
    author     TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS memory_versions_by_file ON memory_versions (project_id, name, id);
-- Files and links of a project (files.py): the file itself lives in FILES_DIR/<project id>/<id>, a link has a url.
CREATE TABLE IF NOT EXISTS files (
    id         INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    category   TEXT NOT NULL,
    size       INTEGER NOT NULL DEFAULT 0,
    url        TEXT,
    status     TEXT NOT NULL DEFAULT 'ready',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS files_by_project ON files (project_id, category, id);
-- Claude folders still to be deleted after an account was deleted (no foreign key: the user row is gone).
CREATE TABLE IF NOT EXISTS claude_wipes (
    user_id    INTEGER PRIMARY KEY,
    created_at INTEGER NOT NULL
);
-- Restart or shutdown of the Pi, asked for by the owner and fetched once by the runner (power.py).
CREATE TABLE IF NOT EXISTS power_requests (
    id           INTEGER PRIMARY KEY,
    action       TEXT NOT NULL,
    requested_by INTEGER NOT NULL,
    created_at   INTEGER NOT NULL,
    taken_at     INTEGER
);
-- Every question to the manager and its answer, kept for looking things up later (Janis, 14.11.2026; chat.py).
-- Only for the user: the manager never reads it. Clearing the chat does not touch it.
CREATE TABLE IF NOT EXISTS chat_archive (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    prompt      TEXT NOT NULL,
    answer      TEXT NOT NULL,
    status      TEXT NOT NULL,
    model       TEXT NOT NULL DEFAULT '',
    effort      TEXT NOT NULL DEFAULT '',
    created_at  INTEGER NOT NULL,
    answered_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS chat_archive_project ON chat_archive (project_id, created_at);
-- Connections to AIs that sign in with an API key (ai_link.py, Mistral). The key is never here, only the state. No
-- foreign key on purpose: a deleted account leaves its rows as 'wipe' until the runner deleted the key files.
CREATE TABLE IF NOT EXISTS ai_connections (
    user_id    INTEGER NOT NULL,
    provider   TEXT NOT NULL,
    status     TEXT NOT NULL,
    previous   TEXT NOT NULL DEFAULT '',
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, provider)
);
-- Folders the runner still has to delete (agents.py): the code repository of a deleted project ('project') and the
-- work folder of one of its tasks ('task'). No foreign key: the rows they belonged to are gone. A row leaves when the
-- runner reports the folder gone, so nothing of a deleted project or account stays behind, here or on the disk.
CREATE TABLE IF NOT EXISTS work_wipes (
    kind       TEXT NOT NULL,
    ref        INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (kind, ref)
);
-- The written status of a project (statusnote.py, KONZEPT-AGENTEN.md 9.7; 17.11.2026): what the AI wrote in its last
-- status rounds, newest last, a few kept per project. `source` 'ai' is a note; 'failed' marks a round that brought
-- none, so the hub does not try again at once. `fingerprint` is the hash of the facts the AI read.
CREATE TABLE IF NOT EXISTS project_status (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    level       TEXT NOT NULL DEFAULT '',
    title       TEXT NOT NULL DEFAULT '',
    text        TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT 'ai',
    fingerprint TEXT NOT NULL DEFAULT '',
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS project_status_by_project ON project_status (project_id, id);
-- Settings of the whole server, chosen by the owner (serversettings.py), e.g. how uploads are cut.
CREATE TABLE IF NOT EXISTS server_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Columns added after the first release; added to existing databases on first use.
NEW_COLUMNS = {
    "users": {
        "display_name": "TEXT",
        "language": "TEXT NOT NULL DEFAULT 'de'",
        "had_project": "INTEGER NOT NULL DEFAULT 0",
        "role": "TEXT NOT NULL DEFAULT 'user'",
        "must_change_password": "INTEGER NOT NULL DEFAULT 0",
        "files_confirm": "INTEGER NOT NULL DEFAULT 1",    # does deleting a file ask first? (the trash circle of the file tile)
        "deleted_at": "INTEGER",                          # when the account was deleted; gone for good DELETED_DAYS later (users.py)
    },
    # The context behind a short board item and whether it starts on its own (Janis, 19.11.2026, manager-board):
    # items the manager put on the board from the chat, and accepted suggestions, go to the programmer by themselves.
    "board_items": {"details": "TEXT NOT NULL DEFAULT ''", "auto": "INTEGER NOT NULL DEFAULT 0"},
    "projects": {"page": "INTEGER NOT NULL DEFAULT 0", "description": "TEXT NOT NULL DEFAULT ''",
                 "memory_seeded": "INTEGER NOT NULL DEFAULT 0"},   # the fixed memory files were made (memory.py)
    "chat_messages": {"mode": "TEXT NOT NULL DEFAULT 'web'", "model": "TEXT NOT NULL DEFAULT 'haiku'",
                      "extra": "TEXT NOT NULL DEFAULT ''",          # contents of files the manager asked for (memory.py)
                      "rounds": "INTEGER NOT NULL DEFAULT 0",       # how often it was answered again with such files
                      "memory_saved": "INTEGER NOT NULL DEFAULT 0",   # the answer updated the memory file
                      "thoughts": "TEXT NOT NULL DEFAULT ''",         # what the AI thought meanwhile (add_thoughts)
                      "effort": "TEXT NOT NULL DEFAULT ''",           # effort level (catalog.py); '' = older question
                      "provider": "TEXT NOT NULL DEFAULT 'claude'",   # which AI answers (catalog.PROVIDERS)
                      "tried": "TEXT NOT NULL DEFAULT ''",            # AIs that could not answer it (chat fallback)
                      "kind": "TEXT NOT NULL DEFAULT 'chat'"},        # 'chat' or 'status' (a status round, statusnote.py)
    "agent_runs": {"effort": "TEXT NOT NULL DEFAULT ''",     # effort level of the run's model (catalog.py)
                   "provider": "TEXT NOT NULL DEFAULT 'claude'"},   # which AI does the run (aichoice.py)
    "agent_tasks": {"merged": "INTEGER NOT NULL DEFAULT 0"},   # the runner merged the approved branch (agents.py)
    "files": {"parts": "TEXT NOT NULL DEFAULT ''",           # one flag per chunk of an unfinished upload (files.py)
              "trashed_at": "INTEGER",                       # when it went into the trash (files.py, TRASH_DAYS)
              "parent_id": "INTEGER",                        # the folder it lies in; NULL = top of its area (18.11.2026)
              "is_folder": "INTEGER NOT NULL DEFAULT 0"},    # the row is a folder (no file on disk)
    "checks": {"days": "TEXT NOT NULL DEFAULT '1111111'"},   # weekdays of a daily check, Monday first (checks.py)
    "power_requests": {"result": "TEXT"},                    # how a manual backup ended: 'ok' or 'failed' (power.py)
    "claude_connections": {"expires_at": "INTEGER"},         # when the user's Claude token runs out (claude_link.py)
    # The broker's side of a device (devices.py, 17.11.2026): login, the trusted host key and address, the system it
    # runs, what the AI may do, the found updates. `key_enc` holds the key or the password (`auth`), sealed by vault.py.
    "devices": {"ssh_user": "TEXT NOT NULL DEFAULT ''", "ssh_port": "INTEGER NOT NULL DEFAULT 22",
                "auth": "TEXT NOT NULL DEFAULT 'key'", "public_key": "TEXT NOT NULL DEFAULT ''",
                "host_key": "TEXT NOT NULL DEFAULT ''", "host_fp": "TEXT NOT NULL DEFAULT ''",
                "pinned_ip": "TEXT NOT NULL DEFAULT ''", "os_family": "TEXT NOT NULL DEFAULT ''",
                "os_name": "TEXT NOT NULL DEFAULT ''", "sudo_ok": "INTEGER", "lan_ok": "INTEGER NOT NULL DEFAULT 0",
                "ai_actions": "TEXT NOT NULL DEFAULT ''", "ai_password": "INTEGER NOT NULL DEFAULT 0",
                "updates_found": "INTEGER NOT NULL DEFAULT 0", "updates_at": "INTEGER",
                "reboot_needed": "INTEGER NOT NULL DEFAULT 0", "checked_at": "INTEGER",
                "ip_hint": "TEXT NOT NULL DEFAULT ''",    # the address the broker found for the hostname (a suggestion)
                "mac": "TEXT NOT NULL DEFAULT ''",        # for switching on (Wake-on-LAN), found by the connection test
                "picture": "TEXT NOT NULL DEFAULT ''",    # a small picture the user dropped on the device (data URL)
                "icon_ai": "TEXT NOT NULL DEFAULT ''",    # the pictogram the AI chose from the fixed set (statusnote.py)
                "pass_enc": "TEXT NOT NULL DEFAULT ''"},  # the password for the human, sealed (key_enc: the key, for the AI)
}

# The three statements below run once, when a database from before the feature is opened for the
# first time (see `_prepare`), never again: they must not undo later changes.

# Projects from before pages existed (page = 0) get their page from their order, 6 per page.
ASSIGN_PAGES = """
UPDATE projects SET page = 1 + (
    SELECT COUNT(*) FROM projects q
    WHERE q.user_id = projects.user_id
      AND (q.position < projects.position OR (q.position = projects.position AND q.id < projects.id))
) / 6
WHERE page = 0
"""

# Users from before roles existed: admins stay admins, and the oldest admin becomes the owner.
ASSIGN_ROLES = (
    "UPDATE users SET role = 'admin' WHERE is_admin = 1 AND role = 'user'",
    "UPDATE users SET role = 'owner' WHERE id = (SELECT MIN(id) FROM users WHERE role = 'admin')"
    " AND NOT EXISTS (SELECT 1 FROM users WHERE role = 'owner')",
)

_ready: set[str] = set()  # database files whose schema is already current in this process


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _prepare(conn: sqlite3.Connection) -> None:
    """Bring a database up to date: create missing tables, add missing columns, and do the
    one-time conversions of old data (roles, pages, session tokens, the old `is_admin` column)."""
    had_archive = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'chat_archive'").fetchone() is not None
    had_one_tree = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'files_by_place'").fetchone() is not None
    conn.executescript(SCHEMA)
    before = {table: _columns(conn, table) for table in {"users", "projects", "sessions", *NEW_COLUMNS}}
    for table, columns in NEW_COLUMNS.items():
        for name, definition in columns.items():
            if name not in before[table]:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
                except sqlite3.OperationalError:
                    pass  # another process added it first
    conn.execute("CREATE INDEX IF NOT EXISTS files_by_parent ON files (project_id, parent_id)")   # needs the new column
    if not had_one_tree:   # once (18.11.2026, file-tags): one folder tree per project, files.one_tree; the index marks it
        from . import files
        files.one_tree(conn)
        conn.execute("CREATE INDEX IF NOT EXISTS files_by_place ON files (project_id, parent_id, name COLLATE NOCASE)")
    if not had_archive:   # once: the answered questions from before the archive go into it (after the new columns exist)
        conn.execute(
            "INSERT INTO chat_archive (user_id, project_id, prompt, answer, status, model, effort, created_at, answered_at)"
            " SELECT m.user_id, m.project_id, m.prompt, m.answer, m.status, m.model, m.effort, m.created_at, m.created_at"
            " FROM chat_messages m JOIN projects p ON p.id = m.project_id JOIN users u ON u.id = m.user_id"
            " WHERE m.status IN ('done', 'failed')")
    if "is_admin" in before["users"]:
        if "role" not in before["users"]:   # roles come from the old admin flag, once
            for statement in ASSIGN_ROLES:
                conn.execute(statement)
        conn.execute("ALTER TABLE users DROP COLUMN is_admin")   # `role` says it all now
    if "theme" in before["users"]:
        # Until 15.11.2026 the server kept a copy of the style each user saw, only so mails could use it. Mails now
        # follow the reader's mail program (mailtext.py), so the copy goes, once. Remove this once no database can
        # have the column any more.
        conn.execute("ALTER TABLE users DROP COLUMN theme")
    if "page" not in before["projects"]:
        conn.execute(ASSIGN_PAGES)
    if "expires_at" not in before["claude_connections"]:
        # Since 14.11.2026 runs use the one-year token of `claude setup-token`, kept encrypted by the runner. A login
        # of the old kind (Claude Code's own files, which ran out after a day) is not used any more: link again.
        conn.execute("UPDATE claude_connections SET status = 'expired' WHERE status = 'connected'")
    if "token" in before["sessions"]:
        # Sessions used to be stored as the cookie value itself, now only as its hash (a copy of the
        # database or a backup must not contain usable logins). Old sessions cannot be converted:
        # everybody logs in once more.
        conn.execute("ALTER TABLE sessions RENAME COLUMN token TO token_hash")
        conn.execute("DELETE FROM sessions")
    if "details" not in before["board_items"]:
        # Once (19.11.2026, manager-board): an item an agent found was marked "claude"; no AI names in the data.
        conn.execute("UPDATE board_items SET source = 'agent' WHERE source = 'claude'")
    if "pass_enc" not in before["devices"]:
        # Once (17.11.2026): a password used to sit in key_enc (auth 'password'); key and password are kept apart now.
        conn.execute("UPDATE devices SET pass_enc = key_enc, key_enc = '', auth = 'key' WHERE auth = 'password' AND key_enc != ''")
    # Safety net: the database itself refuses a second owner (it does not say who the owner is).
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_one_owner ON users (role) WHERE role = 'owner'")
    conn.commit()


def fresh_id(conn: sqlite3.Connection, table: str, waiting: str) -> int:
    """The id for a new row of `table`: above every row it has AND above every number in `waiting` (a SELECT that
    gives one number: the highest id whose folders the runner still has to delete). SQLite gives the number of a
    deleted last row out again; a new project or account with that number would inherit the old folders (code, a
    saved token) or lose its own when the runner gets to the deletion. Call it inside the inserting transaction."""
    return 1 + max(conn.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}").fetchone()[0],
                   conn.execute(waiting).fetchone()[0] or 0)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open the database (path read at call time) for one unit of work.

    Commits on success, rolls back on an exception and always closes the connection.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        if DB_PATH not in _ready:
            _prepare(conn)
            _ready.add(DB_PATH)
        with conn:
            yield conn
    finally:
        conn.close()
