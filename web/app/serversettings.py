"""Settings of the whole server (not of one user), set by the owner on the administration page.

Only the upload so far (Janis, 13.11.2026): how many requests go at once and how big one may be. The right values
depend on the tunnel in front of the server: Cloudflare's free and pro plans take at most 100 MB per request,
business 200 MB, enterprise 500 MB; the choices stay below those with room to spare. Fixed choices instead of free
numbers, so nothing can be set that breaks uploads. Standard library only.
"""
from . import db

PARALLEL = (1, 2, 4, 6, 8, 12)            # requests on their way at the same time
# AI runs (chat answers and agent runs) at the same time (Janis, 15.11.2026): each is a container that needs a lot of
# memory, so a small server stays at one; 0 = no limit, for a server with plenty of memory.
AI_PARALLEL = (1, 2, 3, 4, 0)
REQUEST_MB = (16, 32, 64, 90, 190, 490)   # largest request in MB
# How long an AI whose quota ran out goes to the end of a user's order (aichoice.rest, 21.11.2026), in minutes.
AI_REST = (0, 15, 30, 60, 120, 300)
EXPORT_MB = (10, 25, 50, 100, 250, 500)   # the largest ZIP of a project's code (exports.py)
DEFAULTS = {"upload_parallel": 6, "upload_request_mb": 32, "ai_parallel": 1, "ai_rest": 30, "export_mb": 25}


def _get(key: str) -> int:
    with db.connect() as conn:
        row = conn.execute("SELECT value FROM server_settings WHERE key = ?", (key,)).fetchone()
    return int(row[0]) if row else DEFAULTS[key]


def upload() -> tuple[int, int]:
    """(parallel, request_mb) for uploads; the defaults until the owner chose something."""
    parallel, request_mb = _get("upload_parallel"), _get("upload_request_mb")
    return (parallel if parallel in PARALLEL else DEFAULTS["upload_parallel"],
            request_mb if request_mb in REQUEST_MB else DEFAULTS["upload_request_mb"])


def ai_parallel() -> int:
    """How many AI runs may go at the same time (0 = no limit); 1 until the owner chose something."""
    value = _get("ai_parallel")
    return value if value in AI_PARALLEL else DEFAULTS["ai_parallel"]


def ai_rest() -> int:
    """Minutes an AI with a used-up quota rests (0 = never: it is tried first again at once)."""
    value = _get("ai_rest")
    return value if value in AI_REST else DEFAULTS["ai_rest"]


def export_mb() -> int:
    value = _get("export_mb")
    return value if value in EXPORT_MB else DEFAULTS["export_mb"]


def set_choice(key: str, value: int, choices: tuple) -> None:
    """Keep one of the owner's choices. Raises ValueError for a value that is not one of them."""
    if value not in choices:
        raise ValueError("not a choice")
    with db.connect() as conn:
        conn.execute("INSERT INTO server_settings (key, value) VALUES (?, ?)"
                     " ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))


def set_ai_parallel(value: int) -> None:
    """Keep the owner's choice. Raises ValueError for a value that is not one of the choices."""
    if value not in AI_PARALLEL:
        raise ValueError("not a choice")
    with db.connect() as conn:
        conn.execute("INSERT INTO server_settings (key, value) VALUES ('ai_parallel', ?)"
                     " ON CONFLICT(key) DO UPDATE SET value = excluded.value", (str(value),))


def set_upload(parallel: int, request_mb: int) -> None:
    """Keep the owner's choice. Raises ValueError for a value that is not one of the choices."""
    if parallel not in PARALLEL or request_mb not in REQUEST_MB:
        raise ValueError("not a choice")
    with db.connect() as conn:
        conn.executemany("INSERT INTO server_settings (key, value) VALUES (?, ?)"
                         " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                         (("upload_parallel", str(parallel)), ("upload_request_mb", str(request_mb))))
