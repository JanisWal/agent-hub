"""The read-only /files and /code of a job (view.py)."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from runner import view, workspace


class ViewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.source = Path(self.tmp.name) / "storage"
        (self.source / "4").mkdir(parents=True)
        (self.source / "9").mkdir(parents=True)
        (self.source / "4" / "11").write_bytes(b"%PDF manual")
        (self.source / "4" / "12").write_bytes(b"\x89PNG picture")
        (self.source / "4" / "13").write_bytes(b"other manual")
        (self.source / "9" / "50").write_bytes(b"SECRET OF ANOTHER PROJECT")
        self.views = view.Views(Path(self.tmp.name) / "work", self.source)

    def tearDown(self):
        for folder in Path(self.tmp.name).rglob("*"):   # the view is read-only: make it deletable again
            if folder.is_dir():
                os.chmod(folder, 0o755)
        self.tmp.cleanup()

    def files(self):
        return [{"id": 11, "name": "Anleitung Relais.pdf", "area": "documents", "size": 11},
                {"id": 12, "name": "../../schaltplan.png", "area": "media", "size": 12},
                {"id": 13, "name": "Anleitung Relais.pdf", "area": "documents", "size": 12},
                {"id": 50, "name": "planted.md", "area": "evil", "size": 25}]

    def test_files_come_with_their_names_by_area_read_only_and_only_from_the_jobs_project(self):
        root = self.views.build("run-3", 4, self.files(), [{"name": "Guide", "url": "https://example.com/g"},
                                                           {"name": "Bad", "url": "javascript:alert(1)"}])
        files = root / "files"
        self.assertEqual((files / "documents" / "Anleitung Relais.pdf").read_bytes(), b"%PDF manual")
        self.assertEqual((files / "documents" / "Anleitung Relais (2).pdf").read_bytes(), b"other manual")
        self.assertEqual((files / "media" / "schaltplan.png").read_bytes(), b"\x89PNG picture")   # no way out
        self.assertFalse((files / "documents" / "planted.md").exists())     # id 50 is not in project 4
        self.assertIn("planted.md (1 KB, not available)", (files / "INDEX.md").read_text())
        links = (files / "LINKS.md").read_text()
        self.assertIn("- Guide: https://example.com/g", links)
        self.assertNotIn("javascript", links)
        self.assertEqual(oct((files / "media" / "schaltplan.png").stat().st_mode & 0o777), "0o444")
        self.assertFalse((root / "code").exists())                          # only the chat gets the code

    def test_big_files_are_named_but_not_copied(self):
        big = [{"id": 11, "name": "film.mp4", "area": "media", "size": view.MAX_FILE + 1}]
        root = self.views.build("chat-1", 4, big, [])
        self.assertFalse((root / "files" / "media").exists())
        self.assertIn("film.mp4", (root / "files" / "INDEX.md").read_text())
        self.assertIn("too big", (root / "files" / "INDEX.md").read_text())

    def test_a_photo_brings_the_jpeg_the_browser_made_so_every_ai_can_look_at_it(self):
        (self.source / "4" / "14").write_bytes(b"II*\x00 raw photo")
        (self.source / "4" / "14.preview").write_bytes(b"\xff\xd8\xff jpeg of it")
        (self.source / "4" / "14.thumb").write_bytes(b"\xff\xd8\xff small")
        big = {"id": 14, "name": "Roadster.dng", "area": "media", "size": view.MAX_FILE + 1}
        root = self.views.build("run-5", 4, [big], [])
        media = root / "files" / "media"
        self.assertEqual((media / "Roadster.dng.jpg").read_bytes(), b"\xff\xd8\xff jpeg of it")
        self.assertFalse((media / "Roadster.dng").exists())          # the original is too big, the JPEG still comes
        self.assertIn("to look at: media/Roadster.dng.jpg", (root / "files" / "INDEX.md").read_text())
        self.assertEqual(sorted(p.name for p in media.iterdir()), ["Roadster.dng.jpg"])   # never the small thumb

    def test_the_code_is_main_without_git_and_the_view_goes_away(self):
        work = workspace.Workspace(Path(self.tmp.name) / "work")
        repo = work.ensure_repo(4)
        tree = Path(self.tmp.name) / "tree"
        (tree / "src").mkdir(parents=True)
        (tree / "src" / "relay.py").write_text("ON = True\n")
        git = ["git", "-c", "safe.directory=*", "-c", "user.name=t", "-c", "user.email=t@t", f"--git-dir={repo}",
               f"--work-tree={tree}"]
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-q", "-m", "code"], check=True)
        root = self.views.build("chat-2", 4, [], [], repo)
        self.assertEqual((root / "code" / "src" / "relay.py").read_text(), "ON = True\n")
        self.assertFalse((root / "code" / ".git").exists())
        self.views.remove("chat-2")
        self.assertFalse(root.exists())
        self.views.build("run-4", 4, [], [])
        self.views.clear()
        self.assertFalse(self.views.base.exists())

    def test_names_never_leave_their_folder(self):
        self.assertEqual(view.safe_name("../../etc/passwd"), "passwd")
        self.assertEqual(view.safe_name("a\\..\\b.txt"), "b.txt")
        self.assertEqual(view.safe_name(".."), "file")
        self.assertEqual(view.safe_name(".hidden"), "hidden")
        self.assertEqual(view.safe_name("a\x00b\nc"), "a_b_c")
        with self.assertRaises(ValueError):
            self.views.path("../x")


if __name__ == "__main__":
    unittest.main()
