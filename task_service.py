from datetime import datetime
import time


class TaskService:
    """Task mutations independent from HTTP transport."""

    def __init__(self, *, text, normalize, goal_id, sync_pct, save, event, undo, compact, outcome=None, readiness=None, first_task_started=None, companion=None):
        self.text, self.normalize = text, normalize
        self.goal_id = goal_id
        self.sync_pct, self.save, self.event, self.undo, self.compact, self.outcome = sync_pct, save, event, undo, compact, outcome
        self.readiness, self.first_task_started, self.companion = readiness, first_task_started, companion

    def _ready(self, state):
        return not self.readiness or bool(self.readiness(state).get("ready"))

    def set_status(self, state, idx, status, continuation_note="", next_action=""):
        tasks = self.normalize(state.get("tasks", []), self.goal_id(state), state.get("done_flags", []))
        if idx < 0 or idx >= len(tasks): return False, "task index out of range"
        if status not in ("pending", "doing", "paused", "partial", "skipped"): return False, "invalid task status"
        self.undo(state, "task state")
        task = tasks[idx]
        previous_status = task.get("status")
        if status == "doing" and task.get("status") != "doing":
            task["started_at"] = datetime.now().isoformat(); task["attempts"] = int(task.get("attempts", 0) or 0) + 1
            if self.first_task_started and not any(item.get("started_at") for item in tasks if item is not task):
                self.first_task_started(state, task, idx)
        elif task.get("status") == "doing" and task.get("started_at"):
            try:
                previous_seconds = float(task.get("actual_seconds", 0) or 0)
                task["actual_seconds"] = round(previous_seconds + max(0, time.time() - datetime.fromisoformat(task["started_at"]).timestamp()), 3)
            except (TypeError, ValueError): pass
            task["ended_at"] = datetime.now().isoformat()
        if status == "partial": task["continuation_note"] = self.text(continuation_note)[:500]
        if next_action: task["next_action"] = self.text(next_action)[:500]
        task["status"] = status; state["tasks"] = tasks
        if self.outcome and status != previous_status and status in {"partial", "skipped"}:
            self.outcome(state, status)
        if self.companion:
            self.companion(state, idx, previous_status, status)
        self.sync_pct(state); self.save(state); self.event(state, "task_state", status, {"idx": idx}); self.compact(state)
        return True, "task state updated"

    def replace(self, state, raw_tasks, reason=""):
        if not isinstance(raw_tasks, list) or not any(self.text(x) for x in raw_tasks): return False, "task list cannot be empty"
        if state.get("plan_locked") and not self.text(reason): return False, "plan is locked; provide a reason"
        state["tasks"] = self.normalize(raw_tasks, self.goal_id(state), state.get("done_flags", []))
        flags = state.get("done_flags", []); state["done_flags"] = flags[:len(state["tasks"])] + [False] * max(0, len(state["tasks"]) - len(flags))
        self.sync_pct(state); self.save(state); self.event(state, "task_edit", self.text(reason)); self.compact(state)
        return True, "ok"
