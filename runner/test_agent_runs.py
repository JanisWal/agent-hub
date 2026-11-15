"""Agent runs for every AI (15.11.2026): tickets per AI, the Vibe container, the work folders with real git, the runner
doing a run, merging and cleaning up. Needs git (the runner image has it).

    docker run --rm -v ~/hub-test/runner:/app/runner agent-hub-runner-test python -m unittest runner.test_agent_runs
"""
import json
import os
import subprocess
import tempfile
import types
import unittest
from pathlib import Path

from runner import egress, launcher, runner, tokens, vibe_entry, workspace

KEY = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
CLAUDE = "sk-ant-oat01-" + "t" * 80
TICKET = "hubrun-" + "x" * 43


class TicketTest(unittest.TestCase):
    def test_a_ticket_only_works_at_the_gateway_of_its_ai(self):
        with tempfile.TemporaryDirectory() as folder:
            tickets = tokens.Tickets(folder)
            ticket = tickets.issue(KEY, "mistral")
            self.assertEqual(tokens.lookup(folder, ticket, provider="mistral"), KEY)
            self.assertIsNone(tokens.lookup(folder, ticket))                  # not at Claude's gateway
            claude = tickets.issue(CLAUDE)
            self.assertEqual(tokens.lookup(folder, claude), CLAUDE)
            self.assertIsNone(tokens.lookup(folder, claude, provider="mistral"))
            bare = "hubrun-" + "o" * 43                                       # a file that does not name its AI
            (Path(folder) / tokens.ticket_name(bare)).write_text(CLAUDE)
            self.assertIsNone(tokens.lookup(folder, bare))
            with self.assertRaises(ValueError):
                tickets.issue("not a key!", "mistral")                         # not a Mistral key
            with self.assertRaises(ValueError):
                tickets.issue(KEY, "chatgpt")

    def test_the_mistral_gateway(self):
        self.assertEqual(egress.GATEWAYS["mistral"], ("api.mistral.ai", 3131))
        head = egress.rewrite("POST", "/v1/chat/completions", [("Authorization", f"Bearer {TICKET}")], KEY, 2,
                              "api.mistral.ai").decode()
        self.assertIn("Host: api.mistral.ai", head)
        self.assertIn(f"Authorization: Bearer {KEY}", head)
        self.assertNotIn(TICKET, head)
        self.assertIsNone(egress.parse_request(b"GET /api/v1/code/managed-config HTTP/1.1\r\nHost: x\r\n\r\n"))


class VibeCommandTest(unittest.TestCase):
    def test_chat_and_run(self):
        cmd = launcher.build_vibe_command(name="agent-chat-9", user_id=5, model="mistral-small-2603", ticket=TICKET,
                                          job="chat-all", effort="none")
        line = " ".join(cmd)
        for part in ("--read-only", "--user 10005:10005", "--network agent-hub-agents", "--cap-drop ALL",
                     f"MISTRAL_API_KEY={TICKET}", "HUB_GATEWAY=http://egress:3131", "HUB_JOB=chat-all",
                     "HTTPS_PROXY=http://egress:3128", "NO_PROXY=egress", "agent-hub-vibe python /opt/hub/vibe_entry.py"):
            self.assertIn(part, line)
        self.assertNotIn("--mount", line)                                     # no folder of any project in a chat
        apart = " ".join(launcher.build_vibe_command(name="agent-chat-9", user_id=5, model="mistral-small-2603",
                                                     ticket=TICKET, job="chat-apart"))
        self.assertIn("HTTPS_PROXY=http://egress:3129", apart)
        with tempfile.TemporaryDirectory() as work:
            run = launcher.build_vibe_command(name="agent-run-3", user_id=5, model="mistral-large-4", ticket=TICKET,
                                              job="run", effort="high", net="apart", work_dir=work)
        self.assertIn(f"type=bind,src={work},dst=/work", run)
        self.assertIn("HUB_SECONDS=1050", run)
        for bad in (dict(model="-rf"), dict(effort="x y"), dict(ticket="sk-real"), dict(job="shell"),
                    dict(name="other")):
            args = dict(name="agent-chat-1", user_id=5, model="mistral-small-2603", ticket=TICKET, job="chat-all")
            args.update(bad)
            with self.assertRaises(ValueError):
                launcher.build_vibe_command(**args)

    def test_reading_the_answer(self):
        good = json.dumps({"ok": True, "text": "Hi\nRESULT: done", "tokens_in": 3, "tokens_out": 2, "outcome": "finished"})
        self.assertEqual(launcher.parse_vibe("noise\n" + good), (True, "Hi\nRESULT: done", 3, 2, False))
        refused = json.dumps({"ok": False, "text": "", "outcome": "infrastructure_failure", "error": "401 Unauthorized"})
        ok, text, _, _, login = launcher.parse_vibe(refused)
        self.assertEqual((ok, login), (False, True))
        self.assertTrue(text.startswith("Not logged in"))
        self.assertFalse(launcher.parse_vibe("")[0])
        self.assertEqual(launcher.result_of("tester", "All good\nRESULT: pass"), ("pass", "All good"))
        self.assertEqual(launcher.result_of("tester", "RESULT: done")[0], "failed")    # not a tester's result

    def test_the_entry_script(self):
        config = vibe_entry.config("mistral-small-2603", "off")
        for part in ('api_base = "http://egress:3131/v1"', "enable_telemetry = false", "enable_update_checks = false",
                     'vibe_base_url = "http://egress:3131"', 'thinking = "off"', 'name = "mistral-small-2603"'):
            self.assertIn(part, config)
        stdout = json.dumps([{"type": "message", "role": "user", "content": [{"type": "text", "text": "Q"}]},
                             {"type": "message", "role": "assistant", "content": [{"type": "text", "text": "A1"}]},
                             {"type": "message", "role": "assistant", "content": [{"type": "text", "text": "Final"}]}])
        out = vibe_entry.summary(stdout, {"outcome": "finished", "usage": {"input_tokens": 7, "output_tokens": 3}}, 0)
        self.assertEqual((out["ok"], out["text"], out["tokens_in"], out["tokens_out"]), (True, "Final", 7, 3))
        self.assertFalse(vibe_entry.summary("", {"outcome": "turn_limit"}, 3)["ok"])


