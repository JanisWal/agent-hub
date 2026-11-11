"""The launcher: the command is fixed and safe, the answer is read strictly.

Run inside the web image with both folders mounted (see PROJEKT.md, "Tests"):
    docker compose run --rm --no-deps -v "$PWD/runner:/app/runner" web python -W ignore -m unittest runner.test_launcher
"""
import json
import os
import tempfile
import unittest

from runner import launcher as L

GOOD = dict(run_id=7, user_id=2, model="sonnet", work_dir="/workspaces/task-7", claude_dir="/data/claude/2")


def answer(text, **extra):
    return json.dumps({"result": text, "usage": {"input_tokens": 10, "cache_read_input_tokens": 5,
                                                  "output_tokens": 3}, **extra})


class PowerCommandTest(unittest.TestCase):
    def test_the_two_commands(self):
        for action in ("reboot", "poweroff"):
            cmd = L.build_power_command(action)
            self.assertEqual(cmd[:2], ["docker", "run"])
            self.assertEqual(cmd[-3:], ["systemctl", "--no-block", action])   # a fixed command, nothing else
            self.assertIn("agent-hub-hub-runner", cmd)
            self.assertIn("--pull=never", cmd)                                # never fetches an image at that moment
            self.assertIn("--network=none", cmd)

    def test_the_backup_command_starts_the_unit_and_waits_for_it(self):
        cmd = L.build_power_command("backup")
        self.assertEqual(cmd[-3:], ["systemctl", "start", "agent-hub-backup.service"])
        self.assertNotIn("--no-block", cmd)                                  # the exit code must tell how it went
        self.assertEqual(L.POWER_ACTIONS, ("reboot", "poweroff", "backup"))  # the same three as web/app/power.py

    def test_nothing_else_is_accepted(self):
        for bad in ("", "halt", "REBOOT", "reboot; id", "poweroff --force", None):
            with self.assertRaises(ValueError):
                L.build_power_command(bad)

    def test_an_agent_run_never_gets_these_rights(self):
        for flag in ("--privileged", "--pid=host", "nsenter"):
            self.assertNotIn(flag, L.build_command(**GOOD))


class CommandTest(unittest.TestCase):
    def test_template(self):
        cmd = L.build_command(**GOOD)
        text = " ".join(cmd)
        self.assertEqual(cmd[:3], ["docker", "run", "--rm"])
        for flag in ("--cap-drop ALL", "--security-opt no-new-privileges", "--read-only",
                     "--user 10002:10002", "--network agent-hub-agents", "--memory 480m", "--memory-swap 480m"):
            self.assertIn(flag, text)
        self.assertEqual(sum(1 for c in cmd if c == "--mount"), 2)        # exactly two folders
        self.assertIn("src=/workspaces/task-7,dst=/work", text)
        self.assertIn("src=/data/claude/2,dst=/claude", text)

    def test_nothing_dangerous_in_the_command(self):
        cmd = L.build_command(**GOOD)
        text = " ".join(cmd)
        for bad in ("docker.sock", "hub.db", ".env", "backups", "vault"):
            self.assertNotIn(bad, text)
        for flag in ("--privileged", "--pid", "--ipc", "--device", "--volume", "-v", "--cap-add", "--userns"):
            self.assertNotIn(flag, cmd)                       # whole arguments, so --pids-limit is fine
        self.assertNotIn("host", cmd)
        self.assertFalse(any(part.startswith(("0:", "root")) for part in cmd))

    def test_different_users_get_different_users_and_folders(self):
        a = L.build_command(**GOOD)
        b = L.build_command(**{**GOOD, "user_id": 3, "claude_dir": "/data/claude/3"})
        self.assertIn("10002:10002", a)
        self.assertIn("10003:10003", b)
        self.assertNotIn("/data/claude/2", " ".join(b))

    def test_bad_values_are_refused(self):
        for change in ({"run_id": 0}, {"run_id": "7"}, {"run_id": True}, {"user_id": -1}, {"user_id": "2; rm"},
                       {"model": "gpt"}, {"model": "sonnet --x"}, {"work_dir": "relative/dir"},
                       {"work_dir": "/work,dst=/etc"}, {"work_dir": "/work dir"}, {"claude_dir": "/a/../etc"},
                       {"claude_dir": "/a:/b"}, {"memory": "64"}, {"memory": "1g --privileged"},
                       {"image": "x --privileged"}, {"network": "host --pid=host"}):
            with self.assertRaises(ValueError, msg=str(change)):
                L.build_command(**{**GOOD, **change})

    def test_task_text_never_reaches_the_command(self):
        # there is simply no parameter for it: the prompt travels through stdin
        self.assertNotIn("prompt", L.build_command.__code__.co_varnames)

    @unittest.skipUnless(os.geteuid() == 0, "chown needs root")
    def test_prepare_folder_hands_it_to_the_run_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "claude", "2")
            L.prepare_folder(target, 2)
            info = os.stat(target)
            self.assertEqual((info.st_uid, info.st_mode & 0o777), (10002, 0o700))
            with self.assertRaises(ValueError):
                L.prepare_folder("relative", 2)


