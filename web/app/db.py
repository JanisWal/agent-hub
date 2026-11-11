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
"""

# Columns added after the first release; added to existing databases on first use.
NEW_COLUMNS = {
    "users": {
        "display_name": "TEXT",
        "language": "TEXT NOT NULL DEFAULT 'de'",
        "had_project": "INTEGER NOT NULL DEFAULT 0",
        "role": "TEXT NOT NULL DEFAULT 'user'",
        "must_change_password": "INTEGER NOT NULL DEFAULT 0",
        "theme": "TEXT NOT NULL DEFAULT 'light'",
    },
    "projects": {"page": "INTEGER NOT NULL DEFAULT 0", "description": "TEXT NOT NULL DEFAULT ''"},
    "chat_messages": {"mode": "TEXT NOT NULL DEFAULT 'web'", "model": "TEXT NOT NULL DEFAULT 'haiku'"},
    "checks": {"days": "TEXT NOT NULL DEFAULT '1111111'"},   # weekdays of a daily check, Monday first (checks.py)
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
    conn.executescript(SCHEMA)
    before = {table: _columns(conn, table) for table in {"users", "projects", "sessions", *NEW_COLUMNS}}
    for table, columns in NEW_COLUMNS.items():
        for name, definition in columns.items():
            if name not in before[table]:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
                except sqlite3.OperationalError:
                    pass  # another process added it first
    if "is_admin" in before["users"]:
        if "role" not in before["users"]:   # roles come from the old admin flag, once
            for statement in ASSIGN_ROLES:
                conn.execute(statement)
        conn.execute("ALTER TABLE users DROP COLUMN is_admin")   # `role` says it all now
    if "page" not in before["projects"]:
        conn.execute(ASSIGN_PAGES)
    if "token" in before["sessions"]:
        # Sessions used to be stored as the cookie value itself, now only as its hash (a copy of the
        # database or a backup must not contain usable logins). Old sessions cannot be converted:
        # everybody logs in once more.
        conn.execute("ALTER TABLE sessions RENAME COLUMN token TO token_hash")
        conn.execute("DELETE FROM sessions")
    # Safety net: the database itself refuses a second owner (it does not say who the owner is).
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_one_owner ON users (role) WHERE role = 'owner'")
    conn.commit()


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
