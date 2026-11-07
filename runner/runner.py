"""The runner: asks the hub what to do and does it. Standard library only (urllib).

Now: sign-ins of Claude (link and code between the hub and `claude auth login`) and deleting the
Claude folders of users who disconnected. The agent runs themselves (claim, prompt, container,
result) are the next module. The runner always asks, the hub never calls it.

Environment: HUB_URL (e.g. http://web:8000), RUNNER_TOKEN (the token whose SHA-256 the hub knows),
HUB_CLAUDE_DIR (where the per-user Claude folders live, as seen by this process).
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

from . import launcher, login

LOGIN_TIMEOUT_AFTER_CODE = 90   # seconds Claude Code gets to accept the code
LINK_TIMEOUT = 30               # seconds until the sign-in prints its link
CHAT_TIMEOUT = 150              # seconds a test-chat answer may take


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
    def __init__(self, api, claude_base: str, prepare=launcher.prepare_folder, start_session=None,
                 clock=time.time, run_chat=None):
        self.api = api
        self.claude_base = Path(claude_base)
        self.prepare = prepare
        self.start_session = start_session or self._docker_session
        self.clock = clock
        self.run_chat = run_chat or self._run_chat
        self.sessions: dict[int, login.LoginSession] = {}

    def folder(self, user_id: int) -> str:
        return str(self.claude_base / str(int(user_id)))

    def _docker_session(self, user_id: int) -> login.LoginSession:
        command = launcher.build_login_command(user_id=user_id, claude_dir=self.folder(user_id))
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
        self.prepare(self.folder(user_id), user_id)
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
        waited_too_long = session.code_sent_at and self.clock() - session.code_sent_at > LOGIN_TIMEOUT_AFTER_CODE
        if exit_code is None and not waited_too_long:
            return
        success = exit_code == 0
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

    # --- TEMPORARY test chat (web/app/chat.py): one question, one answer, no tools, no project files
    def _run_chat(self, command: list[str], prompt: str):
        return subprocess.run(command, input=prompt, capture_output=True, text=True, timeout=CHAT_TIMEOUT)

    def handle_chat(self) -> None:
        job = self.api.call("POST", "/runner/chat/claim").get("job")
        if not job:
            return
        user_id, chat_id = job["user_id"], job["chat_id"]
        self.prepare(self.folder(user_id), user_id)
        command = launcher.build_chat_command(chat_id=chat_id, user_id=user_id, model=job["model"],
                                              claude_dir=self.folder(user_id))
        try:
            done = self.run_chat(command, job["prompt"])
            ok, text, tokens_in, tokens_out, login_problem = launcher.parse_chat_output(done.stdout)
            if not ok and done.returncode:
                text = f"{text} (exit code {done.returncode})".strip()
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "rm", "-f", f"agent-chat-{int(chat_id)}"], capture_output=True)
            ok, text, tokens_in, tokens_out, login_problem = False, "Timeout: no answer in time.", 0, 0, False
        if login_problem:   # Claude says we are not signed in: show the connection as expired
            self.api.call("POST", f"/runner/logins/{user_id}/expired")
        self.api.call("POST", f"/runner/chat/{chat_id}/finish", success="1" if ok else "0", answer=text,
                      tokens_in=tokens_in, tokens_out=tokens_out)

    def step(self) -> None:
        self.handle_wipes()
        self.handle_logins()
        self.handle_chat()


def main() -> None:
    base = os.environ.get("HUB_CLAUDE_DIR", "/data/claude")
    Path(base).mkdir(parents=True, exist_ok=True)
    os.chmod(base, 0o700)   # nobody but root may even list whose folders exist
    runner = Runner(Api(os.environ["HUB_URL"], os.environ["RUNNER_TOKEN"]), base)
    while True:
        try:
            runner.step()
        except Exception as error:   # the hub may be restarting: report and try again
            print(f"runner: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        time.sleep(2)


if __name__ == "__main__":
    main()
