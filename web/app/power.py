"""Actions on the Pi itself: restart and shut down. Only the owner or a superadmin may ask; the runner does it.

The web container cannot touch the host. So the owner's request is only written down here; the runner (which
already holds the Docker socket) fetches it once through /runner/power/claim and runs a fixed command
(runner/launcher.py `build_power_command`). A request nobody fetched within `FRESH_SECONDS` is dropped: it must
not fire hours later, when the runner comes back. The backup is a host job since 27.11.2026 (hostjobs.py).
"""
import time

from . import db
from .users import User

ACTIONS = ("poweroff",)   # "reboot" restarts only the hub's containers since 27.11.2026 (hostjobs "restart")
FRESH_SECONDS = 120


def request_action(user: User, action: str) -> bool:
    """Write down a request. False if one is already waiting. PermissionError unless `user` is the
    owner or a superadmin, ValueError for an unknown action."""
    if not user.is_system_admin:
        raise PermissionError("only the owner or a superadmin may restart or shut down")
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
