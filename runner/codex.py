"""ChatGPT through Codex (Janis, 21.11.2026): sign-in with the ChatGPT account (no API, no extra cost), tokens kept by the
runner only, runs with a ticket. Standard library only.

Sign-in: `codex login --device-auth` in a throwaway container (launcher.build_codex_login_command) prints a link and a
one-time code; the user signs in at OpenAI (the hub never sees a password) and Codex writes auth.json into the
container's folder. The runner reads it (`read_auth`), keeps the tokens encrypted (tokens.ProviderKeys, provider
"chatgpt") and deletes the folder.

Tokens: unlike Claude's setup-token they expire; only the runner refreshes them (`fresh`, OAuth refresh at OpenAI with
Codex's own client id), right before a job. Nothing else ever refreshes them, so no two programs fight over a refresh
token. A refused refresh means the user signs in again.

Runs: a run gets `run_auth(ticket, tokens)`: an auth.json whose access token is a JWT-shaped wrapper of the ticket and
whose refresh token is worthless; Codex sends every request to the egress gateway (port 3133), which takes the ticket
out, puts the real token and the account id in and passes only Codex's model calls on to chatgpt.com.

Models: the list the account may use is asked for by Codex itself (`codex debug models` in a container with a ticket,
runner/codex_entry.py job "models"), never by code of ours that would pretend to be Codex.
"""
import base64
import json
import re
import time
import urllib.error
import urllib.request

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"       # Codex's own OAuth client (from Codex 0.167.2)
AUTH_BASE = "https://auth.openai.com"
API_BASE = "https://chatgpt.com/backend-api"
VERSION = "0.167.2"                              # = runner/Dockerfile.codex
REFRESH_BEFORE = 600                             # seconds before the access token runs out
REFRESH_AFTER = 7 * 86400                        # refresh at least this often (Codex itself does after about 8 days)
LINK = re.compile(r"https://auth\.openai\.com/codex/device\b")
CODE = re.compile(r"\b([A-Z0-9]{4}-[A-Z0-9]{4,8})\b")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_JWT = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*")


class Refused(Exception):
    """OpenAI refused the tokens (signed out, revoked, refresh token used up): the user signs in again."""


class NoCodex(Exception):
    """The account's plan does not include Codex."""


def login_prompt(screen: str) -> tuple[str, str] | None:
    """(link, code) from what `codex login --device-auth` printed, or None while they are not there yet."""
    text = _ANSI.sub("", screen or "")
    link = LINK.search(text)
    after = text[text.find("one-time code"):] if "one-time code" in text else ""
    code = CODE.search(after)
    return (link.group(0), code.group(1)) if link and code else None


def claims(token: str) -> dict:
    """The payload of a JWT (not checked: OpenAI checks it; we only read when it runs out and the account)."""
    try:
        part = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (IndexError, ValueError, TypeError):
        return {}


def read_auth(text: str, now: float | None = None) -> dict:
    """The tokens kept by the runner from Codex's auth.json: {access, refresh, id, account, plan, refreshed}. ValueError
    if it is not a ChatGPT sign-in."""
    data = json.loads(text)
    tokens = data.get("tokens") or {}
    access, refresh, id_token = tokens.get("access_token"), tokens.get("refresh_token"), tokens.get("id_token")
    if not all(isinstance(t, str) and _JWT.fullmatch(t) for t in (access, id_token)) or not isinstance(refresh, str):
        raise ValueError("not a ChatGPT sign-in")
    auth = claims(id_token).get("https://api.openai.com/auth") or claims(access).get("https://api.openai.com/auth") or {}
    account = tokens.get("account_id") or auth.get("chatgpt_account_id") or ""
    return {"access": access, "refresh": refresh, "id": id_token, "account": str(account),
            "plan": str(auth.get("chatgpt_plan_type") or ""), "refreshed": int(now if now is not None else time.time())}


def dumps(kept: dict) -> str:
    return json.dumps(kept, separators=(",", ":"))


def loads(text: str) -> dict:
    kept = json.loads(text)
    if not isinstance(kept, dict) or not all(isinstance(kept.get(k), str) for k in ("access", "refresh", "account")):
        raise ValueError("not kept ChatGPT tokens")
    return kept


def _post(url: str, body: dict, opener=urllib.request.urlopen) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with opener(request, timeout=30) as answer:
            return json.load(answer)
    except urllib.error.HTTPError as error:
        if error.code in (400, 401, 403):
            raise Refused(f"refresh refused ({error.code})") from None
        raise OSError(f"refresh failed ({error.code})") from None


def fresh(kept: dict, now: float | None = None, opener=urllib.request.urlopen) -> tuple[dict, bool]:
    """(tokens, changed): refreshed when the access token runs out within REFRESH_BEFORE seconds or the last refresh is
    older than REFRESH_AFTER. Refused when OpenAI says no; OSError when it can not be reached (try again later)."""
    now = int(now if now is not None else time.time())
    expires = int(claims(kept["access"]).get("exp") or 0)
    if expires - now > REFRESH_BEFORE and now - int(kept.get("refreshed") or 0) < REFRESH_AFTER:
        return kept, False
    data = _post(f"{AUTH_BASE}/oauth/token", {"client_id": CLIENT_ID, "grant_type": "refresh_token",
                                              "refresh_token": kept["refresh"], "scope": "openid profile email"},
                 opener)
    access = data.get("access_token")
    if not isinstance(access, str) or not _JWT.fullmatch(access):
        raise Refused("no access token in the answer")
    renewed = dict(kept, access=access, refreshed=now)
    if isinstance(data.get("refresh_token"), str) and data["refresh_token"]:
        renewed["refresh"] = data["refresh_token"]           # it may come anew: the old one is then used up
    if isinstance(data.get("id_token"), str) and _JWT.fullmatch(data["id_token"]):
        renewed["id"] = data["id_token"]
    return renewed, True


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode().rstrip("=")


def ticket_jwt(ticket: str, kept: dict, now: float | None = None) -> str:
    """The run's "access token": a JWT-shaped wrapper of the ticket (unsigned, worthless anywhere but at our gateway).
    It carries what Codex reads from a token: when it runs out and the account; the gateway reads the ticket from it."""
    now = int(now if now is not None else time.time())
    payload = {"exp": now + 6 * 3600, "iat": now, "hub_ticket": ticket,
               "https://api.openai.com/auth": {"chatgpt_account_id": kept.get("account", ""),
                                               "chatgpt_plan_type": kept.get("plan", "")}}
    return f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(payload)}.hub"


def ticket_of(bearer: str) -> str:
    """For the gateway: the ticket inside such a wrapper, "" otherwise."""
    value = claims(bearer).get("hub_ticket") if _JWT.fullmatch(bearer or "") else ""
    return value if isinstance(value, str) else ""


def run_auth(ticket: str, kept: dict, now: float | None = None) -> str:
    """The auth.json of a run: the ticket's wrapper as access and id token, no usable refresh token, refreshed just now
    (so Codex does not try to refresh; if it does, the gateway refuses)."""
    wrapped = ticket_jwt(ticket, kept, now)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now if now is not None else time.time()))
    return json.dumps({"OPENAI_API_KEY": None, "auth_mode": "chatgpt",
                       "tokens": {"id_token": wrapped, "access_token": wrapped, "refresh_token": "hub-none",
                                  "account_id": kept.get("account", "")},
                       "last_refresh": stamp})
