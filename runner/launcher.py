"""Starts one Claude Code run in its own container and reads its answer. Standard library only.

The launcher is trusted code with access to the Docker socket, so it takes no free arguments:
`build_command` fills a fixed template with a few checked values (numbers, a model from a short
list, a folder, a ticket). The text of a task (title, reports, notes) never reaches the command line: the
prompt goes in through stdin. The run container sees exactly one folder, the work folder of this task, and
nothing else (no hub.db, .env, backups, vault, other users, no Claude login). See KONZEPT-AGENTEN.md, section 6a.

Since 14.11.2026 a run has no Claude login of its own: its home is an empty folder in memory, and instead of a
token it gets a ticket (runner/tokens.py) that only the egress gateway can turn into the user's token. Claude Code
sends every request there (ANTHROPIC_BASE_URL) and nothing else to Anthropic (no telemetry, no update checks).
"""
import json
import os
import re
import sys
from pathlib import Path

# Models and effort levels are a list of the hub (web/app/catalog.py) that can change without a code change, and
# the hub checks every choice against it. Here they only have to be safe as one argument each: a fixed pattern,
# lower case, never starting with "-" (the same patterns as catalog.py).
_MODEL = re.compile(r"[a-z][a-z0-9.-]{0,47}")
_EFFORT = re.compile(r"[a-z]{1,12}")
ROLES = ("chef", "programmer", "tester", "reviewer")   # same as web/app/workflow.py; the chef also documents
RESULTS = {
    "programmer": ("done", "failed"),
    "tester": ("pass", "fail", "not_testable", "failed"),
    "reviewer": ("ok", "objections", "failed"),
    "chef": ("done", "failed"),
}
IMAGE = "agent-hub-agent"         # built from runner/Dockerfile
NETWORK = "agent-hub-agents"      # separate from the "web" network: a run cannot reach the hub
UID_BASE = 10000                  # run user = UID_BASE + user_id, never root
MAX_REPORT = 20000
# The agent network has no route to the outside: everything goes through the egress proxy (runner/egress.py).
WEB_PROXY = "http://egress:3128"   # any public host on 443, never the home network or the Pi itself
API_PROXY = "http://egress:3129"   # only Anthropic (sign-ins)
GATEWAY = "http://egress:3130"     # the Claude API with the user's token put in by the proxy (runner/egress.py)
_TICKET = re.compile(r"hubrun-[A-Za-z0-9_-]{43}")   # runner/tokens.py
# What the manager chat may do: tools, proxy and steps (model turns) per question.
CHAT_MODES = {
    # The manager chat (Janis, 07.11.2026/08.11.2026): web search, reading pages and code with internet, always;
    # Claude uses them only when needed. The way out is the public-only proxy: the open internet, never the home
    # network. The user's Claude token is not in the run (only a ticket that works nowhere else and ends with the
    # run), so code can not send it out (14.11.2026; before, code could read the login). The Pi, the hub and the home
    # network stay out of reach.
    "all": {"tools": ("WebSearch", "WebFetch", "Bash"), "proxy": WEB_PROXY, "turns": 12},
    # Web and code apart (switch off): the web search runs on Anthropic's side, the container only reaches
    # Anthropic, so code has no internet and nothing it reads can leave. No WebFetch: it would need the open web.
    "apart": {"tools": ("WebSearch", "Bash"), "proxy": API_PROXY, "turns": 10},
}
# Restart and shutdown of the Pi (owner's request, see web/app/power.py). The host is reached through the
# Docker socket: a short-lived privileged container joins the host's namespaces and runs `systemctl`.
# Only these two fixed commands exist; nothing from the request reaches the command line but the choice.
POWER_COMMANDS = {
    "reboot": ["systemctl", "--no-block", "reboot"],
    "poweroff": ["systemctl", "--no-block", "poweroff"],
    # The unit made by deploy/setup-backup.sh. Without --no-block the command ends when the backup is done, and its
    # exit code says how it went (the runner reports that to the hub).
    "backup": ["systemctl", "start", "agent-hub-backup.service"],
}
POWER_ACTIONS = tuple(POWER_COMMANDS)
POWER_IMAGE = "agent-hub-hub-runner"   # the runner's own image (python:3.13-slim has nsenter), never pulled
_BAD_PATH = re.compile(r"[,\s\x00=:]")   # would confuse --mount parsing or hide something
_MARKER = re.compile(r"^RESULT:\s*([a-z_]+)\s*$")


