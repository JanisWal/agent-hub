"""The runner's sign-in and wipe logic with a fake hub and a fake terminal (no Docker needed).

    docker compose run --rm --no-deps -v "$PWD/runner:/app/runner" web python -W ignore -m unittest runner.test_runner
"""
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

from runner import launcher, login, runner

LINK = "https://claude.com/cai/oauth/authorize?code=true&client_id=abc&state=xyz"
TOKEN = "sk-ant-oat01-" + "t" * 80


class FakeVault:
    """The encrypted store without encryption: what was saved for whom, and which old files were cleared."""
    def __init__(self, saved=None):
        self.saved, self.cleared = dict(saved or {}), []

    def save(self, user_id, token):
        self.saved[user_id] = token

    def load(self, user_id):
        return self.saved.get(user_id)

    def clear_old(self, user_id):
        self.cleared.append(user_id)

    def forget(self, user_id):
        return self.saved.pop(user_id, None) is not None


class FakeTickets:
    def __init__(self):
        self.issued, self.revoked = [], []

    def issue(self, token, provider="claude"):
        ticket = "hubrun-" + str(len(self.issued)).rjust(43, "x")
        self.issued.append((ticket, token))
        return ticket

    def revoke(self, ticket):
        self.revoked.append(ticket)


class FakeApi:
    def __init__(self):
        self.logins, self.wipes, self.codes, self.calls, self.chat_job = [], [], {}, [], None
        self.power, self.expired = None, []

    def call(self, method, path, **form):
        self.calls.append((method, path, form))
        if path == "/runner/wake/claim":
            return {"ok": True, "mac": getattr(self, "wake", None)}
        if path == "/runner/power/claim":
            return {"ok": True, "id": 7 if self.power else None, "action": self.power}
        if path == "/runner/chat/claim":
            return {"ok": True, "job": self.chat_job}
        if path == "/runner/logins":
            return {"ok": True, "logins": self.logins}
        if path == "/runner/wipes":
            return {"ok": True, "user_ids": self.wipes}
        if path == "/runner/expired":
            return {"ok": True, "user_ids": self.expired}
        if path.endswith("/code"):
            return {"ok": True, "code": self.codes.pop(int(path.split("/")[3]), None)}
        return {"ok": True}

    def posted(self, suffix):
        return [form for method, path, form in self.calls if path.endswith(suffix)]


