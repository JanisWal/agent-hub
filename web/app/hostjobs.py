"""Jobs on the server itself (27.11.2026): backup, checking and putting back a backup, settings in .env.

The web service may not touch the host. A job is written down here; the runner fetches it once (`claim_next`) and
starts a container of runner/hubctl.py that does it. That container answers with a file `<data>/jobs/<id>.json`
(`collect` reads it into the table), because while it works it may restart the web service and the runner. Only one
job at a time. The payload may hold a key (a recovery key, a tunnel token): it is cleared the moment the runner takes it.
The nightly backup is a job like any other: `claim_next` makes it when its hour has come (`backups.due`).
"""
import json
import time
from pathlib import Path

from . import db

ACTIONS = ("backup", "restore-check", "restore-apply", "settings", "restart", "stop")
FRESH_SECONDS = 600   # a job nobody fetched within this long is void (the runner was away)
TIMEOUT = {"backup": 3 * 3600, "restore-check": 3600, "restore-apply": 1800, "settings": 600, "restart": 600, "stop": 600}


def results_dir() -> Path:
    return Path(db.DB_PATH).parent / "jobs"


def request(action: str, payload: dict | None = None, user_id: int | None = None, auto: bool = False,
            now: int | None = None) -> int | None:
    """Write a job down; its id, or None when another job is still waiting or running. ValueError for an unknown action.
    Who may ask is checked by the route."""
    if action not in ACTIONS:
        raise ValueError("unknown action")
    now = int(time.time() if now is None else now)
    with db.connect() as conn:
        if _open(conn, now):
            return None
        cur = conn.execute("INSERT INTO host_jobs (action, payload, requested_by, auto, created_at) VALUES (?, ?, ?, ?, ?)",
                           (action, json.dumps(payload or {}), user_id, 1 if auto else 0, now))
        return cur.lastrowid


def _open(conn, now: int):
    """The job that is waiting or running, if any (old ones that never ended count as failed)."""
    collect(conn)
    for row in conn.execute("SELECT id, action, created_at, taken_at FROM host_jobs WHERE result IS NULL").fetchall():
        if row["taken_at"] is None and now - row["created_at"] > FRESH_SECONDS:
            _end(conn, row["id"], False, {"reason": "not_taken"})
        elif row["taken_at"] is not None and now - row["taken_at"] > TIMEOUT[row["action"]]:
            _end(conn, row["id"], False, {"reason": "timeout"})
        else:
            return row
    return None


def busy(now: int | None = None) -> bool:
    with db.connect() as conn:
        return _open(conn, int(time.time() if now is None else now)) is not None


def _end(conn, job_id: int, success: bool, detail: dict) -> None:
    conn.execute("PRAGMA secure_delete = ON")
    conn.execute("UPDATE host_jobs SET result = ?, detail = ?, payload = '{}' WHERE id = ? AND result IS NULL",
                 ("ok" if success else "failed", json.dumps(detail), job_id))


def claim_next(now: int | None = None) -> dict | None:
    """{"id", "action", "payload"} for the runner, once; the payload is cleared in the same step. The nightly backup is
    made here when it is due."""
    from . import backups
    now = int(time.time() if now is None else now)
    recipient = backups.due(now)
    if recipient:
        if request("backup", {"recipient": recipient}, auto=True, now=now) is not None:
            backups.mark_nightly(now)
    with db.connect() as conn:
        row = _open(conn, now)
        if row is None or row["taken_at"] is not None:
            return None
        # The payload may hold a key: secure_delete makes SQLite overwrite the old text on disk instead of leaving it in
        # a free page of the database file (27.11.2026).
        conn.execute("PRAGMA secure_delete = ON")
        payload = conn.execute("SELECT payload FROM host_jobs WHERE id = ?", (row["id"],)).fetchone()[0]
        taken = conn.execute("UPDATE host_jobs SET taken_at = ?, payload = '{}' WHERE id = ? AND taken_at IS NULL",
                             (now, row["id"]))
        if taken.rowcount != 1:
            return None
    return {"id": row["id"], "action": row["action"], "payload": json.loads(payload or "{}")}


def failed_to_start(job_id: int) -> bool:
    """The runner could not start the container."""
    with db.connect() as conn:
        found = conn.execute("SELECT 1 FROM host_jobs WHERE id = ? AND taken_at IS NOT NULL AND result IS NULL",
                             (job_id,)).fetchone()
        if found:
            _end(conn, job_id, False, {"reason": "not_started"})
        return found is not None


def collect(conn=None) -> None:
    """Read the answers hubctl left (`jobs/<id>.json`) into the table and delete the files."""
    folder = results_dir()
    if not folder.is_dir():
        return
    if conn is None:
        with db.connect() as own:
            return collect(own)
    for path in folder.glob("[0-9]*.json"):
        try:
            answer = json.loads(path.read_text())
            job_id = int(path.stem)
        except (OSError, ValueError):
            continue
        detail = {k: v for k, v in answer.items() if k != "ok" and isinstance(v, (str, int, float, bool, list))}
        _end(conn, job_id, bool(answer.get("ok")), detail)
        path.unlink(missing_ok=True)


def state(job_id: int | None = None, action: str | None = None, now: int | None = None) -> dict:
    """{"id", "state" (none, waiting, running, ok, failed), "detail", "auto", "at"} of one job, or of the newest of an
    action."""
    now = int(time.time() if now is None else now)
    with db.connect() as conn:
        _open(conn, now)
        if job_id is not None:
            row = conn.execute("SELECT * FROM host_jobs WHERE id = ?", (job_id,)).fetchone()
        else:
            row = conn.execute("SELECT * FROM host_jobs WHERE action = ? ORDER BY id DESC LIMIT 1", (action,)).fetchone()
    if row is None:
        return {"id": None, "state": "none", "detail": {}, "auto": False, "at": 0}
    current = row["result"] or ("running" if row["taken_at"] else "waiting")
    return {"id": row["id"], "state": current, "detail": json.loads(row["detail"] or "{}"), "auto": bool(row["auto"]),
            "at": row["created_at"]}


def end_open(action: str, reason: str) -> None:
    """End a job of `action` that can not answer any more (a put-back backup that went back to the state before)."""
    with db.connect() as conn:
        for row in conn.execute("SELECT id FROM host_jobs WHERE action = ? AND result IS NULL", (action,)).fetchall():
            _end(conn, row["id"], False, {"reason": reason})