def build_power_command(action: str) -> list[str]:
    """The `docker run` command that restarts or shuts down the Pi or starts its backup. ValueError for any other
    action."""
    if action not in POWER_COMMANDS:
        raise ValueError("unknown power action")
    return [
        "docker", "run", "--rm", "--pull=never", "--privileged", "--pid=host", "--network=none", POWER_IMAGE,
        "nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid", *POWER_COMMANDS[action],
    ]


def run_uid(user_id: int) -> int:
    return UID_BASE + _number(user_id, "user_id")


def _number(value, name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _folder(value, name: str) -> str:
    text = str(value)
    if not os.path.isabs(text) or _BAD_PATH.search(text) or ".." in Path(text).parts:
        raise ValueError(f"{name} must be a plain absolute path")
    return text


def _proxy_env(url: str) -> list[str]:
    return ["-e", f"HTTPS_PROXY={url}", "-e", f"https_proxy={url}"]


def _claude_env(ticket: str) -> list[str]:
    """How a run reaches Claude: an empty home in memory, the ticket as its token, every request to the gateway
    (never past the proxy: NO_PROXY), nothing else sent to Anthropic. The ticket stands on the command line of
    `docker run`, which is fine: it only counts inside the agent network and only while the run lasts."""
    if not isinstance(ticket, str) or not _TICKET.fullmatch(ticket):
        raise ValueError("bad ticket")
    return [
        "--tmpfs", "/home/claude:rw,size=32m,mode=1777",
        "-e", "HOME=/home/claude", "-e", "CLAUDE_CONFIG_DIR=/home/claude/.claude",
        "-e", f"CLAUDE_CODE_OAUTH_TOKEN={ticket}", "-e", f"ANTHROPIC_BASE_URL={GATEWAY}",
        "-e", "NO_PROXY=egress", "-e", "no_proxy=egress", "-e", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1",
    ]


RUN_PROXY = {"together": WEB_PROXY, "apart": API_PROXY}   # the role's switch "web + code together"


def _model_args(model: str, effort: str) -> list[str]:
    """`--model` and, if a level is set, `--effort`. ValueError for anything that does not fit the patterns."""
    if not isinstance(model, str) or not _MODEL.fullmatch(model):
        raise ValueError("bad model")
    if not isinstance(effort, str) or (effort and not _EFFORT.fullmatch(effort)):
        raise ValueError("bad effort")
    return ["--model", model, *(["--effort", effort] if effort else [])]


def build_command(*, run_id: int, user_id: int, model: str, work_dir: str, ticket: str, net: str = "together",
                  effort: str = "", image: str = IMAGE, network: str = NETWORK, memory: str = "480m") -> list[str]:
    """The `docker run` command for one run. Raises ValueError for anything unexpected. `net` is the role's
    switch: "together" = open internet (public hosts only), "apart" = only Anthropic (code without internet).
    `effort` is the model's level (empty = Claude Code's own default)."""
    run_id = _number(run_id, "run_id")
    if net not in RUN_PROXY:
        raise ValueError("unknown net mode")
    uid = run_uid(user_id)
    model_args = _model_args(model, effort)
    if not re.fullmatch(r"[0-9]+[mg]", memory) or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", image + network):
        raise ValueError("bad image, network or memory")
    work = _folder(work_dir, "work_dir")
    return [
        "docker", "run", "--rm", "--init", "-i", "--name", f"agent-run-{run_id}",
        "--user", f"{uid}:{uid}",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--read-only", "--tmpfs", "/tmp:rw,size=64m,mode=1777",
        "--memory", memory, "--memory-swap", memory, "--pids-limit", "256", "--cpus", "2",
        "--network", network,
        "--mount", f"type=bind,src={work},dst=/work", "--workdir", "/work",
        # Agents may use the internet (Janis, 08.11.2026): public hosts only, never the home network; per role switch.
        *_claude_env(ticket), *_proxy_env(RUN_PROXY[net]),
        image,
        # Inside the isolated container the agent may use its tools freely; the prompt comes via stdin.
        "claude", "-p", *model_args, "--output-format", "json", "--dangerously-skip-permissions",
    ]


def build_chat_command(*, chat_id: int, user_id: int, model: str, ticket: str, mode: str = "all",
                       effort: str = "", image: str = IMAGE, network: str = NETWORK, memory: str = "480m") -> list[str]:
    """The manager chat (see web/app/chat.py): one question to Claude, in a container like a run but with no
    work folder at all (nothing of any project is mounted; the project context comes on stdin). `mode` (see
    CHAT_MODES) decides the tools and the way out; "all" = web search and a shell, only Anthropic reachable.
    `effort` is the model's level (empty = Claude Code's own default)."""
    chat_id = _number(chat_id, "chat_id")
    uid = run_uid(user_id)
    model_args = _model_args(model, effort)
    if mode not in CHAT_MODES:
        raise ValueError("unknown mode")
    if not re.fullmatch(r"[0-9]+[mg]", memory) or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", image + network):
        raise ValueError("bad image, network or memory")
    spec = CHAT_MODES[mode]
    tools = spec["tools"]
    # Nothing of the run is kept: no saved login, no settings, so a changed configuration (a hook, say) can not
    # reach a later run either.
    runs_code = "Bash" in tools
    return [
        "docker", "run", "--rm", "--init", "-i", "--name", f"agent-chat-{chat_id}",
        "--user", f"{uid}:{uid}",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--read-only", "--tmpfs", f"/tmp:rw,size={'128m' if runs_code else '64m'},mode=1777", "--workdir", "/tmp",
        "--memory", memory, "--memory-swap", memory, "--pids-limit", "256", "--cpus", "2",
        "--network", network,
        *_claude_env(ticket), "-e", "PYTHONDONTWRITEBYTECODE=1",
        *_proxy_env(spec["proxy"]),
        image,
        "claude", "-p", *model_args, "--output-format", "json", "--no-session-persistence",
        # Exactly the tools of the mode. In -p mode nobody can confirm a permission, so exactly these are
        # allowed; --max-turns keeps a search or a program from running away (and eating quota).
        "--tools", ",".join(tools),
        *(["--allowedTools", " ".join(tools)] if tools else []),
        "--max-turns", str(spec["turns"]),
    ]

# Words in an error answer that mean "not signed in (any more)": the connection is shown as expired.
_AUTH_PROBLEM = re.compile(r"/login|not logged in|log in|authenticat|invalid api key|oauth|401", re.I)


def parse_chat_output(stdout: str) -> tuple[bool, str, int, int, bool]:
    """(ok, text, tokens_in, tokens_out, login_problem) from the JSON of `claude -p`.

    `ok` is False for anything but a clear, non-error answer. `login_problem` is True when the
    error looks like a lost sign-in. Nothing is guessed: an unreadable output is a failure.
    """
    try:
        data = json.loads(stdout)
        text = str(data.get("result", "")).strip()
        usage = data.get("usage") or {}
        tokens_in = sum(int(usage.get(k) or 0) for k in (
            "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        tokens_out = int(usage.get("output_tokens") or 0)
        failed = bool(data.get("is_error"))
        subtype = str(data.get("subtype") or "")
    except (ValueError, AttributeError, TypeError):
        return False, "No readable answer from Claude Code.", 0, 0, bool(_AUTH_PROBLEM.search(stdout or ""))
    if subtype == "error_max_turns" and not text:
        return False, "Too many steps: the search limit was reached.", tokens_in, tokens_out, False
    if failed or not text:
        return False, text or "Claude Code reported an error.", tokens_in, tokens_out, bool(_AUTH_PROBLEM.search(text))
    return True, text[:MAX_REPORT], tokens_in, tokens_out, False


def build_login_command(*, user_id: int, image: str = IMAGE, network: str = NETWORK,
                        memory: str = "480m") -> list[str]:
    """The `docker run` command of one sign-in, same restrictions as a run but with a terminal (it asks for the
    code there). `claude setup-token` (14.11.2026): the normal login ran out after about a day without a screen;
    the setup token lasts a year. It prints the token at the end and saves nothing (its home is in memory and
    gone with the container); the runner takes the token from the terminal and keeps it encrypted (tokens.py)."""
    uid = run_uid(user_id)
    if not re.fullmatch(r"[0-9]+[mg]", memory) or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", image + network):
        raise ValueError("bad image, network or memory")
    return [
        "docker", "run", "--rm", "--init", "-t", "-i", "--name", f"agent-login-{int(user_id)}",
        "--user", f"{uid}:{uid}",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--read-only", "--tmpfs", "/tmp:rw,size=64m,mode=1777",
        "--memory", memory, "--memory-swap", memory, "--pids-limit", "256",
        "--network", network,
        "--tmpfs", "/home/claude:rw,size=16m,mode=1777",
        "-e", "HOME=/home/claude", "-e", "CLAUDE_CONFIG_DIR=/home/claude/.claude", "-e", "BROWSER=none",
        *_proxy_env(API_PROXY),
        image, "claude", "setup-token",
    ]


def prepare_folder(path: str, user_id: int, recursive: bool = False) -> None:
    """Create a folder (if needed) and hand it to the run user: mode 0700, nobody else may enter.
    Needs root (the runner container is root, the runs are not)."""
    uid = run_uid(user_id)
    root = Path(_folder(path, "path"))
    root.mkdir(parents=True, exist_ok=True)
    for item in ([root, *root.rglob("*")] if recursive else [root]):
        os.chown(item, uid, uid, follow_symlinks=False)
    os.chmod(root, 0o700)


def parse_output(role: str, stdout: str) -> tuple[str, str, int, int]:
    """(result, report, tokens_in, tokens_out) from the JSON that `claude -p` prints.

    The agent ends its answer with a line `RESULT: <value>`. Anything else (no JSON, an error, no
    marker, a value that does not fit the role) is reported as "failed": the task then goes to
    the user instead of guessing.
    """
    if role not in RESULTS:
        raise ValueError("unknown role")
    try:
        data = json.loads(stdout)
        text = str(data.get("result", ""))
        usage = data.get("usage") or {}
        tokens_in = sum(int(usage.get(k) or 0) for k in (
            "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        tokens_out = int(usage.get("output_tokens") or 0)
        failed = bool(data.get("is_error"))
    except (ValueError, AttributeError, TypeError):
        return "failed", "No readable answer from Claude Code.", 0, 0
    lines = text.rstrip().splitlines()
    match = _MARKER.match(lines[-1].strip()) if lines else None
    report = "\n".join(lines[:-1] if match else lines).strip()[:MAX_REPORT]
    if failed or match is None or match.group(1) not in RESULTS[role]:
        return "failed", report or "The agent gave no valid result.", tokens_in, tokens_out
    return match.group(1), report, tokens_in, tokens_out


if __name__ == "__main__":   # `python launcher.py role < output.json` for a quick look
    print(parse_output(sys.argv[1], sys.stdin.read()))
