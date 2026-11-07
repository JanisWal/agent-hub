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
        self.assertEqual(len(L.parse_output("documenter", answer("x" * 50000 + "\nRESULT: done"))[1]), L.MAX_REPORT)
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
