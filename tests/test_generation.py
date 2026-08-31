from generation import Generation


class Runner:
    def __init__(self):
        self.jobs = []

    def submit(self, fn, *, key):
        if self.jobs:
            return None
        self.jobs.append((fn, key))
        return object()


def test_generation_rejects_duplicate_and_exposes_status():
    runner = Runner()
    generation = Generation(runner.submit, lambda job_id, set_status: set_status("completed", "ok", job_id=job_id))

    first = generation.start()
    second = generation.start()

    assert first["ok"] is True
    assert second["ok"] is True
    assert second["job_id"] == first["job_id"]
    runner.jobs[0][0]()
    assert generation.status()["running"] is False
    assert generation.status()["step"] == "completed"
