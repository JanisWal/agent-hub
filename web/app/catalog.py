"""Which AI models there are and which effort levels each one has, per provider (Janis, 14.11.2026).

The list is data, not code: new models, other subscriptions and other providers must not need a code change. It
lives in the table `server_settings` (key "ai_catalog.<provider>") as JSON. Until somebody stores a list (the
button "Check AI models", next step), the starting list SEED below is used. Every place that lets the user pick a
model (manager chat, regular checks, the roles) takes the list from here and checks the choice with `check`.

Format of one provider:
  {"name": "Claude", "default_model": "sonnet",
   "models": [{"id": "sonnet", "name": "Sonnet", "hint": "balanced",
               "efforts": ["low", "medium", "high", "xhigh", "max"], "default_effort": "high", "images": true}, ...]}

`id` is what the provider's program takes (for Claude Code an alias such as "sonnet": it always means the newest
version, so a new version needs no change here, only a new family does). `name` is shown as it is (a proper name),
`hint` and the effort levels are keys whose texts are in i18n.py ("model_hint_<hint>", "effort_<level>"); an
unknown key just shows nothing (hint) or the raw level. `images` (18.11.2026) says whether the model sees pictures
(images and PDF pages); it is false when missing, so a model nobody checked is never sent a picture (its API would
refuse the request). Standard library only.

Tools (20.11.2026, Janis: every AI must be usable, with or without tools of its own): per provider `tools` names, for
each tool of TOOLS, where it comes from: "own" (the AI's program has it), "hub" (the hub hands its own, maybe weaker,
tool to the program) or "none". The packages (prompts.py) say only what is there; an AI without a way to read files gets
them in the package and may ask with <read>. Missing in a stored list = DEFAULT_TOOLS of the provider.

Several providers (Mistral since 14.11.2026): a model id belongs to exactly one provider (`store` refuses an id another
provider already has), so a saved choice ("model.chef" = "mistral-small-2603") tells by itself which AI answers
(`find`). Which providers a user may pick from depends on what he has connected (ui.model_picker, chat.send).
"""
import json
import re
import time
from dataclasses import dataclass

from . import db

