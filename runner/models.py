"""The models an AI offers to the user, asked with his own credential once a day (Janis, 21.11.2026: new models appear
in the drop-down by themselves). Standard library only. The hub turns the raw lists into its catalog (web/app/models.py).

- Claude: `GET https://api.anthropic.com/v1/models` with the user's sign-in token.
- Mistral: `GET https://api.mistral.ai/v1/models` with the user's key.
- ChatGPT: asked by Codex itself in a container with a ticket (runner.Runner._chatgpt_models), never by code here.
Each asks only its own AI's fixed address over TLS; nothing of the answer but the list goes to the hub.
"""
import json
import urllib.error
import urllib.request

ADDRESSES = {"claude": "https://api.anthropic.com/v1/models?limit=100",
             "mistral": "https://api.mistral.ai/v1/models"}


def fetch(provider: str, secret: str, opener=urllib.request.urlopen) -> list[dict]:
    """The raw list of an AI ("data" of its answer). OSError when it can not be asked (refused, down)."""
    headers = {"Authorization": f"Bearer {secret}", "Accept": "application/json"}
    if provider == "claude":   # a sign-in token of `claude setup-token` needs the OAuth beta header
        headers.update({"anthropic-version": "2023-06-01", "anthropic-beta": "oauth-2025-04-20"})
    request = urllib.request.Request(ADDRESSES[provider], headers=headers, method="GET")
    try:
        with opener(request, timeout=30) as answer:
            data = json.load(answer)
    except (urllib.error.URLError, ValueError) as error:
        raise OSError(f"model list of {provider}: {type(error).__name__}") from None
    listed = data.get("data") if isinstance(data, dict) else None
    return [m for m in listed or [] if isinstance(m, dict)]
