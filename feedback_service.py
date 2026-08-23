class FeedbackService:
    def __init__(self, *, record, done, sync_pct, save, event, compact):
        self.record, self.done = record, done
        self.sync_pct, self.save, self.event, self.compact = sync_pct, save, event, compact

    def submit(self, state, idx, text, kind=""):
        decision = self.record(state, idx, text, kind)
        state["done_flags"] = [self.done(task) for task in state.get("tasks", [])]
        self.sync_pct(state); self.save(state)
        self.event(state, "user_feedback", decision.get("reason", ""), decision)
        self.compact(state)
        return decision
