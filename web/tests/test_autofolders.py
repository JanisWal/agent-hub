"""Structure the folders automatically (autofolders.py): the job, the list the AI reads, the checked plan, the preview
that changes nothing, applying, dropping, the routes and the button that shows only in the explorer."""
import os
import tempfile
import time
import unittest
from pathlib import Path

from app import (agents, autofolders, chat, claude_link, db, files, i18n, managerpage, projects, reply, serversettings,
                 statusnote, users)
from app.routes import files as file_routes

NOW = int(time.time())


def rows() -> list[tuple]:
    with db.connect() as conn:
        return [tuple(r) for r in conn.execute("SELECT * FROM files ORDER BY id")]


class AutoFoldersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.original = (files.FILES_DIR, files.free_bytes)
        files.FILES_DIR = Path(self.tmp.name) / "files"
        files.free_bytes = lambda: 10 * 1024 ** 3
        self.a = users.create_user("a@example.com", "Aaaa!pass12")
        self.b = users.create_user("b@example.com", "Bbbb!pass12")
        self.pa = projects.create_project(self.a.id, "Roadster")
        self.pb = projects.create_project(self.b.id, "Of B")
        self.memo = files.create_text_file(self.a.id, self.pa.id, "MEMORY.md", "# Stand")
        self.manual = files.create_text_file(self.a.id, self.pa.id, "manual.txt", "heater")
        self.notes = files.create_text_file(self.a.id, self.pa.id, "notes.txt", "relay")
        self.old = files.create_folder(self.a.id, self.pa.id, "Old")
        self.kept = files.create_folder(self.a.id, self.pa.id, "Empty on purpose")
        files.move(self.a.id, self.pa.id, [self.notes.id], folder_id=self.old.id)
        self.link = files.add_link(self.a.id, self.pa.id, "https://example.com/doc", "Example")
        statusnote._LAST_SCAN["at"] = NOW                  # no status round comes in between

    def tearDown(self):
        files.FILES_DIR, files.free_bytes = self.original
        self.tmp.cleanup()

    def connect(self, user):
        claude_link.begin(user.id)
        claude_link.complete(user.id, True)

    def answer(self, text, ok=True):
        job = chat.claim_next(NOW)
        self.assertTrue(chat.finish(job.chat_id, ok, text))
        return job

    def test_reading_the_moves(self):
        text, moves = reply.moves('Sorted. <move id="3" to="Hintergründe/Dunkel"/>\n<move id="4" to="/Code/"></move>'
                                  '<move id="x" to="a"/><move id="3" to="b"/><move id="5" to=""/><move id="6"/>')
        self.assertEqual(text, "Sorted.")
        self.assertEqual(moves, [(3, "Hintergründe/Dunkel"), (4, "Code"), (5, "")])   # "" = the top; no `to`: left out

    def test_a_job_on_the_managers_model_with_the_list_only(self):
        self.assertEqual(autofolders.request(self.a.id, self.pa.id), "none")          # no AI yet
        self.connect(self.a)
        self.assertEqual(autofolders.request(self.a.id, self.pb.id), "missing")       # not his project
        self.assertEqual(autofolders.request(self.a.id, self.pa.id), "queued")
        self.assertEqual(autofolders.request(self.a.id, self.pa.id), "wait")          # one is on its way
        self.assertEqual(autofolders.state(self.a.id, self.pa.id).status, "queued")
        job = chat.claim_next(NOW)
        self.assertEqual((job.mode, job.project_id, job.files), ("brief", 0, []))     # no tools, no files
        self.assertIn(f"{self.notes.id} | Old/notes.txt | documents | text", job.prompt)
        self.assertIn(f"{self.link.id} | Example | links | link", job.prompt)
        self.assertNotIn("MEMORY.md", job.prompt)                                     # the memory never moves
        self.assertIn("<move id=", job.prompt)
        self.assertIn("German", job.prompt)
        self.assertEqual(chat.list_messages(self.a.id, self.pa.id), [])               # not a chat question

    def test_with_contents_the_ai_gets_the_files(self):
        self.connect(self.a)
        self.assertEqual(autofolders.request(self.a.id, self.pa.id, contents=True), "queued")
        job = chat.claim_next(NOW)
        self.assertEqual((job.mode, job.project_id), ("sort", self.pa.id))
        self.assertEqual(job.limits["chat_seconds"], serversettings.sort_seconds() + 20)
        self.assertIn("manual.txt", [f["name"] for f in job.files])
        self.assertIn("/files", job.prompt)

    def test_a_plan_starts_although_all_slots_are_taken_and_takes_none(self):
        self.connect(self.a)
        self.connect(self.b)
        chat.send(self.b.id, self.pb.id, "long question", now=NOW)
        running = chat.claim_next(NOW)                     # the one slot of the default setting
        with db.connect() as conn:
            self.assertFalse(agents.slot_free(conn))
        for contents, mode in ((False, "brief"), (True, "sort")):
            autofolders.request(self.a.id, self.pa.id, contents=contents, now=NOW)
            self.assertEqual(chat.claim_next(NOW).mode, mode)
            self.assertEqual(autofolders.state(self.a.id, self.pa.id).status, "running")
            autofolders.discard(self.a.id, self.pa.id)
        autofolders.request(self.a.id, self.pa.id, now=NOW)
        chat.claim_next(NOW)
        chat.finish(running.chat_id, True, "done")
        with db.connect() as conn:                         # the plan still runs and holds nobody up
            self.assertTrue(agents.slot_free(conn))
        chat.send(self.b.id, self.pb.id, "next question", now=NOW)
        self.assertEqual(chat.claim_next(NOW).project_id, self.pb.id)

    def test_a_chat_question_waits_for_a_slot_and_neither_fails_nor_loses_time(self):
        statusnote._LAST_SCAN["at"] = NOW + 10 ** 6        # no status round in these later minutes
        self.connect(self.a)
        self.connect(self.b)
        chat.send(self.b.id, self.pb.id, "long question", now=NOW)
        running = chat.claim_next(NOW)
        waiting = chat.send(self.a.id, self.pa.id, "me too", now=NOW)
        later = NOW
        for _ in range(8):                                 # the runner keeps asking while the other answer goes on
            later += 100
            with db.connect() as conn:                     # the other answer stays alive
                conn.execute("UPDATE chat_messages SET started_at = ? WHERE id = ?", (later, running.chat_id))
            self.assertIsNone(chat.claim_next(later))
        chat.finish(running.chat_id, True, "done")
        self.assertEqual(chat.claim_next(later + 5).chat_id, waiting.id)   # it starts instead of failing
        chat.claim_next(later + 60)                        # and its time counts from the start, not from the question
        self.assertEqual(chat.list_messages(self.a.id, self.pa.id)[-1].status, "running")

    def test_a_running_plan_gets_longer_than_a_chat_answer_then_fails(self):
        self.connect(self.a)
        autofolders.request(self.a.id, self.pa.id, now=NOW)
        chat.claim_next(NOW)
        chat.claim_next(NOW + serversettings.chat_seconds() + 121)
        self.assertEqual(autofolders.state(self.a.id, self.pa.id).status, "running")
        chat.claim_next(NOW + serversettings.sort_seconds() + 121)
        self.assertEqual(autofolders.state(self.a.id, self.pa.id).status, "failed")
        self.assertLess(serversettings.sort_seconds() + 20, 3600)   # a ticket counts an hour

    def test_a_big_project_is_listed_by_path_with_all_folders_and_what_is_left_out_is_said(self):
        original = autofolders.LIST_MAX
        autofolders.LIST_MAX = 3
        self.addCleanup(setattr, autofolders, "LIST_MAX", original)
        with db.connect() as conn:
            lines = autofolders.listing(conn, self.pa.id).splitlines()
        self.assertEqual(len(lines), 4)
        self.assertIn(f"{self.old.id} | Old/", "\n".join(lines))
        self.assertIn(f"{self.kept.id} | Empty on purpose/", "\n".join(lines))
        self.assertIn("2 more files are not listed", lines[-1])   # 5 rows may move, 3 are listed
        self.connect(self.a)
        autofolders.request(self.a.id, self.pa.id, now=NOW)
        self.answer("nothing to do")
        self.assertGreater(autofolders.state(self.a.id, self.pa.id).left_out, 0)

    def test_nothing_to_sort(self):
        self.connect(self.b)
        self.assertEqual(autofolders.request(self.b.id, self.pb.id), "empty")

    def test_the_preview_changes_nothing_and_apply_carries_the_checked_plan_out(self):
        self.connect(self.a)
        loose_memo = files.create_text_file(self.a.id, self.pa.id, "idea.md", "x")
        files.move(self.a.id, self.pa.id, [loose_memo.id], folder_id=files.create_folder(self.a.id, self.pa.id, "Ideas").id)
        autofolders.request(self.a.id, self.pa.id)
        plan_text = (
            f'<move id="{self.manual.id}" to="Heizung/Anleitungen"/>'
            f'<move id="{self.notes.id}" to="Heizung"/>'
            f'<move id="{self.memo.id}" to="Heizung"/>'                    # the memory stays at the top
            f'<move id="{loose_memo.id}" to=""/>'                         # a memory file never comes to the top
            f'<move id="{self.manual.id}" to="Nope"/>'                    # only the first move of an id counts
            f'<move id="{self.link.id}" to="Quellen"/>'                   # links may lie in folders
            f'<move id="{self.old.id}" to="Heizung/Old"/>'                # emptied: it goes, and so does the new Old
            f'<move id="999" to="X"/>'                                    # not there
            "Heizung zusammengelegt.")
        self.answer(plan_text)
        before = rows()
        plan = autofolders.state(self.a.id, self.pa.id)
        self.assertEqual(rows(), before)                                   # looking moves nothing
        self.assertEqual(plan.status, "done")
        self.assertEqual(plan.note, "Heizung zusammengelegt.")
        tree = [(n.depth, n.name, n.kind, n.moved, n.new) for n in plan.nodes]
        self.assertIn((0, "Heizung", "folder", False, True), tree)
        self.assertIn((1, "Anleitungen", "folder", False, True), tree)
        self.assertIn((2, "manual.txt", "text", True, False), tree)
        self.assertIn((1, "notes.txt", "text", True, False), tree)
        self.assertIn((1, "Example", "link", True, False), tree)
        self.assertIn((0, "Empty on purpose", "folder", False, False), tree)   # an empty folder of the user stays
        self.assertNotIn("Old", [n.name for n in plan.nodes])                 # emptied by the plan: gone
        self.assertIn((0, "MEMORY.md", "text", False, False), tree)
        self.assertEqual({n.label for n in plan.nodes if n.name == "MEMORY.md"}, {"memory"})
        self.assertEqual((plan.moved, plan.folders), (4, 3))   # manual, notes, link, Old; new: Heizung, Anleitungen, Quellen
        self.assertEqual(autofolders.apply(self.b.id, self.pa.id), None)       # not B's
        self.assertEqual(rows(), before)
        self.assertEqual(autofolders.apply(self.a.id, self.pa.id), 4)
        listed = files.list_files(self.a.id, self.pa.id)
        by_id = {f.id: f for f in listed}
        self.assertEqual(files.folder_path(listed, by_id[self.manual.id]), ["Heizung", "Anleitungen"])
        self.assertEqual(files.folder_path(listed, by_id[self.notes.id]), ["Heizung"])
        self.assertEqual(files.folder_path(listed, by_id[loose_memo.id]), ["Ideas"])   # to the top: refused
        self.assertNotIn(self.old.id, by_id)
        self.assertIn(self.kept.id, by_id)
        self.assertEqual((by_id[self.memo.id].category, by_id[self.memo.id].parent_id), ("memory", None))
        self.assertEqual((by_id[self.manual.id].category, by_id[self.link.id].category), ("documents", "links"))
        self.assertEqual(autofolders.state(self.a.id, self.pa.id).status, "none")   # the plan is used up
        self.assertIsNone(autofolders.apply(self.a.id, self.pa.id))

    def test_a_failed_job_and_dropping_a_plan(self):
        self.connect(self.a)
        autofolders.request(self.a.id, self.pa.id)
        self.answer("Not logged in: please run /login", ok=False)
        plan = autofolders.state(self.a.id, self.pa.id)
        self.assertEqual((plan.status, chat.failure_kind(plan.answer)), ("failed", "auth"))
        self.assertEqual(autofolders.request(self.a.id, self.pa.id), "queued")        # a new try replaces it
        self.assertFalse(autofolders.discard(self.b.id, self.pa.id))
        self.assertTrue(autofolders.discard(self.a.id, self.pa.id))
        self.assertEqual(autofolders.state(self.a.id, self.pa.id).status, "none")
        self.assertIsNone(chat.claim_next(NOW))                                       # the job went with it
        self.assertIsNone(autofolders.state(self.b.id, self.pa.id))

    def test_the_routes(self):
        self.assertEqual(file_routes.structure_request(self.pa.id, "0", self.a).status_code, 409)   # no AI
        self.connect(self.a)
        self.assertTrue(file_routes.structure_request(self.pa.id, "0", self.a)["ok"])
        self.assertEqual(file_routes.structure_request(self.pa.id, "0", self.a).status_code, 409)   # on its way
        self.assertEqual(file_routes.structure_state(self.pa.id, self.a)["status"], "queued")
        self.answer(f'<move id="{self.manual.id}" to="Heizung"/>')
        seen = file_routes.structure_state(self.pa.id, self.a)
        self.assertEqual((seen["status"], seen["moved"], seen["folders"]), ("done", 1, 1))
        self.assertIn({"depth": 1, "name": "manual.txt", "kind": "text", "label": "documents", "moved": True,
                       "new": False}, seen["nodes"])
        for call in (file_routes.structure_request(self.pa.id, "0", self.b), file_routes.structure_state(self.pa.id, self.b),
                     file_routes.structure_apply(self.pa.id, self.b), file_routes.structure_discard(self.pa.id, self.b)):
            self.assertEqual(call.status_code, 404)
        self.assertEqual(file_routes.structure_apply(self.pa.id, self.a)["moved"], 1)
        self.assertEqual(file_routes.structure_apply(self.pa.id, self.a).status_code, 404)

    def test_the_circles_of_the_explorer_and_the_dialog(self):
        for lang in ("de", "en"):
            tile = managerpage._files_tile(lang, files.list_files(self.a.id, self.pa.id))
            self.assertIn('id="file-tidy"', tile)
            self.assertIn('class="icon-button m-add file-full-only" id="file-folder-add"', tile)
            dialog = managerpage.dialogs(lang)
            self.assertIn('id="file-tidy-dialog"', dialog)
            self.assertIn(i18n.t(lang, "tidy_contents"), dialog)
            self.assertIn("info-dot", dialog)
            self.assertIn('data-fail-timeout="', dialog)     # the dialog reads its texts from these attributes
            self.assertNotIn("%t.", dialog)
            tag = dialog[dialog.index('id="file-tidy-dialog"'):].split(">", 1)[0]
            self.assertNotIn("data-close=", tag)   # core.js would close the dialog on every click inside it
