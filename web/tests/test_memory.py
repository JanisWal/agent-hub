"""The manager's memory and files (memory.py) and how the chat uses them."""
import unittest
from pathlib import Path

from app import chat, db, files, i18n, memory
from app.routes import chat as chat_routes
from tests.test_chat import Base


class ParseTest(unittest.TestCase):
    def test_a_memory_block_is_cut_out_of_the_answer(self):
        parsed = memory.parse_answer("Done.\n\n<memory>\n# Status\nAll fine\n</memory>")
        self.assertEqual((parsed.text, parsed.memory, parsed.reads), ("Done.", "# Status\nAll fine", []))

    def test_the_last_block_wins_and_an_empty_one_is_ignored(self):
        self.assertEqual(memory.parse_answer("<memory>a</memory> and <memory>b</memory>").memory, "b")
        self.assertIsNone(memory.parse_answer("<memory>   </memory>").memory)
        self.assertIsNone(memory.parse_answer("no tags").memory)

    def test_requested_files_are_listed_once_and_at_most_three(self):
        parsed = memory.parse_answer("<read>a.md</read><read> A.MD </read><read>b.txt</read><read>c</read><read>d</read>")
        self.assertEqual(parsed.reads, ["a.md", "b.txt", "c"])
        self.assertEqual(parsed.text, "")


class MemoryBase(Base):
    def setUp(self):
        super().setUp()
        self.original = (files.FILES_DIR, files.free_bytes)
        files.FILES_DIR = Path(self.tmp.name) / "files"
        files.free_bytes = lambda: 10 * 1024 ** 3
        self.connect(self.a)

    def tearDown(self):
        files.FILES_DIR, files.free_bytes = self.original
        super().tearDown()

    def put(self, user, project, name, data=b"x"):
        item = files.start_upload(user.id, project.id, name, len(data))
        if data:
            files.append_chunk(user.id, item.id, 0, data)
        return files.finish_upload(user.id, item.id)

    def ask(self, text="Question?"):
        chat.send(self.a.id, self.pa.id, text)
        return chat.claim_next()

    def stored(self):
        with db.connect() as conn:
            return dict(conn.execute("SELECT * FROM chat_messages ORDER BY id DESC LIMIT 1").fetchone())


