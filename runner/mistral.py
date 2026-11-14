"""The Mistral adapter (14.11.2026, KONZEPT-AGENTEN.md 9.2): one question in, one answer out, over Mistral's plain API.
Standard library only (urllib, json).

The hub builds the same package for every AI (role and rules, memory, project, question: web/app/chat.py); this
adapter only sends it to `POST https://api.mistral.ai/v1/chat/completions` as one user message and reads the answer
text and the token counts. No tools (no web search, no code): the hub says so in the rules. The fixed answer format
(`<memory file>`, `<read>`) is plain text, so it works the same as with Claude.

Unlike Claude Code, nothing of the AI runs on the Pi: the runner itself makes the request, so the key never goes into
a container and no gateway is needed. The key goes only to api.mistral.ai (fixed here, never from the hub or a job)
over TLS with the certificate checked. Errors never carry the key: only the HTTP status and Mistral's short message.
"""
import json
import re
import socket
import urllib.error
import urllib.request

API = "https://api.mistral.ai/v1"
TIMEOUT = 180            # seconds for one answer (the runner's CHAT_TIMEOUT for Claude is 200)
MAX_TOKENS = 12000       # tokens of one answer at most (thinking included); the hub keeps 8000 characters of it
_MODEL = re.compile(r"[a-z][a-z0-9.-]{0,47}")
_EFFORT = re.compile(r"[a-z]{1,12}")
_SECRET = re.compile(r"[A-Za-z0-9_-]{24,}")   # anything that could be a key is cut out of an error text


def _request(path: str, api_key: str, body: dict | None = None, opener=urllib.request.urlopen, timeout: int = TIMEOUT):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(API + path, data=data, method="GET" if body is None else "POST", headers={
        "Authorization": f"Bearer {api_key}", "Accept": "application/json",
        **({} if body is None else {"Content-Type": "application/json"})})
    with opener(request, timeout=timeout) as answer:
        return json.load(answer)


def _problem(error: urllib.error.HTTPError) -> str:
    """A short reason from Mistral's error answer, never more than 200 characters and nothing that looks like a key."""
    try:
        data = json.loads(error.read(4096) or b"{}")
        message = data.get("message") or data.get("detail") or ""
        if isinstance(message, (dict, list)):
            message = json.dumps(message)[:200]
    except (ValueError, OSError, AttributeError):
        message = ""
    return _SECRET.sub("…", str(message))[:200]


def verify(api_key: str, opener=urllib.request.urlopen) -> str:
    """Does Mistral take this key? "ok", "refused" (401/403) or "error" (network, Mistral down: try again later)."""
    try:
        _request("/models", api_key, opener=opener, timeout=20)
        return "ok"
    except urllib.error.HTTPError as error:
        return "refused" if error.code in (401, 403) else "error"
    except (urllib.error.URLError, OSError, ValueError):
        return "error"


def answer_text(content) -> str:
    """The answer from `message.content`: a string, or (a model that thinks) a list of chunks of which only the
    "text" ones are the answer; the "thinking" ones are left out."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    return ""


def ask(api_key: str, model: str, effort: str, prompt: str, opener=urllib.request.urlopen):
    """One question. Returns (ok, text, tokens_in, tokens_out, auth_problem) like launcher.parse_chat_output; on
    failure `text` is the reason (the hub only shows its kind, chat.failure_kind)."""
    if not _MODEL.fullmatch(model or "") or (effort and not _EFFORT.fullmatch(effort)):
        return False, "Bad model or effort level", 0, 0, False
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": MAX_TOKENS}
    if effort:
        body["reasoning_effort"] = effort
    try:
        data = _request("/chat/completions", api_key, body, opener=opener)
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            return False, f"Not logged in: Mistral refused the key ({error.code})", 0, 0, True
        if error.code == 429:
            return False, f"Mistral: too many requests or no credit left (429) {_problem(error)}".strip(), 0, 0, False
        return False, f"Mistral error {error.code}: {_problem(error)}".strip(), 0, 0, False
    except (socket.timeout, TimeoutError):
        return False, "Timeout: no answer in time.", 0, 0, False
    except urllib.error.URLError as error:
        if isinstance(error.reason, (socket.timeout, TimeoutError)):
            return False, "Timeout: no answer in time.", 0, 0, False
        return False, "Mistral not reachable", 0, 0, False
    except (OSError, ValueError):
        return False, "Mistral sent no readable answer", 0, 0, False
    try:
        choice = data["choices"][0]
        text = answer_text(choice["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError):
        return False, "Mistral sent no readable answer", 0, 0, False
    usage = data.get("usage") or {}
    tokens_in, tokens_out = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    if not text:
        return False, f"Mistral gave an empty answer ({choice.get('finish_reason') or '?'})", tokens_in, tokens_out, False
    return True, text, tokens_in, tokens_out, False
