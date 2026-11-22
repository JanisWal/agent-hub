"""Which AIs a user has connected and which one is his standard (Janis, 15.11.2026). Standard library only.

Every user may have one AI or several (Claude, Mistral, later ChatGPT). One of them is his *standard*: the manager
chat and the agent runs use it, and the model picker shows only its models. When the standard can not answer (not
connected, expired, its quota used up), the next AI of the same user takes over (`order`): never anybody else's.

The choice is a setting of the user (agent_settings, key "ai.default"); a saved standard that is no longer connected
counts as not set, then the first connected AI (in the order of catalog.PROVIDERS) is the standard.
"""
import sqlite3
import time

from . import catalog, credentials, db, serversettings

KEY = "ai.default"
PREVIOUS = "ai.previous"   # the standard before the current one (Janis, 21.11.2026: it moves to the second place)
REST = "ai.rest."   # + provider: until when its quota is used up (unix time), agent_settings


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


def resting(conn: sqlite3.Connection, user_id: int, provider: str, now: int | None = None) -> bool:
    """Did this AI's quota run out a short while ago (`rest`)? Then it is asked last, not first."""
    row = conn.execute("SELECT value FROM agent_settings WHERE user_id = ? AND key = ?",
                       (user_id, REST + provider)).fetchone()
    return row is not None and int(row["value"] or 0) > int(now if now is not None else time.time())


def rest_left(conn: sqlite3.Connection, user_id: int, provider: str, now: int | None = None) -> int:
    """Seconds until a resting AI is asked first again (0: it is not resting)."""
    row = conn.execute("SELECT value FROM agent_settings WHERE user_id = ? AND key = ?",
                       (user_id, REST + provider)).fetchone()
    return max(0, int(row["value"] or 0) - int(now if now is not None else time.time())) if row else 0


def acting_in(conn: sqlite3.Connection, user_id: int, provider: str, now: int | None = None) -> str:
    """The AI that answers for `provider` now (Janis, 22.11.2026: "ChatGPT is my current AI for a while"): itself, or
    while its quota rests the first other AI of the user that is connected and not resting (order_in). The pickers and
    the role pills show this one, so the next question goes straight to it; when the rest is over it is `provider`
    again. Itself, too, when no other AI can."""
    if not resting(conn, user_id, provider, now):
        return provider
    return next((p for p in order_in(conn, user_id) if p != provider and connected_in(conn, user_id, p)
                 and not resting(conn, user_id, p, now)), provider)


def rest(conn: sqlite3.Connection, user_id: int, provider: str, now: int | None = None) -> None:
    """The AI said its quota is used up: for serversettings.ai_rest minutes the user's other AIs go first, so new
    questions and runs do not fail at it again and again (Janis, 21.11.2026). It is still asked when no other can."""
    minutes = serversettings.ai_rest()
    if not minutes:
        return
    until = int(now if now is not None else time.time()) + minutes * 60
    conn.execute("INSERT INTO agent_settings (user_id, key, value) VALUES (?, ?, ?)"
                 " ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (user_id, REST + provider, str(until)))


def ranked_in(conn: sqlite3.Connection, user_id: int) -> list[str]:
    """The user's connected AIs in the order they are shown and asked (Janis, 21.11.2026: it arranges itself, nobody
    moves it by hand): the standard, the one that was the standard before it, then the others in the catalog's order."""
    have = connected_list(conn, user_id)
    if not have:
        return []
    first = default_in(conn, user_id)
    row = conn.execute("SELECT value FROM agent_settings WHERE user_id = ? AND key = ?", (user_id, PREVIOUS)).fetchone()
    second = row["value"] if row is not None and row["value"] in have and row["value"] != first else None
    return [first] + ([second] if second else []) + [p for p in have if p not in (first, second)]


def ranked(user_id: int) -> list[str]:
    with db.connect() as conn:
        return ranked_in(conn, user_id)


def order_in(conn: sqlite3.Connection, user_id: int) -> list[str]:
    """The AIs to ask, in turn (ranked_in: the standard, the one before it, the others: the fallback); an AI that is
    resting after a used-up quota comes after all the others."""
    first = default_in(conn, user_id)
    order = ranked_in(conn, user_id) or [first]
    return [p for p in order if not resting(conn, user_id, p)] + [p for p in order if resting(conn, user_id, p)]


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
        before = default_in(conn, user_id)
        for key, value in ((KEY, provider), (PREVIOUS, before)) if before != provider else ((KEY, provider),):
            conn.execute("INSERT INTO agent_settings (user_id, key, value) VALUES (?, ?, ?)"
                         " ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (user_id, key, value))
    return True
