"""Limits wrong password guesses per client IP (standard library and SQLite only).

Only the IP is counted, never the e-mail address, so nobody can lock the owner out by guessing
at his address. Rule: MAX_FAILURES wrong passwords within WINDOW_SECONDS lock that IP for
LOCK_SECONDS. Login and the password check before deleting a project share one counter.
A correct password does not reset the counter: otherwise an attacker with an account of his
own could log in between guesses. The counter simply runs out with the window.
"""
import os
import socket
import time

from fastapi import Request

from . import db

MAX_FAILURES = 10            # generous: a real user may mistype many times
WINDOW_SECONDS = 30 * 60     # failures older than this are forgotten
LOCK_SECONDS = 60 * 60       # how long an IP stays locked

# The functions below take a key: the IP for passwords, "forgot:" + IP for requests of a reset mail
# (each kind has its own counter).


# The tunnel's host name (HUB_TRUSTED_PROXY, new installs: "tunnel", 27.11.2026). Where the hub's port is open in the
# home network, anybody there could send CF-Connecting-IP himself and dodge the lock with a new made-up address for
# every guess; then the header counts only on requests from the tunnel's container. Empty (the live Pi, whose port
# is only open on the Pi itself): the header always counts, as before.
TRUSTED_PROXY = os.environ.get("HUB_TRUSTED_PROXY", "").strip()
# The gate in front of the web service (28.11.2026, gate/nginx.conf): every request comes from it, so it names the real
# peer (the tunnel or a visitor in the home network) in X-Hub-Peer, set by itself every time. Believed only from the gate.
GATE = os.environ.get("HUB_GATE", "").strip()
_found: dict[str, tuple[str | None, float]] = {}


def _address_of(name: str) -> str | None:
    """The address of a container name (cached a minute: a container made again gets a new one)."""
    now = time.time()
    cached = _found.get(name)
    if cached is None or now - cached[1] > 60:
        try:
            cached = (socket.gethostbyname(name), now)
        except OSError:
            cached = (None, now)
        _found[name] = cached
    return cached[0]


def peer(request: Request) -> str:
    """Who opened the connection: behind the gate the peer it names, else the connection's own address."""
    host = request.client.host if request.client else ""
    if GATE and host and host == _address_of(GATE):
        named = request.headers.get("x-hub-peer", "").strip()
        if named:
            return named
    return host or "unknown"


def via_proxy(request: Request) -> bool:
    """Did this request come from the tunnel (so its forwarded headers may be believed)?"""
    if not request.headers.get("cf-connecting-ip"):
        return False
    if not TRUSTED_PROXY:
        return True
    return peer(request) == _address_of(TRUSTED_PROXY)


def client_ip(request: Request) -> str:
    """The visitor's IP. Behind the Cloudflare tunnel the real address is in CF-Connecting-IP
    (Cloudflare sets it itself; believed only from the tunnel, `via_proxy`)."""
    forwarded = request.headers.get("cf-connecting-ip", "").strip()
    if forwarded and via_proxy(request):
        return forwarded
    return peer(request)


def seconds_locked(ip: str, now: float | None = None) -> int:
    """Seconds this IP stays locked, 0 if it may try."""
    now = int(time.time() if now is None else now)
    with db.connect() as conn:
        row = conn.execute("SELECT locked_until FROM login_attempts WHERE ip = ?", (ip,)).fetchone()
    return max(0, row["locked_until"] - now) if row else 0


def record_failure(ip: str, now: float | None = None) -> None:
    """Count one wrong password; lock the IP when the limit is reached."""
    now = int(time.time() if now is None else now)
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM login_attempts WHERE locked_until <= ? AND window_start <= ?",
            (now, now - WINDOW_SECONDS),
        )
        row = conn.execute(
            "SELECT failures, window_start FROM login_attempts WHERE ip = ?", (ip,)
        ).fetchone()
        if row is None or now - row["window_start"] > WINDOW_SECONDS:
            failures, start = 1, now
        else:
            failures, start = row["failures"] + 1, row["window_start"]
        locked_until = now + LOCK_SECONDS if failures >= MAX_FAILURES else 0
        conn.execute(
            "INSERT INTO login_attempts (ip, failures, window_start, locked_until) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(ip) DO UPDATE SET failures = excluded.failures, "
            "window_start = excluded.window_start, locked_until = excluded.locked_until",
            (ip, failures, start, locked_until),
        )


def minutes(seconds: int) -> int:
    """Whole minutes for the message, rounded up (at least 1)."""
    return max(1, -(-seconds // 60))
