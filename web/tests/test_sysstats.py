"""Live numbers of the server on the administration page (23.11.2026): reading, formatting, who may ask."""
import os
import tempfile
import unittest

from app import db, i18n, sysstats, systempage, users
from app.routes import system as system_routes

MEMINFO = "MemTotal:        1000448 kB\nMemFree:           50000 kB\nMemAvailable:     250112 kB\nBuffers: 1 kB\n"


class ReadingTest(unittest.TestCase):
    def test_memory_free_is_what_is_available(self):
        self.assertEqual(sysstats.memory(MEMINFO), {"total_mb": 977, "free_mb": 244, "used_pct": 75})

    def test_memory_without_available_falls_back_to_free(self):
        self.assertEqual(sysstats.memory("MemTotal: 2048 kB\nMemFree: 1024 kB\n")["free_mb"], 1)

    def test_cpu_is_the_share_of_work_between_two_readings(self):
        readings = iter([(1000, 800), (1100, 850)])   # 100 ticks passed, 50 of them idle
        sysstats._last = None
        self.assertEqual(sysstats.cpu(read=lambda: next(readings), pause=0)["used_pct"], 50)

    def test_cpu_is_shared_within_a_second(self):
        sysstats._last = None
        readings = iter([(0, 0), (100, 0)])
        first = sysstats.cpu(read=lambda: next(readings), pause=0)["used_pct"]
        self.assertEqual(sysstats.cpu(read=lambda: self.fail("read again"), pause=0)["used_pct"], first)

    def test_temperature_none_when_the_machine_does_not_tell(self):
        self.assertIsNone(sysstats.temperature("/nonexistent/temp"))
        with tempfile.NamedTemporaryFile("w", suffix=".txt") as f:
            f.write("61250\n")
            f.flush()
            self.assertEqual(sysstats.temperature(f.name), 61.25)

    def test_disk_numbers_add_up(self):
        d = sysstats.disk(tempfile.gettempdir())
        self.assertTrue(0 <= d["used_pct"] <= 100 and d["free_gb"] <= d["total_gb"])


class PageTest(unittest.TestCase):
    STATS = {"memory": {"total_mb": 949, "free_mb": 412, "used_pct": 57}, "cpu": {"used_pct": 93, "cores": 4},
             "temp_c": 72.4, "disk": {"total_gb": 31.9, "free_gb": 12.34, "used_pct": 61}}

    def test_the_meters_are_formatted_in_the_users_language(self):
        de = {m["key"]: m for m in systempage.meters("de", self.STATS)}
        self.assertEqual(de["memory"]["text"], "412 MB frei von 949 MB")
        self.assertEqual(de["disk"]["text"], "12,3 GB frei von 31,9 GB")
        self.assertEqual((de["cpu"]["level"], de["temp"]["level"], de["memory"]["level"]), ("high", "warn", "ok"))
        en = {m["key"]: m for m in systempage.meters("en", self.STATS)}
        self.assertEqual(en["disk"]["text"], "12.3 GB free of 31.9 GB")

    def test_a_missing_temperature_is_left_out(self):
        keys = [m["key"] for m in systempage.meters("de", {**self.STATS, "temp_c": None})]
        self.assertEqual(keys, ["memory", "cpu", "disk"])

    def test_both_languages_have_all_texts(self):
        for key in ("sys_stat_memory", "sys_stat_cpu", "sys_stat_temp", "sys_stat_disk", "sys_stat_free_of",
                    "sys_stat_busy"):
            self.assertIn(key, i18n.STRINGS["de"])
            self.assertIn(key, i18n.STRINGS["en"])


class RouteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.owner = users.create_user("owner@example.com", "Own3r!pass", role="owner")
        self.admin = users.create_user("admin@example.com", "Adm1n!pass", role="admin")

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_owner_and_superadmin_get_the_numbers(self):
        self.assertTrue(system_routes.stats(user=self.owner)["ok"])
        self.assertEqual(system_routes.stats(user=self.admin).status_code, 403)

    def test_the_system_block_shows_the_row(self):
        html = systempage.render(self.owner)
        self.assertIn('id="sys-stats" data-url="/system/stats"', html)
        self.assertIn('data-key="memory"', html)