class MemoryTest(MemoryBase):
    def test_every_question_carries_the_memory_and_a_list_of_the_other_files(self):
        text = self.ask().prompt
        self.assertIn('<memory file="MEMORY.md">\n(none yet', text)
        self.assertIn("<files>\n(no other files yet)\n</files>", text)
        chat.finish(self.stored()["id"], True, "ok")
        self.put(self.a, self.pa, "MEMORY.md", b"# Status\nHeater works")
        self.put(self.a, self.pa, "notes.md", b"abc")
        self.put(self.a, self.pa, "scan.pdf", b"abc")
        self.put(self.a, self.pa, "wiring.ino", b"abc")
        files.add_link(self.a.id, self.pa.id, "https://docs.example.com/relay", "Relay guide")
        text = self.ask("Next?").prompt
        self.assertIn('<memory file="MEMORY.md">\n# Status\nHeater works\n</memory>', text)
        listing = text[text.index("<files>\n"):text.index("</files>\n")]       # the rules also name the tags
        self.assertIn("- notes.md (memory, 3 bytes)", listing)
        self.assertIn("- wiring.ino (code, 3 bytes)", listing)
        self.assertIn("- scan.pdf (documents, 3 bytes, not text: you can not open it)", listing)
        self.assertIn("- Relay guide: https://docs.example.com/relay (link, a source)", listing)
        self.assertNotIn("MEMORY.md", listing)                                   # it is already above
        project = text[text.index("<project>"):text.index("</project>")]
        self.assertNotIn("Heater works", project)                                # not part of the cut context
        self.assertTrue(text.endswith("Question of the user:\nNext?"))
        self.assertIn("<memory>", chat.MEMORY_RULES)
        self.assertIn("<read>", chat.MEMORY_RULES)

    def test_a_long_memory_file_is_cut(self):
        self.put(self.a, self.pa, "MEMORY.md", b"line\n" * 8000)
        text = self.ask().prompt
        start = text.index('<memory file="MEMORY.md">')
        block = text[start:text.index("</memory>", start)]
        self.assertLessEqual(len(block), memory.MAX_MEMORY + 100)
        self.assertIn(" …", block)

    def test_an_answer_with_a_memory_block_updates_the_file_and_the_block_is_not_shown(self):
        job = self.ask()
        self.assertTrue(chat.finish(job.chat_id, True, "Done.\n<memory>\n# Status\nNew state\n</memory>", 5, 2))
        shown = chat.list_messages(self.a.id, self.pa.id)[-1]
        self.assertEqual((shown.answer, shown.memory_saved), ("Done.", True))
        stored = files.list_files(self.a.id, self.pa.id)
        self.assertEqual([(f.name, f.category, f.editable) for f in stored], [("MEMORY.md", "memory", True)])
        self.assertEqual(files.read_text(self.a.id, stored[0].id), "# Status\nNew state\n")
        again = self.ask("Next?").prompt                                         # the next question reads it
        self.assertIn("# Status\nNew state", again)
        chat.finish(self.stored()["id"], True, "Ok.\n<memory>\n# Status\nNewer\n</memory>")
        stored = files.list_files(self.a.id, self.pa.id)
        self.assertEqual(len(stored), 1)                                         # replaced, not made twice
        self.assertEqual(files.read_text(self.a.id, stored[0].id), "# Status\nNewer\n")

    def test_the_user_can_edit_the_memory_file_and_the_manager_reads_the_change(self):
        item = self.put(self.a, self.pa, "MEMORY.md", b"# Status\nOld")
        files.write_text(self.a.id, item.id, "# Status\nEdited by hand")
        self.assertIn("Edited by hand", self.ask().prompt)

    def test_a_memory_that_is_too_long_is_cut_at_a_line_end(self):
        text = "\n".join(f"line {n}" for n in range(5000))
        self.assertTrue(memory.save_memory(self.a.id, self.pa.id, text))
        saved = files.read_text(self.a.id, files.list_files(self.a.id, self.pa.id)[0].id)
        self.assertLessEqual(len(saved), memory.MAX_MEMORY + 1)
        self.assertTrue(saved.rstrip().rsplit("\n", 1)[-1].startswith("line "))
        self.assertTrue(saved.endswith("\n") and not saved.rstrip().endswith("line 49"[:0] + " "))

    def test_a_memory_row_whose_file_is_gone_does_not_block_saving(self):
        item = self.put(self.a, self.pa, "MEMORY.md", b"# Status\nOld")
        files.path_of(self.pa.id, item.id).unlink()              # the file vanished, the row is still there
        self.assertTrue(memory.save_memory(self.a.id, self.pa.id, "# Status\nNew"))
        stored = files.list_files(self.a.id, self.pa.id)
        self.assertEqual(len(stored), 1)
        self.assertEqual(files.read_text(self.a.id, stored[0].id), "# Status\nNew\n")

    def test_a_failed_answer_saves_nothing_and_keeps_its_reason(self):
        job = self.ask()
        chat.finish(job.chat_id, False, "<memory>planted</memory> boom")
        self.assertEqual(files.list_files(self.a.id, self.pa.id), [])
        self.assertEqual(chat.list_messages(self.a.id, self.pa.id)[-1].answer, "<memory>planted</memory> boom")

    def test_a_requested_file_is_sent_with_the_same_question_again(self):
        self.put(self.a, self.pa, "guide.md", b"# How to wire\nUse 1.5 mm2")
        job = self.ask("How do I wire it?")
        self.assertNotIn("requested-files", job.prompt)
        self.assertTrue(chat.finish(job.chat_id, True, "<read>guide.md</read>", 10, 5))
        self.assertEqual(chat.list_messages(self.a.id, self.pa.id)[-1].status, "queued")   # the user sees: still answering
        second = chat.claim_next()
        self.assertEqual(second.chat_id, job.chat_id)
        self.assertIn('<requested-files>\n<file name="guide.md">\n# How to wire\nUse 1.5 mm2\n</file>', second.prompt)
        self.assertTrue(second.prompt.endswith("Question of the user:\nHow do I wire it?"))
        self.assertTrue(chat.finish(second.chat_id, True, "Use 1.5 mm2.", 20, 7))
        shown = chat.list_messages(self.a.id, self.pa.id)[-1]
        self.assertEqual((shown.status, shown.answer), ("done", "Use 1.5 mm2."))
        stored = self.stored()
        self.assertEqual((stored["tokens_in"], stored["tokens_out"], stored["rounds"]), (30, 12, 1))   # all rounds counted

    def test_asking_for_files_is_limited(self):
        self.put(self.a, self.pa, "a.md", b"A")
        job = self.ask()
        for _ in range(memory.READ_ROUNDS):
            self.assertTrue(chat.finish(job.chat_id, True, "<read>a.md</read>"))
            job = chat.claim_next()
        self.assertTrue(chat.finish(job.chat_id, True, "Final <read>a.md</read>"))     # no more rounds: the answer stands
        shown = chat.list_messages(self.a.id, self.pa.id)[-1]
        self.assertEqual((shown.status, shown.answer), ("done", "Final"))

    def test_a_requested_name_that_is_not_readable_is_said_so_and_other_projects_are_never_read(self):
        self.put(self.a, self.pa, "scan.pdf", b"%PDF")
        self.put(self.b, self.pb, "secret.md", b"SECRET OF B")
        job = self.ask()
        chat.finish(job.chat_id, True, "<read>scan.pdf</read><read>missing.md</read><read>secret.md</read>")
        text = chat.claim_next().prompt
        self.assertIn('<file name="scan.pdf">\n(this file is not text or too large to open here)\n</file>', text)
        self.assertIn('<file name="missing.md">\n(there is no such file in this project)\n</file>', text)
        self.assertIn('<file name="secret.md">\n(there is no such file in this project)\n</file>', text)
        self.assertNotIn("SECRET OF B", text)

    def test_names_do_not_care_for_capital_letters_and_a_big_file_is_cut(self):
        self.put(self.a, self.pa, "Guide.MD", b"word " * 20000)
        with db.connect() as conn:
            block = memory.contents(conn, self.a.id, self.pa.id, ["guide.md"])
        self.assertLessEqual(len(block), memory.MAX_FILE_CHARS + 100)
        self.assertIn(" …", block)

    def test_the_routes_tell_that_the_memory_was_updated(self):
        job = self.ask()
        chat.finish(job.chat_id, True, "Done.<memory>\n# Status\nx\n</memory>")
        messages = chat_routes.messages(self.pa.id, self.a)["messages"]
        self.assertTrue(messages[-1]["memory"])
        self.assertEqual(messages[-1]["answer"], "Done.")

    def test_the_note_has_a_text_in_both_languages(self):
        for lang in ("de", "en"):
            self.assertNotEqual(i18n.t(lang, "chat_memory_saved"), "chat_memory_saved")


if __name__ == "__main__":
    unittest.main()
