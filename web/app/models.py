"""Which models each user's AI offers, asked for by the runner once a day (Janis, 21.11.2026: a new model of an AI must
appear in the drop-down by itself, without an update). Standard library only.

The runner asks each connected AI with the user's own credential (runner/models.py: Claude and Mistral `GET /v1/models`,
ChatGPT through Codex itself) and reports the raw list. Here it becomes catalog models (`normalize`, per provider) and
is kept per user (table ai_models). The catalog of a provider (catalog.py, server_settings) is the union of what all its
users were offered, with the starting list's names, hints and role starts where a model is still there; while nobody's
list has arrived, the starting list (catalog.SEED) holds. Each user sees and can choose only his own (`permits`,
`allowed`); a model that left his list falls back to the role's start or the AI's default (agents._choice).
"""
import json
import re
import sqlite3
import time

from . import aichoice, catalog, db

FETCHABLE = ("claude", "mistral", "chatgpt")    # the own AI has one model, the user's own (ai_link.py)
CHECK_EVERY = 86400                              # a list is asked for again after this long
RETRY_AFTER = 3600                               # ... or after a failed try
MAX_PER_USER = 24
_SKIP = re.compile(r"embed|moderation|ocr|voxtral|codestral|transcri|tts|audio|realtime|auto-review", re.I)
_FAMILY = re.compile(r"claude-([a-z]+)-")


def _name(text: str, fallback: str) -> str:
    """A display name that fits the catalog's pattern."""
    cleaned = re.sub(r"[^\w .+-]", " ", str(text or "")).strip()[:40]
    return cleaned or fallback[:40]


def _known(provider: str) -> dict:
    return {m["id"]: m for m in catalog.SEED[provider]["models"]}


def normalize(provider: str, raw: list) -> list[dict]:
    """The models of one user's list in the catalog's form (catalog.parse), newest first, at most MAX_PER_USER."""
    known, found = _known(provider), []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        if provider == "chatgpt":
            slug = str(item.get("slug") or item.get("id") or "")
            if item.get("visibility") not in (None, "list") or _SKIP.search(slug):
                continue
            levels = [lv.get("effort") if isinstance(lv, dict) else lv for lv in item.get("supported_reasoning_levels") or []]
            efforts = [e for e in levels if isinstance(e, str) and e != "ultra"] or ["medium"]
            default = item.get("default_reasoning_level") if item.get("default_reasoning_level") in efforts else efforts[0]
            images = "image" in (item.get("input_modalities") or [])
            entry = {"id": slug, "name": _name(item.get("display_name"), slug), "efforts": efforts,
                     "default_effort": default, "images": images}
        elif provider == "mistral":
            slug = str(item.get("id") or "")
            caps = item.get("capabilities") or {}
            if (not caps.get("completion_chat") or not caps.get("function_calling") or item.get("deprecation")
                    or slug.endswith("-latest") or _SKIP.search(slug)):
                continue
            seed = known.get(slug, {})
            entry = {"id": slug, "name": _name(item.get("name") or seed.get("name"), slug),
                     "efforts": seed.get("efforts", ["none"]), "default_effort": seed.get("default_effort", "none"),
                     "images": bool(caps.get("vision"))}
        else:   # claude: the family's short name (Claude Code takes "opus", "sonnet", ...): always its newest version
            match = _FAMILY.match(str(item.get("id") or ""))
            if not match:
                continue
            family = match.group(1)
            seed = known.get(family, {})
            entry = {"id": family, "name": seed.get("name", family.capitalize()), "efforts": seed.get("efforts", catalog._ALL),
                     "default_effort": seed.get("default_effort", "medium"), "images": True}
        seed = known.get(entry["id"], {})
        if seed.get("hint"):
            entry["hint"] = seed["hint"]
        if catalog._ID.fullmatch(entry["id"]) and entry["id"] not in {f["id"] for f in found}:
            found.append(entry)
    return found[:MAX_PER_USER]


