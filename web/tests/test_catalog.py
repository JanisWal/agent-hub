"""The list of AI models and effort levels (catalog.py), the settings that use it and the model picker."""
import copy
import os
import tempfile
import unittest
from pathlib import Path

from app import agents, catalog, chat, claude_link, db, i18n, projects, ui, users
from app.routes import manager as manager_routes


def seed() -> dict:
    return copy.deepcopy(catalog.SEED["claude"])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.a = users.create_user("a@example.com", "Aaaa!pass12")
        self.b = users.create_user("b@example.com", "Bbbb!pass12")
        self.pa = projects.create_project(self.a.id, "Project of A")

    def tearDown(self):
        self.tmp.cleanup()


class CatalogTest(Base):
    def test_the_starting_list_until_one_is_stored(self):
        claude = catalog.provider()
        self.assertEqual([m.id for m in claude.models], ["haiku", "sonnet", "opus", "fable"])
        self.assertEqual(claude.default_model, "sonnet")
        self.assertEqual(claude.model("haiku").efforts, ("low", "medium", "high", "xhigh", "max"))
        self.assertIsNone(claude.model("gpt"))

    def test_a_stored_list_replaces_it_and_a_new_model_needs_no_code(self):
        data = seed()
        data["models"].append({"id": "nova", "name": "Nova", "hint": "deepest", "efforts": ["low", "high"],
                               "default_effort": "high"})
        catalog.store("claude", data)
        self.assertEqual(catalog.provider().model("nova").efforts, ("low", "high"))
        catalog.check("nova", "high")
        with self.assertRaises(ValueError):
            catalog.check("nova", "max")                               # a level this model does not have

    def test_a_bad_list_is_refused_whole_and_nothing_changes(self):
        bad_lists = []
        for change in (
            lambda d: d["models"][0].update(id="-rf"),                 # would look like a flag on the command line
            lambda d: d["models"][0].update(id="Sonnet Big"),
            lambda d: d["models"][0].update(efforts=["low", "very high"]),
            lambda d: d["models"][0].update(efforts=[]),
            lambda d: d["models"][0].update(default_effort="max2"),
            lambda d: d.update(default_model="nothing"),
            lambda d: d.update(models=[]),
            lambda d: d.update(models=d["models"] * 4),                # too many and twice the same id
            lambda d: d["models"][0].update(name="<script>"),
            lambda d: d.update(name=""),
        ):
            data = seed()
            change(data)
            bad_lists.append(data)
        for data in bad_lists:
            with self.assertRaises(ValueError, msg=str(data)[:120]):
                catalog.store("claude", data)
        self.assertEqual([m.id for m in catalog.provider().models], ["haiku", "sonnet", "opus", "fable"])
        with self.assertRaises(ValueError):
            catalog.store("gpt", seed())                               # unknown provider

    def test_which_models_see_pictures_and_what_the_ai_is_told_and_sent(self):
        for model in ("haiku", "sonnet", "opus", "fable", "mistral-small-2603", "mistral-large-4"):
            self.assertTrue(catalog.sees_images(model), model)
        self.assertFalse(catalog.sees_images("unknown-model"))
        self.assertFalse(catalog.sees_images(None))
        data = seed()
        data["models"].append({"id": "nova", "name": "Nova", "efforts": ["low"], "default_effort": "low"})
        catalog.store("claude", data)
        self.assertFalse(catalog.sees_images("nova"))                  # nobody said it can: no picture is sent
        bad = seed()
        bad["models"][0]["images"] = "yes"
        with self.assertRaises(ValueError):
            catalog.store("claude", bad)
        claude_link.begin(self.a.id)
        claude_link.complete(self.a.id, True)
        chat.send(self.a.id, self.pa.id, "What does the picture show?")
        job = chat.claim_next()
        self.assertTrue(job.images)
        self.assertNotIn(catalog.BLIND_NOTE, job.prompt)
        self.assertIn("Look at images and PDFs yourself", job.prompt)
        chat.finish(job.chat_id, True, "red")
        agents.configure(self.a.id, "chef", model="nova", effort="low")
        chat.send(self.a.id, self.pa.id, "And this one?")
        job = chat.claim_next()
        self.assertEqual(job.model, "nova")
        self.assertFalse(job.images)
        self.assertIn(catalog.BLIND_NOTE, job.prompt)

    def test_an_unknown_hint_is_dropped_but_the_model_stays(self):
        data = seed()
        data["models"][0]["hint"] = "magic"
        self.assertIsNone(catalog.store("claude", data).model("haiku").hint)

    def test_a_broken_stored_list_falls_back_to_the_starting_list(self):
        with db.connect() as conn:
            conn.execute("INSERT INTO server_settings (key, value) VALUES ('ai_catalog.claude', '{broken')")
        self.assertEqual(catalog.provider().default_model, "sonnet")

    def test_resolve_makes_an_old_choice_valid_again(self):
        self.assertEqual(catalog.resolve("opus", "max"), ("opus", "max"))
        self.assertEqual(catalog.resolve("gone", "max"), ("sonnet", "max"))      # model left the list
        self.assertEqual(catalog.resolve("haiku", "turbo"), ("haiku", "medium"))  # unknown level: the default
        self.assertEqual(catalog.resolve(None, None), ("sonnet", "high"))


