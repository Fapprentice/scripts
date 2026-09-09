"""Browser regression for drafts entered while starting a task."""

import json
import os
import tempfile
import threading

import pytest


APP_URL = os.environ.get("TASKVERGE_TEST_URL", "")
pytestmark = pytest.mark.skipif(not APP_URL, reason="start task-panel.pyw --ci and set TASKVERGE_TEST_URL")


def api(page, path, payload=None):
    return page.evaluate("""async ({path, payload}) => {
      await TaskVergeApi.ensureSession();
      return await TaskVergeApi.api(path, payload === null ? undefined : payload);
    }""", {"path": path, "payload": payload})


def test_start_pending_keeps_drafts_and_start_failure_recovers():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(APP_URL)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_function("() => !!window.TaskVergeApi?.sessionToken()", timeout=10000)

        criteria = ["criterion-start-pending-a", "criterion-start-pending-b"]
        configured = api(page, "settings", {
            "goals": [{"id": "goal-start-pending", "title": "启动竞态目标"}],
            "active_goal": 0,
            "goal_details": {"outcome": "一个可核验结果",
                             "success_criteria": ["输出正确", "内容完整"], "constraints": []},
            "privacy": {"cloud_ai_enabled": False},
        })
        assert configured.get("ok"), configured
        seeded = api(page, "tasks", {"reason": "start pending regression", "tasks": [{
            "id": "outcome-start-pending", "title": "启动竞态验收", "task_kind": "outcome",
            "type": "outcome", "status": "pending", "verification_mode": "strict",
            "expected_output": "一个可核验结果", "acceptance": "每条标准有独立证据",
            "criteria": [{"id": criteria[0], "text": "输出正确"},
                         {"id": criteria[1], "text": "内容完整"}],
            "criterion_ids": criteria, "criterion_evidence": {}, "evidence": [],
        }]})
        assert seeded.get("ok"), seeded
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        page.locator("#currentTaskBar [data-start-task]").wait_for(timeout=10000)

        post_seen = threading.Event()
        pending_post = []

        def hold_start_post(route):
            payload = route.request.post_data or ""
            if route.request.method == "POST" and json.loads(payload).get("status") == "doing":
                pending_post.append(route)
                post_seen.set()
            else:
                route.continue_()

        page.route("**/api/task-state", hold_start_post)
        page.evaluate("document.querySelector('#currentTaskBar [data-start-task]').click()")
        for _ in range(100):
            if post_seen.is_set():
                break
            page.wait_for_timeout(50)
        assert post_seen.is_set(), "start task-state request was not intercepted"

        first = page.locator(f'[data-criterion-text="0"][data-criterion-id="{criteria[0]}"]')
        second = page.locator(f'[data-criterion-text="0"][data-criterion-id="{criteria[1]}"]')
        first.fill("启动期间输入A")
        second.fill("启动期间输入B")
        state_seen = threading.Event()
        pending_state = []

        def hold_start_state(route):
            if route.request.method == "GET" and not pending_state:
                pending_state.append(route)
                state_seen.set()
            else:
                route.continue_()

        page.route("**/api/state", hold_start_state)
        pending_post.pop().continue_()
        for _ in range(100):
            if state_seen.is_set():
                break
            page.wait_for_timeout(50)
        assert state_seen.is_set(), "start refresh state request was not intercepted"
        target_state = pending_state.pop()
        with page.expect_response(lambda response: response.url.endswith("/api/state") and response.request.method == "GET"):
            target_state.continue_()
        page.wait_for_function("() => document.querySelector('#currentTaskBar')?.dataset.startStateApplied === '0'", timeout=10000)
        assert first.input_value() == "启动期间输入A"
        assert second.input_value() == "启动期间输入B"
        page.unroute("**/api/task-state", hold_start_post)
        page.unroute("**/api/state", hold_start_state)

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as evidence:
            evidence.write("启动竞态附件")
            evidence_path = evidence.name
        try:
            page.locator(f'[data-criterion-evidence-file="0"][data-criterion-id="{criteria[0]}"]').set_input_files(evidence_path)
            page.wait_for_function(f"""async () => {{
              const s = await TaskVergeApi.api('state');
              return (s.tasks?.[0]?.criterion_evidence?.['{criteria[0]}'] || []).some(row => row.kind === 'attachment' && row.ref);
            }}""", timeout=10000)
        finally:
            os.unlink(evidence_path)

        page.locator('[data-save-criterion-evidence="0"]').click()
        page.wait_for_function(f"""async () => {{
          const s = await TaskVergeApi.api('state');
          const first = s.tasks?.[0]?.criterion_evidence?.['{criteria[0]}'] || [];
          const second = s.tasks?.[0]?.criterion_evidence?.['{criteria[1]}'] || [];
          return first.some(row => row.kind === 'direct_text' && row.text === '启动期间输入A') &&
                 second.some(row => row.kind === 'direct_text' && row.text === '启动期间输入B') &&
                 first.some(row => row.kind === 'attachment' && row.ref);
        }}""", timeout=10000)
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        assert page.locator(f'[data-criterion-text="0"][data-criterion-id="{criteria[0]}"]').input_value() == "启动期间输入A"
        assert page.locator(f'[data-criterion-text="0"][data-criterion-id="{criteria[1]}"]').input_value() == "启动期间输入B"
        assert page.locator(f'[data-criterion-attachments="0"][data-criterion-id="{criteria[0]}"]').inner_text().strip()

        assert api(page, "task-state", {"idx": 0, "status": "paused"}).get("ok")
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        page.locator("#currentTaskBar [data-start-task]").wait_for(timeout=10000)
        failed_seen = threading.Event()
        pending_post = []

        def hold_failed_start(route):
            payload = route.request.post_data or ""
            if route.request.method == "POST" and json.loads(payload).get("status") == "doing":
                pending_post.append(route)
                failed_seen.set()
                return
            route.continue_()

        page.route("**/api/task-state", hold_failed_start)
        page.evaluate("document.querySelector('#currentTaskBar [data-start-task]').click()")
        for _ in range(100):
            if failed_seen.is_set():
                break
            page.wait_for_timeout(50)
        assert failed_seen.is_set(), "failed start request was not intercepted"
        first.fill("POST失败新草稿A")
        second.fill("POST失败新草稿B")
        pending_post.pop().abort("failed")
        page.locator("#toastHost .toast").filter(has_text="开始任务失败").wait_for(timeout=10000)
        assert page.locator("#currentTaskBar [data-start-task]").is_visible()
        assert first.input_value() == "POST失败新草稿A"
        assert second.input_value() == "POST失败新草稿B"
        page.unroute("**/api/task-state", hold_failed_start)
        assert api(page, "state")["tasks"][0]["status"] == "paused"

        with page.expect_response(lambda response: response.url.endswith("/api/task-state") and response.request.method == "POST"):
            page.locator("#currentTaskBar [data-start-task]").click()
        page.wait_for_function("() => document.querySelector('#currentTaskBar')?.dataset.startStateApplied === '0'", timeout=10000)
        assert first.input_value() == "POST失败新草稿A"
        assert second.input_value() == "POST失败新草稿B"
        assert api(page, "state")["tasks"][0]["status"] == "doing"

        assert api(page, "task-state", {"idx": 0, "status": "paused"}).get("ok")
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        page.locator("#currentTaskBar [data-start-task]").wait_for(timeout=10000)
        post_seen = threading.Event()
        pending_post = []

        def hold_refresh_post(route):
            payload = route.request.post_data or ""
            if route.request.method == "POST" and json.loads(payload).get("status") == "doing":
                pending_post.append(route)
                post_seen.set()
            else:
                route.continue_()

        page.route("**/api/task-state", hold_refresh_post)
        page.evaluate("document.querySelector('#currentTaskBar [data-start-task]').click()")
        for _ in range(100):
            if post_seen.is_set():
                break
            page.wait_for_timeout(50)
        assert post_seen.is_set(), "refresh start task-state request was not intercepted"
        state_seen = threading.Event()
        pending_state = []

        def hold_refresh_state(route):
            if route.request.method == "GET" and not pending_state:
                pending_state.append(route)
                state_seen.set()
            else:
                route.continue_()

        page.route("**/api/state", hold_refresh_state)
        pending_post.pop().continue_()
        for _ in range(100):
            if state_seen.is_set():
                break
            page.wait_for_timeout(50)
        assert state_seen.is_set(), "refresh state request was not intercepted"
        first.fill("GET失败新草稿A")
        second.fill("GET失败新草稿B")
        pending_state.pop().abort("failed")
        page.locator("#toastHost .toast").filter(has_text="状态刷新失败").wait_for(timeout=10000)
        assert not page.locator("#currentTaskBar [data-start-task]").count()
        assert first.input_value() == "GET失败新草稿A"
        assert second.input_value() == "GET失败新草稿B"
        page.unroute("**/api/task-state", hold_refresh_post)
        page.unroute("**/api/state", hold_refresh_state)
        assert api(page, "state")["tasks"][0]["status"] == "doing"

        page.locator('[data-save-criterion-evidence="0"]').click()
        page.wait_for_function(f"""async () => {{
          const s = await TaskVergeApi.api('state');
          const rows = s.tasks?.[0]?.criterion_evidence || {{}};
          return (rows['{criteria[0]}'] || []).some(row => row.kind === 'direct_text' && row.text === 'GET失败新草稿A') &&
                 (rows['{criteria[1]}'] || []).some(row => row.kind === 'direct_text' && row.text === 'GET失败新草稿B');
        }}""", timeout=10000)
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        assert page.locator(f'[data-criterion-text="0"][data-criterion-id="{criteria[0]}"]').input_value() == "GET失败新草稿A"
        assert page.locator(f'[data-criterion-text="0"][data-criterion-id="{criteria[1]}"]').input_value() == "GET失败新草稿B"
        browser.close()
