import threading
from copy import deepcopy

import agent


def test_agent_runs_one_typed_action_and_persists_history():
    store = {}
    calls = []

    def observe(_):
        calls.append("observe")
        return {"status": "pending"}

    def set_status(args):
        calls.append(args["status"])
        return {"ok": True, "finished": True}

    orch = agent.AgentOrchestrator(
        load_state=lambda: store,
        save_state=lambda value: store.update(value),
        tools={"observe": observe, "set_task_status": set_status},
        planner=lambda run, obs: {"name": "set_task_status", "args": {"status": "doing"}},
    )
    run = orch.start("g", {"id": "t"})
    done = orch.step(run["run_id"])
    assert done["status"] == "completed"
    assert done["history"][0]["action"]["name"] == "set_task_status"
    assert calls == ["observe", "doing"]


def test_agent_requires_confirmation_for_write_actions():
    store = {}
    orch = agent.AgentOrchestrator(
        load_state=lambda: store,
        save_state=lambda value: store.update(value),
        planner=lambda run, obs: {"name": "write_file", "args": {"path": "x"}},
    )
    run = orch.start("g", {"id": "t"})
    pending = orch.step(run["run_id"])
    assert pending["status"] == "awaiting_confirmation"


def test_agent_stop_is_sticky():
    store = {}
    orch = agent.AgentOrchestrator(
        load_state=lambda: store,
        save_state=lambda value: store.update(value),
        planner=lambda run, obs: {"name": "observe"},
    )
    run = orch.start("g", {"id": "t"})
    stopped = orch.stop(run["run_id"])
    assert stopped["status"] == "paused"
    assert orch.step(run["run_id"])["status"] == "paused"


def test_stop_during_planning_cannot_start_stale_tool():
    store = {}
    planner_started = threading.Event()
    release_planner = threading.Event()
    calls = []

    def planner(_run, _observation):
        planner_started.set()
        release_planner.wait(2)
        return {"name": "set_task_status", "args": {"status": "doing"}}

    orch = agent.AgentOrchestrator(
        load_state=lambda: store,
        save_state=lambda value: store.update(value),
        tools={"set_task_status": lambda args: calls.append(args)},
        planner=planner,
    )
    run = orch.start("g", {"id": "t"})
    worker = threading.Thread(target=lambda: orch.step(run["run_id"]))
    worker.start()
    assert planner_started.wait(2)
    assert orch.stop(run["run_id"])["status"] == "paused"
    release_planner.set(); worker.join(2)
    assert calls == []
    assert orch.get(run["run_id"]).status == "paused"


def test_two_orchestrators_cannot_overwrite_stop_during_blocked_save():
    storage = {}
    storage_lock = threading.Lock()
    save_started = threading.Event()
    release_save = threading.Event()
    block_worker_save = {"enabled": False}

    def load_state():
        return deepcopy(storage)

    def save_state(value):
        if block_worker_save["enabled"] and not save_started.is_set():
            save_started.set()
            release_save.wait(2)
        storage.clear()
        storage.update(deepcopy(value))

    def atomic_save(candidate, expected_revision):
        if block_worker_save["enabled"] and candidate["status"] == "planning" and not save_started.is_set():
            save_started.set()
            release_save.wait(2)
        with storage_lock:
            current = storage.get(candidate["run_id"])
            if current and current.get("revision", 0) != expected_revision:
                return False
            storage[candidate["run_id"]] = deepcopy(candidate)
            return True

    planner = lambda _run, _observation: {"name": "set_task_status", "args": {"status": "doing"}}
    worker_orch = agent.AgentOrchestrator(
        load_state=load_state, save_state=save_state,
        tools={"set_task_status": lambda _args: {"ok": True}}, planner=planner, atomic_save=atomic_save)
    stop_orch = agent.AgentOrchestrator(
        load_state=load_state, save_state=save_state,
        tools={"set_task_status": lambda _args: {"ok": True}}, planner=planner, atomic_save=atomic_save)
    run = worker_orch.start("g", {"id": "t"})
    block_worker_save["enabled"] = True
    worker = threading.Thread(target=lambda: worker_orch.step(run["run_id"]))
    worker.start()
    assert save_started.wait(2)
    assert stop_orch.stop(run["run_id"])["status"] == "paused"
    release_save.set()
    worker.join(2)
    assert stop_orch.get(run["run_id"]).status == "paused"