class ChatCommandTest(unittest.TestCase):
    """The manager chat: no project files, web search and a shell without internet."""

    def test_no_work_folder_and_no_tool_that_touches_files(self):
        cmd = L.build_chat_command(chat_id=5, user_id=2, model="haiku", claude_dir="/data/claude/2")
        text = " ".join(cmd)
        self.assertEqual(sum(1 for c in cmd if c == "--mount"), 1)            # only the user's Claude folder
        self.assertNotIn("dst=/work", text)
        for tool in ("Edit", "Write", "Read", "Glob", "Grep", "NotebookEdit", "Task"):
            self.assertNotIn(tool, text)
        self.assertNotIn("--dangerously-skip-permissions", cmd)
        for flag in ("--read-only", "--cap-drop", "--no-session-persistence", "-i"):
            self.assertIn(flag, cmd)
        for bad in ("--privileged", "--volume", "-v", "--device", "docker.sock"):
            self.assertNotIn(bad, text.split())
        self.assertIn("10002:10002", cmd)

    def test_web_and_code_apart_has_no_internet_for_code(self):
        cmd = L.build_chat_command(chat_id=7, user_id=2, model="haiku", claude_dir="/data/claude/2", mode="apart")
        self.assertEqual(cmd[cmd.index("--tools") + 1], "WebSearch,Bash")          # search runs at Anthropic
        self.assertIn("HTTPS_PROXY=http://egress:3129", cmd)                       # Anthropic only: code is offline
        self.assertNotIn("HTTPS_PROXY=http://egress:3128", cmd)
        self.assertNotIn("WebFetch", " ".join(cmd))
        self.assertTrue(any(part.endswith(",readonly") for part in cmd))

    def test_only_the_manager_modes_exist(self):
        self.assertEqual(tuple(L.CHAT_MODES), ("all", "apart"))              # the old single modes are gone
        for old in ("plain", "web", "code", "everything"):
            with self.assertRaises(ValueError):
                L.build_chat_command(chat_id=5, user_id=2, model="haiku", claude_dir="/data/claude/2", mode=old)

    def test_the_manager_chat_has_the_open_internet_but_never_the_home_network(self):
        cmd = L.build_chat_command(chat_id=6, user_id=2, model="sonnet", claude_dir="/data/claude/2", mode="all")
        self.assertEqual(cmd[cmd.index("--tools") + 1], "WebSearch,WebFetch,Bash")   # Janis chose the open internet
        self.assertEqual(cmd[cmd.index("--allowedTools") + 1], "WebSearch WebFetch Bash")
        self.assertIn("HTTPS_PROXY=http://egress:3128", cmd)                       # public hosts only (egress.py)
        self.assertEqual(cmd[cmd.index("--network") + 1], "agent-hub-agents")      # internal network: the proxy is the only way
        self.assertTrue(any(part.endswith(",readonly") for part in cmd))           # code never changes the login
        self.assertIn("size=128m", " ".join(cmd))
        self.assertEqual(cmd[cmd.index("--max-turns") + 1], "12")
        self.assertEqual(cmd[cmd.index("--model") + 1], "sonnet")

    def test_each_agent_has_its_own_switch(self):
        apart = L.build_command(run_id=1, user_id=2, model="sonnet", work_dir="/w/1", claude_dir="/c/2", net="apart")
        self.assertIn("HTTPS_PROXY=http://egress:3129", apart)                     # code without internet
        self.assertNotIn("HTTPS_PROXY=http://egress:3128", apart)
        for bad in ("", "open", "together; x", None):
            with self.assertRaises(ValueError):
                L.build_command(run_id=1, user_id=2, model="sonnet", work_dir="/w/1", claude_dir="/c/2", net=bad)

    def test_every_run_goes_through_the_proxy(self):
        run = L.build_command(run_id=1, user_id=2, model="sonnet", work_dir="/w/1", claude_dir="/c/2")
        login = L.build_login_command(user_id=2, claude_dir="/c/2")
        self.assertIn("HTTPS_PROXY=http://egress:3128", run)                       # agents: public internet, no home network
        self.assertIn("HTTPS_PROXY=http://egress:3129", login)                     # sign-ins: Anthropic only
        for cmd in (run, login):
            self.assertIn("https_proxy=http://egress:" + ("3128" if cmd is run else "3129"), cmd)
            self.assertNotIn("host", cmd)
            self.assertNotIn("bridge", cmd)

    def test_unknown_mode_is_refused(self):
        for mode in ("", "root", "web,code", None, "CODE"):
            with self.assertRaises(ValueError, msg=str(mode)):
                L.build_chat_command(chat_id=5, user_id=2, model="haiku", claude_dir="/data/claude/2", mode=mode)
    def test_bad_values(self):
        for change in ({"chat_id": 0}, {"chat_id": "5"}, {"user_id": 0}, {"model": "gpt"},
                       {"claude_dir": "/a,b"}, {"memory": "x"}):
            with self.assertRaises(ValueError, msg=str(change)):
                L.build_chat_command(**{"chat_id": 5, "user_id": 2, "model": "haiku",
                                        "claude_dir": "/data/claude/2", **change})


