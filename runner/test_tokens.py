"""The saved Claude tokens and the tickets of the runs. Needs the package `cryptography` (runner image).

    docker run --rm -v "$PWD/runner:/app/runner" agent-hub-hub-runner python -W ignore -m unittest runner.test_tokens
"""
import os
import tempfile
import time
import unittest
from pathlib import Path

from runner import tokens

TOKEN = "sk-ant-oat01-" + "a" * 90


def key():
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()


class VaultTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.vault = tokens.Vault(self.base, key())

    def tearDown(self):
        self.tmp.cleanup()

    def test_saved_encrypted_and_read_back(self):
        self.vault.save(2, TOKEN)
        raw = (self.base / "2" / tokens.TOKEN_FILE).read_bytes()
        self.assertNotIn(b"sk-ant", raw)                                      # never in plain text on the card
        self.assertNotIn(TOKEN[-40:].encode(), raw)
        self.assertEqual(self.vault.load(2), TOKEN)
        self.assertEqual((self.base / "2" / tokens.TOKEN_FILE).stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.base / "2").stat().st_mode & 0o777, 0o700)

    def test_each_user_has_his_own(self):
        self.vault.save(2, TOKEN)
        self.assertIsNone(self.vault.load(3))
        self.vault.save(3, "sk-ant-oat01-" + "b" * 90)
        self.assertEqual(self.vault.load(2), TOKEN)

    def test_without_the_key_nothing_can_be_read(self):
        self.vault.save(2, TOKEN)
        for other in (key(), None):   # another key, no key: the token is there but unreadable, never "none"
            with self.assertRaises(tokens.Unreadable):
                tokens.Vault(self.base, other).load(2)
        self.assertEqual(self.vault.load(2), TOKEN)                          # and it is still there
        with self.assertRaises(RuntimeError):
            tokens.Vault(self.base, None).save(2, TOKEN)

    def test_only_tokens_are_taken(self):
        for bad in ("", "hello", "sk-ant-api03-" + "x" * 90, TOKEN + " ; rm -rf /", None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.vault.save(2, bad)
        for bad in (0, -1, "2", True):
            with self.assertRaises(ValueError):
                self.vault.save(bad, TOKEN)

    def test_forget_deletes_the_folder_with_the_token(self):
        self.vault.save(2, TOKEN)
        self.assertTrue(self.vault.forget(2))
        self.assertFalse((self.base / "2").exists())
        self.assertFalse(self.vault.forget(2))
        self.assertIsNone(self.vault.load(2))


class TicketTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.tickets = tokens.Tickets(self.dir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_ticket_stands_for_the_token_until_it_is_revoked(self):
        ticket = self.tickets.issue(TOKEN)
        self.assertRegex(ticket, tokens.TICKET)
        self.assertNotIn(TOKEN, ticket)
        self.assertEqual(tokens.lookup(self.dir, ticket), TOKEN)
        self.assertNotIn(ticket, " ".join(os.listdir(self.dir)))             # the folder holds hashes, not tickets
        self.tickets.revoke(ticket)
        self.assertIsNone(tokens.lookup(self.dir, ticket))

    def test_every_ticket_is_new(self):
        self.assertNotEqual(self.tickets.issue(TOKEN), self.tickets.issue(TOKEN))

    def test_unknown_malformed_and_old_tickets_count_for_nothing(self):
        ticket = self.tickets.issue(TOKEN)
        self.assertIsNone(tokens.lookup(self.dir, "hubrun-" + "Z" * 43))
        for bad in ("", "Bearer x", TOKEN, ticket + "x", "../" + ticket, None):
            self.assertIsNone(tokens.lookup(self.dir, bad), repr(bad))
        self.assertIsNone(tokens.lookup(self.dir, ticket, now=time.time() + tokens.TICKET_AGE + 5))

    def test_sweep(self):
        ticket = self.tickets.issue(TOKEN)
        self.tickets.sweep()                                                  # young: stays
        self.assertEqual(tokens.lookup(self.dir, ticket), TOKEN)
        self.tickets.sweep(max_age=0)                                         # at the start of the runner: all go
        self.assertEqual(os.listdir(self.dir), [])

    def test_only_tokens_get_tickets(self):
        with self.assertRaises(ValueError):
            self.tickets.issue("not a token")


if __name__ == "__main__":
    unittest.main()
