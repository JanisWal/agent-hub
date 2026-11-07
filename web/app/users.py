"""Users and sessions, stored in SQLite. Standard library only."""
import hashlib
import hmac
import secrets
import sqlite3
import time
from dataclasses import dataclass

from . import db

SESSION_SECONDS = 14 * 24 * 3600
MIN_PASSWORD_LENGTH = 8
MAX_DISPLAY_NAME = 40

# scrypt cost parameters (about 16 MiB RAM per hash, fine for a Pi 4)
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1


@dataclass
class User:
    id: int
    email: str
    is_admin: bool
    created_at: int
    display_name: str | None = None
    language: str = "de"
    had_project: bool = False

    @property
    def name(self) -> str:
        """Name to show in the interface: chosen name, else the part before the @."""
        return self.display_name or self.email.split("@")[0]


def _hash_password(password: str) -> str:
    """Return 'scrypt$n$r$p$salt$hash' with a fresh random salt."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    _, n, r, p, salt, digest = stored.split("$")
    candidate = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p)
    )
    return hmac.compare_digest(candidate, bytes.fromhex(digest))


# Used to spend the same time on unknown e-mails as on wrong passwords.
_DUMMY_HASH = _hash_password("dummy")


def _normalize(email: str) -> str:
    return email.strip().lower()


def _to_user(row: sqlite3.Row) -> User:
    return User(
        row["id"], row["email"], bool(row["is_admin"]), row["created_at"],
        row["display_name"], row["language"], bool(row["had_project"]),
    )


def create_user(email: str, password: str, is_admin: bool = False) -> User:
    """Create a user. Raises ValueError for bad input or a duplicate e-mail."""
    email = _normalize(email)
    if "@" not in email:
        raise ValueError("Ungültige E-Mail-Adresse")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Passwort zu kurz (mindestens {MIN_PASSWORD_LENGTH} Zeichen)")
    with db.connect() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
                (email, _hash_password(password), int(is_admin), int(time.time())),
            )
        except sqlite3.IntegrityError:
            raise ValueError("E-Mail-Adresse ist schon vergeben") from None
        row = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _to_user(row)


def check_login(email: str, password: str) -> User | None:
    """Return the user if e-mail and password match, else None."""
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (_normalize(email),)).fetchone()
    if row is None:
        _verify_password(password, _DUMMY_HASH)
        return None
    return _to_user(row) if _verify_password(password, row["password_hash"]) else None


def verify_password(user_id: int, password: str) -> bool:
    """Check a password for an already logged-in user (e.g. before deleting)."""
    with db.connect() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    return row is not None and _verify_password(password, row["password_hash"])


def set_profile(user_id: int, display_name: str, language: str) -> None:
    """Store display name (empty = use e-mail) and language. Raises ValueError if too long."""
    display_name = display_name.strip()
    if len(display_name) > MAX_DISPLAY_NAME:
        raise ValueError("Nutzername zu lang")
    with db.connect() as conn:
        conn.execute(
            "UPDATE users SET display_name = ?, language = ? WHERE id = ?",
            (display_name or None, language, user_id),
        )


def create_session(user_id: int) -> str:
    """Store a new session for 14 days and return its random token."""
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    with db.connect() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        conn.execute(
            "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user_id, now + SESSION_SECONDS),
        )
    return token


def get_user(token: str | None) -> User | None:
    """Return the user of a valid, unexpired session token, else None."""
    if not token:
        return None
    with db.connect() as conn:
        row = conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id"
            " WHERE s.token = ? AND s.expires_at > ?",
            (token, int(time.time())),
        ).fetchone()
    return _to_user(row) if row else None


def delete_session(token: str) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
