"""The runner: asks the hub what to do and does it. Standard library only (urllib).

Agent runs (22.11.2026, KONZEPT-AGENTEN.md 10): no fixed time limit for work that moves on. Every run streams its
output; a Watch tells the hub every few seconds that it is going (with its new thoughts), keeps its ticket alive,
follows the hub's answer (run, pause, stop: `docker pause` freezes a run of a user who paused his agents, nothing is
ended) and ends a run only after a standstill (no output for a while) or the longest time of work. When the runner
starts it removes the containers of before and says hello: the hub queues their runs and chat answers again.

Also: sign-ins of Claude (link and code between the hub and `claude setup-token`; the token is kept encrypted,
tokens.py), API keys of other AIs (Mistral: checked with the provider and kept encrypted, tokens.ProviderKeys), the
manager chat and the agent runs (one container per question or run, Claude Code or Mistral Vibe, always with a
ticket instead of the credential: adapters.py), the work folders of the tasks and merging approved work
(workspace.py), restart, shutdown and backup of the Pi, and deleting the saved credentials of users who
disconnected. Every chat answer and every agent run runs in a thread of its own, so the loop goes on with sign-ins
and keys meanwhile. How many containers run at once the hub decides (the owner's setting "AI runs",
serversettings.ai_parallel): it hands out no job while all slots are taken. The runner always asks, the hub never
calls it.

Environment: HUB_URL (e.g. http://web:8000), RUNNER_TOKEN (the token whose SHA-256 the hub knows),
HUB_CLAUDE_DIR (where the per-user folders with the encrypted token live), HUB_TOKEN_KEY (the key of those files,
only here), HUB_TICKETS_DIR (the folder in memory shared with the egress proxy).
"""
import json
import os
import shutil
import subprocess
import tarfile
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import threading

from . import adapters, apikeys, codex, custom, launcher, login, mistral, models, tokens, view, workspace

LOGIN_TIMEOUT_AFTER_CODE = 90   # seconds Claude Code gets to accept the code
LINK_TIMEOUT = 30               # seconds until the sign-in prints its link
THOUGHTS_EVERY = 1.5            # seconds between two reports of new thoughts of a chat answer
POWER_TIMEOUT = 240             # seconds a manual backup may take (the nightly one needs a few seconds)
# The answer when a saved credential is there but this server can not read it: the server's fault, nothing is deleted.
UNREADABLE = "Server: the saved credential can not be read (HUB_TOKEN_KEY)."
LATER = "Server: the AI's sign-in service could not be reached to renew the sign-in; nothing was deleted."
DEVICE_LOGIN_SECONDS = launcher.LOGIN_SECONDS + 60   # a ChatGPT sign-in waits this long for the user at most
ALIVE_EVERY = 10        # seconds between two signs of life of a run to the hub (agents.DEAD_SECONDS is much more)
STOPPED = {"silence": "Ended: the AI wrote nothing for {minutes} minutes.",
           "limit": "Ended: the run reached the longest time of a run ({minutes} minutes of work)."}
LEFTOVERS = ("agent-run-", "agent-test-", "agent-chat-")   # containers of jobs; after a restart none of them is ours


