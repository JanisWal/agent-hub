import os
import sqlite3
import tempfile
import unittest

from app import db, i18n, projects, users


class ProjectsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.me = users.create_user("me@example.com", "correct horse")
        self.other = users.create_user("other@example.com", "correct horse")

    def tearDown(self):
        self.tmp.cleanup()

    def names(self, user):
        return [p.name for page in projects.layout(user.id) for p in page]

    def pages(self, user=None):
        """The layout as lists of names, e.g. [["A", "B"], ["C"]]."""
        user = user or self.me
        return [[p.name for p in page] for page in projects.layout(user.id)]

    def add(self, *names):
        return [projects.create_project(self.me.id, n) for n in names]

    def test_create_appends_in_order(self):
        self.add("A", "B", "C")
        self.assertEqual(self.names(self.me), ["A", "B", "C"])

    def test_name_is_trimmed_and_validated(self):
        self.assertEqual(projects.create_project(self.me.id, "  X  ").name, "X")
        with self.assertRaises(ValueError):
            projects.create_project(self.me.id, "   ")
        with self.assertRaises(ValueError):
            projects.create_project(self.me.id, "x" * 61)

    def test_projects_are_private_per_user(self):
        project = projects.create_project(self.me.id, "Mine")
        self.assertEqual(self.names(self.other), [])
        self.assertIsNone(projects.get_project(self.other.id, project.id))
        self.assertFalse(projects.delete_project(self.other.id, project.id))
        self.assertEqual(self.names(self.me), ["Mine"])

    def test_delete(self):
        project = projects.create_project(self.me.id, "Gone")
        self.assertTrue(projects.delete_project(self.me.id, project.id))
        self.assertEqual(self.names(self.me), [])

    def test_had_project_stays_after_delete(self):
        user_id = self.me.id
        self.assertFalse(users.check_login("me@example.com", "correct horse").had_project)
        project = projects.create_project(user_id, "First")
        projects.delete_project(user_id, project.id)
        self.assertTrue(users.check_login("me@example.com", "correct horse").had_project)

    def test_seventh_project_opens_a_second_page(self):
        self.add(*"ABCDEFG")
        self.assertEqual(self.pages(), [list("ABCDEF"), ["G"]])

    def test_new_project_takes_the_first_free_slot(self):
        made = self.add(*"ABCDEFG")
        projects.delete_project(self.me.id, made[1].id)  # frees a slot on page one
        self.add("H")
        self.assertEqual(self.pages(), [list("ACDEFH"), ["G"]])

    def test_display_page(self):
        made = self.add(*"ABCDEFG")
        self.assertEqual(projects.display_page(self.me.id, made[0].id), 1)
        self.assertEqual(projects.display_page(self.me.id, made[6].id), 2)

    def test_move_within_a_page(self):
        a, b, c = self.add("A", "B", "C")
        self.assertEqual(projects.move(self.me.id, c.id, 1, 0), 1)
        self.assertEqual(self.pages(), [["C", "A", "B"]])

    def test_move_to_a_new_page_like_on_a_phone(self):
        a, b, c, d = self.add("A", "B", "C", "D")
        # Three belong together, the fourth goes to its own page.
        self.assertEqual(projects.move(self.me.id, d.id, 2, 0), 2)
        self.assertEqual(self.pages(), [["A", "B", "C"], ["D"]])

    def test_move_to_a_full_page_pushes_the_last_project_on(self):
        made = self.add(*"ABCDEFG")  # page one full, G alone on page two
        projects.move(self.me.id, made[6].id, 1, 0)
        self.assertEqual(self.pages(), [list("GABCDE"), ["F"]])

    def test_push_cascades_over_several_full_pages(self):
        made = self.add(*"ABCDEFGHIJKLM")  # 6 + 6 + 1
        projects.move(self.me.id, made[12].id, 1, 0)
        self.assertEqual(self.pages(), [list("MABCDE"), list("FGHIJK"), ["L"]])

    def test_emptied_page_disappears(self):
        made = self.add(*"ABCDEFG")
        projects.move(self.me.id, made[6].id, 1, 6)  # page one is full, so G is pushed right back
        self.assertEqual(self.pages(), [list("ABCDEF"), ["G"]])
        projects.delete_project(self.me.id, made[6].id)
        self.assertEqual(self.pages(), [list("ABCDEF")])

    def test_move_clamps_page_and_index(self):
        a, b = self.add("A", "B")
        self.assertEqual(projects.move(self.me.id, a.id, 99, 99), 2)
        self.assertEqual(self.pages(), [["B"], ["A"]])
        self.assertEqual(projects.move(self.me.id, a.id, -5, -5), 1)
        self.assertEqual(self.pages(), [["A", "B"]])

    def test_move_other_pages_stay_untouched(self):
        made = self.add(*"ABCDEFGH")  # page two holds G, H
        projects.move(self.me.id, made[0].id, 1, 5)  # A to the end of page one
        self.assertEqual(self.pages(), [list("BCDEFA"), ["G", "H"]])

    def test_move_rejects_foreign_projects(self):
        theirs = projects.create_project(self.other.id, "Theirs")
        with self.assertRaises(ValueError):
            projects.move(self.me.id, theirs.id, 1, 0)
        self.assertEqual(self.pages(self.other), [["Theirs"]])

    def test_verify_password(self):
        self.assertTrue(users.verify_password(self.me.id, "correct horse"))
        self.assertFalse(users.verify_password(self.me.id, "wrong"))

    def test_profile(self):
        self.assertEqual(self.me.name, "me")
        users.set_profile(self.me.id, "  Janis ", "en")
        user = users.check_login("me@example.com", "correct horse")
        self.assertEqual((user.name, user.language), ("Janis", "en"))
        users.set_profile(self.me.id, "", "de")
        self.assertEqual(users.check_login("me@example.com", "correct horse").name, "me")
        with self.assertRaises(ValueError):
            users.set_profile(self.me.id, "x" * 41, "de")


