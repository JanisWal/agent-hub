"""The launcher: the command is fixed and safe, the answer is read strictly.

Run inside the web image with both folders mounted (see PROJEKT.md, "Tests"):
    docker compose run --rm --no-deps -v "$PWD/runner:/app/runner" web python -W ignore -m unittest runner.test_launcher
"""
import json
import os
import tempfile
import unittest

from runner import launcher as L

TICKET = "hubrun-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
GOOD = dict(run_id=7, user_id=2, model="sonnet", work_dir="/workspaces/task-7", ticket=TICKET)


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
        self.assertEqual(sum(1 for c in cmd if c == "--mount"), 1)        # only the work folder, no Claude login
        self.assertIn("src=/workspaces/task-7,dst=/work", text)
        self.assertNotIn("/claude,", text)

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
        b = L.build_command(**{**GOOD, "user_id": 3, "ticket": "hubrun-" + "B" * 43})
        self.assertIn("10002:10002", a)
        self.assertIn("10003:10003", b)
        self.assertNotIn(TICKET, " ".join(b))

    def test_bad_values_are_refused(self):
        for change in ({"run_id": 0}, {"run_id": "7"}, {"run_id": True}, {"user_id": -1}, {"user_id": "2; rm"},
                       {"model": "-gpt"}, {"model": "Sonnet"}, {"model": "sonnet --x"}, {"model": ""},
                       {"effort": "-x"}, {"effort": "high --x"}, {"effort": "HIGH"}, {"work_dir": "relative/dir"},
                       {"work_dir": "/work,dst=/etc"}, {"work_dir": "/work dir"}, {"ticket": "sk-ant-oat01-" + "x" * 30},
                       {"ticket": "hubrun-short"}, {"ticket": TICKET + " -e X=1"}, {"memory": "64"}, {"memory": "1g --privileged"},
                       {"image": "x --privileged"}, {"network": "host --pid=host"}):
            with self.assertRaises(ValueError, msg=str(change)):
                L.build_command(**{**GOOD, **change})

    def test_the_effort_level_goes_with_the_model(self):
        cmd = L.build_command(**GOOD, effort="xhigh")
        self.assertEqual(cmd[cmd.index("--model"):cmd.index("--model") + 4], ["--model", "sonnet", "--effort", "xhigh"])
        self.assertNotIn("--effort", L.build_command(**GOOD))                 # empty: Claude Code's own default
        chat = L.build_chat_command(chat_id=5, user_id=2, model="fable", ticket=TICKET, effort="max")
        self.assertEqual(chat[chat.index("--model"):chat.index("--model") + 4], ["--model", "fable", "--effort", "max"])

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
        cmd = L.build_chat_command(chat_id=5, user_id=2, model="haiku", ticket=TICKET)
        text = " ".join(cmd)
        self.assertNotIn("--mount", cmd)                                      # no folder at all, no Claude login
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
        cmd = L.build_chat_command(chat_id=7, user_id=2, model="haiku", ticket=TICKET, mode="apart")
        self.assertEqual(cmd[cmd.index("--tools") + 1], "WebSearch,Bash")          # search runs at Anthropic
        self.assertIn("HTTPS_PROXY=http://egress:3129", cmd)                       # Anthropic only: code is offline
        self.assertNotIn("HTTPS_PROXY=http://egress:3128", cmd)
        self.assertNotIn("WebFetch", " ".join(cmd))

    def test_the_status_round_has_no_tools_one_turn_and_only_anthropic(self):
        cmd = L.build_chat_command(chat_id=8, user_id=2, model="haiku", ticket=TICKET, mode="brief", effort="low")
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        self.assertNotIn("--allowedTools", cmd)
        self.assertEqual(cmd[cmd.index("--max-turns") + 1], "1")
        self.assertIn("HTTPS_PROXY=http://egress:3129", cmd)
        vibe = L.build_vibe_command(name="agent-chat-8", user_id=2, model="mistral-small-2603", ticket=TICKET,
                                    job="chat-brief", effort="none")
        self.assertIn("HUB_JOB=chat-brief", vibe)
        self.assertIn("HUB_TURNS=1", vibe)

    def test_the_wake_command_has_no_rights_and_only_the_mac(self):
        cmd = L.build_wake_command("dc:a6:32:01:02:03")
        self.assertEqual(cmd[-1], "dc:a6:32:01:02:03")
        self.assertIn("--network=host", cmd)
        for flag in ("--cap-drop", "--read-only", "no-new-privileges"):
            self.assertIn(flag, cmd)
        self.assertNotIn("--privileged", cmd)
        for bad in ("DC:A6:32:01:02:03", "dc:a6:32:01:02", "dc:a6:32:01:02:03 x", "", None):
            with self.assertRaises(ValueError):
                L.build_wake_command(bad)

    def test_only_the_manager_modes_exist(self):
        self.assertEqual(tuple(L.CHAT_MODES), ("all", "apart", "brief"))     # the old single modes are gone
        for old in ("plain", "web", "code", "everything"):
            with self.assertRaises(ValueError):
                L.build_chat_command(chat_id=5, user_id=2, model="haiku", ticket=TICKET, mode=old)

    def test_the_manager_chat_has_the_open_internet_but_never_the_home_network(self):
        cmd = L.build_chat_command(chat_id=6, user_id=2, model="sonnet", ticket=TICKET, mode="all")
        self.assertEqual(cmd[cmd.index("--tools") + 1], "WebSearch,WebFetch,Bash")   # Janis chose the open internet
        self.assertEqual(cmd[cmd.index("--allowedTools") + 1], "WebSearch WebFetch Bash")
        self.assertIn("HTTPS_PROXY=http://egress:3128", cmd)                       # public hosts only (egress.py)
        self.assertEqual(cmd[cmd.index("--network") + 1], "agent-hub-agents")      # internal network: the proxy is the only way
        self.assertIn("size=128m", " ".join(cmd))
        self.assertEqual(cmd[cmd.index("--max-turns") + 1], "12")
        self.assertEqual(cmd[cmd.index("--model") + 1], "sonnet")

    def test_each_agent_has_its_own_switch(self):
        apart = L.build_command(run_id=1, user_id=2, model="sonnet", work_dir="/w/1", ticket=TICKET, net="apart")
        self.assertIn("HTTPS_PROXY=http://egress:3129", apart)                     # code without internet
        self.assertNotIn("HTTPS_PROXY=http://egress:3128", apart)
        for bad in ("", "open", "together; x", None):
            with self.assertRaises(ValueError):
                L.build_command(run_id=1, user_id=2, model="sonnet", work_dir="/w/1", ticket=TICKET, net=bad)

    def test_every_run_goes_through_the_proxy(self):
        run = L.build_command(run_id=1, user_id=2, model="sonnet", work_dir="/w/1", ticket=TICKET)
        login = L.build_login_command(user_id=2)
        self.assertIn("HTTPS_PROXY=http://egress:3128", run)                       # agents: public internet, no home network
        self.assertIn("HTTPS_PROXY=http://egress:3129", login)                     # sign-ins: Anthropic only
        for cmd in (run, login):
            self.assertIn("https_proxy=http://egress:" + ("3128" if cmd is run else "3129"), cmd)
            self.assertNotIn("host", cmd)
            self.assertNotIn("bridge", cmd)

    def test_unknown_mode_is_refused(self):
        for mode in ("", "root", "web,code", None, "CODE"):
            with self.assertRaises(ValueError, msg=str(mode)):
                L.build_chat_command(chat_id=5, user_id=2, model="haiku", ticket=TICKET, mode=mode)
    def test_bad_values(self):
        for change in ({"chat_id": 0}, {"chat_id": "5"}, {"user_id": 0}, {"model": "-gpt"}, {"effort": "--max"},
                       {"ticket": ""}, {"ticket": None}, {"memory": "x"}):
            with self.assertRaises(ValueError, msg=str(change)):
                L.build_chat_command(**{"chat_id": 5, "user_id": 2, "model": "haiku",
                                        "ticket": TICKET, **change})


