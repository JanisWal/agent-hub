"""Users, roles and sessions, stored in SQLite. Standard library only.

Roles: `owner` (exactly one), `admin`, `user`. Rules in short (see `can_manage`):
the owner manages everybody except himself, an admin manages normal users only, a user nobody.
Only the owner makes or removes admins, and only he can hand the ownership to somebody else
(`transfer_owner`, he becomes an admin then). Nobody is the owner for good: the role moves, but
there is never more than one owner (checked in `create_user` and `transfer_owner`, and the
database refuses a second one too). Accounts are never created by the visitor himself.
"""
import hashlib
import hmac
import secrets
import sqlite3
import time
from dataclasses import dataclass

from . import db, files

SESSION_SECONDS = 14 * 24 * 3600
MIN_PASSWORD_LENGTH = 6      # floor for every password, also a start password given by an admin
MIN_DIGITS = 2               # extra rule for passwords people choose themselves (password_problem)
MAX_DISPLAY_NAME = 40
MAX_EMAIL_LENGTH = 254       # the longest address that exists (RFC 5321)
ROLES = ("owner", "admin", "user")

# scrypt cost parameters (about 16 MiB RAM per hash, fine for a Pi 4)
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1


class UserError(ValueError):
    """Bad input. `code` names the problem so the interface can say it in the user's language:
    email, taken, short, policy, same, wrong_password, not_found, owner_exists, not_ready."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


@dataclass
class User:
    id: int
    email: str
    is_admin: bool          # owner or admin
    created_at: int
    display_name: str | None = None
    language: str = "de"
    had_project: bool = False
    role: str = "user"
    must_change: bool = False   # logged in with a start password: has to choose an own one first
    theme: str = "light"        # "light" or "dark": the style he used last (mails follow it)

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
    role = row["role"]
    return User(
        row["id"], row["email"], role != "user", row["created_at"],
        row["display_name"], row["language"], bool(row["had_project"]),
        role, bool(row["must_change_password"]), row["theme"],
    )


def password_problem(password: str) -> str | None:
    """Rules for a password somebody chooses himself: at least 6 characters with upper and lower
    case letters, one special character and two digits. Returns None if fine, else the code
    "short" or "policy" (the interface shows the rule text for both)."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return "short"
    special = any(not c.isalnum() and not c.isspace() for c in password)
    digits = sum(c.isdigit() for c in password)
    if not (any(c.isupper() for c in password) and any(c.islower() for c in password)
            and special and digits >= MIN_DIGITS):
        return "policy"
    return None


def create_user(email: str, password: str, role: str = "user", must_change: bool = False) -> User:
    """Create a user. Raises UserError for bad input or a duplicate e-mail.

    Only the length is checked here (also for start passwords); people choosing their own
    password go through `password_problem` first.
    """
    email = _normalize(email)
    if "@" not in email or len(email) > MAX_EMAIL_LENGTH:
        raise UserError("email", "Ungültige E-Mail-Adresse")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise UserError("short", f"Passwort zu kurz (mindestens {MIN_PASSWORD_LENGTH} Zeichen)")
    if role not in ROLES:
        raise ValueError(f"unknown role {role}")
    if role == "owner" and owner_exists():
        raise UserError("owner_exists", "Es gibt schon einen Owner")
    with db.connect() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, role, must_change_password, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (email, _hash_password(password), role, int(must_change), int(time.time())),
            )
        except sqlite3.IntegrityError:
            raise UserError("taken", "E-Mail-Adresse ist schon vergeben") from None
        row = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _to_user(row)


def owner_exists() -> bool:
    with db.connect() as conn:
        return conn.execute("SELECT 1 FROM users WHERE role = 'owner'").fetchone() is not None


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


THEMES = ("light", "dark")


def set_theme(user_id: int, theme: str) -> None:
    """Remember which style (light or dark) the user sees now. Raises ValueError for anything else."""
    if theme not in THEMES:
        raise ValueError(f"unknown theme {theme}")
    with db.connect() as conn:
        conn.execute("UPDATE users SET theme = ? WHERE id = ?", (theme, user_id))


# ----- managing users -----

def get_by_id(user_id: int) -> User | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _to_user(row) if row else None


def can_manage(actor: User, target: User) -> bool:
    """May `actor` reset the password of or delete `target`? Nobody touches the owner."""
    if target.role == "owner" or target.id == actor.id:
        return False
    return actor.role == "owner" or (actor.role == "admin" and target.role == "user")


def list_users(actor: User) -> list[User]:
    """All users, owner first. Only for owner and admins (PermissionError otherwise)."""
    if not actor.is_admin:
        raise PermissionError
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY CASE role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, id"
        ).fetchall()
    return [_to_user(row) for row in rows]