class FakeSession:
    def __init__(self, link=LINK):
        self.link, self.sent, self.closed, self.exit, self.code_sent_at = link, [], False, None, None
        self.output = "Paste code here if prompted > "

    def url(self, timeout):
        return self.link

    def send_code(self, code):
        self.sent.append(code)
        self.code_sent_at = 100.0

    def exit_code(self):
        return self.exit

    def refused(self):
        return "OAuth error" in self.output

    def close(self):
        self.closed = True


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name) / "claude"
        self.base.mkdir()
        self.api, self.made, self.now = FakeApi(), {}, [100.0]
        self.vault = FakeVault()

        def start(user_id):
            self.made[user_id] = FakeSession()
            return self.made[user_id]

        self.runner = runner.Runner(self.api, str(self.base), vault=self.vault, tickets=FakeTickets(),
                                    start_session=start, clock=lambda: self.now[0], background=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_power_requests_run_one_fixed_command(self):
        ran = []
        self.runner.run_power = lambda command: ran.append(command) or types.SimpleNamespace(returncode=0, stderr="")
        self.runner.handle_power()
        self.assertEqual(ran, [])                                               # nothing asked: nothing happens
        self.api.power = "reboot"
        self.runner.handle_power()
        self.assertEqual(ran, [launcher.build_power_command("reboot")])

    def test_waking_sends_one_fixed_command_with_the_checked_mac(self):
        ran = []
        self.runner.run_power = lambda command: ran.append(command) or types.SimpleNamespace(returncode=0, stderr="")
        self.runner.handle_wake()
        self.assertEqual(ran, [])
        self.api.wake = "dc:a6:32:01:02:03"
        self.runner.handle_wake()
        self.assertEqual(ran, [launcher.build_wake_command("dc:a6:32:01:02:03")])
        self.api.wake = "dc:a6:32:01:02:03; rm -rf /"
        self.runner.handle_wake()
        self.assertEqual(len(ran), 1)                                          # a bad MAC is never sent

    def test_a_backup_reports_how_it_ended(self):
        for code, expected in ((0, "1"), (1, "0")):
            self.api.calls.clear()
            self.runner.run_power = lambda command, code=code: types.SimpleNamespace(returncode=code, stderr="")
            self.api.power = "backup"
            self.runner.handle_power()
            self.assertEqual(self.api.posted("/7/result"), [{"success": expected}])

    def test_a_backup_that_takes_too_long_is_reported_as_failed(self):
        def too_slow(command):
            raise subprocess.TimeoutExpired(command, 240)
        self.runner.run_power = too_slow
        self.api.power = "backup"
        self.runner.handle_power()
        self.assertEqual(self.api.posted("/7/result"), [{"success": "0"}])

    def test_restart_and_shutdown_report_nothing(self):
        self.runner.run_power = lambda command: types.SimpleNamespace(returncode=0, stderr="")
        for action in ("reboot", "poweroff"):
            self.api.power = action
            self.runner.handle_power()
        self.assertEqual(self.api.posted("/result"), [])

    def test_unknown_power_actions_are_ignored(self):
        ran = []
        self.runner.run_power = lambda command: ran.append(command)
        self.api.power = "format-everything"
        self.runner.handle_power()
        self.assertEqual(ran, [])

    def test_a_failing_power_command_does_not_stop_the_runner(self):
        self.runner.run_power = lambda command: types.SimpleNamespace(returncode=1, stderr="denied")
        self.api.power = "poweroff"
        self.runner.handle_power()   # reports on stderr, raises nothing

    def test_successful_sign_in(self):
        self.api.logins = [{"user_id": 2, "login_url": None}]
        self.runner.handle_logins()
        self.assertEqual(self.api.posted("/2/url"), [{"url": LINK}])           # the link goes to the hub
        self.api.logins = [{"user_id": 2, "login_url": LINK}]
        self.runner.handle_logins()
        self.assertEqual(self.made[2].sent, [])                                # no code yet
        self.api.codes[2] = "the-code"
        self.runner.handle_logins()
        self.assertEqual(self.made[2].sent, ["the-code"])
        self.assertEqual(self.api.posted("/2/done"), [])                       # no token printed yet
        # setup-token prints the token and then waits for a key: the runner does not wait for it to end
        self.made[2].output += f"\r\n\x1b[32mYour OAuth token (valid for 1 year):\x1b[0m\r\n{TOKEN}\r\nPress Enter"
        self.runner.handle_logins()
        self.assertEqual(self.api.posted("/2/done"), [{"success": "1"}])
        self.assertEqual(self.vault.saved, {2: TOKEN})                         # kept (encrypted) for this user only
        self.assertEqual(self.vault.cleared, [2])                              # the files of the old login go
        self.assertTrue(self.made[2].closed)
        self.assertEqual(self.runner.sessions, {})

    def test_expired_tokens_are_deleted_on_their_own(self):
        self.vault.saved = {2: TOKEN, 3: TOKEN}
        self.api.expired = [2]
        self.runner.step()
        self.assertEqual(self.vault.saved, {3: TOKEN})                         # only the expired one goes
        self.runner.step()                                                     # nothing left to do, nothing breaks

    def test_a_token_printed_before_the_code_is_not_taken(self):
        self.api.logins = [{"user_id": 2, "login_url": None}]
        self.runner.handle_logins()
        self.made[2].output += TOKEN
        self.api.logins = [{"user_id": 2, "login_url": LINK}]
        self.runner.handle_logins()
        self.assertEqual(self.vault.saved, {})

    def test_a_refused_code_fails_at_once(self):
        self.api.logins = [{"user_id": 2, "login_url": None}]
        self.runner.handle_logins()
        self.api.logins = [{"user_id": 2, "login_url": LINK}]
        self.api.codes[2] = "old-code"
        self.runner.handle_logins()
        self.made[2].output += "OAuth error: That code wasn't accepted. Press Enter to retry."
        self.runner.handle_logins()                                              # no waiting for the time limit
        self.assertEqual(self.api.posted("/2/done"), [{"success": "0"}])
        self.assertTrue(self.made[2].closed)

    def test_an_exit_without_a_token_is_a_failure(self):
        self.api.logins = [{"user_id": 2, "login_url": None}]
        self.runner.handle_logins()
        self.api.logins = [{"user_id": 2, "login_url": LINK}]
        self.api.codes[2] = "the-code"
        self.runner.handle_logins()
        self.made[2].exit = 0
        self.runner.handle_logins()
        self.assertEqual(self.api.posted("/2/done"), [{"success": "0"}])
        self.assertEqual(self.vault.saved, {})

    def test_wrong_code_is_a_failure(self):
        self.api.logins = [{"user_id": 2, "login_url": None}]
        self.runner.handle_logins()
        self.api.logins = [{"user_id": 2, "login_url": LINK}]
        self.api.codes[2] = "wrong"
        self.runner.handle_logins()
        self.made[2].exit = 1
        self.runner.handle_logins()
        self.assertEqual(self.api.posted("/2/done"), [{"success": "0"}])

    def test_sign_in_that_hangs_after_the_code_gives_up(self):
        self.api.logins = [{"user_id": 2, "login_url": None}]
        self.runner.handle_logins()
        self.api.logins = [{"user_id": 2, "login_url": LINK}]
        self.api.codes[2] = "x"
        self.runner.handle_logins()
        self.now[0] = 100.0 + runner.LOGIN_TIMEOUT_AFTER_CODE + 1
        self.runner.handle_logins()
        self.assertEqual(self.api.posted("/2/done"), [{"success": "0"}])
        self.assertTrue(self.made[2].closed)

    def test_no_link_from_claude_means_failure(self):
        self.runner.start_session = lambda user_id: FakeSession(link=None)
        self.api.logins = [{"user_id": 2, "login_url": None}]
        self.runner.handle_logins()
        self.assertEqual(self.api.posted("/2/done"), [{"success": "0"}])
        self.assertEqual(self.runner.sessions, {})

    def test_cancelled_sign_in_is_stopped(self):
        self.api.logins = [{"user_id": 2, "login_url": None}]
        self.runner.handle_logins()
        self.api.logins = []                                                   # the user cancelled
        self.runner.handle_logins()
        self.assertTrue(self.made[2].closed)
        self.assertEqual(self.runner.sessions, {})

    def test_two_users_two_separate_sessions(self):
        self.api.logins = [{"user_id": 2, "login_url": None}, {"user_id": 3, "login_url": None}]
        self.runner.handle_logins()
        self.assertIsNot(self.made[2], self.made[3])
        self.api.logins = [{"user_id": 2, "login_url": LINK}, {"user_id": 3, "login_url": LINK}]
        self.api.codes[3] = "code-of-3"
        self.runner.handle_logins()
        self.assertEqual((self.made[2].sent, self.made[3].sent), ([], ["code-of-3"]))

    def test_old_link_after_a_restart_is_not_resumed(self):
        self.api.logins = [{"user_id": 2, "login_url": LINK}]
        self.runner.handle_logins()
        self.assertEqual(self.api.posted("/2/done"), [{"success": "0"}])

    def test_wipe_deletes_only_the_users_folder(self):
        for name in ("2", "3"):
            (self.base / name).mkdir()
            (self.base / name / ".claude.json").write_text("x")
        self.api.wipes = [2]
        self.runner.handle_wipes()
        self.assertFalse((self.base / "2").exists())
        self.assertTrue((self.base / "3" / ".claude.json").exists())
        self.assertEqual(self.api.posted("/2/done"), [{}])

    def test_wipe_is_not_reported_when_the_folder_could_not_be_deleted(self):
        (self.base / "2").mkdir()
        self.api.wipes = [2]
        original = runner.shutil.rmtree
        runner.shutil.rmtree = lambda *a, **k: None          # as if the files belonged to somebody else
        try:
            self.runner.handle_wipes()
        finally:
            runner.shutil.rmtree = original
        self.assertEqual(self.api.posted("/wipes/2/done"), [])  # the hub keeps the "wipe" mark

    def test_wipe_cannot_leave_the_base_folder(self):
        outside = Path(self.tmp.name) / "important"
        outside.mkdir()
        self.api.wipes = ["../important"]
        with self.assertRaises(ValueError):
            self.runner.handle_wipes()                                         # not a number: refused
        self.assertTrue(outside.exists())


class Done:
    def __init__(self, stdout, returncode=0):
        self.stdout, self.returncode = stdout, returncode


class RunChatTest(unittest.TestCase):
    """The real _run_chat: the lines come while the program runs, the prompt goes in whole, the timeout holds."""

    def setUp(self):
        self.runner = runner.Runner(FakeApi(), "/data/claude", vault=FakeVault({}), tickets=FakeTickets(),
                                    background=False)

    def test_lines_while_it_runs_and_a_long_prompt(self):
        seen = []
        script = "import sys; data = sys.stdin.read(); print('first', flush=True); print(len(data))"
        done = self.runner._run_chat([sys.executable, "-c", script], "x" * 300000, seen.append)
        self.assertEqual((seen, done.stdout, done.returncode), (["first\n", "300000\n"], "first\n300000\n", 0))

    def test_the_timeout_holds(self):
        old, runner.CHAT_TIMEOUT = runner.CHAT_TIMEOUT, 0.5
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                self.runner._run_chat([sys.executable, "-c", "import time; print('x', flush=True); time.sleep(30)"], "")
        finally:
            runner.CHAT_TIMEOUT = old


class ChatRunTest(unittest.TestCase):
    """The chat window: the runner answers one question in a container."""

    def setUp(self):
        self.api, self.commands = FakeApi(), []
        self.api.chat_job = {"chat_id": 5, "user_id": 2, "model": "haiku", "prompt": "Hello?"}
        self.vault, self.tickets = FakeVault({2: TOKEN}), FakeTickets()
        self.answer = Done(json.dumps({"result": "Hi!", "usage": {"input_tokens": 7, "output_tokens": 2}}))

        def run_chat(command, prompt, on_line=None):
            self.commands.append((command, prompt))
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer

        self.runner = runner.Runner(self.api, "/data/claude", vault=self.vault, tickets=self.tickets,
                                    run_chat=run_chat, background=False)

    def test_thoughts_go_to_the_hub_while_it_answers(self):
        now = [100.0]
        self.runner.clock = lambda: now[0]
        pieces = [json.dumps({"type": "stream_event", "event": {"type": "content_block_delta",
                              "delta": {"type": "thinking_delta", "thinking": text}}}) for text in ("Eins ", "zwei ", "drei")]

        def run_chat(command, prompt, on_line=None):
            for piece, at in zip(pieces, (100.5, 102.0, 102.5)):
                now[0] = at
                on_line(piece + "\n")
            return Done(json.dumps({"result": "Hi!"}))

        self.runner.run_chat = run_chat
        self.runner.handle_chat()
        self.assertEqual(self.api.posted("/chat/5/thoughts"), [{"text": "Eins zwei "}, {"text": "drei"}])
        self.assertEqual(self.api.posted("/chat/5/finish")[0]["answer"], "Hi!")
        names = [path for _, path, _ in self.api.calls if path.startswith("/runner/chat/5/")]
        self.assertEqual(names[-1], "/runner/chat/5/finish")                # the last thoughts come before the answer

    def test_a_lost_thought_is_no_failure(self):
        def call(method, path, **form):
            if path.endswith("/thoughts"):
                raise OSError("hub away")
            return FakeApi.call(self.api, method, path, **form)

        self.api.call = call
        self.runner.run_chat = lambda command, prompt, on_line=None: on_line(json.dumps(
            {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "thinking_delta",
             "thinking": "x"}}})) or Done(json.dumps({"result": "Hi!"}))
        self.runner.handle_chat()
        self.assertEqual(self.api.posted("/chat/5/finish")[0]["success"], "1")

    def test_answer_goes_back_with_tokens(self):
        self.runner.handle_chat()
        command, prompt = self.commands[0]
        self.assertEqual(prompt, "Hello?")                                 # through stdin ...
        self.assertNotIn("Hello?", command)                                # ... never on the command line
        ticket, token = self.tickets.issued[0]
        self.assertEqual(token, TOKEN)                                     # the ticket stands for this user's token
        self.assertIn(f"CLAUDE_CODE_OAUTH_TOKEN={ticket}", command)
        self.assertNotIn(TOKEN, " ".join(command))                          # the token itself never reaches the run
        self.assertNotIn("/data/claude", " ".join(command))
        self.assertEqual(self.tickets.revoked, [ticket])                    # and the ticket ends with the run
        self.assertEqual(self.api.posted("/chat/5/finish"),
                         [{"success": "1", "answer": "Hi!", "tokens_in": 7, "tokens_out": 2, "outside": "0"}])

    def test_every_question_runs_behind_the_public_only_proxy(self):
        for job in ({"mode": "all"}, {}):                                       # a job without a mode is "all" too
            self.commands.clear()
            self.api.chat_job = {"chat_id": 5, "user_id": 2, "model": "haiku", "prompt": "x", **job}
            self.runner.handle_chat()
            command = " ".join(self.commands[0][0])
            self.assertIn("egress:3128", command)
    def test_nothing_to_do(self):
        self.api.chat_job = None
        self.runner.handle_chat()
        self.assertEqual(self.commands, [])
        self.assertEqual(self.api.posted("/finish"), [])

    def test_lost_login_marks_the_connection_expired(self):
        self.answer = Done(json.dumps({"is_error": True, "result": "Invalid API key · Please run /login"}))
        self.runner.handle_chat()
        self.assertEqual(self.api.posted("/2/expired"), [{}])
        self.assertEqual(self.api.posted("/chat/5/finish")[0]["success"], "0")

    def test_failures_are_reported_not_hidden(self):
        self.answer = Done("", returncode=125)
        self.runner.handle_chat()
        sent = self.api.posted("/chat/5/finish")[0]
        self.assertEqual((sent["success"], "125" in sent["answer"]), ("0", True))
        self.assertEqual(self.api.posted("/2/expired"), [])                # an ordinary failure is no lost login

    def test_without_a_saved_token_nothing_runs(self):
        self.vault.saved.clear()
        self.runner.handle_chat()
        self.assertEqual(self.commands, [])
        self.assertEqual(self.api.posted("/2/expired"), [{}])                # the menu asks to link Claude again
        self.assertEqual(self.api.posted("/chat/5/finish")[0]["success"], "0")
        self.assertEqual(self.tickets.issued, [])

    def test_another_users_token_is_never_used(self):
        self.vault.saved = {3: TOKEN}
        self.runner.handle_chat()
        self.assertEqual(self.commands, [])
        self.assertEqual(self.tickets.issued, [])

    def test_timeout_removes_the_container(self):
        calls = []
        original = runner.subprocess.run
        runner.subprocess.run = lambda cmd, **kw: calls.append(cmd)
        try:
            self.answer = runner.subprocess.TimeoutExpired("docker", 1)
            self.runner.handle_chat()
        finally:
            runner.subprocess.run = original
        self.assertEqual(calls, [["docker", "rm", "-f", "agent-chat-5"]])
        self.assertEqual(self.api.posted("/chat/5/finish")[0]["success"], "0")
        self.assertEqual(len(self.tickets.revoked), 1)                       # the ticket ends even then


