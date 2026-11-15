"""Connections of a user to an AI that signs in with an API key (Mistral since 14.11.2026; later more). One per user
and provider, never shared, no fallback to anybody else's. Standard library only.

Like claude_link.py, this module only knows the *state*. The key itself is a credential: the user pastes it in the
menu, it stays in the memory of this process for a few minutes (never in the database, never in a log) and the
runner fetches it once (`take_keys`). The runner checks it with the provider, keeps it encrypted in its own folder
(runner/tokens.py, ProviderKeys) and reports back (`complete`). Nobody can read it back, not the owner either.

States: none -> connecting (the runner checks the key) -> connected -> expired (the provider refused the key) ->
connecting ...; "wipe" = disconnected, the runner still deletes the saved key (then the row goes). A deleted account
leaves its rows as "wipe" (no foreign key on purpose), so the runner deletes the key files of a deleted user too.
The user always comes from the session or the database, never from a parameter a browser could send.
"""
import re
import sqlite3
import time

from . import db

PROVIDERS = ("mistral",)          # providers whose connection is an API key (Claude has claude_link.py)
STATUSES = ("none", "connecting", "connected", "expired")
CHECK_SECONDS = 120               # the runner has this long to check a key, else the connection counts as failed
KEY_SECONDS = 300                 # a pasted key waits this long for the runner, then it is forgotten
KEY = re.compile(r"[A-Za-z0-9_-]{16,200}")   # what an API key looks like (Mistral: 32 letters and digits)

_keys: dict[tuple[int, str], tuple[str, int]] = {}   # (user, provider) -> (key, forget at); memory of this process only


def _check_provider(provider: str) -> None:
    if provider not in PROVIDERS:
        raise ValueError("provider")


def _row(conn: sqlite3.Connection, user_id: int, provider: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM ai_connections WHERE user_id = ? AND provider = ?",
                        (user_id, provider)).fetchone()


def _effective(row: sqlite3.Row | None, now: int) -> str:
    if row is None or row["status"] == "wipe":
        return "none"
    if row["status"] == "connecting" and now - row["updated_at"] > CHECK_SECONDS:
        return row["previous"] or "none"                  # the runner never answered: as it was before
    return row["status"]


def status_in(conn: sqlite3.Connection, user_id: int, provider: str, now: int | None = None) -> str:
    _check_provider(provider)
    return _effective(_row(conn, user_id, provider), int(now if now is not None else time.time()))


def connected_in(conn: sqlite3.Connection, user_id: int, provider: str) -> bool:
    return status_in(conn, user_id, provider) == "connected"


def status(user_id: int, provider: str, now: int | None = None) -> str:
    """none, connecting, connected or expired."""
    with db.connect() as conn:
        return status_in(conn, user_id, provider, now)


def _save(conn: sqlite3.Connection, user_id: int, provider: str, new_status: str, now: int,
          previous: str = "") -> None:
    """Write the state. `previous` is the state before a check began (connected or expired: a saved key exists)."""
    conn.execute(
        "INSERT INTO ai_connections (user_id, provider, status, previous, updated_at) VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT(user_id, provider) DO UPDATE SET status = excluded.status, previous = excluded.previous,"
        " updated_at = excluded.updated_at",
        (user_id, provider, new_status, previous, now),
    )


def submit_key(user_id: int, provider: str, key: str, now: int | None = None) -> bool:
    """The user pasted a key (connect, or a new key after "expired"). ValueError("key") for something that is not a
    key; False while a check of an earlier key is still running. A key that works replaces the old one."""
    _check_provider(provider)
    key = key.strip()
    if not KEY.fullmatch(key):
        raise ValueError("key")
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        before = status_in(conn, user_id, provider, now)
        if before == "connecting":
            return False
        _save(conn, user_id, provider, "connecting", now, before if before in ("connected", "expired") else "")
    _keys[(user_id, provider)] = (key, now + KEY_SECONDS)
    return True


def take_keys(now: int | None = None) -> list[tuple[int, str, str]]:
    """Runner: the keys waiting to be checked, as (user_id, provider, key), each handed over once."""
    now = int(now if now is not None else time.time())
    taken = []
    for (user_id, provider), (key, until) in list(_keys.items()):
        del _keys[(user_id, provider)]
        if until >= now and status(user_id, provider, now) == "connecting":
            taken.append((user_id, provider, key))
    return taken


def complete(user_id: int, provider: str, ok: bool, now: int | None = None) -> bool:
    """Runner: the provider accepted the key (connected) or refused it (back to what was before: the old key keeps
    working, "expired" stays "expired", without a saved key the row goes). False if no check was running."""
    _check_provider(provider)
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        row = _row(conn, user_id, provider)
        if row is None or row["status"] != "connecting":
            return False
        if ok:
            _save(conn, user_id, provider, "connected", now)
        elif row["previous"]:
            _save(conn, user_id, provider, row["previous"], now)   # the runner kept the old key file
        else:
            conn.execute("DELETE FROM ai_connections WHERE user_id = ? AND provider = ?", (user_id, provider))
    return True


def mark_expired(user_id: int, provider: str) -> bool:
    """Runner: the provider refused the saved key during a question (revoked, no credit). The runner deletes it."""
    _check_provider(provider)
    with db.connect() as conn:
        if status_in(conn, user_id, provider) != "connected":
            return False
        _save(conn, user_id, provider, "expired", int(time.time()))
    return True


def disconnect(user_id: int, provider: str, now: int | None = None) -> bool:
    """The user removes the connection: "none" for him at once, "wipe" until the runner deleted the saved key."""
    _check_provider(provider)
    now = int(now if now is not None else time.time())
    _keys.pop((user_id, provider), None)
    with db.connect() as conn:
        if _row(conn, user_id, provider) is None:
            return False
        _save(conn, user_id, provider, "wipe", now)
    return True


def wipe_user(conn: sqlite3.Connection, user_id: int) -> None:
    """The account is being deleted (users.delete_user, same transaction): all its saved keys go."""
    conn.execute("UPDATE ai_connections SET status = 'wipe' WHERE user_id = ?", (user_id,))
    for item in [k for k in _keys if k[0] == user_id]:
        _keys.pop(item, None)


def pending_wipes() -> list[tuple[int, str]]:
    """Runner: (user_id, provider) whose saved key has to be deleted (disconnected or deleted accounts). A refused key
    the runner deletes on its own when the provider refuses it (Janis, 14.11.2026); that row stays "expired"."""
    with db.connect() as conn:
        rows = conn.execute("SELECT user_id, provider FROM ai_connections WHERE status = 'wipe'"
                            " ORDER BY user_id, provider").fetchall()
    return [(r["user_id"], r["provider"]) for r in rows]


def wiped(user_id: int, provider: str) -> bool:
    """Runner: the key file is gone. Forgets the row unless the user pasted a new key meanwhile."""
    _check_provider(provider)
    with db.connect() as conn:
        return conn.execute("DELETE FROM ai_connections WHERE user_id = ? AND provider = ? AND status = 'wipe'",
                            (user_id, provider)).rowcount == 1
