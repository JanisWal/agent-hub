"""Sends e-mail through the Resend HTTP API. Standard library only.

Settings come from the environment (in production from `.env`, passed on by compose.yml):
RESEND_API_KEY (secret, never logged), MAIL_FROM (e.g. `Agent-Hub <noreply@janis-home.de>`) and
HUB_BASE_URL (e.g. https://hub.janis-home.de, used for links in mails). Without key and sender
nothing is sent: the hub keeps working, mail features just do nothing.
"""
import json
import logging
import os
import urllib.error
import urllib.request

API_URL = "https://api.resend.com/emails"
TIMEOUT_SECONDS = 10
# Resend sits behind Cloudflare, which rejects the default "Python-urllib" identification.
USER_AGENT = "agent-hub/1.0"

log = logging.getLogger("agent-hub.mail")


def configured() -> bool:
    """True if key and sender are set."""
    return bool(os.environ.get("RESEND_API_KEY") and os.environ.get("MAIL_FROM"))


def base_url() -> str:
    """Address of the hub for links in mails, without a trailing slash ('' if not set).

    Taken from the settings, never from the request: a forged Host header must not be able to
    point a reset link at somebody else's server.
    """
    return os.environ.get("HUB_BASE_URL", "").strip().rstrip("/")


def send_mail(to: str, subject: str, text: str, html: str | None = None) -> bool:
    """Send a mail with a plain-text part and, if given, an HTML part. True on success; False
    (with a log line) if not configured or the service refused. Never raises, never logs the key."""
    if not configured():
        log.warning("mail not sent: RESEND_API_KEY or MAIL_FROM is not set")
        return False
    message = {"from": os.environ["MAIL_FROM"], "to": [to], "subject": subject, "text": text}
    if html:
        message["html"] = html
    payload = json.dumps(message).encode()
    request = urllib.request.Request(
        API_URL,
        payload,
        {
            "Authorization": "Bearer " + os.environ["RESEND_API_KEY"],
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return 200 <= response.status < 300
    except urllib.error.HTTPError as problem:
        log.warning("mail refused by Resend: HTTP %s %s", problem.code, problem.read(300).decode(errors="replace"))
    except (urllib.error.URLError, OSError) as problem:
        log.warning("mail not sent: %s", problem)
    return False
