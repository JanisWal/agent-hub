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
from pathlib import Path

# Models and effort levels are a list of the hub (web/app/catalog.py) that can change without a code change, and
# the hub checks every choice against it. Here they only have to be safe as one argument each: a fixed pattern,
# lower case, never starting with "-" (the same patterns as catalog.py).
_MODEL = re.compile(r"[a-z][a-z0-9.-]{0,47}")
_EFFORT = re.compile(r"[a-z]{1,12}")
IMAGE = "agent-hub-agent"         # built from runner/Dockerfile
VIBE_IMAGE = "agent-hub-vibe"     # built from runner/Dockerfile.vibe (Mistral Vibe)
NETWORK = "agent-hub-agents"      # separate from the "web" network: a run cannot reach the hub
UID_BASE = 10000                  # run user = UID_BASE + user_id, never root
MAX_REPORT = 100000   # characters of an answer or report handed to the hub (30 board items with context fit)
# The agent network has no route to the outside: everything goes through the egress proxy (runner/egress.py).
WEB_PROXY = "http://egress:3128"   # any public host on 443, never the home network or the Pi itself
API_PROXY = "http://egress:3129"   # only Anthropic (sign-ins)
GATEWAY = "http://egress:3130"     # the Claude API with the user's token put in by the proxy (runner/egress.py)
MISTRAL_GATEWAY = "http://egress:3131"   # the same for Mistral (its key put in by the proxy)
CUSTOM_GATEWAY = "http://egress:3132"    # the user's own AI (any OpenAI-compatible API; address and key from the ticket)
CHATGPT_GATEWAY = "http://egress:3133"   # ChatGPT through Codex (the real token and account put in by the proxy)
CODEX_IMAGE = "agent-hub-codex"           # built from runner/Dockerfile.codex
CODEX_JOBS = {"chat-all": 180, "chat-apart": 180, "chat-brief": 90, "run": 1050, "run-brief": 300, "models": 60}
LOGIN_SECONDS = 900                       # the one-time code of a ChatGPT sign-in lasts 15 minutes
_REMOTE_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,99}")   # a model name at such an API (web/app/ai_link.py)
# Mistral runs: limits per job (turns, seconds); the proxy follows the same switch as Claude.
# "run-brief": a run that needs no tools (the reviewer of a small change, the manager's documentation; 20.11.2026).
VIBE_JOBS = {"chat-all": (12, 180), "chat-apart": (10, 180), "chat-brief": (1, 90), "run": (60, 1050),
             "run-brief": (2, 300)}
_NAME = re.compile(r"agent-(chat|run)-[0-9]+")
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
    # The written status of a project (web/app/statusnote.py, 17.11.2026): no tools at all, one turn, only Anthropic
    # reachable. It reads a short digest on stdin and answers one line; nothing else costs tokens.
    "brief": {"tools": (), "proxy": API_PROXY, "turns": 1},
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
_MARKER = re.compile(r"^RESULT:\s*([a-z_]+)\s*\.?$")
RESULT_LOOK = 5   # non-empty lines at the end of an answer in which the RESULT line may stand (weaker models add a word)


# Switching a device on (Wake-on-LAN, 17.11.2026): the magic packet is a broadcast in the home network. The broker's
# Docker network does not pass broadcasts on, so a short container in the server's own network sends it: no
# privileges, no capabilities, read-only, nothing but this fixed script and the checked MAC as its one argument.
_WAKE_MAC = re.compile(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}")
WAKE_SCRIPT = ("import socket,sys;m=bytes.fromhex(sys.argv[1].replace(':',''));"
               "s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1);"
               "[s.sendto(b'\\xff'*6+m*16,('255.255.255.255',p)) for p in (9,7)]")


def build_wake_command(mac: str) -> list[str]:
    """The `docker run` command that sends the Wake-on-LAN packet for `mac` (aa:bb:cc:dd:ee:ff). ValueError else."""
    if not isinstance(mac, str) or not _WAKE_MAC.fullmatch(mac):
        raise ValueError("bad mac")
    return ["docker", "run", "--rm", "--pull=never", "--network=host", "--user", "65534:65534", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--read-only", "--memory", "32m", POWER_IMAGE,
            "python", "-c", WAKE_SCRIPT, mac]


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


