"""The manager's memory and files (memory.py) and how the chat uses them."""
import unittest
from pathlib import Path
from unittest import mock

from app import catalog, chat, db, files, i18n, memory, projects, prompts
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


class MemoryFolderTest(MemoryBase):
    """Janis, 14.11.2026: fixed memory files per project, all given to whatever AI answers, any of them kept up."""

    def test_the_fixed_files_are_made_once(self):
        self.assertEqual(memory.ensure_skeleton(self.a.id, self.pa.id, "de"), 5)
        names = sorted(f.name for f in files.list_files(self.a.id, self.pa.id))
        self.assertEqual(names, ["ARCHIVE.md", "MEMORY.md", "PROJECT.md", "ROADMAP.md", "RULES.md"])   # English names
        self.assertTrue(all(f.category == "memory" for f in files.list_files(self.a.id, self.pa.id)))
        roadmap = next(f for f in files.list_files(self.a.id, self.pa.id) if f.name == "ROADMAP.md")
        files.delete(self.a.id, roadmap.id)
        self.assertEqual(memory.ensure_skeleton(self.a.id, self.pa.id, "de"), 0)       # a deleted one stays gone
        self.assertEqual(memory.ensure_skeleton(self.b.id, self.pa.id, "de"), 0)       # never in someone else's project

    def test_a_file_of_the_same_name_with_another_label_is_never_written(self):
        """Janis, 16.11.2026: the manager writes only to the memory files; a manual elsewhere stays as it is."""
        manual = self.put(self.a, self.pa, "anleitung.md", b"# Relais\nOriginal")
        files.update(self.a.id, manual.id, "anleitung.md", category="documents")
        self.assertFalse(memory.save_memory(self.a.id, self.pa.id, "# Neu", "anleitung.md"))   # its name at the top: no
        self.assertEqual(files.read_text(self.a.id, manual.id), "# Relais\nOriginal")
        files.move(self.a.id, self.pa.id, [manual.id], files.create_folder(self.a.id, self.pa.id, "Docs").id)
        self.assertTrue(memory.save_memory(self.a.id, self.pa.id, "# Neu", "anleitung.md"))
        stored = {(f.name, f.category): f for f in files.list_files(self.a.id, self.pa.id)}
        self.assertEqual(files.read_text(self.a.id, stored[("anleitung.md", "documents")].id), "# Relais\nOriginal")
        self.assertEqual(files.read_text(self.a.id, stored[("anleitung.md", "memory")].id), "# Neu\n")
        with db.connect() as conn:   # asked for with <read>, the manual itself still comes
            self.assertIn("Original", memory.contents(conn, self.a.id, self.pa.id, ["anleitung.md"]))
            self.assertNotIn("Original", memory.inline(conn, self.a.id, self.pa.id))   # but never by itself

    def test_english_names_and_an_existing_memory_stays(self):
        self.put(self.a, self.pa, "MEMORY.md", b"# Status\nmine")
        self.assertEqual(memory.ensure_skeleton(self.a.id, self.pa.id, "en"), 4)
        names = sorted(f.name for f in files.list_files(self.a.id, self.pa.id))
        self.assertEqual(names, ["ARCHIVE.md", "MEMORY.md", "PROJECT.md", "ROADMAP.md", "RULES.md"])
        memo = next(f for f in files.list_files(self.a.id, self.pa.id) if f.name == "MEMORY.md")
        self.assertEqual(files.read_text(self.a.id, memo.id), "# Status\nmine")

    def test_the_manager_keeps_any_memory_file(self):
        memory.ensure_skeleton(self.a.id, self.pa.id, "de")
        job = self.ask()
        self.assertIn('<file name="ROADMAP.md">', job.prompt)
        answer = ("Done.\n<memory># Stand\nok</memory>\n<memory file=\"ROADMAP.md\"># Als Nächstes\nRelais</memory>\n"
                  "<memory file=\"HARDWARE.md\"># Teile\n12 V</memory><memory file=\"../evil.md\">x</memory>"
                  "<memory file=\"script.sh\">x</memory>")
        self.assertTrue(chat.finish(job.chat_id, True, answer))
        texts = {f.name: files.read_text(self.a.id, f.id) for f in files.list_files(self.a.id, self.pa.id)}
        self.assertEqual(texts["ROADMAP.md"], "# Als Nächstes\nRelais\n")
        self.assertEqual(texts["HARDWARE.md"], "# Teile\n12 V\n")                        # a new one it found useful
        self.assertEqual(texts["MEMORY.md"], "# Stand\nok\n")
        self.assertNotIn("script.sh", texts)
        self.assertFalse(any("evil" in name for name in texts))
        self.assertEqual(chat.list_messages(self.a.id, self.pa.id)[-1].answer, "Done.")


