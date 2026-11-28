"""Updates from the page (28.11.2026, PROJEKT.md Merkliste 3s).

A hub installed with install.sh knows where its code comes from (HUB_SOURCE, HUB_BRANCH in .env) and which commit it
runs (web/app/VERSION, written by deploy/steps/30-code.sh). This module asks the source for its newest commit (at most
once a day by itself, or when the owner asks) and says whether it is newer. The update itself is a host job (hubctl
`update`): it fetches the code and runs that version's own steps, as update.sh would.

For now every commit on the branch is an update (Janis, 28.11.2026: while the hub is still being built and tested). Later
only released versions count; that decision lives in `latest` alone.
"""
import json
import os
import re
import time
import urllib.request
from pathlib import Path

from . import db

VERSION_FILE = Path(__file__).parent / "VERSION"
CHECK_SECONDS = 24 * 3600
_GITHUB = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_KEY = "update.latest"


def source() -> tuple[str, str]:
    return os.environ.get("HUB_SOURCE", "").strip(), os.environ.get("HUB_BRANCH", "").strip() or "main"


def allowed() -> bool:
    """Can this hub update itself from the page? Only with a source on GitHub (the first hub has none: it is updated
    from its own clone)."""
    return bool(_GITHUB.fullmatch(source()[0]))


def installed() -> dict | None:
    """{"commit", "date"} of the running code, or None (installed without Git)."""
    try:
        commit, date = VERSION_FILE.read_text().split()[:2]
    except (OSError, ValueError):
        return None
    return {"commit": commit, "date": date} if _COMMIT.fullmatch(commit) else None


def _ask(url: str, timeout: float) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "agent-hub"})
    with urllib.request.urlopen(request, timeout=timeout) as answer:
        return json.loads(answer.read(200_000))


def _fetch(ask, timeout: float = 6.0) -> dict | None:
    """The newest commit of the branch, from GitHub's public interface: {"commit", "date"}, or None."""
    found = _GITHUB.fullmatch(source()[0])
    if not found:
        return None
    owner, repo = found.groups()
    try:
        data = ask(f"https://api.github.com/repos/{owner}/{repo}/commits/{source()[1]}", timeout)
        commit, date = str(data["sha"]), str(data["commit"]["committer"]["date"])[:10]
    except Exception:
        return None
    return {"commit": commit, "date": date} if _COMMIT.fullmatch(commit) else None


def latest(force: bool = False, now: float | None = None, ask=None) -> dict | None:
    """{"commit", "date", "checked"} of the newest version, asked at most once a day unless `force`; None when it was
    never found. A failed question keeps what was known and tries again on the next day."""
    if not allowed():
        return None
    now = time.time() if now is None else now
    with db.connect() as conn:
        row = conn.execute("SELECT value FROM server_settings WHERE key = ?", (_KEY,)).fetchone()
    known = json.loads(row["value"]) if row else None
    if known and not force and now - known.get("checked", 0) < CHECK_SECONDS:
        return known if known.get("commit") else None
    fresh = _fetch(ask or _ask)
    stored = {**(fresh or {k: v for k, v in (known or {}).items() if k != "checked"}), "checked": now}
    with db.connect() as conn:
        conn.execute("INSERT INTO server_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     (_KEY, json.dumps(stored)))
    return stored if stored.get("commit") else None


def available(newest: dict | None, current: dict | None) -> bool:
    """Is there something newer than what runs? Without a known own version any found version counts."""
    return bool(newest) and (current is None or newest["commit"] != current["commit"])
