"""Whether an AI's own tools are really there, measured on its normal answers (Janis, 21.11.2026). Standard library only.

The catalog says what an AI's program brings (catalog.tools_of: "own", "hub", "none"). Should that be wrong, the hub's
own tool (runner/hub_tools.py) steps in, but only on clear evidence, never because of a fault of ours:
- The program itself names its tools at the start of an answer (Claude Code: its "init" event); the runner passes that
  list on with the tools it asked for (`record`). No extra request, no tokens.
- A tool counts as missing only when the program's list is readable, the tool was asked for and is not in it, STREAK
  times in a row. Only then that one tool comes from the hub (`effective`). An unreadable list (None) changes nothing.
- As soon as the program names the tool again, it is its own again.
- A tool that fails while it runs is no evidence (it may be our container): that is never recorded here.
Every switch is logged with date and reason (table tool_health, `history` for the administration).
"""
import sqlite3
import time

from . import catalog, db

STREAK = 3
# The program's own tool names per AI and the kind of tool each one is (catalog.TOOLS). An AI missing here (its program
# does not name its tools) is never switched.
PROGRAM_TOOLS = {
    "claude": {"Read": ("read", "look"), "Glob": ("read",), "Grep": ("read",), "Write": ("write",), "Edit": ("write",),
               "Bash": ("shell",), "WebSearch": ("search",), "WebFetch": ("fetch",)},
}
# What the hub hands for a kind of tool (hub_tools.TOOLS); no web search of its own.
HUB_TOOLS = {"read": ("list_files", "read_file", "grep"), "write": ("write_file", "edit_file"), "shell": ("run",),
             "fetch": ("fetch",), "look": ("look",)}


def _kinds(provider: str, names) -> set[str]:
    mapping = PROGRAM_TOOLS.get(provider, {})
    return {kind for name in names for kind in mapping.get(name, ())}


def record(provider: str, asked: list[str], seen: list[str] | None, now: int | None = None) -> None:
    """One answer: the tools the hub asked the program for and those it named (None: its list could not be read)."""
    if seen is None or provider not in PROGRAM_TOOLS:
        return
    now = int(now if now is not None else time.time())
    asked_kinds, seen_kinds = _kinds(provider, asked), _kinds(provider, seen)
    with db.connect() as conn:
        for kind in asked_kinds:
            row = conn.execute("SELECT missing FROM tool_health WHERE provider = ? AND tool = ?",
                               (provider, kind)).fetchone()
            missing = 0 if kind in seen_kinds else (row["missing"] if row else 0) + 1
            if row is None and missing == 0:
                continue
            note = "" if missing == 0 else f"not named by the program in {missing} answer(s) in a row"
            conn.execute("INSERT INTO tool_health (provider, tool, missing, note, updated_at) VALUES (?, ?, ?, ?, ?)"
                         " ON CONFLICT(provider, tool) DO UPDATE SET missing = excluded.missing, note = excluded.note,"
                         " updated_at = excluded.updated_at", (provider, kind, missing, note, now))


def _missing(conn: sqlite3.Connection, provider: str) -> set[str]:
    return {r["tool"] for r in conn.execute("SELECT tool FROM tool_health WHERE provider = ? AND missing >= ?",
                                            (provider, STREAK))}


def effective(provider: str) -> dict[str, str]:
    """The tools of an AI as they are: the catalog's, an own tool proven missing from the hub (or none without one)."""
    tools = catalog.tools_of(provider)
    with db.connect() as conn:
        missing = _missing(conn, provider)
    return {t: ("hub" if t in HUB_TOOLS else "none") if s == "own" and t in missing else s for t, s in tools.items()}


def hub_tools(provider: str) -> list[str]:
    """The hub's tools a job of this AI gets (hub_tools.py names), from `effective`."""
    names = [name for kind, source in effective(provider).items() if source == "hub" for name in HUB_TOOLS.get(kind, ())]
    return list(dict.fromkeys(names))


def history(provider: str | None = None) -> list[dict]:
    """The recorded state, newest first: provider, tool, missing in a row, note, when."""
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM tool_health" + (" WHERE provider = ?" if provider else "") +
                            " ORDER BY updated_at DESC", (provider,) if provider else ()).fetchall()
    return [dict(r) for r in rows]
