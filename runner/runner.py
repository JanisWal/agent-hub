"""The runner: asks the hub what to do and does it. Standard library only (urllib).

Now: sign-ins of Claude (link and code between the hub and `claude setup-token`; the token is kept encrypted,
tokens.py), API keys of other AIs (Mistral: checked with the provider and kept encrypted, tokens.ProviderKeys), the
manager chat and the agent runs (one container per question or run, Claude Code or Mistral Vibe, always with a
ticket instead of the credential: adapters.py), the work folders of the tasks and merging approved work
(workspace.py), restart, shutdown and backup of the Pi, and deleting the saved credentials of users who
disconnected. An agent run takes minutes, so it runs in a thread of its own; meanwhile the loop goes on with sign-ins
and keys, but starts no chat (the Pi has room for one big container at a time; the hub lets the question wait). The runner always asks, the hub never
calls it.

Environment: HUB_URL (e.g. http://web:8000), RUNNER_TOKEN (the token whose SHA-256 the hub knows),
HUB_CLAUDE_DIR (where the per-user folders with the encrypted token live), HUB_TOKEN_KEY (the key of those files,
only here), HUB_TICKETS_DIR (the folder in memory shared with the egress proxy).
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import threading

from . import adapters, launcher, login, mistral, tokens, workspace

LOGIN_TIMEOUT_AFTER_CODE = 90   # seconds Claude Code gets to accept the code
LINK_TIMEOUT = 30               # seconds until the sign-in prints its link
CHAT_TIMEOUT = 200              # seconds a chat answer may take (a web search takes several steps)
RUN_TIMEOUT = 1100              # seconds an agent run may take (the hub gives up after 20 minutes)
POWER_TIMEOUT = 240             # seconds a manual backup may take (the nightly one needs a few seconds)


class Api:
    """The runner side of routes/runner.py."""

    def __init__(self, base_url: str, token: str):
        self.base = base_url.rstrip("/")
        self.token = token

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


class Runner:
    def __init__(self, api, claude_base: str, vault=None, tickets=None, start_session=None,
                 clock=time.time, run_chat=None, run_power=None, keys=None, verifiers=None, work=None,
                 run_agent=None, background: bool = True):
        self.api = api
        self.claude_base = Path(claude_base)
        self.vault = vault or tokens.Vault(claude_base, os.environ.get("HUB_TOKEN_KEY"))
        self.tickets = tickets or tokens.Tickets(os.environ.get("HUB_TICKETS_DIR", "/tickets"))
        self.start_session = start_session or self._docker_session
        self.clock = clock
        self.run_chat = run_chat or self._run_chat
        self.run_power = run_power or self._run_power
        self.keys = keys or tokens.ProviderKeys(claude_base, os.environ.get("HUB_TOKEN_KEY"))
        self.verifiers = verifiers or {"mistral": mistral}   # check a pasted API key with its provider: verify()
        self.work = work or workspace.Workspace(os.environ.get("HUB_WORK_DIR", "/opt/agent-hub/work"))
        self.run_agent = run_agent or self._run_agent
        self.background = background
        self.agent_thread: threading.Thread | None = None
        self.sessions: dict[int, login.LoginSession] = {}

    def folder(self, user_id: int) -> str:
        return str(self.claude_base / str(int(user_id)))

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
                self.vault.clear_old(user_id)   # the files of the old kind of login go
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

    # --- the chat window (web/app/chat.py): one question, one answer, no tools, no project files
    def _run_chat(self, command: list[str], prompt: str):
        return subprocess.run(command, input=prompt, capture_output=True, text=True, timeout=CHAT_TIMEOUT)

    # --- API keys (web/app/ai_link.py): check a pasted key with the provider, keep it encrypted, delete old ones
    def handle_keys(self) -> None:
        for item in self.api.call("POST", "/runner/keys/claim").get("keys", []):
            user_id, provider, api_key = int(item["user_id"]), item["provider"], item["key"]
            adapter = self.verifiers.get(provider)
            success = False
            if adapter is not None and tokens.KEY_PATTERNS.get(provider) and tokens.KEY_PATTERNS[provider].fullmatch(api_key):
                result = adapter.verify(api_key)
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

    def _expired(self, user_id: int, provider: str) -> None:
        """The AI refused the credential (or there is none): the menu shows it, a refused API key is deleted."""
        if provider == "claude":
            self.api.call("POST", f"/runner/logins/{int(user_id)}/expired")
        else:
            self.keys.forget(int(user_id), provider)
            self.api.call("POST", f"/runner/keys/{int(user_id)}/{provider}/expired")

    def handle_chat(self) -> None:
        job = self.api.call("POST", "/runner/chat/claim").get("job")
        if not job:
            return
        user_id, chat_id = int(job["user_id"]), int(job["chat_id"])
        provider = job.get("provider") or "claude"
        adapter = adapters.ADAPTERS.get(provider)
        secret = adapter.secret(self, user_id) if adapter else None
        if secret is None:   # no saved credential (or the key changed): the user links this AI again
            self._expired(user_id, provider)
            self.api.call("POST", f"/runner/chat/{chat_id}/finish", success="0",
                          answer="Not logged in: no saved token. Please run /login", tokens_in=0, tokens_out=0)
            return
        ticket = self.tickets.issue(secret, provider)
        secret = None
        try:
            command = adapter.chat_command(chat_id=chat_id, user_id=user_id, model=job["model"], ticket=ticket,
                                           mode=job.get("mode", "all"), effort=job.get("effort") or "")
            done = self.run_chat(command, job["prompt"])
            ok, text, tokens_in, tokens_out, login_problem = adapter.parse_chat(done.stdout)
            if not ok and done.returncode:
                text = f"{text} (exit code {done.returncode})".strip()
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "rm", "-f", f"agent-chat-{chat_id}"], capture_output=True)
            ok, text, tokens_in, tokens_out, login_problem = False, "Timeout: no answer in time.", 0, 0, False
        finally:
            self.tickets.revoke(ticket)   # from here on the ticket is worth nothing
        if login_problem:   # the AI says we are not signed in: show the connection as expired
            self._expired(user_id, provider)
        self.api.call("POST", f"/runner/chat/{chat_id}/finish", success="1" if ok else "0", answer=text,
                      tokens_in=tokens_in, tokens_out=tokens_out)

    # --- agent runs (web/app/agents.py, runtask.py): one container per run in the task's work folder
    def _run_agent(self, command: list[str], prompt: str):
        return subprocess.run(command, input=prompt, capture_output=True, text=True, timeout=RUN_TIMEOUT)

    def agent_busy(self) -> bool:
        return self.agent_thread is not None and self.agent_thread.is_alive()

    def handle_runs(self) -> None:
        job = self.api.call("POST", "/runner/claim", can_mac="0").get("job")
        if not job:
            return
        if self.background:
            self.agent_thread = threading.Thread(target=self.do_run, args=(job,), daemon=True)
            self.agent_thread.start()
        else:
            self.do_run(job)

    def _finish_run(self, run_id: int, result: str, report: str, tokens_in=0, tokens_out=0, seconds=0) -> None:
        self.api.call("POST", f"/runner/runs/{run_id}/finish", result=result, report=report,
                      tokens_in=tokens_in, tokens_out=tokens_out, seconds=seconds)

    def do_run(self, job: dict) -> None:
        run_id, user_id, task_id = int(job["run_id"]), int(job["user_id"]), int(job["task_id"])
        role, provider = job["role"], job.get("provider") or "claude"
        adapter = adapters.ADAPTERS.get(provider)
        secret = adapter.secret(self, user_id) if adapter else None
        if secret is None:
            self._expired(user_id, provider)
            return self._finish_run(run_id, "failed", "Not logged in: no saved credential.")
        try:
            folder = self.work.prepare(task_id, int(job["project_id"]), job["branch"])
            launcher.prepare_folder(str(folder), user_id, recursive=True)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            print(f"runner: work folder of task {task_id}: {type(error).__name__}", file=sys.stderr, flush=True)
            return self._finish_run(run_id, "failed", "The work folder could not be prepared.")
        ticket = self.tickets.issue(secret, provider)
        secret = None
        started = self.clock()
        try:
            command = adapter.run_command(run_id=run_id, user_id=user_id, model=job["model"], ticket=ticket,
                                          net=job.get("net", "together"), effort=job.get("effort") or "",
                                          work_dir=str(folder))
            done = self.run_agent(command, job["prompt"])
            ok, text, tokens_in, tokens_out, login_problem = adapter.parse_run(done.stdout)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "rm", "-f", f"agent-run-{run_id}"], capture_output=True)
            ok, text, tokens_in, tokens_out, login_problem = False, "Timeout: the run took too long.", 0, 0, False
        finally:
            self.tickets.revoke(ticket)
        if login_problem:
            self._expired(user_id, provider)
        result, report = launcher.result_of(role, text, failed=not ok)
        if role in ("programmer", "tester"):   # the runner commits from outside: the run never sees .git
            try:
                self.work.commit(task_id, job["branch"], f"Task {task_id}, round {job.get('round', 1)}: {role}")
            except (OSError, subprocess.SubprocessError) as error:
                print(f"runner: commit of task {task_id} failed: {type(error).__name__}", file=sys.stderr, flush=True)
                report = (report + "\n\n(The hub could not save the changes.)").strip()
                result = "failed"
        self._finish_run(run_id, result, report, tokens_in, tokens_out, int(self.clock() - started))

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

    def handle_cleanups(self) -> None:
        for task_id in self.api.call("GET", "/runner/cleanups").get("task_ids", []):
            self.work.remove(int(task_id))

    # --- restart, shutdown or backup of the Pi, asked for by the owner (web/app/power.py)
    def _run_power(self, command: list[str]):
        return subprocess.run(command, capture_output=True, text=True, timeout=POWER_TIMEOUT)

    def handle_power(self) -> None:
        job = self.api.call("POST", "/runner/power/claim")
        action = job.get("action")
        if not action:
            return
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

    def step(self) -> None:
        self.handle_power()
        self.handle_wipes()
        self.handle_expired()
        self.handle_key_wipes()
        self.handle_keys()
        self.handle_logins()
        if self.agent_busy():
            return              # one big container at a time: chat and the next run wait for this run
        self.handle_chat()
        self.handle_merges()
        self.handle_cleanups()
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
    runner.tickets.sweep(max_age=0)   # no run is going yet: tickets from before a restart are void
    while True:
        try:
            runner.step()
        except Exception as error:   # the hub may be restarting: report and try again
            print(f"runner: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        time.sleep(2)


if __name__ == "__main__":
    main()
