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


def by_ai(user_id: int, now: int | None = None, project_id: int | None = None) -> dict[str, dict]:
    """Per AI of the user (a further AI by its place, "custom-3"): tokens in and out today, in the last 7 days, in all
    (all projects) and, when `project_id` is given, in that project (Janis, 23.11.2026). Only the user's own calls."""
    now = int(now if now is not None else time.time())
    today, week = now - now % DAY, now - 7 * DAY
    out: dict[str, dict] = {}
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT CASE WHEN provider = 'custom' AND model LIKE 'own-%' THEN 'custom-' || substr(model, 5) ELSE provider"
            " END AS ai, SUM(CASE WHEN created_at >= ? THEN tokens_in + tokens_out ELSE 0 END) AS today,"
            " SUM(CASE WHEN created_at >= ? THEN tokens_in + tokens_out ELSE 0 END) AS week,"
            " SUM(tokens_in + tokens_out) AS total,"
            " SUM(CASE WHEN project_id = ? THEN tokens_in + tokens_out ELSE 0 END) AS project"
            " FROM ai_usage WHERE user_id = ? GROUP BY ai",
            (today, week, -1 if project_id is None else int(project_id), user_id)).fetchall()
    for row in rows:
        if not row["total"]:
            continue
        item = {"today": row["today"] or 0, "week": row["week"] or 0, "total": row["total"] or 0}
        if project_id is not None:
            item["project"] = row["project"] or 0
        out[row["ai"]] = item
    return out


AI_SQL = ("CASE WHEN provider = 'custom' AND model LIKE 'own-%' THEN 'custom-' || substr(model, 5) ELSE provider END")


def detail(user_id: int, now: int | None = None, project_id: int | None = None) -> dict[str, dict]:
    """What the usage window shows (Janis, 23.11.2026), per AI of the user: the numbers of `by_ai` plus, for the scope of
    the page, "scope" (the tokens of this project when `project_id` is given, else of all), "days" (the last 7 days,
    the oldest first, today last), and the split of the scope by "roles", "models", "ways" (plan or API key) and, on a
    page without a project, "projects" ({name: tokens}, the biggest first, at most five). Only the user's own calls;
    a project that is not his has no calls of his: all zero. Nothing is estimated."""
    now = int(now if now is not None else time.time())
    today = now - now % DAY
    first = today - 6 * DAY
    out = by_ai(user_id, now, project_id)
    for item in out.values():
        item.update(scope=item["project"] if project_id is not None else item["total"], days=[0] * 7, roles={},
                    models={}, ways={}, projects={})
    where, args = "user_id = ?", [user_id]
    if project_id is not None:
        where += " AND project_id = ?"
        args.append(int(project_id))
    with db.connect() as conn:
        for row in conn.execute(f"SELECT {AI_SQL} AS ai, (created_at - ?) / ? AS day, SUM(tokens_in + tokens_out) AS n"
                                f" FROM ai_usage WHERE {where} AND created_at >= ? GROUP BY ai, day",
                                (first, DAY, *args, first)).fetchall():
            if row["ai"] in out and 0 <= row["day"] < 7:
                out[row["ai"]]["days"][row["day"]] = row["n"] or 0
        for key, column in (("roles", "role"), ("models", "model"), ("ways", "credential")):
            for row in conn.execute(f"SELECT {AI_SQL} AS ai, {column} AS k, SUM(tokens_in + tokens_out) AS n FROM ai_usage"
                                    f" WHERE {where} GROUP BY ai, k", args).fetchall():
                if row["ai"] in out and row["n"]:
                    out[row["ai"]][key][row["k"] or ""] = row["n"]
        if project_id is None:
            ai_u = AI_SQL.replace("provider", "u.provider").replace("model", "u.model")   # both tables have columns of that name
            for row in conn.execute(f"SELECT {ai_u} AS ai, COALESCE(p.name, '') AS name, SUM(u.tokens_in + u.tokens_out) AS n"
                                    " FROM ai_usage u LEFT JOIN projects p ON p.id = u.project_id AND p.user_id = u.user_id"
                                    " WHERE u.user_id = ? GROUP BY ai, name ORDER BY n DESC", (user_id,)).fetchall():
                if row["ai"] in out and row["n"] and len(out[row["ai"]]["projects"]) < 5:
                    out[row["ai"]]["projects"][row["name"]] = row["n"]
    return out
