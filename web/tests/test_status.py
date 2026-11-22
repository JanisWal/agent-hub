"""The assessment of a project (status.py) and the Status tile."""
import os
import tempfile
import unittest

from app import board, checks, db, managerpage, projects, status, users

NOW = 10_000_000
DAY = 86400


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.user = users.create_user("a@example.com", "Aaaa!pass12")
        self.project = projects.create_project(self.user.id, "Project")
        self.pid = self.project.id

    def tearDown(self):
        self.tmp.cleanup()

    def item(self, state="open", at=NOW - 100 * DAY):
        made = board.create_item(self.user.id, self.pid, "bug", "Item")
        with db.connect() as conn:
            conn.execute("UPDATE board_items SET status = ?, created_at = ? WHERE id = ?", (state, at, made.id))
        return made.id

    def task(self, stage, item_id=None, created=NOW - 100 * DAY, finished=None, why="", held=None):
        """A task in a stage; `why` makes it wait for the user's decision (since `held`)."""
        with db.connect() as conn:
            return conn.execute(
                "INSERT INTO agent_tasks (project_id, item_id, title, kind, stage, hold, hold_why, held_since, created_at,"
                " finished_at) VALUES (?, ?, 'T', 'bug', ?, ?, ?, ?, ?, ?)",
                (self.pid, item_id, stage, "decision" if why else "", why, held or created, created, finished)).lastrowid

    def add_run(self, task_id, state, at):
        with db.connect() as conn:
            conn.execute("INSERT INTO agent_runs (task_id, role, model, status, created_at, finished_at)"
                         " VALUES (?, 'coder', 'm', ?, ?, ?)", (task_id, state, at, at))

    def assess(self):
        return status.assess(self.user.id, self.pid, NOW)

    def test_an_empty_project_has_no_lamp_and_says_so(self):
        a = self.assess()
        self.assertEqual((a.lamp, a.total, a.progress, a.activity), ("none", 0, 0, "idle"))
        self.assertIn("Noch nichts geplant", managerpage.status_tile("de", a, NOW))

    def test_planned_in_progress_waiting_done_and_the_progress(self):
        self.item()                                                   # planned
        taken = self.item("working")                                  # off the board while it is worked on
        self.task("coding", taken, created=NOW - 100)                 # in progress
        waiting = self.item("working")
        self.task("coding", waiting, created=NOW - 100, why="returns")   # waits for the user's decision
        self.item("archived")                                         # done
        finished = self.item("archived")
        self.task("done", finished, created=NOW - 100, finished=NOW - 50)   # one thing, not counted twice
        self.item("proposed")
        self.item("trash")
        a = self.assess()
        self.assertEqual((a.planned, a.in_progress, a.waiting, a.done, a.proposals), (1, 1, 1, 2, 1))
        self.assertEqual(a.total, 5)
        self.assertEqual(a.progress, 40)

    def test_a_task_without_an_item_counts_as_done_once(self):
        self.task("done", None, created=NOW - 100, finished=NOW - 50)
        a = self.assess()
        self.assertEqual((a.done, a.progress), (1, 100))

    def test_work_that_is_running_is_green(self):
        i = self.item()
        t = self.task("coding", i, created=NOW - 60)
        self.add_run(t, "running", NOW - 30)
        a = self.assess()
        self.assertEqual((a.activity, a.lamp), ("running", "green"))

    def test_open_work_without_activity_for_a_week_is_stalled_and_amber(self):
        self.item(at=NOW - 8 * DAY)
        a = self.assess()
        self.assertEqual((a.activity, a.lamp, a.reasons), ("stalled", "yellow", ["stalled"]))
        self.item(at=NOW - 3 * DAY)                                   # something happened three days ago
        self.assertEqual(self.assess().activity, "quiet")
        self.item(at=NOW - DAY)                                       # and yesterday
        self.assertEqual(self.assess().activity, "active")

    def test_a_task_that_waits_for_a_decision_is_red(self):
        i = self.item("working", at=NOW - DAY)
        t = self.task("coding", i, created=NOW - DAY, why="returns")
        a = self.assess()
        self.assertEqual((a.lamp, a.waiting, a.reasons), ("red", 1, ["escalated"]))
        with db.connect() as conn:
            conn.execute("UPDATE agent_tasks SET hold_why = 'failed' WHERE id = ?", (t,))
        self.assertEqual(self.assess().reasons, ["escalated", "failed"])
        with db.connect() as conn:
            conn.execute("UPDATE agent_tasks SET hold = '', hold_why = '' WHERE id = ?", (t,))
        self.assertNotEqual(self.assess().lamp, "red")                # the user decided: it goes on

    def test_a_decision_waiting_for_days_says_so(self):
        i = self.item("working", at=NOW - DAY)
        self.task("merging", i, created=NOW - 4 * DAY, why="old", held=NOW - 4 * DAY)
        a = self.assess()
        self.assertEqual((a.lamp, a.reasons), ("red", ["escalated", "release_old"]))

    def test_busy_when_much_happened_in_the_week(self):
        for _ in range(status.BUSY_EVENTS):
            self.item(at=NOW - 3 * DAY)
        self.assertEqual(self.assess().activity, "busy")

    def test_nothing_left_to_do_is_orange_at_rest(self):
        self.item(state="archived", at=NOW - DAY)                     # done, nothing open
        a = self.assess()
        self.assertEqual((a.lamp, a.done, a.planned), ("rest", 1, 0))
        self.assertIn("lamp-rest", managerpage.status_tile("de", a, NOW))
        self.item(at=NOW - DAY)                                       # new work: green again
        self.assertEqual(self.assess().lamp, "green")

    def test_due_checks_are_counted_but_do_not_change_the_lamp(self):
        self.item(at=NOW - DAY)
        checks.create(self.user.id, self.pid, "Security", "weekly", now=NOW - 30 * DAY)
        a = self.assess()
        self.assertEqual((a.checks_due, a.lamp), (1, "green"))

    def test_the_tile_shows_numbers_lamp_and_reasons_in_both_languages(self):
        self.item(at=NOW - 8 * DAY)
        a = self.assess()
        de, en = managerpage.status_tile("de", a, NOW), managerpage.status_tile("en", a, NOW)
        self.assertIn("lamp-yellow", de)
        self.assertIn("Stockt", de)
        self.assertIn("vor 8 Tagen", de)
        self.assertIn("Stalled", en)
        self.assertIn("8 days ago", en)
        self.assertIn('<progress max="100" value="0"', de)
        self.assertNotIn("style=", de)                                # the policy forbids inline styles

    def test_a_foreign_project_is_not_assessed(self):
        other = users.create_user("b@example.com", "Bbbb!pass12")
        self.assertIsNone(status.assess(other.id, self.pid, NOW))


if __name__ == "__main__":
    unittest.main()