PROVIDERS = ("claude", "mistral", "chatgpt", "custom")   # providers the hub can start; "custom" = the user's own AI
DEFAULT_PROVIDER = "claude"
HINTS = ("fast", "balanced", "thorough", "deepest")
TOOLS = ("read", "write", "shell", "search", "fetch", "look")   # look = see images and PDF pages
SOURCES = ("own", "hub", "none")
MAX_MODELS = 24             # models.py fills the lists from the AIs themselves (21.11.2026)
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
        # Claude Code brings all of them (Read shows images and PDFs).
        "tools": {"read": "own", "write": "own", "shell": "own", "search": "own", "fetch": "own", "look": "own"},
        "models": [
            {"id": "haiku", "name": "Haiku", "hint": "fast", "efforts": _ALL, "default_effort": "medium", "images": True},
            {"id": "sonnet", "name": "Sonnet", "hint": "balanced", "efforts": _ALL, "default_effort": "high", "images": True},
            {"id": "opus", "name": "Opus", "hint": "thorough", "efforts": _ALL, "default_effort": "medium", "images": True},
            {"id": "fable", "name": "Fable", "hint": "deepest", "efforts": _ALL, "default_effort": "high", "images": True},
        ],
    },
    # Mistral API (docs.mistral.ai, checked 14.11.2026): exact ids, because the levels (`reasoning_effort`) differ per
    # model and an alias such as "mistral-small-latest" may move to a model with other levels. Small 4 knows none and
    # high, Large 4 low, medium and high ("none" = no thinking: faster, fewer tokens). Medium 3.5 is deprecated.
    # Both take images (checked 18.11.2026: Small 4 is text and image in, Large 4 natively multimodal).
    "mistral": {
        "name": "Mistral",
        "default_model": "mistral-small-2603",
        # Mistral Vibe brings files, shell and web; pictures come through the hub's tool `look` (runner/hub_tools.py).
        "tools": {"read": "own", "write": "own", "shell": "own", "search": "own", "fetch": "own", "look": "hub"},
        "models": [
            {"id": "mistral-small-2603", "name": "Mistral Small", "hint": "fast", "efforts": ["none", "high"],
             "default_effort": "none", "images": True},
            {"id": "mistral-large-4", "name": "Mistral Large 4", "hint": "thorough", "efforts": ["low", "medium", "high"],
             "default_effort": "high", "images": True},
        ],
    },
    # ChatGPT through Codex with the ChatGPT sign-in (21.11.2026): the starting list from Codex 0.167.2's own catalog;
    # the account's real list replaces it (models.py). "ultra" is left out: it hands work to further agents. The roles
    # (21.11.2026, Janis): the manager a general model on a low level, programmer and reviewer a strong one.
    "chatgpt": {
        "name": "ChatGPT",
        "default_model": "gpt-6-luna",
        "tools": {"read": "own", "write": "own", "shell": "own", "search": "own", "fetch": "own", "look": "own"},
        "roles": {"chef": ["gpt-6-luna", "low"], "programmer": ["gpt-6.1-sol", "medium"],
                  "reviewer": ["gpt-6.1-sol", "medium"], "tester": ["gpt-6-luna", "medium"]},
        "models": [
            {"id": "gpt-6-luna", "name": "GPT-6 Luna", "hint": "fast", "efforts": ["low", "medium", "high", "xhigh", "max"],
             "default_effort": "medium", "images": True},
            {"id": "gpt-6-sol", "name": "GPT-6 Sol", "hint": "balanced", "efforts": ["low", "medium", "high", "xhigh", "max"],
             "default_effort": "medium", "images": True},
            {"id": "gpt-6.1-sol", "name": "GPT-6.1 Sol", "hint": "thorough",
             "efforts": ["low", "medium", "high", "xhigh", "max"], "default_effort": "low", "images": True},
            {"id": "gpt-6.1-terra", "name": "GPT-6.1 Terra", "hint": "deepest",
             "efforts": ["low", "medium", "high", "xhigh", "max"], "default_effort": "low", "images": True},
        ],
    },
    # The user's own AI (20.11.2026): any API in the OpenAI chat format. The real model name is the user's (ai_link.py,
    # per connection); here one stand-in model. It brings no tools: the hub's loop gives its own (runner/hubloop.py).
    "custom": {
        "name": "Weitere KI",
        "default_model": "own-1",
        "tools": {"read": "hub", "write": "hub", "shell": "hub", "search": "none", "fetch": "hub", "look": "hub"},
        # one stand-in per place of a further AI (ai_link.SLOTS); the page shows the user's own names for them
        "models": [{"id": f"own-{n}", "name": f"KI {n}", "efforts": ["none"], "default_effort": "none", "images": False}
                   for n in range(1, 9)],
    },
}


@dataclass(frozen=True)
class Model:
    id: str
    name: str
    hint: str | None
    efforts: tuple[str, ...]
    default_effort: str
    images: bool = False      # sees pictures (images, PDF pages)


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    models: tuple[Model, ...]
    default_model: str
    tools: tuple[tuple[str, str], ...] = ()   # (tool, source) for every tool of TOOLS
    roles: tuple[tuple[str, str, str], ...] = ()   # (role, model, effort): what a role starts with (none: default)

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
        if not isinstance(raw.get("images", False), bool):
            raise ValueError("images")
        models.append(Model(model_id, model_name, hint, tuple(efforts), default_effort, raw.get("images", False)))
    if len({m.id for m in models}) != len(models):
        raise ValueError("model ids")
    default_model = data.get("default_model")
    if default_model not in {m.id for m in models}:
        raise ValueError("default model")
    raw_tools = data.get("tools", SEED[provider_id].get("tools", {}))
    if not isinstance(raw_tools, dict) or any(k not in TOOLS or v not in SOURCES for k, v in raw_tools.items()):
        raise ValueError("tools")
    tools = tuple((t, raw_tools.get(t, "none")) for t in TOOLS)
    ids = {m.id: m for m in models}
    roles = tuple((role, pick[0], pick[1]) for role, pick in (data.get("roles") or {}).items()
                  if isinstance(pick, list) and len(pick) == 2 and pick[0] in ids and pick[1] in ids[pick[0]].efforts)
    return Provider(provider_id, name, tuple(models), default_model, tools, roles)


def role_default(provider_id: str, role: str) -> tuple[str, str] | None:
    """(model, effort) a role starts with at this AI when the user chose none (catalog "roles"), or None."""
    try:
        return next(((m, e) for r, m, e in provider(provider_id).roles if r == role), None)
    except ValueError:
        return None


def tools_of(provider_id: str) -> dict[str, str]:
    """{tool: "own" | "hub" | "none"} of a provider (TOOLS); every tool "none" for an unknown one."""
    try:
        return dict(provider(provider_id).tools)
    except ValueError:
        return {t: "none" for t in TOOLS}


