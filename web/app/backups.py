"""The backup of the whole hub (27.11.2026): the recovery key, the nightly hour, the list of backups, and putting one back.

Making and opening a backup is a host job (hostjobs.py, runner/hubctl.py has the file format). Here:
- The recovery key is an age key pair made by the hub; the owner keeps the secret half (shown once, as text and as a file
  in the format `age -i` reads). The server keeps only the public half, so a stolen backup is useless without the key.
  A new key replaces the old one; older backups still need the old key.
- The backups lie in a folder the web service only reads (`/backups`, compose.yml); downloading one needs the owner's
  password (a short-lived token, `issue_download`).
- Putting one back: the file comes in pieces into `<data>/restore/` (`receive`), hubctl checks it with the key and
  leaves a summary (`summary`), the page shows it, the owner confirms, hubctl puts it in place (`restore_result`).
Standard library plus pyrage (already in the web image, vault.py).
"""
import datetime
import hashlib
import json
import os
import re
import secrets
import shutil
import time
from pathlib import Path

from . import db, serversettings

NAME = re.compile(r"agent-hub-backup-(\d{4}-\d{2}-\d{2})-(\d{2})(\d{2})\.zip\.age")
DOWNLOAD_SECONDS = 60
_downloads: dict[str, tuple[float, str]] = {}   # sha256(token) -> (valid until, file name); one process (uvicorn)


