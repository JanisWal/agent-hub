"""The Claude connection of a user: one per user, never shared. Standard library only.

This module only knows the *state* of the connection. The credentials themselves are written by
Claude Code into the user's own folder (`config_dir`) and are never stored in the database, never
passed through the web container and never shown to anybody (not even the owner).

States: none -> connecting -> connected -> expired -> connecting ...
The runner does the real login (Claude Code prints a link, the user confirms it at Claude and
gets a code); it reports back with `set_login_url`, `complete` and `mark_expired`. The user is
always taken from the database, never from a parameter a browser could send.
"""
import os
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse

from . import db

STATUSES = ("none", "connecting", "connected", "expired")
CONNECT_TIMEOUT = 600  # seconds the user has to confirm the login before it is given up
BASE_DIR = Path(os.environ.get("HUB_CLAUDE_DIR", "/data/claude"))
LOGIN_HOSTS = ("claude.ai", "claude.com", "anthropic.com")  # the login link must lead there


def config_dir(user_id: int) -> Path:
    """The private Claude folder of one user (`CLAUDE_CONFIG_DIR` of his runs). Never shared."""
    return BASE_DIR / str(int(user_id))


def _row(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM claude_connections WHERE user_id = ?", (user_id,)).fetchone()


def _effective(row: sqlite3.Row | None, now: int) -> str:
    if row is None:
        return "none"
    if row["status"] == "connecting" and now - row["updated_at"] > CONNECT_TIMEOUT:
        return "none"  # nobody confirmed the link in time
    return row["status"]


def status_in(conn: sqlite3.Connection, user_id: int, now: int | None = None) -> str:
    return _effective(_row(conn, user_id), int(now if now is not None else time.time()))


def connected_in(conn: sqlite3.Connection, user_id: int) -> bool:
    """For code that already holds a connection (the job queue): is this user's Claude usable?"""
    return status_in(conn, user_id) == "connected"


def status(user_id: int, now: int | None = None) -> str:
    """none, connecting, connected or expired."""
    with db.connect() as conn:
        return status_in(conn, user_id, now)


def is_connected(user_id: int) -> bool:
    return status(user_id) == "connected"


def login_url(user_id: int) -> str | None:
    """The link the user has to open while `connecting`, else None."""
    with db.connect() as conn:
        row = _row(conn, user_id)
        if row is None or status_in(conn, user_id) != "connecting":
            return None
        return row["login_url"]


def _save(conn: sqlite3.Connection, user_id: int, new_status: str, url: str | None, now: int) -> None:
    conn.execute(
        "INSERT INTO claude_connections (user_id, status, login_url, updated_at) VALUES (?, ?, ?, ?)"
        " ON CONFLICT(user_id) DO UPDATE SET status = excluded.status,"
        " login_url = excluded.login_url, updated_at = excluded.updated_at",
        (user_id, new_status, url, now),
    )


def begin(user_id: int, now: int | None = None) -> bool:
    """The user pressed "connect Claude". Allowed when nothing is connected (none, expired, or a
    login that timed out). False if he is connected already or a login is running."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        if status_in(conn, user_id, now) in ("connected", "connecting"):
            return False
        _save(conn, user_id, "connecting", None, now)
    return True


def set_login_url(user_id: int, url: str, now: int | None = None) -> bool:
    """Runner: Claude Code printed the login link. Only a plain https link to Claude is taken."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not any(host == h or host.endswith("." + h) for h in LOGIN_HOSTS):
        raise ValueError("Ungueltiger Anmeldelink")
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        if status_in(conn, user_id, now) != "connecting":
            return False
        _save(conn, user_id, "connecting", url, now)
    return True


def complete(user_id: int, ok: bool, now: int | None = None) -> bool:
    """Runner: the login finished. Success means connected, failure goes back to none."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        if status_in(conn, user_id, now) != "connecting":
            return False
        _save(conn, user_id, "connected" if ok else "none", None, now)
    _codes.pop(user_id, None)
    return True


def pending_logins(now: int | None = None) -> list[tuple[int, str | None]]:
    """Runner: users who are in the middle of a login, as (user_id, login_url or None).
    The runner starts Claude Code for those without a link and reports the link back."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM claude_connections WHERE status = 'connecting'").fetchall()
    return [(r["user_id"], r["login_url"]) for r in rows if _effective(r, now) == "connecting"]


# The code the user types after confirming the login. It is a credential: it stays in the memory of
# this process for a few minutes, is never written to the database or a log, and is handed over once.
_codes: dict[int, tuple[str, int]] = {}
CODE_SECONDS = 300
MAX_CODE = 2000


def submit_code(user_id: int, code: str, now: int | None = None) -> bool:
    """The user typed the code. Only accepted while his login waits for it (a link was shown)."""
    code = code.strip()
    now = int(now if now is not None else time.time())
    if not code or len(code) > MAX_CODE:
        raise ValueError("Ungueltiger Code")
    with db.connect() as conn:
        row = _row(conn, user_id)
        if status_in(conn, user_id, now) != "connecting" or not row["login_url"]:
            return False
    _codes[user_id] = (code, now + CODE_SECONDS)
    return True


def take_code(user_id: int, now: int | None = None) -> str | None:
    """Runner: fetch the code once (it is forgotten right away)."""
    now = int(now if now is not None else time.time())
    code, expires = _codes.pop(user_id, (None, 0))
    return code if code is not None and expires >= now else None


def mark_expired(user_id: int) -> bool:
    """Runner: Claude Code says the login is no longer valid. Tasks of this user now wait."""
    with db.connect() as conn:
        if status_in(conn, user_id) != "connected":
            return False
        _save(conn, user_id, "expired", None, int(time.time()))
    return True


def disconnect(user_id: int) -> bool:
    """The user removes his connection. The runner deletes `config_dir(user_id)` afterwards."""
    with db.connect() as conn:
        if _row(conn, user_id) is None:
            return False
        conn.execute("DELETE FROM claude_connections WHERE user_id = ?", (user_id,))
    _codes.pop(user_id, None)
    return True