def _key(provider_id: str) -> str:
    return f"ai_catalog.{provider_id}"


# A page asked for the catalog some 400 times (every model picker, every run row): reading and checking the stored list
# each time took 1.3 of 1.5 seconds of the project page (22.11.2026, measured). So a parsed list is kept for
# CACHE_SECONDS, per database; `store` drops it at once, another process sees a new list after at most that long.
CACHE_SECONDS = 30
_CACHE: dict[tuple[str, str], tuple[float, "Provider"]] = {}


def provider(provider_id: str = DEFAULT_PROVIDER) -> Provider:
    """The models of a provider: the stored list, or SEED while none is stored (or the stored one is broken)."""
    if provider_id not in PROVIDERS:
        raise ValueError("provider")
    key, now = (db.DB_PATH, provider_id), time.monotonic()
    hit = _CACHE.get(key)
    if hit is not None and now - hit[0] < CACHE_SECONDS:
        return hit[1]
    with db.connect() as conn:
        row = conn.execute("SELECT value FROM server_settings WHERE key = ?", (_key(provider_id),)).fetchone()
    found = None
    if row is not None:
        try:
            found = parse(provider_id, json.loads(row[0]))
        except ValueError:
            pass
    found = found or parse(provider_id, SEED[provider_id])
    _CACHE[key] = (now, found)
    return found


def store(provider_id: str, data: dict) -> Provider:
    """Keep a new list for the whole server (the check of step 2 calls it). ValueError, and nothing changes, if the
    list is not valid or names a model id that another provider has (then `find` could not tell them apart)."""
    checked = parse(provider_id, data)
    taken = {m.id for other in PROVIDERS if other != provider_id for m in provider(other).models}
    if taken & {m.id for m in checked.models}:
        raise ValueError("model ids")
    with db.connect() as conn:
        conn.execute("INSERT INTO server_settings (key, value) VALUES (?, ?)"
                     " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     (_key(provider_id), json.dumps(data, ensure_ascii=False)))
    _CACHE.pop((db.DB_PATH, provider_id), None)
    return checked


def find(model: str | None) -> tuple[Provider, Model] | None:
    """The provider a model id belongs to, with the model; None if no provider has it."""
    for provider_id in PROVIDERS:
        current = provider(provider_id)
        found = current.model(model)
        if found is not None:
            return current, found
    return None


def provider_of(model: str | None) -> str:
    """The id of the provider of a model; the default provider for an unknown one (resolve makes it valid there)."""
    hit = find(model)
    return hit[0].id if hit else DEFAULT_PROVIDER


def light(provider_id: str = DEFAULT_PROVIDER) -> tuple[str, str]:
    """The cheapest choice of a provider for small jobs such as the written status (statusnote.py): the first model
    of its list marked "fast" (else its first model) with that model's first, lowest level. From the list, never fixed
    in the code."""
    models = provider(provider_id).models
    model = next((m for m in models if m.hint == "fast"), models[0])
    return model.id, model.efforts[0] if model.efforts else model.default_effort


# Said in the package when the model can not see pictures (runtask.py, chat.py), the same for every AI.
BLIND_NOTE = ("The model you run on can not see pictures: when an image or the look of a PDF matters, say so plainly "
              "instead of guessing what it shows.")


def sees_images(model: str | None) -> bool:
    """Whether the model sees pictures (images, PDF pages); False for a model no provider has."""
    hit = find(model)
    return bool(hit and hit[1].images)


def check(model: str, effort: str | None = None, provider_id: str | None = None) -> None:
    """ValueError if the model is not in the list (of `provider_id`, or of any provider), or the level is not one of
    this model's."""
    hit = find(model)
    if hit is None or (provider_id is not None and hit[0].id != provider_id):
        raise ValueError("model")
    if effort is not None and effort not in hit[1].efforts:
        raise ValueError("effort")


def resolve(model: str | None, effort: str | None, provider_id: str | None = None) -> tuple[str, str]:
    """A saved choice made valid again: a model that left the list becomes the default model (of `provider_id`, or of
    the default provider), a level the model does not have becomes the model's default level. Nothing is stored."""
    hit = find(model)
    if hit is not None and provider_id in (None, hit[0].id):
        found = hit[1]
    else:
        current = provider(provider_id or DEFAULT_PROVIDER)
        found = current.model(current.default_model)
    return found.id, (effort if effort in found.efforts else found.default_effort)
