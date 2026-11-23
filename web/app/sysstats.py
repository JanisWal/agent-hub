"""Live numbers of the server for the administration page (Janis, 23.11.2026): memory, processor, temperature, disk.

Standard library only: /proc and /sys of the host (the web container sees the host's numbers there, it has no limit of
its own), `shutil` for the disk. Every function returns plain numbers or None; the page formats them
(systempage.meters). Nothing here names a process or a path to the outside.
"""
import os
import shutil
import threading
import time

DISK_PATH = "/data"          # the data disk of the hub (database, files, backups' source)
_lock = threading.Lock()
_last: tuple | None = None   # (monotonic time, total ticks, idle ticks, percent) of the last processor reading


def memory(text: str | None = None) -> dict:
    """{"total_mb", "free_mb", "used_pct"}; free is `MemAvailable` (what programs can still get, the cache that can
    be given back included), `MemFree` on a kernel without it. `text`: the content of /proc/meminfo (tests)."""
    if text is None:
        with open("/proc/meminfo", encoding="ascii") as handle:
            text = handle.read()
    kb = {}
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        if rest.split():
            kb[name] = int(rest.split()[0])
    total = kb.get("MemTotal", 0)
    free = kb.get("MemAvailable", kb.get("MemFree", 0))
    return {"total_mb": total // 1024, "free_mb": free // 1024,
            "used_pct": round(100 * (total - free) / total) if total else 0}


def _ticks() -> tuple[int, int]:
    """(all ticks, idle ticks) of all processors since boot, from the first line of /proc/stat."""
    with open("/proc/stat", encoding="ascii") as handle:
        fields = [int(x) for x in handle.readline().split()[1:]]
    return sum(fields[:8]), fields[3] + fields[4]   # idle + iowait are not work


def cpu(read=_ticks, pause: float = 0.25) -> dict:
    """{"used_pct", "cores"}: the share of work over the time since the last reading. Several viewers share one
    reading (within a second nothing is read again); a first reading, or one older than ten seconds, waits `pause`
    seconds for a second sample, so the number always covers a short span."""
    global _last
    with _lock:
        now = time.monotonic()
        if _last is not None and now - _last[0] < 1:
            return {"used_pct": _last[3], "cores": os.cpu_count() or 1}
        total, idle = read()
        if _last is None or now - _last[0] > 10:
            before = (total, idle)
            time.sleep(pause)
            now = time.monotonic()
            total, idle = read()
        else:
            before = (_last[1], _last[2])
        span = total - before[0]
        used = round(100 * (span - (idle - before[1])) / span) if span > 0 else (_last[3] if _last else 0)
        used = max(0, min(100, used))
        _last = (now, total, idle, used)
        return {"used_pct": used, "cores": os.cpu_count() or 1}


def temperature(path: str = "/sys/class/thermal/thermal_zone0/temp") -> float | None:
    """The processor's temperature in °C, None where the machine does not tell."""
    try:
        with open(path, encoding="ascii") as handle:
            return int(handle.read().strip()) / 1000
    except (OSError, ValueError):
        return None


def disk(path: str = DISK_PATH) -> dict:
    """{"total_gb", "free_gb", "used_pct"} of the disk the path lies on."""
    usage = shutil.disk_usage(path)
    return {"total_gb": usage.total / 1e9, "free_gb": usage.free / 1e9,
            "used_pct": round(100 * (usage.total - usage.free) / usage.total) if usage.total else 0}


def read() -> dict:
    """All four at once: {"memory", "cpu", "temp_c", "disk"} ("disk" None when the path is not there)."""
    try:
        disk_now = disk()
    except OSError:
        disk_now = None
    return {"memory": memory(), "cpu": cpu(), "temp_c": temperature(), "disk": disk_now}
