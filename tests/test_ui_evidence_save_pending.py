"""Browser regression for edits made while criterion evidence save is pending."""

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


def test_save_pending_keeps_new_drafts_and_recovers_after_failure():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(APP_URL)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_function("() => !!window.TaskVergeApi?.sessionToken()", timeout=10000)

        criteria = ["criterion-save-pending-a", "criterion-save-pending-b"]
        configured = api(page, "settings", {
            "goals": [{"id": "goal-save-pending", "title": "保存竞态目标"}],
            "active_goal": 0,
            "goal_details": {"outcome": "一个可核验结果",
                             "success_criteria": ["输出正确", "内容完整"], "constraints": []},
            "privacy": {"cloud_ai_enabled": False},
        })
        assert configured.get("ok"), configured
        seeded = api(page, "tasks", {"reason": "save pending regression", "tasks": [{
            "id": "outcome-save-pending", "title": "保存竞态验收", "task_kind": "outcome",
            "type": "outcome", "status": "pending", "verification_mode": "strict",
            "expected_output": "一个可核验结果", "acceptance": "每条标准有独立证据",
            "criteria": [{"id": criteria[0], "text": "输出正确"},
                         {"id": criteria[1], "text": "内容完整"}],
            "criterion_ids": criteria, "criterion_evidence": {}, "evidence": [],
        }]})
        assert seeded.get("ok"), seeded
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        page.locator("#currentTaskBar [data-start-task]").click()
        page.locator(f'[data-criterion-text="0"][data-criterion-id="{criteria[0]}"]').wait_for(timeout=10000)

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as evidence:
            evidence.write("保存竞态附件")
            evidence_path = evidence.name
        try:
            page.locator(f'[data-criterion-evidence-file="0"][data-criterion-id="{criteria[0]}"]').set_input_files(evidence_path)
            page.wait_for_function(f"""async () => {{
              const s = await TaskVergeApi.api('state');
              return (s.tasks?.[0]?.criterion_evidence?.['{criteria[0]}'] || []).some(row => row.kind === 'attachment' && row.ref);
            }}""", timeout=10000)
        finally:
            os.unlink(evidence_path)

        first = page.locator(f'[data-criterion-text="0"][data-criterion-id="{criteria[0]}"]')
        second = page.locator(f'[data-criterion-text="0"][data-criterion-id="{criteria[1]}"]')
        first.fill("保存快照A")
        second.fill("保存快照B")

        save_seen = threading.Event()
        pending_save = []

        def hold_save(route):
            save_seen.set()
            pending_save.append(route)

        page.route("**/api/task-response", hold_save)
        page.evaluate("document.querySelector('[data-save-criterion-evidence=\"0\"]').click()")
        for _ in range(100):
            if save_seen.is_set():
                break
            page.wait_for_timeout(50)
        assert save_seen.is_set(), "save request was not intercepted"
        first.fill("保存期间更新A")
        second.fill("保存期间更新B")
        pending_save.pop().continue_()
        page.locator("#toastHost .toast").filter(has_text="成功标准证据已保存").wait_for(timeout=10000)
        page.wait_for_function("""() =>
          document.querySelector('[data-criterion-text="0"][data-criterion-id="criterion-save-pending-a"]')?.value === '保存期间更新A' &&
          document.querySelector('[data-criterion-text="0"][data-criterion-id="criterion-save-pending-b"]')?.value === '保存期间更新B'
        """, timeout=10000)
        page.unroute("**/api/task-response", hold_save)

        saved = api(page, "state")
        rows = saved["tasks"][0]["criterion_evidence"]
        assert any(row.get("kind") == "attachment" and row.get("ref") for row in rows[criteria[0]])
        assert any(row.get("text") == "保存快照A" for row in rows[criteria[0]])
        assert any(row.get("text") == "保存快照B" for row in rows[criteria[1]])

        failed_seen = threading.Event()

        def fail_save(route):
            failed_seen.set()
            route.abort("failed")

        first.fill("失败后仍可编辑")
        page.route("**/api/task-response", fail_save)
        page.evaluate("document.querySelector('[data-save-criterion-evidence=\"0\"]').click()")
        for _ in range(100):
            if failed_seen.is_set():
                break
            page.wait_for_timeout(50)
        assert failed_seen.is_set(), "failed save request was not intercepted"
        page.locator("#toastHost .toast").filter(has_text="保存成功标准证据失败").wait_for(timeout=10000)
        assert first.input_value() == "失败后仍可编辑"
        page.unroute("**/api/task-response", fail_save)

        first.fill("最终保存A")
        page.locator('[data-save-criterion-evidence="0"]').click()
        page.wait_for_function(f"""async () => {{
          const s = await TaskVergeApi.api('state');
          const first = s.tasks?.[0]?.criterion_evidence?.['{criteria[0]}'] || [];
          const second = s.tasks?.[0]?.criterion_evidence?.['{criteria[1]}'] || [];
          return first.some(row => row.kind === 'direct_text' && row.text === '最终保存A') &&
                 second.some(row => row.kind === 'direct_text' && row.text === '保存期间更新B') &&
                 first.some(row => row.kind === 'attachment' && row.ref);
        }}""", timeout=10000)
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        assert page.locator(f'[data-criterion-text="0"][data-criterion-id="{criteria[0]}"]').input_value() == "最终保存A"
        assert page.locator(f'[data-criterion-text="0"][data-criterion-id="{criteria[1]}"]').input_value() == "保存期间更新B"
        assert page.locator(f'[data-criterion-attachments="0"][data-criterion-id="{criteria[0]}"]').inner_text().strip()
        browser.close()
