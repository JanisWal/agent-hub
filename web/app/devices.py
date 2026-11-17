"""Devices of a project (Manager view, Janis 07.11.2026; broker 17.11.2026): the machines the project works on.

A device has a name (what it is), a kind (the picture), a hostname or IP, a description, and for the broker: the SSH
user and port, the login (`auth` "key" or "password") with its secret, the trusted host key with the address it was
seen at, the operating system found by the connection test, and what the AI may do on it.

Secrets: the key or password is sealed at once (vault.py, the web service has only the public key) and never given
out again; the page only learns that one is stored. A key made by the hub (`keygen`) shows its public line, the private
part never leaves the broker unsealed. Principle (Janis, 17.11.2026): the key is for the AI, the password for the human:
the AI may trigger only the actions the user ticked (`ai_actions`), never shell, files or logs, and with a password
login only if the user allowed the password for the AI (`ai_password`). Home-network targets need `lan_ok`: the
owner's own devices have it; other users' devices stay outside the home network (Janis, 17.11.2026: no approval page
for now).

Like every data module, each function gets the `user_id` and the project must be his: foreign things are "not found"
(None or False). Errors in input are a ValueError whose text is a code: name, kind, hostname, ip, description, key,
duplicate, limit, vault, user, port, auth. Standard library only (plus vault.py).
"""
import ipaddress
import re
import sqlite3
import time
from dataclasses import dataclass, field

from . import db, device_profiles, vault

MAX_NAME = 60
MAX_HOSTNAME = 253
MAX_DESCRIPTION = 500
MAX_KEY = 8000
MAX_PASSWORD = 256
MAX_PER_PROJECT = 50
MAX_IP = 45
LOG_KEEP = 500             # entries of the hub's log kept per device
AUTHS = ("key", "password")
AI_CHOICES = device_profiles.ACTIONS   # what the user may allow the AI (online is always allowed: no login)
KINDS = ("raspberry_pi", "linux_server", "linux_pc", "windows_server", "windows_pc", "mac", "microcontroller",
         "router", "other")
KIND_ICON = {"raspberry_pi": "dev_pi", "linux_server": "dev_server_linux", "linux_pc": "dev_linux",
             "windows_server": "dev_server_windows", "windows_pc": "dev_pc_windows", "mac": "dev_mac",
             "microcontroller": "dev_chip", "router": "dev_router", "other": "dev_box"}
# Words in the name or description that say what a device is for (Janis, 17.11.2026: "a Raspberry Pi that becomes
# my display"): they win over the kind's picture. German and English, matched at the start of a word.
CONTEXT_ICON = (("display", "dev_display"), ("bildschirm", "dev_display"), ("monitor", "dev_display"),
                ("kamera", "dev_camera"), ("camera", "dev_camera"), ("drucker", "dev_printer"),
                ("printer", "dev_printer"), ("nas", "dev_storage"), ("speicher", "dev_storage"),
                ("storage", "dev_storage"), ("lautsprecher", "dev_speaker"), ("speaker", "dev_speaker"),
                ("sensor", "dev_sensor"), ("licht", "dev_light"), ("lampe", "dev_light"), ("light", "dev_light"))
NAME_ICON = (("server", "dev_server_linux"), ("router", "dev_router"), ("laptop", "dev_mac"), ("notebook", "dev_mac"),
             ("pc", "dev_linux"))   # a device of kind "other" gets its picture from its name if the name says what it is
ICONS = tuple(dict.fromkeys(list(KIND_ICON.values()) + [p for _, p in CONTEXT_ICON]))   # the set the AI chooses from
_MAC = re.compile(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}")
_PICTURE = re.compile(r"data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/]+={0,2}")
MAX_PICTURE = 60_000         # characters of a dropped picture (the browser makes it 96 x 96 first)
WAKE_FRESH = 120             # a wake request nobody sent within this time is dropped
MAX_REQUESTS = 3             # open requests of the manager per device
_HOST = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?")   # a name or an IPv4 address; no scheme, port or path
_USER = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.@-]{0,63}")