class Api:
    """The runner side of routes/runner.py."""

    def __init__(self, base_url: str, token: str):
        self.base = base_url.rstrip("/")
        self.token = token

    def send(self, path: str, data: bytes, timeout: int = 300) -> dict:
        """POST raw bytes (a ZIP of a project's code, exports.py)."""
        request = urllib.request.Request(self.base + path, data=data, method="POST",
                                         headers={"Authorization": f"Bearer {self.token}",
                                                  "Content-Type": "application/zip"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as answer:
                return json.load(answer)
        except urllib.error.HTTPError as error:
            if error.code in (400, 409):
                return {"ok": False}
            raise

    def call(self, method: str, path: str, **form) -> dict:
        data = urllib.parse.urlencode(form).encode() if method == "POST" else None
        request = urllib.request.Request(self.base + path, data=data, method=method,
                                         headers={"Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(request, timeout=15) as answer:
                return json.load(answer)
        except urllib.error.HTTPError as error:   # 400/409 carry {"ok": false}; others are real problems
            if error.code in (400, 409):
                return {"ok": False}
            raise


class Thoughts:
    """The thoughts of one chat answer while it runs: read from the output by the adapter, sent to the hub at most every
    THOUGHTS_EVERY seconds (and once at the end). They are only shown, so a piece that does not arrive is no failure."""

    def __init__(self, api, chat_id: int, adapter, clock=time.time):
        self.api, self.chat_id, self.adapter, self.clock = api, int(chat_id), adapter, clock
        self.waiting, self.sent = "", clock()
        self.tools = None      # the tools the program named at its start (toolcheck.py); None: it named none we read

    def line(self, line: str) -> None:
        if self.tools is None and hasattr(self.adapter, "tools_seen"):
            self.tools = self.adapter.tools_seen(line)
        self.waiting += self.adapter.thought(line)
        if self.waiting.strip() and self.clock() - self.sent >= THOUGHTS_EVERY:
            self.flush()

    def flush(self) -> None:
        text, self.waiting = self.waiting, ""
        self.sent = self.clock()
        if text.strip():
            try:
                self.api.call("POST", f"/runner/chat/{self.chat_id}/thoughts", text=text)
            except (OSError, ValueError):
                pass


class Watch:
    """The runner's eye on one agent run (22.11.2026): `line` for every line of its output, `tick` about once a
    second while it runs. Tells the hub every ALIVE_EVERY seconds that the run is going (with the new thoughts) and
    keeps its ticket; follows the hub's answer: "pause" freezes the container (`docker pause`), "run" lets it go on,
    "stop" ends it. Ends it itself after `silence_seconds` without output or `max_seconds` of work; paused time counts
    for neither. `reason`: "" while it may go on, else silence, limit or stop."""

    def __init__(self, runner, run_id: int, ticket: str, adapter, name: str, limits: dict, clock=time.monotonic):
        self.runner, self.run_id, self.ticket, self.adapter, self.name = runner, int(run_id), ticket, adapter, name
        self.silence, self.longest = limits["silence_seconds"], limits["max_seconds"]
        self.clock = clock
        now = clock()
        self.last_output = self.last_tick = now
        self.last_alive = now - ALIVE_EVERY   # tell the hub at the first tick
        self.worked = 0.0
        self.paused = False
        self.reason = ""
        self.waiting = ""
        self.lock = threading.Lock()

    def line(self, line: str) -> None:
        with self.lock:
            self.last_output = self.clock()
            self.waiting += self.adapter.thought(line)

    def _docker(self, *args: str) -> bool:
        return self.runner.docker([*args, self.name]) == 0

    def tick(self) -> bool:
        now = self.clock()
        if not self.paused:
            self.worked += now - self.last_tick
        self.last_tick = now
        if now - self.last_alive >= ALIVE_EVERY:
            self.last_alive = now
            with self.lock:
                text, self.waiting = self.waiting, ""
            self.runner.tickets.touch(self.ticket)
            try:
                state = self.runner.api.call("POST", f"/runner/runs/{self.run_id}/alive", thoughts=text).get("state")
            except (OSError, ValueError):
                state = None                       # the hub restarts: go on, it hears from us again in a moment
            if state == "stop":
                self.reason = "stop"
                return False
            if state == "pause" and not self.paused and self._docker("pause"):
                self.paused = True
            elif state == "run" and self.paused and self._docker("unpause"):
                self.paused = False
                with self.lock:
                    self.last_output = now         # the standstill starts again after a pause
        if self.paused:
            return True
        with self.lock:
            quiet = now - self.last_output
        if quiet > self.silence:
            self.reason = "silence"
            return False
        if self.worked > self.longest:
            self.reason = "limit"
            return False
        return True


class Runner:
    def __init__(self, api, claude_base: str, vault=None, tickets=None, start_session=None,
                 clock=time.time, run_chat=None, run_power=None, keys=None, verifiers=None, work=None,
                 run_agent=None, background: bool = True, views=None, docker=None):
        self.api = api
        self.claude_base = Path(claude_base)
        self.vault = vault or tokens.Vault(claude_base, os.environ.get("HUB_TOKEN_KEY"))
        self.tickets = tickets or tokens.Tickets(os.environ.get("HUB_TICKETS_DIR", "/tickets"))
        self.start_session = start_session or self._docker_session
        self.clock = clock
        self.run_chat = run_chat or self._run_chat
        self.run_power = run_power or self._run_power
        self.keys = keys or tokens.ProviderKeys(claude_base, os.environ.get("HUB_TOKEN_KEY"))
        self.verifiers = verifiers or {"mistral": mistral, **{f"custom-{n}": custom for n in range(1, 9)}, "claude-api": apikeys.Verifier("claude-api"),
                                       "chatgpt-api": apikeys.Verifier("chatgpt-api")}   # check a key with its AI
        self.work = work or workspace.Workspace(os.environ.get("HUB_WORK_DIR", "/opt/agent-hub/work"))
        self.run_agent = run_agent or self._run_agent
        self._local = threading.local()   # the limits of the job this thread runs (launcher.checked)
        self.run_tests = self._run_tests
        self.run_login = self._run_login
        self.device_logins: set[int] = set()
        self.fetch_models = models.fetch
        self.model_checks: set[tuple[int, str]] = set()
        # The user's files (and for the manager chat the code) as read-only folders of each job (view.py)
        self.views = views or view.Views(self.work.base, os.environ.get("HUB_FILES_SOURCE"))
        self.background = background
        self.workers: list[threading.Thread] = []
        self.sessions: dict[int, login.LoginSession] = {}
        self.docker = docker or self._docker      # a docker command (pause, unpause, rm -f) -> exit code
        self.greeted = False                      # the hub heard that this runner started (handle_hello)

    @staticmethod
    def _docker(args: list[str]) -> int:
        return subprocess.run(["docker", *args], capture_output=True).returncode

    # --- a fresh start: the containers of the jobs of before are gone, the hub queues those jobs again
    def handle_hello(self) -> None:
        if self.greeted:
            return
        found = subprocess.run(["docker", "ps", "-aq", *[f"--filter=name={p}" for p in LEFTOVERS]],
                               capture_output=True, text=True)
        names = [n for n in (found.stdout or "").split() if n]
        if names:
            subprocess.run(["docker", "rm", "-f", *names], capture_output=True)
        self.api.call("POST", "/runner/hello")
        self.greeted = True

    def _docker_session(self, user_id: int) -> login.LoginSession:
        command = launcher.build_login_command(user_id=user_id)
        return login.LoginSession(command, f"agent-login-{int(user_id)}")

    def _end(self, user_id: int) -> None:
        session = self.sessions.pop(user_id, None)
        if session is not None:
            session.close()

    # --- sign-ins
    def handle_logins(self) -> None:
        pending = {item["user_id"]: item["login_url"] for item in self.api.call("GET", "/runner/logins")["logins"]}
        for user_id in [u for u in self.sessions if u not in pending]:
            self._end(user_id)              # cancelled or finished on the hub side
        for user_id, url in pending.items():
            session = self.sessions.get(user_id)
            if session is None:
                if url is None:
                    self._begin(user_id)
                else:                       # a link from before a restart of this runner cannot be resumed
                    self.api.call("POST", f"/runner/logins/{user_id}/done", success="0")
                continue
            self._continue(user_id, session)

    def _begin(self, user_id: int) -> None:
        session = self.start_session(user_id)
        link = session.url(LINK_TIMEOUT)
        if link is None or not self.api.call("POST", f"/runner/logins/{user_id}/url", url=link).get("ok"):
            session.close()
            self.api.call("POST", f"/runner/logins/{user_id}/done", success="0")
            return
        self.sessions[user_id] = session

    def _continue(self, user_id: int, session) -> None:
        code = self.api.call("POST", f"/runner/logins/{user_id}/code").get("code")
        if code:
            session.send_code(code)
        exit_code = session.exit_code()
        token = login.extract_token(session.output) if session.code_sent_at else None
        waited_too_long = session.code_sent_at and self.clock() - session.code_sent_at > LOGIN_TIMEOUT_AFTER_CODE
        if token is None and exit_code is None and not waited_too_long and not session.refused():
            return
        success = False
        if token is not None:
            try:
                self.vault.save(user_id, token)
                success = True
            except (OSError, ValueError, RuntimeError) as error:
                print(f"runner: could not save the token of user {user_id}: {type(error).__name__}", file=sys.stderr,
                      flush=True)
        token = None
        if not success:   # what the screen said, without anything secret (login.redacted_tail)
            print(f"runner: sign-in of user {user_id} failed (exit {exit_code}); screen: "
                  f"{login.redacted_tail(session.output)}", file=sys.stderr, flush=True)
        self._end(user_id)
        self.api.call("POST", f"/runner/logins/{user_id}/done", success="1" if success else "0")

    # --- disconnected users: delete their saved login
    def handle_wipes(self) -> None:
        for user_id in self.api.call("GET", "/runner/wipes")["user_ids"]:
            self._end(user_id)
            target = (self.claude_base / str(int(user_id))).resolve()
            if target.parent == self.claude_base.resolve() and target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
                if target.exists():   # not everything could be deleted: stay "wipe", try again next round
                    print(f"runner: could not delete {target}", file=sys.stderr, flush=True)
                    continue
            self.api.call("POST", f"/runner/wipes/{int(user_id)}/done")

    # --- expired or refused tokens are deleted on their own (Janis, 14.11.2026); the menu keeps "expired · renew"
    def handle_expired(self) -> None:
        for user_id in self.api.call("GET", "/runner/expired")["user_ids"]:
            if user_id not in self.sessions and self.vault.forget(int(user_id)):
                print(f"runner: deleted the expired token of user {int(user_id)}", file=sys.stderr, flush=True)

    # --- the manager chat (web/app/chat.py): one question, one answer, no project files
    def _run_chat(self, command: list[str], prompt: str, on_line=None):
        """Like subprocess.run with a timeout, but every line of the output goes to `on_line` while the container
        runs (the thoughts of the AI). The prompt is written from a thread, so a full pipe never blocks reading."""
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True)

        def feed():
            try:
                proc.stdin.write(prompt)
                proc.stdin.close()
            except OSError:   # the container ended before it read everything
                pass

        threading.Thread(target=feed, daemon=True).start()
        late = threading.Event()
        timer = threading.Timer(self._limits()["chat_seconds"], lambda: (late.set(), proc.kill()))
        timer.daemon = True
        timer.start()
        lines = []
        try:
            for line in proc.stdout:
                lines.append(line)
                if on_line is not None:
                    on_line(line)
            proc.wait()
        finally:
            timer.cancel()
        if late.is_set():
            raise subprocess.TimeoutExpired(command, self._limits()["chat_seconds"])
        return subprocess.CompletedProcess(command, proc.returncode, "".join(lines), "")

    # --- API keys (web/app/ai_link.py): check a pasted key with the provider, keep it encrypted, delete old ones
    def handle_keys(self) -> None:
        for item in self.api.call("POST", "/runner/keys/claim").get("keys", []):
            user_id, provider, api_key = int(item["user_id"]), item["provider"], item["key"]
            adapter = self.verifiers.get(provider)
            success = False
            if adapter is not None and tokens.KEY_PATTERNS.get(provider) and tokens.KEY_PATTERNS[provider].fullmatch(api_key):
                result = (adapter.verify(api_key, str(item.get("endpoint") or ""), item.get("lan") is True)
                          if provider.startswith("custom-") else adapter.verify(api_key))
                if result == "ok":
                    try:
                        self.keys.save(user_id, provider, api_key)
                        success = True
                    except (OSError, ValueError, RuntimeError) as error:
                        print(f"runner: could not save the {provider} key of user {user_id}: {type(error).__name__}",
                              file=sys.stderr, flush=True)
                else:
                    print(f"runner: {provider} key of user {user_id} not taken ({result})", file=sys.stderr, flush=True)
            api_key = None
            self.api.call("POST", f"/runner/keys/{user_id}/{provider}/done", success="1" if success else "0")

    def handle_key_wipes(self) -> None:
        for item in self.api.call("GET", "/runner/keys/wipes").get("wipes", []):
            user_id, provider = int(item["user_id"]), item["provider"]
            try:
                self.keys.forget(user_id, provider)
            except (OSError, ValueError) as error:
                print(f"runner: could not delete the {provider} key of user {user_id}: {type(error).__name__}",
                      file=sys.stderr, flush=True)
                continue
            self.api.call("POST", f"/runner/keys/{user_id}/{provider}/wiped")

    def _plan_check(self, user_id: int, provider: str, ok: bool, text: str) -> None:
        """ChatGPT said the plan does not include Codex (codex_entry.py: outcome "plan"): the menu shows it."""
        if not ok and provider == "chatgpt" and "(plan)" in (text or ""):
            self._report(f"/runner/keys/{int(user_id)}/chatgpt/noplan")

    @staticmethod
    def _key_name(provider: str, job: dict | None) -> str:
        """The saved connection a job of this AI uses: a further AI's place ("custom-3", from the job's route)."""
        if provider != "custom":
            return provider
        slot = ((job or {}).get("route") or {}).get("slot")
        return f"custom-{slot}" if isinstance(slot, int) and 1 <= slot <= 8 else "custom-0"   # custom-0: never saved

    def _expired(self, user_id: int, provider: str, credential: str = "plan", job: dict | None = None) -> None:
        """The AI refused the credential (or there is none): the menu shows it, a refused API key is deleted."""
        if credential == "api":   # the user's key next to the plan (its own connection)
            name = f"{provider}-api"
            self.keys.forget(int(user_id), name)
            self.api.call("POST", f"/runner/keys/{int(user_id)}/{name}/expired")
            return
        if provider == "claude":
            self.api.call("POST", f"/runner/logins/{int(user_id)}/expired")
            return
        name = self._key_name(provider, job)
        if name == "custom-0":
            return
        self.keys.forget(int(user_id), name)
        self.api.call("POST", f"/runner/keys/{int(user_id)}/{name}/expired")

    def _secret(self, adapter, user_id: int, credential: str = "plan", job: dict | None = None):
        """(secret, problem): the credential, or None and the reason. A missing one shows the AI as expired; one that
        is there but can not be read is the server's fault and stays (tokens.Unreadable). `credential` "api": the
        user's API key next to the plan (web/app/credentials.py) instead of the plan."""
        api = credential == "api" and adapter.provider in ("claude", "chatgpt")
        try:
            if api:
                secret = self.keys.load(user_id, f"{adapter.provider}-api")
            elif adapter.provider == "custom":   # the place of the further AI the job is for
                name = self._key_name("custom", job)
                secret = None if name == "custom-0" else self.keys.load(user_id, name)
            else:
                secret = adapter.secret(self, user_id)
        except tokens.Unreadable as error:
            print(f"runner: the saved {adapter.provider} credential of user {user_id} can not be read "
                  f"({error}); nothing deleted", file=sys.stderr, flush=True)
            return None, UNREADABLE
        except adapters.Later as error:
            print(f"runner: the {adapter.provider} sign-in of user {user_id} could not be renewed now ({error})",
                  file=sys.stderr, flush=True)
            return None, LATER
        if secret is None:   # no saved credential: the user links this AI again
            self._expired(user_id, adapter.provider, "api" if api else "plan", job)
            return None, "Not logged in: no saved credential. Please run /login"
        return secret, ""

    @staticmethod
    def _route(adapter, job: dict) -> dict:
        """What the ticket must know besides the credential: for an API key of ChatGPT that it is one."""
        if (job.get("credential") or "plan") == "api":
            return {"upstream": "api"} if adapter.provider == "chatgpt" else {}
        return adapter.route(job)

    def _view(self, name: str, job: dict, code: bool = False):
        """(files folder, code folder, view) of a job, or (None, None, None) when the view could not be made: the job
        then runs without them (the package says what the files are; nothing hangs on it). Give the view back with
        `self.views.release` when the job ends (view.py keeps it for the next job of the same content)."""
        try:
            repo = self.work.repo(int(job["project_id"])) if code else None
            root = self.views.acquire(int(job["project_id"]), job.get("files") or [], job.get("links") or [], repo,
                                      self._limits(job)["view_mb"] * 1024 ** 2)
            return str(root / "files"), (str(root / "code") if code else None), root
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, tarfile.TarError) as error:
            print(f"runner: view {name}: {type(error).__name__}", file=sys.stderr, flush=True)
            return None, None, None

    def _release(self, root) -> None:
        if root is not None:
            self.views.release(root)

    MAX_WORKERS = 16        # a safety net only: the hub's setting is the real limit

    def _start(self, target, job: dict) -> None:
        """Run a job in its own thread (in tests: right away). Whatever goes wrong in it, the hub hears the end."""
        if not self.background:
            self._guarded(target, job)
            return
        worker = threading.Thread(target=self._guarded, args=(target, job), daemon=True)
        self.workers.append(worker)
        worker.start()

    def _guarded(self, target, job: dict) -> None:
        """A job that breaks off reports a failure instead of waiting for the hub's time limit (15.11.2026 rule)."""
        try:
            target(job)
        except Exception as error:   # noqa: BLE001 - every job must end with a report
            print(f"runner: {target.__name__} broke off: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
            try:
                if "chat_id" in job:
                    self._report(f"/runner/chat/{int(job['chat_id'])}/finish", success="0",
                                 answer="The server could not run this question.", tokens_in=0, tokens_out=0)
                elif "run_id" in job:
                    self._finish_run(int(job["run_id"]), "failed", "The server could not run this job.")
            except Exception as again:   # noqa: BLE001 - the hub's time limit is the last net
                print(f"runner: could not report it: {type(again).__name__}", file=sys.stderr, flush=True)

    REPORT_TRIES = 5        # a result is reported again while the hub restarts (a deploy takes some seconds)
    REPORT_WAIT = 3

    def _report(self, path: str, **form) -> dict:
        for attempt in range(self.REPORT_TRIES):
            try:
                return self.api.call("POST", path, **form)
            except OSError:
                if attempt == self.REPORT_TRIES - 1:
                    raise
                time.sleep(self.REPORT_WAIT)
        return {}

    def busy(self) -> bool:
        self.workers = [w for w in self.workers if w.is_alive()]
        return len(self.workers) >= self.MAX_WORKERS

    def handle_chat(self) -> None:
        job = self.api.call("POST", "/runner/chat/claim").get("job")
        if job:
            self._start(self.do_chat, job)

    def do_chat(self, job: dict) -> None:
        user_id, chat_id = int(job["user_id"]), int(job["chat_id"])
        provider = job.get("provider") or "claude"
        adapter = adapters.ADAPTERS.get(provider)
        if adapter is None:   # an AI this runner has no adapter for (hub and runner of different versions)
            self.api.call("POST", f"/runner/chat/{chat_id}/finish", success="0",
                          answer="This AI is not available on the server.", tokens_in=0, tokens_out=0)
            return
        way = job.get("credential") or "plan"
        secret, problem = self._secret(adapter, user_id, way, job)
        if secret is None:
            self.api.call("POST", f"/runner/chat/{chat_id}/finish", success="0", answer=problem, tokens_in=0,
                          tokens_out=0)
            return
        files_dir, code_dir, root = (self._view(f"chat-{chat_id}", job, code=True) if job.get("project_id")
                                     else (None, None, None))
        ticket = self.tickets.issue(secret, provider, **self._route(adapter, job))
        secret = None
        thoughts = Thoughts(self.api, chat_id, adapter, self.clock)
        try:
            command = adapter.chat_command(chat_id=chat_id, user_id=user_id, model=job["model"], ticket=ticket,
                                           mode=job.get("mode", "all"), effort=job.get("effort") or "",
                                           files_dir=files_dir, code_dir=code_dir, images=job.get("images") is True,
                                           route=job.get("route"), hub_tools=job.get("hub_tools") or [],
                                           credential=job.get("credential") or "plan")
            command = launcher.apply_limits(command, self._limits(job))
            done = self.run_chat(command, job["prompt"], thoughts.line)
            thoughts.flush()
            ok, text, tokens_in, tokens_out, login_problem = adapter.parse_chat(done.stdout)
            if not ok and done.returncode:
                text = f"{text} (exit code {done.returncode})".strip()
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "rm", "-f", f"agent-chat-{chat_id}"], capture_output=True)
            ok, text, tokens_in, tokens_out, login_problem = False, "Timeout: no answer in time.", 0, 0, False
        finally:
            self.tickets.revoke(ticket)   # from here on the ticket is worth nothing
            self._release(root)
        if login_problem:   # the AI says we are not signed in: show the connection as expired
            self._expired(user_id, provider, job.get("credential") or "plan", job)
        self._plan_check(user_id, provider, ok, text)
        extra = {}
        if thoughts.tools is not None:   # what the program named, with what we asked of it (toolcheck.py)
            extra = {"tools_asked": ",".join(launcher.asked_tools(command)), "tools_seen": ",".join(thoughts.tools)}
        self._report(f"/runner/chat/{chat_id}/finish", success="1" if ok else "0", answer=text,
                     tokens_in=tokens_in, tokens_out=tokens_out, **extra)

    # --- agent runs (web/app/agents.py, runtask.py): one container per run in the task's work folder
    def _limits(self, job: dict | None = None) -> dict:
        """The container limits of the job this thread runs (set with a job, read by the run functions below)."""
        if job is not None:
            self._local.limits = launcher.checked(job.get("limits"))
        return getattr(self._local, "limits", None) or launcher.checked(None)

    def _run_agent(self, command: list[str], prompt: str, watch: Watch) -> tuple[str, int, str]:
        """Run an agent's container, its output line by line to `watch`, until it ends or the watch ends it:
        (output, exit code, why it was ended or ""). The prompt is written from a thread (a full pipe never blocks)."""
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True)
        lines: list[str] = []

        def feed():
            try:
                proc.stdin.write(prompt)
                proc.stdin.close()
            except OSError:
                pass

        def read():
            for line in proc.stdout:
                lines.append(line)
                watch.line(line)

        threading.Thread(target=feed, daemon=True).start()
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        while proc.poll() is None:
            time.sleep(1)
            if not watch.tick():
                self.docker(["rm", "-f", watch.name])
                proc.kill()
                break
        proc.wait()
        reader.join(timeout=10)
        return "".join(lines), proc.returncode or 0, watch.reason

    TEST_OUTPUT = 6000   # characters of the end of the tests' output that go to the hub

    def _run_tests(self, command: list[str]):
        return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=self._limits()["test_seconds"] + 30)

    def _tests(self, run_id: int, user_id: int, task_id: int, folder, net: str) -> tuple[int, str]:
        """Run the project's own tests (workspace.TEST_SCRIPT) in a container of their own: (exit code, end of the
        output). (-1, "") when the project has none. The folder goes back to the commit afterwards."""
        if not self.work.has_tests(task_id):
            return -1, ""
        try:
            limits = self._limits()
            done = self.run_tests(launcher.apply_limits(launcher.build_test_command(
                run_id=run_id, user_id=user_id, work_dir=str(folder), net=net, test_seconds=limits["test_seconds"]),
                limits))
            code, output = done.returncode, (done.stdout or "") + (done.stderr or "")
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "rm", "-f", f"agent-test-{run_id}"], capture_output=True)
            code, output = 124, "Timeout: the tests took too long."
        finally:
            try:
                self.work.reset(task_id)
            except (OSError, subprocess.SubprocessError):
                pass
        return code, output[-self.TEST_OUTPUT:]

    def handle_runs(self) -> None:
        job = self.api.call("POST", "/runner/claim", can_mac="0").get("job")
        if job:
            self._start(self.do_run, job)

    def _finish_run(self, run_id: int, result: str, report: str, tokens_in=0, tokens_out=0, seconds=0, **extra) -> None:
        """Report a run. `extra`: diff_stat, diff (what the task changed), tests_exit and tests (the hub's test run)."""
        self._report(f"/runner/runs/{run_id}/finish", result=result, report=report,
                     tokens_in=tokens_in, tokens_out=tokens_out, seconds=seconds, **extra)

    def _stopped(self, reason: str) -> str:
        limits = self._limits()
        seconds = limits["silence_seconds"] if reason == "silence" else limits["max_seconds"]
        return STOPPED[reason].format(minutes=seconds // 60)

    def do_run(self, job: dict) -> None:
        run_id, user_id, task_id = int(job["run_id"]), int(job["user_id"]), int(job["task_id"])
        role, provider = job["role"], job.get("provider") or "claude"
        adapter = adapters.ADAPTERS.get(provider)
        if adapter is None:
            return self._finish_run(run_id, "failed", "This AI is not available on the server.")
        limits = self._limits(job)
        way = job.get("credential") or "plan"
        secret, problem = self._secret(adapter, user_id, way, job)
        if secret is None:
            return self._finish_run(run_id, "failed", problem)
        if job.get("mode") == "brief":
            return self._brief_run(job, adapter, secret)
        try:
            folder, conflicts = self.work.prepare(task_id, int(job["project_id"]), job["branch"], sync=job.get("sync") is True)
            launcher.prepare_folder(str(folder), user_id, recursive=True)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            print(f"runner: work folder of task {task_id}: {type(error).__name__}", file=sys.stderr, flush=True)
            return self._finish_run(run_id, "failed", "The work folder could not be prepared.")
        prompt = job["prompt"]
        if conflicts and job.get("conflict_note"):   # the text comes from the hub (prompts.CONFLICTS); only the names here
            prompt += "\n\n" + str(job["conflict_note"]).replace("{files}", "\n".join(conflicts))
        files_dir, _, root = self._view(f"run-{run_id}", job)
        ticket = self.tickets.issue(secret, provider, **self._route(adapter, job))
        secret = None
        started = self.clock()
        try:
            command = adapter.run_command(run_id=run_id, user_id=user_id, model=job["model"], ticket=ticket,
                                          net=job.get("net", "together"), effort=job.get("effort") or "",
                                          work_dir=str(folder), files_dir=files_dir,
                                          images=job.get("images") is True, route=job.get("route"),
                                          hub_tools=job.get("hub_tools") or [], credential=way)
            command = launcher.apply_limits(command, limits)
            watch = Watch(self, run_id, ticket, adapter, f"agent-run-{run_id}", limits)
            output, code, stopped = self.run_agent(command, prompt, watch)
            ok, text, tokens_in, tokens_out, login_problem = adapter.parse_run(output)
        finally:
            self.tickets.revoke(ticket)
            self._release(root)
        if stopped == "stop":
            return                                   # the hub gave the run up (its task was cancelled)
        if login_problem:
            self._expired(user_id, provider, way, job)
        self._plan_check(user_id, provider, ok, text)
        if stopped:
            result, report = "stopped", self._stopped(stopped)
        else:
            result, report = launcher.result_of(text, failed=not ok)
        extra = {}
        if role in ("programmer", "tester"):   # the runner commits from outside: the run never sees .git
            try:
                committed = self.work.commit(task_id, job["branch"], f"Task {task_id}: {role} (run {run_id})")
                extra["committed"] = "1" if committed else "0"
                extra["diff_stat"], extra["diff"] = self.work.diff(task_id)
            except (OSError, subprocess.SubprocessError) as error:
                print(f"runner: commit of task {task_id} failed: {type(error).__name__}", file=sys.stderr, flush=True)
                report = (report + "\n\n(The hub could not save the changes.)").strip()
                result = "failed"
        if role == "programmer" and conflicts and result != "failed":
            left = self.work.markers(task_id, conflicts)
            if left:
                extra["markers"] = "\n".join(left)
        if role == "programmer" and result in ("done", "none") and "markers" not in extra:
            extra["tests_exit"], extra["tests"] = self._tests(run_id, user_id, task_id, folder, job.get("net", "apart"))
        self._finish_run(run_id, result, report, tokens_in, tokens_out, int(self.clock() - started), **extra)

    def _brief_run(self, job: dict, adapter, secret: str) -> None:
        """A run that needs no tools (the reviewer of a small change, the manager's short jobs): one answer, no work
        folder, no files, nothing to commit; watched like every run."""
        run_id, user_id = int(job["run_id"]), int(job["user_id"])
        limits = self._limits(job)
        way = job.get("credential") or "plan"
        ticket = self.tickets.issue(secret, adapter.provider, **self._route(adapter, job))
        started = self.clock()
        try:
            command = adapter.brief_command(run_id=run_id, user_id=user_id, model=job["model"], ticket=ticket,
                                            effort=job.get("effort") or "", route=job.get("route"), credential=way)
            command = launcher.apply_limits(command, limits)
            watch = Watch(self, run_id, ticket, adapter, f"agent-run-{run_id}", limits)
            output, code, stopped = self.run_agent(command, job["prompt"], watch)
            ok, text, tokens_in, tokens_out, login_problem = adapter.parse_chat(output)
        finally:
            self.tickets.revoke(ticket)
        if stopped == "stop":
            return
        if login_problem:
            self._expired(user_id, adapter.provider, way, job)
        result, report = ("stopped", self._stopped(stopped)) if stopped else launcher.result_of(text, failed=not ok)
        if job.get("purpose") in ("decide", "explain", "doc") and result == "none":
            result = "done"                          # the manager's jobs are read for their markers, not a RESULT line
        self._finish_run(run_id, result, report, tokens_in, tokens_out, int(self.clock() - started))

    # --- ChatGPT sign-in with a one-time code (runner/codex.py): one container per sign-in, in a thread of its own
    def handle_device_logins(self) -> None:
        wanted = {int(i["user_id"]) for i in self.api.call("GET", "/runner/device-logins").get("logins", [])}
        for user_id in [u for u in self.device_logins if u not in wanted]:   # the user closed the dialog
            subprocess.run(["docker", "rm", "-f", f"agent-login-chatgpt-{user_id}"], capture_output=True)
            self.device_logins.discard(user_id)
        for user_id in wanted - self.device_logins:
            self.device_logins.add(user_id)
            self._start(self.do_device_login, {"user_id": user_id})

    def _login_folder(self, user_id: int) -> Path:
        return self.claude_base / "keys" / "chatgpt-login" / str(int(user_id))

    def _run_login(self, command: list[str], on_line) -> int:
        proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True)
        try:
            for line in proc.stdout:
                on_line(line)
            return proc.wait(timeout=DEVICE_LOGIN_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            return -9

    def do_device_login(self, job: dict) -> None:
        """Show the link and code of `codex login --device-auth`, wait for the user at OpenAI, keep the tokens."""
        user_id = int(job["user_id"])
        folder = self._login_folder(user_id)
        success = False
        try:
            shutil.rmtree(folder, ignore_errors=True)
            launcher.prepare_folder(str(folder), user_id)
            screen, told = [], []

            def on_line(line: str) -> None:
                screen.append(line)
                found = codex.login_prompt("".join(screen))
                if found and not told:
                    told.append(found)
                    self._report(f"/runner/device-logins/{user_id}/chatgpt/url", url=found[0], code=found[1])
            self.run_login(launcher.build_codex_login_command(user_id=user_id, folder=str(folder)), on_line)
            auth = folder / "auth.json"
            if auth.is_file() and not auth.is_symlink():
                kept = codex.read_auth(auth.read_text())
                self.keys.save(user_id, "chatgpt", codex.dumps(kept))
                success = True
            else:
                print(f"runner: ChatGPT sign-in of user {user_id} ended without tokens", file=sys.stderr, flush=True)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            print(f"runner: ChatGPT sign-in of user {user_id}: {type(error).__name__}", file=sys.stderr, flush=True)
        finally:
            shutil.rmtree(folder, ignore_errors=True)   # the plain tokens never stay on the card
            self.device_logins.discard(user_id)
        self._report(f"/runner/keys/{user_id}/chatgpt/done", success="1" if success else "0")

    # --- the models each user's AI offers (runner/models.py, web/app/models.py), once a day
    def handle_model_checks(self) -> None:
        for item in self.api.call("GET", "/runner/model-checks").get("checks", []):
            key = (int(item["user_id"]), str(item["provider"]))
            if key not in self.model_checks:
                self.model_checks.add(key)
                self._start(self.do_model_check, {"user_id": key[0], "provider": key[1]})

    def do_model_check(self, job: dict) -> None:
        user_id, provider = int(job["user_id"]), job["provider"]
        raw = None
        try:
            adapter = adapters.ADAPTERS.get(provider)
            secret = self._secret(adapter, user_id)[0] if adapter else None
            if secret is not None:
                raw = (self._chatgpt_models(user_id, adapter, secret) if provider == "chatgpt"
                       else self.fetch_models(provider, secret))
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            print(f"runner: model list of {provider} for user {user_id}: {type(error).__name__}", file=sys.stderr,
                  flush=True)
        finally:
            self.model_checks.discard((user_id, provider))
        self._report(f"/runner/models/{user_id}/{provider}", models=json.dumps(raw) if raw else "")

    def _chatgpt_models(self, user_id: int, adapter, secret: str):
        """Codex itself asks for the account's models (job "models" of codex_entry.py), with a ticket."""
        ticket = self.tickets.issue(secret, "chatgpt", **adapter.route({"user_id": user_id}))
        try:
            command = launcher.build_codex_command(name=f"agent-chat-{900000000 + user_id}", user_id=user_id, model="",
                                                   effort="", auth=adapter._auth(ticket, user_id), job="models")
            done = subprocess.run(command, input="", capture_output=True, text=True, timeout=180)
        finally:
            self.tickets.revoke(ticket)
        line = (done.stdout or "").strip().splitlines()[-1:] or ["{}"]
        listed = json.loads(line[0]).get("models")
        return listed if isinstance(listed, list) else None

    def handle_merges(self) -> None:
        """Approved tasks: merge their branch into the project's main, then the manager documents."""
        for item in self.api.call("GET", "/runner/merges").get("merges", []):
            task_id = int(item["task_id"])
            try:
                ok = self.work.merge(task_id, int(item["project_id"]), item["branch"])
            except (OSError, subprocess.SubprocessError) as error:
                print(f"runner: merge of task {task_id}: {type(error).__name__}", file=sys.stderr, flush=True)
                ok = False
            self.api.call("POST", f"/runner/merges/{task_id}/done", success="1" if ok else "0")

    # --- the project's code as a ZIP for the user (web/app/exports.py): main or a task's branch, made with git archive
    def handle_exports(self) -> None:
        answer = self.api.call("GET", "/runner/exports")
        limit = int(answer.get("limit") or 0)
        for item in answer.get("exports", []):
            export_id = int(item["id"])
            try:
                data = self.work.archive(int(item["project_id"]), str(item["ref"]))
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                print(f"runner: export {export_id}: {type(error).__name__}", file=sys.stderr, flush=True)
                data = b""
            if limit and len(data) > limit:
                data = b""                                  # too big: the hub says so (serversettings.export_mb)
            self.api.send(f"/runner/exports/{export_id}", data)

    def handle_cleanups(self) -> None:
        """Folders of finished tasks, and everything of deleted projects (their code and their tasks' folders): the
        hub forgets a deleted project only when its folders are really gone."""
        data = self.api.call("GET", "/runner/cleanups")
        for task_id in data.get("task_ids", []):
            self.work.remove(int(task_id))
        for item in data.get("wipes", []):
            kind, ref = item.get("kind"), int(item.get("ref", 0))
            remove = {"task": self.work.remove,
                      "project": lambda ref: self.work.remove_project(ref) and self.views.remove_project(ref)}.get(kind)
            if remove is None or ref < 1:
                continue
            if not remove(ref):   # not everything could be deleted: it stays queued, try again next round
                print(f"runner: could not delete the folders of {kind} {ref}", file=sys.stderr, flush=True)
                continue
            self.api.call("POST", "/runner/cleanups/done", kind=kind, ref=ref)

    # --- restart, shutdown or backup of the Pi, asked for by the owner (web/app/power.py)
    def _run_power(self, command: list[str]):
        return subprocess.run(command, capture_output=True, text=True, timeout=POWER_TIMEOUT)

    def handle_power(self) -> None:
        job = self.api.call("POST", "/runner/power/claim")
        if job.get("action"):   # in a thread: a backup takes minutes and must not stop sign-ins and chats
            self._start(self.do_power, job)

    def do_power(self, job: dict) -> None:
        action = job.get("action")
        try:
            command = launcher.build_power_command(action)
        except ValueError:
            print(f"runner: ignored unknown power action {action!r}", file=sys.stderr, flush=True)
            return
        print(f"runner: {action} of the Pi on the owner's request", file=sys.stderr, flush=True)
        try:
            done = self.run_power(command)
            success, problem = done.returncode == 0, (done.stderr or "").strip()
        except subprocess.TimeoutExpired:
            success, problem = False, "timeout"
        if not success:
            print(f"runner: {action} failed: {problem}", file=sys.stderr, flush=True)
        if action == "backup" and job.get("id"):   # restart and shutdown end this very Pi: nothing to report
            self.api.call("POST", f"/runner/power/{int(job['id'])}/result", success="1" if success else "0")

    def handle_wake(self) -> None:
        """Switch a device on (Wake-on-LAN): the hub hands out each MAC once (web/app/devices.claim_wake)."""
        mac = self.api.call("POST", "/runner/wake/claim").get("mac")
        if not mac:
            return
        try:
            command = launcher.build_wake_command(mac)
        except ValueError:
            print("runner: ignored a bad MAC for waking", file=sys.stderr, flush=True)
            return
        try:
            done = self.run_power(command)
            if done.returncode:
                print(f"runner: waking failed: {(done.stderr or '').strip()[:200]}", file=sys.stderr, flush=True)
        except subprocess.TimeoutExpired:
            print("runner: waking timed out", file=sys.stderr, flush=True)

    def step(self) -> None:
        self.handle_hello()
        self.handle_power()
        self.handle_wake()
        self.handle_wipes()
        self.handle_expired()
        self.handle_key_wipes()
        self.handle_keys()
        self.handle_logins()
        self.handle_device_logins()
        self.handle_model_checks()
        self.handle_merges()
        self.handle_cleanups()
        self.handle_exports()
        if self.busy():
            return
        self.handle_chat()
        self.handle_runs()


def main() -> None:
    base = os.environ.get("HUB_CLAUDE_DIR", "/data/claude")
    Path(base).mkdir(parents=True, exist_ok=True)
    os.chmod(base, 0o700)   # nobody but root may even list whose folders exist
    if not os.environ.get("HUB_TOKEN_KEY"):
        print("runner: HUB_TOKEN_KEY is not set, Claude can not be linked or used", file=sys.stderr, flush=True)
    work = os.environ.get("HUB_WORK_DIR", "/opt/agent-hub/work")
    Path(work).mkdir(parents=True, exist_ok=True)
    os.chmod(work, 0o700)   # the projects' code and the tasks' folders: only root (and the run of each task)
    runner = Runner(Api(os.environ["HUB_URL"], os.environ["RUNNER_TOKEN"]), base)
    runner.views.clear()   # views of jobs that were going when the runner stopped
    runner.tickets.sweep(max_age=0)   # no run is going yet: tickets from before a restart are void
    while True:
        try:
            runner.step()
        except Exception as error:   # the hub may be restarting: report and try again
            print(f"runner: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        time.sleep(2)


if __name__ == "__main__":
    main()