def add_user(actor: User, email: str, start_password: str) -> User:
    """Owner or admin creates a normal user with a start password that must be changed at once."""
    if not actor.is_admin:
        raise PermissionError
    return create_user(email, start_password, role="user", must_change=True)


def _managed(actor: User, user_id: int) -> User:
    target = get_by_id(user_id)
    if target is None:
        raise UserError("not_found")
    if not can_manage(actor, target):
        raise PermissionError
    return target


def set_password(user_id: int, new_password: str, must_change: bool = False, keep_token: str | None = None) -> None:
    """Store a new password, end all sessions of that user (except the one with the cookie value
    `keep_token`) and cancel reset links that are still open. Checks only the length: callers
    that let people choose a password check `password_problem` first."""
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise UserError("short")
    with db.connect() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, must_change_password = ? WHERE id = ?",
            (_hash_password(new_password), int(must_change), user_id),
        )
        conn.execute(
            "DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
            (user_id, hash_token(keep_token) if keep_token else ""),
        )
        conn.execute("DELETE FROM password_resets WHERE user_id = ?", (user_id,))


def reset_password(actor: User, user_id: int, start_password: str) -> None:
    """Give a user a new start password (he must change it at the next login)."""
    target = _managed(actor, user_id)
    set_password(target.id, start_password, must_change=True)


def delete_user(actor: User, user_id: int) -> None:
    """Delete an account with its projects, board items and sessions (cascade)."""
    target = _managed(actor, user_id)
    with db.connect() as conn:
        # The cascade removes his rows, but not his saved Claude login on the runner's disk: queue the
        # deletion of that folder (claude_link.pending_wipes), in the same transaction as the deletion.
        conn.execute("INSERT OR IGNORE INTO claude_wipes (user_id, created_at) VALUES (?, strftime('%s','now'))",
                     (target.id,))
        conn.execute("DELETE FROM users WHERE id = ?", (target.id,))
    files.remove_orphans()   # the stored files of his projects


def set_admin(actor: User, user_id: int, make_admin: bool) -> None:
    """Only the owner makes or removes admins; the owner himself cannot be changed."""
    if actor.role != "owner":
        raise PermissionError
    target = get_by_id(user_id)
    if target is None:
        raise UserError("not_found")
    if target.role == "owner":
        raise PermissionError
    role = "admin" if make_admin else "user"
    with db.connect() as conn:
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, target.id))


def transfer_owner(actor: User, user_id: int) -> None:
    """The owner hands the ownership to another account and becomes an admin himself.

    Both changes happen in one transaction, so there is never no owner and never two. Only the
    owner may do it (PermissionError, also for himself as target). The other account must have
    chosen its own password already (UserError "not_ready"), otherwise the ownership could end up
    with somebody who cannot log in. The caller asks for the owner's password first.
    """
    if actor.role != "owner":
        raise PermissionError
    target = get_by_id(user_id)
    if target is None:
        raise UserError("not_found")
    if target.id == actor.id:
        raise PermissionError
    if target.must_change:
        raise UserError("not_ready")
    with db.connect() as conn:
        # step down first, so that the unique index never sees two owners
        stepped_down = conn.execute(
            "UPDATE users SET role = 'admin' WHERE id = ? AND role = 'owner'", (actor.id,)
        ).rowcount
        if stepped_down != 1:  # the actor object was out of date
            raise PermissionError
        conn.execute("UPDATE users SET role = 'owner' WHERE id = ?", (target.id,))


def change_own_password(user: User, old_password: str, new_password: str, keep_token: str | None = None) -> None:
    """The user chooses a new password. Raises UserError: wrong_password, short, policy, same.

    The old password is asked for, except from somebody who has just logged in with a start
    password (`must_change`): he proved it a moment ago, and it is not his own anyway.
    Other sessions end; the one in `keep_token` stays.
    """
    if not user.must_change and not verify_password(user.id, old_password):
        raise UserError("wrong_password")
    problem = password_problem(new_password)
    if problem:
        raise UserError(problem)
    if verify_password(user.id, new_password):  # same as the current password
        raise UserError("same")
    set_password(user.id, new_password, must_change=False, keep_token=keep_token)


def hash_token(token: str) -> str:
    """What the database stores of a token (session cookie, reset link): its SHA-256. The tokens are
    long random strings, so a plain hash is enough, and a copy of the database holds nothing usable."""
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(user_id: int) -> str:
    """Store a new session for 14 days and return its random token (the cookie value)."""
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    with db.connect() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (hash_token(token), user_id, now + SESSION_SECONDS),
        )
    return token


def get_user(token: str | None) -> User | None:
    """Return the user of a valid, unexpired session token, else None."""
    if not token:
        return None
    with db.connect() as conn:
        row = conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id"
            " WHERE s.token_hash = ? AND s.expires_at > ?",
            (hash_token(token), int(time.time())),
        ).fetchone()
    return _to_user(row) if row else None


def delete_session(token: str) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))
