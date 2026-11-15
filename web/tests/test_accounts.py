import os
import re
import sqlite3
import tempfile
import types
import unittest

from app import board, db, projects, ui, userspage, users
from app.routes import accounts


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

    def _count(self, sql, *args):
        with db.connect() as conn:
            return conn.execute(sql, args).fetchone()[0]

    def test_a_deleted_account_is_locked_but_keeps_its_data(self):
        project = projects.create_project(self.user.id, "Mine")
        board.create_item(self.user.id, project.id, "bug", "x")
        token = users.create_session(self.user.id)
        users.delete_user(self.admin, self.user.id)
        self.assertIsNone(users.get_by_id(self.user.id))                       # can not be managed any more
        self.assertIsNone(users.get_user(token))                               # the session ended
        self.assertIsNone(users.check_login("user@example.com", "Start1234"))  # no login
        self.assertNotIn(self.user.id, [u.id for u in users.list_users(self.owner)])
        self.assertEqual(self._count("SELECT COUNT(*) FROM sessions WHERE user_id = ?", self.user.id), 0)
        self.assertEqual(self._count("SELECT COUNT(*) FROM projects WHERE user_id = ?", self.user.id), 1)
        self.assertEqual(len(board.list_items(self.user.id, project.id)), 1)   # nothing of it was touched

    def test_inviting_the_address_again_brings_the_account_back_as_it_was(self):
        project = projects.create_project(self.user.id, "Mine")
        users.set_profile(self.user.id, "Uwe", "en")
        users.delete_user(self.admin, self.user.id, now=1000)
        back = users.add_user(self.owner, " User@Example.com ", "Neustart1")
        self.assertEqual(back.id, self.user.id)                                # the same account, not a new one
        self.assertEqual((back.display_name, back.language, back.role), ("Uwe", "en", "user"))
        self.assertTrue(back.must_change)
        self.assertIsNone(users.check_login("user@example.com", "Start1234"))  # the old password is gone
        self.assertIsNotNone(users.check_login("user@example.com", "Neustart1"))
        self.assertEqual([p.id for page in projects.layout(back.id) for p in page], [project.id])
        self.assertEqual(users.purge_deleted(now=10**10), 0)                   # it is not deleted any more

    def test_a_deleted_admin_comes_back_as_a_normal_user(self):
        users.delete_user(self.owner, self.admin.id)
        back = users.add_user(self.owner, "admin@example.com", "Neustart1")
        self.assertEqual((back.id, back.role, back.is_admin), (self.admin.id, "user", False))

    def test_after_the_time_nothing_of_the_account_is_left(self):
        project = projects.create_project(self.user.id, "Mine")
        board.create_item(self.user.id, project.id, "bug", "x")
        users.delete_user(self.admin, self.user.id, now=1000)
        day = 86400
        self.assertEqual(users.purge_deleted(now=1000 + users.DELETED_DAYS * day - 5), 0)    # not yet
        self.assertEqual(self._count("SELECT COUNT(*) FROM users WHERE id = ?", self.user.id), 1)
        self.assertEqual(users.purge_deleted(now=1000 + users.DELETED_DAYS * day + 5), 1)
        for table, column in (("users", "id"), ("projects", "user_id"), ("sessions", "user_id"),
                              ("agent_settings", "user_id"), ("chat_archive", "user_id")):
            self.assertEqual(self._count(f"SELECT COUNT(*) FROM {table} WHERE {column} = ?", self.user.id), 0, table)
        self.assertEqual(self._count("SELECT COUNT(*) FROM board_items WHERE project_id = ?", project.id), 0)
        self.assertEqual(self._count("SELECT COUNT(*) FROM users WHERE email = 'user@example.com'"), 0)
        new = users.add_user(self.owner, "user@example.com", "Neustart1")     # a later invitation is a new account
        self.assertNotEqual(new.id, self.user.id)
        self.assertEqual(projects.layout(new.id), [])

    def test_the_time_to_bring_an_account_back_ends_before_an_invitation(self):
        users.delete_user(self.admin, self.user.id)
        with db.connect() as conn:
            conn.execute("UPDATE users SET deleted_at = 1000 WHERE id = ?", (self.user.id,))   # long ago
        new = users.add_user(self.owner, "user@example.com", "Neustart1")
        self.assertNotEqual(new.id, self.user.id)

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

    def test_drawer_has_one_text_link_and_a_quiet_button_for_the_administration(self):
        for who in (self.owner, self.admin):
            bar = ui.settings_bar(who)
            self.assertIn('<a class="admin-btn" href="/admin">Verwaltung</a>', bar)
            self.assertLess(bar.index('class="admin-btn"'), bar.index('class="primary save"'))   # above "Save"
        self.assertNotIn("/admin", ui.settings_bar(self.user))                                 # normal users: no button at all
        for who in (self.owner, self.admin, self.user):
            bar = ui.settings_bar(who)
            self.assertIn('href="/password"', bar)
            self.assertEqual(bar.count('<a class="link"'), 1)                                  # only "change password"
            for old in ('href="/users"', 'href="/system"'):
                self.assertNotIn(old, bar)

    def test_rows_show_only_allowed_buttons(self):
        admin_view = userspage.render(self.admin, users.list_users(self.admin))
        self.assertNotIn("data-admin", admin_view)          # only the owner switches admins
        self.assertEqual(admin_view.count("data-delete"), 1)  # only the normal user
        owner_view = userspage.render(self.owner, users.list_users(self.owner))
        self.assertEqual(owner_view.count("data-admin"), 2)  # admin and user, not himself
        self.assertEqual(owner_view.count("data-delete"), 2)


class OwnerTransferTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.owner = users.create_user("owner@example.com", "Own3r!pass", role="owner")
        self.admin = users.create_user("admin@example.com", "Adm1n!pass", role="admin")
        self.fresh = users.add_user(self.owner, "fresh@example.com", "Start1234")   # still a start password
        self.user = users.add_user(self.owner, "user@example.com", "Start1234")
        users.change_own_password(self.user, "", "Mein!Pass12")
        self.user = users.get_by_id(self.user.id)

    def tearDown(self):
        self.tmp.cleanup()

    def roles(self):
        return {u.email.split("@")[0]: u.role for u in users.list_users(self.owner)}

    def owners(self):
        with db.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM users WHERE role = 'owner'").fetchone()[0]

    def request(self):
        return types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="203.0.113.7"))

    def test_the_owner_hands_over_and_becomes_admin(self):
        users.transfer_owner(self.owner, self.admin.id)
        self.assertEqual(self.roles()["admin"], "owner")
        self.assertEqual(self.roles()["owner"], "admin")
        self.assertEqual(self.owners(), 1)
        self.assertTrue(users.get_by_id(self.owner.id).is_admin)   # is_admin stays in step with role

    def test_a_normal_user_can_become_owner(self):
        users.transfer_owner(self.owner, self.user.id)
        new_owner = users.get_by_id(self.user.id)
        self.assertEqual((new_owner.role, new_owner.is_admin), ("owner", True))
        self.assertEqual(users.get_by_id(self.owner.id).role, "admin")
        self.assertEqual(self.owners(), 1)

    def test_the_new_owner_has_the_owner_rights_and_the_old_one_lost_them(self):
        users.transfer_owner(self.owner, self.admin.id)
        new_owner, old_owner = users.get_by_id(self.admin.id), users.get_by_id(self.owner.id)
        self.assertTrue(users.can_manage(new_owner, old_owner))
        self.assertFalse(users.can_manage(old_owner, new_owner))
        with self.assertRaises(PermissionError):
            users.set_admin(old_owner, self.user.id, True)
        users.set_admin(new_owner, self.user.id, True)

    def test_sessions_stay_and_the_old_object_cannot_repeat_it(self):
        token = users.create_session(self.owner.id)
        users.transfer_owner(self.owner, self.admin.id)
        self.assertEqual(users.get_user(token).role, "admin")   # still logged in, with the new role
        with self.assertRaises(PermissionError):                # self.owner is out of date now
            users.transfer_owner(self.owner, self.user.id)
        self.assertEqual(self.owners(), 1)
        self.assertEqual(self.roles()["admin"], "owner")

    def test_refused_cases_change_nothing(self):
        before = self.roles()
        with self.assertRaises(PermissionError):
            users.transfer_owner(self.admin, self.user.id)         # only the owner
        with self.assertRaises(PermissionError):
            users.transfer_owner(self.user, self.admin.id)
        with self.assertRaises(PermissionError):
            users.transfer_owner(self.owner, self.owner.id)        # not to himself
        with self.assertRaises(users.UserError) as missing:
            users.transfer_owner(self.owner, 9999)
        self.assertEqual(missing.exception.code, "not_found")
        with self.assertRaises(users.UserError) as not_ready:
            users.transfer_owner(self.owner, self.fresh.id)        # no own password yet
        self.assertEqual(not_ready.exception.code, "not_ready")
        self.assertEqual(self.roles(), before)

    def test_there_can_never_be_two_owners(self):
        with self.assertRaises(users.UserError) as second:
            users.create_user("second@example.com", "Own3r!pass", role="owner")
        self.assertEqual(second.exception.code, "owner_exists")
        with db.connect() as conn:     # the database refuses it as well
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE users SET role = 'owner' WHERE id = ?", (self.admin.id,))
        self.assertEqual(self.owners(), 1)

    def test_the_owner_is_not_tied_to_one_account(self):
        users.transfer_owner(self.owner, self.admin.id)
        users.transfer_owner(users.get_by_id(self.admin.id), self.owner.id)   # and back again
        self.assertEqual(self.roles()["owner"], "owner")
        self.assertEqual(self.owners(), 1)

    # --- the route (password asked first)
    def test_route_needs_the_owners_password(self):
        answer = accounts.make_owner(self.request(), self.admin.id, "wrong", self.owner)
        self.assertEqual(answer.status_code, 403)
        self.assertEqual(self.roles()["owner"], "owner")
        answer = accounts.make_owner(self.request(), self.admin.id, "Own3r!pass", self.owner)
        self.assertEqual(answer, {"ok": True})
        self.assertEqual(self.roles()["admin"], "owner")

    def test_route_is_for_the_owner_only(self):
        self.assertEqual(accounts.make_owner(self.request(), self.user.id, "Adm1n!pass", self.admin).status_code, 403)
        self.assertEqual(self.roles()["owner"], "owner")

    def test_route_messages(self):
        not_ready = accounts.make_owner(self.request(), self.fresh.id, "Own3r!pass", self.owner)
        self.assertEqual(not_ready.status_code, 400)
        self.assertEqual(accounts.make_owner(self.request(), 9999, "Own3r!pass", self.owner).status_code, 404)

    # --- the page
    def test_button_only_for_the_owner_and_only_for_accounts_that_can_log_in(self):
        owner_view = userspage.render(self.owner, users.list_users(self.owner))
        self.assertEqual(owner_view.count("data-owner"), 2)     # admin and settled user, not the start-password one
        self.assertIn('id="owner-dialog"', owner_view)
        admin_view = userspage.render(self.admin, users.list_users(self.admin))
        self.assertNotIn("data-owner", admin_view)

    def test_the_index_exists_after_migration(self):
        with db.connect() as conn:
            names = [row["name"] for row in conn.execute("PRAGMA index_list(users)")]
        self.assertIn("users_one_owner", names)


if __name__ == "__main__":
    unittest.main()
