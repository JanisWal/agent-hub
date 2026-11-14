"""Mistral as a second AI (14.11.2026): the list of models, the connection with an API key, the manager chat that
asks Mistral, the menu row and the runner interface for keys."""
import copy
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import agents, ai_link, catalog, chat, claude_link, db, i18n, managerpage, projects, ui, users
from app.routes import ai as ai_routes
from app.routes import runner as runner_routes

KEY = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        claude_link.BASE_DIR = Path(self.tmp.name) / "claude"
        ai_link._keys.clear()
        self.a = users.create_user("a@example.com", "Aaaa!pass12")
        self.b = users.create_user("b@example.com", "Bbbb!pass12")
        self.pa = projects.create_project(self.a.id, "Project of A")
        self.pb = projects.create_project(self.b.id, "Project of B")

    def tearDown(self):
        self.tmp.cleanup()

    def connect(self, user):
        self.assertTrue(ai_link.submit_key(user.id, "mistral", KEY))
        self.assertEqual(ai_link.take_keys(), [(user.id, "mistral", KEY)])
        self.assertTrue(ai_link.complete(user.id, "mistral", True))


class CatalogTest(Base):
    def test_both_providers_and_every_model_belongs_to_one(self):
        self.assertEqual(catalog.PROVIDERS, ("claude", "mistral"))
        mistral = catalog.provider("mistral")
        self.assertEqual(mistral.name, "Mistral")
        self.assertEqual(mistral.model("mistral-small-2603").efforts, ("none", "high"))
        self.assertEqual(mistral.model("mistral-large-4").efforts, ("low", "medium", "high"))
        self.assertEqual(catalog.provider_of("mistral-large-4"), "mistral")
        self.assertEqual(catalog.provider_of("sonnet"), "claude")
        self.assertEqual(catalog.provider_of("gone"), "claude")
        catalog.check("mistral-small-2603", "none")
        with self.assertRaises(ValueError):
            catalog.check("mistral-small-2603", "max")
        with self.assertRaises(ValueError):
            catalog.check("mistral-small-2603", None, "claude")       # not a model of this provider
        self.assertEqual(catalog.resolve("mistral-large-4", "max"), ("mistral-large-4", "high"))
        self.assertEqual(catalog.resolve("mistral-large-4", "none", "claude"), ("sonnet", "high"))

    def test_a_list_may_not_take_an_id_of_another_provider(self):
        data = copy.deepcopy(catalog.SEED["mistral"])
        data["models"].append({"id": "sonnet", "name": "Fake", "efforts": ["high"], "default_effort": "high"})
        with self.assertRaises(ValueError):
            catalog.store("mistral", data)
        self.assertEqual(catalog.provider_of("sonnet"), "claude")

    def test_only_the_manager_may_use_another_ai(self):
        agents.configure(self.a.id, "chef", model="mistral-large-4", effort="medium")
        role = agents.settings(self.a.id)["roles"]["chef"]
        self.assertEqual((role["model"], role["effort"]), ("mistral-large-4", "medium"))
        with self.assertRaises(ValueError):
            agents.configure(self.a.id, "programmer", model="mistral-large-4")   # the runs start Claude Code
        self.assertEqual(agents.settings(self.a.id)["roles"]["programmer"]["model"], "sonnet")


