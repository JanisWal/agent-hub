"""The tool loop for an AI that has only an API (hubloop.py) and the check of its address (custom.py), 20.11.2026."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from runner import custom, hubloop, launcher, runner, tokens

TICKET = "hubrun-" + "x" * 43


def reply(content="", calls=None, tokens_in=10, tokens_out=3, thinking=None):
    message = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = calls
    if thinking:
        message["reasoning_content"] = thinking
    return {"choices": [{"message": message}], "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_out}}


class LoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name) / "work"
        self.work.mkdir()
        (self.work / "plan.md").write_text("Relais 12 V")
        tools = hubloop.hub_tools
        for patch in (mock.patch.object(tools, "ROOTS", (str(self.work),)),
                      mock.patch.object(tools, "WRITE_ROOT", str(self.work))):
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self.tmp.cleanup)
        self.sent = []

    def run_loop(self, answers, job="chat-apart", turns=6):
        answers = list(answers)

        def post(path, body):
            self.sent.append(json.loads(json.dumps(body)))
            item = answers.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        out = io.StringIO()
        with mock.patch.object(hubloop, "post", post), redirect_stdout(out):
            result = hubloop.loop("The package", "llama3.1:8b", job, turns, 60)
        return result, [json.loads(line) for line in out.getvalue().splitlines()]

    def test_tool_calls_the_apis_own_way(self):
        call = {"id": "c1", "type": "function",
                "function": {"name": "read_file", "arguments": json.dumps({"path": str(self.work / "plan.md")})}}
        result, lines = self.run_loop([reply(calls=[call], thinking="Erst lesen."), reply("Es sind 12 V.")])
        self.assertEqual((result["ok"], result["text"], result["tokens_in"], result["tokens_out"]),
                         (True, "Es sind 12 V.", 20, 6))
        self.assertEqual(lines, [{"thought": "Erst lesen."}])
        first, second = self.sent
        self.assertEqual(first["model"], "llama3.1:8b")
        self.assertNotIn("fetch", [t["function"]["name"] for t in first["tools"]])   # apart: no web
        self.assertEqual(second["messages"][-1], {"role": "tool", "tool_call_id": "c1", "content": "Relais 12 V"})

    def test_an_api_without_tool_calls_gets_them_as_text(self):
        text_call = f'<tool name="read_file">{{"path": "{self.work / "plan.md"}"}}</tool>'
        result, _ = self.run_loop([hubloop.Stop("HTTP 400 tools not supported", 400), reply(text_call), reply("12 V")])
        self.assertEqual(result["text"], "12 V")
        self.assertNotIn("tools", self.sent[1])
        self.assertIn("<tool name=", self.sent[1]["messages"][0]["content"])
        self.assertIn('<tool-result name="read_file">\nRelais 12 V', self.sent[2]["messages"][-1]["content"])

    def test_limits_refusals_and_a_brief_job(self):
        call = {"id": "c", "function": {"name": "list_files", "arguments": json.dumps({"path": str(self.work)})}}
        result, _ = self.run_loop([reply(calls=[call])] * 2, turns=2)
        self.assertEqual((result["ok"], result["outcome"]), (False, "steps"))
        result, _ = self.run_loop([hubloop.Stop("HTTP 401 invalid key", 401)])
        self.assertIn("401", result["error"])
        ok, text, _, _, login = launcher.parse_vibe(json.dumps(result))
        self.assertEqual((ok, login), (False, True))                        # the runner treats it as a refused key
        result, _ = self.run_loop([reply("Kurz.")], job="run-brief")
        self.assertNotIn("tools", self.sent[-1])
        self.assertEqual(result["text"], "Kurz.")

    def test_bad_settings(self):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"HUB_MODEL": "-rf", "HUB_JOB": "chat-all"}), redirect_stdout(out):
            hubloop.main()
        self.assertEqual(json.loads(out.getvalue())["outcome"], "usage_error")


class CommandTest(unittest.TestCase):
    def test_the_container_of_the_own_ai(self):
        with tempfile.TemporaryDirectory() as work:
            cmd = launcher.build_hubloop_command(name="agent-run-4", user_id=3, model="deepseek/deepseek-chat:free",
                                                 ticket=TICKET, job="run", net="apart", work_dir=work)
        self.assertIn("HUB_GATEWAY=http://egress:3132", cmd)
        self.assertIn("HUB_MODEL=deepseek/deepseek-chat:free", cmd)
        self.assertIn("HTTPS_PROXY=http://egress:3129", cmd)
        self.assertEqual(cmd[-2:], ["python3", "/opt/hub/hubloop.py"])
        self.assertIn("--read-only", cmd)
        for bad in (dict(model="-x"), dict(model="a b"), dict(ticket="sk-real"), dict(job="shell"), dict(name="x")):
            args = dict(name="agent-chat-1", user_id=3, model="llama3", ticket=TICKET, job="chat-all")
            args.update(bad)
            with self.assertRaises(ValueError):
                launcher.build_hubloop_command(**args)

    def test_the_ticket_carries_the_address(self):
        with tempfile.TemporaryDirectory() as folder:
            box = tokens.Tickets(folder)
            ticket = box.issue("-", "custom", upstream="http://192.168.1.5:11434/v1", lan=True)
            self.assertEqual(tokens.lookup_route(folder, ticket, provider="custom"),
                             ("-", "http://192.168.1.5:11434/v1", True))
            self.assertIsNone(tokens.lookup_route(folder, ticket, provider="mistral"))
            with self.assertRaises(ValueError):
                box.issue("k", "custom", upstream="http://a.example/v1\nlan")
            with self.assertRaises(ValueError):
                box.issue("k", "custom")                                        # no address, no ticket


class VerifyTest(unittest.TestCase):
    def resolve(self, *addresses):
        return lambda host, port, type=0: [(2, 1, 6, "", (a, port)) for a in addresses]

    def test_only_allowed_addresses_are_asked(self):
        self.assertEqual(custom.verify("k", "https://ai.example.com/v1", resolve=self.resolve("10.0.0.5")), "address")
        self.assertEqual(custom.verify("k", "http://ai.lan:8080/v1", True, resolve=self.resolve("172.20.0.4")), "address")
        self.assertEqual(custom.verify("k", "https://x.example/v1", resolve=self.resolve("93.184.216.34", "127.0.0.1")),
                         "address")                                          # every address must be allowed
        self.assertEqual(custom.verify("k", "not a url"), "address")

    def test_a_runner_hands_the_address_to_the_check(self):
        seen = []

        class Verifier:
            def verify(self, key, endpoint, lan):
                seen.append((key, endpoint, lan))
                return "ok"

        class Keys:
            def save(self, *args):
                seen.append(args)

        class Hub:
            def call(self, method, path, **form):
                if path == "/runner/keys/claim":
                    return {"keys": [{"user_id": 2, "provider": "custom-3", "key": "-",
                                      "endpoint": "http://192.168.1.5:11434/v1", "lan": True}]}
                seen.append((path, form))
                return {"ok": True}
        r = runner.Runner(Hub(), "/nowhere", vault=object(), tickets=object(), keys=Keys(),
                          verifiers={"custom-3": Verifier()}, background=False)
        r.handle_keys()
        self.assertEqual(seen[0], ("-", "http://192.168.1.5:11434/v1", True))
        self.assertEqual(seen[1], (2, "custom-3", "-"))
        self.assertEqual(seen[2], ("/runner/keys/2/custom-3/done", {"success": "1"}))

    def test_a_job_of_a_further_ai_uses_the_key_of_its_place(self):
        loaded, calls = [], []

        class Keys:
            def load(self, user_id, name):
                loaded.append(name)
                return None if name == "custom-5" else "sk-local"

            def forget(self, user_id, name):
                calls.append(("forget", name))

        class Hub:
            def call(self, method, path, **form):
                calls.append(path)
                return {"ok": True}
        r = runner.Runner(Hub(), "/nowhere", vault=object(), tickets=object(), keys=Keys(), background=False)
        adapter = runner.adapters.ADAPTERS["custom"]
        self.assertEqual(r._secret(adapter, 2, "plan", {"route": {"slot": 3}}), ("sk-local", ""))
        self.assertEqual(loaded, ["custom-3"])
        self.assertIsNone(r._secret(adapter, 2, "plan", {"route": {"slot": 5}})[0])   # gone: that place shows expired
        self.assertEqual(calls, [("forget", "custom-5"), "/runner/keys/2/custom-5/expired"])
        calls.clear()
        self.assertIsNone(r._secret(adapter, 2, "plan", {"route": {"slot": "1; rm"}})[0])   # no place: nothing touched
        self.assertEqual(calls, [])
        self.assertEqual(loaded, ["custom-3", "custom-5"])

    def test_keys_of_further_ais_are_kept_per_place_and_tickets_take_them(self):
        self.assertTrue(all(f"custom-{n}" in tokens.KEY_PATTERNS for n in range(1, 9)))
        self.assertNotIn("custom", tokens.KEY_PATTERNS)
        self.assertNotIn("custom-9", tokens.KEY_PATTERNS)
        self.assertTrue(tokens._secret_ok("custom", "sk-local"))


if __name__ == "__main__":
    unittest.main()
