from datetime import datetime

from companion_service import CompanionService
from state_store import SqliteStore
from acceptance_service import AcceptanceService
from task_service import TaskService
from adaptive import record_outcome


class Clock:
    def __init__(self, start=None):
        self.now = start or datetime(2026, 4, 8, 10, 0, 0).timestamp()

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def _service(tmp_path, clock=None):
    store = SqliteStore(tmp_path, auto_backup=False)
    clock = clock or Clock()
    return CompanionService(store, clock=clock), store, clock


def test_poke_feed_talk_persist_and_respect_daily_caps(tmp_path):
    service, store, clock = _service(tmp_path)
    first = service.apply("poke")
    assert first["ok"] and first["applied"]
    assert first["delta_bond"] == 1
    assert store.load_companion()["bond"] == 21
    for _ in range(2):
        clock.advance(21)
        assert service.apply("poke")["delta_bond"] == 1
    for _ in range(5):
        clock.advance(21)
        result = service.apply("poke")
        assert result["ok"] is True
        assert result["delta_bond"] == 0
    clock.advance(21)
    ninth = service.apply("poke")
    assert ninth["applied"] is False
    assert ninth["delta_bond"] == 0
    assert ninth["play_hint"]["kind"] == "poke"
    assert store.load_companion()["bond"] == 23
    assert store.load_companion()["energy"] == 70

    feed = service.apply("feed", {"treat": "小鱼干"})
    assert feed["applied"] and feed["delta_energy"] == 8 and feed["delta_bond"] == 2
    clock.advance(601)
    cake = service.apply("feed", {"treat": "蛋糕"})
    assert cake["applied"] and cake["delta_energy"] == 5
    clock.advance(601)
    candy = service.apply("feed", {"treat": "棒棒糖"})
    assert candy["applied"] and candy["delta_energy"] == 4
    clock.advance(601)
    before_cap = store.load_companion()
    fourth = service.apply("feed", {"treat": "小鱼干"})
    assert fourth["applied"] is False
    assert fourth["delta_energy"] == 0 and fourth["delta_bond"] == 0
    assert "inventory" not in fourth["snapshot"]
    assert store.load_companion()["energy"] == before_cap["energy"] == 87
    assert store.load_companion()["bond"] == before_cap["bond"]
    unknown = service.apply("feed", {"treat": "神秘罐头"})
    assert unknown["ok"] is False

    talk = service.apply("talk")
    assert talk["delta_bond"] == 1
    for _ in range(3):
        clock.advance(31)
        assert service.apply("talk")["delta_bond"] == 1
    for _ in range(2):
        clock.advance(31)
        result = service.apply("talk")
        assert result["applied"] is True
        assert result["delta_bond"] == 0
    clock.advance(31)
    before_talk_cap = store.load_companion()
    seventh = service.apply("talk")
    assert seventh["applied"] is False
    assert seventh["delta_energy"] == 0 and seventh["delta_bond"] == 0
    assert store.load_companion()["energy"] == before_talk_cap["energy"]
    assert store.load_companion()["bond"] == before_talk_cap["bond"]


def test_acceptance_passed_failed_and_needs_review(tmp_path):
    service, store, _ = _service(tmp_path)
    state = {"tasks": [{"id": "t1", "status": "doing", "title": "原型"}], "done_flags": [False]}
    passed = service.on_acceptance(state, 0, {"status": "passed", "id": "run-1"})
    assert passed["applied"]
    assert passed["delta_energy"] == 6 and passed["delta_bond"] == 8
    replay = service.on_acceptance(state, 0, {"status": "passed", "id": "run-1"})
    assert replay["applied"] is False
    before = store.load_companion()
    before_events = store.list_companion_events()
    none = service.on_acceptance(state, 0, {"status": "needs_review"})
    assert none is None
    assert store.load_companion()["energy"] == before["energy"]
    assert store.load_companion()["bond"] == before["bond"]
    after_review = store.list_companion_events()
    assert after_review == before_events
    assert not any(item["kind"] == "needs_review" for item in after_review)
    failed = service.on_acceptance(state, 0, {"status": "failed", "id": "run-2"})
    assert failed["applied"] is True
    assert failed["delta_energy"] == 0 and failed["delta_bond"] == 0
    assert failed["play_hint"]["kind"] == "cheer"
    failed_events = [item for item in store.list_companion_events() if item["kind"] == "failed"]
    assert len(failed_events) == 1
    assert failed_events[0]["delta_energy"] == 0 and failed_events[0]["delta_bond"] == 0
    assert failed_events[0]["delta_bond"] == 0
    replay_failed = service.on_acceptance(state, 0, {"status": "failed", "id": "run-2"})
    assert replay_failed["applied"] is False
    assert len([item for item in store.list_companion_events() if item["kind"] == "failed"]) == 1