class SettingsTest(Base):
    def test_model_and_effort_per_role_with_defaults(self):
        roles = agents.settings(self.a.id)["roles"]
        self.assertEqual((roles["chef"]["model"], roles["chef"]["effort"]), ("sonnet", "high"))
        agents.configure(self.a.id, "chef", model="haiku")
        self.assertEqual(agents.settings(self.a.id)["roles"]["chef"]["effort"], "medium")   # haiku's default
        agents.configure(self.a.id, "chef", effort="max")
        agents.configure(self.a.id, "reviewer", model="opus", effort="low")
        roles = agents.settings(self.a.id)["roles"]
        self.assertEqual((roles["chef"]["model"], roles["chef"]["effort"]), ("haiku", "max"))
        self.assertEqual((roles["reviewer"]["model"], roles["reviewer"]["effort"]), ("opus", "low"))
        other = agents.settings(self.b.id)["roles"]["chef"]                   # B is untouched
        self.assertEqual((other["model"], other["effort"]), ("sonnet", "high"))

    def test_unknown_values_are_refused(self):
        for bad in ({"model": "gpt-4"}, {"model": "sonnet --x"}, {"effort": "turbo"},
                    {"model": "haiku", "effort": "ultra"}):
            with self.assertRaises(ValueError, msg=str(bad)):
                agents.configure(self.a.id, "chef", **bad)
        self.assertEqual(agents.settings(self.a.id)["roles"]["chef"]["model"], "sonnet")

    def test_a_level_the_new_model_lacks_becomes_its_default(self):
        data = seed()
        data["models"].append({"id": "nova", "name": "Nova", "efforts": ["low", "high"], "default_effort": "low"})
        catalog.store("claude", data)
        agents.configure(self.a.id, "chef", effort="max")
        answer = manager_routes.manager_settings("nova", "", "", "", user=self.a)
        self.assertEqual((answer["model"], answer["effort"]), ("nova", "low"))
        answer = manager_routes.manager_settings("sonnet", "", "", "", user=self.a)
        self.assertEqual(answer["effort"], "max")                             # the saved level counts again

    def test_the_route_saves_the_level(self):
        answer = manager_routes.manager_settings("", "", "", "xhigh", user=self.a)
        self.assertEqual((answer["ok"], answer["effort"]), (True, "xhigh"))
        self.assertEqual(manager_routes.manager_settings("", "", "", "turbo", user=self.a).status_code, 400)

    def test_runs_and_questions_carry_the_level(self):
        claude_link.begin(self.a.id)
        claude_link.complete(self.a.id, True)
        agents.configure(self.a.id, "chef", model="opus", effort="xhigh")
        chat.send(self.a.id, self.pa.id, "q")
        job = chat.claim_next()
        self.assertEqual((job.model, job.effort), ("opus", "xhigh"))          # from the database, not the runner
        with self.assertRaises(ValueError) as problem:
            chat.send(self.a.id, self.pa.id, "x", model="haiku", effort="ultra")
        self.assertEqual(str(problem.exception), "mode")


class PickerTest(Base):
    def picker(self, lang="de", model="haiku", effort="max"):
        return ui.model_picker(lang, "manager", model, effort, label_model="chat_model", label_effort="chat_effort")

    def test_two_drop_downs_in_our_own_style(self):
        html = self.picker()
        self.assertEqual(html.count('class="m-select has-select"'), 2)
        self.assertIn('id="manager-model" data-setting="model"', html)
        self.assertIn('id="manager-effort" data-setting="effort"', html)
        self.assertIn('<option value="haiku" label="Haiku" data-ai="Claude" selected>Haiku · schnell</option>', html)
        self.assertIn('<option value="max" selected>Maximal</option>', html)
        self.assertIn('aria-label="Stufe des Managers"', html)
        self.assertNotIn("title=", html)                                      # its tip would cover the list
        self.assertIn("Sonnet · balanced", self.picker("en"))

    def test_levels_the_model_lacks_are_hidden_and_unknown_texts_show_plainly(self):
        data = seed()
        data["models"].append({"id": "nova", "name": "Nova", "hint": None, "efforts": ["low", "turbo"],
                               "default_effort": "turbo"})
        catalog.store("claude", data)
        html = self.picker(model="nova", effort="turbo")
        self.assertIn('<option value="nova" label="Nova" data-ai="Claude" selected>Nova</option>', html)    # no hint: only the name
        self.assertIn('<option value="turbo" selected>turbo</option>', html)  # unknown level: its name as it is
        self.assertIn('<option value="max" hidden>Maximal</option>', html)    # nova has no "max"
        self.assertIn("data-levels=", html)
        self.assertIn("&quot;nova&quot;:[&quot;low&quot;,&quot;turbo&quot;]", html)

    def test_a_saved_choice_that_left_the_list_shows_the_default(self):
        html = self.picker(model="gone", effort="nothing")
        self.assertIn('<option value="sonnet" label="Sonnet" data-ai="Claude" selected>', html)
        self.assertIn('<option value="high" selected>', html)

    def test_texts_in_both_languages(self):
        for key in ("picker_model", "picker_effort", "chat_effort", *(f"model_hint_{h}" for h in catalog.HINTS),
                    *(f"effort_{e}" for e in ("low", "medium", "high", "xhigh", "max"))):
            self.assertIn(key, i18n.STRINGS["de"])
            self.assertIn(key, i18n.STRINGS["en"])
        for gone in ("model_haiku", "model_sonnet", "model_opus"):
            self.assertNotIn(gone, i18n.STRINGS["de"])


if __name__ == "__main__":
    unittest.main()
