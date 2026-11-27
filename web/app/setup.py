"""The set-up assistant of a new hub (27.11.2026, PROJEKT.md Merkliste 3s).

Before there is an owner, `/setup` is open to anybody who reaches the server in the home network (Janis, 27.11.2026:
no set-up code; whoever is in the network could claim it, but only for a short time). Three limits keep that window
small: it closes for good as soon as an owner exists, it is never open through the tunnel (a request that carries
`CF-Connecting-IP` came from the internet), and it is open only for WINDOW_SECONDS after the hub started (a restart of
the server opens it again). After the owner is made, the rest of the assistant is the owner's (logged in): reaching the
hub from outside, mail, backup, connecting an AI. Every optional step can be skipped; the owner can open it again later
from the administration (`/setup?step=...`).
"""
import os
import time
import urllib.request

from . import db, sysstats, users

WINDOW_SECONDS = 3600
STARTED = time.time()
# The steps in their order. Before the owner exists only the first ones; "restore" is the other way to an owner.
STEPS = ("check", "account", "access", "mail", "backup", "ai", "done")
OWNER_STEPS = ("access", "mail", "backup", "ai", "done")
MIN_MEMORY_MB = 850      # a Raspberry Pi 4 with 1 GB reports about 905 MB
MIN_DISK_GB = 6


def via_tunnel(request) -> bool:
    return bool(request.headers.get("cf-connecting-ip"))


def open_for(request, now: float | None = None) -> bool:
    """May this visitor use the set-up before there is an owner? Never through the tunnel, only while there is no owner
    and only for WINDOW_SECONDS after the start. Also from a public address (Janis, 28.11.2026: a server with its own
    IPv4 is set up from outside for now; limiting it to private networks is noted for later, PROJEKT.md Merkliste 3v)."""
    now = time.time() if now is None else now
    return not via_tunnel(request) and not users.owner_exists() and now - STARTED < WINDOW_SECONDS


def minutes_left(now: float | None = None) -> int:
    now = time.time() if now is None else now
    return max(0, int((WINDOW_SECONDS - (now - STARTED)) // 60))


def is_done() -> bool:
    with db.connect() as conn:
        return conn.execute("SELECT 1 FROM server_settings WHERE key = 'setup.done'").fetchone() is not None


def finish() -> None:
    with db.connect() as conn:
        conn.execute("INSERT OR IGNORE INTO server_settings (key, value) VALUES ('setup.done', '1')")


def storage(mountinfo: str | None = None, path: str = "/data") -> str:
    """What the data lies on: "card" (a memory card), "disk", or "" when unknown (from /proc/self/mountinfo)."""
    if mountinfo is None:
        try:
            with open("/proc/self/mountinfo", encoding="utf-8") as handle:
                mountinfo = handle.read()
        except OSError:
            return ""
    for line in mountinfo.splitlines():
        fields = line.split()
        if len(fields) > 4 and fields[4] == path and " - " in line:
            source = line.split(" - ", 1)[1].split()
            device = source[1] if len(source) > 1 else ""
            return "card" if "mmcblk" in device else ("disk" if device.startswith("/dev/") else "")
    return ""


def checks(runner_seen: float, now: float | None = None) -> list[dict]:
    """What the first page shows: [{"key", "state" (ok, warn, bad), "value"}]. Memory and free space against the
    least a hub needs, the kind of disk (a memory card wears out, a disk is better), and whether the runner answers."""
    now = time.time() if now is None else now
    stats = sysstats.read()
    mem, disk = stats["memory"], stats["disk"]
    rows = [{"key": "memory", "state": "ok" if mem["total_mb"] >= MIN_MEMORY_MB else "bad", "value": mem["total_mb"]}]
    if disk is not None:
        rows.append({"key": "disk", "state": "ok" if disk["free_gb"] >= MIN_DISK_GB else "bad",
                     "value": round(disk["free_gb"], 1)})
    kind = storage()
    if kind:
        rows.append({"key": "storage", "state": "warn" if kind == "card" else "ok", "value": kind})
    rows.append({"key": "runner", "state": "ok" if now - runner_seen < 30 else "bad", "value": ""})
    return rows


def reachable(base_url: str, timeout: float = 8.0) -> bool:
    """Does the public address lead to this hub (through the tunnel, or the server's address)? Asks `<address>/health`."""
    if not base_url.startswith(("https://", "http://")):
        return False
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/health", timeout=timeout) as answer:
            return answer.status == 200 and b'"ok"' in answer.read(200)
    except Exception:
        return False


def current() -> dict:
    """What is set already, for the steps (never a secret itself, only whether it is there)."""
    return {"base_url": os.environ.get("HUB_BASE_URL", "").strip(), "tunnel": bool(os.environ.get("HUB_TUNNEL_ON")),
            "mail_from": os.environ.get("MAIL_FROM", "").strip(), "mail_key": bool(os.environ.get("RESEND_API_KEY"))}