@dataclass
class Device:
    id: int
    project_id: int
    name: str
    hostname: str
    description: str
    has_key: bool
    created_at: int
    kind: str = "other"
    ip: str = ""
    ssh_user: str = ""
    ssh_port: int = 22
    auth: str = "key"
    public_key: str = ""
    host_fp: str = ""
    pinned_ip: str = ""
    os_family: str = ""
    os_name: str = ""
    sudo_ok: bool | None = None
    lan_ok: bool = False
    ai_actions: tuple = field(default_factory=tuple)
    ai_password: bool = False
    updates_found: int = 0
    updates_at: int | None = None
    reboot_needed: bool = False
    checked_at: int | None = None
    ip_hint: str = ""           # the address found for the hostname: a suggestion, shown muted until taken
    mac: str = ""               # for switching on (Wake-on-LAN)
    picture: str = ""           # a picture the user dropped on the device (small data URL), wins over the pictogram
    icon_ai: str = ""           # the pictogram the AI chose from the fixed set

    @property
    def icon(self) -> str:
        return icon_for(self.kind, self.name, self.description, self.icon_ai)

    @property
    def can_wake(self) -> bool:
        """Can the hub switch it on? With a known MAC, in the owner's home network (Wake-on-LAN is a local broadcast)."""
        return bool(self.mac) and self.lan_ok

    @property
    def trusted(self) -> bool:
        return bool(self.host_fp)

    @property
    def actions(self) -> tuple:
        """What the buttons can do on this device: nothing before the host key is trusted and the system known."""
        return device_profiles.supported(self.os_family) if self.trusted and self.ssh_user else ()


def icon_for(kind: str, name: str = "", description: str = "", chosen: str = "") -> str:
    """The pictogram (icons.py): the one the AI chose from the fixed set, else a word for its use in the name or
    description, else the kind's picture; for "other" also a word of the name that says what it is."""
    if chosen in ICONS:
        return chosen
    text = f"{name} {description}".lower()
    for word, picture in CONTEXT_ICON:
        if re.search(rf"\b{word}", text):
            return picture
    if kind == "other":
        for word, picture in NAME_ICON:
            if re.search(rf"\b{word}", name.lower()):
                return picture
    return KIND_ICON.get(kind, "dev_box")


def _to_device(row: sqlite3.Row) -> Device:
    return Device(row["id"], row["project_id"], row["name"], row["hostname"], row["description"],
                  bool(row["key_enc"]), row["created_at"], row["kind"], row["ip"], row["ssh_user"], row["ssh_port"],
                  row["auth"], row["public_key"], row["host_fp"], row["pinned_ip"], row["os_family"], row["os_name"],
                  None if row["sudo_ok"] is None else bool(row["sudo_ok"]), bool(row["lan_ok"]),
                  tuple(a for a in row["ai_actions"].split(",") if a in AI_CHOICES), bool(row["ai_password"]),
                  row["updates_found"], row["updates_at"], bool(row["reboot_needed"]), row["checked_at"], row["ip_hint"],
                  row["mac"], row["picture"], row["icon_ai"])


def _clean(name: str, hostname: str, description: str, kind: str = "other", ip: str = "", ssh_user: str = "",
           ssh_port=22, auth: str = "key") -> tuple:
    name, hostname, description, ip, ssh_user = (name.strip(), hostname.strip().lower(), description.strip(),
                                                 ip.strip(), ssh_user.strip())
    if kind not in KINDS:
        raise ValueError("kind")
    if ip:
        try:
            ip = str(ipaddress.ip_address(ip))
        except ValueError:
            raise ValueError("ip") from None
    if not name or len(name) > MAX_NAME:
        raise ValueError("name")
    if len(hostname) > MAX_HOSTNAME or not _HOST.fullmatch(hostname):
        raise ValueError("hostname")
    if len(description) > MAX_DESCRIPTION:
        raise ValueError("description")
    if ssh_user and not _USER.fullmatch(ssh_user):
        raise ValueError("user")
    try:
        ssh_port = int(ssh_port or 22)
    except (TypeError, ValueError):
        raise ValueError("port") from None
    if not 0 < ssh_port < 65536:
        raise ValueError("port")
    if auth not in AUTHS:
        raise ValueError("auth")
    return name, hostname, description, kind, ip, ssh_user, ssh_port, auth


