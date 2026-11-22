"""From the manager chat to the programmer (Janis, 19.11.2026): the manager splits a wish into short bullets with the
context behind them, they go on the board and start by themselves one after the other; what the manager or an agent
adds on its own waits for the user's yes (a bug excepted)."""
import os
import tempfile
import unittest

from app import agents, board, chat, claude_link, db, projectpage, projects, reply, statusnote, users

WISH = (
    'Gern, ich habe es aufgeteilt.\n'
    '<task kind="major" title="Heizung per Zeitplan" from="user">Ein Zeitplan je Wochentag, gespeichert in plan.json.\n'
    'Fertig, wenn der Test test_plan grün ist.</task>\n'
    '<task kind="minor" title="Temperatur in der Anzeige runden" from="user">Eine Nachkommastelle.</task>\n'
    '<task kind="minor" title="Dunkler Modus für die Anzeige" from="idea">Wäre nachts angenehmer.</task>\n'
    '<task kind="bug" title="Relais klickt doppelt">Beim Einschalten zweimal.</task>\n'
    '<task kind="minor" title="Temperatur in der Anzeige runden" from="user">doppelt</task>'
)


class ManagerBoardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.a = users.create_user("a@example.com", "Aaaa!pass12")
        self.b = users.create_user("b@example.com", "Bbbb!pass12")
        self.pa = projects.create_project(self.a.id, "Heizung")
        self.pb = projects.create_project(self.b.id, "Of B")
        statusnote._LAST_SCAN["at"] = 2 ** 40         # no status round in between
        claude_link.begin(self.a.id)
        claude_link.complete(self.a.id, True)

    def tearDown(self):
        self.tmp.cleanup()

    def ask(self, answer):
        chat.send(self.a.id, self.pa.id, "Bau mir bitte die Heizungssteuerung fertig.")
        job = chat.claim_next()
        self.assertTrue(chat.finish(job.chat_id, True, answer))
        return chat.list_messages(self.a.id, self.pa.id)[-1]

    def items(self, user=None, project=None):
        return {i.title: i for i in board.list_items((user or self.a).id, (project or self.pa).id)}

    def test_the_rule_and_reading_the_origin(self):
        chat.send(self.a.id, self.pa.id, "Hallo")
        prompt = chat.claim_next().prompt
        self.assertIn('from="user"', prompt)
        self.assertIn("small pieces", prompt)
        found = reply.parse(WISH).tasks
        self.assertEqual([t.origin for t in found], ["user", "user", "idea", "idea", "user"])   # no `from` = an idea

    def test_the_chat_puts_short_bullets_with_context_on_the_board(self):
        message = self.ask(WISH)
        self.assertNotIn("<task", message.answer)                   # the user reads no tags
        self.assertIn("aufgeteilt", message.answer)
        items = self.items()
        self.assertEqual(len(items), 4)                             # the same bullet twice comes once
        plan = items["Heizung per Zeitplan"]
        self.assertEqual((plan.status, plan.source, plan.auto), ("open", "manager", True))   # asked for: no confirmation
        self.assertIn("plan.json", plan.details)
        idea = items["Dunkler Modus für die Anzeige"]
        self.assertEqual((idea.status, idea.auto), ("proposed", False))                # his own idea waits
        self.assertEqual((items["Relais klickt doppelt"].status, items["Relais klickt doppelt"].auto), ("open", True))
        self.assertEqual(self.items(self.b, self.pb), {})                              # only the question's project

    def test_a_credential_the_server_can_not_read_is_its_own_kind_of_failure(self):
        self.assertEqual(chat.failure_kind("Server: the saved credential can not be read (HUB_TOKEN_KEY)."), "server")
        self.assertEqual(chat.failure_kind("Not logged in: no saved credential. Please run /login"), "auth")

    def test_items_start_by_themselves_one_after_the_other_bugs_first(self):
        self.ask(WISH)
        job = agents.claim_next(can_mac=False)
        self.assertEqual((job.role, job.title), ("programmer", "Relais klickt doppelt"))   # a bug goes first
        self.assertIn("Context (from the manager and the user):\nBeim Einschalten zweimal.", job.prompt)
        self.assertIn("<task kind=", job.prompt)                                        # it may name what it notices
        self.assertIsNone(agents.claim_next(can_mac=False))                            # one task per project at a time
        self.assertEqual(len(agents.tasks_by_item(self.a.id, self.pa.id)), 1)
        # it went through to the user's approval: the project's next item waits until the task is out of the way
        for role, result in (("programmer", "done"), ("tester", "pass"), ("reviewer", "ok")):
            if job is None:
                job = agents.claim_next(can_mac=False)
            self.assertEqual(job.role, role)
            self.assertTrue(agents.finish_run(job.run_id, result, f"Bericht {role}"))
            job = None
        self.assertIsNone(agents.claim_next(can_mac=False))                            # waits for the user
        task = agents.item_task(self.a.id, self.items()["Relais klickt doppelt"].id)
        self.assertTrue(agents.decide(self.a.id, task.id, "cancel"))                     # stopped by the user ...
        job = agents.claim_next(can_mac=False)
        self.assertEqual(job.title, "Temperatur in der Anzeige runden")                # ... the next one comes
        self.assertFalse(self.items()["Relais klickt doppelt"].auto)                    # and the stopped one never again

    def test_an_approval_a_day_later_still_gets_the_managers_documentation(self):
        agents.configure(self.a.id, autonomy="all")   # it waits for the approval (else it merges by itself)
        item = board.create_item(self.a.id, self.pa.id, "minor", "Anzeige bauen")
        start = 1_000_000
        task = agents.start_item(self.a.id, item.id, now=start)
        for result in ("done", "pass", "ok"):
            job = agents.claim_next(can_mac=False, now=start + 60)
            agents.finish_run(job.run_id, result, "Bericht", now=start + 60)
        later = start + 86400                                                   # the user approves the next day
        self.assertTrue(agents.decide(self.a.id, task.id, "approve", now=later))
        with db.connect() as conn:
            conn.execute("UPDATE agent_tasks SET merged = 1 WHERE id = ?", (task.id,))   # the runner merged
        job = agents.claim_next(can_mac=False, now=later + 60)
        self.assertEqual((job.role, agents.get_task(self.a.id, task.id).status), ("chef", "documenting"))

    def test_what_a_run_notices_goes_on_the_board(self):
        item = board.create_item(self.a.id, self.pa.id, "minor", "Anzeige bauen")
        agents.start_item(self.a.id, item.id)
        job = agents.claim_next(can_mac=False)
        report = ("Gebaut.\n<task kind=\"major\" title=\"Helligkeit einstellbar\">Ein Regler wäre gut.</task>\n"
                  "<task kind=\"minor\" title=\"Schrift etwas größer\">gehört zur Aufgabe</task>\n"
                  "<task kind=\"bug\" title=\"Absturz bei leerem Plan\">plan.json leer: KeyError.</task>\nRESULT: done")
        self.assertTrue(agents.finish_run(job.run_id, "done", report))
        items = self.items()
        self.assertEqual((items["Helligkeit einstellbar"].status, items["Helligkeit einstellbar"].source), ("proposed", "agent"))
        self.assertEqual((items["Absturz bei leerem Plan"].status, items["Absturz bei leerem Plan"].auto), ("open", True))
        self.assertNotIn("Schrift etwas größer", items)                          # part of the task: done in it
        stored = agents.task_runs(self.a.id, agents.item_task(self.a.id, item.id).id)[0].report
        self.assertNotIn("<task", stored)
        # the user says yes to the suggestion: it goes to the programmer by itself
        self.assertTrue(board.accept(self.a.id, items["Helligkeit einstellbar"].id))
        self.assertTrue(self.items()["Helligkeit einstellbar"].auto)

    def test_an_item_made_by_hand_starts_by_itself_too(self):
        hand = board.create_item(self.a.id, self.pa.id, "minor", "Von Hand")      # agreed by hand (Janis, 19.11.2026)
        self.assertTrue(hand.auto)
        self.assertEqual(agents.claim_next(can_mac=False).title, "Von Hand")

    def test_the_manager_corrects_an_item_the_programmer_has_not_started(self):
        self.ask(WISH)
        items = self.items()
        chat.send(self.a.id, self.pa.id, "Hmm")
        prompt = chat.claim_next().prompt
        plan = items["Heizung per Zeitplan"]
        self.assertIn(f"- #{plan.id} [major] Heizung per Zeitplan (waiting)", prompt)
        self.assertIn("Dunkler Modus für die Anzeige (suggestion)", prompt)
        job_id = chat.list_messages(self.a.id, self.pa.id)[-1].id
        self.assertTrue(chat.finish(job_id, True, f'Korrigiert.<task-edit id="{plan.id}" kind="minor" title="Zeitplan je Tag">'
                                                  f'Nur Werktage.</task-edit>'))
        fixed = self.items()["Zeitplan je Tag"]
        self.assertEqual((fixed.id, fixed.kind, fixed.details), (plan.id, "minor", "Nur Werktage."))
        self.assertNotIn("<task-edit", chat.list_messages(self.a.id, self.pa.id)[-1].answer)
        # once the programmer has it, it stays as it is, and the user reads why; nothing of another project changes
        started = agents.claim_next(can_mac=False)
        self.assertEqual(started.title, "Relais klickt doppelt")
        self.assertTrue(agents.finish_run(started.run_id, "done", "Gebaut."))   # with the tester now; the slot is free
        bug = self.items()["Relais klickt doppelt"]
        mine = board.create_item(self.b.id, self.pb.id, "bug", "Of B")
        chat.send(self.a.id, self.pa.id, "Doch anders")
        job = chat.claim_next()
        chat.finish(job.chat_id, True, f'<task-edit id="{bug.id}" title="Anders"></task-edit><task-edit id="{mine.id}" title="Planted"></task-edit>')
        self.assertIn("Relais klickt doppelt", self.items())
        self.assertIn("Of B", self.items(self.b, self.pb))
        self.assertIn("2 Punkt(e) waren schon in Arbeit", chat.list_messages(self.a.id, self.pa.id)[-1].answer)

    def test_accepting_a_suggestion_starts_it_at_once(self):
        from app.routes import board as board_routes
        with db.connect() as conn:
            idea = board.add_from_ai(conn, self.pa.id, "minor", "Helligkeit einstellbar", "Ein Regler.", False, "agent")
        self.assertEqual(board_routes.item_action(idea, "accept", user=self.b).status_code, 404)   # not B's
        self.assertEqual(board_routes.item_action(idea, "accept", user=self.a), {"ok": True})
        task = agents.item_task(self.a.id, idea)
        self.assertEqual(task.status, "coding")                              # no second step "give to the agents"

    def test_an_item_by_hand_carries_its_context_and_can_be_changed(self):
        from app.routes import board as board_routes
        board_routes.create_item(self.pa.id, "minor", "Anzeige dimmen", user=self.a, details="Nachts auf 30 %.")
        item = self.items()["Anzeige dimmen"]
        self.assertEqual((item.details, item.auto, item.source), ("Nachts auf 30 %.", True, "user"))
        board_routes.rename_item(item.id, "Anzeige nachts dimmen", user=self.a, details="Zwischen 22 und 6 Uhr.")
        self.assertEqual(self.items()["Anzeige nachts dimmen"].details, "Zwischen 22 und 6 Uhr.")
        board_routes.rename_item(item.id, "Anzeige dimmen", user=self.a, details=None)   # no field: the context stays
        self.assertEqual(self.items()["Anzeige dimmen"].details, "Zwischen 22 und 6 Uhr.")
        board_routes.rename_item(item.id, "Fremd", user=self.b, details="x")
        self.assertIn("Anzeige dimmen", self.items())

    def test_no_ai_no_start_and_nothing_for_a_foreign_project(self):
        self.ask(WISH)
        claude_link.disconnect(self.a.id)
        with db.connect() as conn:
            self.assertEqual(agents.autostart(conn, 0), 0)
        with db.connect() as conn:                     # an AI can never name another project: it comes from the job
            self.assertIsNone(board.add_from_ai(conn, self.pa.id, "nowhere", "X"))
            self.assertIsNone(board.add_from_ai(conn, self.pa.id, "bug", "Heizung per Zeitplan"))   # there already
            self.assertIsNone(board.add_from_ai(conn, self.pa.id, "bug", "X", source="admin"))

    def test_the_programmers_tab_shows_the_task_with_its_context_and_the_parts_to_come(self):
        self.ask(WISH)
        agents.claim_next(can_mac=False)                                       # the bug runs now
        project = projects.get_project(self.a.id, self.pa.id)
        page = projectpage.render(self.a, project, board.list_items(self.a.id, self.pa.id))
        view = page[page.index('id="view-programmer"'):page.index('id="view-tester"')]
        self.assertIn('<p class="p-title">Relais klickt doppelt</p>', view)
        self.assertIn("Beim Einschalten zweimal.", view)                        # the context from the board
        for part in ("Verlauf", "Vorschau", "Code", "Änderungen", "Läufe", "Verbrauch"):
            self.assertIn(f"<h2>{part}</h2>", view)
        self.assertEqual(view.count('class="p-badge"'), 3)                       # the three placeholders (code is real)
        self.assertIn("disabled", view)
        tester = page[page.index('id="view-tester"'):page.index('id="view-reviewer"')]
        self.assertNotIn("p-badge", tester)

    def test_the_card_shows_the_bullet_and_folds_the_context(self):
        self.ask(WISH)
        project = projects.get_project(self.a.id, self.pa.id)
        page = projectpage.render(self.a, project, board.list_items(self.a.id, self.pa.id))
        self.assertIn('<span class="card-text">Heizung per Zeitplan</span>', page)
        self.assertIn("vom Manager", page)
        self.assertIn('<span class="card-details" hidden>Ein Zeitplan je Wochentag', page)
        self.assertIn("Vorschlag · vom Manager", page)                       # a suggestion in the list, marked
        self.assertNotIn("Vorschläge von Claude", page)


if __name__ == "__main__":
    unittest.main()