class ArchiveTest(MemoryBase):
    """Janis, 15.11.2026: ARCHIVE.md keeps what once existed, was dropped or changed, and why. It only grows."""

    def text(self, name="ARCHIVE.md"):
        return next(files.read_text(self.a.id, f.id) for f in files.list_files(self.a.id, self.pa.id) if f.name == name)

    def test_older_projects_get_the_archive_once(self):
        with db.connect() as conn:                       # a project seeded before the archive existed
            conn.execute("UPDATE projects SET memory_seeded = 1 WHERE id = ?", (self.pa.id,))
        self.put(self.a, self.pa, "MEMORY.md", b"# Stand\nmine")
        self.assertEqual(memory.ensure_skeleton(self.a.id, self.pa.id, "de"), 1)
        self.assertEqual(sorted(f.name for f in files.list_files(self.a.id, self.pa.id)), ["ARCHIVE.md", "MEMORY.md"])
        self.assertIn("# Archiv", self.text())
        archive = next(f for f in files.list_files(self.a.id, self.pa.id) if f.name == "ARCHIVE.md")
        files.delete(self.a.id, archive.id)
        self.assertEqual(memory.ensure_skeleton(self.a.id, self.pa.id, "de"), 0)      # deleted by the user: stays gone

    def test_the_manager_only_adds_with_the_date_and_never_replaces(self):
        memory.ensure_skeleton(self.a.id, self.pa.id, "de")
        job = self.ask()
        self.assertIn('<file name="ARCHIVE.md" size=', job.prompt)                 # only named: it only grows
        self.assertIn("is added to the history under today's date", job.prompt)   # the rule says how it works
        self.assertTrue(chat.finish(job.chat_id, True,
                                    'Ok.<memory file="ARCHIVE.md">- Verworfen: eigene Websuche. Grund: Struktur</memory>'))
        self.assertTrue(memory.save_memory(self.a.id, self.pa.id, "# Archiv\n(alles weg)", "ARCHIVE.md"))
        text = self.text()
        self.assertTrue(text.startswith("# Archiv\n\nWas es einmal gab"))                # the start is still there
        self.assertIn("- Verworfen: eigene Websuche. Grund: Struktur", text)          # the first entry too
        self.assertRegex(text, r"\n## \d{4}-\d{2}-\d{2}\n- Verworfen")
        self.assertTrue(text.rstrip().endswith("(alles weg)"))                         # a "rewrite" is only added

    def test_a_date_the_ai_wrote_itself_is_not_doubled(self):
        self.assertTrue(memory._append_archive(self.a.id, self.pa.id, "## 2026-11-14\n\n## 2026-11-15\n## Task\n- x",
                                               today="2026-11-15"))
        self.assertEqual(self.text(), "## 2026-11-15\n## Task\n- x\n")

    def test_without_a_file_it_is_made_and_it_stops_at_its_size(self):
        self.assertTrue(memory._append_archive(self.a.id, self.pa.id, "- first", today="2026-11-15"))
        self.assertEqual(self.text(), "## 2026-11-15\n- first\n")
        with mock.patch.object(memory, "MAX_ARCHIVE", len(self.text()) + 10):
            self.assertFalse(memory.save_memory(self.a.id, self.pa.id, "- far too long " * 5, "ARCHIVE.md"))
        self.assertEqual(self.text(), "## 2026-11-15\n- first\n")                    # nothing changed
        self.assertFalse(memory._append_archive(self.b.id, self.pa.id, "- planted"))   # never in someone else's project

    def test_the_archive_is_only_named_and_the_others_while_the_budget_lasts(self):
        self.put(self.a, self.pa, "ARCHIVE.md", b"# Archiv\n- old entry\n")
        self.put(self.a, self.pa, "MEMORY.md", ("# Stand\n" + "s" * 9000).encode())
        self.put(self.a, self.pa, "PROJECT.md", b"# Ziel\nHeizung")
        self.put(self.a, self.pa, "ROADMAP.md", ("# Als Nächstes\n" + "r" * memory.MAX_INLINE).encode())
        with db.connect() as conn:
            text = memory.inline(conn, self.a.id, self.pa.id)
            asking = memory.inline(conn, self.a.id, self.pa.id, can_open=False)
            rules_only = memory.inline(conn, self.a.id, self.pa.id, only=("PROJECT.md",))
        self.assertIn("s" * 9000, text)                                          # MEMORY.md always whole
        self.assertNotIn("old entry", text)                                      # the history never comes by itself
        self.assertIn('<file name="ARCHIVE.md" size=', text)
        self.assertIn("# Ziel\nHeizung", text)
        self.assertIn('<file name="ROADMAP.md" size=', text)                     # beyond the budget: named
        self.assertIn("open it in /files", text)
        self.assertIn("ask for it with <read>", asking)
        self.assertEqual(rules_only, '<file name="PROJECT.md">\n# Ziel\nHeizung\n</file>')

    def test_german_names_of_older_projects_become_english_once(self):
        from app import db as hubdb
        old = self.put(self.a, self.pa, "REGELN.md", b"# Design\ndunkel")
        self.put(self.a, self.pa, "PROJEKT.md", b"# Ziel")
        self.put(self.a, self.pa, "PROJECT.md", b"# Goal")                     # the English name is taken: stays
        with db.connect() as conn:
            conn.execute("DELETE FROM server_settings WHERE key = 'done.memory_names'")
        hubdb._ready.clear()
        with db.connect() as conn:
            names = sorted(r["name"] for r in conn.execute("SELECT name FROM files WHERE project_id = ?", (self.pa.id,)))
        self.assertEqual(names, ["PROJECT.md", "PROJEKT.md", "RULES.md"])
        self.assertEqual(files.read_text(self.a.id, old.id), "# Design\ndunkel")


