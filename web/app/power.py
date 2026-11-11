"""Actions on the Pi itself: restart, shut down, and a manual backup. Only the owner may ask; the runner does it.

The web container cannot touch the host. So the owner's request is only written down here; the runner (which
already holds the Docker socket) fetches it once through /runner/power/claim and runs a fixed command
(runner/launcher.py `build_power_command`). A request nobody fetched within `FRESH_SECONDS` is dropped: it must
not fire hours later, when the runner comes back. A backup also reports how it ended (`finish`), so the page can
say "done" or "did not work" (`backup_state`).
"""
import time

from . import db
from .users import User

ACTIONS = ("reboot", "poweroff", "backup")
FRESH_SECONDS = 120
BACKUP_SECONDS = 300   # a started backup that has not reported after this long counts as lost


def request_action(user: User, action: str) -> bool:
    """Write down a request. False if one is already waiting. PermissionError unless `user` is the
    owner, ValueError for an unknown action."""
    if user.role != "owner":
        raise PermissionError("only the owner may restart, shut down or back up")
    if action not in ACTIONS:
        raise ValueError("unknown action")
    now = int(time.time())
    with db.connect() as conn:
        waiting = conn.execute(
            "SELECT 1 FROM power_requests WHERE taken_at IS NULL AND created_at > ?", (now - FRESH_SECONDS,)
        ).fetchone()
        if waiting:
            return False
        conn.execute(
            "INSERT INTO power_requests (action, requested_by, created_at) VALUES (?, ?, ?)",
            (action, user.id, now),
        )
    return True


def claim_next() -> tuple[int, str] | None:
    """(id, action) the runner should carry out now, or None. Every request is handed out once."""
    now = int(time.time())
    with db.connect() as conn:
        row = conn.execute(
            "SELECT id, action FROM power_requests WHERE taken_at IS NULL AND created_at > ? ORDER BY id LIMIT 1",
            (now - FRESH_SECONDS,),
        ).fetchone()
        if row is None:
            return None
        taken = conn.execute(
            "UPDATE power_requests SET taken_at = ? WHERE id = ? AND taken_at IS NULL", (now, row["id"])
        )
        return (row["id"], row["action"]) if taken.rowcount == 1 else None


def finish(request_id: int, success: bool) -> bool:
    """The runner reports how a manual backup ended. Only a taken backup without a result can be finished."""
    with db.connect() as conn:
        done = conn.execute(
            "UPDATE power_requests SET result = ? WHERE id = ? AND action = 'backup'"
            " AND taken_at IS NOT NULL AND result IS NULL",
            ("ok" if success else "failed", request_id),
        )
        return done.rowcount == 1


def backup_state(now: int | None = None) -> str:
    """The latest manual backup: "none" (never asked), "running", "ok" or "failed" (also: nobody fetched the
    request, or it never reported)."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        row = conn.execute(
            "SELECT created_at, taken_at, result FROM power_requests WHERE action = 'backup' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return "none"
    if row["result"]:
        return row["result"]
    if row["taken_at"] is None:
        return "running" if now - row["created_at"] <= FRESH_SECONDS else "failed"
    return "running" if now - row["taken_at"] <= BACKUP_SECONDS else "failed"
