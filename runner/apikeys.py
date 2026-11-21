"""Checks an API key a user gave next to his plan of Claude or ChatGPT (21.11.2026, web/app/credentials.py) before the
runner keeps it. Standard library only; each key goes only to its own AI's fixed address over TLS.
"""
import json
import urllib.error
import urllib.request

ADDRESSES = {"claude-api": "https://api.anthropic.com/v1/models", "chatgpt-api": "https://api.openai.com/v1/models"}


def verify(provider: str, api_key: str, opener=urllib.request.urlopen) -> str:
    """"ok", "refused" (401/403) or "error" (not reachable: try again later)."""
    headers = ({"x-api-key": api_key, "anthropic-version": "2023-06-01"} if provider == "claude-api"
               else {"Authorization": f"Bearer {api_key}"})
    request = urllib.request.Request(ADDRESSES[provider], headers={**headers, "Accept": "application/json"})
    try:
        with opener(request, timeout=20) as answer:
            json.load(answer)
        return "ok"
    except urllib.error.HTTPError as error:
        return "refused" if error.code in (401, 403) else "error"
    except (urllib.error.URLError, OSError, ValueError):
        return "error"


class Verifier:
    """The interface of runner.Runner.verifiers for one of the two keys."""

    def __init__(self, provider: str):
        self.provider = provider

    def verify(self, api_key: str) -> str:
        return verify(self.provider, api_key)