class MemoryTest(MemoryBase):
    def test_every_question_carries_the_memory_and_an_ai_with_tools_opens_the_rest(self):
        text = self.ask().prompt
        self.assertIn('<memory>\n(empty', text)
        self.assertNotIn("<files>", text)                                        # /files/INDEX.md lists them
        self.assertNotIn("<read>", text)                                         # it opens files itself
        self.assertIn(prompts.FILES_OPEN, text)
        self.assertNotIn(prompts.DEVICES, text)                                  # no devices: no device rule
        self.assertNotIn("Regular checks", text)                                 # nothing there: not mentioned
        chat.finish(self.stored()["id"], True, "ok")
        self.put(self.a, self.pa, "MEMORY.md", b"# Status\nHeater works")
        self.put(self.a, self.pa, "notes.md", b"abc")
        text = self.ask("Next?").prompt
        self.assertIn('<file name="MEMORY.md">\n# Status\nHeater works\n</file>', text)
        self.assertIn('<file name="notes.md">\nabc\n</file>', text)
        self.assertLess(text.index("<memory>"), text.index("<project>"))         # the steadier part first (cache)
        project = text[text.index("<project>"):text.index("</project>")]
        self.assertNotIn("Heater works", project)
        self.assertTrue(text.endswith("Question of the user:\nNext?"))

    def test_an_ai_that_can_not_open_files_gets_the_list_and_read(self):
        seed = dict(catalog.SEED["claude"], tools={t: "none" for t in catalog.TOOLS})
        catalog.store("claude", seed)
        self.put(self.a, self.pa, "MEMORY.md", b"# Status\nHeater works")
        self.put(self.a, self.pa, "notes.md", b"abc")
        self.put(self.a, self.pa, "scan.pdf", b"abc")
        self.put(self.a, self.pa, "wiring.ino", b"abc")
        files.add_link(self.a.id, self.pa.id, "https://docs.example.com/relay", "Relay guide")
        text = self.ask("Next?").prompt
        self.assertIn(prompts.FILES_ASK, text)
        self.assertIn(prompts.BRIEF, text)                                       # it is told it has no tools
        listing = text[text.index("<files>\n"):text.index("</files>\n")]
        self.assertNotIn("notes.md", listing)                                    # it is in the memory folder
        self.assertIn("- wiring.ino (code, 3 bytes)", listing)
        self.assertIn("- scan.pdf (documents, 3 bytes, not text: you can not open it)", listing)
        self.assertIn("- Relay guide: https://docs.example.com/relay (link, a source)", listing)
        self.assertNotIn("MEMORY.md", listing)                                   # it is already above

    def test_a_long_memory_file_is_cut(self):
        self.put(self.a, self.pa, "MEMORY.md", b"line\n" * 8000)
        text = self.ask().prompt
        start = text.index('<file name="MEMORY.md">')
        block = text[start:text.index("</file>", start)]
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


