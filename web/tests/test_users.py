import os
import tempfile
import unittest

from app import users


class UsersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        users.DB_PATH = os.path.join(self.tmp.name, "test.db")
        users.create_user("Janis@Example.com", "correct horse")

    def tearDown(self):
        self.tmp.cleanup()

    def test_correct_password(self):
        user = users.check_login("janis@example.com", "correct horse")
        self.assertIsNotNone(user)
        self.assertEqual(user.email, "janis@example.com")

    def test_email_is_case_insensitive(self):
        self.assertIsNotNone(users.check_login("  JANIS@example.COM ", "correct horse"))

    def test_wrong_password(self):
        self.assertIsNone(users.check_login("janis@example.com", "wrong"))

    def test_unknown_email(self):
        self.assertIsNone(users.check_login("nobody@example.com", "correct horse"))

    def test_duplicate_email_rejected(self):
        with self.assertRaises(ValueError):
            users.create_user("janis@example.com", "another password")

    def test_short_password_rejected(self):
        with self.assertRaises(ValueError):
            users.create_user("new@example.com", "short")

    def test_session_roundtrip(self):
        user = users.check_login("janis@example.com", "correct horse")
        token = users.create_session(user.id)
        self.assertEqual(users.get_user(token), user)
        users.delete_session(token)
        self.assertIsNone(users.get_user(token))


if __name__ == "__main__":
    unittest.main()
