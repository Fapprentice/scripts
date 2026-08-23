class AgentService:
    """Transport-neutral facade for agent lifecycle operations."""

    def __init__(self, orchestrator_factory, *, start_loop):
        self.orchestrator_factory = orchestrator_factory
        self.start_loop = start_loop

    def start(self, goal_id, task, max_steps):
        run = self.orchestrator_factory().start(goal_id, task, max_steps)
        self.start_loop(run["run_id"])
        return run

    def step(self, run_id): return self.orchestrator_factory().step(run_id)
    def confirm(self, run_id): return self.orchestrator_factory().confirm(run_id)
    def resume(self, run_id): return self.orchestrator_factory().resume(run_id)
    def stop(self, run_id, reason): return self.orchestrator_factory().stop(run_id, reason)