def _sealed(secret: str, auth: str = "key") -> str:
    """The secret as it is stored. SSH keys need their last line break, so a key is only normalised; a password is
    taken as typed (one line)."""
    if auth == "password":
        if not secret or len(secret) > MAX_PASSWORD or any(c in secret for c in "\x00\r\n"):
            raise ValueError("key")
        text = secret
    else:
        key = secret.replace("\r\n", "\n").replace("\r", "\n").strip("\n ")
        if not key or len(key) > MAX_KEY or "\x00" in key:
            raise ValueError("key")
        text = key + "\n"
    try:
        return vault.seal(text)
    except vault.VaultError:
        raise ValueError("vault") from None


def _owned(conn: sqlite3.Connection, user_id: int, device_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT d.* FROM devices d JOIN projects p ON p.id = d.project_id WHERE d.id = ? AND p.user_id = ?",
        (device_id, user_id)).fetchone()


def _taken(conn: sqlite3.Connection, project_id: int, name: str, except_id: int = 0) -> bool:
    return conn.execute("SELECT 1 FROM devices WHERE project_id = ? AND lower(name) = lower(?) AND id != ?",
                        (project_id, name, except_id)).fetchone() is not None


def _is_owner(conn: sqlite3.Connection, user_id: int) -> bool:
    return conn.execute("SELECT 1 FROM users WHERE id = ? AND role = 'owner'", (user_id,)).fetchone() is not None


