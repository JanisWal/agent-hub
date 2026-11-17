"""Encryption of secrets kept in the database (device keys and passwords; Janis, 17.11.2026: asymmetric).

age, through the package `pyrage` (no own cryptography). The web service has only the PUBLIC key (`HUB_VAULT_PUBLIC`,
an "age1…" recipient from the .env): it can lock a secret away but never open it again, not even by mistake. The
private key (`HUB_VAULT_IDENTITY`) is only in the broker (broker/broker.py), the one part that uses the secrets. So a
hole in the web service, a copy of the database or a backup gives no secret; only the broker's key and the database
together do. Without a valid public key nothing is stored (`available()` False, `seal` raises VaultError): never in
the clear. Before 17.11.2026 this was Fernet (symmetric); the table was still empty then, nothing was converted.

There is no `unseal` here on purpose (CLAUDE.md: secrets are never readable, only replaced or removed).
"""
import base64
import os

PREFIX = "age:"


class VaultError(Exception):
    """No usable public key."""


def _recipient():
    text = os.environ.get("HUB_VAULT_PUBLIC", "").strip()
    if not text:
        raise VaultError("no key")
    try:
        import pyrage
        return pyrage.x25519.Recipient.from_str(text)
    except Exception as exc:   # missing package or a malformed key
        raise VaultError("bad key") from exc


def available() -> bool:
    try:
        _recipient()
    except VaultError:
        return False
    return True


def seal(text: str) -> str:
    """The encrypted form of `text`: "age:" and the base64 of an age file (ASCII, safe for a TEXT column)."""
    import pyrage
    return PREFIX + base64.b64encode(pyrage.encrypt(text.encode("utf-8"), [_recipient()])).decode("ascii")
