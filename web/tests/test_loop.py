"""The agents' loop after the calculator test (Janis, 21.11.2026): what belongs to a task is done in it, a role puts only
bugs outside it and new features on the board, the environment never goes there, repeats are kept once, a task's
questions go with it, and a clean task merges by itself as the manager's autonomy allows."""
import os
import tempfile
import unittest

from app import agents, board, chat, claude_link, db, projects, prompts, questions, reply, statusnote, users
from app.managerpage import _question_row

DIFF = ("calc.js | 2 ++\n 1 file changed", "diff --git a/calc.js b/calc.js\n+export const add = (a, b) => a + b;\n")


class SimilarTest(unittest.TestCase):
    def test_repeats_of_the_calculator_test(self):
        for a, b in (("Anzeige ans Ende scrollen", "app.js: Anzeige ans Ende scrollen"),
                     ("Anzeige bei langer Eingabe ans Ende scrollen", "Anzeige: bei langer Zahl zum Ende scrollen"),
                     ("Node in der Agent-Umgebung bereitstellen", "Node in der Agent-Umgebung installieren"),
                     ("Ziffern und Komma nach % sperren", "Nach % keine Ziffer/Komma zulassen")):
            self.assertTrue(reply.similar(a, b), (a, b))
        for a, b in (("Negative Zahlen per Eingabe ermöglichen", "Taste 0 über zwei Spalten (.wide)"),
                     ("Tastatureingabe", "Rechenlogik calc.js"), ("Login", "Logout"),
                     ("Schritt 1", "Schritt 2"), ("Schritt 1: Grundgerüst", "Schritt 2: Grundgerüst prüfen")):
            self.assertFalse(reply.similar(a, b), (a, b))

    def test_env_marker(self):
        found = reply.parse("Fertig. <env>Kein Browser für die Sichtprüfung</env> <env>Kein Browser für die "
                            "Sichtprüfung</env>\nRESULT: done")
        self.assertEqual(found.envs, ["Kein Browser für die Sichtprüfung"])
        self.assertNotIn("<env>", found.text)

    def test_the_packages_say_it(self):
        self.assertIn("Finish the task well", prompts.ROLES["programmer"])
        self.assertIn("never a board item", prompts.ROLES["tester"])
        self.assertIn("<env>", prompts.FOUND)
        self.assertNotIn("minor", prompts.FOUND)
        self.assertIn("never plan a separate polish", prompts.BOARD)
        self.assertIn("env", prompts.ALLOWED[("programmer", "run")])


class LoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        statusnote._LAST_SCAN["at"] = 2 ** 40
        self.a = users.create_user("a@example.com", "Aaaa!pass12")
        self.pa = projects.create_project(self.a.id, "Rechner")
        claude_link.begin(self.a.id)
        claude_link.complete(self.a.id, True)

    def tearDown(self):
        self.tmp.cleanup()

    def start(self, kind="minor", title="Addieren"):
        item = board.create_item(self.a.id, self.pa.id, kind, title)
        return agents.start_item(self.a.id, item.id)

    def items(self):
        return {i.title: i for i in board.list_items(self.a.id, self.pa.id)}

    def to_review(self, report="Gebaut."):
        job = agents.claim_next(can_mac=False)
        agents.finish_run(job.run_id, "done", report, change=DIFF, tests=(0, "ok 1\n"))
        return agents.claim_next(can_mac=False)

    def test_a_role_puts_only_bugs_and_features_on_the_board_and_the_environment_never(self):
        self.start()
        job = agents.claim_next(can_mac=False)
        agents.finish_run(job.run_id, "done", "Gebaut.\n"
                          '<task kind="minor" title="Anzeige ans Ende scrollen">Feinschliff</task>\n'
                          '<task kind="bug" title="Löschen-Taste leert den Speicher nicht">in memory.js</task>\n'
                          '<task kind="major" title="Verlauf der Rechnungen">eine Liste</task>\n'
                          "<env>Kein Browser für die Sichtprüfung</env>", change=DIFF, tests=(0, "ok\n"))
        items = self.items()
        self.assertNotIn("Anzeige ans Ende scrollen", items)                         # part of the task: done in it
        self.assertEqual(items["Löschen-Taste leert den Speicher nicht"].status, "open")
        self.assertEqual(items["Verlauf der Rechnungen"].status, "proposed")         # waits for the user's yes
        [note] = questions.open_questions(self.a.id, self.pa.id)
        self.assertEqual((note.kind, note.text, note.task_id), ("note", "Kein Browser für die Sichtprüfung", None))
        self.assertIn("Erledigt", _question_row("de", note))
        self.assertNotIn("w-input", _question_row("de", note))
        done = questions.answer(self.a.id, note.id, "ok")
        self.assertEqual(done.status, "delivered")                                   # it goes to no AI

    def test_repeats_add_their_context_to_the_item_there_is(self):
        with db.connect() as conn:
            first = board.add_from_ai(conn, self.pa.id, "bug", "Anzeige ans Ende scrollen", "in app.js", True)
            self.assertIsNone(board.add_from_ai(conn, self.pa.id, "bug", "app.js: Anzeige ans Ende scrollen",
                                                "auch bei Ergebnissen", True))
            details = conn.execute("SELECT details FROM board_items WHERE id = ?", (first,)).fetchone()[0]
        self.assertIn("auch bei Ergebnissen", details)
        self.assertEqual(len(self.items()), 1)

    def test_a_similar_open_question_is_kept_once_and_a_tasks_questions_go_with_it(self):
        task = self.start()
        with db.connect() as conn:
            self.assertIsNotNone(questions.add(conn, self.pa.id, "programmer",
                                               reply.Ask("Soll die %-Taste bleiben?", "text", "small", []), task.id))
            self.assertIsNone(questions.add(conn, self.pa.id, "reviewer",
                                            reply.Ask("Soll die %-Taste bleiben oder weg?", "text", "small", []), task.id))
        agents.decide(self.a.id, task.id, "cancel")
        self.assertEqual(questions.open_questions(self.a.id, self.pa.id), [])

    def test_a_clean_improvement_merges_by_itself(self):
        task = self.start("minor")
        job = self.to_review()
        self.assertEqual(job.role, "reviewer")
        agents.finish_run(job.run_id, "ok", "Keine Einwände.")
        self.assertNotEqual(agents.get_task(self.a.id, task.id).status, "awaiting_approval")   # merged by itself

    def test_a_new_feature_waits(self):
        task = self.start("major", "Verlauf")
        agents.finish_run(self.to_review().run_id, "ok", "Keine Einwände.")
        self.assertEqual(agents.get_task(self.a.id, task.id).status, "awaiting_approval")

    def test_everything_waits_when_the_manager_asks_for_all(self):
        agents.configure(self.a.id, autonomy="all")
        task = self.start("bug", "Minus doppelt")
        agents.finish_run(self.to_review().run_id, "ok", "Keine Einwände.")
        self.assertEqual(agents.get_task(self.a.id, task.id).status, "awaiting_approval")

    def test_red_tests_or_an_open_question_keep_it_waiting(self):
        task = self.start("minor")
        job = self.to_review()
        with db.connect() as conn:
            questions.add(conn, self.pa.id, "reviewer", reply.Ask("Komma oder Punkt?", "text", "small", []), task.id)
        agents.finish_run(job.run_id, "ok", "Keine Einwände.")
        self.assertEqual(agents.get_task(self.a.id, task.id).status, "awaiting_approval")