def list_devices(user_id: int, project_id: int) -> list[Device]:
    """The devices of a project in the order they were made; empty for a foreign project."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT d.* FROM devices d JOIN projects p ON p.id = d.project_id"
            " WHERE d.project_id = ? AND p.user_id = ? ORDER BY d.id", (project_id, user_id)).fetchall()
    return [_to_device(r) for r in rows]


def get(user_id: int, device_id: int) -> Device | None:
    with db.connect() as conn:
        row = _owned(conn, user_id, device_id)
    return None if row is None else _to_device(row)


def create(user_id: int, project_id: int, name: str, hostname: str, description: str = "", key: str = "",
           kind: str = "other", ip: str = "", now: int | None = None, ssh_user: str = "", ssh_port=22,
           auth: str = "key") -> Device | None:
    """Add a device; None for a foreign project. ValueError(code) for bad input, a name that is already used in the
    project, a full list, or a secret that cannot be stored encrypted (no public key). The owner's own devices may
    reach the home network at once; other users' devices do not (lan_ok)."""
    name, hostname, description, kind, ip, ssh_user, ssh_port, auth = _clean(
        name, hostname, description, kind, ip, ssh_user, ssh_port, auth)
    sealed = _sealed(key, auth) if key.strip() else ""
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id)).fetchone() is None:
            return None
        if _taken(conn, project_id, name):
            raise ValueError("duplicate")
        if conn.execute("SELECT COUNT(*) FROM devices WHERE project_id = ?", (project_id,)).fetchone()[0] >= MAX_PER_PROJECT:
            raise ValueError("limit")
        cur = conn.execute(
            "INSERT INTO devices (project_id, name, kind, hostname, ip, description, key_enc, created_at, ssh_user,"
            " ssh_port, auth, lan_ok) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (project_id, name, kind, hostname, ip, description, sealed, int(now if now is not None else time.time()),
             ssh_user, ssh_port, auth, int(_is_owner(conn, user_id))))
        row = conn.execute("SELECT * FROM devices WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _to_device(row)


def update(user_id: int, device_id: int, name: str, hostname: str, description: str = "", key: str = "",
           remove_key: bool = False, kind: str = "other", ip: str = "", ssh_user: str | None = None,
           ssh_port=None, auth: str | None = None) -> int | None:
    """Change a device; its project id, or None if it is not the user's. An empty `key` keeps the stored secret, a new
    one replaces it, `remove_key` deletes it. Changing the login kind drops the old secret (a key is no password).
    A new hostname, IP or port forgets the trusted host key: the next connection shows the new one to confirm."""
    with db.connect() as conn:
        row = _owned(conn, user_id, device_id)
        if row is None:
            return None
        ssh_user = row["ssh_user"] if ssh_user is None else ssh_user
        ssh_port = row["ssh_port"] if ssh_port in (None, "") else ssh_port
        auth = row["auth"] if not auth else auth
        name, hostname, description, kind, ip, ssh_user, ssh_port, auth = _clean(
            name, hostname, description, kind, ip, ssh_user, ssh_port, auth)
        sealed = _sealed(key, auth) if key.strip() and not remove_key else None
        if _taken(conn, row["project_id"], name, device_id):
            raise ValueError("duplicate")
        conn.execute("UPDATE devices SET name = ?, kind = ?, hostname = ?, ip = ?, description = ?, ssh_user = ?,"
                     " ssh_port = ?, auth = ? WHERE id = ?",
                     (name, kind, hostname, ip, description, ssh_user, ssh_port, auth, device_id))
        if (hostname, ip, ssh_port) != (row["hostname"], row["ip"], row["ssh_port"]):
            conn.execute("UPDATE devices SET host_key = '', host_fp = '', pinned_ip = '' WHERE id = ?", (device_id,))
        if remove_key or (auth != row["auth"] and sealed is None):
            conn.execute("UPDATE devices SET key_enc = '', public_key = '' WHERE id = ?", (device_id,))
        elif sealed is not None:
            conn.execute("UPDATE devices SET key_enc = ?, public_key = '' WHERE id = ?", (sealed, device_id))
    return row["project_id"]


def delete(user_id: int, device_id: int) -> bool:
    with db.connect() as conn:
        if _owned(conn, user_id, device_id) is None:
            return False
        conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
    return True


# --- the broker's side -----------------------------------------------------------------------------------------------
def payload(user_id: int, device_id: int, origin: str = "human") -> dict | None:
    """The one device as the broker gets it (with the sealed secret, never in the clear), or None if it is not the
    user's or the AI may not use it at all."""
    with db.connect() as conn:
        row = _owned(conn, user_id, device_id)
    if row is None or origin not in ("human", "ai"):
        return None
    if origin == "ai" and row["auth"] == "password" and not row["ai_password"]:
        return None
    return {"id": row["id"], "host": row["hostname"], "ip": row["ip"], "port": row["ssh_port"],
            "user": row["ssh_user"], "auth": row["auth"], "secret": row["key_enc"], "host_key": row["host_key"],
            "pinned_ip": row["pinned_ip"], "lan_ok": bool(row["lan_ok"]), "family": row["os_family"],
            "ai_password": bool(row["ai_password"])}


def ai_may(user_id: int, device_id: int, action: str) -> bool:
    """May an AI run of this user trigger this action on this device? Only what the user ticked, and with a password
    login only if he allowed the password for the AI."""
    device = get(user_id, device_id)
    if device is None or action not in device.ai_actions or action not in device.actions:
        return False
    return device.auth != "password" or device.ai_password


def trust_host(user_id: int, device_id: int, host_key: str, fingerprint: str, address: str) -> bool:
    """Remember the host key the user confirmed and the address it was seen at (no switching by DNS later)."""
    with db.connect() as conn:
        if _owned(conn, user_id, device_id) is None:
            return False
        conn.execute("UPDATE devices SET host_key = ?, host_fp = ?, pinned_ip = ? WHERE id = ?",
                     (host_key[:4000], fingerprint[:200], address[:MAX_IP], device_id))
    return True


def set_ip_hint(user_id: int, device_id: int, address: str) -> bool:
    """The address the broker found for the hostname (a suggestion; the user's own IP field stays as it is)."""
    try:
        address = str(ipaddress.ip_address(address)) if address else ""
    except ValueError:
        return False
    with db.connect() as conn:
        if _owned(conn, user_id, device_id) is None:
            return False
        conn.execute("UPDATE devices SET ip_hint = ? WHERE id = ?", (address, device_id))
    return True


def forget_host(user_id: int, device_id: int) -> bool:
    with db.connect() as conn:
        if _owned(conn, user_id, device_id) is None:
            return False
        conn.execute("UPDATE devices SET host_key = '', host_fp = '', pinned_ip = '' WHERE id = ?", (device_id,))
    return True


def set_system(user_id: int, device_id: int, family: str, name: str, sudo_ok: bool | None,
               now: int | None = None, mac: str = "") -> bool:
    """What the connection test found: the system (family '' = unknown, then no buttons), whether sudo works and the
    MAC address (kept only if it looks like one; one the user typed is not overwritten by an empty one)."""
    family = family if family in device_profiles.FAMILIES else ""
    mac = clean_mac(mac)
    with db.connect() as conn:
        if _owned(conn, user_id, device_id) is None:
            return False
        conn.execute("UPDATE devices SET os_family = ?, os_name = ?, sudo_ok = ?, checked_at = ? WHERE id = ?",
                     (family, name[:80], None if sudo_ok is None else int(sudo_ok),
                      int(now if now is not None else time.time()), device_id))
        if mac:
            conn.execute("UPDATE devices SET mac = ? WHERE id = ?", (mac, device_id))
    return True


def clean_mac(value: str) -> str:
    """A MAC address as aa:bb:cc:dd:ee:ff, or '' if it is none (dashes and capitals are fine)."""
    value = (value or "").strip().lower().replace("-", ":")
    return value if _MAC.fullmatch(value) and value != "00:00:00:00:00:00" else ""


def set_login(user_id: int, device_id: int, ssh_user: str, ssh_port, mac: str | None = None) -> bool | None:
    """The SSH user and port (and optionally the MAC) on their own, for the setup assistant. None if not the user's;
    ValueError("user"/"port"/"mac") for bad input."""
    ssh_user = ssh_user.strip()
    if ssh_user and not _USER.fullmatch(ssh_user):
        raise ValueError("user")
    try:
        ssh_port = int(ssh_port or 22)
    except (TypeError, ValueError):
        raise ValueError("port") from None
    if not 0 < ssh_port < 65536:
        raise ValueError("port")
    if mac is not None and mac.strip() and not clean_mac(mac):
        raise ValueError("mac")
    with db.connect() as conn:
        row = _owned(conn, user_id, device_id)
        if row is None:
            return None
        conn.execute("UPDATE devices SET ssh_user = ?, ssh_port = ? WHERE id = ?", (ssh_user, ssh_port, device_id))
        if ssh_port != row["ssh_port"]:
            conn.execute("UPDATE devices SET host_key = '', host_fp = '', pinned_ip = '' WHERE id = ?", (device_id,))
        if mac is not None:
            conn.execute("UPDATE devices SET mac = ? WHERE id = ?", (clean_mac(mac), device_id))
    return True


def set_secret(user_id: int, device_id: int, auth: str, secret: str = "", remove: bool = False) -> bool | None:
    """Store a key or a password (sealed at once) or remove what is stored. None if not the user's; ValueError
    ("auth", "key", "vault") for bad input."""
    if auth not in AUTHS:
        raise ValueError("auth")
    sealed = "" if remove else _sealed(secret, auth)
    with db.connect() as conn:
        if _owned(conn, user_id, device_id) is None:
            return None
        conn.execute("UPDATE devices SET key_enc = ?, public_key = '', auth = ? WHERE id = ?", (sealed, auth, device_id))
    return True


def set_picture(user_id: int, device_id: int, picture: str) -> bool:
    """A small picture for the device (a data URL the browser made from a dropped image), or '' to go back to the
    pictogram. Only JPEG, PNG or WebP whose bytes really are one of these."""
    picture = picture.strip()
    if picture:
        import base64
        if len(picture) > MAX_PICTURE or not _PICTURE.fullmatch(picture):
            return False
        head = base64.b64decode(picture.split(",", 1)[1])[:12]
        if not (head.startswith(b"\xff\xd8\xff") or head.startswith(b"\x89PNG") or head[8:12] == b"WEBP"):
            return False
    with db.connect() as conn:
        if _owned(conn, user_id, device_id) is None:
            return False
        conn.execute("UPDATE devices SET picture = ? WHERE id = ?", (picture, device_id))
    return True


def set_icon_ai(conn: sqlite3.Connection, project_id: int, name: str, icon: str) -> bool:
    """The pictogram the AI chose for a device of this project (statusnote.save; the project comes from the job)."""
    if icon not in ICONS:
        return False
    return conn.execute("UPDATE devices SET icon_ai = ? WHERE project_id = ? AND lower(name) = lower(?)",
                        (icon, project_id, name.strip()[:MAX_NAME])).rowcount == 1


# --- the manager asks for an action (Janis, 17.11.2026: always through "waiting for you", whatever the autonomy) ---
@dataclass
class Request:
    id: int
    device_id: int
    device: str
    action: str
    reason: str
    created_at: int


def request_action(conn: sqlite3.Connection, user_id: int, project_id: int, name: str, action: str,
                   reason: str = "", now: int | None = None) -> bool:
    """The manager asks for `action` on the device called `name` of this project (from the chat answer; user and
    project come from the question). Taken only if the user allowed the AI this action on the device (ai_may), the
    device can do it, nothing of the same kind is open and the device has fewer than MAX_REQUESTS open."""
    row = conn.execute("SELECT d.id FROM devices d JOIN projects p ON p.id = d.project_id WHERE d.project_id = ?"
                       " AND p.user_id = ? AND lower(d.name) = lower(?)", (project_id, user_id, name.strip()[:MAX_NAME])).fetchone()
    if row is None:
        return False
    device = _to_device(conn.execute("SELECT * FROM devices WHERE id = ?", (row["id"],)).fetchone())
    if action not in device.ai_actions or action not in device.actions:
        return False
    if device.auth == "password" and not device.ai_password:
        return False
    open_rows = conn.execute("SELECT action FROM device_requests WHERE device_id = ? AND status = 'open'",
                             (device.id,)).fetchall()
    if action in {r["action"] for r in open_rows} or len(open_rows) >= MAX_REQUESTS:
        return False
    conn.execute("INSERT INTO device_requests (device_id, action, reason, created_at) VALUES (?, ?, ?, ?)",
                 (device.id, action, " ".join(reason.split())[:300], int(now if now is not None else time.time())))
    return True


def open_requests(user_id: int, project_id: int) -> list[Request]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT r.*, d.name FROM device_requests r JOIN devices d ON d.id = r.device_id JOIN projects p ON"
            " p.id = d.project_id WHERE d.project_id = ? AND p.user_id = ? AND r.status = 'open' ORDER BY r.id",
            (project_id, user_id)).fetchall()
    return [Request(r["id"], r["device_id"], r["name"], r["action"], r["reason"], r["created_at"]) for r in rows]