class ConnectionTest(Base):
    def test_whole_connection_as_the_user_does_it(self):
        self.assertEqual(ai_routes.status("mistral", user=self.a), {"ok": True, "status": "none"})
        self.assertEqual(ai_routes.connect("mistral", "short", user=self.a).status_code, 400)
        self.assertEqual(ai_routes.connect("mistral", KEY, user=self.a)["status"], "connecting")
        self.assertEqual(ai_routes.connect("mistral", KEY, user=self.a).status_code, 409)   # one check at a time
        self.assertEqual(ai_link.take_keys(), [(self.a.id, "mistral", KEY)])
        self.assertEqual(ai_link.take_keys(), [])                                         # handed over once
        ai_link.complete(self.a.id, "mistral", True)
        self.assertEqual(ai_routes.status("mistral", user=self.a)["status"], "connected")
        self.assertEqual(ai_link.connected_providers(self.a.id), ("mistral",))
        self.assertEqual(ai_routes.disconnect("mistral", user=self.a), {"ok": True})
        self.assertEqual(ai_routes.status("mistral", user=self.a)["status"], "none")
        self.assertEqual(ai_link.pending_wipes(), [(self.a.id, "mistral")])
        self.assertTrue(ai_link.wiped(self.a.id, "mistral"))
        self.assertEqual(ai_link.pending_wipes(), [])

    def test_the_key_is_never_stored_in_the_database(self):
        ai_link.submit_key(self.a.id, "mistral", KEY)
        with open(db.DB_PATH, "rb") as raw:
            self.assertNotIn(KEY.encode(), raw.read())

    def test_a_refused_key_and_a_refused_renewal(self):
        ai_link.submit_key(self.a.id, "mistral", KEY)
        ai_link.take_keys()
        ai_link.complete(self.a.id, "mistral", False)
        self.assertEqual(ai_link.status(self.a.id, "mistral"), "none")                    # no key before: nothing
        self.connect(self.a)
        ai_link.submit_key(self.a.id, "mistral", KEY[::-1])                               # a new key, refused
        ai_link.take_keys()
        ai_link.complete(self.a.id, "mistral", False)
        self.assertEqual(ai_link.status(self.a.id, "mistral"), "connected")              # the old one still works
        self.assertTrue(ai_link.mark_expired(self.a.id, "mistral"))                      # Mistral refused it later
        self.assertEqual(ai_link.status(self.a.id, "mistral"), "expired")

    def test_a_check_the_runner_never_answers_ends(self):
        ai_link.submit_key(self.a.id, "mistral", KEY, now=1000)
        self.assertEqual(ai_link.status(self.a.id, "mistral", now=1000 + ai_link.CHECK_SECONDS + 1), "none")
        self.assertEqual(ai_link.take_keys(now=1000 + ai_link.KEY_SECONDS + 1), [])     # an old key is forgotten

    def test_unknown_providers_are_404(self):
        self.assertEqual(ai_routes.status("chatgpt", user=self.a).status_code, 404)
        self.assertEqual(ai_routes.connect("claude", KEY, user=self.a).status_code, 404)

    def test_deleting_an_account_queues_its_keys(self):
        self.connect(self.b)
        owner = users.create_user("owner@example.com", "Own3r!pass", role="owner")
        users.delete_user(owner, self.b.id)
        self.assertEqual(ai_link.pending_wipes(), [(self.b.id, "mistral")])

    def test_every_route_needs_a_login(self):
        from app.deps import api_user
        for route in ai_routes.router.routes:
            self.assertTrue(any(d.call is api_user for d in route.dependant.dependencies), route.path)


class ChatTest(Base):
    def test_a_question_to_mistral_needs_mistral_and_carries_the_provider(self):
        agents.configure(self.a.id, "chef", model="mistral-small-2603")
        with self.assertRaisesRegex(ValueError, "mistral"):
            chat.send(self.a.id, self.pa.id, "Hello")
        self.connect(self.a)
        chat.send(self.a.id, self.pa.id, "Hello")                    # Claude is not connected: not needed
        job = chat.claim_next()
        self.assertEqual((job.provider, job.model, job.effort), ("mistral", "mistral-small-2603", "none"))
        self.assertIn("You have no tools here", job.prompt)          # the rules say what this AI can not do
        self.assertNotIn("web search, can read web pages", job.prompt)
        self.assertIn("<memory-folder>", job.prompt)                 # the same package as for Claude
        self.assertTrue(chat.finish(job.chat_id, True, "Hi <memory file=\"MEMORY.md\"># Status\nok</memory>"))
        message = chat.list_messages(self.a.id, self.pa.id)[-1]
        self.assertEqual((message.status, message.answer, message.memory_saved), ("done", "Hi", True))

    def test_claude_questions_stay_as_they_were(self):
        claude_link.begin(self.a.id)
        claude_link.complete(self.a.id, True)
        chat.send(self.a.id, self.pa.id, "Hello")
        job = chat.claim_next()
        self.assertEqual((job.provider, job.model), ("claude", "sonnet"))
        self.assertIn("web search", job.prompt)

    def test_a_question_waits_while_mistral_is_disconnected(self):
        agents.configure(self.a.id, "chef", model="mistral-small-2603")
        self.connect(self.a)
        chat.send(self.a.id, self.pa.id, "Hello")
        ai_link.disconnect(self.a.id, "mistral")
        self.assertIsNone(chat.claim_next())