class ViewerFocusTest(unittest.TestCase):
    def test_the_viewers_take_the_focus_themselves(self):
        from app import managerpage
        for dialog in ('id="file-reader" tabindex="-1" autofocus', 'id="file-viewer" tabindex="-1" autofocus'):
            self.assertIn(dialog, managerpage.FILE_DIALOGS)


class StatusTileTest(LoopTest):
    def test_the_tile_alone_follows_the_board_without_an_ai(self):
        from app.routes import manager as manager_routes
        answer = manager_routes.status_tile(self.pa.id, user=self.a)
        self.assertIn('id="status"', answer["html"])
        self.start()                                                               # a task is under way now
        self.assertIn("<dd>1</dd>", manager_routes.status_tile(self.pa.id, user=self.a)["html"])
        other = users.create_user("o@example.com", "Oooo!pass12")
        self.assertEqual(manager_routes.status_tile(self.pa.id, user=other).status_code, 404)

    def test_the_arrow_turns_and_waits_while_a_status_is_on_its_way(self):
        from app import statusnote
        from app.routes import manager as manager_routes
        self.assertNotIn("spinning", manager_routes.status_tile(self.pa.id, user=self.a)["html"])
        self.start()
        self.assertEqual(statusnote.request(self.a.id, self.pa.id), "queued")
        html = manager_routes.status_tile(self.pa.id, user=self.a)["html"]
        self.assertIn("status-again spinning", html)
        self.assertIn(" disabled", html[html.index('id="status-again"'):html.index('id="status-again"') + 200])


class HoverTest(unittest.TestCase):
    """Nothing that moves under the pointer may leave the pointer behind (Janis, 22.11.2026, the third time): a hover
    rule that shifts an element is allowed only for the cards that keep their hit area while lifted (.file-row)."""
    LIFTED = {".file-row", ".open-list .card", ".tile[data-id]", ".tile.plus"}

    def test_no_hover_moves_a_control(self):
        import glob
        import re
        for path in glob.glob(os.path.join(os.path.dirname(__file__), "..", "app", "static", "*.css")):
            css = open(path).read()
            for selectors, body in re.findall(r"([^{}]*:hover[^{}]*)\{([^}]*)\}", css):
                if not re.search(r"translate\s*:\s*(?!none)|translate[XY]?\(", body):
                    continue
                for selector in selectors.split(","):
                    base = selector.strip().split("\n")[-1].replace(":hover", "").strip()
                    self.assertIn(base, self.LIFTED, f"{os.path.basename(path)}: {selector.strip()} moves under the pointer")
                    self.assertRegex(css, re.escape(base) + r":hover::(after|before)\s*(,[^{]*)?\{[^}]*(inset|top)\s*:\s*-",
                                     f"{base} lifts without keeping its hit area")


