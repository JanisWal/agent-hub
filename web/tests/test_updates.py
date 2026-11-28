"""Updates from the administration (28.11.2026): which version runs, whether a newer one is there, who may start the
update and what the runner gets."""
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from app import db, hostjobs, systempage, updates, users
from app.routes import update as routes

NEW = "b" * 40
OLD = "a" * 40


def github(sha=NEW, day="2026-11-29T10:00:00Z", calls=None):
    def ask(url, timeout):
        if calls is not None:
            calls.append(url)
        return {"sha": sha, "commit": {"committer": {"date": day}}}
    return ask


class UpdatesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.owner = users.create_user("owner@example.com", "Own3r!pass", role="owner")
        self.sup = users.get_by_id(users.create_user("super@example.com", "Sup3r!pass", role="superadmin").id)
        self.version = Path(self.tmp.name) / "VERSION"
        self.version.write_text(f"{OLD} 2026-11-28\n")
        for patcher in (mock.patch.dict(os.environ, {"HUB_SOURCE": "https://github.com/JanisWal/agent-hub.git",
                                                      "HUB_BRANCH": "main"}),
                        mock.patch.object(updates, "VERSION_FILE", self.version),
                        mock.patch.object(updates, "_ask", github())):
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def request(self):
        return types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="203.0.113.7"))

    def test_the_running_version_comes_from_the_version_file(self):
        self.assertEqual(updates.installed(), {"commit": OLD, "date": "2026-11-28"})
        self.version.write_text("not a commit\n")
        self.assertIsNone(updates.installed())
        self.version.unlink()
        self.assertIsNone(updates.installed())

    def test_the_source_is_asked_once_a_day_unless_the_owner_asks(self):
        calls = []
        ask = github(calls=calls)
        found = updates.latest(now=1000, ask=ask)
        self.assertEqual((found["commit"], found["date"]), (NEW, "2026-11-29"))
        self.assertEqual(calls, ["https://api.github.com/repos/JanisWal/agent-hub/commits/main"])
        updates.latest(now=1000 + 3600, ask=ask)
        self.assertEqual(len(calls), 1)                                     # within a day: what is known
        updates.latest(force=True, now=1000 + 3600, ask=ask)
        self.assertEqual(len(calls), 2)
        updates.latest(now=1000 + 3600 + updates.CHECK_SECONDS, ask=ask)
        self.assertEqual(len(calls), 3)

    def test_a_failed_question_keeps_what_was_known(self):
        updates.latest(now=1000, ask=github())
        def broken(url, timeout):
            raise OSError("offline")
        self.assertEqual(updates.latest(force=True, now=2000, ask=broken)["commit"], NEW)
        self.assertEqual(updates.latest(force=True, now=3000, ask=github(sha="no sha"))["commit"], NEW)
        with db.connect() as conn:
            conn.execute("DELETE FROM server_settings WHERE key = 'update.latest'")
        self.assertIsNone(updates.latest(force=True, ask=broken))

    def test_newer_means_another_commit(self):
        self.assertTrue(updates.available({"commit": NEW}, {"commit": OLD}))
        self.assertFalse(updates.available({"commit": OLD}, {"commit": OLD}))
        self.assertFalse(updates.available(None, {"commit": OLD}))
        self.assertTrue(updates.available({"commit": NEW}, None))

    def test_only_a_hub_with_a_source_on_github(self):
        for source in ("", "https://gitlab.com/x/y.git", "http://github.com/x/y", "https://github.com/x/y/../z"):
            with mock.patch.dict(os.environ, {"HUB_SOURCE": source}):
                self.assertFalse(updates.allowed(), source)
                self.assertIsNone(updates.latest(force=True))
                self.assertEqual(routes.state(self.owner).status_code, 403)
                self.assertNotIn("sys-update", systempage.render(self.owner))
        self.assertTrue(updates.allowed())

    def test_the_row_says_what_is_there(self):
        seen = routes.state(self.owner)
        self.assertTrue(seen["available"])
        self.assertEqual(seen["text"], "28.11.2026 (aaaaaaa) · neue Version vom 29.11.2026")
        self.version.write_text(f"{NEW} 2026-11-29\n")
        seen = routes.check(self.owner)
        self.assertEqual((seen["available"], seen["text"]), (False, "29.11.2026 (bbbbbbb) · aktuell"))
        self.assertIn('id="sys-update"', systempage.render(self.owner))
        self.assertIn('id="update-dialog"', systempage.render(self.owner))

    def test_only_the_owner_with_the_password_starts_it(self):
        self.assertEqual(routes.state(self.sup).status_code, 403)
        self.assertNotIn("sys-update", systempage.render(self.sup))
        self.assertEqual(routes.start(self.request(), "Sup3r!pass", self.sup).status_code, 403)
        self.assertEqual(routes.start(self.request(), "wrong", self.owner).status_code, 403)
        self.assertIsNone(hostjobs.claim_next())
        self.assertEqual(routes.start(self.request(), "Own3r!pass", self.owner), {"ok": True})
        self.assertEqual(routes.start(self.request(), "Own3r!pass", self.owner).status_code, 409)   # one at a time
        claimed = hostjobs.claim_next()
        self.assertEqual((claimed["action"], claimed["payload"]), ("update", {}))   # nothing from the page goes along
        seen = routes.state(self.owner)
        self.assertEqual((seen["running"], seen["available"]), (True, False))

    def test_a_failed_update_shows_why_and_its_log(self):
        job = hostjobs.request("update", {}, self.owner.id)
        hostjobs.claim_next()
        hostjobs.results_dir().mkdir(parents=True, exist_ok=True)
        (hostjobs.results_dir() / f"{job}.json").write_text(json.dumps(
            {"ok": False, "reason": "rolled_back", "log": ["== Images bauen", "error: no space left"]}))
        seen = routes.state(self.owner)
        self.assertEqual(seen["failed"], "Die neue Version startete nicht. Die bisherige läuft wieder.")
        self.assertEqual(seen["log"], "== Images bauen\nerror: no space left")
        self.assertFalse(seen["running"])


if __name__ == "__main__":
    unittest.main()
