"""The settings a small server needs and a big one does not (Janis, 21.11.2026): chosen by owner or superadmin, given
to every job, checked again by the runner; the test browser named only when it is on."""
import asyncio
import os
import tempfile
import unittest

from app import agents, board, chat, claude_link, db, projects, prompts, serversettings, statusnote, systempage, users
from app.routes import system as routes


class FakeRequest:
    def __init__(self, form):
        self._form = form

    async def form(self):
        return self._form


def post(form, user):
    return asyncio.run(routes.limits(FakeRequest(form), user=user))


class LimitsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        statusnote._LAST_SCAN["at"] = 2 ** 40
        self.owner = users.create_user("o@example.com", "Oooo!pass12", role="owner")
        self.a = users.create_user("a@example.com", "Aaaa!pass12")
        self.pa = projects.create_project(self.owner.id, "Rechner")
        claude_link.begin(self.owner.id)
        claude_link.complete(self.owner.id, True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_defaults_are_what_the_pi_used(self):
        self.assertEqual(serversettings.run_limits(),
                         {"memory_mb": 480, "cpus": 2, "pids": 512, "run_seconds": 1100, "chat_seconds": 200,
                          "test_seconds": 300, "view_mb": 200, "browser": 1})
        self.assertEqual(serversettings.task_seconds(), 2 * 3600)

    def test_only_choices_and_only_system_admins(self):
        self.assertEqual(post({"run_memory_mb": "2048"}, self.a).status_code, 403)
        for bad in ({"run_memory_mb": "999"}, {"run_memory_mb": "lots"}, {"upload_parallel": "4"}, {}):
            self.assertEqual(post(bad, self.owner).status_code, 400, bad)
        self.assertEqual(post({"run_memory_mb": "2048", "run_cpus": "4"}, self.owner), {"ok": True})
        self.assertEqual(post({"run_minutes": "60"}, self.owner), {"ok": True})
        limits = serversettings.run_limits()
        self.assertEqual((limits["memory_mb"], limits["cpus"], limits["run_seconds"]), (2048, 4, 3500))
        self.assertEqual(serversettings.task_seconds(), 6 * 3600)                    # the task grows with the run

    def test_every_job_carries_them(self):
        serversettings.set_choice("run_memory_mb", 1024, serversettings.CHOICES["run_memory_mb"])
        chat.send(self.owner.id, self.pa.id, "Hallo")
        job = chat.claim_next()
        self.assertEqual(job.limits["memory_mb"], 1024)
        chat.finish(job.chat_id, True, "Hi")                                      # one AI run at a time
        item = board.create_item(self.owner.id, self.pa.id, "minor", "Addieren")
        agents.start_item(self.owner.id, item.id)
        self.assertEqual(agents.claim_next(can_mac=False).limits["memory_mb"], 1024)

    def test_the_browser_is_named_only_when_it_is_on(self):
        item = board.create_item(self.owner.id, self.pa.id, "minor", "Addieren")
        agents.start_item(self.owner.id, item.id)
        job = agents.claim_next(can_mac=False)
        self.assertIn("hub-browser", job.prompt)                                    # programmer, browser on
        serversettings.set_choice("agent_browser", 0, serversettings.CHOICES["agent_browser"])
        with db.connect() as conn:
            self.assertNotIn("hub-browser", prompts.run(conn, job))

    def test_the_system_page_shows_the_rows(self):
        html = systempage.render(self.owner)
        for text in ("Je KI-Lauf", "Arbeitsspeicher", "Zeitlimits", "Testbrowser", "Leeres Kontingent", "8 GB"):
            self.assertIn(text, html)
        self.assertEqual(html.count('data-url="/system/limits"'), len(systempage.LIMIT_ROWS))


if __name__ == "__main__":
    unittest.main()
