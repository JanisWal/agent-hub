"""The runner's sign-in and wipe logic with a fake hub and a fake terminal (no Docker needed).

    docker compose run --rm --no-deps -v "$PWD/runner:/app/runner" web python -W ignore -m unittest runner.test_runner
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from runner import launcher, login, runner

LINK = "https://claude.com/cai/oauth/authorize?code=true&client_id=abc&state=xyz"


class FakeApi:
    def __init__(self):
        self.logins, self.wipes, self.codes, self.calls, self.chat_job = [], [], {}, [], None

    def call(self, method, path, **form):
        self.calls.append((method, path, form))
        if path == "/runner/chat/claim":
            return {"ok": True, "job": self.chat_job}
        if path == "/runner/logins":
            return {"ok": True, "logins": self.logins}
        if path == "/runner/wipes":
            return {"ok": True, "user_ids": self.wipes}
        if path.endswith("/code"):
            return {"ok": True, "code": self.codes.pop(int(path.split("/")[3]), None)}
        return {"ok": True}

    def posted(self, suffix):
        return [form for method, path, form in self.calls if path.endswith(suffix)]


class FakeSession:
    def __init__(self, link=LINK):
        self.link, self.sent, self.closed, self.exit, self.code_sent_at = link, [], False, None, None

    def url(self, timeout):
        return self.link

    def send_code(self, code):
        self.sent.append(code)
        self.code_sent_at = 100.0

    def exit_code(self):
        return self.exit

    def close(self):
        self.closed = True


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name) / "claude"
        self.base.mkdir()
        self.api, self.made, self.now = FakeApi(), {}, [100.0]
        self.prepared = []

        def start(user_id):
            self.made[user_id] = FakeSession()
            return self.made[user_id]

        self.runner = runner.Runner(self.api, str(self.base), prepare=lambda p, u: self.prepared.append((p, u)),
                                    start_session=start, clock=lambda: self.now[0])

    def tearDown(self):
        self.tmp.cleanup()

    def test_successful_sign_in(self):
        self.api.logins = [{"user_id": 2, "login_url": None}]
        self.runner.handle_logins()
        self.assertEqual(self.api.posted("/2/url"), [{"url": LINK}])           # the link goes to the hub
        self.assertEqual(self.prepared, [(str(self.base / "2"), 2)])           # folder of this user only
        self.api.logins = [{"user_id": 2, "login_url": LINK}]
        self.runner.handle_logins()
        self.assertEqual(self.made[2].sent, [])                                # no code yet
        self.api.codes[2] = "the-code"
        self.runner.handle_logins()
        self.assertEqual(self.made[2].sent, ["the-code"])
        self.made[2].exit = 0
        self.runner.handle_logins()
        self.assertEqual(self.api.posted("/2/done"), [{"success": "1"}])
        self.assertTrue(self.made[2].closed)
        self.assertEqual(self.runner.sessions, {})

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


class ChatRunTest(unittest.TestCase):
    """The chat window: the runner answers one question in a container."""

    def setUp(self):
        self.api, self.commands = FakeApi(), []
        self.api.chat_job = {"chat_id": 5, "user_id": 2, "model": "haiku", "prompt": "Hello?"}
        self.prepared = []
        self.answer = Done(json.dumps({"result": "Hi!", "usage": {"input_tokens": 7, "output_tokens": 2}}))

        def run_chat(command, prompt):
            self.commands.append((command, prompt))
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer

        self.runner = runner.Runner(self.api, "/data/claude", prepare=lambda p, u: self.prepared.append((p, u)),
                                    run_chat=run_chat)

    def test_answer_goes_back_with_tokens(self):
        self.runner.handle_chat()
        command, prompt = self.commands[0]
        self.assertEqual(prompt, "Hello?")                                 # through stdin ...
        self.assertNotIn("Hello?", command)                                # ... never on the command line
        self.assertIn("src=/data/claude/2,dst=/claude", " ".join(command))
        self.assertEqual(self.prepared, [("/data/claude/2", 2)])
        self.assertEqual(self.api.posted("/chat/5/finish"),
                         [{"success": "1", "answer": "Hi!", "tokens_in": 7, "tokens_out": 2}])

    def test_the_mode_of_the_question_decides_the_container(self):
        for mode, proxy, readonly in (("code", "egress:3129", True), ("web", "egress:3128", False), ("plain", "egress:3129", False)):
            self.commands.clear()
            self.api.chat_job = {"chat_id": 5, "user_id": 2, "model": "haiku", "prompt": "x", "mode": mode}
            self.runner.handle_chat()
            command = " ".join(self.commands[0][0])
            self.assertIn(proxy, command)
            self.assertEqual(",readonly" in command, readonly)
        self.commands.clear()
        self.api.chat_job = {"chat_id": 5, "user_id": 2, "model": "haiku", "prompt": "x"}      # an old job without a mode
        self.runner.handle_chat()
        self.assertIn("egress:3128", " ".join(self.commands[0][0]))
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


class LoginCommandTest(unittest.TestCase):
    def test_only_the_users_claude_folder_is_mounted(self):
        cmd = launcher.build_login_command(user_id=2, claude_dir="/data/claude/2")
        self.assertEqual(sum(1 for c in cmd if c == "--mount"), 1)
        self.assertIn("src=/data/claude/2,dst=/claude", " ".join(cmd))
        self.assertEqual(cmd[-4:], ["claude", "auth", "login", "--claudeai"])
        for flag in ("-t", "-i", "--read-only", "--init"):
            self.assertIn(flag, cmd)
        for bad in ("--privileged", "--volume", "-v", "--network host", "--device"):
            self.assertNotIn(bad, cmd)
        self.assertIn("10002:10002", cmd)

    def test_bad_values(self):
        for change in ({"user_id": 0}, {"user_id": "2"}, {"claude_dir": "rel"}, {"claude_dir": "/a,b"},
                       {"memory": "x"}, {"image": "i --privileged"}):
            with self.assertRaises(ValueError, msg=str(change)):
                launcher.build_login_command(**{"user_id": 2, "claude_dir": "/data/claude/2", **change})


if __name__ == "__main__":
    unittest.main()