def decide(user_id: int, request_id: int, yes: bool, now: int | None = None) -> Request | None:
    """The user's yes or no to an open request; the request (for the caller to start the action on yes) or None."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT r.*, d.name FROM device_requests r JOIN devices d ON d.id = r.device_id JOIN projects p ON"
            " p.id = d.project_id WHERE r.id = ? AND p.user_id = ? AND r.status = 'open'", (request_id, user_id)).fetchone()
        if row is None:
            return None
        conn.execute("UPDATE device_requests SET status = ?, decided_at = ? WHERE id = ?",
                     ("done" if yes else "refused", int(now if now is not None else time.time()), request_id))
    return Request(row["id"], row["device_id"], row["name"], row["action"], row["reason"], row["created_at"])


# --- switching on ---------------------------------------------------------------------------------------------------
def request_wake(user_id: int, device_id: int, now: int | None = None) -> bool:
    """Ask the runner to send the Wake-on-LAN packet for this device. False if it is not the user's or can not be
    woken (no MAC, not in the owner's home network) or a wake for it is already waiting."""
    device = get(user_id, device_id)
    if device is None or not device.can_wake:
        return False
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM device_wakes WHERE mac = ? AND taken_at IS NULL AND created_at > ?",
                        (device.mac, now - WAKE_FRESH)).fetchone():
            return False
        conn.execute("INSERT INTO device_wakes (mac, created_at) VALUES (?, ?)", (device.mac, now))
    return True


