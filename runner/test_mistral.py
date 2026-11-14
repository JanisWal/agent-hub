"""The Mistral adapter, the encrypted API keys and the runner's part, with a fake Mistral and a fake hub (no network).

    bash ~/rt.sh <branch>     (the runner image has `cryptography`; the key store needs it)
"""
import io
import json
import os
import tempfile
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


class AdapterTest(unittest.TestCase):
    def test_one_question_one_answer(self):
        fake = FakeMistral(reply("Hello"))
        self.assertEqual(mistral.ask(KEY, "mistral-small-2603", "none", "The package", opener=fake),
                         (True, "Hello", 120, 30, False))
        request = fake.requests[0]
        self.assertEqual(request.full_url, "https://api.mistral.ai/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), f"Bearer {KEY}")
        body = json.loads(request.data)
        self.assertEqual(body["model"], "mistral-small-2603")
        self.assertEqual(body["messages"], [{"role": "user", "content": "The package"}])
        self.assertEqual(body["reasoning_effort"], "none")

    def test_no_level_sends_none_of_it_and_thinking_is_left_out(self):
        fake = FakeMistral(reply([{"type": "thinking", "thinking": [{"type": "text", "text": "secret thoughts"}]},
                                  {"type": "text", "text": "The answer"}]))
        ok, text, *_ = mistral.ask(KEY, "mistral-large-4", "", "Q", opener=fake)
        self.assertEqual((ok, text), (True, "The answer"))
        self.assertNotIn("reasoning_effort", json.loads(fake.requests[0].data))

    def test_failures(self):
        ok, text, _, _, auth = mistral.ask(KEY, "mistral-small-2603", "high", "Q", opener=FakeMistral(error=401))
        self.assertEqual((ok, auth), (False, True))
        self.assertTrue(text.startswith("Not logged in"))
        ok, text, _, _, auth = mistral.ask(KEY, "mistral-small-2603", "high", "Q", opener=FakeMistral(error=429))
        self.assertEqual((ok, auth), (False, False))
        self.assertIn("429", text)
        self.assertNotIn(KEY, text)                                   # an error text never carries the key
        ok, text, *_ = mistral.ask(KEY, "mistral-small-2603", "high", "Q", opener=FakeMistral(reply({"choices": []})))
        self.assertFalse(ok)
        self.assertFalse(mistral.ask(KEY, "-rf", "", "Q", opener=FakeMistral())[0])   # never a bad model
        self.assertFalse(mistral.ask(KEY, "mistral-small-2603", "x y", "Q", opener=FakeMistral())[0])

    def test_verify(self):
        fake = FakeMistral({"data": []})
        self.assertEqual(mistral.verify(KEY, opener=fake), "ok")
        self.assertEqual(fake.requests[0].full_url, "https://api.mistral.ai/v1/models")
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


class FakeAdapter:
    def __init__(self, verdict="ok", answer=(True, "Answer", 10, 5, False)):
        self.verdict, self.answer, self.asked = verdict, answer, []

    def verify(self, api_key):
        return self.verdict

    def ask(self, api_key, model, effort, prompt):
        self.asked.append((api_key, model, effort, prompt))
        return self.answer


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


def make(hub, keys=None, adapter=None):
    return runner.Runner(hub, "/nowhere", vault=object(), tickets=object(), keys=keys or FakeKeys(),
                         adapters={"mistral": adapter or FakeAdapter()})


class RunnerTest(unittest.TestCase):
    def test_a_good_key_is_saved_and_reported(self):
        hub, keys = FakeHub(keys=[{"user_id": 5, "provider": "mistral", "key": KEY}]), FakeKeys()
        make(hub, keys).handle_keys()
        self.assertEqual(keys.saved, {(5, "mistral"): KEY})
        self.assertEqual(hub.posted("/runner/keys/5/mistral/done"), [{"success": "1"}])

    def test_a_refused_or_strange_key_is_not_saved(self):
        for verdict, key in (("refused", KEY), ("error", KEY), ("ok", "bad key with spaces")):
            hub, keys = FakeHub(keys=[{"user_id": 5, "provider": "mistral", "key": key}]), FakeKeys()
            make(hub, keys, FakeAdapter(verdict)).handle_keys()
            self.assertEqual(keys.saved, {})
            self.assertEqual(hub.posted("/done"), [{"success": "0"}])

    def test_wipes(self):
        hub, keys = FakeHub(wipes=[{"user_id": 5, "provider": "mistral"}]), FakeKeys({(5, "mistral"): KEY})
        make(hub, keys).handle_key_wipes()
        self.assertEqual(keys.saved, {})
        self.assertEqual(len(hub.posted("/runner/keys/5/mistral/wiped")), 1)

    def test_a_question_goes_to_mistral_without_a_container(self):
        job = {"chat_id": 9, "user_id": 5, "model": "mistral-small-2603", "prompt": "Package", "mode": "all",
               "effort": "none", "provider": "mistral"}
        adapter = FakeAdapter()
        hub = FakeHub(job=job)
        r = make(hub, FakeKeys({(5, "mistral"): KEY}), adapter)
        r.run_chat = lambda *a: self.fail("no container for Mistral")
        r.handle_chat()
        self.assertEqual(adapter.asked, [(KEY, "mistral-small-2603", "none", "Package")])
        self.assertEqual(hub.posted("/runner/chat/9/finish"),
                         [{"success": "1", "answer": "Answer", "tokens_in": 10, "tokens_out": 5}])

    def test_a_refused_key_goes_and_the_hub_hears_it(self):
        job = {"chat_id": 9, "user_id": 5, "model": "mistral-small-2603", "prompt": "P", "provider": "mistral"}
        keys = FakeKeys({(5, "mistral"): KEY})
        hub = FakeHub(job=job)
        make(hub, keys, FakeAdapter(answer=(False, "Not logged in: refused (401)", 0, 0, True))).handle_chat()
        self.assertEqual(keys.saved, {})
        self.assertEqual(len(hub.posted("/runner/keys/5/mistral/expired")), 1)
        self.assertEqual(hub.posted("/runner/chat/9/finish")[0]["success"], "0")

    def test_no_saved_key(self):
        job = {"chat_id": 9, "user_id": 5, "model": "mistral-small-2603", "prompt": "P", "provider": "mistral"}
        hub = FakeHub(job=job)
        make(hub).handle_chat()
        self.assertEqual(len(hub.posted("/runner/keys/5/mistral/expired")), 1)
        self.assertIn("Not logged in", hub.posted("/runner/chat/9/finish")[0]["answer"])


if __name__ == "__main__":
    unittest.main()
