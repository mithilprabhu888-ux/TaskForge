import unittest
import tempfile
from pathlib import Path

from task_store import TaskError, TaskStore


def make_store():
    tmp = Path(tempfile.mkdtemp())
    return TaskStore(tmp / "tasks.json")


class TaskStoreTest(unittest.TestCase):
    def setUp(self):
        self.store = make_store()

    def test_create_and_list(self):
        self.store.create("Ship demo", priority="high", due="2999-01-01")
        self.store.create("Read paper", priority="low")
        tasks = self.store.list()
        self.assertEqual([t["title"] for t in tasks],
                         ["Ship demo", "Read paper"])  # high first
        pending = self.store.list(status="pending")
        self.assertEqual(len(pending), 2)
        done = self.store.list(status="done")
        self.assertEqual(done, [])

    def test_ids_increment(self):
        a = self.store.create("A")
        b = self.store.create("B")
        self.assertEqual(b["id"], a["id"] + 1)

    def test_complete_flow(self):
        task = self.store.create("Write tests")
        done = self.store.complete(task["id"])
        self.assertEqual(done["status"], "done")
        with self.assertRaises(TaskError):
            self.store.complete(task["id"])          # already done
        self.assertEqual(len(self.store.list(status="done")), 1)

    def test_update_and_delete(self):
        task = self.store.create("Old title", priority="low")
        updated = self.store.update(task["id"], title="New title",
                                    priority="high")
        self.assertEqual(updated["title"], "New title")
        self.assertEqual(updated["priority"], "high")
        self.store.delete(task["id"])
        self.assertEqual(self.store.list(), [])
        with self.assertRaises(TaskError):
            self.store.delete(task["id"])

    def test_validation(self):
        with self.assertRaises(TaskError):
            self.store.create("   ")                  # empty title
        with self.assertRaises(TaskError):
            self.store.create("X", priority="urgent")  # bad priority
        with self.assertRaises(TaskError):
            self.store.create("X", due="20-01-01")    # bad date
        with self.assertRaises(TaskError):
            self.store.create("X", due="1999-01-01")  # past date
        self.assertEqual(self.store.list(), [])

    def test_stats_and_overdue(self):
        self.store.create("Overdue", priority="high", due="2999-01-01")
        self.store.create("Fine", priority="low", due="2999-06-01")
        self.store.create("Done thing", priority="low")
        self.store.complete(3)
        stats = self.store.stats()
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["by_status"]["pending"], 2)
        self.assertEqual(stats["by_status"]["done"], 1)
        self.assertEqual(stats["pending_by_priority"]["high"], 1)
        self.assertEqual(stats["overdue"], 0)   # both due dates are future

        # Simulate a task that became overdue after creation (the store
        # rejects past dates at create/update time, so edit the file).
        raw = self.store.path.read_text(encoding="utf-8")
        self.store.path.write_text(raw.replace("2999-01-01", "2000-01-01"),
                                   encoding="utf-8")
        reloaded = TaskStore(self.store.path)
        self.assertEqual(reloaded.stats()["overdue"], 1)

    def test_persistence_across_instances(self):
        task = self.store.create("Survives restart")
        again = TaskStore(self.store.path)
        found = again.list()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["title"], "Survives restart")
        again.complete(task["id"])
        reloaded = TaskStore(self.store.path)
        self.assertEqual(reloaded.list(status="done")[0]["id"], task["id"])


if __name__ == "__main__":
    unittest.main()