class ReadOnlyFolderTest(unittest.TestCase):
    """Janis, 16.11.2026: the user's files at /files and the code at /code, never writable."""

    def test_runs_and_chats_mount_them_read_only(self):
        run = L.build_command(**GOOD, files_dir="/opt/agent-hub/work/views/run-7/files")
        self.assertIn("type=bind,src=/opt/agent-hub/work/views/run-7/files,dst=/files,readonly", run)
        chat = L.build_chat_command(chat_id=5, user_id=2, model="haiku", ticket=TICKET,
                                    files_dir="/v/chat-5/files", code_dir="/v/chat-5/code")
        self.assertIn("type=bind,src=/v/chat-5/files,dst=/files,readonly", chat)
        self.assertIn("type=bind,src=/v/chat-5/code,dst=/code,readonly", chat)
        tools = chat[chat.index("--tools") + 1]
        self.assertTrue({"Read", "Glob", "Grep"} <= set(tools.split(",")))      # to open them
        vibe = L.build_vibe_command(name="agent-run-7", user_id=2, model="mistral-small-2603", ticket=TICKET,
                                    job="run", work_dir="/w/7", files_dir="/v/run-7/files")
        self.assertIn("type=bind,src=/v/run-7/files,dst=/files,readonly", vibe)

    def test_without_them_nothing_is_mounted_and_bad_paths_are_refused(self):
        chat = L.build_chat_command(chat_id=5, user_id=2, model="haiku", ticket=TICKET)
        self.assertFalse(any("dst=/files" in part or "dst=/code" in part for part in chat))
        self.assertNotIn("Read", chat[chat.index("--tools") + 1].split(","))
        for bad in ("relative/files", "/v/a,dst=/etc", "/v/../etc", "/v/a b"):
            with self.assertRaises(ValueError):
                L.build_command(**GOOD, files_dir=bad)


