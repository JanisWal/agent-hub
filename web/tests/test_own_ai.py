"""The user's own AI (Janis, 20.11.2026): any API in the OpenAI chat format, with the hub's tools. Address and model are
the user's, plain http and the home network only for the owner; everything else as with the other AIs."""
import os
import tempfile
import unittest

from app import agents, ai_link, aichoice, board, chat, db, projects, prompts, statusnote, ui, users
from app.routes import ai as ai_routes
from app.routes import runner as runner_routes


class OwnAiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        ai_link._keys.clear()
        statusnote._LAST_SCAN["at"] = 2 ** 40
        self.owner = users.create_user("o@example.com", "Oooo!pass12", role="owner")
        self.a = users.create_user("a@example.com", "Aaaa!pass12")
        self.b = users.create_user("b@example.com", "Bbbb!pass12")
        self.pa = projects.create_project(self.a.id, "Rechner")

    def tearDown(self):
        self.tmp.cleanup()
        ai_link._keys.clear()

    def connect(self, user, endpoint="https://api.example.com/v1", model="llama-3.1-70b", key=""):
        self.assertTrue(ai_link.submit_key(user.id, "custom", key, endpoint=endpoint, model=model))
        claimed = ai_link.take_keys()
        self.assertTrue(ai_link.complete(user.id, "custom", True))
        return claimed

    def test_address_model_and_an_optional_key(self):
        [item] = self.connect(self.a)
        self.assertEqual(item, {"user_id": self.a.id, "provider": "custom", "key": "-",
                                "endpoint": "https://api.example.com/v1", "lan": False})
        with db.connect() as conn:
            self.assertEqual(ai_link.route_in(conn, self.a.id, "custom"),
                             {"endpoint": "https://api.example.com/v1", "remote_model": "llama-3.1-70b", "lan": False})
            self.assertEqual(ai_link.route_in(conn, self.b.id, "custom"), {})        # nothing of A for B
            self.assertEqual(ai_link.route_in(conn, self.a.id, "mistral"), {})
        self.assertEqual(aichoice.connected(self.a.id), ["custom"])

    def test_bad_values_are_refused_and_plain_http_only_for_the_owner(self):
        for endpoint, model, field in (("ftp://x/v1", "m", "endpoint"), ("https://a b/v1", "m", "endpoint"),
                                       ("https://x.example/v1", "-rf", "model"), ("https://x.example/v1", "a b", "model"),
                                       ("http://192.168.1.5:11434/v1", "llama3", "endpoint")):
            with self.assertRaisesRegex(ValueError, field):
                ai_link.submit_key(self.a.id, "custom", "", endpoint=endpoint, model=model)
        with self.assertRaisesRegex(ValueError, "key"):
            ai_link.submit_key(self.a.id, "custom", "with space", endpoint="https://x.example/v1", model="m")
        [item] = self.connect(self.owner, "http://192.168.1.5:11434/v1", "llama3.1:8b")
        self.assertEqual((item["endpoint"], item["lan"]), ("http://192.168.1.5:11434/v1", True))
        answer = ai_routes.connect("custom", "", "ftp://x", "m", user=self.a)
        self.assertEqual((answer.status_code, answer.body), (400, b'{"ok":false,"field":"endpoint"}'))

    def test_a_new_address_counts_only_once_it_was_checked(self):
        self.connect(self.a)
        ai_link.submit_key(self.a.id, "custom", "", endpoint="https://other.example/v1", model="m2")
        ai_link.take_keys()
        ai_link.complete(self.a.id, "custom", False)                                 # refused: the old one stays
        with db.connect() as conn:
            self.assertEqual(ai_link.route_in(conn, self.a.id, "custom")["endpoint"], "https://api.example.com/v1")
        self.assertEqual(ai_link.status(self.a.id, "custom"), "connected")

    def test_chat_and_runs_carry_the_route_and_the_package_names_the_hubs_tools(self):
        self.connect(self.a)
        chat.send(self.a.id, self.pa.id, "Hallo")
        job = chat.claim_next()
        self.assertEqual((job.provider, job.model), ("custom", "own"))
        self.assertEqual(job.route["remote_model"], "llama-3.1-70b")
        self.assertNotIn("a web search", job.prompt)                                 # it has none
        self.assertIn("reading web pages", job.prompt)                               # the hub's fetch
        self.assertIn(prompts.FILES_OPEN, job.prompt)                                # it can open files
        chat.finish(job.chat_id, True, "Hi")
        item = board.create_item(self.a.id, self.pa.id, "minor", "Addieren")
        agents.start_item(self.a.id, item.id)
        run = agents.claim_next(can_mac=False)
        self.assertEqual((run.provider, run.route["endpoint"]), ("custom", "https://api.example.com/v1"))
        claimed = runner_routes.claim("0")["job"]
        self.assertIsNone(claimed)                                                   # one at a time

    def test_the_drawer_shows_it_with_its_dialog_and_where_the_tools_come_from(self):
        page = ui.settings_bar(self.a)
        self.assertIn('id="key-dialog-custom"', page)
        self.assertIn('name="endpoint"', page)
        self.assertIn("Eigene KI", page)
        self.assertIn("Werkzeuge: vom Hub, ohne Websuche", page)
        self.assertIn("Werkzeuge: eigene", page)                                      # Claude
        self.assertIn("Werkzeuge: eigene, Bilder und PDFs vom Hub", page)            # Mistral
        users.set_profile(self.a.id, "", "en")
        page = ui.settings_bar(users.get_by_id(self.a.id))
        self.assertIn("Own AI", page)
        self.assertIn("Tools: from the hub, no web search", page)


if __name__ == "__main__":
    unittest.main()
