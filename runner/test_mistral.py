"""The Mistral adapter, the encrypted API keys and the runner's part, with a fake Mistral and a fake hub (no network).

    bash ~/rt.sh <branch>     (the runner image has `cryptography`; the key store needs it)
"""
import io
import json
import os
import tempfile
import types
import unittest
import urllib.error
from pathlib import Path

from runner import mistral, runner, tokens

KEY = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"


class FakeAnswer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeMistral:
    """Records the requests; answers with `reply` (a dict) or raises `error` (an HTTP status)."""
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.requests = reply, error, []

    def __call__(self, request, timeout):
        self.requests.append(request)
        if self.error:
            raise urllib.error.HTTPError(request.full_url, self.error, "x", {},
                                         io.BytesIO(json.dumps({"message": f"bad {KEY}"}).encode()))
        return FakeAnswer(json.dumps(self.reply or {"data": []}).encode())


def reply(content, prompt_tokens=120, completion_tokens=30):
    return {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}}


class VerifyTest(unittest.TestCase):
    def test_verify(self):
        fake = FakeMistral({"data": []})
        self.assertEqual(mistral.verify(KEY, opener=fake), "ok")
        self.assertEqual(fake.requests[0].full_url, "https://api.mistral.ai/v1/models")
        self.assertEqual(fake.requests[0].get_header("Authorization"), f"Bearer {KEY}")
        self.assertEqual(mistral.verify(KEY, opener=FakeMistral(error=401)), "refused")
        self.assertEqual(mistral.verify(KEY, opener=FakeMistral(error=503)), "error")


class KeyStoreTest(unittest.TestCase):
    def setUp(self):
        from cryptography.fernet import Fernet
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.keys = tokens.ProviderKeys(self.base, Fernet.generate_key().decode())

    def tearDown(self):
        self.tmp.cleanup()

    def test_encrypted_on_its_own_and_apart_from_the_claude_folders(self):
        self.keys.save(5, "mistral", KEY)
        path = self.base / "keys" / "mistral" / "5.enc"
        self.assertNotIn(KEY.encode(), path.read_bytes())
        self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
        self.assertEqual(self.keys.load(5, "mistral"), KEY)
        self.assertIsNone(self.keys.load(6, "mistral"))
        tokens.Vault(self.base, None).forget(5)                     # the Claude folder of user 5 goes ...
        self.assertEqual(self.keys.load(5, "mistral"), KEY)         # ... the Mistral key stays
        self.assertTrue(self.keys.forget(5, "mistral"))
        self.assertIsNone(self.keys.load(5, "mistral"))

    def test_bad_values(self):
        for user_id, provider, value in ((0, "mistral", KEY), (5, "../x", KEY), (5, "mistral", "short"),
                                         (5, "mistral", KEY + "\n")):
            with self.assertRaises(ValueError):
                self.keys.save(user_id, provider, value)

    def test_another_server_key_reads_nothing(self):
        from cryptography.fernet import Fernet
        self.keys.save(5, "mistral", KEY)
        other = tokens.ProviderKeys(self.base, Fernet.generate_key().decode())
        self.assertIsNone(other.load(5, "mistral"))


class FakeKeys:
    def __init__(self, saved=None):
        self.saved = dict(saved or {})

    def save(self, user_id, provider, api_key):
        self.saved[(user_id, provider)] = api_key

    def load(self, user_id, provider):
        return self.saved.get((user_id, provider))

    def forget(self, user_id, provider):
        return self.saved.pop((user_id, provider), None) is not None


class FakeVerifier:
    def __init__(self, verdict="ok"):
        self.verdict = verdict

    def verify(self, api_key):
        return self.verdict


class FakeTickets:
    def __init__(self):
        self.issued, self.revoked = [], []

    def issue(self, secret, provider="claude"):
        ticket = "hubrun-" + str(len(self.issued)).rjust(43, "m")
        self.issued.append((ticket, secret, provider))
        return ticket

    def revoke(self, ticket):
        self.revoked.append(ticket)


class FakeHub:
    def __init__(self, keys=(), wipes=(), job=None):
        self.keys, self.wipes, self.job, self.calls = list(keys), list(wipes), job, []

    def call(self, method, path, **form):
        self.calls.append((path, form))
        if path == "/runner/keys/claim":
            keys, self.keys = self.keys, []
            return {"ok": True, "keys": keys}
        if path == "/runner/keys/wipes":
            return {"ok": True, "wipes": self.wipes}
        if path == "/runner/chat/claim":
            return {"ok": True, "job": self.job}
        return {"ok": True}

    def posted(self, suffix):
        return [form for path, form in self.calls if path.endswith(suffix)]


def make(hub, keys=None, verifier=None, tickets=None):
    return runner.Runner(hub, "/nowhere", vault=object(), tickets=tickets or FakeTickets(), keys=keys or FakeKeys(),
                         verifiers={"mistral": verifier or FakeVerifier()}, background=False)


