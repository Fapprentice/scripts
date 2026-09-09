"""Browser regression for outcome evidence editing and persistence."""

import os
import tempfile

import pytest


APP_URL = os.environ.get("TASKVERGE_TEST_URL", "")
pytestmark = pytest.mark.skipif(not APP_URL, reason="start task-panel.pyw --ci and set TASKVERGE_TEST_URL")


def api(page, path, payload=None):
    return page.evaluate("""async ({path, payload}) => {
      await TaskVergeApi.ensureSession();
      return await TaskVergeApi.api(path, payload === null ? undefined : payload);
    }""", {"path": path, "payload": payload})


def test_outcome_evidence_survives_ui_save_reload_edit_and_recheck():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(APP_URL)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_function("() => !!window.TaskVergeApi?.sessionToken()", timeout=10000)

        criterion_ids = ["criterion-ui-roundtrip-a", "criterion-ui-roundtrip-b"]
        configured = api(page, "settings", {
            "goals": [{"id": "goal-ui-roundtrip", "title": "UI 证据往返目标"}],
            "active_goal": 0,
            "goal_details": {"outcome": "一个可核验结果",
                             "success_criteria": ["输出正确", "内容完整"], "constraints": []},
            "privacy": {"cloud_ai_enabled": False},
        })
        assert configured.get("ok"), configured
        seeded = api(page, "tasks", {"reason": "UI evidence roundtrip", "tasks": [{
            "id": "outcome-ui-roundtrip", "title": "UI 证据往返验收", "task_kind": "outcome",
            "type": "outcome", "status": "pending", "verification_mode": "strict",
            "expected_output": "一个可核验结果", "acceptance": "每条标准有独立证据",
            "criteria": [{"id": criterion_ids[0], "text": "输出正确"},
                         {"id": criterion_ids[1], "text": "内容完整"}],
            "criterion_ids": criterion_ids, "criterion_evidence": {}, "evidence": [],
        }]})
        assert seeded.get("ok"), seeded
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        page.locator("#currentTaskBar [data-start-task]").click()
        page.locator('[data-criterion-text="0"][data-criterion-id="criterion-ui-roundtrip-a"]').wait_for(timeout=10000)

        page.locator('[data-criterion-text="0"][data-criterion-id="criterion-ui-roundtrip-a"]').fill("直接文字证据A：42")
        page.locator('[data-criterion-text="0"][data-criterion-id="criterion-ui-roundtrip-b"]').fill("直接文字证据B：42")
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as evidence:
            evidence.write("附件真实内容：42")
            evidence_path = evidence.name
        try:
            page.locator('[data-criterion-evidence-file="0"][data-criterion-id="criterion-ui-roundtrip-a"]').set_input_files(evidence_path)
            page.wait_for_function("""async () => {
              const s = await TaskVergeApi.api('state');
              const rows = s.tasks?.[0]?.criterion_evidence?.['criterion-ui-roundtrip-a'] || [];
              return rows.some(row => row.kind === 'attachment' && row.ref);
            }""", timeout=10000)
            assert page.locator('[data-criterion-text="0"][data-criterion-id="criterion-ui-roundtrip-a"]').input_value() == "直接文字证据A：42"
            assert page.locator('[data-criterion-text="0"][data-criterion-id="criterion-ui-roundtrip-b"]').input_value() == "直接文字证据B：42"
        finally:
            os.unlink(evidence_path)

        page.locator('[data-save-criterion-evidence="0"]').click()
        page.wait_for_function("""async () => {
          const s = await TaskVergeApi.api('state');
          const first = s.tasks?.[0]?.criterion_evidence?.['criterion-ui-roundtrip-a'] || [];
          const second = s.tasks?.[0]?.criterion_evidence?.['criterion-ui-roundtrip-b'] || [];
          return first.some(row => row.kind === 'direct_text' && row.text === '直接文字证据A：42') &&
                 first.some(row => row.kind === 'attachment' && row.ref) &&
                 second.some(row => row.kind === 'direct_text' && row.text === '直接文字证据B：42');
        }""", timeout=10000)
        before_evaluate = api(page, "state")
        assert any(row.get("kind") == "attachment" and row.get("ref")
                   for row in before_evaluate["tasks"][0]["criterion_evidence"][criterion_ids[0]]), before_evaluate["tasks"][0].get("criterion_evidence")
        evaluated = api(page, "evaluate-task", {"idx": 0})
        assert evaluated.get("status") == "needs_review", evaluated

        page.reload()
        page.wait_for_load_state("domcontentloaded")
        text_box = page.locator('[data-criterion-text="0"][data-criterion-id="criterion-ui-roundtrip-a"]')
        text_box.wait_for(timeout=10000)
        assert "[object Object]" not in text_box.input_value()
        assert text_box.input_value() == "直接文字证据A：42"
        second_text_box = page.locator('[data-criterion-text="0"][data-criterion-id="criterion-ui-roundtrip-b"]')
        assert second_text_box.input_value() == "直接文字证据B：42"
        assert page.locator('[data-criterion-attachments="0"][data-criterion-id="criterion-ui-roundtrip-a"]').inner_text().strip()

        before_unchanged = api(page, "state")
        rows = before_unchanged["tasks"][0]["criterion_evidence"][criterion_ids[0]]
        assert any(row.get("kind") == "attachment" and row.get("ref") for row in rows), before_unchanged["tasks"][0].get("criterion_evidence")
        page.locator('[data-save-criterion-evidence="0"]').click()
        page.wait_for_timeout(300)
        unchanged = api(page, "state")
        rows = unchanged["tasks"][0]["criterion_evidence"][criterion_ids[0]]
        assert any(row.get("kind") == "attachment" and row.get("ref") for row in rows)
        assert any(row.get("kind") == "direct_text" and row.get("text") == "直接文字证据A：42" for row in rows)
        rows = unchanged["tasks"][0]["criterion_evidence"][criterion_ids[1]]
        assert any(row.get("kind") == "direct_text" and row.get("text") == "直接文字证据B：42" for row in rows)

        text_box.fill("修改后的文字证据A：43")
        page.locator('[data-save-criterion-evidence="0"]').click()
        page.wait_for_function("""async () => {
          const s = await TaskVergeApi.api('state');
          const first = s.tasks?.[0]?.criterion_evidence?.['criterion-ui-roundtrip-a'] || [];
          const second = s.tasks?.[0]?.criterion_evidence?.['criterion-ui-roundtrip-b'] || [];
          return first.some(row => row.kind === 'direct_text' && row.text === '修改后的文字证据A：43') &&
                 second.some(row => row.kind === 'direct_text' && row.text === '直接文字证据B：42') &&
                 first.some(row => row.kind === 'attachment' && row.ref);
        }""", timeout=10000)
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        assert page.locator('[data-criterion-text="0"][data-criterion-id="criterion-ui-roundtrip-a"]').input_value() == "修改后的文字证据A：43"
        assert page.locator('[data-criterion-text="0"][data-criterion-id="criterion-ui-roundtrip-b"]').input_value() == "直接文字证据B：42"
        assert "[object Object]" not in page.locator('[data-criterion-attachments="0"][data-criterion-id="criterion-ui-roundtrip-a"]').inner_text()
        rechecked = api(page, "evaluate-task", {"idx": 0})
        assert rechecked.get("status") == "needs_review", rechecked
        browser.close()
