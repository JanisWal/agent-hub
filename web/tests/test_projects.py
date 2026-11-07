import os
import sqlite3
import tempfile
import unittest

from app import i18n, projects, users


class ProjectsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        users.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.me = users.create_user("me@example.com", "correct horse")
        self.other = users.create_user("other@example.com", "correct horse")

    def tearDown(self):
        self.tmp.cleanup()

    def names(self, user):
        return [p.name for p in projects.list_projects(user.id)]

    def test_create_appends_in_order(self):
        for name in ("A", "B", "C"):
            projects.create_project(self.me.id, name)
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

    def test_reorder_swaps_positions(self):
        a, b, c = (projects.create_project(self.me.id, n) for n in "ABC")
        projects.reorder(self.me.id, [c.id, a.id, b.id])
        self.assertEqual(self.names(self.me), ["C", "A", "B"])

    def test_reorder_of_one_page_keeps_other_pages(self):
        made = [projects.create_project(self.me.id, str(i)) for i in range(8)]
        # Reverse the first six, as if dragged on page one.
        projects.reorder(self.me.id, [p.id for p in reversed(made[:6])])
        self.assertEqual(self.names(self.me), ["5", "4", "3", "2", "1", "0", "6", "7"])

    def test_reorder_rejects_foreign_and_duplicate_ids(self):
        mine = projects.create_project(self.me.id, "Mine")
        theirs = projects.create_project(self.other.id, "Theirs")
        with self.assertRaises(ValueError):
            projects.reorder(self.me.id, [mine.id, theirs.id])
        with self.assertRaises(ValueError):
            projects.reorder(self.me.id, [mine.id, mine.id])

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
            users.DB_PATH = os.path.join(tmp, "old.db")
            old = sqlite3.connect(users.DB_PATH)
            old.executescript(
                "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE,"
                " password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0,"
                " created_at INTEGER NOT NULL);"
                "INSERT INTO users (email, password_hash, is_admin, created_at)"
                " VALUES ('old@example.com', 'x', 1, 1);"
            )
            old.commit()
            old.close()
            with users.connect() as db:
                row = db.execute("SELECT * FROM users").fetchone()
            self.assertEqual(row["email"], "old@example.com")
            self.assertEqual((row["language"], row["had_project"]), ("de", 0))
            self.assertIsNone(row["display_name"])


class I18nTest(unittest.TestCase):
    def test_both_languages_have_the_same_keys(self):
        self.assertEqual(set(i18n.STRINGS["de"]), set(i18n.STRINGS["en"]))

    def test_unknown_language_falls_back_to_german(self):
        self.assertEqual(i18n.t("xx", "logout"), "Abmelden")
        self.assertEqual(i18n.t("en", "page_n", n=3), "Page 3")


if __name__ == "__main__":
    unittest.main()
