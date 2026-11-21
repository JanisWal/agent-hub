"""ChatGPT through Codex, the model lists per user and the measured tools (Janis, 21.11.2026)."""
import os
import tempfile
import unittest

from app import agents, ai_link, aichoice, catalog, chat, claude_link, db, models, projects, prompts, statusnote, toolcheck
from app import ui, users
from app.routes import ai as ai_routes
from app.routes import runner as runner_routes


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        ai_link._keys.clear()
        statusnote._LAST_SCAN["at"] = 2 ** 40
        self.a = users.create_user("a@example.com", "Aaaa!pass12")
        self.b = users.create_user("b@example.com", "Bbbb!pass12")
        self.pa = projects.create_project(self.a.id, "Rechner")

    def tearDown(self):
        self.tmp.cleanup()

    def chatgpt(self, user):
        self.assertTrue(ai_link.begin_login(user.id, "chatgpt"))
        self.assertTrue(ai_link.set_device_prompt(user.id, "chatgpt", "https://auth.openai.com/codex/device", "AB12-CDE34"))
        self.assertTrue(ai_link.complete(user.id, "chatgpt", True))


class SignInTest(Base):
    def test_the_sign_in_with_a_one_time_code(self):
        answer = ai_routes.connect("chatgpt", "", endpoint="", model="", label="", user=self.a)
        self.assertEqual(answer["status"], "connecting")
        self.assertEqual(ai_routes.connect("chatgpt", "", endpoint="", model="", label="", user=self.a).status_code, 409)
        self.assertEqual(runner_routes.device_logins()["logins"], [{"user_id": self.a.id, "provider": "chatgpt"}])
        self.assertEqual(ai_routes.status("chatgpt", user=self.a)["url"], "")
        self.assertEqual(runner_routes.device_login_url(self.a.id, "chatgpt", "https://evil.example/x", "AB12-CDE34").status_code, 400)
        self.assertEqual(runner_routes.device_login_url(self.a.id, "chatgpt", "https://auth.openai.com/codex/device", "x").status_code, 400)
        self.assertEqual(runner_routes.device_login_url(self.a.id, "chatgpt", "https://auth.openai.com/codex/device", "AB12-CDE34"), {"ok": True})
        shown = ai_routes.status("chatgpt", user=self.a)
        self.assertEqual((shown["url"], shown["code"]), ("https://auth.openai.com/codex/device", "AB12-CDE34"))
        self.assertEqual(ai_routes.status("chatgpt", user=self.b)["code"], "")       # only his own
        self.assertEqual(runner_routes.key_done(self.a.id, "chatgpt", "1"), {"ok": True})
        self.assertEqual(ai_link.status(self.a.id, "chatgpt"), "connected")
        self.assertEqual(ai_routes.status("chatgpt", user=self.a)["code"], "")       # the code is gone afterwards
        self.assertEqual(aichoice.connected(self.a.id), ["chatgpt"])

    def test_a_plan_without_codex_is_said_and_the_next_ai_answers(self):
        self.chatgpt(self.a)
        claude_link.begin(self.a.id)
        claude_link.complete(self.a.id, True)
        self.assertTrue(ai_link.mark_noplan(self.a.id, "chatgpt"))
        self.assertEqual(aichoice.connected(self.a.id), ["claude"])
        self.assertIn("Abo ohne Codex", ui.settings_bar(self.a))
        self.assertEqual(chat.failure_kind("The AI's program stopped (plan): unexpected status 403"), "plan")

    def test_the_drawer_has_the_dialog_and_no_placeholder(self):
        page = ui.settings_bar(self.a)
        self.assertIn('id="key-dialog-chatgpt"', page)
        self.assertIn("data-device-code", page)
        self.assertNotIn("Kommt später", page)
        self.assertIn("Werkzeuge: eigene", page)


class RoleStartTest(Base):
    def test_the_manager_starts_light_and_the_programmer_strong(self):
        self.chatgpt(self.a)
        roles = agents.settings(self.a.id)["roles"]
        self.assertEqual((roles["chef"]["model"], roles["chef"]["effort"]), ("gpt-6-luna", "low"))
        self.assertEqual(roles["programmer"]["model"], "gpt-6.1-sol")
        chat.send(self.a.id, self.pa.id, "Hallo")
        job = chat.claim_next()
        self.assertEqual((job.provider, job.model, job.effort), ("chatgpt", "gpt-6-luna", "low"))
        self.assertIn("a web search", job.prompt)                              # Codex brings its own


