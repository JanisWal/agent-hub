"""The usage ledger (KONZEPT-AGENTEN.md 10.10; Janis, 22.11.2026: "this value has to be reliable"). Standard library only.

One row per call of an AI, written where the runner reports its end (chat.finish, agents.finish_run): chat answers,
status texts, folder plans, every agent run and the manager's short jobs, also a run the runner ended (`partial`: what
it saw in the stream until then) and every try before a switch to another AI or the API key. `tokens_in` is the whole
input; `cache_read` and `cache_write` are the part of it read from or written to the provider's cache (only Claude Code
and Codex report it). Rows never go with the chat history; they go with the account, and stay without a project when a
project is deleted (they belong to the account). The numbers come from the AIs' programs; nothing is estimated.
"""
import sqlite3
import time

from . import db

KINDS = ("chat", "status", "folders", "run")
DAY = 86400


def record(conn: sqlite3.Connection, *, user_id: int, project_id: int | None, provider: str, model: str,
           credential: str, kind: str, tokens_in: int, tokens_out: int, cache_read: int = 0, cache_write: int = 0,
           role: str = "", purpose: str = "", seconds: int = 0, partial: bool = False, ref: int | None = None,
           now: int | None = None) -> None:
    """Keep one call (the caller knows user and project: they come from the job). A call that used nothing is skipped."""
    numbers = [max(0, int(v or 0)) for v in (tokens_in, tokens_out, cache_read, cache_write, seconds)]
    tokens_in, tokens_out, cache_read, cache_write, seconds = numbers
    if not (tokens_in or tokens_out):
        return
    conn.execute(
        "INSERT INTO ai_usage (user_id, project_id, provider, model, credential, kind, role, purpose, ref, tokens_in,"
        " tokens_out, cache_read, cache_write, seconds, partial, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
        " ?, ?, ?, ?)",
        (user_id, project_id, provider or "", model or "", credential or "plan", kind if kind in KINDS else "chat",
         role or "", purpose or "", ref, tokens_in, tokens_out, min(cache_read, tokens_in), min(cache_write, tokens_in),
         seconds, int(bool(partial)), int(now if now is not None else time.time())))


EMPTY = {"calls": 0, "tokens_in": 0, "tokens_out": 0, "cache_read": 0, "cache_write": 0, "seconds": 0}


def totals(user_id: int, project_id: int | None = None, role: str | None = None, kind: str | None = None,
           since: int | None = None) -> dict:
    """The sums of the user's calls, narrowed to a project, a role, a kind or a time: calls, tokens in (with the cache
    part) and out, seconds."""
    sql = ("SELECT COUNT(*) AS calls, COALESCE(SUM(tokens_in), 0) AS tokens_in, COALESCE(SUM(tokens_out), 0) AS tokens_out,"
           " COALESCE(SUM(cache_read), 0) AS cache_read, COALESCE(SUM(cache_write), 0) AS cache_write,"
           " COALESCE(SUM(seconds), 0) AS seconds FROM ai_usage WHERE user_id = ?")
    args: list = [user_id]
    for column, value in (("project_id", project_id), ("role", role), ("kind", kind)):
        if value is not None:
            sql += f" AND {column} = ?"
            args.append(value)
    if since is not None:
        sql += " AND created_at >= ?"
        args.append(int(since))
    with db.connect() as conn:
        return dict(conn.execute(sql, args).fetchone())


def by_ai(user_id: int, now: int | None = None) -> dict[str, dict]:
    """Per AI of the user (a further AI by its place, "custom-3"): tokens in and out today and in the last 7 days."""
    now = int(now if now is not None else time.time())
    today = now - now % DAY
    out: dict[str, dict] = {}
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT CASE WHEN provider = 'custom' AND model LIKE 'own-%' THEN 'custom-' || substr(model, 5) ELSE provider"
            " END AS ai, SUM(CASE WHEN created_at >= ? THEN tokens_in + tokens_out ELSE 0 END) AS today,"
            " SUM(tokens_in + tokens_out) AS week FROM ai_usage WHERE user_id = ? AND created_at >= ? GROUP BY ai",
            (today, user_id, now - 7 * DAY)).fetchall()
    for row in rows:
        out[row["ai"]] = {"today": row["today"] or 0, "week": row["week"] or 0}
    return out
