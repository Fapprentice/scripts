"""Deterministic API endpoint tests — no browser needed.

These test API endpoint behavior, session management, and CRUD operations.
Run against a running Task Verge instance in CI mode.

Run: python -m pytest tests/test_api.py -v
"""

import json, os, urllib.request, urllib.error
import pytest

BASE = os.environ.get("TASKVERGE_TEST_URL")
if BASE:
    BASE = BASE.rstrip("/")
_SESSION = None

pytestmark = pytest.mark.skipif(
    not BASE,
    reason="No running Task Verge instance — start with python task-panel.pyw --ci",
)


def _get(path):
    url = BASE + path
    headers = {}
    if path != "/api/claim":
        global _SESSION
        if not _SESSION:
            try:
                _SESSION = json.loads(urllib.request.urlopen(BASE + "/api/claim", timeout=10).read()).get("token")
            except Exception: pass
        if _SESSION: headers["X-Session"] = _SESSION
    req = urllib.request.Request(url, headers=headers)
    try:
        return json.loads(urllib.request.urlopen(req, timeout=10).read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try: body = json.loads(body)
        except Exception: pass
        return {"_status": e.code, "_body": body}
    except Exception as e:
        return {"_error": str(e)}


def _post(path, data=None, session=None):
    body = json.dumps(data or {}, ensure_ascii=False).encode()
    headers = {"Content-Type": "application/json"}
    global _SESSION
    if session: _SESSION = session
    elif path not in ("/api/heartbeat",):
        if not _SESSION:
            try:
                _SESSION = json.loads(urllib.request.urlopen(BASE + "/api/claim", timeout=10).read()).get("token")
            except Exception: pass
        if _SESSION: headers["X-Session"] = _SESSION
    if _SESSION and "X-Session" not in headers: headers["X-Session"] = _SESSION
    req = urllib.request.Request(BASE + path, data=body, headers=headers)
    try:
        return json.loads(urllib.request.urlopen(req, timeout=10).read())
    except urllib.error.HTTPError as e:
        resp_body = e.read().decode(errors="replace")
        try: resp_body = json.loads(resp_body)
        except Exception: pass
        return {"_status": e.code, "_body": resp_body}
    except Exception as e:
        return {"_error": str(e)}


def test_write_requires_session_before_first_claim():
    req = urllib.request.Request(
        BASE + "/api/event", data=b'{}', headers={"Content-Type": "application/json"}
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=10)
    assert exc.value.code == 401


class TestStateEndpoint:
    """GET /api/state — the main data endpoint."""

    def test_state_returns_dict(self):
        r = _get("/api/state")
        assert isinstance(r, dict)
        assert "tasks" in r
        assert "done_flags" in r
        assert "completion_pct" in r
        assert "goal" in r
        assert "goals" in r

    def test_state_tasks_is_list(self):
        r = _get("/api/state")
        assert isinstance(r.get("tasks"), list)

    def test_state_completion_pct_range(self):
        r = _get("/api/state")
        pct = r.get("completion_pct", 0)
        assert 0 <= pct <= 100


class TestClaimSession:
    """GET /api/claim — backend session management."""

    def test_claim_returns_token(self):
        r = _get("/api/claim")
        if r.get("_status") == 409:
            assert r.get("_body", {}).get("ok") is False
            return
        assert r.get("ok"), f"Claim should succeed: {r}"
        assert r.get("token"), "Should return a session token"

    def test_second_claim_returns_409(self):
        """Second claim within TTL should be rejected."""
        r1 = _get("/api/claim")
        if r1.get("token"):
            r2 = _get("/api/claim")
            # Should either return the same token or 409
            assert (
                r2.get("_status") == 409
                or r2.get("ok") is False
                or r2.get("token") == r1.get("token")
            ), f"Second claim should be rejected or return same token: {r2}"


class TestHeartbeat:
    """POST /api/heartbeat — session keepalive."""

    def test_heartbeat_returns_ok(self):
        r = _post("/api/heartbeat")
        assert r.get("ok"), f"Heartbeat should return ok: {r}"


class TestGenerateStatus:
    """GET /api/generate-status — task generation progress."""

    def test_status_returns_dict(self):
        r = _get("/api/generate-status")
        assert isinstance(r, dict)
        assert "running" in r
        assert "step" in r


class TestInsights:
    """GET /api/insights — coach insight cards."""

    def test_insights_returns_dict(self):
        r = _get("/api/insights")
        assert isinstance(r, dict)
        assert "alerts" in r
        assert "stats" in r


class TestExport:
    """GET /api/export — data export endpoint."""

    def test_export_returns_dict(self):
        r = _get("/api/export")
        assert isinstance(r, dict)
        assert "tasks" in r or "tasks_by_goal" in r


class TestStorageSafety:
    def test_storage_status_backup_and_complete_export(self):
        status = _get("/api/storage-status")
        assert status.get("ok") is True, status
        backup = _post("/api/storage-backup")
        assert backup.get("ok") is True and os.path.isfile(backup["path"]), backup
        export = _post("/api/storage-export")
        assert export.get("ok") is True and os.path.isfile(export["path"]), export

    def test_restore_requires_explicit_confirmation(self):
        status = _get("/api/storage-status")
        path = status["backups"][0]["path"]
        rejected = _post("/api/storage-restore", {"path": path, "confirm": False})
        assert rejected.get("_status") == 400


class TestErrorHandling:
    """Error path handling."""

    def test_nonexistent_endpoint_returns_404(self):
        r = _get("/api/nonexistent-xyz")
        status = r.get("_status", 200)
        assert status == 404, f"Nonexistent endpoint: {r}"



class TestSafetyEndpoints:
    """Safe write endpoints that don't modify critical data."""

    def test_clear_fg_returns_ok(self):
        """Clearing FG data should work and be idempotent."""
        r = _post("/api/clear-fg")
        assert r.get("ok"), f"clear-fg should succeed: {r}"

    def test_event_returns_ok(self):
        """Logging a UI event should succeed."""
        r = _post("/api/event", {
            "kind": "test_event",
            "message": "automated API test",
        })
        assert r.get("ok"), f"event should succeed: {r}"


class TestReviewedFixes:
    def test_settings_persist_schedule_workspace_and_consent(self):
        r = _post("/api/settings", {
            "goals": [{"id":"goal_regression", "title":"回归目标"}], "active_goal": 0,
            "schedule": {"focus_template": "25"}, "workspace": os.getcwd(),
            "privacy": {"share_foreground_with_ai": True},
        })
        assert r.get("ok"), r
        assert _post("/api/privacy-consent", {"accepted": True}).get("ok")
        state = _get("/api/state")
        assert state["schedule"]["focus_template"] == "25"
        assert state["workspace"] == os.path.abspath(os.getcwd())
        assert state["privacy"]["monitoring_consent"] is True
        assert state["privacy"]["share_foreground_with_ai"] is True

    def test_goal_delete_archives_goal_and_keeps_tasks(self):
        assert _post("/api/settings", {
            "goals": [{"id":"goal_keep", "title":"保留目标"}, {"id":"goal_delete", "title":"待删除目标"}], "active_goal": 1,
        }).get("ok")
        assert _post("/api/tasks", {"tasks": [{"title": "归档后仍保留的任务"}]}).get("ok")
        before = _get("/api/export")
        assert before.get("tasks"), before
        deleted = _post("/api/goal-delete", {"index": 1})
        assert deleted.get("ok"), deleted
        assert deleted["archived_goal"]["title"] == "待删除目标"
        state = _get("/api/state")
        assert [g["title"] for g in state["goals"]] == ["保留目标"]
        assert all(isinstance(g, dict) and g.get("id") and g.get("title") for g in state["goals"])
        after = _get("/api/export")
        assert after.get("tasks_by_goal", {}).get("goal_1"), after

    def test_write_endpoint_requires_session(self):
        req = urllib.request.Request(
            BASE + "/api/event", data=b'{}', headers={"Content-Type": "application/json"}
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=10)
        assert exc.value.code == 401

    def test_arbitrary_evidence_path_is_rejected(self):
        assert _post("/api/tasks", {"tasks": [{"title": "边界测试任务"}], "reason": "安全边界回归"}).get("ok")
        r = _post("/api/task-evidence", {"idx": 0, "evidence": os.path.abspath(__file__)})
        assert r.get("_status") == 400

    def test_evaluate_task_does_not_evaluate_siblings(self):
        tasks = [
            {"title": "当前任务", "type": "behavior"},
            {"title": "后续任务", "type": "behavior"},
        ]
        assert _post("/api/tasks", {"tasks": tasks, "reason": "单任务验收回归"}).get("ok")
        result = _post("/api/evaluate-task", {"idx": 0})
        assert result.get("ok") is True
        state = _get("/api/state")
        assert state["tasks"][0]["acceptance_result"]
        assert state["tasks"][1]["status"] != "done"
        assert not state["tasks"][1]["acceptance_result"]
