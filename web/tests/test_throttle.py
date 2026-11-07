import os
import tempfile
import unittest
from types import SimpleNamespace

from app import db, throttle


class ThrottleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")

    def tearDown(self):
        self.tmp.cleanup()

    def fail(self, ip, times, at=1000):
        for i in range(times):
            throttle.record_failure(ip, now=at + i)

    def test_nine_failures_do_not_lock(self):
        self.fail("1.2.3.4", throttle.MAX_FAILURES - 1)
        self.assertEqual(throttle.seconds_locked("1.2.3.4", now=1100), 0)

    def test_tenth_failure_locks_for_an_hour(self):
        self.fail("1.2.3.4", throttle.MAX_FAILURES)
        wait = throttle.seconds_locked("1.2.3.4", now=1010)
        self.assertGreater(wait, throttle.LOCK_SECONDS - 20)
        self.assertLessEqual(wait, throttle.LOCK_SECONDS)

    def test_lock_ends(self):
        self.fail("1.2.3.4", throttle.MAX_FAILURES)
        self.assertEqual(throttle.seconds_locked("1.2.3.4", now=1010 + throttle.LOCK_SECONDS), 0)

    def test_other_ips_are_not_affected(self):
        self.fail("1.2.3.4", throttle.MAX_FAILURES)
        self.assertEqual(throttle.seconds_locked("5.6.7.8", now=1010), 0)

    def test_old_failures_are_forgotten(self):
        self.fail("1.2.3.4", throttle.MAX_FAILURES - 1, at=1000)
        later = 1000 + throttle.WINDOW_SECONDS + 10
        throttle.record_failure("1.2.3.4", now=later)  # starts a new window: 1 failure, not 10
        self.assertEqual(throttle.seconds_locked("1.2.3.4", now=later), 0)

    def test_minutes_round_up(self):
        self.assertEqual(throttle.minutes(1), 1)
        self.assertEqual(throttle.minutes(60), 1)
        self.assertEqual(throttle.minutes(61), 2)
        self.assertEqual(throttle.minutes(3600), 60)

    def test_client_ip_prefers_cloudflare_header(self):
        request = SimpleNamespace(headers={"cf-connecting-ip": " 9.9.9.9 "}, client=SimpleNamespace(host="172.18.0.2"))
        self.assertEqual(throttle.client_ip(request), "9.9.9.9")
        request = SimpleNamespace(headers={}, client=SimpleNamespace(host="172.18.0.2"))
        self.assertEqual(throttle.client_ip(request), "172.18.0.2")


if __name__ == "__main__":
    unittest.main()
