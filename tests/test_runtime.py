from runtime import JobRunner
from threading import Event


def test_keyed_jobs_do_not_duplicate():
    runner = JobRunner(1)
    started = Event()
    release = Event()
    try:
        def job():
            started.set()
            release.wait(1)
            return 1

        first = runner.submit(job, key="same")
        assert started.wait(1)
        second = runner.submit(lambda: 2, key="same")
        release.set()
        assert first.result() == 1
        assert second is None
    finally:
        runner.shutdown()
