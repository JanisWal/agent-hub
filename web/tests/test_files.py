"""Files and links of a project: data rules, upload in chunks, protection, serving and the tile."""
import os
import tempfile
import types
import unittest
from pathlib import Path

from app import db, files, i18n, managerpage, memory, projects, users
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

    # --- one folder tree for the project, labels by ending (Janis, 18.11.2026, file-tags)
    def test_folders_hold_files_names_are_unique_per_folder_and_the_list_shows_folders_first(self):
        top = files.create_folder(self.user.id, self.project.id, "Backgrounds")
        dark = files.create_folder(self.user.id, self.project.id, "Dark", top.id)
        self.assertEqual((dark.category, dark.parent_id, dark.kind), ("", top.id, "folder"))   # a folder has no label
        with self.assertRaises(files.FileError):
            files.create_folder(self.user.id, self.project.id, "backgrounds")                     # case does not matter
        self.assertEqual(files.create_folder(self.user.id, self.project.id, "Backgrounds", reuse=True).id, top.id)
        item = files.start_upload(self.user.id, self.project.id, "notes.md", 2, folder_id=dark.id)
        files.append_chunk(self.user.id, item.id, 0, b"hi")
        item = files.finish_upload(self.user.id, item.id)
        self.assertEqual((item.category, item.parent_id), ("memory", dark.id))   # the label of its ending, in the folder
        self.upload("notes.md", b"top")                                          # the same name elsewhere is fine
        self.assertEqual(files.check_names(self.user.id, self.project.id, ["notes.md"], folder_id=dark.id)[0]["ids"], [item.id])
        self.assertEqual(files.check_names(self.user.id, self.project.id, ["other.md"], folder_id=dark.id), [])
        listed = files.list_files(self.user.id, self.project.id)
        self.assertEqual([f.name for f in listed][:2], ["Backgrounds", "Dark"])
        self.assertEqual(files.folder_path(listed, item), ["Backgrounds", "Dark"])
        self.assertIsNone(files.open_file(self.user.id, top.id))                 # a folder has no file to serve
        with db.connect() as conn:
            stored, _ = files.for_agents(conn, self.user.id, self.project.id)
        self.assertIn(["Backgrounds", "Dark"], [s["path"] for s in stored])
        self.assertNotIn("Backgrounds", [s["name"] for s in stored])           # folders are no files for the AI

    def test_a_file_dropped_on_a_tab_gets_its_label(self):
        item = files.start_upload(self.user.id, self.project.id, "plan.pdf", 1, label="code")
        self.assertEqual(item.category, "code")
        for bad in ("links", "nowhere"):
            self.assertEqual(files.start_upload(self.user.id, self.project.id, "x.pdf", 1, label=bad).category, "documents")

    def test_moving_changes_only_the_place_and_labels_only_the_label(self):
        a = self.upload("a.png", b"a")
        b = self.upload("b.py", b"b")
        link = files.add_link(self.user.id, self.project.id, "https://example.org", "Site")
        box = files.create_folder(self.user.id, self.project.id, "Box")
        inner = files.create_folder(self.user.id, self.project.id, "Inner", box.id)
        self.upload("a.png", b"other")                                           # a name the folder will have
        files.move(self.user.id, self.project.id, [self.upload("a.png", b"x").id], folder_id=box.id)
        self.assertEqual(files.move(self.user.id, self.project.id, [a.id, b.id, link.id], folder_id=box.id), 3)
        rows = {f.id: f for f in files.list_files(self.user.id, self.project.id)}
        self.assertEqual({rows[i].parent_id for i in (a.id, b.id, link.id)}, {box.id})   # links may lie in folders
        self.assertEqual((rows[a.id].category, rows[a.id].name), ("media", "a (2).png"))  # label stays, name made free
        self.assertEqual(rows[link.id].category, "links")
        self.assertEqual(files.move(self.user.id, self.project.id, [box.id], folder_id=inner.id), 0)   # not into itself
        self.assertEqual(files.move(self.user.id, self.project.id, [box.id], folder_id=box.id), 0)
        self.assertEqual(files.move(self.user.id, self.project.id, [a.id]), 1)                  # back to the top
        self.assertEqual(files.move(self.user.id, self.project.id, [a.id], folder_id=inner.id), 1)
        # labels: a folder gives its label to every file inside, the folder stays where it is; links keep theirs
        self.assertEqual(files.set_label(self.user.id, self.project.id, [box.id], "documents"), 3)
        rows = {f.id: f for f in files.list_files(self.user.id, self.project.id)}
        self.assertEqual({rows[i].category for i in (a.id, b.id)}, {"documents"})
        self.assertEqual((rows[box.id].category, rows[box.id].parent_id, rows[link.id].category), ("", None, "links"))
        for bad in ("links", "nowhere"):
            with self.assertRaises(files.FileError):
                files.set_label(self.user.id, self.project.id, [a.id], bad)
        renamed = files.update(self.user.id, inner.id, "Renamed", category="code")   # pencil on a folder: name only
        self.assertEqual((renamed.name, renamed.category, renamed.parent_id), ("Renamed", "", box.id))
        relabelled = files.update(self.user.id, b.id, "b.py", category="code")
        self.assertEqual((relabelled.category, relabelled.parent_id), ("code", box.id))   # stays in its folder

    def test_a_folder_goes_into_the_trash_with_all_inside_and_comes_back_together(self):
        box = files.create_folder(self.user.id, self.project.id, "Box")
        inner = files.create_folder(self.user.id, self.project.id, "Inner", box.id)
        a = self.upload("a.png", b"a")
        files.move(self.user.id, self.project.id, [a.id], folder_id=inner.id)
        early = self.upload("early.png", b"e")
        files.move(self.user.id, self.project.id, [early.id], folder_id=box.id)
        files.delete(self.user.id, early.id, now=100)                            # went in on its own, earlier
        self.assertTrue(files.delete(self.user.id, box.id, now=200))
        self.assertEqual([f.name for f in files.list_files(self.user.id, self.project.id)], [])
        self.assertEqual([f.name for f, _ in files.list_trash(self.user.id, self.project.id, now=300)], ["Box", "early.png"])
        files.restore(self.user.id, box.id)
        self.assertEqual(sorted(f.name for f in files.list_files(self.user.id, self.project.id)), ["Box", "Inner", "a.png"])
        back = files.restore(self.user.id, early.id)
        self.assertEqual(back.parent_id, box.id)                                 # its folder is back: into it
        files.delete(self.user.id, box.id)
        self.assertTrue(files.purge(self.user.id, box.id))
        self.assertFalse(files.path_of(self.project.id, a.id).exists())          # everything inside is gone from disk
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0], 0)

    def test_a_folder_comes_as_a_zip_with_its_paths(self):
        box = files.create_folder(self.user.id, self.project.id, "Box")
        inner = files.create_folder(self.user.id, self.project.id, "Inner", box.id)
        a = self.upload("a.png", b"A")
        b = self.upload("b.png", b"B")
        files.move(self.user.id, self.project.id, [a.id], folder_id=box.id)
        files.move(self.user.id, self.project.id, [b.id], folder_id=inner.id)
        loose = self.upload("a.png", b"loose")
        names = [name for _, name in files.zip_entries(self.user.id, self.project.id, [box.id, loose.id])]
        self.assertEqual(names, ["Box/Inner/b.png", "Box/a.png", "a.png"])

    def test_the_memory_is_only_the_memory_files_at_the_top(self):
        sub = files.create_folder(self.user.id, self.project.id, "Old")
        old = files.create_text_file(self.user.id, self.project.id, "MEMORY.md", "old notes")
        files.move(self.user.id, self.project.id, [old.id], folder_id=sub.id)
        with db.connect() as conn:
            self.assertIsNone(memory._find(conn, self.user.id, self.project.id, "MEMORY.md"))
            self.assertIsNotNone(memory._find(conn, self.user.id, self.project.id, "MEMORY.md", memory_only=False))
            self.assertNotIn("Old", memory.listing(conn, self.user.id, self.project.id))

    def test_the_folder_routes(self):
        made = file_routes.create_folder(self.project.id, "Plans", "", "0", self.user)
        self.assertTrue(made["ok"] and made["folder"])
        again = file_routes.create_folder(self.project.id, "Plans", "", "0", self.user)
        self.assertEqual(again.status_code, 409)
        self.assertEqual(file_routes.create_folder(self.project.id, "plans", "", "1", self.user)["id"], made["id"])
        item = self.upload("x.pdf", b"x")
        self.assertEqual(file_routes.move(self.project.id, f"{item.id},junk", str(made["id"]), self.user)["moved"], 1)
        self.assertEqual(file_routes.set_label(self.project.id, str(made["id"]), "media", self.user)["changed"], 1)
        self.assertEqual(file_routes.set_label(self.project.id, str(item.id), "links", self.user).status_code, 400)
        started = file_routes.start_upload(self.project.id, "y.pdf", 1, self.user, folder=str(made["id"]), label="code")
        self.assertEqual((started["parent"], started["category"]), (made["id"], "code"))
        link = file_routes.add_link(self.project.id, "https://example.org", "", self.user, folder=str(made["id"]))
        self.assertEqual(link["parent"], made["id"])

    def test_once_folders_lose_their_area_and_top_names_become_unique(self):
        with db.connect() as conn:                     # the state before file-tags: a folder per area, names per area
            for name, category, folder in (("Notes", "media", 1), ("Notes", "documents", 1), ("MEMORY.md", "documents", 0),
                                           ("MEMORY.md", "memory", 0), ("plan.pdf", "documents", 0)):
                conn.execute("INSERT INTO files (project_id, name, category, size, status, created_at, parts, is_folder)"
                             " VALUES (?, ?, ?, 0, 'ready', 0, '', ?)", (self.project.id, name, category, folder))
            files.one_tree(conn)
            rows = conn.execute("SELECT name, category, is_folder FROM files ORDER BY id").fetchall()
        self.assertEqual([tuple(r) for r in rows], [("Notes", "", 1), ("Notes (2)", "", 1), ("MEMORY (2).md", "documents", 0),
                                                    ("MEMORY.md", "memory", 0), ("plan.pdf", "documents", 0)])

    # --- sorting by ending
    def test_new_files_are_sorted_by_their_ending(self):
        wanted = {"a.md": "memory", "a.py": "code", "a.swift": "code", "a.PNG": "media", "a.mp4": "media",
                  "a.m4a": "media", "a.pdf": "documents", "a.zip": "documents", "noending": "documents",
                  "IMG_0001.DNG": "media", "a.tif": "media", "a.heic": "media", "a.cr2": "media", "a.nef": "media"}
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
    def test_an_interrupted_upload_can_ask_what_the_server_has_and_keeps_it_alive(self):
        uid = self.user.id
        item = files.start_upload(uid, self.project.id, "a.bin", 10, now=1000)    # blocks of 4, 4 and 2
        self.assertEqual(files.upload_progress(uid, item.id, now=1000 + files.STALE - 5), (10, "000"))
        files.append_chunk(uid, item.id, 4, b"abcd")
        self.assertEqual(files.upload_progress(uid, item.id, now=1000 + files.STALE - 5), (10, "010"))
        files.start_upload(uid, self.project.id, "b.bin", 1, now=1000 + files.STALE + 100)   # a later start drops stale uploads
        self.assertEqual(files.upload_progress(uid, item.id), (10, "010"))        # asking had kept it alive
        files.append_chunk(uid, item.id, 0, b"abcd")
        files.append_chunk(uid, item.id, 8, b"ab")
        files.finish_upload(uid, item.id)
        self.assertIsNone(files.upload_progress(uid, item.id))                    # finished: nothing to resume
        self.assertIsNone(files.upload_progress(uid, 9999))

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

    def test_a_broken_request_keeps_the_whole_blocks_that_arrived(self):
        uid = self.user.id
        item = files.start_upload(uid, self.project.id, "a.bin", 10)             # blocks of 4, 4 and 2
        run = files.Run(uid, item.id, 0, 10)
        run.write(b"abcdef")                                                     # one and a half blocks, then the line breaks
        self.assertEqual(run.close(), 1)
        self.assertEqual(files.upload_progress(uid, item.id)[1], "100")          # the browser sends only from block 2 on
        run = files.Run(uid, item.id, 4, None)                                   # no announced length: up to the end of the file
        run.write(b"efgh")
        run.write(b"ij")
        self.assertEqual(run.close(), 3)
        self.assertEqual(files.open_file(uid, files.finish_upload(uid, item.id).id)[0].read_bytes(), b"abcdefghij")

    def test_a_request_may_not_carry_more_than_it_announced(self):
        item = files.start_upload(self.user.id, self.project.id, "a.bin", 12)
        run = files.Run(self.user.id, item.id, 0, 4)
        with self.assertRaises(files.FileError) as caught:
            run.write(b"abcde")
        self.assertEqual(caught.exception.code, "too_big")
        self.assertEqual(run.close(), 0)

    def _post_chunk(self, file_id, offset, pieces, announced):
        """The upload route with a body that arrives in pieces; a None piece is the line breaking."""
        import asyncio
        from starlette.requests import Request
        messages = [{"type": "http.disconnect"} if piece is None else {"type": "http.request", "body": piece, "more_body": True}
                    for piece in pieces]
        if pieces and pieces[-1] is not None:
            messages[-1]["more_body"] = False

        async def receive():
            return messages.pop(0)
        scope = {"type": "http", "method": "POST", "path": f"/files/{file_id}/chunk", "query_string": b"",
                 "headers": [(b"content-length", str(announced).encode())]}
        answer = asyncio.run(file_routes.upload_chunk(file_id, offset, Request(scope, receive), self.user))
        return types.SimpleNamespace(status_code=200) if isinstance(answer, dict) else answer      # ok() is a plain dict

    def test_the_route_writes_while_the_body_arrives_and_keeps_it_after_a_break(self):
        uid = self.user.id
        item = files.start_upload(uid, self.project.id, "a.bin", 10)             # blocks of 4, 4 and 2
        broken = self._post_chunk(item.id, 0, [b"abcd", b"ef", None], 10)
        self.assertNotEqual(broken.status_code, 200)
        self.assertEqual(files.upload_progress(uid, item.id)[1], "100")
        self.assertEqual(self._post_chunk(item.id, 4, [b"efg", b"hij"], 6).status_code, 200)
        self.assertEqual(files.upload_progress(uid, item.id)[1], "111")
        self.assertEqual(self._post_chunk(item.id, 1, [b"x"], 1).status_code, 409)          # a wrong offset reads nothing

    # --- same names: the upload asks first, renaming refuses
    def test_the_check_says_which_names_the_place_has_and_offers_free_ones(self):
        old = self.upload("Bild.png", b"x")
        self.upload("Bild (2).png", b"x")
        self.upload("Makefile", b"x")
        taken = files.check_names(self.user.id, self.project.id, ["bild.PNG", "neu.png", "Makefile", "Bild.png"])
        self.assertEqual(taken, [
            {"name": "bild.PNG", "ids": [old.id], "free": "bild (3).PNG"},       # case does not matter, (2) is taken
            {"name": "Makefile", "ids": [taken[1]["ids"][0]], "free": "Makefile (2)"},
            {"name": "Bild.png", "ids": [old.id], "free": "Bild (4).png"},       # a free name is never handed out twice
        ])
        box = files.create_folder(self.user.id, self.project.id, "Box")
        self.assertEqual(files.check_names(self.user.id, self.project.id, ["Bild.png"], folder_id=box.id), [])   # another folder

    def test_a_name_twice_in_the_same_upload_counts_as_taken(self):
        taken = files.check_names(self.user.id, self.project.id, ["a.txt", "a.txt", "../bad", ""])
        self.assertEqual(taken, [{"name": "a.txt", "ids": [], "free": "a (2).txt"}])

    def test_renaming_onto_a_name_of_the_place_is_refused(self):
        first = self.upload("a.txt", b"x")
        second = self.upload("b.txt", b"x")
        for name, category in (("A.TXT", None), ("a.txt", "documents")):
            with self.assertRaises(files.FileError) as caught:
                files.update(self.user.id, second.id, name, category=category)
            self.assertEqual(caught.exception.code, "name_taken")
        self.assertEqual(files.update(self.user.id, first.id, "a.txt").name, "a.txt")        # its own name is fine
        files.update(self.user.id, first.id, "a.txt", category="code")                     # the label does not free it
        with self.assertRaises(files.FileError):
            files.update(self.user.id, second.id, "a.txt")
        files.move(self.user.id, self.project.id, [first.id], files.create_folder(self.user.id, self.project.id, "Box").id)
        self.assertEqual(files.update(self.user.id, second.id, "a.txt").name, "a.txt")     # another folder is free

    def test_the_check_route_answers_only_for_own_projects(self):
        self.upload("a.txt", b"x")
        answer = file_routes.check_names(self.project.id, ["a.txt"], self.user)
        self.assertEqual(answer["taken"][0]["free"], "a (2).txt")
        other = users.create_user("b@example.com", "Bbbb!pass12")
        self.assertEqual(file_routes.check_names(self.project.id, ["a.txt"], other).status_code, 404)

    # --- several files out as one ZIP
    def test_marked_files_come_as_one_zip_with_the_original_bytes(self):
        import io
        import zipfile
        a = self.upload("a.txt", b"first file")
        pic = self.upload("a.png", bytes(range(256)) * 4)
        same = self.upload("a.txt", b"other area")                      # the same name in another folder
        files.move(self.user.id, self.project.id, [same.id], files.create_folder(self.user.id, self.project.id, "Box").id)
        link = files.add_link(self.user.id, self.project.id, "https://example.org", "Link")
        entries = files.zip_entries(self.user.id, self.project.id, [pic.id, a.id, same.id, link.id, 9999, a.id])
        self.assertEqual([name for _, name in entries], ["a.png", "a.txt", "a (2).txt"])   # no link, no doubles
        pieces = list(files.zip_stream(entries, piece=1000))
        self.assertGreater(len(pieces), 5)                                  # sent in pieces, not built whole first
        archive = zipfile.ZipFile(io.BytesIO(b"".join(pieces)))
        self.assertIsNone(archive.testzip())
        self.assertEqual(archive.read("a.png"), bytes(range(256)) * 4)      # the original, unchanged
        self.assertEqual(archive.read("a (2).txt"), b"other area")
        self.assertEqual({i.compress_type for i in archive.infolist()}, {zipfile.ZIP_STORED})

    def test_the_zip_route_answers_only_for_own_files(self):
        a = self.upload("a.txt", b"x")
        b = self.upload("b.txt", b"y")
        answer = file_routes.download_zip(self.project.id, f"{a.id},{b.id},x", self.user)
        self.assertEqual(answer.media_type, "application/zip")
        self.assertIn("filename*=UTF-8''2%20Dateien.zip", answer.headers["content-disposition"])
        other = users.create_user("b@example.com", "Bbbb!pass12")
        self.assertEqual(file_routes.download_zip(self.project.id, f"{a.id}", other).status_code, 404)
        self.assertEqual(file_routes.download_zip(self.project.id, "", self.user).status_code, 404)

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

    # --- rename, label, delete
    def test_rename_and_label_by_hand(self):
        item = self.upload("a.pdf", b"x")
        changed = files.update(self.user.id, item.id, "manual.pdf", category="memory")
        self.assertEqual((changed.name, changed.category), ("manual.pdf", "memory"))
        for bad in ("links", "nonsense"):
            with self.assertRaises(files.FileError):
                files.update(self.user.id, item.id, "manual.pdf", category=bad)

    def test_delete_puts_the_file_into_the_trash(self):
        """Janis, 14.11.2026: a trash for files, kept TRASH_DAYS, then gone; the manager never sees it."""
        item = self.upload("a.txt", b"x")
        path = files.path_of(self.project.id, item.id)
        self.assertTrue(files.delete(self.user.id, item.id, now=1000))
        self.assertTrue(path.exists())                                          # still there ...
        self.assertEqual(files.list_files(self.user.id, self.project.id), [])  # ... but out of every list
        with db.connect() as conn:
            self.assertNotIn("a.txt", memory.listing(conn, self.user.id, self.project.id))   # the manager: nothing
        trashed = files.list_trash(self.user.id, self.project.id, now=1000 + 86400)
        self.assertEqual([(t.name, left) for t, left in trashed], [("a.txt", files.TRASH_DAYS - 1)])
        self.assertIsNone(files.open_file(self.user.id, item.id))              # no download from the trash
        self.assertEqual(files.restore(self.user.id, item.id).name, "a.txt")
        self.assertEqual([f.name for f in files.list_files(self.user.id, self.project.id)], ["a.txt"])

    def test_restore_gives_a_taken_name_a_number(self):
        old = self.upload("a.txt", b"x")
        files.delete(self.user.id, old.id)
        self.upload("a.txt", b"new")
        self.assertEqual(files.restore(self.user.id, old.id).name, "a (2).txt")
        self.assertIsNone(files.restore(self.user.id, old.id))                  # not in the trash any more

    def test_purge_empty_and_the_end_of_the_thirty_days(self):
        a, b, c = self.upload("a.txt", b"x"), self.upload("b.txt", b"x"), self.upload("c.txt", b"x")
        self.assertFalse(files.purge(self.user.id, a.id))                       # a finished file is never purged
        for item in (a, b, c):
            files.delete(self.user.id, item.id, now=1000)
        self.assertTrue(files.purge(self.user.id, a.id))
        self.assertFalse(files.path_of(self.project.id, a.id).exists())
        self.assertEqual(files.purge_old_trash(now=1000 + files.TRASH_DAYS * 86400 - 10), 0)
        self.assertEqual(files.purge_old_trash(now=1000 + files.TRASH_DAYS * 86400 + 10), 2)
        self.assertEqual(files.list_trash(self.user.id, self.project.id), [])
        d = self.upload("d.txt", b"x")
        files.delete(self.user.id, d.id)
        self.assertEqual(files.empty_trash(self.user.id, self.project.id), 1)
        self.assertFalse(files.path_of(self.project.id, d.id).exists())

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
        users.delete_user(owner, self.user.id, now=1000)
        self.assertTrue(files.path_of(self.project.id, item.id).exists())      # kept while the account can come back
        users.purge_deleted(now=1000 + (users.DELETED_DAYS + 1) * 86400)
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
        # code and data are shown in the reader, but only notes are changed there (Janis, 18.11.2026)
        for name in ("main.py", "data.csv", "page.html", "Makefile", "server.log"):
            item = self.upload(name, b"print(1)")
            self.assertEqual(files.read_text(self.user.id, item.id), "print(1)", name)
            self.assertTrue(item.readable and not item.editable, name)
            self.assertFalse(files.write_text(self.user.id, item.id, "x"), name)
        self.assertFalse(self.upload("a.docx", b"x").readable)
        with self.assertRaises(files.FileError):
            files.write_text(self.user.id, note.id, "x" * (files.TEXT_MAX + 1))

    # --- serving: fixed type, nothing runs
    def serve(self, item):
        return file_routes.serve(item.id, 0, self.user)

    def test_only_images_video_audio_and_pdfs_are_shown_everything_else_is_a_download(self):
        for name, shown in (("a.png", True), ("a.svg", True), ("a.mp4", True), ("a.mp3", True), ("a.html", False),
                            ("a.pdf", True), ("a.js", False), ("a.exe", False), ("a.md", False)):
            response = self.serve(self.upload(name, b"<script>alert(1)</script>"))
            self.assertEqual(response.headers["content-disposition"].startswith("inline"), shown, name)
            if not shown:
                self.assertEqual(response.media_type, "application/octet-stream", name)
            if name != "a.pdf":
                self.assertIn("sandbox", response.headers["content-security-policy"])

    def test_a_pdf_is_shown_by_the_browsers_viewer_under_a_policy_that_allows_nothing_else(self):
        item = self.upload("Schaltplan.pdf", b"%PDF-1.4")
        self.assertEqual(item.kind, "pdf")
        shown = self.serve(item)
        self.assertEqual(shown.media_type, "application/pdf")
        policy = shown.headers["content-security-policy"]
        self.assertNotIn("sandbox", policy)                       # Chrome does not start its PDF viewer in a sandbox
        self.assertIn("default-src 'none'", policy)
        self.assertNotIn("script-src", policy)
        self.assertIn("frame-ancestors 'self'", policy)           # only the hub's own page may show it
        downloaded = file_routes.serve(item.id, 1, self.user)
        self.assertTrue(downloaded.headers["content-disposition"].startswith("attachment"))
        self.assertIn("sandbox", downloaded.headers["content-security-policy"])

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
    def test_the_trash_circle_setting_is_kept_with_the_account_and_shows_in_the_tile(self):
        self.assertTrue(users.get_by_id(self.user.id).files_confirm)                 # asking is the default
        file_routes.preferences("0", self.user)
        self.assertFalse(users.get_by_id(self.user.id).files_confirm)
        stored = files.list_files(self.user.id, self.project.id)
        settings = {"roles": {"chef": {"model": "sonnet", "net": "together"}}, "autonomy": "major"}
        self.assertIn('data-confirm-delete="0"', managerpage.render("en", settings, stored_files=stored, files_confirm=False))
        self.assertIn('data-confirm-delete="1"', managerpage.render("en", settings, stored_files=stored, files_confirm=True))
        file_routes.preferences("1", self.user)
        self.assertTrue(users.get_by_id(self.user.id).files_confirm)

    def test_the_tile_header_has_the_trash_and_the_enlarge_circle_next_to_the_plus(self):
        for lang in ("de", "en"):
            html = self.tile(lang)
            start = html.index('class="file-tools"')
            head = html[start:html.index("</header>", start)]
            self.assertLess(head.index('id="file-download"'), head.index('id="file-trash-mode"'))   # quiet, left of the bin
            self.assertIn('aria-hidden="true"', head[:head.index('id="file-trash-mode"')])      # hidden until files are marked
            self.assertIn('data-download-marked="', html)
            self.assertLess(head.index('id="file-trash-mode"'), head.index('id="file-expand"'))
            self.assertLess(head.index('id="file-expand"'), head.index('id="file-add"'))     # the plus stays on the right
            self.assertIn('id="file-status"', html)                                  # one quiet line, nothing that floats over things
            self.assertNotIn('id="file-note"', html)
            self.assertIn('data-marked="', html)
            self.assertIn('data-drop="', html)
            self.assertNotIn("%t.", html)

    def test_the_tile_and_the_dialogs_carry_the_texts_for_marking_and_deleting_many(self):
        for lang in ("de", "en"):
            self.assertIn('data-delete-selected="', self.tile(lang))
            dialogs = managerpage.dialogs(lang)
            self.assertIn('data-text-many="', dialogs)
            self.assertIn("{n}", dialogs[dialogs.index('data-text-many="'):dialogs.index('data-text-many="') + 80])   # filled in by the script
            self.assertNotIn("%t.", dialogs)
            self.assertNotIn("%MANY%", dialogs)

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
        raw = self.upload("IMG_0001.dng", b"II*\x00 raw")                         # a camera file gets one too (14.11.2026)
        self.assertEqual(raw.kind, "photo")
        self.assertTrue(files.save_thumb(self.user.id, raw.id, b"\xff\xd8\xff data"))
        # and a big preview for the viewer (a browser can not show a raw file), but only such files get one
        self.assertTrue(files.save_thumb(self.user.id, raw.id, b"\xff\xd8\xff big", large=True))
        self.assertEqual(files.open_thumb(self.user.id, raw.id, large=True).read_bytes(), b"\xff\xd8\xff big")
        self.assertFalse(files.save_thumb(self.user.id, pic.id, b"\xff\xd8\xff big", large=True))
        other = users.create_user("b@example.com", "Bbbb!pass12")
        self.assertEqual(file_routes.preview(raw.id, other).status_code, 404)               # never someone else's
        files.delete(self.user.id, raw.id)
        files.purge(self.user.id, raw.id)
        self.assertFalse(files.thumb_path(self.project.id, raw.id, True).exists())
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
        files.purge(self.user.id, pic.id)
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
