"""Connections of a user to an AI that signs in with an API key (Mistral since 14.11.2026; later more). One per user
and provider, never shared, no fallback to anybody else's. Standard library only.

Like claude_link.py, this module only knows the *state*. The key itself is a credential: the user pastes it in the
menu, it stays in the memory of this process for a few minutes (never in the database, never in a log) and the
runner fetches it once (`take_keys`). The runner checks it with the provider, keeps it encrypted in its own folder
(runner/tokens.py, ProviderKeys) and reports back (`complete`). Nobody can read it back, not the owner either.

States: none -> connecting (the runner checks the key) -> connected -> expired (the provider refused the key) ->
connecting ...; "wipe" = disconnected, the runner still deletes the saved key (then the row goes). A deleted account
leaves its rows as "wipe" (no foreign key on purpose), so the runner deletes the key files of a deleted user too.
The user always comes from the session or the database, never from a parameter a browser could send.

The user's own AI ("custom", 20.11.2026): besides the key (optional: a local model may need none) the address of an
API in the OpenAI chat format and the model name there. They are no secret and stay in the row (`endpoint`,
`remote_model`), taken over only once the runner checked them. Plain http and addresses in the home network only for the
owner's own AI (`route_in`: lan); the gateway and the runner check the address again (runner/egress.py, runner/custom.py).
"""
import re
import sqlite3
import time

from . import db

PROVIDERS = ("mistral", "chatgpt")   # AIs whose connection the runner keeps (Claude has claude_link.py)
# More AIs in the OpenAI format (catalog provider "custom", 21.11.2026): as many as SLOTS per user, each its own
# connection with its own name ("custom-1" ...); the tile to add one more always stays in the menu.
SLOTS = tuple(f"custom-{n}" for n in range(1, 9))
# API keys next to a plan (credentials.py, 21.11.2026): connections of their own, not AIs of their own
API_KEYS = ("claude-api", "chatgpt-api")
# ChatGPT (21.11.2026): no key at all; the user signs in at OpenAI with a one-time code the runner shows (runner/codex.py)
DEVICE_LOGIN = ("chatgpt",)
DEVICE_SECONDS = 16 * 60         # the code lasts 15 minutes; then the sign-in counts as failed
DEVICE_URL = re.compile(r"https://auth\.openai\.com/codex/device")
DEVICE_CODE = re.compile(r"[A-Z0-9]{4}-[A-Z0-9]{4,8}")
STATUSES = ("none", "connecting", "connected", "expired", "noplan")   # noplan: ChatGPT without Codex in the plan
CHECK_SECONDS = 120               # the runner has this long to check a key, else the connection counts as failed
KEY_SECONDS = 300                 # a pasted key waits this long for the runner, then it is forgotten
KEY = re.compile(r"[A-Za-z0-9_-]{16,200}")   # what an API key looks like (Mistral: 32 letters and digits)
KEYS = {"mistral": KEY, **{slot: re.compile(r"[!-~]{1,400}") for slot in SLOTS},   # = runner/tokens.KEY_PATTERNS
        "claude-api": re.compile(r"sk-ant-api[0-9]{2}-[A-Za-z0-9_-]{20,300}"),
        "chatgpt-api": re.compile(r"sk-[A-Za-z0-9_-]{20,300}")}
NO_KEY = "-"                                        # the own AI needs no key (runner/tokens.NO_KEY)
ENDPOINT = re.compile(r"https?://[A-Za-z0-9.-]{1,253}(?::[0-9]{1,5})?(?:/[A-Za-z0-9._~/-]{0,200})?")   # = tokens.ENDPOINT
REMOTE_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,99}")                                   # = launcher._REMOTE_MODEL

# (user, provider) -> (key, forget at, endpoint, model); memory of this process only
_keys: dict[tuple[int, str], tuple[str, int, str, str]] = {}


def _check_provider(provider: str) -> None:
    if provider not in PROVIDERS and provider not in API_KEYS and provider not in SLOTS:
        raise ValueError("provider")


def is_custom(name: str) -> bool:
    return name in SLOTS


