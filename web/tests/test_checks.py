"""Regular checks of the Manager view: data rules, the tile and the manager's context."""
import dataclasses
import datetime
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

    # --- weekdays of a daily check (Mo, We, Fr, Su = "1010101"; 9 November 2026 is a Monday)
    @staticmethod
    def at(day, hour=12):
        return int(datetime.datetime(2026, 11, day, hour).timestamp())

    def test_a_daily_check_is_due_on_its_days_only(self):
        days = "1010101"
        mon, tue, wed, thu, fri = (self.at(d) for d in (9, 10, 11, 12, 13))
        self.assertTrue(checks.is_due("daily", None, mon, days))                    # never done
        self.assertFalse(checks.is_due("daily", mon, self.at(9, 20), days))        # done today
        self.assertFalse(checks.is_due("daily", mon, tue, days))                   # Tuesday does not count
        self.assertTrue(checks.is_due("daily", mon, wed, days))                    # Wednesday does
        self.assertFalse(checks.is_due("daily", tue, self.at(10, 22), days))       # done on a day that is not one of its days
        self.assertTrue(checks.is_due("daily", tue, wed, days))
        self.assertFalse(checks.is_due("daily", wed, thu, days))
        self.assertTrue(checks.is_due("daily", wed, fri, days))                    # a missed Thursday does not matter, Friday is due
        self.assertTrue(checks.is_due("daily", wed, wed + 30 * DAY, days))         # long unused: due
        self.assertTrue(checks.is_due("daily", self.at(15), self.at(16), days))    # Sunday done, Monday due

    def test_every_day_ticked_behaves_like_before(self):
        self.assertFalse(checks.is_due("daily", self.at(9), self.at(9, 23)))
        self.assertTrue(checks.is_due("daily", self.at(9), self.at(10, 1)))

    def test_days_are_stored_checked_and_only_kept_for_daily_checks(self):
        created = self.make("Gym", "daily")
        self.assertEqual(created.days, checks.ALL_DAYS)
        with_days = checks.create(self.user.id, self.project.id, "Mo We", "daily", "1010000")
        self.assertEqual(with_days.days, "1010000")
        weekly = checks.create(self.user.id, self.project.id, "Weekly", "weekly", "1010000")
        self.assertEqual(weekly.days, checks.ALL_DAYS)
        checks.update(self.user.id, with_days.id, "Mo We", "daily", "0000011")
        self.assertEqual(checks.list_checks(self.user.id, self.project.id)[1].days, "0000011")
        checks.update(self.user.id, with_days.id, "Mo We", "monthly", "0000011")
        self.assertEqual(checks.list_checks(self.user.id, self.project.id)[1].days, checks.ALL_DAYS)
        self.assertEqual((checks.days_string(["0", "2", "4", "6"]), checks.day_numbers("1010101")),
                         ("1010101", [0, 2, 4, 6]))

    def test_bad_days_are_refused(self):
        for days in ("0000000", "101", "10101010", "10x0101", ""):
            with self.assertRaises(ValueError, msg=days):
                checks.create(self.user.id, self.project.id, "Gym", "daily", days)
        self.assertEqual(checks.list_checks(self.user.id, self.project.id), [])

    def test_an_old_database_gets_all_days(self):
        with db.connect() as conn:
            conn.execute("INSERT INTO checks (project_id, text, cycle, created_at) VALUES (?, 'old', 'daily', 1)",
                         (self.project.id,))
        self.assertEqual(checks.list_checks(self.user.id, self.project.id)[0].days, checks.ALL_DAYS)

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

    def test_the_row_has_a_pencil_instead_of_a_done_button_and_names_the_days(self):
        every = self.make("Every day", "daily", now=0)
        some = checks.create(self.user.id, self.project.id, "Some days", "daily", "1010101", now=0)
        html = self.tile()
        self.assertEqual(html.count('data-check="edit"'), 2)
        self.assertEqual(html.count('data-check="delete"'), 2)
        self.assertNotIn('data-check="done"', html)
        self.assertIn('data-days="1010101"', html)
        self.assertIn("Täglich · fällig", html[html.index(f'data-id="{every.id}"'):html.index(f'data-id="{some.id}"')])
        self.assertIn("Mo, Mi, Fr, So · fällig", html)
        self.assertIn("Mo, We, Fr, Su · due", self.tile("en"))

    def test_the_dialog_has_seven_day_circles_and_a_done_link(self):
        for lang, first, last in (("de", "Montag", "Sonntag"), ("en", "Monday", "Sunday")):
            dialogs = managerpage.dialogs(lang)
            self.assertEqual(dialogs.count('name="day"'), 7)
            self.assertEqual(dialogs.count(" checked "), 7)                     # all ticked at first
            self.assertIn(f'aria-label="{first}"', dialogs)
            self.assertIn(f'aria-label="{last}"', dialogs)
            self.assertIn('id="check-dialog-done"', dialogs)
            self.assertIn('id="check-days-error"', dialogs)
            self.assertNotIn("%t.", dialogs)

    def test_the_manager_hears_the_days_of_a_daily_check(self):
        claude_link.begin(self.user.id)
        claude_link.complete(self.user.id, True)
        checks.create(self.user.id, self.project.id, "Gym", "daily", "1010101", now=0)
        chat.send(self.user.id, self.project.id, "What is next?")
        self.assertIn("- Gym (daily on Mon, Wed, Fri, Sun, due)", chat.claim_next().prompt)

    def test_the_to_do_dialog_says_to_do_not_title(self):
        self.assertEqual((i18n.t("de", "item_title"), i18n.t("en", "item_title")), ("To-Do", "To-do"))

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
        every_day = list("0123456")
        answer = check_routes.create_check(self.project.id, "Look at security", "daily", self.user, every_day)
        self.assertEqual((answer.status_code, answer.headers["location"]), (303, location))
        [check] = checks.list_checks(self.user.id, self.project.id)
        check_routes.create_check(self.project.id, "", "daily", self.user, every_day)       # empty: nothing created
        check_routes.create_check(self.project.id, "Fine", "hourly", self.user, every_day)  # bad cycle: nothing created
        self.assertEqual(len(checks.list_checks(self.user.id, self.project.id)), 1)
        changed = check_routes.change_check(check.id, "Look again", "weekly", self.user)
        self.assertEqual(changed.headers["location"], location)
        check_routes.change_check(check.id, "Mo and We", "daily", self.user, ["0", "2", "x", "9"])   # junk is ignored
        self.assertEqual(checks.list_checks(self.user.id, self.project.id)[0].days, "1010000")
        check_routes.change_check(check.id, "No day", "daily", self.user, [])    # a daily check needs a day: unchanged
        self.assertEqual(checks.list_checks(self.user.id, self.project.id)[0].text, "Mo and We")
        self.assertEqual(check_routes.check_done(check.id, self.user), {"ok": True})
        self.assertIsNotNone(checks.list_checks(self.user.id, self.project.id)[0].last_done)
        self.assertEqual(check_routes.check_delete(check.id, self.user), {"ok": True})
        self.assertEqual(check_routes.check_delete(check.id, self.user).status_code, 404)

    # --- the manager knows the checks
    def test_the_manager_reads_the_checks_in_its_context(self):
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
