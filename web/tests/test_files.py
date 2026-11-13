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
        self.original = (files.FILES_DIR, files.free_bytes, files.BLOCK_SIZE, files.MAX_REQUEST)
        files.FILES_DIR = Path(self.tmp.name) / "files"
        files.BLOCK_SIZE = 4                       # small blocks, so a few bytes make several
        files.MAX_REQUEST = 16
        self.free = 10 * 1024 ** 3
        files.free_bytes = lambda: self.free
        self.user = users.create_user("a@example.com", "Aaaa!pass12")
        self.project = projects.create_project(self.user.id, "Project")

    def tearDown(self):
        files.FILES_DIR, files.free_bytes, files.BLOCK_SIZE, files.MAX_REQUEST = self.original
        self.tmp.cleanup()

    def upload(self, name="notes.md", data=b"hello", user=None, project=None):
        user, project = user or self.user, project or self.project
        item = files.start_upload(user.id, project.id, name, len(data))
        for offset in range(0, len(data), files.BLOCK_SIZE):
            files.append_chunk(user.id, item.id, offset, data[offset:offset + files.BLOCK_SIZE])
        return files.finish_upload(user.id, item.id)

    # --- the folder is tied to the database: a test can never reach the real files
    def test_the_folder_of_the_files_follows_the_database(self):
        from unittest import mock
        files.FILES_DIR = None
        with mock.patch.dict(os.environ):
            os.environ.pop("HUB_FILES_DIR", None)
            self.assertEqual(files.files_dir(), Path(db.DB_PATH).parent / "files")
            os.environ["HUB_FILES_DIR"] = "/somewhere/else"
            self.assertEqual(files.files_dir(), Path("/somewhere/else"))

    def test_removing_orphans_only_touches_folders_named_like_a_dead_project(self):
        item = self.upload("a.txt", b"x")
        (files.files_dir() / "99").mkdir()                       # a project that does not exist
        (files.files_dir() / "keep-me").mkdir()                  # not a project folder at all
        files.remove_orphans()
        self.assertFalse((files.files_dir() / "99").exists())
        self.assertTrue((files.files_dir() / "keep-me").exists())
        self.assertTrue(files.path_of(self.project.id, item.id).exists())

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
        item = files.start_upload(self.user.id, self.project.id, "a.bin", 10)    # blocks of 4, 4 and 2
        for offset, data in ((1, b"abcd"), (4, b"ab"), (8, b"abcd"), (12, b"ab"), (-4, b"abcd"), (0, b"abc"), (0, b"")):
            with self.assertRaises(files.FileError, msg=(offset, data)) as caught:
                files.append_chunk(self.user.id, item.id, offset, data)
            self.assertEqual(caught.exception.code, "bad_offset")

    def test_a_request_may_carry_any_run_of_blocks_and_runs_may_overlap(self):
        data = bytes(range(10))
        uid = self.user.id
        item = files.start_upload(uid, self.project.id, "a.bin", 10)             # blocks of 4, 4 and 2
        self.assertEqual(files.append_chunk(uid, item.id, 4, data[4:10]), 2)      # two blocks at once, the tail among them
        self.assertEqual(files.append_chunk(uid, item.id, 0, data[0:8]), 3)       # overlaps what is in, cut differently
        self.assertEqual(files.append_chunk(uid, item.id, 0, data[0:4]), 3)       # sent again
        done = files.finish_upload(uid, item.id)
        self.assertEqual(files.open_file(uid, done.id)[0].read_bytes(), data)
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
            files.append_chunk(self.user.id, item.id, 0, b"x" * (files.MAX_REQUEST + 1))
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
        return file_routes.serve(item.id, 0, self.user)

    def test_only_images_video_and_audio_are_shown_everything_else_is_a_download(self):
        for name, shown in (("a.png", True), ("a.svg", True), ("a.mp4", True), ("a.mp3", True), ("a.html", False),
                            ("a.pdf", False), ("a.js", False), ("a.exe", False), ("a.md", False)):
            response = self.serve(self.upload(name, b"<script>alert(1)</script>"))
            self.assertEqual(response.headers["content-disposition"].startswith("inline"), shown, name)
            if not shown:
                self.assertEqual(response.media_type, "application/octet-stream", name)
            self.assertIn("sandbox", response.headers["content-security-policy"])

    # --- the tile
    def tile(self, lang="en"):
        stored = files.list_files(self.user.id, self.project.id)
        return managerpage.render(lang, {"roles": {"chef": {"model": "sonnet", "net": "together"}}, "autonomy": "major"},
                                  stored_files=stored)

    def test_the_tile_shows_previews_only_where_there_is_something_to_see(self):
        pic, clip = self.upload("pic.png", b"x"), self.upload("clip.mp4", b"x")
        self.upload("memo.m4a", b"x")
        self.upload("doc.pdf", b"x")
        files.add_link(self.user.id, self.project.id, "https://example.org:8443/guide", "Example")
        for lang in ("de", "en"):
            html = self.tile(lang)
            self.assertEqual(html.count('<li class="file-row"'), 5)
            self.assertEqual(html.count("data-need-thumb"), 2)                       # image and video wait for a small picture
            self.assertEqual(html.count("<video "), 0)                               # no player, no original in the list
            self.assertEqual(html.count('class="file-preview file-favicon"'), 1)     # only the link has a picture yet
            self.assertIn('src="https://example.org:8443/favicon.ico"', html)
            self.assertNotIn("%t.", html)
        self.assertTrue(files.save_thumb(self.user.id, pic.id, b"\xff\xd8\xff small"))
        self.assertTrue(files.save_thumb(self.user.id, clip.id, b"\xff\xd8\xff small"))
        html = self.tile()
        self.assertEqual(html.count("data-need-thumb"), 0)
        self.assertIn(f'src="/files/{pic.id}/thumb"', html)
        self.assertNotIn(f'src="/files/{pic.id}"', html)                             # the original is never in the list

    def test_the_tile_counts_in_blocks_and_the_pencil_dialog_has_no_text_but_the_reader_exists(self):
        html = self.tile()
        self.assertIn(f'data-block="{files.BLOCK_SIZE}"', html)
        self.assertNotIn("data-chunk", html)
        self.assertIn('data-starting="', html)
        for lang in ("de", "en"):
            dialogs = managerpage.dialogs(lang)
            pencil = dialogs[dialogs.index('id="file-dialog"'):dialogs.index('id="file-confirm"')]
            self.assertNotIn("<textarea", pencil)                         # the pencil changes name and area only
            self.assertIn('id="file-reader"', dialogs)                    # a click on Markdown opens the big reader
            self.assertIn('id="file-reader-text"', dialogs)
            self.assertNotIn("%t.", dialogs)
    def test_a_click_on_the_name_downloads_a_link_opens_in_a_new_tab(self):
        item = self.upload("a.pdf", b"x")
        link = files.add_link(self.user.id, self.project.id, "https://example.org/doc")
        html = self.tile()
        self.assertIn(f'href="/files/{item.id}?download=1"', html)
        self.assertIn('href="https://example.org/doc" target="_blank" rel="noopener noreferrer"', html)

    # --- small preview pictures
    def test_a_preview_picture_is_kept_for_images_and_video_only(self):
        pic, doc = self.upload("pic.png", b"x"), self.upload("doc.pdf", b"x")
        self.assertTrue(files.save_thumb(self.user.id, pic.id, b"\xff\xd8\xff data"))
        self.assertFalse(files.save_thumb(self.user.id, doc.id, b"\xff\xd8\xff data"))
        self.assertEqual(files.open_thumb(self.user.id, pic.id).read_bytes(), b"\xff\xd8\xff data")
        self.assertIsNone(files.open_thumb(self.user.id, doc.id))
        for bad, code in ((b"<script>alert(1)</script>", "bad_type"), (b"\xff\xd8\xff" + b"x" * files.THUMB_MAX, "too_big")):
            with self.assertRaises(files.FileError) as caught:
                files.save_thumb(self.user.id, pic.id, bad)
            self.assertEqual(caught.exception.code, code)
        unfinished = files.start_upload(self.user.id, self.project.id, "half.png", 3)
        self.assertFalse(files.save_thumb(self.user.id, unfinished.id, b"\xff\xd8\xff data"))
        link = files.add_link(self.user.id, self.project.id, "https://example.org")
        self.assertFalse(files.save_thumb(self.user.id, link.id, b"\xff\xd8\xff data"))

    def test_the_preview_picture_goes_with_the_file_and_is_served_with_a_fixed_type(self):
        pic = self.upload("pic.png", b"x")
        files.save_thumb(self.user.id, pic.id, b"\xff\xd8\xff data")
        response = file_routes.thumb(pic.id, self.user)
        self.assertEqual(response.media_type, "image/jpeg")
        self.assertIn("sandbox", response.headers["content-security-policy"])
        path = files.thumb_path(self.project.id, pic.id)
        files.delete(self.user.id, pic.id)
        self.assertFalse(path.exists())

    def test_a_download_link_always_downloads(self):
        item = self.upload("pic.png", b"x")
        self.assertTrue(file_routes.serve(item.id, 0, self.user).headers["content-disposition"].startswith("inline"))
        self.assertTrue(file_routes.serve(item.id, 1, self.user).headers["content-disposition"].startswith("attachment"))
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