def test_focus_and_user_rest_not_quit_continue(tmp_path):
    service, store, clock = _service(tmp_path)
    state = {"tasks": [{"id": "t1", "status": "doing", "title": "原型"}], "done_flags": [False]}
    start = service.on_status(state, 0, "pending", "doing")
    assert start["delta_bond"] == 3
    again = service.on_status(state, 0, "paused", "doing")
    assert again["applied"] is False
    pause = service.on_status(state, 0, "doing", "paused")
    assert pause["delta_energy"] == 0 and pause["delta_bond"] == 0

    item = {"ts": "2026-04-08T10:00:00", "until": clock.now + 6 * 60, "reason": "休息一下", "source": "user"}
    rest = service.on_break_start(state, item, "user")
    assert rest["delta_energy"] == 6
    clock.advance(6 * 60)
    ended = dict(item); ended["until"] = clock.now; ended["ended"] = True
    finish = service.on_break_end(state, ended)
    assert finish["delta_energy"] == 4 and finish["delta_bond"] == 1
    quit_item = {"ts": "2026-04-08T12:00:00", "until": clock.now + 15 * 60, "reason": "收尾仪式-继续", "source": "quit"}
    assert service.on_break_start(state, quit_item, "quit")["applied"] is False


def test_acceptance_service_skips_companion_on_needs_review(tmp_path):
    calls = []
    service = AcceptanceService(
        normalize=lambda tasks, *_: [dict(t) for t in tasks],
        text=str, sync_pct=lambda state: None, save=lambda state: None,
        event=lambda *args: None, companion=lambda state, idx, result: calls.append(result["status"]),
    )
    state = {"tasks": [{"id": "t1", "status": "pending", "title": "完成原型", "acceptance": "可运行"}], "done_flags": [False]}
    service.persist_result(state, 0, {"status": "needs_review", "reason": "语义不确定"})
    service.persist_result(state, 0, {"status": "failed", "reason": "证据不足"})
    service.persist_result(state, 0, {"status": "passed", "reason": "证据充分"})
    assert calls == ["failed", "passed"]


def test_task_service_notifies_companion_on_doing(tmp_path):
    seen = []
    service = TaskService(
        text=str, normalize=lambda tasks, goal, flags: [dict(t) for t in tasks],
        goal_id=lambda state: "g1", sync_pct=lambda state: None, save=lambda state: None,
        event=lambda *args: None, undo=lambda *args: None, compact=lambda state: None,
        companion=lambda state, idx, previous, status: seen.append((previous, status)),
    )
    state = {"tasks": [{"id": "one", "status": "pending"}], "done_flags": [False]}
    service.set_status(state, 0, "doing")
    service.set_status(state, 0, "paused")
    assert seen == [("pending", "doing"), ("doing", "paused")]


def test_companion_survives_store_reopen(tmp_path):
    service, store, clock = _service(tmp_path)
    service.apply("poke")
    clock.advance(601)
    feed = service.apply("feed", {"treat": "小鱼干"})
    assert feed["applied"] is True
    energy = store.load_companion()["energy"]
    bond = store.load_companion()["bond"]
    assert energy == 78
    assert bond == 23
    event_ids = [item["id"] for item in store.list_companion_events()]

    reopened = SqliteStore(tmp_path, auto_backup=False)
    companion = reopened.load_companion()
    assert companion["energy"] == 78
    assert companion["bond"] == 23
    assert [item["id"] for item in reopened.list_companion_events()] == event_ids
    again = CompanionService(reopened, clock=clock)
    snapshot = again.snapshot()
    assert snapshot["energy"] == 78
    assert snapshot["bond"] == 23


def test_motivation_points_do_not_change_companion_energy(tmp_path):
    companion, store, _ = _service(tmp_path)
    state = {
        "tasks": [{"id": "t1", "status": "pending", "title": "完成原型", "acceptance": "可运行"}],
        "done_flags": [False],
        "motivation": {"points": 10, "streak": 1, "best_streak": 1, "history": []},
    }
    assert store.load_companion()["energy"] == 70
    assert store.load_companion()["bond"] == 20

    failed_points = record_outcome(state, "failed")
    assert failed_points["points"] == -3
    assert state["motivation"]["points"] == 7
    assert store.load_companion()["energy"] == 70
    assert store.load_companion()["bond"] == 20

    skipped_points = record_outcome(state, "skipped")
    assert skipped_points["points"] == -5
    assert state["motivation"]["points"] == 2
    assert store.load_companion()["energy"] == 70

    service = AcceptanceService(
        normalize=lambda tasks, *_: [dict(t) for t in tasks],
        text=str, sync_pct=lambda state: None, save=lambda state: None,
        event=lambda *args: None, outcome=lambda current, outcome: record_outcome(current, outcome),
        companion=companion.on_acceptance,
    )
    service.persist_result(state, 0, {"status": "failed", "reason": "证据不足", "id": "run-fail"})
    assert state["motivation"]["points"] == -1
    assert store.load_companion()["energy"] == 70
    assert store.load_companion()["bond"] == 20
    failed_events = [item for item in store.list_companion_events() if item["kind"] == "failed"]
    assert len(failed_events) == 1
    assert failed_events[0]["delta_energy"] == 0 and failed_events[0]["delta_bond"] == 0

    points_before_poke = state["motivation"]["points"]
    poke = companion.apply("poke")
    assert poke["applied"] is True
    assert poke["delta_energy"] == 0 and poke["delta_bond"] == 1
    assert state["motivation"]["points"] == points_before_poke
    assert store.load_companion()["energy"] == 70
    assert store.load_companion()["bond"] == 21