def claim_wake(now: int | None = None) -> str | None:
    """Runner: the next MAC to wake (each handed out once), or None. Old ones are dropped."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        conn.execute("DELETE FROM device_wakes WHERE created_at <= ? OR taken_at IS NOT NULL", (now - WAKE_FRESH,))
        row = conn.execute("SELECT id, mac FROM device_wakes WHERE taken_at IS NULL ORDER BY id LIMIT 1").fetchone()
        if row is None:
            return None
        conn.execute("UPDATE device_wakes SET taken_at = ? WHERE id = ?", (now, row["id"]))
    return row["mac"]


def set_generated_key(user_id: int, device_id: int, sealed: str, public: str) -> bool:
    """A key pair the broker made: the sealed private part and the public line (to put on the device)."""
    if not sealed.startswith(vault.PREFIX) or not re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/=]+( [\w@.-]*)?", public):
        return False
    with db.connect() as conn:
        if _owned(conn, user_id, device_id) is None:
            return False
        conn.execute("UPDATE devices SET key_enc = ?, public_key = ?, auth = 'key' WHERE id = ?",
                     (sealed, public, device_id))
    return True


def set_ai(user_id: int, device_id: int, actions, ai_password: bool) -> bool:
    chosen = ",".join(a for a in AI_CHOICES if a in set(actions or ()))
    with db.connect() as conn:
        if _owned(conn, user_id, device_id) is None:
            return False
        conn.execute("UPDATE devices SET ai_actions = ?, ai_password = ? WHERE id = ?",
                     (chosen, int(bool(ai_password)), device_id))
    return True


def set_updates(user_id: int, device_id: int, found: int | None = None, reboot: bool | None = None,
                now: int | None = None) -> bool:
    """Updates found by a check (kept until they are installed or a day passes), or the state after installing."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        if _owned(conn, user_id, device_id) is None:
            return False
        if found is not None:
            conn.execute("UPDATE devices SET updates_found = ?, updates_at = ? WHERE id = ?", (max(0, int(found)), now, device_id))
        if reboot is not None:
            conn.execute("UPDATE devices SET reboot_needed = ? WHERE id = ?", (int(reboot), device_id))
    return True