def test_stop_retries_after_its_own_cas_loses_to_worker():
    storage = {}
    storage_lock = threading.Lock()
    stop_started = threading.Event()
    release_stop = threading.Event()
    block_stop = {"enabled": True}

    def load_state():
        return deepcopy(storage)

    def atomic_save(candidate, expected_revision):
        if block_stop["enabled"] and candidate["status"] == "paused" and not stop_started.is_set():
            stop_started.set()
            release_stop.wait(2)
        with storage_lock:
            current = storage.get(candidate["run_id"])
            if current and current.get("revision", 0) != expected_revision:
                return False
            storage[candidate["run_id"]] = deepcopy(candidate)
            return True

    planner = lambda _run, _observation: {"name": "set_task_status", "args": {"status": "doing"}}
    worker_orch = agent.AgentOrchestrator(
        load_state=load_state, save_state=lambda _value: None,
        tools={"set_task_status": lambda _args: {"ok": True}}, planner=planner, atomic_save=atomic_save)
    stop_orch = agent.AgentOrchestrator(
        load_state=load_state, save_state=lambda _value: None,
        tools={"set_task_status": lambda _args: {"ok": True}}, planner=planner, atomic_save=atomic_save)
    run = worker_orch.start("g", {"id": "t"})

    stop_result = {}
    stopper = threading.Thread(target=lambda: stop_result.setdefault("run", stop_orch.stop(run["run_id"])))
    stopper.start()
    assert stop_started.wait(2)
    worker_orch.step(run["run_id"])
    release_stop.set()
    stopper.join(2)

    assert stop_result["run"]["status"] == "paused"
    assert stop_orch.get(run["run_id"]).status == "paused"


def test_stop_uses_shared_atomic_pause_after_three_worker_updates():
    storage = {}
    storage_lock = threading.Lock()
    worker_updates = {"count": 0}

    def load_state():
        return deepcopy(storage)

    def atomic_save(candidate, expected_revision):
        with storage_lock:
            current = storage.get(candidate["run_id"])
            if current and current.get("revision", 0) != expected_revision:
                return False
            storage[candidate["run_id"]] = deepcopy(candidate)
            return True

    planner = lambda _run, _observation: {"name": "set_task_status", "args": {"status": "doing"}}
    worker_orch = agent.AgentOrchestrator(
        load_state=load_state, save_state=lambda _value: None,
        tools={"set_task_status": lambda _args: worker_updates.__setitem__("count", worker_updates["count"] + 1) or {"ok": True}},
        planner=planner, atomic_save=atomic_save)

    def atomic_pause(run_id, reason):
        for _ in range(3):
            worker_orch.step(run_id)
        with storage_lock:
            current = deepcopy(storage[run_id])
            current["status"] = "paused"
            current["errors"] = list(dict.fromkeys(list(current.get("errors", [])) + [reason]))
            current["revision"] = int(current.get("revision", 0) or 0) + 1
            storage[run_id] = deepcopy(current)
            return current

    stop_orch = agent.AgentOrchestrator(
        load_state=load_state, save_state=lambda _value: None,
        tools={"set_task_status": lambda _args: {"ok": True}}, planner=planner,
        atomic_save=atomic_save, atomic_pause=atomic_pause)
    run = worker_orch.start("g", {"id": "t"})

    stopped = stop_orch.stop(run["run_id"])

    assert worker_updates["count"] == 3
    assert stopped["status"] == "paused"
    assert stop_orch.get(run["run_id"]).status == "paused"