class PageTest(Base):
    def test_the_menu_has_a_mistral_row_and_its_dialog(self):
        bar = ui.settings_bar(self.a)
        folded = bar[bar.index('id="ai-more"'):bar.index('id="chat-clear-open"')]
        self.assertIn("ChatGPT", folded)
        self.assertIn('id="key-row-mistral"', folded)
        self.assertIn('data-key-open="mistral" data-status="none"', folded)
        self.assertIn('id="key-dialog-mistral"', bar)
        self.assertIn('href="https://console.mistral.ai/api-keys"', bar)
        self.assertIn('type="password" name="key"', bar)
        self.connect(self.a)
        bar = ui.settings_bar(self.a)
        self.assertIn('data-key-open="mistral" data-status="connected"', bar)
        self.assertIn(i18n.t("de", "claude_disconnect"), bar[bar.index('id="key-row-mistral"'):])

    def test_the_picker_offers_mistral_only_when_connected(self):
        plain = ui.model_picker("de", "manager", "sonnet", "high")
        self.assertNotIn("mistral-small-2603", plain)
        both = ui.model_picker("de", "manager", "sonnet", "high", providers=("claude", "mistral"))
        self.assertIn('value="mistral-small-2603"', both)
        self.assertIn('data-ai="Mistral"', both)
        self.assertIn(i18n.t("de", "effort_none"), both)
        self.assertLess(both.index('value="fable"'), both.index('value="mistral-small-2603"'))   # Claude first
        chosen = ui.model_picker("de", "manager", "mistral-large-4", "low")           # chosen, not connected
        self.assertIn('value="mistral-large-4" label="Mistral Large" data-ai="Mistral" selected', chosen)

    def test_the_chat_names_the_ai_of_the_chosen_model(self):
        agents.configure(self.a.id, "chef", model="mistral-large-4")
        html = managerpage.render("de", agents.settings(self.a.id), ais=("claude", "mistral"))
        self.assertIn('data-ai="Mistral"', html)
        self.assertIn('data-waiting="{name} antwortet"', html)

    def test_every_new_text_in_both_languages(self):
        for key in ("key_title", "key_steps", "key_open", "key_label", "key_wait", "key_done", "key_failed",
                    "key_disconnect_text", "key_checking", "key_refused", "effort_none", "chat_err_mistral"):
            self.assertIn(key, i18n.STRINGS["de"])
            self.assertIn(key, i18n.STRINGS["en"])


class RunnerInterfaceTest(Base):
    def test_keys_go_to_the_runner_once_and_it_reports_back(self):
        ai_link.submit_key(self.a.id, "mistral", KEY)
        self.assertEqual(runner_routes.keys_claim(), {"ok": True, "keys": [
            {"user_id": self.a.id, "provider": "mistral", "key": KEY}]})
        self.assertEqual(runner_routes.keys_claim()["keys"], [])
        self.assertEqual(runner_routes.key_done(self.a.id, "mistral", "1"), {"ok": True})
        self.assertEqual(runner_routes.key_done(self.a.id, "mistral", "1").status_code, 409)
        self.assertEqual(runner_routes.key_expired(self.a.id, "mistral"), {"ok": True})
        self.assertEqual(ai_link.status(self.a.id, "mistral"), "expired")
        ai_link.disconnect(self.a.id, "mistral")
        self.assertEqual(runner_routes.key_wipes()["wipes"], [{"user_id": self.a.id, "provider": "mistral"}])
        self.assertEqual(runner_routes.key_wiped(self.a.id, "mistral"), {"ok": True})
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            runner_routes.key_done(self.a.id, "../claude", "1")

    def test_the_chat_job_carries_the_provider(self):
        import dataclasses
        agents.configure(self.a.id, "chef", model="mistral-small-2603")
        self.connect(self.a)
        chat.send(self.a.id, self.pa.id, "Hello")
        with mock.patch.dict(os.environ, {runner_routes.TOKEN_HASH_ENV: hashlib.sha256(b"t").hexdigest()}):
            job = runner_routes.chat_claim()["job"]
        self.assertEqual(job["provider"], "mistral")


if __name__ == "__main__":
    unittest.main()
