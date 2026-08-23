"""Small runtime primitives shared by the desktop host.

Keep this deliberately boring: one bounded executor and keyed jobs.
"""

from concurrent.futures import ThreadPoolExecutor
import http.server
import threading


class JobRunner:
    """Run short background jobs without creating an unbounded thread per call."""

    def __init__(self, workers=4):
        self._executor = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="taskverge")
        self._active = set()
        self._lock = threading.Lock()

    def submit(self, fn, *args, key=None, **kwargs):
        if key is not None:
            with self._lock:
                if key in self._active:
                    return None
                self._active.add(key)

        def run():
            try:
                return fn(*args, **kwargs)
            finally:
                if key is not None:
                    with self._lock:
                        self._active.discard(key)

        return self._executor.submit(run)

    def shutdown(self):
        self._executor.shutdown(wait=False, cancel_futures=True)


class BoundedHTTPServer(http.server.ThreadingHTTPServer):
    """Threading HTTP server with a fixed request worker pool."""

    daemon_threads = True

    def __init__(self, address, handler, workers=16):
        self._request_pool = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="http")
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        self._request_pool.submit(self.process_request_thread, request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
            self.shutdown_request(request)
        except Exception:
            self.handle_error(request, client_address)
            self.shutdown_request(request)

    def shutdown(self):
        try:
            return super().shutdown()
        finally:
            self._request_pool.shutdown(wait=False, cancel_futures=True)
