from feedback_service import FeedbackService


def test_feedback_service_persists_decision():
    calls = []
    service = FeedbackService(
        record=lambda state, idx, text, kind: {"reason": text, "kind": kind},
        done=lambda task: task.get("done", False),
        sync_pct=lambda state: calls.append("sync"),
        save=lambda state: calls.append("save"),
        event=lambda *args: calls.append("event"),
        compact=lambda state: calls.append("compact"),
    )
    state = {"tasks": [{"done": True}]}
    assert service.submit(state, 0, "blocked", "too_hard")["reason"] == "blocked"
    assert calls == ["sync", "save", "event", "compact"]
