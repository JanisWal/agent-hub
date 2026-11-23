"""ChatGPT through Codex (codex.py, codex_entry.py), the model lists (models.py) and the measured tools, 21.11.2026."""
import base64
import io
import json
import os
import tempfile
import types
import unittest
import urllib.error
from pathlib import Path

from runner import adapters, codex, codex_entry, launcher, models, runner, tokens

TICKET = "hubrun-" + "c" * 43


def jwt(payload: dict) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{enc({'alg': 'RS256'})}.{enc(payload)}.signature1234"


AUTH = {"OPENAI_API_KEY": None, "tokens": {
    "id_token": jwt({"email": "a@b.c", "https://api.openai.com/auth": {"chatgpt_account_id": "acct-1", "chatgpt_plan_type": "plus"}}),
    "access_token": jwt({"exp": 2_000_000_000}), "refresh_token": "rt-1", "account_id": "acct-1"},
    "last_refresh": "2026-11-21T08:00:00Z"}


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class CodexTest(unittest.TestCase):
    def test_link_and_code_from_the_screen(self):
        screen = ("\x1b[94mhttps://auth.openai.com/codex/device\x1b[0m\n2. Enter this one-time code \x1b[90m(expires in 15 "
                  "minutes)\x1b[0m\n   \x1b[94mAB12-CDE34\x1b[0m\n")
        self.assertEqual(codex.login_prompt(screen), ("https://auth.openai.com/codex/device", "AB12-CDE34"))
        self.assertIsNone(codex.login_prompt("Welcome to Codex"))

    def test_the_kept_tokens_and_the_runs_wrapper(self):
        kept = codex.read_auth(json.dumps(AUTH), now=100)
        self.assertEqual((kept["account"], kept["plan"], kept["refresh"]), ("acct-1", "plus", "rt-1"))
        self.assertEqual(codex.loads(codex.dumps(kept)), kept)
        auth = codex.run_auth(TICKET, kept, now=100)
        self.assertNotIn(kept["access"], auth)                                # never the real token in a run
        self.assertNotIn("rt-1", auth)
        self.assertNotIn("a@b.c", auth)                                        # nor the e-mail of the id token
        wrapped = json.loads(auth)["tokens"]["access_token"]
        self.assertEqual(codex.ticket_of(wrapped), TICKET)
        self.assertEqual(codex.claims(wrapped)["https://api.openai.com/auth"]["chatgpt_account_id"], "acct-1")
        self.assertTrue(launcher._codex_auth(auth))
        self.assertFalse(launcher._codex_auth(json.dumps(AUTH)))              # a real auth.json is refused
        with self.assertRaises(ValueError):
            codex.read_auth(json.dumps({"OPENAI_API_KEY": "sk-x"}))

    def test_only_the_runner_refreshes_and_only_when_needed(self):
        kept = codex.read_auth(json.dumps(AUTH), now=1_000_000)
        self.assertEqual(codex.fresh(kept, now=1_000_100, opener=None), (kept, False))
        kept["access"] = jwt({"exp": 1_000_200})                              # runs out in 100 s
        calls = []

        def opener(request, timeout):
            calls.append((request.full_url, json.loads(request.data)))
            return Answer(json.dumps({"access_token": jwt({"exp": 1_100_000}), "refresh_token": "rt-2"}).encode())
        renewed, changed = codex.fresh(kept, now=1_000_100, opener=opener)
        self.assertTrue(changed)
        self.assertEqual(renewed["refresh"], "rt-2")                          # the new one replaces the used one
        url, body = calls[0]
        self.assertEqual(url, "https://auth.openai.com/oauth/token")
        self.assertEqual((body["grant_type"], body["client_id"], body["refresh_token"]),
                         ("refresh_token", codex.CLIENT_ID, "rt-1"))

        def refused(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 400, "used", {}, io.BytesIO(b"{}"))
        with self.assertRaises(codex.Refused):
            codex.fresh(kept, now=1_000_100, opener=refused)

    def test_the_container_of_a_chatgpt_run_and_of_the_sign_in(self):
        auth = codex.run_auth(TICKET, {"account": "acct-1", "plan": "plus"})
        with tempfile.TemporaryDirectory() as work:
            cmd = launcher.build_codex_command(name="agent-run-5", user_id=2, model="gpt-6.1-sol", effort="medium",
                                               auth=auth, job="run", net="apart", work_dir=work)
        self.assertIn("HUB_GATEWAY=http://egress:3133", cmd)
        self.assertIn("agent-hub-codex", cmd)
        self.assertIn("HTTPS_PROXY=http://egress:3129", cmd)
        for bad in (dict(auth=json.dumps(AUTH)), dict(model="-x"), dict(job="shell"), dict(name="x")):
            args = dict(name="agent-chat-1", user_id=2, model="gpt-6-luna", effort="low", auth=auth, job="chat-all")
            args.update(bad)
            with self.assertRaises(ValueError):
                launcher.build_codex_command(**args)
        with tempfile.TemporaryDirectory() as folder:
            login = launcher.build_codex_login_command(user_id=2, folder=folder)
        self.assertIn("--device-auth", login)
        self.assertIn("CODEX_HOME=/login", login)

    def test_the_entry_script(self):
        config = codex_entry.config("gpt-6-luna", "low", "chat-all")
        for part in ('chatgpt_base_url = "http://egress:3133/backend-api/"', "supports_websockets = false",
                     "requires_openai_auth = true", "plugins = false", 'cli_auth_credentials_store = "file"'):
            self.assertIn(part, config)
        self.assertIn('sandbox_mode = "read-only"', codex_entry.config("m", "", "chat-brief"))
        events = [{"type": "item.completed", "item": {"type": "agent_message", "text": "Fertig"}},
                  {"type": "turn.completed", "usage": {"input_tokens": 30, "cached_input_tokens": 20, "output_tokens": 5}}]
        self.assertEqual(codex_entry.summary(events, 0, ""),
                         {"ok": True, "text": "Fertig", "tokens_in": 30, "tokens_out": 5, "cache_read": 20,
                          "outcome": "finished", "error": ""})
        plan = codex_entry.summary([{"type": "error", "message": "unexpected status 403 Forbidden"}], 1, "")
        self.assertEqual(plan["outcome"], "plan")
        ok, text, _, _, login = launcher.parse_vibe(json.dumps(plan))
        self.assertIn("(plan)", text)
        self.assertFalse(login)

    def test_an_ended_plan_is_a_login_problem(self):
        """23.11.2026: after the plan ended Codex said its token could not be refreshed; the connection stayed
        "connected" and the next AI never took over. Both of its words count as a refused sign-in."""
        for message in ("Your access token could not be refreshed. Please log out and sign in again.",
                        "error sending request for url (https://auth.openai.com/oauth/token)"):
            failed = codex_entry.summary([{"type": "error", "message": message}], 1, "")
            ok, text, _, _, login = launcher.parse_vibe(json.dumps(failed))
            self.assertTrue(login, message)
            self.assertFalse(ok)
        other = codex_entry.summary([{"type": "error", "message": "stream disconnected"}], 1, "")
        self.assertFalse(launcher.parse_vibe(json.dumps(other))[4])             # a bad moment is not a sign-out