class ModelListTest(Base):
    CHATGPT = [{"slug": "gpt-7-nova", "display_name": "GPT-7 Nova", "supported_reasoning_levels":
                [{"effort": "low"}, {"effort": "high"}, {"effort": "ultra"}], "default_reasoning_level": "low",
                "input_modalities": ["text", "image"]},
               {"slug": "gpt-6-luna", "display_name": "GPT-6 Luna", "supported_reasoning_levels": [{"effort": "low"}],
                "default_reasoning_level": "low", "input_modalities": ["text"]},
               {"slug": "codex-auto-review", "supported_reasoning_levels": [{"effort": "low"}]}]

    def test_a_new_model_appears_for_its_user_only(self):
        self.chatgpt(self.a)
        self.chatgpt(self.b)
        self.assertEqual(sorted(i["user_id"] for i in models.due()), [self.a.id, self.b.id])
        self.assertTrue(models.save(self.a.id, "chatgpt", self.CHATGPT))
        provider = catalog.provider("chatgpt")
        self.assertEqual([m.id for m in provider.models], ["gpt-7-nova", "gpt-6-luna"])
        nova = provider.model("gpt-7-nova")
        self.assertEqual((nova.efforts, nova.images), (("low", "high"), True))  # no "ultra"
        self.assertNotIn(self.a.id, [i["user_id"] for i in models.due()])        # asked today
        with db.connect() as conn:
            self.assertEqual(models.allowed(conn, self.a.id, "chatgpt"), {"gpt-7-nova", "gpt-6-luna"})
            self.assertIsNone(models.allowed(conn, self.b.id, "chatgpt"))       # B's list is not known yet
        picker = ui.model_picker("de", "x", "gpt-6-luna", "low", providers=("chatgpt",),
                                 allowed={"chatgpt": {"gpt-6-luna"}})
        self.assertNotIn("gpt-7-nova", picker)
        roles = agents.settings(self.a.id)["roles"]
        self.assertEqual(roles["programmer"]["model"], "gpt-6-luna")            # 6.1 Sol left his list: the default
        agents.configure(self.a.id, "programmer", model="gpt-7-nova")
        self.assertEqual(agents.settings(self.a.id)["roles"]["programmer"]["model"], "gpt-7-nova")

    def test_claude_and_mistral_lists(self):
        claude = models.normalize("claude", [{"id": "claude-opus-5-5"}, {"id": "claude-nova-6"}, {"id": "x"}])
        self.assertEqual([m["id"] for m in claude], ["opus", "nova"])           # the families, newest version each
        mistral = models.normalize("mistral", [
            {"id": "mistral-large-5", "capabilities": {"completion_chat": True, "function_calling": True, "vision": True}},
            {"id": "mistral-small-2603", "capabilities": {"completion_chat": True, "function_calling": True}},
            {"id": "mistral-embed", "capabilities": {"completion_chat": False}},
            {"id": "old", "capabilities": {"completion_chat": True, "function_calling": True}, "deprecation": "2026-01-01"}])
        self.assertEqual([m["id"] for m in mistral], ["mistral-large-5", "mistral-small-2603"])
        self.assertEqual(mistral[1]["efforts"], ["none", "high"])               # a known model keeps its levels
        self.assertFalse(models.save(self.a.id, "mistral", None))               # could not be asked: nothing changes
        self.assertEqual(catalog.provider("mistral").default_model, "mistral-small-2603")

    def test_a_model_outside_his_list_can_not_be_asked(self):
        self.chatgpt(self.a)
        models.save(self.a.id, "chatgpt", self.CHATGPT[:1])
        with self.assertRaisesRegex(ValueError, "mode"):
            chat.send(self.a.id, self.pa.id, "Hallo", model="gpt-6-luna")


class ToolCheckTest(Base):
    def test_only_clear_evidence_switches_and_it_switches_back(self):
        asked = ["WebSearch", "WebFetch", "Bash", "Read"]
        for _ in range(toolcheck.STREAK - 1):
            toolcheck.record("claude", asked, ["WebSearch", "Bash", "Read"])
        self.assertEqual(toolcheck.effective("claude")["fetch"], "own")         # not yet
        toolcheck.record("claude", asked, None)                                 # unreadable: no evidence at all
        self.assertEqual(toolcheck.effective("claude")["fetch"], "own")
        toolcheck.record("claude", asked, ["WebSearch", "Bash", "Read"])
        self.assertEqual(toolcheck.effective("claude")["fetch"], "hub")
        self.assertEqual(toolcheck.hub_tools("claude"), ["fetch"])
        self.assertIn("in 3 answer(s) in a row", toolcheck.history("claude")[0]["note"])
        toolcheck.record("claude", ["WebSearch", "Bash"], ["WebSearch", "Bash"])  # not asked: changes nothing
        self.assertEqual(toolcheck.effective("claude")["fetch"], "hub")
        toolcheck.record("claude", asked, asked)                                # named again: its own again
        self.assertEqual(toolcheck.effective("claude")["fetch"], "own")
        self.assertEqual(toolcheck.hub_tools("claude"), [])
        for _ in range(5):
            toolcheck.record("chatgpt", ["x"], [])                              # a program that names no tools
        self.assertEqual(toolcheck.effective("chatgpt"), catalog.tools_of("chatgpt"))

    def test_the_chat_job_carries_the_hubs_tools_and_the_package_says_so(self):
        claude_link.begin(self.a.id)
        claude_link.complete(self.a.id, True)
        for _ in range(toolcheck.STREAK):
            toolcheck.record("claude", ["WebSearch"], ["Bash"])
        self.assertEqual(toolcheck.effective("claude")["search"], "none")        # the hub has no web search
        chat.send(self.a.id, self.pa.id, "Hallo")
        job = chat.claim_next()
        self.assertEqual(job.hub_tools, [])
        self.assertNotIn("a web search", job.prompt)
        self.assertTrue(chat.finish(job.chat_id, True, "Hi", tools=(["WebSearch"], ["WebSearch"])))
        self.assertEqual(toolcheck.effective("claude")["search"], "own")


if __name__ == "__main__":
    unittest.main()