class TokenTest(unittest.TestCase):
    """Since 14.11.2026 no run holds the user's Claude token: only a ticket, and every request goes to the gateway."""

    def test_runs_reach_claude_only_through_the_gateway(self):
        for cmd in (L.build_command(**GOOD), L.build_chat_command(chat_id=5, user_id=2, model="haiku", ticket=TICKET)):
            self.assertIn(f"CLAUDE_CODE_OAUTH_TOKEN={TICKET}", cmd)
            self.assertIn("ANTHROPIC_BASE_URL=http://egress:3130", cmd)
            self.assertIn("NO_PROXY=egress", cmd)                                # straight to the gateway, not the proxy
            self.assertIn("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1", cmd)      # nothing else goes to Anthropic
            self.assertIn("HOME=/home/claude", cmd)
            self.assertIn("/home/claude:rw,size=32m,mode=1777", cmd)            # an empty home in memory
            self.assertFalse(any("sk-ant-" in part for part in cmd))
            self.assertFalse(any("dst=/claude" in part for part in cmd))

    def test_the_sign_in_makes_a_setup_token_and_keeps_nothing(self):
        cmd = L.build_login_command(user_id=2)
        self.assertEqual(cmd[-2:], ["claude", "setup-token"])
        self.assertNotIn("--mount", cmd)
        self.assertIn("HOME=/home/claude", cmd)
        self.assertIn("-t", cmd)


