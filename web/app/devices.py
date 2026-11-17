"""Devices of a project (Manager view, Janis 07.11.2026): the machines the project works on, each with a name, a
hostname, a description and optionally a key.

The key (an SSH private key, a password or a token) is encrypted at once (vault.py) and never given out again: the
page only learns that one is stored (`has_key`); the user can replace or remove it. No AI and no page ever reads it;
only the broker that later connects to a device will (vault.unseal). Hardware at the vehicle is not switched by the AIs
at all (CLAUDE.md), so this list is about reaching a device, not about the permissions: allowed commands, the host key
and the approval come with the broker.

Like every data module, each function gets the `user_id` and the project must be his: foreign things are "not found"
(None or False). Errors in input are a ValueError whose text is a code: name, hostname, description, key, duplicate,
limit, vault. Standard library only (plus vault.py).
"""
import re
import sqlite3
import time
from dataclasses import dataclass

from . import db, vault

MAX_NAME = 60
MAX_HOSTNAME = 253
MAX_DESCRIPTION = 500
MAX_KEY = 8000
MAX_PER_PROJECT = 50
_HOST = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?")   # a name or an IPv4 address; no scheme, port or path


@dataclass
class Device:
    id: int
    project_id: int
    name: str
    hostname: str
    description: str
    has_key: bool
    created_at: int


def _to_device(row: sqlite3.Row) -> Device:
    return Device(row["id"], row["project_id"], row["name"], row["hostname"], row["description"],
                  bool(row["key_enc"]), row["created_at"])


def _clean(name: str, hostname: str, description: str) -> tuple[str, str, str]:
    name, hostname, description = name.strip(), hostname.strip().lower(), description.strip()
    if not name or len(name) > MAX_NAME:
        raise ValueError("name")
    if len(hostname) > MAX_HOSTNAME or not _HOST.fullmatch(hostname):
        raise ValueError("hostname")
    if len(description) > MAX_DESCRIPTION:
        raise ValueError("description")
    return name, hostname, description


def _sealed(key: str) -> str:
    """The key as it is stored. SSH keys need their last line break, so the text is only normalised."""
    key = key.replace("\r\n", "\n").replace("\r", "\n").strip("\n ")
    if not key or len(key) > MAX_KEY or "\x00" in key:
        raise ValueError("key")
    try:
        return vault.seal(key + "\n")
    except vault.VaultError:
        raise ValueError("vault") from None


def _owned(conn: sqlite3.Connection, user_id: int, device_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT d.* FROM devices d JOIN projects p ON p.id = d.project_id WHERE d.id = ? AND p.user_id = ?",
        (device_id, user_id)).fetchone()


def _taken(conn: sqlite3.Connection, project_id: int, name: str, except_id: int = 0) -> bool:
    return conn.execute("SELECT 1 FROM devices WHERE project_id = ? AND lower(name) = lower(?) AND id != ?",
                        (project_id, name, except_id)).fetchone() is not None


def list_devices(user_id: int, project_id: int) -> list[Device]:
    """The devices of a project in the order they were made; empty for a foreign project."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT d.* FROM devices d JOIN projects p ON p.id = d.project_id"
            " WHERE d.project_id = ? AND p.user_id = ? ORDER BY d.id", (project_id, user_id)).fetchall()
    return [_to_device(r) for r in rows]


def create(user_id: int, project_id: int, name: str, hostname: str, description: str = "", key: str = "",
           now: int | None = None) -> Device | None:
    """Add a device; None for a foreign project. ValueError(code) for bad input, a name that is already used in the
    project, a full list, or a key that cannot be stored encrypted (no master key)."""
    name, hostname, description = _clean(name, hostname, description)
    sealed = _sealed(key) if key.strip() else ""
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id)).fetchone() is None:
            return None
        if _taken(conn, project_id, name):
            raise ValueError("duplicate")
        if conn.execute("SELECT COUNT(*) FROM devices WHERE project_id = ?", (project_id,)).fetchone()[0] >= MAX_PER_PROJECT:
            raise ValueError("limit")
        cur = conn.execute(
            "INSERT INTO devices (project_id, name, hostname, description, key_enc, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, name, hostname, description, sealed, int(now if now is not None else time.time())))
        row = conn.execute("SELECT * FROM devices WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _to_device(row)


def update(user_id: int, device_id: int, name: str, hostname: str, description: str = "", key: str = "",
           remove_key: bool = False) -> int | None:
    """Change a device; its project id, or None if it is not the user's. An empty `key` keeps the stored one, a new
    one replaces it, `remove_key` deletes it. Errors as in `create`."""
    name, hostname, description = _clean(name, hostname, description)
    sealed = _sealed(key) if key.strip() and not remove_key else None
    with db.connect() as conn:
        row = _owned(conn, user_id, device_id)
        if row is None:
            return None
        if _taken(conn, row["project_id"], name, device_id):
            raise ValueError("duplicate")
        conn.execute("UPDATE devices SET name = ?, hostname = ?, description = ? WHERE id = ?",
                     (name, hostname, description, device_id))
        if remove_key:
            conn.execute("UPDATE devices SET key_enc = '' WHERE id = ?", (device_id,))
        elif sealed is not None:
            conn.execute("UPDATE devices SET key_enc = ? WHERE id = ?", (sealed, device_id))
    return row["project_id"]


def delete(user_id: int, device_id: int) -> bool:
    with db.connect() as conn:
        if _owned(conn, user_id, device_id) is None:
            return False
        conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
    return True
