"""Files and links of a project: data rules, upload in chunks, protection, serving and the tile."""
import os
import tempfile
import types
import unittest
from pathlib import Path

from app import db, files, i18n, managerpage, projects, users
from app.routes import files as file_routes


class FilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.original = (files.FILES_DIR, files.free_bytes, files.CHUNK_SIZE)
        files.FILES_DIR = Path(self.tmp.name) / "files"
        files.CHUNK_SIZE = 4                       # small chunks, so a few bytes make several
        self.free = 10 * 1024 ** 3
        files.free_bytes = lambda: self.free
        self.user = users.create_user("a@example.com", "Aaaa!pass12")
        self.project = projects.create_project(self.user.id, "Project")

    def tearDown(self):
        files.FILES_DIR, files.free_bytes, files.CHUNK_SIZE = self.original
        self.tmp.cleanup()

    def upload(self, name="notes.md", data=b"hello", user=None, project=None):
        user, project = user or self.user, project or self.project
        item = files.start_upload(user.id, project.id, name, len(data))
        for offset in range(0, len(data), files.CHUNK_SIZE):
            files.append_chunk(user.id, item.id, offset, data[offset:offset + files.CHUNK_SIZE])
        return files.finish_upload(user.id, item.id)

    # --- sorting by ending
    def test_new_files_are_sorted_by_their_ending(self):
        wanted = {"a.md": "memory", "a.py": "code", "a.swift": "code", "a.PNG": "media", "a.mp4": "media",
                  "a.m4a": "media", "a.pdf": "documents", "a.zip": "documents", "noending": "documents"}
        for name, category in wanted.items():
            self.assertEqual(files.category_for(name), category, name)

    # --- upload in chunks
    def test_a_file_comes_in_chunks_and_is_stored_under_its_id(self):
        item = self.upload("notes.md", b"hello world")
        self.assertEqual((item.name, item.category, item.size, item.status), ("notes.md", "memory", 11, "ready"))
        path, _ = files.open_file(self.user.id, item.id)
        self.assertEqual(path.read_bytes(), b"hello world")
        self.assertEqual(path, files.FILES_DIR / str(self.project.id) / str(item.id))   # the name is not in the path
        self.assertEqual([f.id for f in files.list_files(self.user.id, self.project.id)], [item.id])

    def test_an_unfinished_upload_is_not_listed_and_cannot_be_opened(self):
        item = files.start_upload(self.user.id, self.project.id, "a.bin", 3)
        files.append_chunk(self.user.id, item.id, 0, b"abc")
        self.assertEqual(files.list_files(self.user.id, self.project.id), [])
        self.assertIsNone(files.open_file(self.user.id, item.id))

    def test_chunks_may_come_in_any_order_and_be_sent_again(self):
        data = b"0123456789ab"                        # 12 bytes = 3 chunks of 4
        uid = self.user.id
        item = files.start_upload(uid, self.project.id, "a.bin", 12)
        self.assertEqual(files.append_chunk(uid, item.id, 8, data[8:]), 1)
        self.assertEqual(files.append_chunk(uid, item.id, 0, data[:4]), 2)
        self.assertEqual(files.append_chunk(uid, item.id, 0, data[:4]), 2)      # sent again: nothing changes
        with self.assertRaises(files.FileError) as caught:
            files.finish_upload(uid, item.id)                                    # the middle chunk is missing
        self.assertEqual(caught.exception.code, "incomplete")
        files.append_chunk(uid, item.id, 4, data[4:8])
        done = files.finish_upload(uid, item.id)
        self.assertEqual(done.size, 12)
        self.assertEqual(files.open_file(uid, done.id)[0].read_bytes(), data)

    def test_wrong_offsets_and_lengths_are_refused(self):
        item = files.start_upload(self.user.id, self.project.id, "a.bin", 10)    # chunks of 4, 4 and 2
        for offset, data in ((1, b"abcd"), (4, b"ab"), (8, b"abcd"), (12, b"ab"), (-4, b"abcd"), (0, b"abc")):
            with self.assertRaises(files.FileError, msg=(offset, data)) as caught:
                files.append_chunk(self.user.id, item.id, offset, data)
            self.assertEqual(caught.exception.code, "bad_offset")

    def test_chunks_sent_at_the_same_time_are_all_counted(self):
        import threading
        data = bytes(range(64))                                                 # 16 chunks of 4
        item = files.start_upload(self.user.id, self.project.id, "a.bin", 64)
        problems = []

        def send(offset):
            try:
                files.append_chunk(self.user.id, item.id, offset, data[offset:offset + 4])
            except Exception as problem:                                        # noqa: BLE001
                problems.append(problem)

        threads = [threading.Thread(target=send, args=(offset,)) for offset in range(0, 64, 4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(problems, [])
        done = files.finish_upload(self.user.id, item.id)
        self.assertEqual(files.open_file(self.user.id, done.id)[0].read_bytes(), data)
    def test_an_empty_file_is_fine(self):
        self.assertEqual(self.upload("empty.txt", b"").size, 0)

    def test_any_type_and_any_size_is_accepted(self):
        for name in ("a.exe", "a.sh", "a.html", "a.svg", "noending"):
            self.assertEqual(self.upload(name, b"x").status, "ready", name)

    def test_a_chunk_over_the_limit_is_refused(self):
        item = files.start_upload(self.user.id, self.project.id, "big.bin", 1)
        with self.assertRaises(files.FileError) as caught:
            files.append_chunk(self.user.id, item.id, 0, b"x" * (files.CHUNK_SIZE + 1))
        self.assertEqual(caught.exception.code, "too_big")

    # --- the only protection: free space
    def test_nothing_is_stored_when_the_disk_would_be_nearly_full(self):
        self.free = files.MIN_FREE + 5
        with self.assertRaises(files.FileError) as caught:
            files.start_upload(self.user.id, self.project.id, "big.bin", 10)
        self.assertEqual(caught.exception.code, "disk_full")
        item = files.start_upload(self.user.id, self.project.id, "ok.bin", 4)
        self.free = files.MIN_FREE + 1          # it filled up in the meantime
        with self.assertRaises(files.FileError) as caught:
            files.append_chunk(self.user.id, item.id, 0, b"abcd")
        self.assertEqual(caught.exception.code, "disk_full")
        self.assertEqual(files.path_of(self.project.id, item.id).read_bytes(), b"\0\0\0\0")      # nothing was written

    def test_old_unfinished_uploads_are_thrown_away(self):
        old = files.start_upload(self.user.id, self.project.id, "old.bin", 1, now=1000)
        files.append_chunk(self.user.id, old.id, 0, b"x")
        recent = files.start_upload(self.user.id, self.project.id, "recent.bin", 1, now=1500)   # keeps the next id apart
        files.start_upload(self.user.id, self.project.id, "new.bin", 1, now=1000 + files.STALE + 1)
        self.assertFalse(files.path_of(self.project.id, old.id).exists())
        self.assertTrue(files.path_of(self.project.id, recent.id).exists())
        with self.assertRaises(files.FileError):
            files.append_chunk(self.user.id, old.id, 0, b"y")

    # --- names
    def test_names_are_cleaned_and_cannot_reach_a_path(self):
        item = self.upload("../../etc/pass:wd.md", b"x")
        self.assertNotIn("/", item.name)
        self.assertNotIn("..", item.name.replace("pass", ""))
        for bad in ("", "   ", "...", "///"):
            with self.assertRaises(files.FileError):
                files.start_upload(self.user.id, self.project.id, bad, 1)
        self.assertEqual(len(self.upload("x" * 300 + ".md", b"x").name), files.MAX_NAME)

    # --- rename, move, delete
    def test_rename_and_move_by_hand(self):
        item = self.upload("a.pdf", b"x")
        changed = files.update(self.user.id, item.id, "manual.pdf", category="memory")
        self.assertEqual((changed.name, changed.category), ("manual.pdf", "memory"))
        for bad in ("links", "nonsense"):
            with self.assertRaises(files.FileError):
                files.update(self.user.id, item.id, "manual.pdf", category=bad)

    def test_delete_removes_the_file_for_good(self):
        item = self.upload("a.txt", b"x")
        path = files.path_of(self.project.id, item.id)
        self.assertTrue(files.delete(self.user.id, item.id))
        self.assertFalse(path.exists())
        self.assertEqual(files.list_files(self.user.id, self.project.id), [])
        self.assertFalse(files.delete(self.user.id, item.id))

    def test_deleting_a_project_removes_its_files_from_the_disk(self):
        item = self.upload("a.txt", b"x")
        other = projects.create_project(self.user.id, "Other")
        keep = self.upload("keep.txt", b"y", project=other)
        projects.delete_project(self.user.id, self.project.id)
        self.assertFalse(files.path_of(self.project.id, item.id).exists())
        self.assertTrue(files.path_of(other.id, keep.id).exists())

    def test_deleting_an_account_removes_its_files_from_the_disk(self):
        owner = users.create_user("o@example.com", "Oooo!pass12", role="owner")
        item = self.upload("a.txt", b"x")
        users.delete_user(owner, self.user.id)
        self.assertFalse(files.path_of(self.project.id, item.id).exists())

    # --- links
    def test_links_need_an_http_address_and_default_to_the_host_as_name(self):
        link = files.add_link(self.user.id, self.project.id, " https://docs.example.com/guide?x=1 ")
        self.assertEqual((link.name, link.url, link.category, link.kind), ("docs.example.com", "https://docs.example.com/guide?x=1", "links", "link"))
        for bad in ("", "javascript:alert(1)", "ftp://x.org/a", "https://", "not a url", "https://a b.org"):
            with self.assertRaises(files.FileError, msg=bad):
                files.add_link(self.user.id, self.project.id, bad)
        self.assertIsNone(files.open_file(self.user.id, link.id))        # a link has no file
        changed = files.update(self.user.id, link.id, "Guide", url="http://example.org/new", category="media")
        self.assertEqual((changed.name, changed.url, changed.category), ("Guide", "http://example.org/new", "links"))

    # --- text editor
    def test_markdown_and_text_can_be_read_and_changed_others_cannot(self):
        note = self.upload("note.md", b"# Hi")
        self.assertEqual(files.read_text(self.user.id, note.id), "# Hi")
        self.assertTrue(files.write_text(self.user.id, note.id, "# Changed"))
        self.assertEqual(files.read_text(self.user.id, note.id), "# Changed")
        self.assertEqual(files.list_files(self.user.id, self.project.id)[0].size, len("# Changed"))
        image = self.upload("a.png", b"x")
        self.assertIsNone(files.read_text(self.user.id, image.id))
        self.assertFalse(files.write_text(self.user.id, image.id, "x"))
        with self.assertRaises(files.FileError):
            files.write_text(self.user.id, note.id, "x" * (files.TEXT_MAX + 1))

    # --- serving: fixed type, nothing runs
    def serve(self, item):
        return file_routes.serve(item.id, self.user)

    def test_only_images_video_and_audio_are_shown_everything_else_is_a_download(self):
        for name, shown in (("a.png", True), ("a.svg", True), ("a.mp4", True), ("a.mp3", True), ("a.html", False),
                            ("a.pdf", False), ("a.js", False), ("a.exe", False), ("a.md", False)):
            response = self.serve(self.upload(name, b"<script>alert(1)</script>"))
            self.assertEqual(response.headers["content-disposition"].startswith("inline"), shown, name)
            if not shown:
                self.assertEqual(response.media_type, "application/octet-stream", name)
            self.assertIn("sandbox", response.headers["content-security-policy"])

    # --- the tile
    def test_the_tile_shows_previews_only_where_there_is_something_to_see(self):
        self.upload("pic.png", b"x")
        self.upload("clip.mp4", b"x")
        self.upload("memo.m4a", b"x")
        self.upload("doc.pdf", b"x")
        files.add_link(self.user.id, self.project.id, "https://example.org", "Example")
        stored = files.list_files(self.user.id, self.project.id)
        for lang in ("de", "en"):
            html = managerpage.render(lang, {"roles": {"chef": {"model": "sonnet", "net": "together"}}, "autonomy": "major"},
                                      stored_files=stored)
            self.assertEqual(html.count("<img "), 1)
            self.assertEqual(html.count("<video "), 1)
            self.assertEqual(html.count('class="file-row"'), 5)
            self.assertNotIn("%t.", html)
            self.assertIn("pic.png", html)
            self.assertIn('rel="noopener noreferrer"', html)

    def test_the_names_in_the_tile_are_escaped(self):
        item = self.upload("a<script>.md", b"x")
        html = managerpage.render("en", {"roles": {"chef": {"model": "sonnet", "net": "together"}}, "autonomy": "major"},
                                  stored_files=[item])
        self.assertNotIn("<script>", html)

    def test_every_error_has_a_text_in_both_languages(self):
        for _, key in file_routes.ERRORS.values():
            for lang in ("de", "en"):
                self.assertNotEqual(i18n.t(lang, key), key)


if __name__ == "__main__":
    unittest.main()