class ChatOutputTest(unittest.TestCase):
    def test_the_chat_streams_with_thought_summaries(self):
        cmd = L.build_chat_command(chat_id=5, user_id=2, model="haiku", ticket=TICKET)
        at = cmd.index("--output-format")
        self.assertEqual(cmd[at + 1], "stream-json")
        for flag in ("--verbose", "--include-partial-messages"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("--thinking-display") + 1], "summarized")
        run = L.build_command(run_id=1, user_id=2, model="haiku", work_dir="/opt/agent-hub/work/1", ticket=TICKET)
        self.assertEqual(run[run.index("--output-format") + 1], "json")      # agent runs keep the one JSON object

    def test_the_result_line_of_a_stream(self):
        lines = [{"type": "system", "subtype": "init"},
                 {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}}},
                 {"type": "result", "subtype": "success", "is_error": False, "result": " Hi! ",
                  "usage": {"input_tokens": 3, "output_tokens": 2}}]
        out = "\n".join(json.dumps(x) for x in lines) + "\n"
        self.assertEqual(L.parse_chat_output(out), (True, "Hi!", 3, 2, False))
        self.assertFalse(L.parse_chat_output("\n".join(json.dumps(x) for x in lines[:2]))[0])   # no result: failure
        broken = '{"type": "system"}\nnot json\n' + json.dumps(lines[2])
        self.assertTrue(L.parse_chat_output(broken)[0])

    def test_thought_pieces(self):
        def line(event):
            return json.dumps({"type": "stream_event", "event": event})
        start = line({"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}})
        piece = line({"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "Farbe "}})
        self.assertEqual(L.claude_thought(start), "\n\n")                  # a new block starts a paragraph
        self.assertEqual(L.claude_thought(piece), "Farbe ")
        for other in (line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "thinking"}}),
                      line({"type": "content_block_delta", "delta": {"type": "signature_delta", "signature": "x"}}),
                      line({"type": "content_block_start", "content_block": {"type": "text", "text": "thinking"}}),
                      json.dumps({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "x"}]}}),
                      json.dumps({"type": "result", "result": "thinking"}), '"thinking', "[1]", ""):
            self.assertEqual(L.claude_thought(other), "", other)
        self.assertEqual(L.vibe_thought(json.dumps({"thought": "Rot?"})), "\n\nRot?")
        for other in (json.dumps({"ok": True, "text": "thought"}), json.dumps({"thought": 3}), json.dumps({"thought": " "}),
                      '{"thought": broken', ""):
            self.assertEqual(L.vibe_thought(other), "", other)

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
        for text in ("The login page fails: log in shows an OAuth error", "authenticate the user first"):
            self.assertFalse(L.parse_chat_output(json.dumps({"is_error": True, "result": text}))[4], text)

    def test_outside_tools_in_the_stream(self):
        call = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "WebFetch", "input": {}}]}}
        self.assertTrue(L.claude_outside(json.dumps(call)))
        call["message"]["content"][0]["name"] = "Read"
        self.assertFalse(L.claude_outside(json.dumps(call)))
        self.assertFalse(L.claude_outside(json.dumps({"type": "result", "result": "WebFetch tool_use"})))
        self.assertTrue(L.vibe_outside('{"outside": true}'))
        self.assertFalse(L.vibe_outside('{"thought": "outside"}'))


class OutputTest(unittest.TestCase):
    """An agent run: adapters.Claude.parse_run reads Claude Code's JSON, result_of the answer's last line."""

    def result(self, role, out):
        from runner import adapters
        ok, text, tokens_in, tokens_out, _ = adapters.Claude().parse_run(out)
        return (*L.result_of(role, text, failed=not ok), tokens_in, tokens_out)

    def test_result_marker_report_and_tokens(self):
        result = self.result("tester", answer("All good.\nChecked 3 things.\nRESULT: pass"))
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
            self.assertEqual(self.result(role, out)[0], "failed", (role, out))

    def test_marker_must_be_the_last_line(self):
        self.assertEqual(self.result("programmer", answer("RESULT: done\nand then more text"))[0], "failed")

    def test_report_is_capped_and_role_checked(self):
        self.assertEqual(len(self.result("chef", answer("x" * 50000 + "\nRESULT: done"))[1]), L.MAX_REPORT)
        with self.assertRaises(ValueError):
            self.result("janitor", answer("x"))


class ConsistencyTest(unittest.TestCase):
    """The launcher repeats a few lists of the hub (it lives in another image): they must agree."""

    def test_same_lists_as_the_hub(self):
        try:
            from app import catalog, workflow
        except ImportError:
            self.skipTest("hub code not available")
        # models and levels are a list of the hub; the launcher only checks the same safe patterns
        self.assertEqual(L._MODEL.pattern, catalog._ID.pattern)
        self.assertEqual(L._EFFORT.pattern, catalog._EFFORT.pattern)
        self.assertEqual(L.ROLES, workflow.ROLES)
        # "skipped" is the chief's own result (a test left out without the Mac), no run reports it
        self.assertEqual({k: set(v) for k, v in L.RESULTS.items()},
                         {k: set(v) - {"skipped"} for k, v in workflow.RESULTS.items()})


if __name__ == "__main__":
    unittest.main()
