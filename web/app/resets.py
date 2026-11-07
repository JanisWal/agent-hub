"""Password reset tokens, stored in SQLite. Standard library only.

Flow: `create_token` for an e-mail address gives a random token that goes into the mail link.
Only its SHA-256 hash is stored, so a copy of the database cannot be used to reset anybody's
password. A token is valid for one hour and works once. A new request replaces older ones.
"""
import hashlib
import secrets
import time

from . import db, users

TOKEN_SECONDS = 3600
INVITE_SECONDS = 7 * 24 * 3600   # an invitation may wait in a mailbox for a while
COOLDOWN_SECONDS = 60    # a new mail for the same account earliest after this (no mail flood)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_token(email: str, valid_seconds: int = TOKEN_SECONDS) -> tuple[users.User, str] | None:
    """Make a reset token for the account with this address, valid for `valid_seconds`.

    None if there is no such account or a mail was requested less than COOLDOWN_SECONDS ago;
    the caller treats both like success so nobody can find out which addresses exist.
    """
    now = int(time.time())
    with db.connect() as conn:
        conn.execute("DELETE FROM password_resets WHERE expires_at <= ?", (now,))
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
        if row is None:
            return None
        recent = conn.execute(
            "SELECT 1 FROM password_resets WHERE user_id = ? AND created_at > ?",
            (row["id"], now - COOLDOWN_SECONDS),
        ).fetchone()
        if recent:
            return None
        token = secrets.token_urlsafe(32)
        conn.execute("DELETE FROM password_resets WHERE user_id = ?", (row["id"],))
        conn.execute(
            "INSERT INTO password_resets (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (_hash(token), row["id"], now, now + valid_seconds),
        )
    return users.get_by_id(row["id"]), token


def user_for_token(token: str) -> users.User | None:
    """The user a valid (known, unexpired) token belongs to, else None."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT user_id FROM password_resets WHERE token_hash = ? AND expires_at > ?",
            (_hash(token), int(time.time())),
        ).fetchone()
    return users.get_by_id(row["user_id"]) if row else None


def consume(token: str, new_password: str) -> bool:
    """Set a new password with a token. False if the token is unknown, expired or used.

    Raises users.UserError ("short" or "policy") if the password breaks the rules; the token
    stays valid then. On success the token is gone, all sessions of the user end and a start
    password no longer has to be changed.
    """
    user = user_for_token(token)
    if user is None:
        return False
    problem = users.password_problem(new_password)
    if problem:
        raise users.UserError(problem)
    with db.connect() as conn:
        used = conn.execute("DELETE FROM password_resets WHERE token_hash = ?", (_hash(token),)).rowcount
    if used != 1:  # somebody else used it a moment ago
        return False
    users.set_password(user.id, new_password, must_change=False)
    return True
