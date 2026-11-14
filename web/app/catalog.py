"""Which AI models there are and which effort levels each one has, per provider (Janis, 14.11.2026).

The list is data, not code: new models, other subscriptions and other providers must not need a code change. It
lives in the table `server_settings` (key "ai_catalog.<provider>") as JSON. Until somebody stores a list (the
button "Check AI models", next step), the starting list SEED below is used. Every place that lets the user pick a
model (manager chat, regular checks, the roles) takes the list from here and checks the choice with `check`.

Format of one provider:
  {"name": "Claude", "default_model": "sonnet",
   "models": [{"id": "sonnet", "name": "Sonnet", "hint": "balanced",
               "efforts": ["low", "medium", "high", "xhigh", "max"], "default_effort": "high"}, ...]}

`id` is what the provider's program takes (for Claude Code an alias such as "sonnet": it always means the newest
version, so a new version needs no change here, only a new family does). `name` is shown as it is (a proper name),
`hint` and the effort levels are keys whose texts are in i18n.py ("model_hint_<hint>", "effort_<level>"); an
unknown key just shows nothing (hint) or the raw level. Standard library only.
"""
import json
import re
from dataclasses import dataclass

from . import db

PROVIDERS = ("claude",)                   # providers the hub can start; more come with their own connection
DEFAULT_PROVIDER = "claude"
HINTS = ("fast", "balanced", "thorough", "deepest")
MAX_MODELS = 12
MAX_EFFORTS = 8
_ID = re.compile(r"[a-z][a-z0-9.-]{0,47}")     # never starts with "-": it goes to a command line as one argument
_EFFORT = re.compile(r"[a-z]{1,12}")
_NAME = re.compile(r"[\w .+-]{1,40}")

# Claude Code 2.1.319: --model takes an alias, --effort low, medium, high, xhigh or max (checked 14.11.2026).
# The default levels are Anthropic's defaults per model (Haiku and Opus medium, Sonnet and Fable high).
_ALL = ["low", "medium", "high", "xhigh", "max"]
SEED = {
    "claude": {
        "name": "Claude",
        "default_model": "sonnet",
        "models": [
            {"id": "haiku", "name": "Haiku", "hint": "fast", "efforts": _ALL, "default_effort": "medium"},
            {"id": "sonnet", "name": "Sonnet", "hint": "balanced", "efforts": _ALL, "default_effort": "high"},
            {"id": "opus", "name": "Opus", "hint": "thorough", "efforts": _ALL, "default_effort": "medium"},
            {"id": "fable", "name": "Fable", "hint": "deepest", "efforts": _ALL, "default_effort": "high"},
        ],
    },
}


@dataclass(frozen=True)
class Model:
    id: str
    name: str
    hint: str | None
    efforts: tuple[str, ...]
    default_effort: str


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    models: tuple[Model, ...]
    default_model: str

    def model(self, model_id: str | None) -> Model | None:
        return next((m for m in self.models if m.id == model_id), None)


def parse(provider_id: str, data: dict) -> Provider:
    """A provider from its JSON form. Raises ValueError if anything is missing, too long or not allowed, so a
    list from outside (the web check) is either taken whole or not at all."""
    if provider_id not in PROVIDERS or not isinstance(data, dict):
        raise ValueError("provider")
    name, raw_models = data.get("name"), data.get("models")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError("name")
    if not isinstance(raw_models, list) or not 1 <= len(raw_models) <= MAX_MODELS:
        raise ValueError("models")
    models = []
    for raw in raw_models:
        if not isinstance(raw, dict):
            raise ValueError("model")
        model_id, model_name, hint = raw.get("id"), raw.get("name"), raw.get("hint")
        efforts, default_effort = raw.get("efforts"), raw.get("default_effort")
        if not isinstance(model_id, str) or not _ID.fullmatch(model_id):
            raise ValueError("model id")
        if not isinstance(model_name, str) or not _NAME.fullmatch(model_name):
            raise ValueError("model name")
        if hint is not None and hint not in HINTS:
            hint = None                                   # an unknown hint is left out, the model stays
        if (not isinstance(efforts, list) or not 1 <= len(efforts) <= MAX_EFFORTS
                or not all(isinstance(e, str) and _EFFORT.fullmatch(e) for e in efforts)
                or len(set(efforts)) != len(efforts)):
            raise ValueError("efforts")
        if default_effort not in efforts:
            raise ValueError("default effort")
        models.append(Model(model_id, model_name, hint, tuple(efforts), default_effort))
    if len({m.id for m in models}) != len(models):
        raise ValueError("model ids")
    default_model = data.get("default_model")
    if default_model not in {m.id for m in models}:
        raise ValueError("default model")
    return Provider(provider_id, name, tuple(models), default_model)


def _key(provider_id: str) -> str:
    return f"ai_catalog.{provider_id}"


def provider(provider_id: str = DEFAULT_PROVIDER) -> Provider:
    """The models of a provider: the stored list, or SEED while none is stored (or the stored one is broken)."""
    if provider_id not in PROVIDERS:
        raise ValueError("provider")
    with db.connect() as conn:
        row = conn.execute("SELECT value FROM server_settings WHERE key = ?", (_key(provider_id),)).fetchone()
    if row is not None:
        try:
            return parse(provider_id, json.loads(row[0]))
        except ValueError:
            pass
    return parse(provider_id, SEED[provider_id])


def store(provider_id: str, data: dict) -> Provider:
    """Keep a new list for the whole server (the check of step 2 calls it). ValueError, and nothing changes, if the
    list is not valid."""
    checked = parse(provider_id, data)
    with db.connect() as conn:
        conn.execute("INSERT INTO server_settings (key, value) VALUES (?, ?)"
                     " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     (_key(provider_id), json.dumps(data, ensure_ascii=False)))
    return checked


def check(model: str, effort: str | None = None, provider_id: str = DEFAULT_PROVIDER) -> None:
    """ValueError if the model is not in the list, or the level is not one of this model's."""
    found = provider(provider_id).model(model)
    if found is None:
        raise ValueError("model")
    if effort is not None and effort not in found.efforts:
        raise ValueError("effort")


def resolve(model: str | None, effort: str | None, provider_id: str = DEFAULT_PROVIDER) -> tuple[str, str]:
    """A saved choice made valid again: a model that left the list becomes the default model, a level the model
    does not have becomes the model's default level. Nothing is stored here."""
    current = provider(provider_id)
    found = current.model(model) or current.model(current.default_model)
    return found.id, (effort if effort in found.efforts else found.default_effort)
