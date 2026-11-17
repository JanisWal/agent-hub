"""Encryption of secrets kept in the database (device keys, later more).

Fernet of the package `cryptography` (no own cryptography; the only dependency added for this, in requirements.txt).
The master key is `HUB_VAULT_KEY` from the `.env` (a Fernet key, made with `Fernet.generate_key()`); it is not in the
database, not in the backup and not in Git. Without a valid key nothing can be encrypted: `available()` is False and
`seal` raises VaultError, so a secret is never stored in the clear.

Honest limit: whoever has the `.env` and the database together (access to the server) can decrypt. The backup alone
or a stolen SD card is not enough. The web service only ever seals; opening (`unseal`) is for the broker that later
connects to a device, never for a page or a route.
"""
import os


class VaultError(Exception):
    """No usable master key, or the text does not open with it."""


def _fernet():
    key = os.environ.get("HUB_VAULT_KEY", "").strip()
    if not key:
        raise VaultError("no key")
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode())
    except Exception as exc:   # missing package or a malformed key
        raise VaultError("bad key") from exc


def available() -> bool:
    try:
        _fernet()
    except VaultError:
        return False
    return True


def seal(text: str) -> str:
    """The encrypted form of `text` (ASCII, safe for a TEXT column)."""
    return _fernet().encrypt(text.encode("utf-8")).decode("ascii")


def unseal(token: str) -> str:
    """The clear text of a sealed value. Only for the broker."""
    from cryptography.fernet import InvalidToken
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise VaultError("wrong key") from exc
