"""Start of a ChatGPT run inside its container (runner/Dockerfile.codex, 21.11.2026). Standard library only, runs as the
run user.

The launcher passes only checked values (model, level, kind of job, time limit) and HUB_AUTH, the run's auth.json
(runner/codex.run_auth: the ticket in a JWT-shaped wrapper, no usable refresh token). This script writes it and Codex's
settings into the home folder in memory and runs `codex exec --json` with the package from stdin. Every request of Codex
goes to the egress gateway (port 3133): the model calls through `chatgpt_base_url`, sign-in and refresh through
CODEX_AUTHAPI_BASE_URL (the gateway refuses those). Output like runner/vibe_entry.py: {"thought": ...} and once
{"outside": true} while it runs, then ONE last line {"ok", "text", "tokens_in", "tokens_out", "outcome", "error"}.
Job "models": `codex debug models` (the account's model list as Codex asks for it), printed as {"models": [...]}.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

GATEWAY = os.environ.get("HUB_GATEWAY", "http://egress:3133")
HOME = Path(os.environ.get("HOME", "/home/codex"))
JOBS = ("chat-all", "chat-apart", "chat-brief", "run", "run-brief", "models")
LEVELS = ("low", "medium", "high", "xhigh", "max", "none", "minimal")
FEATURES_OFF = ("plugins", "apps", "remote_plugin", "plugin_discovery_prefetch", "browser_use", "browser_use_external",
                "in_app_browser", "computer_use", "in_app_updates", "daemon_auto_start")
OUTSIDE = {"chat-all": ("web_search", "command_execution"), "chat-apart": ("web_search",),
           "run": ("web_search", "command_execution")}


def config(model: str, effort: str, job: str, api: bool = False) -> str:
    """Codex's settings for one job: our gateway, no updates, no telemetry, the file store for the sign-in."""
    brief = job in ("chat-brief", "run-brief")
    lines = [
        f'model = "{model}"' if model else "",
        f'model_reasoning_effort = "{effort}"' if effort else "",
        f'chatgpt_base_url = "{GATEWAY}/backend-api/"',
        'model_provider = "hub"',
        'cli_auth_credentials_store = "file"',
        'approval_policy = "never"',
        f'sandbox_mode = "{"read-only" if brief else "danger-full-access"}"',
        "check_for_update_on_startup = false",
        "hide_agent_reasoning = false",
        "",
        "[analytics]",
        "enabled = false",
        "",
        # Nothing but the model and its tools: no plugins, apps, browser or computer use (they call other addresses)
        "[features]",
        *(f"{name} = false" for name in FEATURES_OFF),
        "",
        "[tools]",
        f"web_search = {'false' if brief else 'true'}",
        "",
        # The ChatGPT sign-in, but plain requests to our gateway instead of a WebSocket (it passes one request on); with
        # the user's API key (HUB_KEY: its ticket) the OpenAI API behind the same gateway
        "[model_providers.hub]",
        'name = "ChatGPT"',
        f'base_url = "{GATEWAY}/v1"' if api else f'base_url = "{GATEWAY}/backend-api/codex"',
        'wire_api = "responses"',
        'env_key = "HUB_KEY"' if api else "requires_openai_auth = true",
        "supports_websockets = false",
    ]
    return "\n".join(line for line in lines if line is not None) + "\n"


def summary(events: list[dict], code: int, stderr: str) -> dict:
    text, tokens_in, tokens_out, error, outcome = "", 0, 0, "", "finished"
    for event in events:
        kind = event.get("type")
        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        if kind == "item.completed" and item.get("type") == "agent_message" and isinstance(item.get("text"), str):
            text = item["text"]
        elif kind == "turn.completed":
            usage = event.get("usage") or {}
            tokens_in += int(usage.get("input_tokens") or 0)
            tokens_out += int(usage.get("output_tokens") or 0)
        elif kind in ("turn.failed", "error"):
            detail = event.get("error") if isinstance(event.get("error"), dict) else event
            error = str(detail.get("message") or "")[:500]
            outcome = "failed"
    if code and not error:
        error, outcome = (stderr.strip()[-500:] or f"exit code {code}"), "failed"
    if re.search(r"\b403\b|not (?:included|available) (?:in|on) your plan|upgrade your plan", error, re.I):
        outcome = "plan"
    return {"ok": outcome == "finished" and bool(text.strip()), "text": text, "tokens_in": tokens_in,
            "tokens_out": tokens_out, "outcome": outcome, "error": error}


def say(data: dict) -> None:
    print(json.dumps(data), flush=True)


def main() -> int:
    model, effort, job = os.environ.get("HUB_MODEL", ""), os.environ.get("HUB_EFFORT", ""), os.environ.get("HUB_JOB", "")
    seconds = os.environ.get("HUB_SECONDS", "180")
    auth, key = os.environ.get("HUB_AUTH", ""), os.environ.get("HUB_KEY", "")
    if ((model and not re.fullmatch(r"[a-z][a-z0-9.-]{0,47}", model)) or (effort and effort not in LEVELS)
            or job not in JOBS or not seconds.isdigit() or not (auth.startswith("{") or key.startswith("hubrun-"))):
        say({"ok": False, "text": "", "tokens_in": 0, "tokens_out": 0, "outcome": "usage_error", "error": "bad settings"})
        return 0
    codex_home = HOME / ".codex"
    codex_home.mkdir(parents=True, exist_ok=True)
    if auth:
        (codex_home / "auth.json").write_text(auth)
    (codex_home / "config.toml").write_text(config(model, effort, job, api=bool(key)))
    env = dict(os.environ, CODEX_HOME=str(codex_home), CODEX_AUTHAPI_BASE_URL=f"{GATEWAY}/auth")
    env.pop("HUB_AUTH", None)
    if job == "models":
        done = subprocess.run(["codex", "debug", "models"], env=env, capture_output=True, text=True,
                              timeout=int(seconds), stdin=subprocess.DEVNULL)
        try:
            data = json.loads(done.stdout)
            say({"models": data.get("models", data) if isinstance(data, dict) else data})
        except ValueError:
            say({"models": [], "error": (done.stderr or "").strip()[-300:]})
        return 0
    workdir = Path("/work") if job == "run" else HOME / "scratch"
    workdir.mkdir(parents=True, exist_ok=True)
    command = ["codex", "exec", "--json", "--skip-git-repo-check", "--ephemeral", "--color", "never", "-C", str(workdir)]
    if job not in ("chat-brief", "run-brief"):
        command.append("--dangerously-bypass-approvals-and-sandbox")   # our container is the sandbox
    command.append("-")
    events, went_out = [], False
    with open(HOME / "stderr.txt", "w+") as errors:
        proc = subprocess.Popen(command, stdin=sys.stdin, stdout=subprocess.PIPE, stderr=errors, text=True, env=env)
        try:
            for line in proc.stdout:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                events.append(event)
                item = event.get("item") if isinstance(event.get("item"), dict) else {}
                if event.get("type") == "item.completed" and item.get("type") == "reasoning" and item.get("text"):
                    say({"thought": str(item["text"]).strip()})
                if not went_out and item.get("type") in OUTSIDE.get(job, ()):
                    went_out = True
                    say({"outside": True})
            code = proc.wait(timeout=int(seconds))
        except subprocess.TimeoutExpired:
            proc.kill()
            code = -9
            events.append({"type": "error", "message": "time limit"})
        errors.seek(0)
        stderr = errors.read()
    say(summary(events, code, stderr))
    return 0


if __name__ == "__main__":
    sys.exit(main())
