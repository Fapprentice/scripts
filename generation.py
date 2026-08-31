"""Deep module for one keyed background generation job."""

import copy
import threading
import time


class Generation:
    """Own generation lifecycle; the caller supplies the domain worker."""

    TERMINAL = {"completed", "failed", "conflict"}

    def __init__(self, submit, worker, status=None):
        self._submit = submit
        self._worker = worker
        self._lock = threading.Lock()
        self._status = status if status is not None else {"running": False, "step": "空闲", "message": "", "ts": time.time()}

    def status(self):
        with self._lock:
            return copy.deepcopy(self._status)

    def start(self):
        with self._lock:
            if self._status["running"]:
                return {"ok": True, "message": "generation already running", "job_id": self._status.get("job_id", "")}
            job_id = "gen-{}".format(int(time.time() * 1000))
            self._set("queued", "waiting for generation job", job_id=job_id, mode="ai", error="")
        future = self._submit(lambda: self._run(job_id), key="generate")
        if future is None:
            with self._lock:
                self._set("conflict", "generation job already queued", job_id=job_id)
            return {"ok": False, "message": "generation already queued", "job_id": job_id}
        return {"ok": True, "message": "generation started", "job_id": job_id}

    def _set(self, step, message="", **extra):
        self._status.update({"running": step not in self.TERMINAL, "step": step, "message": message, "ts": time.time(), **extra})

    def _run(self, job_id):
        try:
            self._worker(job_id, self._set)
        except Exception as exc:
            with self._lock:
                self._set("failed", str(exc), job_id=job_id, mode="error", error=str(exc))
