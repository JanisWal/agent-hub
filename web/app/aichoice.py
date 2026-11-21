"""Which AIs a user has connected and which one is his standard (Janis, 15.11.2026). Standard library only.

Every user may have one AI or several (Claude, Mistral, later ChatGPT). One of them is his *standard*: the manager
chat and the agent runs use it, and the model picker shows only its models. When the standard can not answer (not
connected, expired, its quota used up), the next AI of the same user takes over (`order`): never anybody else's.

The choice is a setting of the user (agent_settings, key "ai.default"); a saved standard that is no longer connected
counts as not set, then the first connected AI (in the order of catalog.PROVIDERS) is the standard.
"""
import sqlite3

from . import catalog, credentials, db

KEY = "ai.default"


def connected_in(conn: sqlite3.Connection, user_id: int, provider: str) -> bool:
    """Can this user's own account of this provider answer now: its plan, or his API key if he allows it
    (credentials.py)?"""
    return credentials.plan_in(conn, user_id, provider) or credentials.api_usable(conn, user_id, provider)


def connected_list(conn: sqlite3.Connection, user_id: int) -> list[str]:
    """The user's connected AIs, in the order of catalog.PROVIDERS."""
    return [p for p in catalog.PROVIDERS if connected_in(conn, user_id, p)]


def default_in(conn: sqlite3.Connection, user_id: int) -> str:
    """The standard AI: the saved one if it is connected, else the first connected one, else catalog's default."""
    row = conn.execute("SELECT value FROM agent_settings WHERE user_id = ? AND key = ?", (user_id, KEY)).fetchone()
    have = connected_list(conn, user_id)
    if row is not None and row["value"] in have:
        return row["value"]
    return have[0] if have else catalog.DEFAULT_PROVIDER


def order_in(conn: sqlite3.Connection, user_id: int) -> list[str]:
    """The AIs to ask, in turn: the standard first, then the user's other connected AIs (the fallback)."""
    first = default_in(conn, user_id)
    return [first] + [p for p in connected_list(conn, user_id) if p != first]


def default(user_id: int) -> str:
    with db.connect() as conn:
        return default_in(conn, user_id)


def connected(user_id: int) -> list[str]:
    with db.connect() as conn:
        return connected_list(conn, user_id)


def set_default(user_id: int, provider: str) -> bool:
    """Make one of the user's own connected AIs his standard. False for anything else."""
    with db.connect() as conn:
        if provider not in catalog.PROVIDERS or not connected_in(conn, user_id, provider):
            return False
        conn.execute("INSERT INTO agent_settings (user_id, key, value) VALUES (?, ?, ?)"
                     " ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (user_id, KEY, provider))
    return True
