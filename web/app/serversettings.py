"""Settings of the whole server (not of one user), set by the owner on the administration page.

Only the upload so far (Janis, 13.11.2026): how many requests go at once and how big one may be. The right values
depend on the tunnel in front of the server: Cloudflare's free and pro plans take at most 100 MB per request,
business 200 MB, enterprise 500 MB; the choices stay below those with room to spare. Fixed choices instead of free
numbers, so nothing can be set that breaks uploads. Standard library only.
"""
from . import db

PARALLEL = (1, 2, 4, 6, 8, 12)            # requests on their way at the same time
REQUEST_MB = (16, 32, 64, 90, 190, 490)   # largest request in MB
DEFAULTS = {"upload_parallel": 6, "upload_request_mb": 32}


def _get(key: str) -> int:
    with db.connect() as conn:
        row = conn.execute("SELECT value FROM server_settings WHERE key = ?", (key,)).fetchone()
    return int(row[0]) if row else DEFAULTS[key]


def upload() -> tuple[int, int]:
    """(parallel, request_mb) for uploads; the defaults until the owner chose something."""
    parallel, request_mb = _get("upload_parallel"), _get("upload_request_mb")
    return (parallel if parallel in PARALLEL else DEFAULTS["upload_parallel"],
            request_mb if request_mb in REQUEST_MB else DEFAULTS["upload_request_mb"])


def set_upload(parallel: int, request_mb: int) -> None:
    """Keep the owner's choice. Raises ValueError for a value that is not one of the choices."""
    if parallel not in PARALLEL or request_mb not in REQUEST_MB:
        raise ValueError("not a choice")
    with db.connect() as conn:
        conn.executemany("INSERT INTO server_settings (key, value) VALUES (?, ?)"
                         " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                         (("upload_parallel", str(parallel)), ("upload_request_mb", str(request_mb))))