class LoginTextTest(unittest.TestCase):
    def test_link_is_found_in_what_the_terminal_prints(self):
        plain = "Opening browser to sign in…\nIf the browser didn't open, visit: " + LINK + "\nPaste code here if prompted > "
        self.assertEqual(login.extract_login_url(plain), LINK)

    def test_link_inside_an_osc8_hyperlink(self):
        osc = f"visit: \x1b]8;;{LINK}\x1b\\{LINK}\x1b]8;;\x1b\\\r\n\x1b[2mPaste code\x1b[0m"
        self.assertEqual(login.extract_login_url(osc), LINK)
        bel = f"visit: \x1b]8;;{LINK}\x07{LINK}\x1b]8;;\x07"
        self.assertEqual(login.extract_login_url(bel), LINK)

    def test_only_links_to_claude(self):
        self.assertIsNone(login.extract_login_url("visit https://evil.example/claude.com/x"))
        self.assertIsNone(login.extract_login_url("visit http://claude.com/x and nothing else"))
        self.assertIsNone(login.extract_login_url("Opening browser to sign in…"))
        self.assertIsNone(login.extract_login_url(""))


    def test_a_wrapped_and_redrawn_token_is_put_together(self):
        """14.11.2026: the terminal UI wrapped the token and drew the screen twice; the first version took none."""
        first, rest = TOKEN[:60], TOKEN[60:]
        frame_wrapped = (f"\x1b[32m\u2713 Long-lived authentication token created successfully!\x1b[39m\r\n\r\n"
                         f"Your OAuth token (valid for 1 year):\r\n\r\n\x1b[33m{first}\r\n{rest}\x1b[39m\r\n\r\n"
                         f"\x1b[2mStore this token securely. You won't be able to see it again.\x1b[22m\r\n")
        self.assertEqual(login.extract_token(frame_wrapped), TOKEN)
        partial = f"Your OAuth token (valid for 1 year):\r\n{TOKEN[:40]}"            # a screen still being written
        frame_full = frame_wrapped.replace(f"{first}\r\n{rest}", TOKEN)
        self.assertEqual(login.extract_token(partial + "\x1b[2K\x1b[1A" * 6 + frame_full), TOKEN)
        self.assertEqual(login.extract_token(f"{TOKEN[:40]} ... {TOKEN}"), TOKEN)     # a beginning and the whole one

    def test_the_failure_log_holds_nothing_secret(self):
        screen = (f"Paste code here if prompted > abcDEF0123456789abcdef0123456789#state0123456789abcdef\r\n"
                  f"visit: {LINK}\r\nYour OAuth token (valid for 1 year):\r\n{TOKEN}\r\nOAuth error: invalid code")
        shown = login.redacted_tail(screen)
        screen += "\r\n" + "*" * 61 + "ABCDEF OAuth error"                       # the masked code shows its end
        shown = login.redacted_tail(screen)
        for secret in (TOKEN, "abcDEF0123456789", "state0123456789", "client_id=abc", "ABCDEF"):
            self.assertNotIn(secret, shown)
        self.assertIn("OAuth error: invalid code", shown)

    def test_the_token_is_found_once(self):
        printed = f"\x1b[1mYour token:\x1b[0m\r\n\x1b[36m{TOKEN}\x1b[0m\r\nStore it safely."
        self.assertEqual(login.extract_token(printed), TOKEN)
        self.assertEqual(login.extract_token(printed + printed), TOKEN)          # the same token twice is fine
        self.assertIsNone(login.extract_token(printed + " sk-ant-oat01-" + "u" * 80))   # two different: no guessing
        self.assertIsNone(login.extract_token("Paste code here if prompted > "))


class LoginCommandTest(unittest.TestCase):
    def test_no_folder_is_mounted(self):
        cmd = launcher.build_login_command(user_id=2)
        self.assertNotIn("--mount", cmd)
        self.assertEqual(cmd[-2:], ["claude", "setup-token"])
        for flag in ("-t", "-i", "--read-only", "--init"):
            self.assertIn(flag, cmd)
        for bad in ("--privileged", "--volume", "-v", "--network host", "--device"):
            self.assertNotIn(bad, cmd)
        self.assertIn("10002:10002", cmd)

    def test_bad_values(self):
        for change in ({"user_id": 0}, {"user_id": "2"}, {"memory": "x"}, {"image": "i --privileged"}):
            with self.assertRaises(ValueError, msg=str(change)):
                launcher.build_login_command(**{"user_id": 2, **change})


if __name__ == "__main__":
    unittest.main()