class RoleAiTest(LoopTest):
    """The AI of a role, chosen in its tab (Janis, 22.11.2026)."""

    def connect_chatgpt(self):
        from app import ai_link
        ai_link.begin_login(self.a.id, "chatgpt")
        ai_link.set_device_prompt(self.a.id, "chatgpt", "https://auth.openai.com/codex/device", "AB12-CDE34")
        ai_link.complete(self.a.id, "chatgpt", True)

    def test_a_role_works_with_the_ai_chosen_for_it(self):
        from app.routes import roles as role_routes
        self.connect_chatgpt()
        self.assertEqual(agents.settings(self.a.id)["roles"]["programmer"]["provider"], "claude")   # the standard
        self.assertEqual(role_routes.role_settings("programmer", provider="mistral", user=self.a).status_code, 400)
        self.assertEqual(role_routes.role_settings("programmer", provider="chatgpt", user=self.a)["provider"], "chatgpt")
        mine = agents.settings(self.a.id)["roles"]["programmer"]
        self.assertEqual((mine["provider"], catalog_provider(mine["model"])), ("chatgpt", "chatgpt"))
        self.assertEqual(agents.settings(self.a.id)["roles"]["reviewer"]["provider"], "claude")      # only that role
        self.start()
        job = agents.claim_next(can_mac=False)
        self.assertEqual((job.role, job.provider), ("programmer", "chatgpt"))
        role_routes.role_settings("programmer", provider="", user=self.a)                            # back to the standard
        self.assertEqual(agents.settings(self.a.id)["roles"]["programmer"]["provider"], "claude")

    def test_the_tab_lists_the_connected_ais_first_and_marks_the_roles(self):
        from app import rolepage
        self.connect_chatgpt()
        agents.configure(self.a.id, "programmer", provider="chatgpt")
        html = rolepage._ai_pills("de", "programmer", "chatgpt", ("claude", "chatgpt"))
        self.assertLess(html.index('data-role-ai="claude"'), html.index('data-role-ai="chatgpt"'))
        self.assertLess(html.index('data-role-ai="chatgpt"'), html.index('class="p-ai off"'))       # connected first
        self.assertIn('data-role-ai="chatgpt" data-role="programmer" aria-pressed="true"', html)
        self.assertNotIn('class="p-ai off">ChatGPT', html)                                         # connected: not dashed

    def test_the_programmer_says_where_his_task_stands_when_nothing_runs(self):
        from app import rolepage
        html = rolepage._now("de", [], 0, (FakeTask("Feinschliff", "awaiting_approval"), ""))
        self.assertIn("Wartet auf deine Freigabe: Feinschliff", html)
        self.assertIn("r-now idle", html)
        self.assertIn("nichts zu tun", rolepage._now("de", [], 0, None))


class FakeTask:
    def __init__(self, title, status):
        self.title, self.status = title, status


def catalog_provider(model):
    from app import catalog
    return catalog.provider_of(model)


class PauseTest(LoopTest):
    """The emergency switch (Janis, 22.11.2026): the agents stop at once, the manager chat does not."""

    def test_pause_stops_the_running_run_and_starts_nothing_until_going_on(self):
        from app.routes import ai as ai_routes
        from app.routes import runner as runner_routes
        task = self.start()
        job = agents.claim_next(can_mac=False)
        with db.connect() as conn:
            deadline = conn.execute("SELECT deadline FROM agent_tasks WHERE id = ?", (task.id,)).fetchone()[0]
        self.assertEqual(ai_routes.pause("1", user=self.a), {"ok": True, "paused": True})
        self.assertEqual(runner_routes.stops()["runs"], [job.run_id])              # the runner stops its container
        self.assertIsNone(agents.claim_next(can_mac=False))                         # nothing starts while paused
        self.assertFalse(agents.finish_run(job.run_id, "done", "late"))            # the stopped run's word is no more
        self.assertEqual(runner_routes.stop_done(job.run_id), {"ok": True})
        chat.send(self.a.id, self.pa.id, "Hallo")                                   # the manager chat goes on
        self.assertIsNotNone(chat.claim_next())
        agents.set_paused(self.a.id, False, now=int(__import__("time").time()) + 600)
        with db.connect() as conn:
            later = conn.execute("SELECT deadline FROM agent_tasks WHERE id = ?", (task.id,)).fetchone()[0]
        self.assertGreaterEqual(later - deadline, 590)                              # the pause does not count
        self.assertEqual(agents.claim_next(can_mac=False).run_id, job.run_id)      # it starts again

    def test_the_drawer_shows_the_switch_in_both_states(self):
        from app import ui
        page = ui.settings_bar(self.a)
        self.assertLess(page.index('id="ai-pause"'), page.index('id="chat-clear-open"'))
        self.assertIn(">KIs pausieren<", page)
        agents.set_paused(self.a.id, True)
        page = ui.settings_bar(self.a)
        self.assertIn('class="clear-btn pause-btn paused"', page)
        self.assertIn(">KIs fortfahren<", page)


if __name__ == "__main__":
    unittest.main()