def vibe_line(**kw):
    data = {"ok": True, "text": "Hallo", "tokens_in": 30, "tokens_out": 9, "outcome": "finished", "error": ""}
    data.update(kw)
    return json.dumps(data) + "\n"


class RunnerTest(unittest.TestCase):
    def test_a_good_key_is_saved_and_reported(self):
        hub, keys = FakeHub(keys=[{"user_id": 5, "provider": "mistral", "key": KEY}]), FakeKeys()
        make(hub, keys).handle_keys()
        self.assertEqual(keys.saved, {(5, "mistral"): KEY})
        self.assertEqual(hub.posted("/runner/keys/5/mistral/done"), [{"success": "1"}])

    def test_a_refused_or_strange_key_is_not_saved(self):
        for verdict, key in (("refused", KEY), ("error", KEY), ("ok", "bad key with spaces")):
            hub, keys = FakeHub(keys=[{"user_id": 5, "provider": "mistral", "key": key}]), FakeKeys()
            make(hub, keys, FakeVerifier(verdict)).handle_keys()
            self.assertEqual(keys.saved, {})
            self.assertEqual(hub.posted("/done"), [{"success": "0"}])

    def test_wipes(self):
        hub, keys = FakeHub(wipes=[{"user_id": 5, "provider": "mistral"}]), FakeKeys({(5, "mistral"): KEY})
        make(hub, keys).handle_key_wipes()
        self.assertEqual(keys.saved, {})
        self.assertEqual(len(hub.posted("/runner/keys/5/mistral/wiped")), 1)

    def test_a_question_goes_to_mistral_vibe_in_a_container_with_a_ticket(self):
        job = {"chat_id": 9, "user_id": 5, "model": "mistral-small-2603", "prompt": "Package", "mode": "all",
               "effort": "none", "provider": "mistral"}
        hub, tickets, seen = FakeHub(job=job), FakeTickets(), []
        r = make(hub, FakeKeys({(5, "mistral"): KEY}), tickets=tickets)
        r.run_chat = lambda command, prompt, on_line=None: seen.append((command, prompt)) or types.SimpleNamespace(
            stdout=vibe_line(), returncode=0)
        r.handle_chat()
        command, prompt = seen[0]
        self.assertEqual(prompt, "Package")
        self.assertIn("agent-hub-vibe", command)
        self.assertNotIn(KEY, " ".join(command))                                  # the key never reaches the run
        self.assertIn("MISTRAL_API_KEY=" + tickets.issued[0][0], command)
        self.assertEqual(tickets.issued[0][1:], (KEY, "mistral"))
        self.assertEqual(tickets.revoked, [tickets.issued[0][0]])
        self.assertEqual(hub.posted("/runner/chat/9/finish"),
                         [{"success": "1", "answer": "Hallo", "tokens_in": 30, "tokens_out": 9}])

    def test_a_refused_key_goes_and_the_hub_hears_it(self):
        job = {"chat_id": 9, "user_id": 5, "model": "mistral-small-2603", "prompt": "P", "provider": "mistral"}
        keys, hub = FakeKeys({(5, "mistral"): KEY}), FakeHub(job=job)
        r = make(hub, keys)
        r.run_chat = lambda command, prompt, on_line=None: types.SimpleNamespace(
            stdout=vibe_line(ok=False, text="", outcome="infrastructure_failure", error="HTTP 401 Unauthorized"),
            returncode=0)
        r.handle_chat()
        self.assertEqual(keys.saved, {})
        self.assertEqual(len(hub.posted("/runner/keys/5/mistral/expired")), 1)
        self.assertEqual(hub.posted("/runner/chat/9/finish")[0]["success"], "0")

    def test_no_saved_key(self):
        job = {"chat_id": 9, "user_id": 5, "model": "mistral-small-2603", "prompt": "P", "provider": "mistral"}
        hub = FakeHub(job=job)
        make(hub).handle_chat()
        self.assertEqual(len(hub.posted("/runner/keys/5/mistral/expired")), 1)
        self.assertIn("Not logged in", hub.posted("/runner/chat/9/finish")[0]["answer"])

    def test_an_ai_without_an_adapter_fails_the_question_and_touches_no_key(self):
        job = {"chat_id": 9, "user_id": 5, "model": "x", "prompt": "P", "provider": "nobody"}
        keys, hub = FakeKeys({(5, "mistral"): KEY}), FakeHub(job=job)
        make(hub, keys).handle_chat()
        self.assertEqual(hub.posted("/runner/chat/9/finish")[0]["success"], "0")
        self.assertEqual(keys.saved, {(5, "mistral"): KEY})
        self.assertEqual([path for path, _ in hub.calls if "expired" in path], [])


