"""Settings of the whole server (upload): choices, who may change them, and that the upload follows them."""
import os
import tempfile
import unittest
from pathlib import Path

from app import db, files, managerpage, projects, serversettings, systempage, users
from app.routes import system


class ServerSettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.original = (files.FILES_DIR, files.free_bytes)
        files.FILES_DIR = Path(self.tmp.name) / "files"
        files.free_bytes = lambda: 10 * 1024 ** 4
        self.owner = users.create_user("owner@example.com", "Own3r!pass", role="owner")
        self.admin = users.create_user("admin@example.com", "Adm1n!pass", role="admin")
        self.user = users.add_user(self.owner, "user@example.com", "Start1234")

    def tearDown(self):
        files.FILES_DIR, files.free_bytes = self.original
        self.tmp.cleanup()

    def test_defaults_until_the_owner_chooses(self):
        self.assertEqual(serversettings.upload(), (6, 32))
        self.assertEqual(files.max_request(), 32 * 1024 ** 2)

    def test_only_the_choices_are_kept(self):
        serversettings.set_upload(4, 90)
        self.assertEqual(serversettings.upload(), (4, 90))
        for parallel, size in ((0, 32), (5, 32), (6, 100), (6, -1), (99, 9999)):
            with self.assertRaises(ValueError):
                serversettings.set_upload(parallel, size)
        self.assertEqual(serversettings.upload(), (4, 90))

    def test_only_the_owner_may_change_them(self):
        for who in (self.admin, self.user):
            self.assertEqual(system.upload_settings(2, 16, who).status_code, 403)
        self.assertEqual(serversettings.upload(), (6, 32))
        self.assertEqual(system.upload_settings(7, 16, self.owner).status_code, 400)
        self.assertEqual(system.upload_settings(2, 16, self.owner), {"ok": True})
        self.assertEqual(serversettings.upload(), (2, 16))

    def test_the_server_refuses_a_request_over_the_chosen_size(self):
        serversettings.set_upload(6, 16)
        project = projects.create_project(self.owner.id, "P")
        item = files.start_upload(self.owner.id, project.id, "big.bin", 40 * 1024 ** 2)
        with self.assertRaises(files.FileError) as caught:
            files.Run(self.owner.id, item.id, 0, 16 * 1024 ** 2 + files.BLOCK_SIZE)
        self.assertEqual(caught.exception.code, "too_big")
        files.Run(self.owner.id, item.id, 0, 16 * 1024 ** 2).close()      # exactly the limit is fine

    def test_the_page_and_the_file_tile_show_the_choice(self):
        serversettings.set_upload(8, 64)
        html = systempage.render(self.owner)
        self.assertIn('<option value="8" selected>', html)
        self.assertIn('<option value="64" selected>', html)
        # one "i" per row that needs it (Janis, 14.11.2026): backup, upload, AI runs, restart, shut down (skins: none)
        self.assertEqual(html.count('class="info-dot"'), 5)
        self.assertNotIn("sys-hint", html)
        self.assertIn("Gleichzeitig: So viele Stücke", html)               # the upload "i" explains both choices
        self.assertEqual(html.count("Backup erstellen<"), 1)               # the button, no title repeating it
        self.assertNotIn(" title=", html)                                  # explanations only as our own tips
        tile = managerpage._files_tile("de", [])
        self.assertIn('data-parallel="8"', tile)
        self.assertIn(f'data-max-request="{64 * 1024 ** 2}"', tile)


if __name__ == "__main__":
    unittest.main()
