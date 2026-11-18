"""TaskForge store: rich tasks with persistence (JSON file on disk)."""

import json
import threading
from datetime import date, datetime
from pathlib import Path

PRIORITIES = ("low", "medium", "high")
STATUSES = ("pending", "done")
DEFAULT_FILE = Path(__file__).resolve().parent / "tasks.json"


class TaskError(ValueError):
    """Raised for invalid task input or unknown task ids."""


class TaskStore:
    def __init__(self, path=DEFAULT_FILE):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.data = {"next_id": 1, "tasks": []}
        self._load()

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    def _load(self):
        if self.path.exists():
            try:
                self.data = json.loads(
                    self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self.data = {"next_id": 1, "tasks": []}

    def _save(self):
        self.path.write_text(
            json.dumps(self.data, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------ #
    # Validation helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _check_priority(priority):
        if priority not in PRIORITIES:
            raise TaskError(
                f"priority must be one of {', '.join(PRIORITIES)}")

    @staticmethod
    def _check_due(due):
        if due is None:
            return
        try:
            parsed = date.fromisoformat(due)
        except (TypeError, ValueError):
            raise TaskError("due must be an ISO date like 2026-11-20")
        if parsed < date.today():
            raise TaskError(f"due date {due} is in the past")

    def _find(self, task_id):
        for task in self.data["tasks"]:
            if task["id"] == task_id:
                return task
        raise TaskError(f"No task with id {task_id}")

    # ------------------------------------------------------------------ #
    # Operations
    # ------------------------------------------------------------------ #

    def create(self, title, priority="medium", due=None):
        title = (title or "").strip()
        if not title:
            raise TaskError("title must not be empty")
        if len(title) > 200:
            raise TaskError("title must be at most 200 characters")
        self._check_priority(priority)
        self._check_due(due)
        with self.lock:
            task = {
                "id": self.data["next_id"],
                "title": title,
                "priority": priority,
                "due": due,
                "status": "pending",
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
            self.data["next_id"] += 1
            self.data["tasks"].append(task)
            self._save()
        return task

    def list(self, status=None, priority=None):
        if status is not None and status not in STATUSES:
            raise TaskError(f"status must be one of {', '.join(STATUSES)}")
        if priority is not None:
            self._check_priority(priority)
        with self.lock:
            tasks = list(self.data["tasks"])
        if status is not None:
            tasks = [t for t in tasks if t["status"] == status]
        if priority is not None:
            tasks = [t for t in tasks if t["priority"] == priority]
        order = {p: len(PRIORITIES) - 1 - i
                 for i, p in enumerate(PRIORITIES)}  # high first
        tasks.sort(key=lambda t: (order[t["priority"]], t["id"]))
        return tasks

    def complete(self, task_id):
        with self.lock:
            task = self._find(task_id)
            if task["status"] == "done":
                raise TaskError(f"Task {task_id} is already done")
            task["status"] = "done"
            self._save()
        return task

    def delete(self, task_id):
        with self.lock:
            self._find(task_id)
            self.data["tasks"] = [
                t for t in self.data["tasks"] if t["id"] != task_id]
            self._save()

    def update(self, task_id, title=None, priority=None, due=None):
        with self.lock:
            task = self._find(task_id)
            if title is not None:
                title = title.strip()
                if not title:
                    raise TaskError("title must not be empty")
                task["title"] = title
            if priority is not None:
                self._check_priority(priority)
                task["priority"] = priority
            if due is not None:
                self._check_due(due)
                task["due"] = due
            self._save()
        return task

    def stats(self):
        with self.lock:
            tasks = list(self.data["tasks"])
        today = date.today().isoformat()
        by_status = {s: 0 for s in STATUSES}
        by_priority = {p: 0 for p in PRIORITIES}
        overdue = 0
        for t in tasks:
            by_status[t["status"]] += 1
            if t["status"] == "pending":
                by_priority[t["priority"]] += 1
                if t["due"] and t["due"] < today:
                    overdue += 1
        return {"total": len(tasks), "by_status": by_status,
                "pending_by_priority": by_priority, "overdue": overdue}
