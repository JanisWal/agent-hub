"""Addresses in the server's network that further AIs may use (Janis, 21.11.2026). Standard library only.

A further AI (ai_link.py) may sit anywhere on the internet without anybody's approval. An address in the server's own
network (a local Ollama, an AI server in the office) opens that network to the AI's requests, so it needs an entry
here: host and port exactly, for all accounts or for one. Only the owner keeps the list (routes/system.py); it is not
tied to a project or a device. Plain http is allowed for a listed address (local AIs rarely have a certificate).

What counts: the job's ticket says `lan` only when its address is listed for its user (ai_link.route_in, take_keys);
only then does the gateway (runner/egress.py, port 3132) connect to a home address, and only to that host. Removing an
entry holds from the next job on. Without an entry, an address in the network is refused when it is saved (`local`)
and, for a name that resolves into the network, by the gateway.
"""
import ipaddress
import re
import sqlite3
import time

from . import db

MAX_ENTRIES = 50
MAX_NOTE = 60
_HOST = r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?"
ADDRESS = re.compile(rf"({_HOST}):([0-9]{{1,5}})")
_ENDPOINT = re.compile(rf"(https?)://({_HOST})(?::([0-9]{{1,5}}))?(?:/.*)?")
# What the gateway takes for an address in the server's network (= runner/egress.HOME_NETS) and names that only a
# local network resolves.
_NETS = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "192.168.0.0/16", "100.64.0.0/10", "172.16.0.0/12",
                                                "127.0.0.0/8", "169.254.0.0/16"))
# Never listed: the server itself and Docker's networks (the gateway never connects there either).
_NEVER = tuple(ipaddress.ip_network(n) for n in ("127.0.0.0/8", "172.16.0.0/12", "169.254.0.0/16", "0.0.0.0/8"))
_LOCAL_NAMES = (".local", ".lan", ".home", ".internal", ".intranet", ".fritz.box", ".localhost")


def _ip(host: str):
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def parse(text: str) -> tuple[str, int]:
    """("192.168.1.20", 11434) from "192.168.1.20:11434"; ValueError("address") for anything else (the port is
    needed: an entry opens one service, not a whole machine)."""
    match = ADDRESS.fullmatch((text or "").strip().lower())
    if not match or not 1 <= int(match.group(2)) <= 65535 or match.group(1) == "localhost":
        raise ValueError("address")
    if _ip(match.group(1)) is not None and any(_ip(match.group(1)) in net for net in _NEVER):
        raise ValueError("address")   # the server itself or Docker's networks
    return match.group(1), int(match.group(2))


def host_port(endpoint: str) -> tuple[str, int] | None:
    """Host and port of an API address ("http://pc:8080/v1" -> ("pc", 8080); no port: 80 or 443)."""
    match = _ENDPOINT.fullmatch((endpoint or "").strip().lower())
    if not match:
        return None
    port = int(match.group(3)) if match.group(3) else (443 if match.group(1) == "https" else 80)
    return match.group(2), port


def local(host: str) -> bool:
    """Is this host in the server's network as far as the name shows (an address of _NETS, a name without a dot or a
    local ending)? A public name that resolves into the network is caught by the gateway."""
    ip = _ip(host)
    if ip is not None:
        return any(ip in net for net in _NETS)
    return "." not in host or host.endswith(_LOCAL_NAMES)


def entries(conn: sqlite3.Connection) -> list[dict]:
    """The list for the owner's page: {id, host, port, user_id, email, note}, oldest first."""
    rows = conn.execute("SELECT a.*, u.email FROM net_addresses a LEFT JOIN users u ON u.id = a.user_id"
                        " ORDER BY a.id").fetchall()
    return [{"id": r["id"], "host": r["host"], "port": r["port"], "user_id": r["user_id"], "email": r["email"] or "",
             "note": r["note"]} for r in rows]


def add(address: str, user_id: int | None, note: str = "", now: int | None = None) -> int:
    """List an address for one account or all (None). ValueError("address"), ("user") for an account that is not
    there, ("full") over MAX_ENTRIES. The same address for the same account twice is kept once."""
    host, port = parse(address)
    note = " ".join((note or "").split())[:MAX_NOTE]
    with db.connect() as conn:
        if user_id is not None and conn.execute("SELECT 1 FROM users WHERE id = ? AND deleted_at IS NULL",
                                                (user_id,)).fetchone() is None:
            raise ValueError("user")
        same = conn.execute("SELECT id FROM net_addresses WHERE host = ? AND port = ? AND user_id IS ?",
                            (host, port, user_id)).fetchone()
        if same:
            conn.execute("UPDATE net_addresses SET note = ? WHERE id = ?", (note, same["id"]))
            return same["id"]
        if conn.execute("SELECT COUNT(*) FROM net_addresses").fetchone()[0] >= MAX_ENTRIES:
            raise ValueError("full")
        return conn.execute("INSERT INTO net_addresses (host, port, user_id, note, created_at) VALUES (?, ?, ?, ?, ?)",
                            (host, port, user_id, note, int(now if now is not None else time.time()))).lastrowid


def remove(entry_id: int) -> bool:
    with db.connect() as conn:
        return conn.execute("DELETE FROM net_addresses WHERE id = ?", (entry_id,)).rowcount == 1


def allows(conn: sqlite3.Connection, user_id: int, endpoint: str) -> bool:
    """May this user's further AI use this address in the server's network (listed for him or for all)?"""
    found = host_port(endpoint)
    if found is None:
        return False
    return conn.execute("SELECT 1 FROM net_addresses WHERE host = ? AND port = ? AND (user_id IS NULL OR user_id = ?)",
                        (found[0], found[1], user_id)).fetchone() is not None