UPDATES_VALID = 86400   # found updates count for a day (then the next press searches again)


def updates_pending(device: Device, now: int | None = None) -> int:
    now = int(now if now is not None else time.time())
    if not device.updates_found or not device.updates_at or now - device.updates_at > UPDATES_VALID:
        return 0
    return device.updates_found


# --- the hub's log of a device -----------------------------------------------------------------------------------------
@dataclass
class Entry:
    action: str
    result: str
    detail: str
    origin: str
    seconds: int
    created_at: int


def log(device_id: int, user_id: int | None, action: str, result: str = "", detail: str = "", origin: str = "human",
        seconds: int = 0, now: int | None = None) -> None:
    """Note what happened (never what was typed). Callers checked the device; the log only keeps the last LOG_KEEP."""
    with db.connect() as conn:
        conn.execute("INSERT INTO device_log (device_id, user_id, origin, action, result, detail, seconds, created_at)"
                     " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (device_id, user_id, origin if origin in ("human", "ai") else "human", action[:40], result[:40],
                      detail[:300], max(0, int(seconds)), int(now if now is not None else time.time())))
        conn.execute("DELETE FROM device_log WHERE device_id = ? AND id NOT IN"
                     " (SELECT id FROM device_log WHERE device_id = ? ORDER BY id DESC LIMIT ?)",
                     (device_id, device_id, LOG_KEEP))


def history(user_id: int, device_id: int, limit: int = 100) -> list[Entry] | None:
    with db.connect() as conn:
        if _owned(conn, user_id, device_id) is None:
            return None
        rows = conn.execute("SELECT * FROM device_log WHERE device_id = ? ORDER BY id DESC LIMIT ?",
                            (device_id, limit)).fetchall()
    return [Entry(r["action"], r["result"], r["detail"], r["origin"], r["seconds"], r["created_at"]) for r in rows]
