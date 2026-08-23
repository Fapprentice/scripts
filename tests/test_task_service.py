from task_service import TaskService


def test_task_service_replaces_tasks():
    calls = []
    service = TaskService(text=str, normalize=lambda tasks, goal, flags: [dict(t) for t in tasks],
        goal_id=lambda state: "g1", sync_pct=lambda state: calls.append("sync"),
        save=lambda state: calls.append("save"), event=lambda *args: calls.append("event"),
        undo=lambda *args: calls.append("undo"), compact=lambda state: calls.append("compact"))
    state = {"tasks": [], "done_flags": []}
    assert service.replace(state, [{"title": "new"}], "reason")[1] == "ok"
    assert state["tasks"][0]["title"] == "new"


def test_task_service_scores_partial_and_skip_once():
    outcomes = []
    service = TaskService(text=str, normalize=lambda tasks, goal, flags: [dict(t) for t in tasks],
        goal_id=lambda state: "g1", sync_pct=lambda state: None, save=lambda state: None,
        event=lambda *args: None, undo=lambda *args: None, compact=lambda state: None,
        outcome=lambda state, value: outcomes.append(value))
    state = {"tasks": [{"status": "pending"}], "done_flags": [False]}
    service.set_status(state, 0, "partial")
    service.set_status(state, 0, "partial")
    service.set_status(state, 0, "skipped")
    assert outcomes == ["partial", "skipped"]