def _merged(conn: sqlite3.Connection, provider: str) -> dict | None:
    """The provider's catalog from all users' lists (None while there is none): their models, the starting list's
    default and roles where those models are still there."""
    lists = [json.loads(r["models"]) for r in conn.execute(
        "SELECT models FROM ai_models WHERE provider = ? AND models != '[]' ORDER BY checked_at DESC", (provider,))]
    models, seen = [], set()
    for entries in lists:
        for entry in entries:
            if entry["id"] not in seen:
                seen.add(entry["id"])
                models.append(entry)
    if not models:
        return None
    seed = catalog.SEED[provider]
    data = {key: value for key, value in seed.items() if key not in ("models", "default_model")}
    data["models"] = models[:catalog.MAX_MODELS]
    ids = {m["id"] for m in data["models"]}
    data["default_model"] = seed["default_model"] if seed["default_model"] in ids else data["models"][0]["id"]
    data["roles"] = {r: pick for r, pick in (seed.get("roles") or {}).items() if pick[0] in ids}
    return data


def save(user_id: int, provider: str, raw: list | None, now: int | None = None) -> bool:
    """Runner: the user's list (None: the AI could not be asked). The catalog of the provider follows. False if the
    list could not be used (nothing changes then but the time of the try)."""
    if provider not in FETCHABLE:
        raise ValueError("provider")
    now = int(now if now is not None else time.time())
    entries = normalize(provider, raw) if raw is not None else None
    with db.connect() as conn:
        if entries:
            conn.execute("INSERT INTO ai_models (user_id, provider, models, checked_at, tried_at) VALUES (?, ?, ?, ?, ?)"
                         " ON CONFLICT(user_id, provider) DO UPDATE SET models = excluded.models,"
                         " checked_at = excluded.checked_at, tried_at = excluded.tried_at",
                         (user_id, provider, json.dumps(entries), now, now))
        else:
            conn.execute("INSERT INTO ai_models (user_id, provider, models, checked_at, tried_at) VALUES (?, ?, '[]', 0, ?)"
                         " ON CONFLICT(user_id, provider) DO UPDATE SET tried_at = excluded.tried_at",
                         (user_id, provider, now))
        data = _merged(conn, provider) if entries else None
    if data is None:
        return False
    try:
        catalog.store(provider, data)
    except ValueError:
        return False
    return True


def due(now: int | None = None) -> list[dict]:
    """Runner: the users' AIs whose list is to be asked for (connected; never asked, a day old, or a failed try an
    hour ago)."""
    now = int(now if now is not None else time.time())
    out = []
    with db.connect() as conn:
        users_ = [r["id"] for r in conn.execute("SELECT id FROM users WHERE deleted_at IS NULL ORDER BY id")]
        for user_id in users_:
            for provider in aichoice.connected_list(conn, user_id):
                if provider not in FETCHABLE:
                    continue
                row = conn.execute("SELECT checked_at, tried_at FROM ai_models WHERE user_id = ? AND provider = ?",
                                   (user_id, provider)).fetchone()
                if row is None or (now - row["checked_at"] > CHECK_EVERY and now - row["tried_at"] > RETRY_AFTER):
                    out.append({"user_id": user_id, "provider": provider})
    return out


def allowed(conn: sqlite3.Connection, user_id: int, provider: str) -> set[str] | None:
    """The model ids the user's AI offered him, or None while his list is not known (then every model counts)."""
    row = conn.execute("SELECT models FROM ai_models WHERE user_id = ? AND provider = ? AND models != '[]'",
                       (user_id, provider)).fetchone()
    return None if row is None else {m["id"] for m in json.loads(row["models"])}


def permits(conn: sqlite3.Connection, user_id: int, model: str) -> bool:
    """May this user choose this model (it is in his list, or his list is not known yet)?"""
    ids = allowed(conn, user_id, catalog.provider_of(model))
    return ids is None or model in ids

