"""Each role gets only what it needs (Janis, 20.11.2026): prompts.py builds the packages, the same for every AI."""
import os
import tempfile
import unittest
from pathlib import Path

from app import agents, board, catalog, chat, claude_link, db, files, memory, projects, prompts, statusnote, users

DIFF = ("calc.js | 1 +", "diff --git a/calc.js b/calc.js\n+export const add = (a, b) => a + b;\n")


class PromptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        files.FILES_DIR, old = Path(self.tmp.name) / "files", (files.FILES_DIR, files.free_bytes)
        files.free_bytes = lambda: 10 * 1024 ** 3
        self.addCleanup(lambda: setattr(files, "FILES_DIR", old[0]) or setattr(files, "free_bytes", old[1]))
        self.a = users.create_user("a@example.com", "Aaaa!pass12")
        self.pa = projects.create_project(self.a.id, "Rechner")
        statusnote._LAST_SCAN["at"] = 2 ** 40
        claude_link.begin(self.a.id)
        claude_link.complete(self.a.id, True)
        memory.ensure_skeleton(self.a.id, self.pa.id, "de")
        memory.save_memory(self.a.id, self.pa.id, "# Stand\n- Geheimer Zwischenstand", "MEMORY.md")
        memory.save_memory(self.a.id, self.pa.id, "# Design\n- dunkel, runde Knöpfe", "RULES.md")

    def tearDown(self):
        self.tmp.cleanup()

    def through_programmer(self):
        board.create_item(self.a.id, self.pa.id, "minor", "Addieren")
        job = agents.claim_next(can_mac=False)
        agents.finish_run(job.run_id, "done", "Gebaut.", change=DIFF, committed=True)
        return agents.list_tasks(self.a.id, self.pa.id)[0], job

    def test_the_programmer_gets_the_rules_and_the_task_not_the_memory(self):
        board.create_item(self.a.id, self.pa.id, "minor", "Addieren")
        job = agents.claim_next(can_mac=False)
        self.assertEqual(job.mode, "")
        self.assertIn("runde Knöpfe", job.prompt)
        self.assertNotIn("Geheimer Zwischenstand", job.prompt)
        self.assertNotIn("<memory-edit", job.prompt)                     # no manager markers for the programmer
        self.assertNotIn("<reports>", job.prompt)                         # nothing yet

    def test_the_tester_reads_the_change_and_the_reviewer_answers_without_tools(self):
        self.through_programmer()
        tester = agents.claim_next(can_mac=False)
        self.assertEqual((tester.role, tester.mode), ("tester", ""))
        self.assertIn("+export const add", tester.prompt)
        self.assertNotIn("runde Knöpfe", tester.prompt)
        agents.finish_run(tester.run_id, "pass", "Passt.")
        reviewer = agents.claim_next(can_mac=False)
        self.assertEqual((reviewer.role, reviewer.mode, reviewer.files), ("reviewer", "brief", []))
        self.assertIn(prompts.BRIEF, reviewer.prompt)
        self.assertIn("runde Knöpfe", reviewer.prompt)
        self.assertIn('<report role="tester">\nPasst.', reviewer.prompt)

    def test_a_change_too_big_for_the_package_gives_the_reviewer_his_tools(self):
        board.create_item(self.a.id, self.pa.id, "minor", "Viel")
        job = agents.claim_next(can_mac=False)
        agents.finish_run(job.run_id, "done", "Gebaut.", change=("big", "+x\n" * 30000), committed=True)
        agents.finish_run(agents.claim_next(can_mac=False).run_id, "pass", "ok")
        reviewer = agents.claim_next(can_mac=False)
        self.assertEqual(reviewer.mode, "")
        self.assertIn("read the rest in /work", reviewer.prompt)

    def test_the_documentation_is_brief_and_puts_nothing_on_the_board(self):
        task, _ = self.through_programmer()
        agents.finish_run(agents.claim_next(can_mac=False).run_id, "pass", "ok")
        agents.finish_run(agents.claim_next(can_mac=False).run_id, "ok", "ok")
        agents.merge_done(task.id, True)                                    # no approval: merged after the ok
        chef = agents.claim_next(can_mac=False)
        self.assertEqual((chef.role, chef.mode), ("chef", "brief"))
        self.assertIn("Geheimer Zwischenstand", chef.prompt)                # MEMORY.md and ROADMAP.md to update
        self.assertIn('<file name="ROADMAP.md">', chef.prompt)
        self.assertNotIn("runde Knöpfe", chef.prompt)
        self.assertIn("calc.js | 1 +", chef.prompt)
        self.assertNotIn("+export const add", chef.prompt)                 # only the summary of the change
        report = 'Notiert.<task kind="bug" title="Neuer Fehler">x</task>RESULT: done'
        agents.finish_run(chef.run_id, "done", report)
        self.assertNotIn("Neuer Fehler", [i.title for i in board.list_items(self.a.id, self.pa.id)])

    def test_the_manager_hears_of_devices_only_when_there_are_some(self):
        from app import devices
        chat.send(self.a.id, self.pa.id, "Hallo")
        text = chat.claim_next().prompt
        self.assertNotIn("Devices", text)
        with db.connect() as conn:
            conn.execute("UPDATE chat_messages SET status = 'done'")
        d = devices.create(self.a.id, self.pa.id, "Roadster", "roadster.local")
        with db.connect() as conn:
            conn.execute("UPDATE devices SET ai_actions = 'reboot' WHERE id = ?", (d.id,))
        chat.send(self.a.id, self.pa.id, "Neu starten?")
        text = chat.claim_next().prompt
        self.assertIn(prompts.DEVICES, text)
        self.assertIn("[you may ask for: reboot]", text)

    def test_the_tools_sentence_names_only_what_there_is(self):
        everything = catalog.tools_of("claude")
        self.assertIn("a shell with the public internet", prompts.tools_text(everything, "all"))
        self.assertNotIn("reading web pages", prompts.tools_text(everything, "apart"))
        self.assertEqual(prompts.tools_text(everything, "brief"), prompts.BRIEF)
        self.assertEqual(prompts.tools_text({t: "none" for t in catalog.TOOLS}, "all"), prompts.BRIEF)
        self.assertEqual(catalog.tools_of("mistral")["look"], "hub")
        self.assertEqual(set(catalog.tools_of("nobody").values()), {"none"})
        with self.assertRaises(ValueError):
            catalog.parse("claude", dict(catalog.SEED["claude"], tools={"read": "maybe"}))


if __name__ == "__main__":
    unittest.main()
