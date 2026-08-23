from agent_service import AgentService


def test_agent_service_delegates_lifecycle():
    class Fake:
        def start(self, *args): return {"run_id": "r1"}
        def step(self, value): return value
        def confirm(self, value): return value
        def resume(self, value): return value
        def stop(self, value, reason): return (value, reason)

    started = []
    service = AgentService(lambda: Fake(), start_loop=started.append)
    assert service.start("g", {"id": "t"}, 2)["run_id"] == "r1"
    assert started == ["r1"]
