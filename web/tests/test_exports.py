"""The project's code as a ZIP for the user (Janis, 21.11.2026): only his own projects, the runner makes it, it goes after
an hour and with its project."""
import io
import os
import tempfile
import unittest
import zipfile

from app import agents, board, claude_link, db, exports, projects, rolepage, serversettings, statusnote, users
from app.routes import exports as routes
from app.routes import runner as runner_routes


def a_zip(name="calc.js", body=b"x"):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(name, body)
    return out.getvalue()


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        statusnote._LAST_SCAN["at"] = 2 ** 40
        self.a = users.create_user("a@example.com", "Aaaa!pass12")
        self.b = users.create_user("b@example.com", "Bbbb!pass12")
        self.pa = projects.create_project(self.a.id, "Rechner")

    def tearDown(self):
        self.tmp.cleanup()

    def test_main_from_asking_to_download(self):
        answer = routes.export_request(self.pa.id, task="", user=self.a)
        export_id = answer["id"]
        self.assertEqual(routes.export_request(self.pa.id, task="", user=self.a)["id"], export_id)   # reused
        self.assertEqual(exports.pending(), [{"id": export_id, "project_id": self.pa.id, "ref": "main"}])
        self.assertEqual(routes.export_state(self.pa.id, export_id, user=self.a)["state"], "waiting")
        self.assertTrue(exports.deliver(export_id, a_zip()))
        self.assertEqual(routes.export_state(self.pa.id, export_id, user=self.a)["state"], "ready")
        response = routes.export_download(self.pa.id, export_id, user=self.a)
        self.assertEqual(response.media_type, "application/zip")
        self.assertEqual(exports.pending(), [])

    def test_only_the_users_own_project_and_task(self):
        self.assertEqual(routes.export_request(self.pa.id, task="", user=self.b).status_code, 404)
        export_id = routes.export_request(self.pa.id, task="", user=self.a)["id"]
        exports.deliver(export_id, a_zip())
        self.assertEqual(routes.export_state(self.pa.id, export_id, user=self.b).status_code, 404)
        self.assertEqual(routes.export_download(self.pa.id, export_id, user=self.b).status_code, 404)
        self.assertEqual(routes.export_request(self.pa.id, task="999", user=self.a).status_code, 404)

    def test_a_tasks_branch(self):
        claude_link.begin(self.a.id)
        claude_link.complete(self.a.id, True)
        board.create_item(self.a.id, self.pa.id, "minor", "Addieren")
        agents.claim_next(can_mac=False)                                    # the programmer takes it
        task = agents.list_tasks(self.a.id, self.pa.id)[0]
        export_id = routes.export_request(self.pa.id, task=str(task.id), user=self.a)["id"]
        self.assertEqual(exports.pending()[0]["ref"], f"agent/task-{task.id}")
        html = rolepage._code_tile("de", (task, ""))
        self.assertIn(f'data-export="{task.id}"', html)
        self.assertIn("Hauptstand herunterladen", html)
        self.assertGreater(export_id, 0)

    def test_no_zip_too_big_or_empty_counts_as_failed(self):
        serversettings.set_choice("export_mb", 10, serversettings.EXPORT_MB)
        export_id = exports.request(self.a.id, self.pa.id)
        self.assertFalse(exports.deliver(export_id, b"not a zip"))
        self.assertEqual(exports.state(self.a.id, self.pa.id, export_id), "failed")
        export_id = exports.request(self.a.id, self.pa.id)
        self.assertFalse(exports.deliver(export_id, b"PK" + b"0" * (11 * 1024 * 1024)))
        export_id = exports.request(self.a.id, self.pa.id)
        exports.fail(export_id)                                                     # the runner could not
        self.assertEqual(exports.state(self.a.id, self.pa.id, export_id), "failed")

    def test_it_goes_after_an_hour_and_with_its_project(self):
        export_id = exports.request(self.a.id, self.pa.id, now=1000)
        exports.deliver(export_id, a_zip())
        self.assertTrue((exports.folder() / f"{export_id}.zip").is_file())
        exports.sweep(now=1000 + exports.KEEP_SECONDS + 1)
        self.assertFalse((exports.folder() / f"{export_id}.zip").exists())
        export_id = exports.request(self.a.id, self.pa.id)
        exports.deliver(export_id, a_zip())
        projects.delete_project(self.a.id, self.pa.id)
        exports.sweep()
        self.assertFalse((exports.folder() / f"{export_id}.zip").exists())

    def test_runner_routes(self):
        export_id = exports.request(self.a.id, self.pa.id)
        answer = runner_routes.export_requests()
        self.assertEqual(answer["exports"][0]["id"], export_id)
        self.assertEqual(answer["limit"], exports.limit())


if __name__ == "__main__":
    unittest.main()
