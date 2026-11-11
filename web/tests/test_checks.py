"""Regular checks of the Manager view: data rules, the tile and the manager's context."""
import dataclasses
import os
import tempfile
import unittest

from app import board, checks, chat, claude_link, db, i18n, managerpage, projectpage, projects, users
from app.routes import checks as check_routes
from pathlib import Path

DAY = checks.DAY


class ChecksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.user = users.create_user("a@example.com", "Aaaa!pass12")
        self.project = projects.create_project(self.user.id, "Project")

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, text="Check security", cycle="weekly", now=1_000_000):
        return checks.create(self.user.id, self.project.id, text, cycle, now=now)

    # --- data rules
    def test_create_and_list_in_the_order_they_were_made(self):
        first, second = self.make("First"), self.make("Second", "daily")
        self.assertEqual([c.text for c in checks.list_checks(self.user.id, self.project.id)], ["First", "Second"])
        self.assertEqual((first.cycle, first.last_done, second.cycle), ("weekly", None, "daily"))

    def test_bad_input_is_refused(self):
        for text, cycle in (("", "daily"), ("   ", "daily"), ("x" * 201, "daily"), ("Fine", "hourly"), ("Fine", "")):
            with self.assertRaises(ValueError):
                checks.create(self.user.id, self.project.id, text, cycle)
        self.assertEqual(checks.list_checks(self.user.id, self.project.id), [])
        self.assertEqual(self.make("  trimmed  ").text, "trimmed")

    def test_a_project_holds_at_most_fifty(self):
        for number in range(checks.MAX_PER_PROJECT):
            self.make(f"Check {number}")
        with self.assertRaises(ValueError):
            self.make("One too many")

    def test_a_check_is_due_when_never_done_or_a_cycle_has_passed(self):
        for cycle, days in (("daily", 1), ("weekly", 7), ("monthly", 30), ("quarterly", 91)):
            self.assertTrue(checks.is_due(cycle, None, 5 * DAY), cycle)
            self.assertFalse(checks.is_due(cycle, 100 * DAY, 100 * DAY + days * DAY - 1), cycle)
            self.assertTrue(checks.is_due(cycle, 100 * DAY, 100 * DAY + days * DAY), cycle)

    def test_done_sets_the_time_and_update_keeps_it(self):
        check = self.make()
        self.assertTrue(checks.mark_done(self.user.id, check.id, now=2_000_000))
        self.assertEqual(checks.update(self.user.id, check.id, "Renamed", "monthly"), self.project.id)
        [again] = checks.list_checks(self.user.id, self.project.id)
        self.assertEqual((again.text, again.cycle, again.last_done), ("Renamed", "monthly", 2_000_000))
        with self.assertRaises(ValueError):
            checks.update(self.user.id, check.id, "", "monthly")

    def test_delete_and_deleting_the_project_removes_checks(self):
        check, other = self.make("Gone"), self.make("Stays")
        self.assertTrue(checks.delete(self.user.id, check.id))
        self.assertFalse(checks.delete(self.user.id, check.id))
        self.assertEqual([c.text for c in checks.list_checks(self.user.id, self.project.id)], ["Stays"])
        self.assertTrue(projects.delete_project(self.user.id, self.project.id))
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM checks WHERE id = ?", (other.id,)).fetchone()[0], 0)

    # --- the tile
    def tile(self, lang="de", now=1_000_000):
        mine = checks.list_checks(self.user.id, self.project.id)
        return managerpage.render(lang, {"autonomy": "major", "roles": {"chef": {"model": "sonnet", "net": "together"}}},
                                  mine, now=now)

    def test_empty_tile_shows_the_hint_and_the_plus(self):
        html = self.tile()
        self.assertIn('id="check-add"', html)
        self.assertIn("nicht Teil des Boards", html)
        self.assertNotIn("check-row", html)

    def test_tile_lists_checks_marks_due_ones_and_escapes_text(self):
        due = self.make("<b>Security</b> %BODY%", "weekly", now=0)
        done = self.make("Standards", "monthly", now=0)
        checks.mark_done(self.user.id, done.id, now=1_000_000 - 3 * DAY)
        html = self.tile()
        self.assertIn("&lt;b&gt;Security&lt;/b&gt; %BODY%", html)
        self.assertNotIn("<b>Security</b>", html)
        row_due = html[html.index(f'data-id="{due.id}"'):html.index(f'data-id="{done.id}"')]
        self.assertIn("Wöchentlich · fällig", row_due)
        self.assertIn('class="check-row due"', html)
        self.assertIn("Monatlich · vor 3 Tagen erledigt", html)
        self.assertEqual(html.count('class="check-row'), 2)
        self.assertIn('<span class="count">2</span>', html[html.index('id="checks"'):])

    def test_every_text_exists_in_both_languages(self):
        self.make("Security")
        for lang in ("de", "en"):
            html = self.tile(lang) + managerpage.dialogs(lang)
            self.assertNotIn("%t.", html)
        self.assertIn("Weekly · due", self.tile("en"))
        for key in ("daily", "weekly", "monthly", "quarterly"):
            self.assertNotEqual(i18n.t("de", "cycle_" + key), i18n.t("en", "cycle_" + key))

    def test_dialog_offers_the_four_cycles_and_sits_outside_the_hidden_view(self):
        dialogs = managerpage.dialogs("de")
        for value in ("daily", "weekly", "monthly", "quarterly"):
            self.assertIn(f'<option value="{value}">', dialogs)
        self.assertIn('id="check-dialog"', dialogs)
        user = dataclasses.replace(self.user, language="de")
        page = projectpage.render(user, self.project, [], [])
        self.assertIn('id="check-dialog"', page)
        self.assertNotIn('id="check-dialog"', page[page.index('id="manager-view"'):page.index('id="item-dialog"')])

    # --- the routes
    def test_routes_create_change_done_and_delete(self):
        location = f"/projects/{self.project.id}#manager"
        answer = check_routes.create_check(self.project.id, "Look at security", "daily", self.user)
        self.assertEqual((answer.status_code, answer.headers["location"]), (303, location))
        [check] = checks.list_checks(self.user.id, self.project.id)
        check_routes.create_check(self.project.id, "", "daily", self.user)            # empty: nothing created
        check_routes.create_check(self.project.id, "Fine", "hourly", self.user)       # bad cycle: nothing created
        self.assertEqual(len(checks.list_checks(self.user.id, self.project.id)), 1)
        changed = check_routes.change_check(check.id, "Look again", "weekly", self.user)
        self.assertEqual(changed.headers["location"], location)
        self.assertEqual(check_routes.check_done(check.id, self.user), {"ok": True})
        self.assertIsNotNone(checks.list_checks(self.user.id, self.project.id)[0].last_done)
        self.assertEqual(check_routes.check_delete(check.id, self.user), {"ok": True})
        self.assertEqual(check_routes.check_delete(check.id, self.user).status_code, 404)

    # --- the manager knows the checks
    def test_the_manager_reads_the_checks_in_its_context(self):
        claude_link.BASE_DIR = Path(self.tmp.name) / "claude"
        claude_link.begin(self.user.id)
        claude_link.complete(self.user.id, True)
        self.make("Check security", "weekly", now=0)
        done = self.make("Remove old code", "quarterly", now=0)
        checks.mark_done(self.user.id, done.id)
        chat.send(self.user.id, self.project.id, "What is next?")
        text = chat.claim_next().prompt
        self.assertIn("Regular checks", text)
        self.assertIn("- Check security (weekly, due)", text)
        self.assertIn("- Remove old code (quarterly, not due yet)", text)


if __name__ == "__main__":
    unittest.main()