READ_TOOLS = ("Read", "Glob", "Grep")   # to open the read-only /files and /code in the manager chat (16.11.2026)
HUB_TOOL_NAMES = ("look", "list_files", "read_file", "grep", "write_file", "edit_file", "run", "fetch")   # hub_tools.TOOLS


def _hub_mcp(hub_tools) -> list[str]:
    """`--mcp-config` for Claude Code with the hub's tools a measured missing own tool needs (web/app/toolcheck.py);
    nothing when there are none. Only names of the fixed list reach the command line."""
    names = [n for n in (hub_tools or ()) if n in HUB_TOOL_NAMES]
    if not names:
        return []
    config = {"mcpServers": {"hub": {"command": "python3", "args": ["/opt/hub/hub_tools.py"],
                                     "env": {"HUB_TOOLS": ",".join(names)}}}}
    return ["--mcp-config", json.dumps(config, separators=(",", ":"))]


def _read_only(files_dir: str | None, code_dir: str | None = None) -> list[str]:
    """The user's files of the project at /files and the project's code at /code, both mounted read-only
    (runner/view.py makes the folders; nothing written there could reach the hub)."""
    mounts = []
    for value, name, target in ((files_dir, "files_dir", "/files"), (code_dir, "code_dir", "/code")):
        if value is not None:
            mounts += ["--mount", f"type=bind,src={_folder(value, name)},dst={target},readonly"]
    return mounts


def _check_container(memory: str, image: str, network: str) -> None:
    """The fixed values of a `docker run`: a memory size and plain names. ValueError for anything else."""
    if not re.fullmatch(r"[0-9]+[mg]", memory) or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", image + network):
        raise ValueError("bad image, network or memory")


def _proxy_env(url: str) -> list[str]:
    return ["-e", f"HTTPS_PROXY={url}", "-e", f"https_proxy={url}"]


def _claude_env(ticket: str, api: bool = False) -> list[str]:
    """How a run reaches Claude: an empty home in memory, the ticket as its token, every request to the gateway
    (never past the proxy: NO_PROXY), nothing else sent to Anthropic. The ticket stands on the command line of
    `docker run`, which is fine: it only counts inside the agent network and only while the run lasts."""
    if not isinstance(ticket, str) or not _TICKET.fullmatch(ticket):
        raise ValueError("bad ticket")
    return [
        "--tmpfs", "/home/claude:rw,size=32m,mode=1777",
        "-e", "HOME=/home/claude", "-e", "CLAUDE_CONFIG_DIR=/home/claude/.claude",
        "-e", f"{'ANTHROPIC_API_KEY' if api else 'CLAUDE_CODE_OAUTH_TOKEN'}={ticket}", "-e", f"ANTHROPIC_BASE_URL={GATEWAY}",
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
                  effort: str = "", image: str = IMAGE, network: str = NETWORK, memory: str = "480m",
                  files_dir: str | None = None, hub_tools=None, api: bool = False) -> list[str]:
    """The `docker run` command for one run. Raises ValueError for anything unexpected. `net` is the role's
    switch: "together" = open internet (public hosts only), "apart" = only Anthropic (code without internet).
    `effort` is the model's level (empty = Claude Code's own default)."""
    run_id = _number(run_id, "run_id")
    if net not in RUN_PROXY:
        raise ValueError("unknown net mode")
    uid = run_uid(user_id)
    model_args = _model_args(model, effort)
    _check_container(memory, image, network)
    work = _folder(work_dir, "work_dir")
    return [
        "docker", "run", "--rm", "--init", "-i", "--name", f"agent-run-{run_id}",
        "--user", f"{uid}:{uid}",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--read-only", "--tmpfs", "/tmp:rw,size=64m,mode=1777",
        "--memory", memory, "--memory-swap", memory, "--pids-limit", "256", "--cpus", "2",
        "--network", network,
        "--mount", f"type=bind,src={work},dst=/work", "--workdir", "/work", *_read_only(files_dir),
        # Agents may use the internet (Janis, 08.11.2026): public hosts only, never the home network; per role switch.
        *_claude_env(ticket, api), *_proxy_env(RUN_PROXY[net]),
        image,
        # Inside the isolated container the agent may use its tools freely; the prompt comes via stdin. stream-json:
        # one line per event, so the runner sees that the run moves on (no fixed time limit, 22.11.2026) and can show
        # its thoughts; the summaries are only displayed.
        "claude", "-p", *model_args, "--output-format", "stream-json", "--verbose", "--include-partial-messages",
        "--thinking-display", "summarized", "--dangerously-skip-permissions", *_hub_mcp(hub_tools),
    ]


