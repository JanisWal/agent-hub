"""The Claude connection of a user: one per user, never shared. Standard library only.

This module only knows the *state* of the connection. The credential itself (since 14.11.2026 the one-year token of
`claude setup-token`) is kept by the runner, encrypted, in the user's own folder (`config_dir`, runner/tokens.py); it
is never stored in the database, never passed through the web container and never shown to anybody (not even the
owner). Runs only get a ticket for it.

States: none -> connecting -> connected -> (expiring: less than RENEW_DAYS left) -> expired -> connecting ...
`expires_at` is when the token runs out (a year after the sign-in); "expiring" works like "connected" and offers
"renew", which signs in again while the old token keeps working until the new one is there.
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

STATUSES = ("none", "connecting", "connected", "expiring", "expired")
TOKEN_DAYS = 365       # claude setup-token makes a token for one year
RENEW_DAYS = 30        # from this many days before the end the menu offers "renew"
CONNECT_TIMEOUT = 600  # seconds the user has to confirm the login before it is given up
BASE_DIR = Path(os.environ.get("HUB_CLAUDE_DIR", "/data/claude"))
LOGIN_HOSTS = ("claude.ai", "claude.com", "anthropic.com")  # the login link must lead there


def config_dir(user_id: int) -> Path:
    """The private Claude folder of one user (`CLAUDE_CONFIG_DIR` of his runs). Never shared."""
    return BASE_DIR / str(int(user_id))


def _row(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM claude_connections WHERE user_id = ?", (user_id,)).fetchone()


def _effective(row: sqlite3.Row | None, now: int) -> str:
    if row is None or row["status"] == "wipe":   # "wipe": disconnected, the runner still deletes the folder
        return "none"
    if row["status"] == "connecting" and now - row["updated_at"] > CONNECT_TIMEOUT:
        return _fallback(row, now)  # nobody confirmed the link in time
    if row["status"] == "connected" and row["expires_at"]:
        if now >= row["expires_at"]:
            return "expired"
        if row["expires_at"] - now < RENEW_DAYS * 86400:
            return "expiring"
    return row["status"]


def _fallback(row: sqlite3.Row, now: int) -> str:
    """Where a sign-in that did not work leaves the user: a renewal keeps the token that still works."""
    if row["expires_at"] and row["expires_at"] > now:
        return "expiring" if row["expires_at"] - now < RENEW_DAYS * 86400 else "connected"
    return "none"


def status_in(conn: sqlite3.Connection, user_id: int, now: int | None = None) -> str:
    return _effective(_row(conn, user_id), int(now if now is not None else time.time()))


def connected_in(conn: sqlite3.Connection, user_id: int) -> bool:
    """For code that already holds a connection (the job queue): is this user's Claude usable?"""
    return status_in(conn, user_id) in ("connected", "expiring")


def status(user_id: int, now: int | None = None) -> str:
    """none, connecting, connected, expiring or expired."""
    with db.connect() as conn:
        return status_in(conn, user_id, now)


def is_connected(user_id: int) -> bool:
    return status(user_id) in ("connected", "expiring")


def login_url(user_id: int) -> str | None:
    """The link the user has to open while `connecting`, else None."""
    with db.connect() as conn:
        row = _row(conn, user_id)
        if row is None or status_in(conn, user_id) != "connecting":
            return None
        return row["login_url"]


def _save(conn: sqlite3.Connection, user_id: int, new_status: str, url: str | None, now: int,
          expires_at: int | None = None, keep_expiry: bool = True) -> None:
    """Write the state. The end of the token stays as it was unless a new one is given (or keep_expiry=False)."""
    conn.execute(
        "INSERT INTO claude_connections (user_id, status, login_url, updated_at, expires_at) VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT(user_id) DO UPDATE SET status = excluded.status, login_url = excluded.login_url,"
        " updated_at = excluded.updated_at,"
        " expires_at = CASE WHEN ? AND excluded.expires_at IS NULL THEN expires_at ELSE excluded.expires_at END",
        (user_id, new_status, url, now, expires_at, int(keep_expiry)),
    )


def begin(user_id: int, now: int | None = None) -> bool:
    """The user pressed "connect Claude" (or "renew"). Allowed when nothing usable is connected (none, expired, a
    login that timed out) or the token runs out soon (expiring). False if he is connected or a login is running."""
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
    """Runner: the login finished. Success means connected with a new token for TOKEN_DAYS; failure goes back to
    none, or to the old token if it still works (a renewal that did not go through)."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        if status_in(conn, user_id, now) != "connecting":
            return False
        if ok:
            _save(conn, user_id, "connected", None, now, expires_at=now + TOKEN_DAYS * 86400)
        else:
            back = _fallback(_row(conn, user_id), now)
            _save(conn, user_id, "connected" if back != "none" else "none", None, now, keep_expiry=back != "none")
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
    """Runner: Claude says the token is no longer valid (or there is no token). Tasks of this user now wait."""
    with db.connect() as conn:
        if status_in(conn, user_id) not in ("connected", "expiring"):
            return False
        _save(conn, user_id, "expired", None, int(time.time()), keep_expiry=False)
    return True


def disconnect(user_id: int, now: int | None = None) -> bool:
    """The user removes his connection (or cancels a login). For the user it is `none` at once; the
    row stays as "wipe" until the runner has deleted `config_dir(user_id)` (`wiped`). The web
    container cannot reach that folder itself, and the saved login must not be left behind."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        if _row(conn, user_id) is None:
            return False
        _save(conn, user_id, "wipe", None, now)
    _codes.pop(user_id, None)
    return True


def expired_users(now: int | None = None) -> list[int]:
    """Runner: users whose token has run out or was refused (Janis, 14.11.2026: expired tokens are deleted on their
    own). The runner deletes their saved token; the state stays "expired", so the menu still offers "renew"."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM claude_connections WHERE status IN ('connected', 'expired')").fetchall()
    return [r["user_id"] for r in rows if _effective(r, now) == "expired"]


def pending_wipes() -> list[int]:
    """Runner: users whose folder has to be deleted."""
    with db.connect() as conn:
        return [r["user_id"] for r in conn.execute(
            "SELECT user_id FROM claude_connections WHERE status = 'wipe'"
            " UNION SELECT user_id FROM claude_wipes ORDER BY 1")]


def wiped(user_id: int) -> bool:
    """Runner: the folder is gone. Forgets the row unless the user has started a new login meanwhile."""
    with db.connect() as conn:
        cur = conn.execute("DELETE FROM claude_connections WHERE user_id = ? AND status = 'wipe'", (user_id,))
        queued = conn.execute("DELETE FROM claude_wipes WHERE user_id = ?", (user_id,))
    return cur.rowcount + queued.rowcount >= 1
