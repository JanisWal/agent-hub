"""Checks a pasted Mistral API key with Mistral before the runner keeps it (runner.handle_keys). Standard library only.

Since 15.11.2026 Mistral answers in its own container (Mistral Vibe, runner/adapters.py, launcher.build_vibe_command)
with a ticket instead of the key; this module only asks `GET https://api.mistral.ai/v1/models` whether a key is taken.
The key goes only to api.mistral.ai (fixed here), over TLS with the certificate checked.
"""
import json
import urllib.error
import urllib.request

API = "https://api.mistral.ai/v1"


def verify(api_key: str, opener=urllib.request.urlopen) -> str:
    """Does Mistral take this key? "ok", "refused" (401/403) or "error" (network, Mistral down: try again later)."""
    request = urllib.request.Request(API + "/models", method="GET",
                                     headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"})
    try:
        with opener(request, timeout=20) as answer:
            json.load(answer)
        return "ok"
    except urllib.error.HTTPError as error:
        return "refused" if error.code in (401, 403) else "error"
    except (urllib.error.URLError, OSError, ValueError):
        return "error"
