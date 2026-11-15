"""Start of a Mistral run inside its container (runner/Dockerfile.vibe). Standard library only, runs as the run user.

The launcher passes only checked values in the environment (model, level, kind of job, limits) and the ticket as
MISTRAL_API_KEY. This script writes Vibe's settings into the home folder in memory, runs `vibe --prompt` with the
package from stdin and prints ONE line of JSON for the runner, the same shape for every job:
    {"ok": bool, "text": str, "tokens_in": int, "tokens_out": int, "outcome": str, "error": str}

Vibe's API address is the egress gateway (the only way to Mistral; it puts the real key in). Its other addresses
(managed settings, sessions, console) point to the gateway as well, which refuses them: nothing goes to Mistral but
model calls, and no telemetry, update checks or notifications at all.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

GATEWAY = os.environ.get("HUB_GATEWAY", "http://egress:3131")
HOME = Path(os.environ.get("HOME", "/home/vibe"))
LEVELS = {"none": "off", "off": "off", "low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "max"}
# Tools per job (always by --disabled-tools: with --enabled-tools Vibe hides its deferred web tools in headless runs).
OFF_ALWAYS = ("ask_user_question", "powershell*", "git_bash*", "task")
OFF_JOB = {"chat-all": (), "chat-apart": ("web_fetch",), "run": ()}


def config(model: str, level: str) -> str:
    return f'''active_model = "hub"
enable_telemetry = false
enable_otel = false
enable_update_checks = false
enable_auto_update = false
enable_notifications = false
enable_pr_monitoring = false
show_greeting = false
enable_connectors = false
include_commit_signature = false
enable_subagents = false
enable_background_processes = false
experimental_enable_model_catalog = false
experimental_enable_registry_skills = false
vibe_base_url = "{GATEWAY}"
vibe_code_sessions_base_url = "{GATEWAY}"
console_base_url = "{GATEWAY}"

[[providers]]
name = "mistral"
api_base = "{GATEWAY}/v1"
api_key_env_var = "MISTRAL_API_KEY"
backend = "mistral"

[[models]]
name = "{model}"
provider = "mistral"
alias = "hub"
thinking = "{level}"
'''


def summary(stdout: str, export: dict, code: int) -> dict:
    """The answer text (the last message of the assistant), tokens and how the run ended."""
    text = ""
    try:
        for entry in json.loads(stdout or "[]"):
            if entry.get("type") == "message" and entry.get("role") == "assistant":
                parts = [c.get("text", "") for c in entry.get("content") or [] if c.get("type") == "text"]
                if any(p.strip() for p in parts):
                    text = "".join(parts)
    except (ValueError, AttributeError, TypeError):
        pass
    usage = export.get("usage") or {}
    outcome = str(export.get("outcome") or ("finished" if code == 0 else "failed"))
    error = export.get("error") or ""
    if not isinstance(error, str):
        error = json.dumps(error)[:500]
    return {"ok": code == 0 and outcome == "finished" and bool(text.strip()), "text": text,
            "tokens_in": int(usage.get("input_tokens") or 0), "tokens_out": int(usage.get("output_tokens") or 0),
            "outcome": outcome, "error": error[:500]}


def main() -> int:
    model, effort, job = os.environ.get("HUB_MODEL", ""), os.environ.get("HUB_EFFORT", ""), os.environ.get("HUB_JOB", "")
    turns, seconds = os.environ.get("HUB_TURNS", "12"), os.environ.get("HUB_SECONDS", "180")
    if (not re.fullmatch(r"[a-z][a-z0-9.-]{0,47}", model) or (effort and effort not in LEVELS) or job not in OFF_JOB
            or not turns.isdigit() or not seconds.isdigit()):
        print(json.dumps({"ok": False, "text": "", "tokens_in": 0, "tokens_out": 0, "outcome": "usage_error",
                          "error": "bad settings"}))
        return 0
    vibe_home = HOME / ".vibe"
    vibe_home.mkdir(parents=True, exist_ok=True)
    (vibe_home / "config.toml").write_text(config(model, LEVELS.get(effort or "off", "off")))
    workdir = Path("/work") if job == "run" else HOME / "scratch"
    workdir.mkdir(parents=True, exist_ok=True)
    out = HOME / "out"
    command = ["vibe", "-p", "--output", "json", "--auto-approve", "--trust", "--workdir", str(workdir),
               "--max-turns", turns, "--time-limit", seconds, "--output-dir", str(out)]
    for tool in OFF_ALWAYS + OFF_JOB[job]:
        command += ["--disabled-tools", tool]
    env = dict(os.environ, VIBE_HOME=str(vibe_home))
    done = subprocess.run(command, stdin=sys.stdin, capture_output=True, text=True, env=env)
    try:
        export = json.loads((out / "export.json").read_text())
    except (OSError, ValueError):
        export = {"error": (done.stderr or "").strip()[-500:]}
    print(json.dumps(summary(done.stdout, export, done.returncode)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
