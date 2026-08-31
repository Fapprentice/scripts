from task_service import TaskService
from datetime import datetime, timedelta


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


def test_manual_tasks_allow_unready_goal_but_preserve_callbacks():
    starts = []
    service = TaskService(text=str, normalize=lambda tasks, goal, flags: [dict(t) for t in tasks],
        goal_id=lambda state: "g1", sync_pct=lambda state: None, save=lambda state: None,
        event=lambda *args: None, undo=lambda *args: None, compact=lambda state: None,
        readiness=lambda state: {"ready": state.get("ready", False)},
        first_task_started=lambda state, task, idx: starts.append((task["id"], idx)))
    state = {"tasks": [{"id": "one", "status": "pending"}], "done_flags": [False]}
    assert service.replace(state, [{"id": "one", "title": "replacement"}], "reason") == (True, "ok")
    assert service.set_status(state, 0, "doing")[0] is True
    assert starts == [("one", 0)]


def test_task_timer_pauses_in_seconds_and_resumes_from_total():
    service = TaskService(text=str, normalize=lambda tasks, goal, flags: tasks,
        goal_id=lambda state: "g1", sync_pct=lambda state: None, save=lambda state: None,
        event=lambda *args: None, undo=lambda *args: None, compact=lambda state: None)
    state = {"tasks": [{"status": "doing", "started_at": (datetime.now() - timedelta(seconds=7)).isoformat()}], "done_flags": [False]}
    service.set_status(state, 0, "paused")
    assert 6 <= state["tasks"][0]["actual_seconds"] <= 8
    assert "actual_minutes" not in state["tasks"][0]
    total = state["tasks"][0]["actual_seconds"]
    service.set_status(state, 0, "doing")
    assert state["tasks"][0]["actual_seconds"] == total