class ChatOutputTest(unittest.TestCase):
    def test_answer(self):
        out = json.dumps({"result": " Hi! ", "usage": {"input_tokens": 3, "cache_read_input_tokens": 4,
                                                          "output_tokens": 2}})
        self.assertEqual(L.parse_chat_output(out), (True, "Hi!", 7, 2, False))

    def test_search_limit_reached_is_a_clear_failure(self):
        out = json.dumps({"is_error": True, "subtype": "error_max_turns", "result": "", "usage": {"output_tokens": 9}})
        ok, text, tokens_in, tokens_out, login = L.parse_chat_output(out)
        self.assertEqual((ok, login, tokens_out), (False, False, 9))
        self.assertIn("search limit", text)

    def test_errors_are_not_answers(self):
        self.assertFalse(L.parse_chat_output(json.dumps({"is_error": True, "result": "Overloaded"}))[0])
        self.assertFalse(L.parse_chat_output(json.dumps({"result": ""}))[0])
        self.assertFalse(L.parse_chat_output("not json")[0])
        self.assertFalse(L.parse_chat_output(json.dumps(["x"]))[0])

    def test_a_lost_login_is_recognised(self):
        for text in ("Invalid API key · Please run /login", "Not logged in", "OAuth token has expired",
                     "authentication_error 401"):
            out = json.dumps({"is_error": True, "result": text})
            self.assertTrue(L.parse_chat_output(out)[4], text)
        self.assertFalse(L.parse_chat_output(json.dumps({"is_error": True, "result": "Overloaded"}))[4])
        self.assertFalse(L.parse_chat_output(json.dumps({"result": "You can log in with /login"}))[4])  # an answer


class OutputTest(unittest.TestCase):
    def test_result_marker_report_and_tokens(self):
        result = L.parse_output("tester", answer("All good.\nChecked 3 things.\nRESULT: pass"))
        self.assertEqual(result, ("pass", "All good.\nChecked 3 things.", 15, 3))

    def test_everything_unclear_is_failed(self):
        cases = [
            ("programmer", "not json at all"),
            ("programmer", answer("Done, but no marker")),
            ("programmer", answer("x\nRESULT: pass")),                 # a tester value for the programmer
            ("tester", answer("x\nRESULT: done")),
            ("programmer", answer("x\nRESULT: done", is_error=True)),
            ("programmer", answer("")),
            ("reviewer", json.dumps(["list"])),
        ]
        for role, out in cases:
            self.assertEqual(L.parse_output(role, out)[0], "failed", (role, out))

    def test_marker_must_be_the_last_line(self):
        self.assertEqual(L.parse_output("programmer", answer("RESULT: done\nand then more text"))[0], "failed")

    def test_report_is_capped_and_role_checked(self):
        self.assertEqual(len(L.parse_output("chef", answer("x" * 50000 + "\nRESULT: done"))[1]), L.MAX_REPORT)
        with self.assertRaises(ValueError):
            L.parse_output("janitor", answer("x"))


class ConsistencyTest(unittest.TestCase):
    """The launcher repeats a few lists of the hub (it lives in another image): they must agree."""

    def test_same_lists_as_the_hub(self):
        try:
            from app import agents, workflow
        except ImportError:
            self.skipTest("hub code not available")
        self.assertEqual(L.MODELS, agents.MODELS)
        self.assertEqual(L.ROLES, workflow.ROLES)
        # "skipped" is the chief's own result (a test left out without the Mac), no run reports it
        self.assertEqual({k: set(v) for k, v in L.RESULTS.items()},
                         {k: set(v) - {"skipped"} for k, v in workflow.RESULTS.items()})


if __name__ == "__main__":
    unittest.main()
