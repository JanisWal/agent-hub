"""The users' Claude tokens: kept encrypted, handed to a run only as a ticket (Janis, 14.11.2026).

A user links Claude with `claude setup-token`: a token for one year, made by Anthropic for machines without a
screen (code.claude.com/docs/en/authentication, "Generate a long-lived token"). It does not need refreshing, so
it does not run out after a day like the normal login did.

At rest: the runner keeps the token encrypted (Fernet = AES-128-CBC with HMAC-SHA256, from the package
`cryptography`; no own cryptography) in `<HUB_CLAUDE_DIR>/<user id>/token.enc`, owner root, folder 0700, file 0600.
The key (HUB_TOKEN_KEY) is only in the runner's environment (from .env): the web service, the egress proxy and
the runs never see it. No page and no route shows a token, not to the owner or an admin either.

In use: a run never gets the token. It gets a ticket, a random value that only counts while the run lasts. The
runner writes the token in plain text into a folder in memory (tmpfs), under the SHA-256 of the ticket, readable
only by the egress proxy; the proxy's gateway puts the real token into each request to Anthropic
(runner/egress.py) and the runner deletes the file when the run ends. A ticket that leaves the run is worthless:
it only works from inside the agent network and only until the run ends.
"""
import hashlib
import os
import re
import secrets
import shutil
import time
from pathlib import Path

TOKEN_FILE = "token.enc"
TOKEN = re.compile(r"sk-ant-oat[0-9]{2}-[A-Za-z0-9_-]{20,400}")     # what setup-token prints
TICKET = re.compile(r"hubrun-[A-Za-z0-9_-]{43}")                    # what a run gets instead
TICKET_OWNER = 65534        # the egress proxy runs as this user (compose.yml) and must read the ticket files
TICKET_AGE = 3600           # seconds a ticket file counts at most, even if a run forgot to delete it


def ticket_name(ticket: str) -> str:
    """The file name of a ticket: its SHA-256, so the folder never holds a ticket itself."""
    return hashlib.sha256(ticket.encode()).hexdigest()


class Vault:
    """The encrypted tokens, one file per user. Needs root (the runner) and the key."""

    def __init__(self, base: str | Path, key: str | None):
        self.base = Path(base)
        self.key = key or None

    def _fernet(self):
        from cryptography.fernet import Fernet   # only the runner has this package (runner/Dockerfile.runner)
        if not self.key:
            raise RuntimeError("HUB_TOKEN_KEY is not set")
        return Fernet(self.key.encode())

    def folder(self, user_id: int) -> Path:
        if type(user_id) is not int or user_id < 1:
            raise ValueError("user_id must be a positive integer")
        return self.base / str(user_id)

    def save(self, user_id: int, token: str) -> None:
        """Encrypt and store the token (replaces an older one). ValueError for anything that is not a token."""
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            raise ValueError("not a Claude token")
        folder = self.folder(user_id)
        folder.mkdir(parents=True, exist_ok=True)
        os.chown(folder, 0, 0)
        os.chmod(folder, 0o700)
        data = self._fernet().encrypt(token.encode())
        part = folder / (TOKEN_FILE + ".part")
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        os.replace(part, folder / TOKEN_FILE)

    def load(self, user_id: int) -> str | None:
        """The user's token, or None (none saved, or it can not be read with this key)."""
        from cryptography.fernet import InvalidToken
        try:
            data = (self.folder(user_id) / TOKEN_FILE).read_bytes()
            token = self._fernet().decrypt(data).decode()
        except (OSError, InvalidToken, RuntimeError, UnicodeDecodeError):
            return None
        return token if TOKEN.fullmatch(token) else None

    def forget(self, user_id: int) -> bool:
        """Delete the user's folder with the token in it (an expired or refused token). True if there was one."""
        folder = self.folder(user_id)
        if not folder.is_dir():
            return False
        shutil.rmtree(folder, ignore_errors=True)
        return True

    def clear_old(self, user_id: int) -> None:
        """Delete everything in the user's folder but the token: the files of the old login (until 14.11.2026 the
        runs used Claude Code's own login there, with a refresh token in plain text)."""
        folder = self.folder(user_id)
        for item in folder.iterdir() if folder.is_dir() else ():
            if item.name == TOKEN_FILE:
                continue
            if item.is_dir() and not item.is_symlink():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)