def _setting(key: str) -> str:
    with db.connect() as conn:
        row = conn.execute("SELECT value FROM server_settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else ""


def _set(conn, key: str, value: str) -> None:
    conn.execute("INSERT INTO server_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, value))


# --- the recovery key ----------------------------------------------------------------------------------------------
def recipient() -> str:
    """The public half of the recovery key, or "" while there is none (then no backup is made)."""
    return _setting("backup.recipient")


def key_made_at() -> int:
    value = _setting("backup.key_at")
    return int(value) if value.isdigit() else 0


def new_key(now: float | None = None) -> str:
    """Make a new recovery key, keep its public half, and return the secret half as the text of a key file (comments
    plus the one line `AGE-SECRET-KEY-1...`). It is not kept anywhere on the server."""
    import pyrage
    secret = pyrage.x25519.Identity.generate()
    public = str(secret.to_public())
    now = int(time.time() if now is None else now)
    with db.connect() as conn:
        _set(conn, "backup.recipient", public)
        _set(conn, "backup.key_at", str(now))
    made = datetime.datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M")
    return (f"# Agent-Hub recovery key, made {made}\n# Keep it safe: without it no backup can be opened.\n"
            f"# public key: {public}\n{secret}\n")


def key_line(text: str) -> str:
    """The secret line of a pasted key or key file; "" when there is none that age accepts."""
    import pyrage
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("AGE-SECRET-KEY-1"):
            try:
                pyrage.x25519.Identity.from_str(line)
            except Exception:
                return ""
            return line
    return ""


# --- the nightly backup --------------------------------------------------------------------------------------------
def hour() -> int:
    return serversettings.get("backup_hour")


def due(now: float) -> str:
    """The public key when the nightly backup should be made now (a key exists, its hour has come, not made today),
    else "". Local time of the server (compose.yml gives the containers the host's clock zone)."""
    public = recipient()
    if not public:
        return ""
    local = time.localtime(now)
    today = time.strftime("%Y-%m-%d", local)
    return public if local.tm_hour >= hour() and _setting("backup.nightly") != today else ""


def mark_nightly(now: float) -> None:
    with db.connect() as conn:
        _set(conn, "backup.nightly", time.strftime("%Y-%m-%d", time.localtime(now)))


# --- the backups there are -----------------------------------------------------------------------------------------
def folder() -> Path:
    return Path(os.environ.get("HUB_BACKUP_DIR", "/backups"))


def listing() -> list[dict]:
    """The backups in the folder, newest first: {"name", "size", "date" (YYYY-MM-DD), "time" (HH:MM)}."""
    found = []
    try:
        entries = list(folder().iterdir())
    except OSError:
        return []
    for path in entries:
        match = NAME.fullmatch(path.name)
        if match and path.is_file():
            try:
                size = path.stat().st_size
            except OSError:
                continue
            found.append({"name": path.name, "size": size, "date": match.group(1),
                          "time": f"{match.group(2)}:{match.group(3)}"})
    return sorted(found, key=lambda item: item["name"], reverse=True)


def issue_download(name: str, now: float | None = None) -> str | None:
    """A one-time token to download backup `name` within DOWNLOAD_SECONDS, or None if there is no such backup."""
    if not any(item["name"] == name for item in listing()):
        return None
    now = time.time() if now is None else now
    for key in [k for k, (until, _) in _downloads.items() if until < now]:
        _downloads.pop(key, None)
    token = secrets.token_urlsafe(32)
    _downloads[hashlib.sha256(token.encode()).hexdigest()] = (now + DOWNLOAD_SECONDS, name)
    return token


def redeem_download(token: str, now: float | None = None) -> Path | None:
    """The file of a download token (once), or None."""
    entry = _downloads.pop(hashlib.sha256((token or "").encode()).hexdigest(), None)
    now = time.time() if now is None else now
    if entry is None or entry[0] < now:
        return None
    path = folder() / entry[1]
    return path if NAME.fullmatch(entry[1]) and path.is_file() else None


# --- putting a backup back -----------------------------------------------------------------------------------------
def restore_dir() -> Path:
    return Path(db.DB_PATH).parent / "restore"


def receive(offset: int, piece: bytes, total: int) -> str:
    """Take the next piece of an uploaded backup. "more" (send the next), "done" (complete), or ValueError: "offset"
    (the pieces got out of order: start again), "size" (no room on the disk), "big" (more than said)."""
    folder = restore_dir()
    folder.mkdir(parents=True, exist_ok=True)
    part = folder / "upload.part"
    if offset == 0:
        part.unlink(missing_ok=True)
        (folder / "upload.age").unlink(missing_ok=True)
        (folder / "summary.json").unlink(missing_ok=True)
        # Room for the file, the opened ZIP and the unpacked files, and some to spare.
        if total <= 0 or shutil.disk_usage(folder).free < 3 * total + 512 * 1024 * 1024:
            raise ValueError("size")
    have = part.stat().st_size if part.exists() else 0
    if offset != have:
        raise ValueError("offset")
    if have + len(piece) > total:
        raise ValueError("big")
    with open(part, "ab") as out:
        out.write(piece)
    if have + len(piece) == total:
        os.replace(part, folder / "upload.age")
        return "done"
    return "more"


def received() -> int:
    """How many bytes of an upload the server has (the page goes on from there after a lost answer)."""
    part = restore_dir() / "upload.part"
    return part.stat().st_size if part.exists() else 0


def uploaded() -> bool:
    return (restore_dir() / "upload.age").is_file()


def summary() -> dict | None:
    """What hubctl found in a checked backup (date, owner, counts, size, schema), or None."""
    try:
        return json.loads((restore_dir() / "summary.json").read_text())
    except (OSError, ValueError):
        return None


def newer_than_us(found: dict) -> bool:
    """True when the backup has a table or column this hub does not know: it comes from a newer version and would
    lose data here. An older backup is fine (db.py adds what is missing on the first start)."""
    with db.connect() as conn:
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        ours = {t: {row[1] for row in conn.execute(f'PRAGMA table_info("{t}")')} for t in tables}
    for table, columns in (found.get("schema") or {}).items():
        if table not in ours or not set(columns) <= ours[table]:
            return True
    return False


def forget_restore() -> None:
    """Drop an upload and its summary (the owner cancelled)."""
    for name in ("upload.part", "upload.age", "summary.json"):
        (restore_dir() / name).unlink(missing_ok=True)


def restore_result() -> dict | None:
    """How putting a backup back ended (hubctl writes it into the data it put back), or None."""
    from . import hostjobs
    try:
        return json.loads((hostjobs.results_dir() / "restore.json").read_text())
    except (OSError, ValueError):
        return None


def clear_restore_result() -> None:
    from . import hostjobs
    (hostjobs.results_dir() / "restore.json").unlink(missing_ok=True)