class MigrationTest(unittest.TestCase):
    def test_old_database_gets_new_columns_and_keeps_users(self):
        with tempfile.TemporaryDirectory() as tmp:
            db.DB_PATH = os.path.join(tmp, "old.db")
            old = sqlite3.connect(db.DB_PATH)
            old.executescript(
                "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE,"
                " password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0,"
                " created_at INTEGER NOT NULL);"
                "INSERT INTO users (email, password_hash, is_admin, created_at)"
                " VALUES ('old@example.com', 'x', 1, 1);"
            )
            old.commit()
            old.close()
            with db.connect() as conn:
                row = conn.execute("SELECT * FROM users").fetchone()
            self.assertEqual(row["email"], "old@example.com")
            self.assertEqual((row["language"], row["had_project"]), ("de", 0))
            self.assertIsNone(row["display_name"])

    def test_projects_without_pages_are_spread_over_pages_of_six(self):
        with tempfile.TemporaryDirectory() as tmp:
            db.DB_PATH = os.path.join(tmp, "old.db")
            old = sqlite3.connect(db.DB_PATH)
            old.executescript(
                "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE,"
                " password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0,"
                " created_at INTEGER NOT NULL);"
                "INSERT INTO users (email, password_hash, created_at) VALUES ('a@b.c', 'x', 1);"
                "CREATE TABLE projects (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,"
                " name TEXT NOT NULL, position INTEGER NOT NULL, created_at INTEGER NOT NULL);"
            )
            for i in range(8):  # positions with a gap, as after a deleted project
                old.execute(
                    "INSERT INTO projects (user_id, name, position, created_at) VALUES (1, ?, ?, 1)",
                    (f"P{i}", i * 2 + 1),
                )
            old.commit()
            old.close()
            pages = [[p.name for p in page] for page in projects.layout(1)]
            self.assertEqual(pages, [[f"P{i}" for i in range(6)], ["P6", "P7"]])


class I18nTest(unittest.TestCase):
    def test_both_languages_have_the_same_keys(self):
        self.assertEqual(set(i18n.STRINGS["de"]), set(i18n.STRINGS["en"]))

    def test_unknown_language_falls_back_to_german(self):
        self.assertEqual(i18n.t("xx", "logout"), "Abmelden")
        self.assertEqual(i18n.t("en", "page_n", n=3), "Page 3")


if __name__ == "__main__":
    unittest.main()
