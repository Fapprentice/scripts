from datetime import datetime


class AcceptanceService:
    def __init__(self, *, normalize, text, sync_pct, save, event, outcome=None, learning_outcome=None):
        self.normalize, self.text = normalize, text
        self.sync_pct, self.save, self.event, self.outcome, self.learning_outcome = sync_pct, save, event, outcome, learning_outcome

    def manual_accept(self, state, idx, reason="manual approval"):
        tasks = self.normalize(state.get("tasks", []), state.get("active_goal_id", ""), state.get("done_flags", []))
        if idx < 0 or idx >= len(tasks): return False, "task index out of range"
        if tasks[idx].get("skill_id") and not tasks[idx].get("recall_rating"):
            return False, "select recall quality before accepting a learning task"
        reason = self.text(reason) or "manual approval"
        tasks[idx]["acceptance_result"] = {"pass": True, "reason": "manual approval: " + reason,
            "missing": [], "next_steps": [], "evidence_refs": [], "overridden": True,
            "override_reason": reason, "override_ts": datetime.now().isoformat(),
            "confidence": 1.0, "decision": "accepted"}
        flags = state.get("done_flags", [])
        while len(flags) <= idx: flags.append(False)
        flags[idx] = True; tasks[idx]["status"] = "done"
        state["tasks"], state["done_flags"] = tasks, flags
        if self.outcome: self.outcome(state, "accepted")
        if self.learning_outcome: self.learning_outcome(state, tasks[idx], True)
        self.sync_pct(state); self.save(state)
        self.event(state, "manual_accept", "manual task approval", {"idx": idx, "reason": reason})
        return True, "task manually accepted"
