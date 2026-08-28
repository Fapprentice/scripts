from copy import deepcopy

from acceptance_service import AcceptanceService


def _service(saved=None):
    saved = [] if saved is None else saved
    return AcceptanceService(
        normalize=lambda tasks, *_: [dict(t) for t in tasks],
        text=str,
        sync_pct=lambda state: None,
        save=lambda state: saved.append(deepcopy(state)),
        event=lambda *args: None,
    ), saved


def test_manual_accept_marks_task_done():
    calls = []
    service = AcceptanceService(normalize=lambda tasks, *_: [dict(t) for t in tasks], text=str,
        sync_pct=lambda state: calls.append("sync"), save=lambda state: calls.append("save"),
        event=lambda *args: calls.append("event"))
    state = {"tasks": [{"status": "pending"}], "done_flags": [False]}
    ok, _ = service.manual_accept(state, 0, "checked")
    assert ok and state["tasks"][0]["status"] == "done" and state["done_flags"] == [True]
    assert calls == ["sync", "save", "event"]


def test_persist_result_marks_done_only_when_passed():
    service, _ = _service()
    state = {"tasks": [{"id": "t1", "status": "pending", "title": "完成原型", "acceptance": "可运行"}], "done_flags": [False]}
    ok, result = service.persist_result(state, 0, {"status": "needs_review", "reason": "语义不确定"})
    assert ok and result["status"] == "needs_review"
    assert state["done_flags"] == [False]
    assert state["tasks"][0]["status"] != "done"
    assert len(state["tasks"]) == 1
    ok, result = service.persist_result(state, 0, {"status": "passed", "reason": "证据充分"})
    assert result["status"] == "passed" and state["done_flags"] == [True]


def test_failed_acceptance_inserts_one_remediation_after_original():
    service, saved = _service()
    original = {"id": "t1", "status": "pending", "title": "完成原型", "acceptance": "可运行", "goal_id": "goal_0"}
    state = {"tasks": [original, {"id": "t2", "title": "下一件", "acceptance": "可检查"}], "done_flags": [False, False]}
    ok, result = service.persist_result(state, 0, {"status": "failed", "reason": "证据不足"})
    assert ok and result["status"] == "failed"
    assert len(state["tasks"]) == 3
    recovery = state["tasks"][1]
    assert recovery["source"] == "remediation"
    assert recovery["parent_task_id"] == "t1"
    assert recovery["goal_id"] == "goal_0"
    assert recovery["acceptance"] == "可运行"
    assert recovery["original_acceptance"] == "可运行"
    assert state["tasks"][2]["id"] == "t2"
    assert state["done_flags"] == [False, False, False]
    assert len(saved[-1]["tasks"]) == 3


def test_repeated_failure_does_not_duplicate_remediation():
    service, _ = _service()
    state = {"tasks": [{"id": "t1", "status": "pending", "title": "完成原型", "acceptance": "可运行"}], "done_flags": [False]}
    service.persist_result(state, 0, {"status": "failed", "reason": "证据不足"})
    first_id = state["tasks"][1]["id"]
    service.persist_result(state, 0, {"status": "failed", "reason": "证据仍不足"})
    assert len(state["tasks"]) == 2
    assert state["tasks"][1]["id"] == first_id
    assert state["done_flags"] == [False, False]


def test_non_failed_statuses_do_not_create_remediation():
    service, _ = _service()
    for status in ("passed", "blocked", "needs_review"):
        state = {"tasks": [{"id": "t1", "status": "pending", "title": "完成原型", "acceptance": "可运行"}], "done_flags": [False]}
        service.persist_result(state, 0, {"status": status, "reason": status})
        assert len(state["tasks"]) == 1, status
        assert state["done_flags"] == [status == "passed"]


def test_ensure_remediation_reuses_existing_task():
    service, saved = _service()
    state = {"tasks": [{"id": "t1", "status": "pending", "title": "完成原型", "acceptance": "可运行",
                        "acceptance_result": {"status": "failed"}}], "done_flags": [False]}
    first = service.ensure_remediation(state, 0)
    second = service.ensure_remediation(state, 0)
    assert first is second
    assert len(state["tasks"]) == 2


def test_saved_state_keeps_remediation_after_reload():
    service, saved = _service()
    state = {"tasks": [{"id": "t1", "status": "pending", "title": "完成原型", "acceptance": "可运行"}], "done_flags": [False]}
    service.persist_result(state, 0, {"status": "failed", "reason": "证据不足"})
    reloaded = deepcopy(saved[-1])
    assert len(reloaded["tasks"]) == 2
    assert reloaded["tasks"][1]["source"] == "remediation"
    assert reloaded["done_flags"] == [False, False]


def test_learning_task_requires_recall_rating():
    service, _ = _service()
    state = {"tasks": [{"status": "pending", "skill_id": "loops"}], "done_flags": [False]}
    ok, message = service.manual_accept(state, 0)
    assert ok is False
    assert "recall quality" in message
