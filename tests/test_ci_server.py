"""Regression coverage for CI server URL discovery."""

import os
import subprocess
import sys
import tempfile
import time
import json
import urllib.request


def test_ci_mode_reports_reachable_configured_port():
    """CI must print its actual URL so callers never probe port zero."""
    with tempfile.TemporaryDirectory() as data_dir:
        env = os.environ.copy()
        env.update({
            "LOCALAPPDATA": data_dir,
            "TASKVERGE_PORT": "0",
            "PYTHONUNBUFFERED": "1",
        })
        server = subprocess.Popen(
            [sys.executable, "task-panel.pyw", "--ci"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        try:
            deadline = time.monotonic() + 20
            url = ""
            while time.monotonic() < deadline:
                line = server.stdout.readline().strip()
                if line.startswith("CI_URL="):
                    url = line.removeprefix("CI_URL=")
                    break
            assert url.startswith("http://127.0.0.1:")
            assert not url.endswith(":0/")
            with urllib.request.urlopen(url + "api/claim", timeout=5) as response:
                token = json.loads(response.read())['token']
            request = urllib.request.Request(url + "api/state", headers={'X-Session': token})
            with urllib.request.urlopen(request, timeout=5) as response:
                assert response.status == 200
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)