class Tickets:
    """Tickets of running runs: a file per ticket in a folder in memory that only the runner and the proxy see."""

    def __init__(self, folder: str | Path, owner: int = TICKET_OWNER):
        self.folder = Path(folder)
        self.owner = owner

    def issue(self, token: str) -> str:
        """A new ticket for this token; the proxy accepts it until `revoke` (or TICKET_AGE)."""
        if not TOKEN.fullmatch(token):
            raise ValueError("not a Claude token")
        ticket = "hubrun-" + secrets.token_urlsafe(32)
        path = self.folder / ticket_name(ticket)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        try:
            os.write(fd, token.encode())
            if os.geteuid() == 0:
                os.fchown(fd, self.owner, self.owner)
        finally:
            os.close(fd)
        return ticket

    def revoke(self, ticket: str) -> None:
        if TICKET.fullmatch(ticket):
            (self.folder / ticket_name(ticket)).unlink(missing_ok=True)

    def sweep(self, now: float | None = None, max_age: int = TICKET_AGE) -> None:
        """Delete tickets older than max_age (0 = all, e.g. when the runner starts and no run is going)."""
        now = time.time() if now is None else now
        for item in self.folder.iterdir() if self.folder.is_dir() else ():
            try:
                if max_age == 0 or now - item.stat().st_mtime > max_age:
                    item.unlink(missing_ok=True)
            except OSError:
                pass


def lookup(folder: str | Path, ticket: str, now: float | None = None, max_age: int = TICKET_AGE) -> str | None:
    """For the proxy: the token behind a ticket, or None (unknown, malformed or too old)."""
    if not isinstance(ticket, str) or not TICKET.fullmatch(ticket):
        return None
    path = Path(folder) / ticket_name(ticket)
    try:
        if (time.time() if now is None else now) - path.stat().st_mtime > max_age:
            return None
        token = path.read_text().strip()
    except (OSError, UnicodeDecodeError):
        return None
    return token if TOKEN.fullmatch(token) else None


# --- API keys of other AIs (Mistral since 14.11.2026; web/app/ai_link.py). Same encryption and key as the Claude
# tokens, but their own folder `<HUB_CLAUDE_DIR>/keys/<provider>/<user id>.enc`: deleting or renewing a user's Claude
# folder (wipes, Vault.clear_old) never touches them, and the folder name "keys" can never be a user id.
# These keys never go to a run: the runner itself asks the provider (runner/mistral.py), no code of an AI runs there.
KEY_PATTERNS = {"mistral": re.compile(r"[A-Za-z0-9_-]{16,200}")}


class ProviderKeys:
    """The encrypted API keys, one file per user and provider. Needs root (the runner) and HUB_TOKEN_KEY."""

    def __init__(self, base: str | Path, key: str | None):
        self.vault = Vault(base, key)          # only for its Fernet
        self.base = Path(base) / "keys"

    def path(self, user_id: int, provider: str) -> Path:
        if type(user_id) is not int or user_id < 1:
            raise ValueError("user_id must be a positive integer")
        if provider not in KEY_PATTERNS:
            raise ValueError("unknown provider")
        return self.base / provider / f"{user_id}.enc"

    def save(self, user_id: int, provider: str, api_key: str) -> None:
        path = self.path(user_id, provider)
        if not isinstance(api_key, str) or not KEY_PATTERNS[provider].fullmatch(api_key):
            raise ValueError("not an API key")
        for folder in (self.base, path.parent):
            folder.mkdir(parents=True, exist_ok=True)
            os.chmod(folder, 0o700)
        data = self.vault._fernet().encrypt(api_key.encode())
        part = path.with_suffix(".part")
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        os.replace(part, path)

    def load(self, user_id: int, provider: str) -> str | None:
        from cryptography.fernet import InvalidToken
        try:
            path = self.path(user_id, provider)
            api_key = self.vault._fernet().decrypt(path.read_bytes()).decode()
        except (OSError, ValueError, InvalidToken, RuntimeError, UnicodeDecodeError):
            return None
        return api_key if KEY_PATTERNS[provider].fullmatch(api_key) else None

    def forget(self, user_id: int, provider: str) -> bool:
        """Delete the saved key. True if there was one."""
        path = self.path(user_id, provider)
        existed = path.exists()
        path.unlink(missing_ok=True)
        return existed
