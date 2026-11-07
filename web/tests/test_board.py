import os
import tempfile
import unittest

from app import board, db, projects, users


class BoardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        self.me = users.create_user("me@example.com", "correct horse")
        self.other = users.create_user("other@example.com", "correct horse")
        self.project = projects.create_project(self.me.id, "P")
        self.foreign = projects.create_project(self.other.id, "Q")

    def tearDown(self):
        self.tmp.cleanup()

    def titles(self, status=None, kind=None):
        items = board.list_items(self.me.id, self.project.id)
        return [i.title for i in items
                if (status is None or i.status == status) and (kind is None or i.kind == kind)]

    def add(self, title, kind="bug"):
        return board.create_item(self.me.id, self.project.id, kind, title)

    def test_new_manual_items_go_to_the_top(self):
        for title in ("A", "B", "C"):
            self.add(title)
        self.assertEqual(self.titles("open", "bug"), ["C", "B", "A"])
        self.assertTrue(all(i.source == "user" for i in board.list_items(self.me.id, self.project.id)))

    def test_title_and_kind_are_validated(self):
        with self.assertRaises(ValueError):
            self.add("   ")
        with self.assertRaises(ValueError):
            self.add("x" * 201)
        with self.assertRaises(ValueError):
            self.add("ok", kind="nonsense")

    def test_cannot_add_to_foreign_project(self):
        with self.assertRaises(ValueError):
            board.create_item(self.me.id, self.foreign.id, "bug", "Nope")
        self.assertEqual(board.list_items(self.me.id, self.foreign.id), [])

    def test_suggestion_accept_goes_below_agreed_items(self):
        self.add("Mine")
        item = board.create_suggestion(self.me.id, self.project.id, "minor", "Idea")
        self.assertEqual(item.status, "proposed")
        mine = board.create_item(self.me.id, self.project.id, "minor", "Mine minor")
        self.assertTrue(board.accept(self.me.id, item.id))
        self.assertEqual(self.titles("open", "minor"), ["Mine minor", "Idea"])
        self.assertTrue(mine.id)

    def test_agent_bug_needs_no_approval(self):
        self.add("Mine")
        bug = board.create_suggestion(self.me.id, self.project.id, "bug", "Found by Claude")
        self.assertEqual((bug.status, bug.source), ("open", "claude"))
        self.assertEqual(self.titles("open", "bug"), ["Found by Claude", "Mine"])   # on top
        self.assertEqual(self.titles("proposed"), [])
        self.assertTrue(board.discard(self.me.id, bug.id))
        self.assertTrue(board.restore(self.me.id, bug.id))
        self.assertEqual(self.titles("open", "bug"), ["Found by Claude", "Mine"])   # open again, not "proposed"

    def test_archive_and_restore(self):
        item = self.add("Done thing")
        self.assertFalse(board.archive(self.other.id, item.id))
        self.assertTrue(board.archive(self.me.id, item.id))
        self.assertEqual(self.titles("archived"), ["Done thing"])
        self.assertFalse(board.archive(self.me.id, item.id))            # only open items
        self.assertFalse(board.delete_item(self.me.id, item.id))        # no way to delete from the archive
        self.assertEqual(board.empty_trash(self.me.id, self.project.id), 0)
        self.assertEqual(self.titles("archived"), ["Done thing"])
        self.assertTrue(board.restore(self.me.id, item.id))
        self.assertEqual(self.titles("open", "bug"), ["Done thing"])

    def test_archived_items_cannot_be_reordered_or_accepted(self):
        item = self.add("Done thing")
        board.archive(self.me.id, item.id)
        with self.assertRaises(ValueError):
            board.reorder(self.me.id, "bug", [item.id])
        self.assertFalse(board.accept(self.me.id, item.id))
        self.assertFalse(board.reject(self.me.id, item.id))

    def test_reject_restore_and_delete_flow(self):
        item = board.create_suggestion(self.me.id, self.project.id, "minor", "Idea")
        self.assertTrue(board.reject(self.me.id, item.id))
        self.assertEqual(self.titles("trash"), ["Idea"])
        self.assertTrue(board.restore(self.me.id, item.id))
        self.assertEqual(self.titles("proposed"), ["Idea"])  # suggestion waits again
        board.reject(self.me.id, item.id)
        self.assertTrue(board.delete_item(self.me.id, item.id))
        self.assertEqual(self.titles(), [])

    def test_discarded_manual_item_is_restored_as_open(self):
        item = self.add("Mine")
        self.assertTrue(board.discard(self.me.id, item.id))
        self.assertTrue(board.restore(self.me.id, item.id))
        self.assertEqual(self.titles("open"), ["Mine"])

    def test_delete_only_works_in_the_trash(self):
        item = self.add("Keep")
        self.assertFalse(board.delete_item(self.me.id, item.id))
        self.assertEqual(self.titles(), ["Keep"])

    def test_empty_trash_removes_only_trashed_items(self):
        keep = self.add("Keep")
        gone = self.add("Gone")
        board.discard(self.me.id, gone.id)
        self.assertEqual(board.empty_trash(self.me.id, self.project.id), 1)
        self.assertEqual(self.titles(), ["Keep"])
        self.assertEqual(board.empty_trash(self.me.id, self.foreign.id), 0)
        self.assertTrue(keep.id)

    def test_reorder_within_and_across_columns(self):
        a, b, c = self.add("A"), self.add("B"), self.add("C")
        board.reorder(self.me.id, "bug", [a.id, b.id, c.id])
        self.assertEqual(self.titles("open", "bug"), ["A", "B", "C"])
        board.reorder(self.me.id, "major", [b.id])  # B moves to another column
        self.assertEqual(self.titles("open", "bug"), ["A", "C"])
        self.assertEqual(self.titles("open", "major"), ["B"])

    def test_reorder_rejects_foreign_proposed_and_duplicate_ids(self):
        mine = self.add("Mine")
        suggestion = board.create_suggestion(self.me.id, self.project.id, "minor", "Idea")
        theirs = board.create_item(self.other.id, self.foreign.id, "bug", "Theirs")
        for ids in ([mine.id, theirs.id], [mine.id, suggestion.id], [mine.id, mine.id]):
            with self.assertRaises(ValueError):
                board.reorder(self.me.id, "bug", ids)
        with self.assertRaises(ValueError):
            board.reorder(self.me.id, "nonsense", [mine.id])

    def test_actions_on_foreign_items_do_nothing(self):
        theirs = board.create_item(self.other.id, self.foreign.id, "bug", "Theirs")
        self.assertFalse(board.discard(self.me.id, theirs.id))
        self.assertIsNone(board.update_title(self.me.id, theirs.id, "Hacked"))
        self.assertEqual(board.list_items(self.other.id, self.foreign.id)[0].title, "Theirs")

    def test_rename(self):
        item = self.add("Old")
        self.assertEqual(board.update_title(self.me.id, item.id, "  New "), self.project.id)
        self.assertEqual(self.titles(), ["New"])
        with self.assertRaises(ValueError):
            board.update_title(self.me.id, item.id, "")

    def test_deleting_a_project_removes_its_items(self):
        self.add("A")
        projects.delete_project(self.me.id, self.project.id)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM board_items").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
