from datetime import datetime

from acceptance import build_remediation_task, explainable_result


class AcceptanceService:
    def __init__(self, *, normalize, text, sync_pct, save, event, outcome=None, learning_outcome=None, companion=None):
        self.normalize, self.text = normalize, text
        self.sync_pct, self.save, self.event, self.outcome, self.learning_outcome = sync_pct, save, event, outcome, learning_outcome
        self.companion = companion

    def persist_result(self, state, idx, result):
        tasks = self.normalize(state.get("tasks", []), state.get("active_goal_id", ""), state.get("done_flags", []))
        if idx < 0 or idx >= len(tasks): return False, "task index out of range"
        result = explainable_result(result)
        tasks[idx]["acceptance_result"] = result
        flags = list(state.get("done_flags", []))
        while len(flags) <= idx: flags.append(False)
        passed = result["status"] == "passed"
        flags[idx] = passed
        tasks[idx]["status"] = "done" if passed else tasks[idx].get("status") or "pending"
        state["tasks"], state["done_flags"] = tasks, flags
        if result["status"] == "failed":
            self.ensure_remediation(state, idx, result)
        if passed and self.outcome: self.outcome(state, "accepted")
        elif result["status"] == "failed" and self.outcome: self.outcome(state, "failed")
        if result["status"] in ("passed", "failed") and self.learning_outcome:
            self.learning_outcome(state, state["tasks"][idx], passed)
        if self.companion and result["status"] != "needs_review":
            self.companion(state, idx, result)
        self.sync_pct(state); self.save(state)
        self.event(state, "task_acceptance", result["status"], {"idx": idx, "status": result["status"]})
        return True, result

    def ensure_remediation(self, state, idx, result=None):
        tasks = state.get("tasks")
        if not isinstance(tasks, list) or idx < 0 or idx >= len(tasks):
            return None
        original = tasks[idx]
        if original.get("source") == "remediation":
            return None
        result = explainable_result(result or original.get("acceptance_result"))
        if result["status"] != "failed":
            return None
        existing = next((item for item in tasks if item.get("source") == "remediation" and item.get("parent_task_id") == original.get("id")), None)
        if existing:
            return existing
        recovery = build_remediation_task(original, result)
        if not recovery:
            return None
        insert_at = idx + 1
        tasks.insert(insert_at, recovery)
        flags = list(state.get("done_flags") or [])
        while len(flags) < len(tasks) - 1:
            flags.append(False)
        flags.insert(insert_at, False)
        state["tasks"] = tasks
        state["done_flags"] = flags
        return recovery

    def manual_accept(self, state, idx, reason="manual approval"):
        tasks = self.normalize(state.get("tasks", []), state.get("active_goal_id", ""), state.get("done_flags", []))
        if idx < 0 or idx >= len(tasks): return False, "task index out of range"
        if tasks[idx].get("skill_id") and not tasks[idx].get("recall_rating"):
            return False, "select recall quality before accepting a learning task"
        reason = self.text(reason) or "manual approval"
        result = explainable_result({"pass": True, "status": "passed", "reason": "manual approval: " + reason,
            "missing": [], "next_steps": [], "evidence_refs": [], "overridden": True,
            "override_reason": reason, "override_ts": datetime.now().isoformat(),
            "confidence": 1.0, "decision": "accepted"})
        return self.persist_result(state, idx, result)[0], "task manually accepted"
