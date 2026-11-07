"""Starts one Claude Code run in its own container and reads its answer. Standard library only.

The launcher is trusted code with access to the Docker socket, so it takes no free arguments:
`build_command` fills a fixed template with a few checked values (numbers, a model from a short
list, two folders). The text of a task (title, reports, notes) never reaches the command line: the
prompt goes in through stdin. The run container sees exactly two folders, the work folder of this
task and the Claude folder of this user, and nothing else (no hub.db, .env, backups, vault, other
users). See KONZEPT-AGENTEN.md, section 6a.
"""
import json
import os
import re
import sys
from pathlib import Path

MODELS = ("haiku", "sonnet", "opus")
ROLES = ("chef", "programmer", "tester", "reviewer", "documenter")
RESULTS = {
    "programmer": ("done", "failed"),
    "tester": ("pass", "fail", "not_testable", "failed"),
    "reviewer": ("ok", "objections", "failed"),
    "documenter": ("done", "failed"),
}
IMAGE = "agent-hub-agent"         # built from runner/Dockerfile
NETWORK = "agent-hub-agents"      # separate from the "web" network: a run cannot reach the hub
UID_BASE = 10000                  # run user = UID_BASE + user_id, never root
MAX_REPORT = 20000
CHAT_TOOLS = ("WebSearch", "WebFetch")   # what the chat window may use: search the web and read a page
CHAT_MAX_TURNS = 8                       # steps (model turns) per question
_BAD_PATH = re.compile(r"[,\s\x00=:]")   # would confuse --mount parsing or hide something
_MARKER = re.compile(r"^RESULT:\s*([a-z_]+)\s*$")


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


def build_command(*, run_id: int, user_id: int, model: str, work_dir: str, claude_dir: str,
                  image: str = IMAGE, network: str = NETWORK, memory: str = "480m") -> list[str]:
    """The `docker run` command for one run. Raises ValueError for anything unexpected."""
    run_id = _number(run_id, "run_id")
    uid = run_uid(user_id)
    if model not in MODELS:
        raise ValueError("unknown model")
    if not re.fullmatch(r"[0-9]+[mg]", memory) or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", image + network):
        raise ValueError("bad image, network or memory")
    work, claude = _folder(work_dir, "work_dir"), _folder(claude_dir, "claude_dir")
    return [
        "docker", "run", "--rm", "--init", "-i", "--name", f"agent-run-{run_id}",
        "--user", f"{uid}:{uid}",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--read-only", "--tmpfs", "/tmp:rw,size=64m,mode=1777",
        "--memory", memory, "--memory-swap", memory, "--pids-limit", "256", "--cpus", "2",
        "--network", network,
        "--mount", f"type=bind,src={work},dst=/work", "--workdir", "/work",
        "--mount", f"type=bind,src={claude},dst=/claude",
        "-e", "HOME=/claude", "-e", "CLAUDE_CONFIG_DIR=/claude",
        image,
        # Inside the isolated container the agent may use its tools freely; the prompt comes via stdin.
        "claude", "-p", "--model", model, "--output-format", "json", "--dangerously-skip-permissions",
    ]


def build_chat_command(*, chat_id: int, user_id: int, model: str, claude_dir: str, image: str = IMAGE,
                       network: str = NETWORK, memory: str = "480m") -> list[str]:
    """The chat window (see web/app/chat.py): one question to Claude, in a container like a run but
    with no work folder at all (nothing of any project is mounted) and with only the web tools switched on."""
    chat_id = _number(chat_id, "chat_id")
    uid = run_uid(user_id)
    if model not in MODELS:
        raise ValueError("unknown model")
    if not re.fullmatch(r"[0-9]+[mg]", memory) or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", image + network):
        raise ValueError("bad image, network or memory")
    claude = _folder(claude_dir, "claude_dir")
    return [
        "docker", "run", "--rm", "--init", "-i", "--name", f"agent-chat-{chat_id}",
        "--user", f"{uid}:{uid}",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--read-only", "--tmpfs", "/tmp:rw,size=64m,mode=1777", "--workdir", "/tmp",
        "--memory", memory, "--memory-swap", memory, "--pids-limit", "256", "--cpus", "2",
        "--network", network,
        "--mount", f"type=bind,src={claude},dst=/claude",
        "-e", "HOME=/claude", "-e", "CLAUDE_CONFIG_DIR=/claude",
        image,
        "claude", "-p", "--model", model, "--output-format", "json", "--no-session-persistence",
        # Only the two web tools, nothing that touches files or runs commands. In -p mode nobody can confirm a
        # permission, so exactly these are allowed; --max-turns keeps a search from running away (and eating quota).
        "--tools", ",".join(CHAT_TOOLS), "--allowedTools", " ".join(CHAT_TOOLS), "--max-turns", str(CHAT_MAX_TURNS),
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


def build_login_command(*, user_id: int, claude_dir: str, image: str = IMAGE, network: str = NETWORK,
                        memory: str = "480m") -> list[str]:
    """The `docker run` command of one sign-in (`claude auth login`), same restrictions as a run but
    with a terminal (the login asks for the code there) and only the Claude folder of this user."""
    uid = run_uid(user_id)
    if not re.fullmatch(r"[0-9]+[mg]", memory) or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", image + network):
        raise ValueError("bad image, network or memory")
    claude = _folder(claude_dir, "claude_dir")
    return [
        "docker", "run", "--rm", "--init", "-t", "-i", "--name", f"agent-login-{int(user_id)}",
        "--user", f"{uid}:{uid}",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--read-only", "--tmpfs", "/tmp:rw,size=64m,mode=1777",
        "--memory", memory, "--memory-swap", memory, "--pids-limit", "256",
        "--network", network,
        "--mount", f"type=bind,src={claude},dst=/claude",
        "-e", "HOME=/claude", "-e", "CLAUDE_CONFIG_DIR=/claude", "-e", "BROWSER=none",
        image, "claude", "auth", "login", "--claudeai",
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