def custom_rows(conn: sqlite3.Connection, user_id: int, now: int | None = None) -> list[dict]:
    """The user's further AIs: {slot, name, state, label, endpoint, model}, in the order of SLOTS (not the deleted)."""
    now = int(now if now is not None else time.time())
    rows = {r["provider"]: r for r in conn.execute(
        "SELECT * FROM ai_connections WHERE user_id = ? AND provider LIKE 'custom-%'", (user_id,))}
    out = []
    for n, slot in enumerate(SLOTS, 1):
        row = rows.get(slot)
        state = _effective(row, now) if row is not None else "none"
        if state != "none":
            out.append({"slot": n, "name": slot, "state": state, "label": row["label"] or f"KI {n}",
                        "endpoint": row["endpoint"], "model": row["remote_model"]})
    return out


def custom_connected(conn: sqlite3.Connection, user_id: int) -> list[int]:
    """The slots of the user's further AIs that are connected."""
    return [r["slot"] for r in custom_rows(conn, user_id) if r["state"] == "connected"]


def free_slot(conn: sqlite3.Connection, user_id: int) -> str | None:
    """The next free place for one more AI, or None when all SLOTS are taken. A place whose key the runner has still
    to delete ("wipe") is not free yet: a new key there could go with the old one's deletion."""
    taken = {r["name"] for r in custom_rows(conn, user_id)} | {r["provider"] for r in conn.execute(
        "SELECT provider FROM ai_connections WHERE user_id = ? AND provider LIKE 'custom-%' AND status = 'wipe'",
        (user_id,))}
    return next((s for s in SLOTS if s not in taken), None)


def _row(conn: sqlite3.Connection, user_id: int, provider: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM ai_connections WHERE user_id = ? AND provider = ?",
                        (user_id, provider)).fetchone()


def _effective(row: sqlite3.Row | None, now: int) -> str:
    if row is None or row["status"] == "wipe":
        return "none"
    limit = DEVICE_SECONDS if row["provider"] in DEVICE_LOGIN else CHECK_SECONDS
    if row["status"] == "connecting" and now - row["updated_at"] > limit:
        return row["previous"] or "none"                  # the runner never answered: as it was before
    return row["status"]


def status_in(conn: sqlite3.Connection, user_id: int, provider: str, now: int | None = None) -> str:
    _check_provider(provider)
    return _effective(_row(conn, user_id, provider), int(now if now is not None else time.time()))


def connected_in(conn: sqlite3.Connection, user_id: int, provider: str) -> bool:
    return status_in(conn, user_id, provider) == "connected"


def status(user_id: int, provider: str, now: int | None = None) -> str:
    """none, connecting, connected or expired."""
    with db.connect() as conn:
        return status_in(conn, user_id, provider, now)


def _save(conn: sqlite3.Connection, user_id: int, provider: str, new_status: str, now: int,
          previous: str = "") -> None:
    """Write the state. `previous` is the state before a check began (connected or expired: a saved key exists)."""
    conn.execute(
        "INSERT INTO ai_connections (user_id, provider, status, previous, updated_at) VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT(user_id, provider) DO UPDATE SET status = excluded.status, previous = excluded.previous,"
        " updated_at = excluded.updated_at",
        (user_id, provider, new_status, previous, now),
    )


def _owner(conn: sqlite3.Connection, user_id: int) -> bool:
    row = conn.execute("SELECT role FROM users WHERE id = ? AND deleted_at IS NULL", (user_id,)).fetchone()
    return row is not None and row["role"] == "owner"


def submit_key(user_id: int, provider: str, key: str, now: int | None = None, endpoint: str = "",
               model: str = "", label: str = "") -> bool:
    """The user pasted a key (connect, or a new key after "expired"). ValueError("key") for something that is not a
    key; False while a check of an earlier key is still running. A key that works replaces the old one.
    The own AI also needs `endpoint` and `model`: ValueError("endpoint") or ("model") for bad ones, ("home") for plain
    http without the owner's switch (home_allowed); its key may be empty."""
    _check_provider(provider)
    key = key.strip()
    endpoint, model = endpoint.strip().rstrip("/"), model.strip()
    label = " ".join(label.split())[:40]
    if is_custom(provider):
        key = key or NO_KEY
        if not REMOTE_MODEL.fullmatch(model):
            raise ValueError("model")
        if not ENDPOINT.fullmatch(endpoint):
            raise ValueError("endpoint")
    if not KEYS[provider].fullmatch(key):
        raise ValueError("key")
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        if is_custom(provider) and endpoint.startswith("http://") and not home_allowed(conn, user_id):
            raise ValueError("home")   # plain http only in the home network, and that only for the owner who allows it
        before = status_in(conn, user_id, provider, now)
        if before == "connecting":
            return False
        _save(conn, user_id, provider, "connecting", now, before if before in ("connected", "expired") else "")
    _keys[(user_id, provider)] = (key, now + KEY_SECONDS, endpoint, model, label)
    return True