def test_clamped_growth_records_actual_delta(tmp_path):
    service, store, _ = _service(tmp_path)
    row = store.load_companion()
    row["energy"] = 98
    row["bond"] = 99
    store.write_companion(row)
    result = service.apply("accepted", {"acceptance_id": "run-cap", "task_id": "t1"})
    assert result["applied"] is True
    assert result["delta_energy"] == 2
    assert result["delta_bond"] == 1
    assert store.load_companion()["energy"] == 100
    assert store.load_companion()["bond"] == 100
    event = store.find_companion_event("accepted:run-cap")
    assert event["delta_energy"] == 2
    assert event["delta_bond"] == 1


def test_companion_and_task_save_share_one_transaction(tmp_path):
    service, store, _ = _service(tmp_path)
    path = tmp_path / "task-config.json"
    store.save(str(path), {"goal": "原目标", "goals": [{"id": "g1", "title": "原目标"}]}, backup=False)

    def boom(row, txn):
        service._apply_with_row(row, txn, "poke", {}, {})
        raise RuntimeError("companion boom")

    try:
        store.save(str(path), {"goal": "新目标", "goals": [{"id": "g1", "title": "新目标"}]}, backup=False, companion_mutator=boom)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected companion boom")
    assert store.load(str(path))["goal"] == "原目标"
    assert store.load_companion()["bond"] == 20
    assert store.list_companion_events() == []

    store.save(
        str(path),
        {"goal": "已验收", "goals": [{"id": "g1", "title": "已验收"}]},
        backup=False,
        companion_mutator=lambda row, txn: service._apply_with_row(row, txn, "accepted", {"acceptance_id": "run-tx", "task_id": "t1"}, {}),
    )
    assert store.load(str(path))["goal"] == "已验收"
    assert store.load_companion()["energy"] == 76
    assert store.find_companion_event("accepted:run-tx")["delta_energy"] == 6


def test_deferred_apply_commits_only_with_state_save(tmp_path):
    service, store, _ = _service(tmp_path)
    deferred = service.apply("poke", {}, {}, commit=False)
    assert deferred["deferred"] is True
    assert store.load_companion()["bond"] == 20
    path = tmp_path / "task-config.json"
    store.save(str(path), {"goal": "同事务", "goals": [{"id": "g1", "title": "同事务"}]}, backup=False, companion_mutator=service.pending_mutator())
    service.clear_pending()
    assert store.load_companion()["bond"] == 21
    assert store.load(str(path))["goal"] == "同事务"


def test_snapshot_and_feed_do_not_lose_updates(tmp_path):
    import threading
    service, store, clock = _service(tmp_path)
    barrier = threading.Barrier(2)
    errors = []

    def feed():
        try:
            barrier.wait()
            clock.advance(1)
            result = service.apply("feed", {"treat": "小鱼干"})
            assert result["applied"] is True
        except Exception as exc:
            errors.append(exc)

    def snap():
        try:
            barrier.wait()
            service.snapshot({})
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=feed), threading.Thread(target=snap)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert store.load_companion()["energy"] == 78


def test_failed_hurts_hp_not_energy_and_needs_review_still_skips(tmp_path):
    service, store, _ = _service(tmp_path)
    state = {"tasks": [{"id": "t1", "status": "doing", "title": "原型"}], "done_flags": [False]}
    before = store.load_companion()
    failed = service.on_acceptance(state, 0, {"status": "failed", "id": "hurt-1"})
    assert failed["delta_energy"] == 0 and failed["delta_bond"] == 0
    assert store.load_companion()["energy"] == before["energy"]
    payload = store.load_companion()["payload"]
    assert payload["hp"] == 96
    assert payload["hunger"] == 64
    none = service.on_acceptance(state, 0, {"status": "needs_review", "id": "nr-1"})
    assert none is None
    assert store.load_companion()["payload"]["hp"] == 96


def test_xp_levels_up_and_spend_uses_points_not_fail_mapping(tmp_path):
    service, store, _ = _service(tmp_path)
    row = store.load_companion()
    row["payload"] = {"xp": 38, "level": 1, "stage": "鱼苗", "hunger": 70, "hp": 100, "fainted": False}
    store.write_companion(row)
    passed = service.apply("accepted", {"acceptance_id": "lv-1", "task_id": "t1"})
    payload = store.load_companion()["payload"]
    assert payload["level"] == 2
    assert payload["stage"] == "鱼苗"
    assert passed["snapshot"]["level"] == 2
    state = {"motivation": {"points": 15, "history": []}, "tasks": [{"id": "t1"}], "done_flags": [False]}
    spend = service.apply("spend", {}, state)
    assert spend["applied"] is True
    assert state["motivation"]["points"] == 5
    assert store.load_companion()["energy"] == 86
    broke = service.apply("spend", {}, state)
    assert broke["applied"] is False
    assert state["motivation"]["points"] == 5