class EditParseTest(unittest.TestCase):
    """Janis, 16.11.2026: targeted changes instead of the whole text; by section since 20.11.2026."""

    def test_sections_appends_and_line_breaks_inside_the_tags(self):
        parsed = memory.parse_answer(
            'Done.\n<memory-edit file="MEMORY.md">\n<section title=" Stand ">\n- b\n</section>'
            '<append>- c</append></memory-edit>')
        self.assertEqual(parsed.text, "Done.")
        self.assertEqual(parsed.edits, [memory.Edit("MEMORY.md", [("Stand", "- b"), (None, "- c")])])

    def test_at_most_three_blocks(self):
        answer = "".join(f'<memory-edit file="F{n}.md"><section title="x">y</section></memory-edit>' for n in range(5))
        parsed = memory.parse_answer(answer)
        self.assertEqual([e.file for e in parsed.edits], ["F0.md", "F1.md", "F2.md"])
        self.assertEqual(parsed.text, "")


class EditTest(MemoryBase):
    def setUp(self):
        super().setUp()
        memory.ensure_skeleton(self.a.id, self.pa.id, "de")
        self.memo = self.file("MEMORY.md")
        files.write_text(self.a.id, self.memo.id, "# Stand\n- Heizung: offen\n- Licht: offen\n\n## Teile\n- Relais\n\n"
                                                  "# Offene Fragen\n- 12 V?\n")

    def file(self, name):
        return next(f for f in files.list_files(self.a.id, self.pa.id) if f.name == name)

    def text(self, name="MEMORY.md"):
        return files.read_text(self.a.id, self.file(name).id)

    def edit(self, *changes, name="MEMORY.md", user=None):
        return memory.apply_edits((user or self.a).id, self.pa.id, [memory.Edit(name, list(changes))])

    def test_a_section_replaces_only_its_part_and_keeps_the_old_text_as_a_version(self):
        [result] = self.edit(("Stand", "- Heizung: 30-A-Relais\n- Licht: offen"), (None, "- Neu"))
        self.assertTrue(result.ok)
        self.assertEqual(self.text(), "# Stand\n- Heizung: 30-A-Relais\n- Licht: offen\n\n# Offene Fragen\n- 12 V?\n\n- Neu\n")
        [version] = memory.versions(self.a.id, self.pa.id)
        self.assertEqual((version.name, version.author), ("MEMORY.md", "manager"))
        self.assertIn("- Heizung: offen", memory.version_text(self.a.id, version.id))

    def test_a_sub_section_a_repeated_heading_and_a_new_heading(self):
        self.assertTrue(self.edit(("## Teile", "## Teile\n- Relais 30 A"))[0].ok)   # the AI repeated the heading
        self.assertIn("## Teile\n- Relais 30 A\n\n# Offene Fragen", self.text())
        self.assertIn("# Stand\n- Heizung: offen", self.text())                   # the section above stays
        self.assertTrue(self.edit(("Entscheidungen", "- Relais statt MOSFET"))[0].ok)
        self.assertTrue(self.text().endswith("# Entscheidungen\n- Relais statt MOSFET\n"))   # added at the end

    def test_a_block_that_does_not_fit_changes_nothing_at_all(self):
        files.write_text(self.a.id, self.memo.id, "# Stand\n- a\n# Stand\n- b\n")
        before = self.text()
        self.assertEqual(self.edit(("Neu", "x"), ("Stand", "y"))[0].reason, "not_unique")
        self.assertEqual(self.edit((" ", "x"))[0].reason, "empty")
        self.assertEqual(self.text(), before)                              # all or nothing
        self.assertEqual(memory.versions(self.a.id, self.pa.id), [])

    def test_the_archive_unknown_and_foreign_files_are_never_edited(self):
        self.assertEqual(self.edit(("Archiv", "x"), name="ARCHIVE.md")[0].reason, "archive")
        self.assertEqual(self.edit(("a", "b"), name="FEHLT.md")[0].reason, "not_found")
        self.assertEqual(self.edit(("a", "b"), name="../x.md")[0].reason, "bad_name")
        self.assertFalse(self.edit(("Stand", "x"), user=self.b)[0].ok)   # B: not his project
        self.assertIn("- Heizung: offen", self.text())

    def test_only_the_newest_versions_stay_and_restoring_loses_nothing(self):
        for n in range(memory.MAX_VERSIONS + 3):
            memory.save_memory(self.a.id, self.pa.id, f"# Stand {n}")
        listed = memory.versions(self.a.id, self.pa.id)
        self.assertEqual(len(listed), memory.MAX_VERSIONS)
        oldest = listed[-1]
        self.assertEqual(memory.version_text(self.a.id, oldest.id), "# Stand 2\n")   # the start text and Stand 0, 1 fell out
        self.assertIsNone(memory.version_text(self.b.id, oldest.id))          # never someone else's
        self.assertIsNone(memory.restore(self.b.id, oldest.id))
        self.assertEqual(memory.restore(self.a.id, oldest.id), self.pa.id)
        self.assertEqual(self.text(), "# Stand 2\n")
        newest = memory.versions(self.a.id, self.pa.id)[0]
        self.assertEqual((memory.version_text(self.a.id, newest.id), newest.author), (f"# Stand {memory.MAX_VERSIONS + 2}\n", "user"))

    def test_the_users_own_save_keeps_a_version_and_deleting_the_project_removes_them(self):
        self.assertTrue(memory.write_by_user(self.a.id, self.memo.id, "# Von Hand\n"))
        self.assertEqual(memory.versions(self.a.id, self.pa.id)[0].author, "user")
        self.assertTrue(projects.delete_project(self.a.id, self.pa.id))
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_versions").fetchone()[0], 0)

    def test_the_chat_asks_again_when_an_edit_does_not_fit_and_then_saves_it(self):
        job = self.ask()
        self.assertIn("<memory-edit", job.prompt)                               # the rules explain the format
        files.write_text(self.a.id, self.memo.id, "# Stand\n- a\n# Stand\n- b\n")
        bad = 'Ok.<memory-edit file="MEMORY.md"><section title="Stand">x</section></memory-edit>'
        self.assertTrue(chat.finish(job.chat_id, True, bad))
        second = chat.claim_next()
        self.assertEqual(second.chat_id, job.chat_id)
        self.assertIn('<edit-failed file="MEMORY.md">that heading stands more than once', second.prompt)
        good = 'Erledigt.<memory file="MEMORY.md"># Stand\n- Heizung: fertig</memory>'
        self.assertTrue(chat.finish(second.chat_id, True, good))
        shown = chat.list_messages(self.a.id, self.pa.id)[-1]
        self.assertEqual((shown.answer, shown.memory_saved), ("Erledigt.", True))
        self.assertIn("- Heizung: fertig", self.text())


class AgentFilesTest(MemoryBase):
    """Janis, 16.11.2026: the user's files go to every chat and run as a list; the runner mounts them read-only."""

    def test_the_chat_job_names_the_files_and_links_of_its_project_only(self):
        manual = self.put(self.a, self.pa, "Anleitung.pdf", b"%PDF")
        files.add_link(self.a.id, self.pa.id, "https://example.com/guide", "Guide")
        gone = self.put(self.a, self.pa, "alt.png", b"x")
        files.delete(self.a.id, gone.id)                                          # in the trash: not given
        self.put(self.b, self.pb, "secret-of-b.pdf", b"SECRET")
        job = self.ask()
        self.assertEqual(job.project_id, self.pa.id)
        self.assertEqual(job.files, [{"id": manual.id, "name": "Anleitung.pdf", "area": "documents", "size": 4, "path": []}])
        self.assertEqual(job.links, [{"name": "Guide", "url": "https://example.com/guide", "path": []}])
        self.assertIn("/files", job.prompt)
        self.assertIn("/code", job.prompt)
        with db.connect() as conn:
            self.assertEqual(files.for_agents(conn, self.b.id, self.pa.id), ([], []))   # never someone else's