def begin_login(user_id: int, provider: str, now: int | None = None) -> bool:
    """The user wants to sign in with a one-time code (ChatGPT): "connecting" until the runner reports how it went.
    False while one is running already."""
    if provider not in DEVICE_LOGIN:
        raise ValueError("provider")
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        before = status_in(conn, user_id, provider, now)
        if before == "connecting":
            return False
        _save(conn, user_id, provider, "connecting", now, before if before in ("connected", "expired") else "")
        conn.execute("UPDATE ai_connections SET login_url = '', login_code = '' WHERE user_id = ? AND provider = ?",
                     (user_id, provider))
    return True


def pending_device_logins(now: int | None = None) -> list[dict]:
    """Runner: sign-ins with a one-time code that are going on, as {user_id, provider}."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM ai_connections WHERE status = 'connecting' AND provider IN"
                            f" ({','.join('?' * len(DEVICE_LOGIN))})", DEVICE_LOGIN).fetchall()
    return [{"user_id": r["user_id"], "provider": r["provider"]} for r in rows if _effective(r, now) == "connecting"]


def set_device_prompt(user_id: int, provider: str, url: str, code: str) -> bool:
    """Runner: the link and the one-time code to show. ValueError for anything else than OpenAI's page and a code."""
    if provider not in DEVICE_LOGIN or not DEVICE_URL.fullmatch(url or "") or not DEVICE_CODE.fullmatch(code or ""):
        raise ValueError("prompt")
    with db.connect() as conn:
        return conn.execute("UPDATE ai_connections SET login_url = ?, login_code = ? WHERE user_id = ? AND provider = ?"
                            " AND status = 'connecting'", (url, code, user_id, provider)).rowcount == 1


def device_prompt(user_id: int, provider: str) -> tuple[str, str]:
    """(link, code) of the user's own sign-in going on; ("", "") while there is none."""
    with db.connect() as conn:
        row = _row(conn, user_id, provider)
        if row is None or status_in(conn, user_id, provider) != "connecting":
            return "", ""
    return row["login_url"], row["login_code"]


def take_keys(now: int | None = None) -> list[dict]:
    """Runner: the keys waiting to be checked, each handed over once: {user_id, provider, key} and for the own AI also
    endpoint and lan (the owner's own AI may be in the home network)."""
    now = int(now if now is not None else time.time())
    taken = []
    for (user_id, provider), (key, until, endpoint, _model, label) in list(_keys.items()):
        if until >= now and status(user_id, provider, now) == "connecting":
            item = {"user_id": user_id, "provider": provider, "key": key}
            if is_custom(provider):   # the key stays until `complete`: endpoint and model are taken over with it
                with db.connect() as conn:
                    item.update(endpoint=endpoint, lan=home_allowed(conn, user_id))
                _keys[(user_id, provider)] = ("", until, endpoint, _model, label)
            else:
                del _keys[(user_id, provider)]
            taken.append(item)
        else:
            del _keys[(user_id, provider)]
    return [t for t in taken if t["key"]]


def complete(user_id: int, provider: str, ok: bool, now: int | None = None) -> bool:
    """Runner: the provider accepted the key (connected) or refused it (back to what was before: the old key keeps
    working, "expired" stays "expired", without a saved key the row goes). False if no check was running."""
    _check_provider(provider)
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        row = _row(conn, user_id, provider)
        if row is None or row["status"] != "connecting":
            return False
        conn.execute("UPDATE ai_connections SET login_url = '', login_code = '' WHERE user_id = ? AND provider = ?",
                     (user_id, provider))
        if ok:
            _save(conn, user_id, provider, "connected", now)
            pending = _keys.pop((user_id, provider), None)
            if is_custom(provider) and pending:   # the checked address, model and name become the connection's
                conn.execute("UPDATE ai_connections SET endpoint = ?, remote_model = ?, label = ? WHERE user_id = ?"
                             " AND provider = ?", (pending[2], pending[3], pending[4], user_id, provider))
        elif row["previous"]:
            _save(conn, user_id, provider, row["previous"], now)   # the runner kept the old key file
        else:
            conn.execute("DELETE FROM ai_connections WHERE user_id = ? AND provider = ?", (user_id, provider))
    return True


