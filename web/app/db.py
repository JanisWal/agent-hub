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
    is_admin      INTEGER NOT NULL DEFAULT 0,
    created_at    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    position   INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    page       INTEGER NOT NULL DEFAULT 0
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
    "projects": {"page": "INTEGER NOT NULL DEFAULT 0"},
}

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


def _prepare(conn: sqlite3.Connection) -> None:
    """Create missing tables, add missing columns, give old projects a page."""
    conn.executescript(SCHEMA)
    for table, columns in NEW_COLUMNS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in existing:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
                except sqlite3.OperationalError:
                    pass  # another process added it first
    for statement in ASSIGN_ROLES:
        conn.execute(statement)
    # Safety net: the database itself refuses a second owner (it does not say who the owner is).
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_one_owner ON users (role) WHERE role = 'owner'")
    conn.execute(ASSIGN_PAGES)
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
