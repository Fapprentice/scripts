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