TEST_SECONDS = 300   # the project's tests (hub-test.sh) at most, until the hub says otherwise (limits)

# The container of a job as the owner set it (web/app/serversettings.run_limits, 21.11.2026), checked here again: a
# value out of its range or of the wrong type falls back to the one the Pi has always used.
LIMITS = {"memory_mb": (480, 256, 65536), "cpus": (2, 1, 64), "pids": (256, 64, 65536),
          # an agent run ends after this long without output, or after the longest time of work (22.11.2026)
          "silence_seconds": (900, 60, 86400), "max_seconds": (14400, 600, 172800),
          "chat_seconds": (200, 60, 86400), "test_seconds": (TEST_SECONDS, 60, 86400),
          "view_mb": (200, 50, 100000), "browser": (1, 0, 1)}


def checked(raw) -> dict:
    """The job's limits, each an int inside its range (LIMITS), else its default."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for key, (default, low, high) in LIMITS.items():
        value = raw.get(key)
        out[key] = value if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high else default
    return out


def apply_limits(command: list[str], limits: dict) -> list[str]:
    """The `docker run` of a job with the owner's memory, processor cores, process count and /tmp size (a quarter of
    the memory, at least what it was). Only the options before the image are touched, never the program's own."""
    limits = checked(limits)
    images = {IMAGE, VIBE_IMAGE, CODEX_IMAGE}
    out = list(command)
    end = next((i for i, part in enumerate(out) if part in images), len(out))
    for i in range(end - 1):
        flag = out[i]
        if flag in ("--memory", "--memory-swap"):
            out[i + 1] = f"{limits['memory_mb']}m"
        elif flag == "--pids-limit":
            out[i + 1] = str(limits["pids"])
        elif flag == "--cpus":
            out[i + 1] = str(limits["cpus"])
        elif flag == "--tmpfs" and out[i + 1].startswith("/tmp:"):
            size = re.search(r"size=([0-9]+)m", out[i + 1])
            if size:
                wanted = max(int(size.group(1)), limits["memory_mb"] // 4)
                out[i + 1] = out[i + 1].replace(size.group(0), f"size={wanted}m")
    return out


def build_test_command(*, run_id: int, user_id: int, work_dir: str, net: str = "apart", image: str = IMAGE,
                       network: str = NETWORK, memory: str = "480m", test_seconds: int = TEST_SECONDS) -> list[str]:
    """The `docker run` command that runs the project's own tests (`sh hub-test.sh` in /work) after a programmer's run:
    the same limits as a run, no AI, no ticket. Nothing of the script is on the command line; it is a file in the
    task's folder. `net` is the programmer's switch (installing packages needs the web)."""
    run_id = _number(run_id, "run_id")
    if net not in RUN_PROXY:
        raise ValueError("unknown net mode")
    uid = run_uid(user_id)
    _check_container(memory, image, network)
    work = _folder(work_dir, "work_dir")
    return [
        "docker", "run", "--rm", "--init", "--name", f"agent-test-{run_id}", "--user", f"{uid}:{uid}",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--read-only", "--tmpfs", "/tmp:rw,size=128m,mode=1777", "--tmpfs", "/home/test:rw,size=64m,mode=1777",
        "-e", "HOME=/home/test", "-e", "CI=1",
        "--memory", memory, "--memory-swap", memory, "--pids-limit", "256", "--cpus", "2",
        "--network", network, *_proxy_env(RUN_PROXY[net]),
        "--mount", f"type=bind,src={work},dst=/work", "--workdir", "/work",
        image, "timeout", str(int(test_seconds)), "sh", "hub-test.sh",
    ]


def build_chat_command(*, chat_id: int, user_id: int, model: str, ticket: str, mode: str = "all",
                       effort: str = "", image: str = IMAGE, network: str = NETWORK, memory: str = "480m",
                       files_dir: str | None = None, code_dir: str | None = None, name: str | None = None,
                       hub_tools=None, api: bool = False) -> list[str]:
    """The manager chat (see web/app/chat.py): one question to Claude, in a container like a run but with no
    work folder at all (nothing of any project is mounted; the project context comes on stdin). `mode` (see
    CHAT_MODES) decides the tools and the way out; "all" = web search and a shell, only Anthropic reachable.
    `effort` is the model's level (empty = Claude Code's own default)."""
    chat_id = _number(chat_id, "chat_id")
    name = name or f"agent-chat-{chat_id}"     # "agent-run-<n>" for a brief agent run (runner.do_run)
    if not _NAME.fullmatch(name):
        raise ValueError("bad name")
    uid = run_uid(user_id)
    model_args = _model_args(model, effort)
    if mode not in CHAT_MODES:
        raise ValueError("unknown mode")
    _check_container(memory, image, network)
    spec = CHAT_MODES[mode]
    tools = spec["tools"] + (READ_TOOLS if files_dir or code_dir else ())   # reading the user's files and the code
    mcp = _hub_mcp(hub_tools) if spec["tools"] else []                       # a brief job gets no tools at all
    if mcp:
        tools += tuple(f"mcp__hub__{n}" for n in hub_tools if n in HUB_TOOL_NAMES)
    # Nothing of the run is kept: no saved login, no settings, so a changed configuration (a hook, say) can not
    # reach a later run either.
    runs_code = "Bash" in tools
    return [
        "docker", "run", "--rm", "--init", "-i", "--name", name,
        "--user", f"{uid}:{uid}",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--read-only", "--tmpfs", f"/tmp:rw,size={'128m' if runs_code else '64m'},mode=1777", "--workdir", "/tmp",
        "--memory", memory, "--memory-swap", memory, "--pids-limit", "256", "--cpus", "2",
        "--network", network, *_read_only(files_dir, code_dir),
        *_claude_env(ticket, api), "-e", "PYTHONDONTWRITEBYTECODE=1",
        *_proxy_env(spec["proxy"]),
        image,
        # stream-json: one line per event, so the runner can show the thoughts while they come (Janis, 18.11.2026);
        # the summaries are only displayed, the thinking itself is the same and costs the same.
        "claude", "-p", *model_args, "--output-format", "stream-json", "--verbose", "--include-partial-messages",
        "--thinking-display", "summarized", "--no-session-persistence",
        # Exactly the tools of the mode. In -p mode nobody can confirm a permission, so exactly these are
        # allowed; --max-turns keeps a search or a program from running away (and eating quota).
        "--tools", ",".join(t for t in tools if not t.startswith("mcp__")),
        *(["--allowedTools", " ".join(tools)] if tools else []), *mcp,
        "--max-turns", str(spec["turns"]),
    ]

# What Claude Code says when the AI refused the token (only read in an error answer): the connection is shown as
# expired and the token is deleted, so only clear words count, never a bare "log in" or "oauth" (20.11.2026).
_AUTH_PROBLEM = re.compile(r"authentication_error|invalid api key|please run /login|not logged in|"
                           r"oauth token (?:has )?expired|token (?:has been )?revoked|\b401\b", re.I)


def claude_tokens(data: dict) -> tuple[int, int]:
    """(tokens_in, tokens_out) from the JSON of `claude -p`; what was read from or written to the cache counts as in."""
    usage = data.get("usage") or {}
    tokens_in = sum(int(usage.get(k) or 0) for k in (
        "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    return tokens_in, int(usage.get("output_tokens") or 0)


def usage_of(stdout: str) -> dict:
    """What a job used, for the usage ledger (22.11.2026): {"tokens_in", "tokens_out", "cache_read", "cache_write",
    "partial"}. From the final summary when there is one (Claude Code's result, the one JSON line of Vibe, Codex and the
    hub's loop); else what the stream showed until the job was ended (Claude Code's finished messages, each counted
    once, or the last {"usage_so_far": ...} line of the entry scripts), marked `partial`. tokens_in is the whole input,
    the cache numbers are the part of it read from or written to the AI's cache. Nothing is estimated."""
    def numbers(u: dict) -> tuple[int, int, int, int]:
        read, write = int(u.get("cache_read_input_tokens") or 0), int(u.get("cache_creation_input_tokens") or 0)
        return int(u.get("input_tokens") or 0) + read + write, int(u.get("output_tokens") or 0), read, write
    out = {"tokens_in": 0, "tokens_out": 0, "cache_read": 0, "cache_write": 0, "partial": False}
    try:
        result = claude_result(stdout)
        if result.get("type") == "result" or isinstance(result.get("usage"), dict):   # not the entry scripts' summary
            tin, tout, read, write = numbers(result.get("usage") or {})
            return dict(out, tokens_in=tin, tokens_out=tout, cache_read=read, cache_write=write)
    except (ValueError, AttributeError, TypeError):
        pass
    messages, so_far, summary = {}, None, None
    for line in (stdout or "").splitlines():
        if '"usage' not in line and '"tokens_in"' not in line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        message = data.get("message") if data.get("type") == "assistant" else None
        if isinstance(message, dict) and isinstance(message.get("usage"), dict):
            messages[message.get("id") or len(messages)] = message["usage"]
        elif isinstance(data.get("usage_so_far"), dict):
            so_far = data["usage_so_far"]
        elif "tokens_in" in data:
            summary = data
    for found, partial in ((summary, False), (so_far, True)):
        if found is not None:
            try:
                tin, tout, read = (int(found.get(k) or 0) for k in ("tokens_in", "tokens_out", "cache_read"))
            except (TypeError, ValueError):
                continue
            return dict(out, tokens_in=tin, tokens_out=tout, cache_read=read, partial=partial)
    if messages:
        sums = [sum(v) for v in zip(*(numbers(u) for u in messages.values()))]
        return dict(out, tokens_in=sums[0], tokens_out=sums[1], cache_read=sums[2], cache_write=sums[3], partial=True)
    return out


def claude_result(stdout: str) -> dict:
    """The result object of `claude -p`: the whole output (--output-format json, agent runs) or the last line of type
    "result" (stream-json, the chat). ValueError if there is none."""
    text = (stdout or "").strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    for line in reversed(text.splitlines()):
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("type") == "result":
            return data
    raise ValueError("no result")


def claude_thought(line: str) -> str:
    """Thought text in one line of `claude -p --output-format stream-json --include-partial-messages`: a piece of a
    thinking block (summarized by the API), a new block starts a new paragraph; "" for anything else."""
    if '"thinking' not in line:   # most lines are text, tools and status: no need to read them
        return ""
    try:
        data = json.loads(line)
    except ValueError:
        return ""
    event = data.get("event") if isinstance(data, dict) and data.get("type") == "stream_event" else None
    if not isinstance(event, dict):
        return ""
    if event.get("type") == "content_block_start":
        block = event.get("content_block")
        return "\n\n" if isinstance(block, dict) and block.get("type") == "thinking" else ""
    delta = event.get("delta") if event.get("type") == "content_block_delta" else None
    if isinstance(delta, dict) and delta.get("type") == "thinking_delta":
        return str(delta.get("thinking") or "")
    return ""


def claude_tools(line: str) -> list[str] | None:
    """The tools Claude Code names in its "init" event (stream-json), or None for any other line."""
    if '"init"' not in line:
        return None
    try:
        data = json.loads(line)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("type") != "system" or data.get("subtype") != "init":
        return None
    tools = data.get("tools")
    return [t for t in tools if isinstance(t, str)] if isinstance(tools, list) else None


def asked_tools(command: list[str]) -> list[str]:
    """The program's own tools a Claude command asks for (`--tools`), for comparing with what it names."""
    try:
        return [t for t in command[command.index("--tools") + 1].split(",") if t]
    except (ValueError, IndexError):
        return []


def vibe_thought(line: str) -> str:
    """Thought text in one line of vibe_entry.py ({"thought": ...}, one finished block of reasoning); "" otherwise."""
    if '"thought"' not in line:
        return ""
    try:
        data = json.loads(line)
    except ValueError:
        return ""
    thought = data.get("thought") if isinstance(data, dict) else None
    return "\n\n" + thought if isinstance(thought, str) and thought.strip() else ""


def parse_chat_output(stdout: str) -> tuple[bool, str, int, int, bool]:
    """(ok, text, tokens_in, tokens_out, login_problem) from the JSON of `claude -p` (claude_result).

    `ok` is False for anything but a clear, non-error answer. `login_problem` is True when the
    error looks like a lost sign-in. Nothing is guessed: an unreadable output is a failure.
    """
    try:
        data = claude_result(stdout)
        text = str(data.get("result", "")).strip()
        tokens_in, tokens_out = claude_tokens(data)
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
    _check_container(memory, image, network)
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


def build_vibe_command(*, name: str, user_id: int, model: str, ticket: str, job: str, effort: str = "",
                       net: str = "together", work_dir: str | None = None, image: str = VIBE_IMAGE,
                       network: str = NETWORK, memory: str = "480m", files_dir: str | None = None,
                       code_dir: str | None = None, images: bool = False, hub_tools=None) -> list[str]:
    """The `docker run` command of a Mistral run (Mistral Vibe, runner/vibe_entry.py): the chat ("chat-all",
    "chat-apart": no folder of any project) or an agent run ("run": the task's work folder at /work). Like Claude:
    run user, read-only, nothing but a home in memory, the ticket instead of the key, every request to the gateway,
    the web only through the proxy of the switch. `name` is "agent-chat-<n>" or "agent-run-<n>". `images`: the model
    sees pictures (the tool `look` of hub_tools.py then hands it images and PDF pages)."""
    if job not in VIBE_JOBS or (job == "run") != (work_dir is not None):
        raise ValueError("unknown job")
    if not _NAME.fullmatch(name):
        raise ValueError("bad name")
    if not isinstance(ticket, str) or not _TICKET.fullmatch(ticket):
        raise ValueError("bad ticket")
    _model_args(model, effort)                        # the same patterns as for Claude
    proxy = ({"chat-all": WEB_PROXY, "chat-apart": API_PROXY, "chat-brief": API_PROXY, "run-brief": API_PROXY}.get(job)
             or RUN_PROXY.get(net))
    if proxy is None:
        raise ValueError("unknown net mode")
    _check_container(memory, image, network)
    uid = run_uid(user_id)
    turns, seconds = VIBE_JOBS[job]
    mount = ["--mount", f"type=bind,src={_folder(work_dir, 'work_dir')},dst=/work", "--workdir", "/work"] if work_dir else []
    return [
        "docker", "run", "--rm", "--init", "-i", "--name", name, "--user", f"{uid}:{uid}",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--read-only", "--tmpfs", "/tmp:rw,size=64m,mode=1777", "--tmpfs", "/home/vibe:rw,size=128m,mode=1777",
        "--memory", memory, "--memory-swap", memory, "--pids-limit", "256", "--cpus", "2",
        "--network", network, *mount, *_read_only(files_dir, code_dir),
        "-e", "HOME=/home/vibe", "-e", f"MISTRAL_API_KEY={ticket}", "-e", f"HUB_GATEWAY={MISTRAL_GATEWAY}",
        "-e", f"HUB_MODEL={model}", "-e", f"HUB_EFFORT={effort}", "-e", f"HUB_JOB={job}",
        "-e", f"HUB_TURNS={turns}", "-e", f"HUB_SECONDS={seconds}", "-e", f"HUB_IMAGES={1 if images is True else 0}",
        "-e", "HUB_TOOLS=" + ",".join(dict.fromkeys(["look", *[n for n in (hub_tools or ()) if n in HUB_TOOL_NAMES]])),
        "-e", "NO_PROXY=egress", "-e", "no_proxy=egress", *_proxy_env(proxy),
        image, "python", "/opt/hub/vibe_entry.py",
    ]


def build_hubloop_command(*, name: str, user_id: int, model: str, ticket: str, job: str, net: str = "together",
                          work_dir: str | None = None, image: str = IMAGE, network: str = NETWORK, memory: str = "480m",
                          files_dir: str | None = None, code_dir: str | None = None) -> list[str]:
    """The `docker run` command of the user's own AI (runner/hubloop.py: the hub's tool loop for an AI that has only an
    API). Like the other runs: run user, read-only, a home in memory, the ticket instead of the key, every request to
    the gateway, the web only through the proxy of the job. `model` is the model name at the user's API (checked
    pattern); `job` as for Vibe (VIBE_JOBS)."""
    if job not in VIBE_JOBS or (job == "run") != (work_dir is not None):
        raise ValueError("unknown job")
    if not _NAME.fullmatch(name):
        raise ValueError("bad name")
    if not isinstance(ticket, str) or not _TICKET.fullmatch(ticket):
        raise ValueError("bad ticket")
    if not isinstance(model, str) or not _REMOTE_MODEL.fullmatch(model):
        raise ValueError("bad model")
    proxy = ({"chat-all": WEB_PROXY, "chat-apart": API_PROXY, "chat-brief": API_PROXY, "run-brief": API_PROXY}.get(job)
             or RUN_PROXY.get(net))
    if proxy is None:
        raise ValueError("unknown net mode")
    _check_container(memory, image, network)
    uid = run_uid(user_id)
    turns, seconds = VIBE_JOBS[job]
    mount = ["--mount", f"type=bind,src={_folder(work_dir, 'work_dir')},dst=/work", "--workdir", "/work"] if work_dir else []
    return [
        "docker", "run", "--rm", "--init", "-i", "--name", name, "--user", f"{uid}:{uid}",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--read-only", "--tmpfs", "/tmp:rw,size=128m,mode=1777", "--tmpfs", "/home/run:rw,size=64m,mode=1777",
        "--memory", memory, "--memory-swap", memory, "--pids-limit", "256", "--cpus", "2",
        "--network", network, *mount, *_read_only(files_dir, code_dir),
        "-e", "HOME=/home/run", "-e", f"HUB_KEY={ticket}", "-e", f"HUB_GATEWAY={CUSTOM_GATEWAY}",
        "-e", f"HUB_MODEL={model}", "-e", f"HUB_JOB={job}", "-e", f"HUB_TURNS={turns}", "-e", f"HUB_SECONDS={seconds}",
        "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "NO_PROXY=egress", "-e", "no_proxy=egress", *_proxy_env(proxy),
        image, "python3", "/opt/hub/hubloop.py",
    ]


def build_codex_command(*, name: str, user_id: int, model: str, effort: str, auth: str, job: str, net: str = "together",
                        work_dir: str | None = None, image: str = CODEX_IMAGE, network: str = NETWORK,
                        memory: str = "480m", files_dir: str | None = None, code_dir: str | None = None,
                        key_ticket: str = "") -> list[str]:
    """The `docker run` command of a ChatGPT run (Codex, runner/codex_entry.py). With `key_ticket` (the user's API
    key, credentials.py) there is no auth.json: the ticket goes as the key (HUB_KEY), Codex talks to /v1 of the gateway. `auth` is the run's auth.json
    (codex.run_auth: the ticket in its wrapper, nothing real), checked to be that and nothing else; model and level
    after the same patterns as everywhere. Like the other runs: run user, read-only, a home in memory, every request to
    the gateway, the web only through the proxy of the job."""
    if job not in CODEX_JOBS or (job == "run") != (work_dir is not None):
        raise ValueError("unknown job")
    if not _NAME.fullmatch(name):
        raise ValueError("bad name")
    if model or job != "models":
        _model_args(model, effort)
    if key_ticket:
        if auth or not _TICKET.fullmatch(key_ticket):
            raise ValueError("bad key ticket")
    elif not _codex_auth(auth):
        raise ValueError("bad auth")
    proxy = ({"chat-all": WEB_PROXY, "chat-apart": API_PROXY, "chat-brief": API_PROXY, "run-brief": API_PROXY,
              "models": API_PROXY}.get(job) or RUN_PROXY.get(net))
    if proxy is None:
        raise ValueError("unknown net mode")
    _check_container(memory, image, network)
    uid = run_uid(user_id)
    mount = ["--mount", f"type=bind,src={_folder(work_dir, 'work_dir')},dst=/work", "--workdir", "/work"] if work_dir else []
    return [
        "docker", "run", "--rm", "--init", "-i", "--name", name, "--user", f"{uid}:{uid}",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--read-only", "--tmpfs", "/tmp:rw,size=128m,mode=1777", "--tmpfs", "/home/codex:rw,size=128m,mode=1777",
        "--memory", memory, "--memory-swap", memory, "--pids-limit", "256", "--cpus", "2",
        "--network", network, *mount, *_read_only(files_dir, code_dir),
        "-e", "HOME=/home/codex", *(["-e", f"HUB_KEY={key_ticket}"] if key_ticket else ["-e", f"HUB_AUTH={auth}"]),
        "-e", f"HUB_GATEWAY={CHATGPT_GATEWAY}",
        "-e", f"HUB_MODEL={model}", "-e", f"HUB_EFFORT={effort}", "-e", f"HUB_JOB={job}",
        "-e", f"HUB_SECONDS={CODEX_JOBS[job]}", "-e", "NO_PROXY=egress", "-e", "no_proxy=egress", *_proxy_env(proxy),
        image, "python3", "/opt/hub/codex_entry.py",
    ]


def _codex_auth(auth) -> bool:
    """The run's auth.json and nothing else: the shape of codex.run_auth with a wrapped ticket, no real token."""
    try:
        data = json.loads(auth)
        tokens = data["tokens"]
        from runner import codex   # the runner's own module (no import cycle at load time)
        ticket = codex.ticket_of(tokens["access_token"])
    except (ValueError, KeyError, TypeError):
        return False
    return (bool(_TICKET.fullmatch(ticket)) and tokens.get("refresh_token") == "hub-none"
            and set(data) <= {"OPENAI_API_KEY", "auth_mode", "tokens", "last_refresh"} and "\n" not in auth)


def build_codex_login_command(*, user_id: int, folder: str, image: str = CODEX_IMAGE, network: str = NETWORK,
                              memory: str = "480m") -> list[str]:
    """`codex login --device-auth` for a ChatGPT sign-in: it prints a link and a one-time code, the user signs in at
    OpenAI, Codex writes auth.json into `folder` (the runner's own folder of this sign-in, mounted as the only place it
    can write to). Public web only through the proxy: Codex talks to auth.openai.com itself."""
    uid = run_uid(user_id)
    _check_container(memory, image, network)
    return [
        "docker", "run", "--rm", "--init", "-i", "--name", f"agent-login-chatgpt-{int(user_id)}",
        "--user", f"{uid}:{uid}", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--read-only", "--tmpfs", "/tmp:rw,size=64m,mode=1777", "--tmpfs", "/home/codex:rw,size=32m,mode=1777",
        "--memory", memory, "--memory-swap", memory, "--pids-limit", "256", "--network", network,
        "--mount", f"type=bind,src={_folder(folder, 'folder')},dst=/login",
        "-e", "HOME=/home/codex", "-e", "CODEX_HOME=/login", "-e", "NO_COLOR=1", *_proxy_env(WEB_PROXY),
        image, "timeout", str(LOGIN_SECONDS), "codex", "-c", 'cli_auth_credentials_store="file"', "login", "--device-auth",
    ]


def parse_vibe(stdout: str) -> tuple[bool, str, int, int, bool]:
    """(ok, text, tokens_in, tokens_out, login_problem) from the one JSON line of vibe_entry.py or hubloop.py (the same
    shape). A refused key (401 from the AI) is a login problem; anything unreadable is a failure, never a guess."""
    try:
        data = json.loads((stdout or "").strip().splitlines()[-1])
        ok, text = bool(data.get("ok")), str(data.get("text") or "")
        tokens_in, tokens_out = int(data.get("tokens_in") or 0), int(data.get("tokens_out") or 0)
        error = str(data.get("error") or "")
    except (ValueError, IndexError, AttributeError, TypeError):
        return False, "No readable answer from the AI's program.", 0, 0, False
    login = bool(re.search(r"\b401\b|unauthori[sz]ed|invalid api key", error, re.I))
    if ok:
        return True, text.strip()[:MAX_REPORT], tokens_in, tokens_out, False
    reason = ("Not logged in: the AI refused the key (401)" if login
              else ("Too many steps: the step limit was reached." if data.get("outcome") == "steps"
                    else f"The AI's program stopped ({data.get('outcome')}): {error}".strip()))
    return False, reason[:2000], tokens_in, tokens_out, login


def result_of(text: str, failed: bool = False) -> tuple[str, str]:
    """(result, report) from an agent's answer, the same for every AI: a line `RESULT: <value>` among its last
    RESULT_LOOK lines (markdown around it does not count). A failed run is "failed"; an answer without the line is
    "none" (the hub asks the same AI once more for it). Whether the value fits the role, the hub decides."""
    lines = text.rstrip().splitlines()
    match, at = None, None
    filled = [i for i, line in enumerate(lines) if line.strip()][-RESULT_LOOK:]
    for i in reversed(filled):                    # the last RESULT line near the end, without markdown around it
        match = _MARKER.match(lines[i].strip().strip("*`_ ").strip())
        if match:
            at = i
            break
    report = "\n".join(lines[:at] + lines[at + 1:] if match else lines).strip()[:MAX_REPORT]
    if failed:
        return "failed", report or "The agent gave no valid result."
    if match is None:
        return "none", report
    return match.group(1), report
