"""Subscription or API key for one job (Janis, 21.11.2026): an AI with a plan (Claude, ChatGPT) may also have an API key
of the user. The key can cost extra, so it is used only as the user set it. Standard library only.

Settings per user and AI (agent_settings, `api.<provider>.<name>`):
- mode: "fallback" (default: only when the plan can not answer, e.g. its quota is used up), "always" (the key instead of
  the plan, so the plan's quota stays), "off" (the key is kept but never used);
- scope: "all", "runs" (agent runs only), "chat" (manager chat and the hub's small jobs only);
- daily: at most this many thousand tokens a day through the key (0 = no limit); over it the key waits until tomorrow.
The key itself is a connection of its own (ai_link: "claude-api", "chatgpt-api"), checked and kept by the runner.
Which one a job used stands with it (chat_messages.credential, agent_runs.credential), so the daily limit counts it.
"""
import re
import sqlite3
import time

from . import ai_link, claude_link

API_FOR = {"claude": "claude-api", "chatgpt": "chatgpt-api"}   # the AIs with a plan and an optional key
MODES = ("fallback", "always", "off")
SCOPES = ("all", "runs", "chat")
MAX_DAILY = 1_000_000                                           # thousand tokens a day at most (a typing error guard)
DEFAULTS = {"mode": "fallback", "scope": "all", "daily": "0"}
# A run or answer that failed for its quota or sign-in (the same words as chat.py): the other way is tried first.
EXHAUSTED = re.compile(r"usage limit|limit reached|rate.?limit|\b429\b|no credit|quota|not logged in|\b401\b", re.I)


def _setting(conn: sqlite3.Connection, user_id: int, provider: str, name: str) -> str:
    row = conn.execute("SELECT value FROM agent_settings WHERE user_id = ? AND key = ?",
                       (user_id, f"api.{provider}.{name}")).fetchone()
    return row["value"] if row else DEFAULTS[name]


def settings_in(conn: sqlite3.Connection, user_id: int, provider: str) -> dict:
    """{connected, status, mode, scope, daily, spent} of the user's key for this AI (spent: thousand tokens today)."""
    status = ai_link.status_in(conn, user_id, API_FOR[provider])
    return {"status": status, "connected": status == "connected", "mode": _setting(conn, user_id, provider, "mode"),
            "scope": _setting(conn, user_id, provider, "scope"), "daily": int(_setting(conn, user_id, provider, "daily")),
            "spent": spent_today(conn, user_id, provider) // 1000}


def configure_in(conn: sqlite3.Connection, user_id: int, provider: str, mode: str, scope: str, daily: int) -> None:
    """Save the settings; ValueError for anything not allowed."""
    if provider not in API_FOR or mode not in MODES or scope not in SCOPES or not 0 <= int(daily) <= MAX_DAILY:
        raise ValueError("api settings")
    for name, value in (("mode", mode), ("scope", scope), ("daily", str(int(daily)))):
        conn.execute("INSERT INTO agent_settings (user_id, key, value) VALUES (?, ?, ?)"
                     " ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
                     (user_id, f"api.{provider}.{name}", value))


def _day_start(now: float) -> int:
    local = time.localtime(now)
    return int(time.mktime((local.tm_year, local.tm_mon, local.tm_mday, 0, 0, 0, 0, 0, -1)))


def spent_today(conn: sqlite3.Connection, user_id: int, provider: str, now: float | None = None) -> int:
    """Tokens (in and out) the user's key of this AI used since midnight."""
    since = _day_start(now if now is not None else time.time())
    chats = conn.execute("SELECT COALESCE(SUM(tokens_in + tokens_out), 0) FROM chat_messages WHERE user_id = ?"
                         " AND provider = ? AND credential = 'api' AND created_at >= ?",
                         (user_id, provider, since)).fetchone()[0]
    runs = conn.execute("SELECT COALESCE(SUM(r.tokens_in + r.tokens_out), 0) FROM agent_runs r JOIN agent_tasks t"
                        " ON t.id = r.task_id JOIN projects p ON p.id = t.project_id WHERE p.user_id = ?"
                        " AND r.provider = ? AND r.credential = 'api' AND r.created_at >= ?",
                        (user_id, provider, since)).fetchone()[0]
    return int(chats) + int(runs)


def plan_in(conn: sqlite3.Connection, user_id: int, provider: str) -> bool:
    """Is the user's plan of this AI connected?"""
    if provider == "claude":
        return claude_link.connected_in(conn, user_id)
    if provider == "custom":   # any of his further AIs
        return bool(ai_link.custom_connected(conn, user_id))
    return provider in ai_link.PROVIDERS and ai_link.connected_in(conn, user_id, provider)


def api_usable(conn: sqlite3.Connection, user_id: int, provider: str, kind: str | None = None) -> bool:
    """May the user's key of this AI be used now for a job of this kind ("chat", "run"; None = any)?"""
    if provider not in API_FOR or not ai_link.connected_in(conn, user_id, API_FOR[provider]):
        return False
    s = settings_in(conn, user_id, provider)
    if s["mode"] == "off" or (kind is not None and s["scope"] not in ("all", "chat" if kind == "chat" else "runs")):
        return False
    return not s["daily"] or s["spent"] < s["daily"]


def order(conn: sqlite3.Connection, user_id: int, provider: str, kind: str) -> list[str]:
    """The ways this job may take at this AI, in turn: "plan" and/or "api" (empty = none)."""
    plan, api = plan_in(conn, user_id, provider), api_usable(conn, user_id, provider, kind)
    if provider in API_FOR and api and _setting(conn, user_id, provider, "mode") == "always":
        return ["api"] + (["plan"] if plan else [])
    return (["plan"] if plan else []) + (["api"] if api else [])


def first(conn: sqlite3.Connection, user_id: int, provider: str, kind: str) -> str:
    """The way a new job takes ("plan" when there is none either: the job then waits or goes to the next AI)."""
    ways = order(conn, user_id, provider, kind)
    return ways[0] if ways else "plan"


def next_way(conn: sqlite3.Connection, user_id: int, provider: str, kind: str, failed: str) -> str | None:
    """After the plan or key failed for its quota or sign-in: the other way at the same AI, if the user allows it."""
    ways = order(conn, user_id, provider, kind)
    return next((w for w in ways if w != failed), None)