def git(*args, cwd=None):
    return subprocess.run(["git", "-c", "safe.directory=*", *args], capture_output=True, text=True, cwd=cwd).stdout.strip()


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = workspace.Workspace(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_task_from_its_folder_to_main(self):
        tree = self.work.prepare(7, 1, "agent/task-7")
        self.assertFalse((tree / ".git").exists())                            # the run never sees git
        (tree / "relay.py").write_text("ON = True\n")
        self.assertTrue(self.work.commit(7, "agent/task-7", "Task 7: programmer"))
        self.assertFalse(self.work.commit(7, "agent/task-7", "nothing new"))
        repo = self.work.repo(1)
        self.assertIn("relay.py", git(f"--git-dir={repo}", "ls-tree", "--name-only", "agent/task-7"))
        self.assertNotIn("relay.py", git(f"--git-dir={repo}", "ls-tree", "--name-only", "main"))
        self.assertTrue(self.work.merge(7, 1, "agent/task-7"))
        self.assertIn("relay.py", git(f"--git-dir={repo}", "ls-tree", "--name-only", "main"))
        self.work.remove(7)
        self.assertFalse(tree.exists() or self.work.gitdir(7).exists())

    def test_caches_of_running_the_code_are_not_committed(self):
        tree = self.work.prepare(9, 1, "agent/task-9")
        (tree / "__pycache__").mkdir()
        (tree / "__pycache__" / "a.cpython-313.pyc").write_bytes(b"x")
        (tree / "a.py").write_text("A = 1\n")
        self.work.commit(9, "agent/task-9", "Task 9")
        names = git(f"--git-dir={self.work.repo(1)}", "ls-tree", "-r", "--name-only", "agent/task-9")
        self.assertIn("a.py", names)
        self.assertNotIn("pyc", names)

    def test_hooks_and_settings_in_the_folder_do_nothing(self):
        tree = self.work.prepare(8, 1, "agent/task-8")
        (tree / ".git").mkdir()                                               # a run plants a fake git folder
        (tree / ".git" / "config").write_text("[core]\n\tfsmonitor = touch /tmp/pwned-by-run\n")
        (tree / "a.txt").write_text("a")
        self.work.commit(8, "agent/task-8", "Task 8")
        self.assertFalse(Path("/tmp/pwned-by-run").exists())
        self.assertNotIn(".git", git(f"--git-dir={self.work.repo(1)}", "ls-tree", "-r", "--name-only", "agent/task-8"))

    def test_main_moved_on_and_a_conflict(self):
        one, two = self.work.prepare(1, 1, "agent/task-1"), self.work.prepare(2, 1, "agent/task-2")
        (one / "a.txt").write_text("one\n")
        (two / "b.txt").write_text("two\n")
        self.work.commit(1, "agent/task-1", "1")
        self.work.commit(2, "agent/task-2", "2")
        self.assertTrue(self.work.merge(1, 1, "agent/task-1"))
        self.assertTrue(self.work.merge(2, 1, "agent/task-2"))                # main moved: merged, both files there
        names = git(f"--git-dir={self.work.repo(1)}", "ls-tree", "--name-only", "main")
        self.assertIn("a.txt", names)
        self.assertIn("b.txt", names)
        three, four = self.work.prepare(3, 1, "agent/task-3"), self.work.prepare(4, 1, "agent/task-4")
        (three / "a.txt").write_text("three\n")
        (four / "a.txt").write_text("four\n")
        self.work.commit(3, "agent/task-3", "3")
        self.work.commit(4, "agent/task-4", "4")
        self.assertTrue(self.work.merge(3, 1, "agent/task-3"))
        before = git(f"--git-dir={self.work.repo(1)}", "rev-parse", "main")
        self.assertFalse(self.work.merge(4, 1, "agent/task-4"))               # a conflict: nothing changes
        self.assertEqual(git(f"--git-dir={self.work.repo(1)}", "rev-parse", "main"), before)


class FakeKeys:
    def __init__(self, saved=None):
        self.saved = dict(saved or {})

    def load(self, user_id, provider):
        return self.saved.get((user_id, provider))

    def forget(self, user_id, provider):
        return self.saved.pop((user_id, provider), None) is not None


class FakeTickets:
    def __init__(self):
        self.issued, self.revoked = [], []

    def issue(self, secret, provider="claude"):
        self.issued.append((secret, provider))
        return TICKET

    def revoke(self, ticket):
        self.revoked.append(ticket)


class FakeHub:
    def __init__(self, job=None, merges=(), cleanups=(), wipes=()):
        self.job, self.merges, self.cleanups, self.calls = job, list(merges), list(cleanups), []
        self.wipes = list(wipes)

    def call(self, method, path, **form):
        self.calls.append((path, form))
        if path == "/runner/claim":
            job, self.job = self.job, None
            return {"ok": True, "job": job}
        if path == "/runner/merges":
            return {"ok": True, "merges": self.merges}
        if path == "/runner/cleanups":
            return {"ok": True, "task_ids": self.cleanups, "wipes": self.wipes}
        return {"ok": True}

    def posted(self, suffix):
        return [form for path, form in self.calls if path.endswith(suffix)]


class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = workspace.Workspace(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def runner(self, hub, keys=None):
        return runner.Runner(hub, "/nowhere", vault=object(), tickets=FakeTickets(),
                             keys=keys or FakeKeys({(5, "mistral"): KEY}), work=self.work, background=False)

    def job(self, role="programmer"):
        return {"run_id": 3, "user_id": 5, "project_id": 1, "task_id": 7, "role": role, "model": "mistral-small-2603",
                "branch": "agent/task-7", "round": 1, "net": "together", "effort": "none", "provider": "mistral",
                "prompt": "The package"}

    def test_a_programmer_run_of_mistral_is_committed_and_reported(self):
        hub, seen = FakeHub(job=self.job()), []

        def fake_run(command, prompt):
            seen.append((command, prompt))
            (self.work.tree(7) / "relay.py").write_text("ON = True\n")       # what the agent wrote
            return types.SimpleNamespace(stdout=json.dumps({"ok": True, "text": "Built it.\nRESULT: done",
                                                            "tokens_in": 50, "tokens_out": 20}), returncode=0)
        r = self.runner(hub)
        r.run_agent = fake_run
        if os.geteuid() != 0:
            self.skipTest("needs root (the folder is handed to the run user)")
        r.handle_runs()
        command, prompt = seen[0]
        self.assertEqual(prompt, "The package")
        self.assertIn("HUB_JOB=run", command)
        self.assertIn(f"type=bind,src={self.work.tree(7)},dst=/work", command)
        finish = hub.posted("/runner/runs/3/finish")[0]
        self.assertEqual((finish["result"], finish["report"], finish["tokens_in"]), ("done", "Built it.", 50))
        self.assertIn("relay.py", git(f"--git-dir={self.work.repo(1)}", "ls-tree", "--name-only", "agent/task-7"))

    def test_without_a_key_the_run_fails_and_the_menu_hears_it(self):
        hub = FakeHub(job=self.job())
        self.runner(hub, FakeKeys()).handle_runs()
        self.assertEqual(hub.posted("/runner/runs/3/finish")[0]["result"], "failed")
        self.assertEqual(len(hub.posted("/runner/keys/5/mistral/expired")), 1)

    def test_merges_and_cleanups(self):
        tree = self.work.prepare(7, 1, "agent/task-7")
        (tree / "x.txt").write_text("x")
        self.work.commit(7, "agent/task-7", "7")
        hub = FakeHub(merges=[{"task_id": 7, "project_id": 1, "user_id": 5, "branch": "agent/task-7"}], cleanups=[7])
        r = self.runner(hub)
        r.handle_merges()
        self.assertEqual(hub.posted("/runner/merges/7/done"), [{"success": "1"}])
        r.handle_cleanups()
        self.assertFalse(tree.exists())

    def test_the_folders_of_a_deleted_project_go_and_are_reported(self):
        tree = self.work.prepare(7, 1, "agent/task-7")
        other = self.work.prepare(8, 2, "agent/task-8")
        hub = FakeHub(wipes=[{"kind": "task", "ref": 7}, {"kind": "project", "ref": 1}, {"kind": "disk", "ref": 1},
                             {"kind": "project", "ref": 0}])
        self.runner(hub).handle_cleanups()
        self.assertFalse(tree.exists())
        self.assertFalse(self.work.gitdir(7).exists())
        self.assertFalse(self.work.repo(1).exists())
        self.assertTrue(other.exists() and self.work.repo(2).exists())         # another project is not touched
        self.assertEqual(hub.posted("/runner/cleanups/done"),
                         [{"kind": "task", "ref": 7}, {"kind": "project", "ref": 1}])   # unknown kinds: nothing


if __name__ == "__main__":
    unittest.main()
