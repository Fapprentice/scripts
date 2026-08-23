from acceptance_service import AcceptanceService


def test_manual_accept_marks_task_done():
    calls = []
    service = AcceptanceService(normalize=lambda tasks, *_: [dict(t) for t in tasks], text=str,
        sync_pct=lambda state: calls.append("sync"), save=lambda state: calls.append("save"),
        event=lambda *args: calls.append("event"))
    state = {"tasks": [{"status": "pending"}], "done_flags": [False]}
    ok, _ = service.manual_accept(state, 0, "checked")
    assert ok and state["tasks"][0]["status"] == "done" and state["done_flags"] == [True]
    assert calls == ["sync", "save", "event"]


def test_learning_task_requires_recall_rating():
    service = AcceptanceService(normalize=lambda tasks, *_: [dict(t) for t in tasks], text=str,
        sync_pct=lambda state: None, save=lambda state: None, event=lambda *args: None)
    state = {"tasks": [{"status": "pending", "skill_id": "loops"}], "done_flags": [False]}
    ok, message = service.manual_accept(state, 0)
    assert ok is False
    assert "recall quality" in message