def home_allowed(conn: sqlite3.Connection, user_id: int) -> bool:
    """May this user's further AI be in the server's home network (plain http too)? Only the owner's, and only when
    he switched it on in the system settings (serversettings.ai_home_network, 21.11.2026). A colleague's AI at his
    home is not in this network: reachable only if it is public (then no switch is needed) or later over a VPN."""
    from . import serversettings
    return _owner(conn, user_id) and serversettings.ai_home_network()


def route_in(conn: sqlite3.Connection, user_id: int, provider: str, model: str = "") -> dict:
    """What a job of a further AI needs besides the ticket: {slot, endpoint, remote_model, lan}; {} for other AIs.
    The slot comes from the model ("own-3"); one that is not connected (a stand-in of the cheapest model) takes the
    user's first connected one."""
    if provider != "custom":
        return {}
    connected = custom_connected(conn, user_id)
    wanted = int(model.split("-")[1]) if model.startswith("own-") and model.split("-")[1].isdigit() else 0
    slot = wanted if wanted in connected else (connected[0] if connected else 0)
    row = _row(conn, user_id, f"custom-{slot}") if slot else None
    if row is None:
        return {}
    return {"slot": slot, "endpoint": row["endpoint"], "remote_model": row["remote_model"],
            "lan": home_allowed(conn, user_id)}


def mark_noplan(user_id: int, provider: str) -> bool:
    """Runner: the AI said the account's plan does not include its program (ChatGPT without Codex). The sign-in stays;
    the menu says why it is not used, and signing in again (after a change of plan) tries anew."""
    _check_provider(provider)
    with db.connect() as conn:
        if status_in(conn, user_id, provider) != "connected":
            return False
        _save(conn, user_id, provider, "noplan", int(time.time()))
    return True


def mark_expired(user_id: int, provider: str) -> bool:
    """Runner: the provider refused the saved key during a question (revoked, no credit). The runner deletes it."""
    _check_provider(provider)
    with db.connect() as conn:
        if status_in(conn, user_id, provider) != "connected":
            return False
        _save(conn, user_id, provider, "expired", int(time.time()))
    return True


def disconnect(user_id: int, provider: str, now: int | None = None) -> bool:
    """The user removes the connection: "none" for him at once, "wipe" until the runner deleted the saved key."""
    _check_provider(provider)
    now = int(now if now is not None else time.time())
    _keys.pop((user_id, provider), None)
    with db.connect() as conn:
        if _row(conn, user_id, provider) is None:
            return False
        _save(conn, user_id, provider, "wipe", now)
    return True


def wipe_user(conn: sqlite3.Connection, user_id: int) -> None:
    """The account is being deleted (users.delete_user, same transaction): all its saved keys go."""
    conn.execute("UPDATE ai_connections SET status = 'wipe' WHERE user_id = ?", (user_id,))
    for item in [k for k in _keys if k[0] == user_id]:
        _keys.pop(item, None)


def pending_wipes() -> list[tuple[int, str]]:
    """Runner: (user_id, provider) whose saved key has to be deleted (disconnected or deleted accounts). A refused key
    the runner deletes on its own when the provider refuses it (Janis, 14.11.2026); that row stays "expired"."""
    with db.connect() as conn:
        rows = conn.execute("SELECT user_id, provider FROM ai_connections WHERE status = 'wipe'"
                            " ORDER BY user_id, provider").fetchall()
    return [(r["user_id"], r["provider"]) for r in rows]


def wiped(user_id: int, provider: str) -> bool:
    """Runner: the key file is gone. Forgets the row unless the user pasted a new key meanwhile."""
    _check_provider(provider)
    with db.connect() as conn:
        return conn.execute("DELETE FROM ai_connections WHERE user_id = ? AND provider = ? AND status = 'wipe'",
                            (user_id, provider)).rowcount == 1
