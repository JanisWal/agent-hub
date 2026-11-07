import os
import re
import sqlite3
import tempfile
import unittest

from app import board, db, projects, ui, userspage, users


class AccountsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.owner = users.create_user("owner@example.com", "Own3r!pass", role="owner")
        self.admin = users.create_user("admin@example.com", "Adm1n!pass", role="admin")
        self.user = users.add_user(self.owner, "user@example.com", "Start1234")

    def tearDown(self):
        self.tmp.cleanup()

    # --- password rules
    def test_password_rules(self):
        self.assertIsNone(users.password_problem("Ab1!2c"))
        self.assertEqual(users.password_problem("Ab1!2"), "short")
        for bad in ("abcde1!2", "ABCDE1!2", "Abcdef!1", "Abcdef12", "Abcdef1!"):
            self.assertEqual(users.password_problem(bad), "policy", bad)

    # --- roles
    def test_roles(self):
        self.assertEqual((self.owner.role, self.admin.role, self.user.role), ("owner", "admin", "user"))
        self.assertTrue(self.owner.is_admin and self.admin.is_admin and not self.user.is_admin)
        self.assertTrue(users.owner_exists())

    def test_start_password_must_be_changed(self):
        self.assertTrue(users.check_login("user@example.com", "Start1234").must_change)
        self.assertFalse(users.check_login("admin@example.com", "Adm1n!pass").must_change)

    def test_only_owner_and_admins_list_and_add(self):
        self.assertEqual(len(users.list_users(self.admin)), 3)
        self.assertEqual(users.list_users(self.owner)[0].role, "owner")
        with self.assertRaises(PermissionError):
            users.list_users(self.user)
        with self.assertRaises(PermissionError):
            users.add_user(self.user, "x@example.com", "Start1234")

    def test_add_user_errors(self):
        with self.assertRaises(users.UserError) as taken:
            users.add_user(self.owner, "USER@example.com", "Start1234")
        self.assertEqual(taken.exception.code, "taken")
        with self.assertRaises(users.UserError) as short:
            users.add_user(self.owner, "new@example.com", "Ab1!")
        self.assertEqual(short.exception.code, "short")
        with self.assertRaises(users.UserError) as mail:
            users.add_user(self.owner, "nope", "Start1234")
        self.assertEqual(mail.exception.code, "email")

    def test_who_can_manage_whom(self):
        self.assertTrue(users.can_manage(self.owner, self.admin))
        self.assertTrue(users.can_manage(self.owner, self.user))
        self.assertTrue(users.can_manage(self.admin, self.user))
        self.assertFalse(users.can_manage(self.admin, self.owner))
        self.assertFalse(users.can_manage(self.admin, self.admin))
        self.assertFalse(users.can_manage(self.owner, self.owner))
        self.assertFalse(users.can_manage(self.user, self.admin))

    def test_nobody_touches_the_owner(self):
        for actor in (self.owner, self.admin):
            with self.assertRaises(PermissionError):
                users.delete_user(actor, self.owner.id)
            with self.assertRaises(PermissionError):
                users.reset_password(actor, self.owner.id, "Start1234")
        with self.assertRaises(PermissionError):
            users.set_admin(self.owner, self.owner.id, False)

    def test_admin_cannot_manage_other_admins(self):
        with self.assertRaises(PermissionError):
            users.delete_user(self.admin, self.admin.id)
        other = users.create_user("admin2@example.com", "Adm1n!pass", role="admin")
        with self.assertRaises(PermissionError):
            users.reset_password(self.admin, other.id, "Start1234")

    def test_only_owner_sets_admin(self):
        users.set_admin(self.owner, self.user.id, True)
        self.assertEqual(users.get_by_id(self.user.id).role, "admin")
        self.assertTrue(users.get_by_id(self.user.id).is_admin)
        users.set_admin(self.owner, self.user.id, False)
        self.assertEqual(users.get_by_id(self.user.id).role, "user")
        with self.assertRaises(PermissionError):
            users.set_admin(self.admin, self.user.id, True)

    def test_reset_password_forces_change_and_ends_sessions(self):
        token = users.create_session(self.user.id)
        users.reset_password(self.admin, self.user.id, "Neu12345")
        self.assertIsNone(users.get_user(token))
        again = users.check_login("user@example.com", "Neu12345")
        self.assertTrue(again.must_change)
        self.assertIsNone(users.check_login("user@example.com", "Start1234"))

    def test_delete_user_removes_projects_and_sessions(self):
        project = projects.create_project(self.user.id, "Mine")
        board.create_item(self.user.id, project.id, "bug", "x")
        token = users.create_session(self.user.id)
        users.delete_user(self.admin, self.user.id)
        self.assertIsNone(users.get_by_id(self.user.id))
        self.assertIsNone(users.get_user(token))
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM projects WHERE user_id = ?", (self.user.id,)).fetchone()[0], 0)

    # --- own password
    def test_change_own_password(self):
        token = users.create_session(self.user.id)
        other = users.create_session(self.user.id)
        users.change_own_password(self.user, "Start1234", "Mein!Pass12", keep_token=token)
        self.assertFalse(users.get_user(token).must_change)
        self.assertIsNotNone(users.get_user(token))
        self.assertIsNone(users.get_user(other))
        self.assertIsNotNone(users.check_login("user@example.com", "Mein!Pass12"))

    def test_change_own_password_errors(self):
        # first the user chooses his own password (no old one asked: he has a start password) ...
        users.change_own_password(self.user, "", "Mein!Pass12")
        settled = users.get_by_id(self.user.id)

        # ... from then on the old password is checked
        def code(old, new):
            with self.assertRaises(users.UserError) as raised:
                users.change_own_password(settled, old, new)
            return raised.exception.code

        self.assertEqual(code("wrong", "Other!Pass12"), "wrong_password")
        self.assertEqual(code("Mein!Pass12", "short"), "short")
        self.assertEqual(code("Mein!Pass12", "nodigits!Aa"), "policy")
        self.assertEqual(code("Mein!Pass12", "Mein!Pass12"), "same")

    # --- old databases
    def test_old_database_gets_an_owner(self):
        path = os.path.join(self.tmp.name, "old.db")
        conn = sqlite3.connect(path)
        conn.executescript(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE,"
            " password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL);"
            "INSERT INTO users (email, password_hash, is_admin, created_at) VALUES ('a@x.de', 'h', 1, 1);"
            "INSERT INTO users (email, password_hash, is_admin, created_at) VALUES ('b@x.de', 'h', 1, 2);"
            "INSERT INTO users (email, password_hash, is_admin, created_at) VALUES ('c@x.de', 'h', 0, 3);"
        )
        conn.commit()
        conn.close()
        db.DB_PATH = path
        roles = {u.email: u.role for u in users.list_users(users.User(0, "", True, 0, role="owner"))}
        self.assertEqual(roles, {"a@x.de": "owner", "b@x.de": "admin", "c@x.de": "user"})

    # --- pages
    def test_pages_are_filled_and_escape_text(self):
        hostile = users.create_user('<img src=x onerror=1>@example.com', "Start1234")
        for actor in (self.owner, self.admin, self.user):
            for lang in ("de", "en"):
                users.set_profile(actor.id, "", lang)
                fresh = users.get_by_id(actor.id)
                pages = [userspage.password_page(fresh, "<b>err</b>")]
                if fresh.is_admin:
                    pages.append(ui.logged_in_page(fresh, "U", userspage.render(fresh, users.list_users(fresh))))
                for page in pages:
                    self.assertIsNone(re.search(r"%[A-Za-z_.]+%", page.replace("%BODY%</", "")), "placeholder left over")
                    self.assertNotIn("<img src=x", page)
                    self.assertNotIn("<b>err</b>", page)

    def test_drawer_links_depend_on_role(self):
        self.assertIn('href="/users"', ui.settings_bar(self.admin))
        self.assertIn('href="/password"', ui.settings_bar(self.admin))
        self.assertNotIn('href="/users"', ui.settings_bar(self.user))
        self.assertIn('href="/password"', ui.settings_bar(self.user))

    def test_rows_show_only_allowed_buttons(self):
        admin_view = userspage.render(self.admin, users.list_users(self.admin))
        self.assertNotIn("data-admin", admin_view)          # only the owner switches admins
        self.assertEqual(admin_view.count("data-delete"), 1)  # only the normal user
        owner_view = userspage.render(self.owner, users.list_users(self.owner))
        self.assertEqual(owner_view.count("data-admin"), 2)  # admin and user, not himself
        self.assertEqual(owner_view.count("data-delete"), 2)


if __name__ == "__main__":
    unittest.main()
