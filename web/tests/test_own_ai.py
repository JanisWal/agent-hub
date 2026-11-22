"""The further AIs (Janis, 20.11. and 21.11.2026): any API in the OpenAI chat format, with the hub's tools, up to eight per
user with a name each. Address and model are the user's; the server's network and plain http only at addresses the owner
listed (netaddresses.py), for one account or all; everything else as with the other AIs."""
import os
import tempfile
import unittest

from app import (agents, ai_link, aichoice, board, chat, db, models, netaddresses, projects, prompts, statusnote,
                 systempage, ui, users)
from app.routes import ai as ai_routes
from app.routes import system as system_routes
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

    def connect(self, user, endpoint="https://api.example.com/v1", model="llama-3.1-70b", key="", label="", slot=None):
        """Connect one more AI the way the dialog does (route "custom" takes the next free place); its place."""
        if slot is None:
            answer = ai_routes.connect("custom", key, endpoint, model, label, user=user)
            self.assertTrue(answer["ok"], answer)
            slot = answer["provider"]
        else:
            self.assertTrue(ai_link.submit_key(user.id, slot, key, endpoint=endpoint, model=model, label=label))
        self.claimed = ai_link.take_keys()
        self.assertTrue(ai_link.complete(user.id, slot, True))
        return slot

    def test_address_model_and_an_optional_key(self):
        self.assertEqual(self.connect(self.a), "custom-1")
        self.assertEqual(self.claimed, [{"user_id": self.a.id, "provider": "custom-1", "key": "-",
                                         "endpoint": "https://api.example.com/v1", "lan": False}])
        with db.connect() as conn:
            self.assertEqual(ai_link.route_in(conn, self.a.id, "custom", "own-1"),
                             {"slot": 1, "endpoint": "https://api.example.com/v1", "remote_model": "llama-3.1-70b",
                              "lan": False})
            self.assertEqual(ai_link.route_in(conn, self.b.id, "custom", "own-1"), {})   # nothing of A for B
            self.assertEqual(ai_link.route_in(conn, self.a.id, "mistral"), {})
        self.assertEqual(aichoice.connected(self.a.id), ["custom"])

    def test_several_with_names_each_its_own_model_and_place(self):
        self.assertEqual(self.connect(self.a, label="Büro  Llama"), "custom-1")
        self.assertEqual(self.connect(self.a, "https://two.example/v1", "qwen", label="Qwen"), "custom-2")
        self.assertEqual(self.connect(self.b), "custom-1")                            # B's places are his own
        with db.connect() as conn:
            rows = ai_link.custom_rows(conn, self.a.id)
            self.assertEqual([(r["name"], r["label"], r["model"]) for r in rows],
                             [("custom-1", "Büro Llama", "llama-3.1-70b"), ("custom-2", "Qwen", "qwen")])
            self.assertEqual(ai_link.route_in(conn, self.a.id, "custom", "own-2")["remote_model"], "qwen")
            self.assertEqual(ai_link.route_in(conn, self.a.id, "custom", "own-5")["slot"], 1)   # not there: the first
            self.assertEqual(models.allowed(conn, self.a.id, "custom"), {"own-1", "own-2"})
            self.assertFalse(models.permits(conn, self.b.id, "own-2"))
        self.assertTrue(ai_link.disconnect(self.a.id, "custom-1"))
        with db.connect() as conn:
            self.assertEqual(ai_link.free_slot(conn, self.a.id), "custom-3")          # custom-1: its key is not gone yet
        self.assertEqual(ai_link.pending_wipes(), [(self.a.id, "custom-1")])
        self.assertTrue(ai_link.wiped(self.a.id, "custom-1"))
        with db.connect() as conn:
            self.assertEqual(ai_link.free_slot(conn, self.a.id), "custom-1")

    def test_all_places_taken(self):
        for n in range(1, 9):
            self.connect(self.a, slot=f"custom-{n}")
        answer = ai_routes.connect("custom", "", "https://x.example/v1", "m", "", user=self.a)
        self.assertEqual((answer.status_code, answer.body), (400, b'{"ok":false,"field":"full"}'))
        self.assertNotIn('data-key-open="custom"', ui.settings_bar(self.a))           # no open tile any more
        self.assertEqual(ai_routes.connect("custom-9", "", "https://x.example/v1", "m", "", user=self.a).status_code, 404)

    def test_bad_values_are_refused_and_the_servers_network_only_where_listed(self):
        for endpoint, model, field in (("ftp://x/v1", "m", "endpoint"), ("https://a b/v1", "m", "endpoint"),
                                       ("https://x.example/v1", "-rf", "model"), ("https://x.example/v1", "a b", "model"),
                                       ("http://192.168.1.5:11434/v1", "llama3", "network"),
                                       ("https://192.168.1.5/v1", "llama3", "network"),            # https, but local
                                       ("https://ollama.local/v1", "llama3", "network"),
                                       ("http://ai.example.com/v1", "llama3", "network")):         # plain http
            with self.assertRaisesRegex(ValueError, field):
                ai_link.submit_key(self.a.id, "custom-1", "", endpoint=endpoint, model=model)
        with self.assertRaisesRegex(ValueError, "key"):
            ai_link.submit_key(self.a.id, "custom-1", "with space", endpoint="https://x.example/v1", model="m")
        with self.assertRaisesRegex(ValueError, "network"):                           # the owner too, while not listed
            ai_link.submit_key(self.owner.id, "custom-1", "", endpoint="http://192.168.1.5:11434/v1", model="llama3")
        answer = ai_routes.connect("custom", "", "http://192.168.1.5:11434/v1", "m", "", user=self.a)
        self.assertEqual((answer.status_code, answer.body), (400, b'{"ok":false,"field":"network"}'))
        answer = ai_routes.connect("custom", "", "ftp://x", "m", "", user=self.a)
        self.assertEqual((answer.status_code, answer.body), (400, b'{"ok":false,"field":"endpoint"}'))
        self.connect(self.a, "https://colleague.example.net/v1", "llama3")              # public: nothing to list
        self.assertFalse(self.claimed[0]["lan"])

    def test_the_owner_lists_addresses_for_one_account_or_all(self):
        superadmin = users.create_user("s@example.com", "Ssss!pass12", role="superadmin")
        for who in (self.a, superadmin):                                              # only the owner
            self.assertEqual(system_routes.address_add("192.168.1.5:11434", "", "", user=who).status_code, 403)
        for bad in ("192.168.1.5", "192.168.1.5:0", "127.0.0.1:11434", "172.17.0.1:8000", "localhost:80", "a b:1"):
            answer = system_routes.address_add(bad, "", "", user=self.owner)
            self.assertEqual((answer.status_code, answer.body), (400, b'{"ok":false,"field":"address"}'), bad)
        self.assertEqual(system_routes.address_add("10.0.0.9:80", "999", "", user=self.owner).status_code, 400)
        answer = system_routes.address_add("192.168.1.5:11434", str(self.a.id), "Ollama", user=self.owner)
        self.assertIn("192.168.1.5:11434", answer["list"])
        self.assertIn("a@example.com", answer["list"])
        self.connect(self.a, "http://192.168.1.5:11434/v1", "llama3.1:8b")              # listed for A
        self.assertEqual((self.claimed[0]["endpoint"], self.claimed[0]["lan"]), ("http://192.168.1.5:11434/v1", True))
        with db.connect() as conn:
            self.assertTrue(ai_link.route_in(conn, self.a.id, "custom", "own-1")["lan"])
        with self.assertRaisesRegex(ValueError, "network"):                           # not for B, not another port
            ai_link.submit_key(self.b.id, "custom-1", "", endpoint="http://192.168.1.5:11434/v1", model="m")
        with self.assertRaisesRegex(ValueError, "network"):
            ai_link.submit_key(self.a.id, "custom-2", "", endpoint="http://192.168.1.5:8080/v1", model="m")
        system_routes.address_add("ollama.local:11434", "", "", user=self.owner)          # for all accounts
        self.connect(self.b, "http://ollama.local:11434/v1", "m")
        self.assertTrue(self.claimed[0]["lan"])
        [entry] = [e for e in self._entries() if e["user_id"] == self.a.id]
        self.assertNotIn("a@example.com", system_routes.address_remove(entry["id"], user=self.owner)["list"])
        with db.connect() as conn:                                                     # from the next job on
            self.assertFalse(ai_link.route_in(conn, self.a.id, "custom", "own-1")["lan"])

    def _entries(self):
        with db.connect() as conn:
            return netaddresses.entries(conn)

    def test_an_entry_of_a_deleted_account_goes_with_it(self):
        system_routes.address_add("192.168.1.5:11434", str(self.a.id), "", user=self.owner)
        with db.connect() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (self.a.id,))                # what purge_deleted does
        self.assertEqual(self._entries(), [])

    def test_the_system_page_shows_the_list_only_to_the_owner(self):
        self.assertIn('id="addresses-dialog"', systempage.render(self.owner))
        self.assertIn("data-addresses", systempage.render(self.owner))
        superadmin = users.create_user("s@example.com", "Ssss!pass12", role="superadmin")
        self.assertNotIn("addresses-dialog", systempage.render(superadmin))

    def test_a_new_address_counts_only_once_it_was_checked(self):
        self.connect(self.a)
        ai_link.submit_key(self.a.id, "custom-1", "", endpoint="https://other.example/v1", model="m2")
        ai_link.take_keys()
        ai_link.complete(self.a.id, "custom-1", False)                                 # refused: the old one stays
        with db.connect() as conn:
            self.assertEqual(ai_link.route_in(conn, self.a.id, "custom", "own-1")["endpoint"],
                             "https://api.example.com/v1")
        self.assertEqual(ai_link.status(self.a.id, "custom-1"), "connected")

    def test_chat_and_runs_carry_the_route_and_the_package_names_the_hubs_tools(self):
        self.connect(self.a)
        chat.send(self.a.id, self.pa.id, "Hallo")
        job = chat.claim_next()
        self.assertEqual((job.provider, job.model), ("custom", "own-1"))
        self.assertEqual((job.route["remote_model"], job.route["slot"]), ("llama-3.1-70b", 1))
        self.assertNotIn("a web search", job.prompt)                                 # it has none
        self.assertIn("reading web pages", job.prompt)                               # the hub's fetch
        self.assertIn(prompts.FILES_OPEN, job.prompt)                                # it can open files
        chat.finish(job.chat_id, True, "Hi")
        board.create_item(self.a.id, self.pa.id, "minor", "Addieren")
        run = agents.claim_next(can_mac=False)
        self.assertEqual((run.provider, run.route["endpoint"]), ("custom", "https://api.example.com/v1"))
        claimed = runner_routes.claim("0")["job"]
        self.assertIsNone(claimed)                                                   # one at a time

    def test_the_drawer_shows_each_one_the_open_tile_and_the_later_ones(self):
        page = ui.settings_bar(self.a)
        self.assertIn('id="key-dialog-custom"', page)
        self.assertIn('name="endpoint"', page)
        self.assertIn('name="label"', page)
        self.assertIn('data-key-open="custom"', page)                                 # the open tile
        self.assertIn("Jede Standard-API", page)
        for name in ui.SOON:
            self.assertIn(name, page)
        self.assertIn("Kommt später", page)
        self.connect(self.a, label="Büro")
        page = ui.settings_bar(self.a)
        self.assertIn('data-key-open="custom-1"', page)
        self.assertIn('data-label="Büro"', page)
        self.assertIn('data-key-open="custom"', page)                                 # still there for one more
        self.assertIn("Werkzeuge: vom Hub, ohne Websuche", page)
        self.assertIn("Werkzeuge: eigene", page)                                      # Claude
        self.assertIn("Werkzeuge: eigene, Bilder und PDFs vom Hub", page)            # Mistral
        soon = page[page.index("Kommt später") - 300:page.index("Kommt später")]
        self.assertNotIn("data-tip", soon)                                            # no "i" at a placeholder
        users.set_profile(self.a.id, "", "en")
        page = ui.settings_bar(users.get_by_id(self.a.id))
        self.assertIn("Other AI", page)
        self.assertIn("Tools: from the hub, no web search", page)

    def test_the_model_picker_shows_the_names(self):
        self.connect(self.a, label="Büro")
        self.connect(self.a, "https://two.example/v1", "qwen", label="Qwen")
        settings = agents.settings(self.a.id)
        self.assertEqual(settings["model_names"], {"own-1": "Büro", "own-2": "Qwen"})
        picker = ui.model_picker("de", "x", "own-2", "none", providers=("custom",), allowed=settings["models"],
                                 names=settings["model_names"])
        self.assertIn(">Büro<", picker)
        self.assertIn(">Qwen<", picker)
        self.assertNotIn("own-3", picker)

if __name__ == "__main__":
    unittest.main()
