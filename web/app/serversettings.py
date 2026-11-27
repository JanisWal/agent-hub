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
# What a small server needs and a big one does not (Janis, 21.11.2026: "wherever we limit ourselves because it runs on a
# Pi, there is a setting"): the choices of the owner, each with its default (the values the Pi has used so far).
CHOICES = {
    "ai_rest": (0, 15, 30, 60, 120, 300),            # minutes a used-up AI goes to the end of the order (aichoice.rest)
    "export_mb": (10, 25, 50, 100, 250, 500),        # the largest ZIP of a project's code (exports.py)
    # memory of one AI run's container (runner/launcher.py); 384 since 22.11.2026: on a 1 GB server 480 left web and
    # runner too little, and the memory card stalled the whole server (PROJEKT.md 11)
    "run_memory_mb": (384, 480, 768, 1024, 2048, 4096, 8192),
    "run_cpus": (1, 2, 4, 8),                        # processor cores of one run
    "run_pids": (256, 512, 1024, 4096),              # processes and threads of one run (a browser needs many)
    # No fixed time for work that moves on (Janis, 22.11.2026: a big task gets the time it needs): a run ends when its
    # AI wrote nothing for this long, or after the longest time, which is only a net against a run that never ends.
    "run_silence_minutes": (10, 15, 30, 60),
    "run_max_hours": (1, 2, 4, 8, 12),
    "test_minutes": (5, 10, 20, 40),                 # the project's own tests (hub-test.sh, no AI)
    "chat_minutes": (3, 5, 10, 20),                  # time of one chat answer
    "view_mb": (200, 500, 1000, 5000),               # the user's files copied for one job (runner/view.py)
    "agent_browser": (0, 1),                         # the agents' test browser (runner/hub_browser.js)
    "backup_hour": tuple(range(24)),                 # the hour of the nightly backup, server time (backups.py, 27.11.2026)
}
AI_REST, EXPORT_MB = CHOICES["ai_rest"], CHOICES["export_mb"]
DEFAULTS = {"upload_parallel": 6, "upload_request_mb": 32, "ai_parallel": 1, "ai_rest": 30, "export_mb": 25,
            "run_memory_mb": 480, "run_cpus": 2, "run_pids": 512, "run_silence_minutes": 15, "run_max_hours": 4, "test_minutes": 10, "chat_minutes": 3, "view_mb": 200,
            "agent_browser": 1, "backup_hour": 3}


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


def get(key: str) -> int:
    """One of the owner's choices (CHOICES), its default until he chose or when the stored value is no choice."""
    value = _get(key)
    return value if value in CHOICES[key] else DEFAULTS[key]


def ai_rest() -> int:
    """Minutes an AI with a used-up quota rests (0 = never: it is tried first again at once)."""
    return get("ai_rest")


def export_mb() -> int:
    return get("export_mb")


def chat_seconds() -> int:
    return get("chat_minutes") * 60


def sort_seconds() -> int:
    """The time of a plan for the folders (autofolders.py): it goes through all files of a project, so three times a
    chat answer; below the hour a run's ticket counts (runner/tokens.TICKET_AGE)."""
    return min(chat_seconds() * 3, 3000)


def run_limits() -> dict:
    """What every job tells the runner about the container it starts (checked there again, runner/launcher.py): an
    agent run ends after `silence_seconds` without output or after `max_seconds` of work (a paused run's time does
    not count); a chat answer after `chat_seconds`; the project's tests after `test_seconds`."""
    return {"memory_mb": get("run_memory_mb"), "cpus": get("run_cpus"), "pids": get("run_pids"),
            "silence_seconds": get("run_silence_minutes") * 60, "max_seconds": get("run_max_hours") * 3600,
            "chat_seconds": chat_seconds() + 20, "test_seconds": get("test_minutes") * 60,
            "view_mb": get("view_mb"), "browser": get("agent_browser")}


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
