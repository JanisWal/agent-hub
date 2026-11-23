"""Why an AI's answer or run failed, in one place for the manager chat and the agent runs (Janis, 21.11.2026: "You've hit
your 5-hour limit" was not seen as a used-up quota, so neither the API key nor the next AI took over). Standard library.

Kinds: "server" (our own fault: a saved credential the server can not read; nothing is deleted), "plan" (the account's
plan does not include the program, e.g. ChatGPT without Codex), "auth" (sign-in lost or key refused), "limit" (quota,
rate or credit used up), "timeout", "steps" (the step limit of the hub's loop), "other".
The patterns come from the programs' real messages (Claude Code, Codex, Mistral Vibe, OpenAI-format APIs); a new
wording gets a line in `LIMIT` or `AUTH` and a case in tests/test_failures.py.
"""
import re

SERVER = re.compile(r"^Server: the saved credential")
PLAN = re.compile(r"\(plan\)")
AUTH = re.compile(r"authenticat|not logged in|/login|oauth token has expired|invalid (x-)?api.?key|incorrect api key"
                  r"|\b401\b|unauthori[sz]ed|token_expired|refresh token|token could not be refreshed"
                  r"|log out and sign in again|auth\.openai\.com/oauth/token", re.I)
LIMIT = re.compile(r"usage.?limit|limit reached|hit your [\w -]{0,24}limit|(5-hour|weekly|daily|monthly) limit"
                   r"|rate.?limit|\b429\b|too many requests|no credit|credit balance|out of (extra )?usage|quota"
                   r"|· ?resets|resets at \d|try again in \d", re.I)
SWITCH = ("auth", "limit", "server", "plan")   # kinds after which the user's next AI takes over
EXHAUSTED = ("auth", "limit")                  # kinds after which the plan gives way to the user's API key


def kind(reason: str) -> str:
    """The kind of a failed answer or run (see the module text)."""
    reason = reason or ""
    if SERVER.search(reason):
        return "server"
    if PLAN.search(reason):
        return "plan"
    if AUTH.search(reason):
        return "auth"
    if LIMIT.search(reason):
        return "limit"
    if reason.lower().startswith("timeout"):
        return "timeout"
    if reason.startswith("Too many steps"):
        return "steps"
    return "other"