class FakeKeys:
    def __init__(self, saved=None):
        self.saved = dict(saved or {})

    def load(self, user_id, provider):
        return self.saved.get((user_id, provider))

    def save(self, user_id, provider, value):
        self.saved[(user_id, provider)] = value

    def forget(self, user_id, provider):
        return self.saved.pop((user_id, provider), None) is not None


class Hub:
    def __init__(self, answers=None):
        self.calls, self.answers = [], answers or {}

    def call(self, method, path, **form):
        self.calls.append((path, form))
        return self.answers.get(path, {"ok": True})

    def posted(self, end):
        return [form for path, form in self.calls if path.endswith(end)]


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def make(self, hub, keys):
        return runner.Runner(hub, self.tmp.name, vault=object(), tickets=tokens.Tickets(self.tmp.name), keys=keys,
                             background=False)

    def test_the_sign_in_keeps_the_tokens_and_reports_link_and_code(self):
        hub, keys = Hub({"/runner/device-logins": {"logins": [{"user_id": 2, "provider": "chatgpt"}]}}), FakeKeys()
        r = self.make(hub, keys)
        if os.geteuid() != 0:
            self.skipTest("needs root (the folder is handed to the run user)")

        def run_login(command, on_line):
            folder = Path(command[command.index("--mount") + 1].split("src=")[1].split(",")[0])
            on_line("https://auth.openai.com/codex/device\n")
            on_line("Enter this one-time code\n  AB12-CDE34\n")
            (folder / "auth.json").write_text(json.dumps(AUTH))
            return 0
        r.run_login = run_login
        r.handle_device_logins()
        self.assertEqual(hub.posted("/chatgpt/url"), [{"url": "https://auth.openai.com/codex/device", "code": "AB12-CDE34"}])
        self.assertEqual(hub.posted("/runner/keys/2/chatgpt/done"), [{"success": "1"}])
        self.assertEqual(codex.loads(keys.saved[(2, "chatgpt")])["account"], "acct-1")
        self.assertFalse(r._login_folder(2).exists())                         # the plain auth.json is gone

    def test_a_refused_refresh_deletes_and_an_unreachable_one_keeps(self):
        kept = codex.read_auth(json.dumps(AUTH), now=0)
        kept["access"] = jwt({"exp": 1})
        keys = FakeKeys({(2, "chatgpt"): codex.dumps(kept)})
        adapter = adapters.ADAPTERS["chatgpt"]
        r = self.make(Hub(), keys)
        original = codex.fresh
        try:
            codex.fresh = lambda k: (_ for _ in ()).throw(OSError("down"))
            self.assertEqual(r._secret(adapter, 2), (None, runner.LATER))
            self.assertIn((2, "chatgpt"), keys.saved)                          # kept
            codex.fresh = lambda k: (_ for _ in ()).throw(codex.Refused("used"))
            self.assertEqual(r._secret(adapter, 2)[0], None)
            self.assertNotIn((2, "chatgpt"), keys.saved)                       # refused by OpenAI: gone
        finally:
            codex.fresh = original

    def test_model_lists_are_asked_and_reported(self):
        hub = Hub({"/runner/model-checks": {"checks": [{"user_id": 3, "provider": "mistral"}]}})
        r = self.make(hub, FakeKeys({(3, "mistral"): "K" * 32}))
        r.fetch_models = lambda provider, secret: [{"id": "mistral-large-5", "capabilities": {"completion_chat": True}}]
        r.handle_model_checks()
        [posted] = hub.posted("/runner/models/3/mistral")
        self.assertEqual(json.loads(posted["models"])[0]["id"], "mistral-large-5")
        opened = []

        def opener(request, timeout):
            opened.append(dict(request.header_items()))
            return Answer(json.dumps({"data": [{"id": "claude-opus-5-5"}]}).encode())
        self.assertEqual(models.fetch("claude", "sk-ant-oat01-x", opener), [{"id": "claude-opus-5-5"}])
        self.assertEqual(opened[0]["Anthropic-beta"], "oauth-2025-04-20")

    def test_claudes_own_tools_are_read_and_the_hubs_given_only_when_asked(self):
        init = json.dumps({"type": "system", "subtype": "init", "tools": ["Bash", "Read", "WebSearch"]})
        self.assertEqual(launcher.claude_tools(init), ["Bash", "Read", "WebSearch"])
        self.assertIsNone(launcher.claude_tools(json.dumps({"type": "assistant"})))
        plain = launcher.build_chat_command(chat_id=1, user_id=2, model="sonnet", ticket=TICKET, mode="all")
        self.assertNotIn("--mcp-config", plain)
        with_hub = launcher.build_chat_command(chat_id=1, user_id=2, model="sonnet", ticket=TICKET, mode="all",
                                               hub_tools=["fetch", "rm -rf"])
        config = json.loads(with_hub[with_hub.index("--mcp-config") + 1])
        self.assertEqual(config["mcpServers"]["hub"]["env"]["HUB_TOOLS"], "fetch")   # only names of the list
        self.assertIn("mcp__hub__fetch", with_hub[with_hub.index("--allowedTools") + 1])
        self.assertEqual(launcher.asked_tools(plain), ["WebSearch", "WebFetch", "Bash"])


if __name__ == "__main__":
    unittest.main()
