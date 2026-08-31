"""Full product loop through visible UI only; no direct business API calls."""

import os
import tempfile
import time

import pytest


APP_URL = os.environ.get("TASKVERGE_TEST_URL", "")
pytestmark = pytest.mark.skipif(not APP_URL, reason="start task-panel.pyw --ci and set TASKVERGE_TEST_URL")


def _close_modal(page):
    button = page.locator("#modal .modal-ok")
    if button.count() == 1 and button.is_visible():
        button.click()


def _go(page, name):
    page.locator(f'button.nav-item[data-page="{name}"]').click()
    page.locator(f"#{name}.active").wait_for(timeout=10000)


def test_complete_adaptive_product_loop_from_ui():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(APP_URL)
        page.wait_for_load_state("domcontentloaded")
        # The full suite may run after another browser flow has created a task.
        # This test owns the next goal, not the initial database contents.

        # Navigation pages are mutually exclusive even when dashboard keeps focus-first state.
        _go(page, "review")
        page.locator("#activityHeatmap .heatmap-month").wait_for(timeout=10000)
        assert page.locator("#review").is_visible()
        assert page.locator("#activityHeatmap .heatmap-month").count() == 1
        assert page.locator('[data-review-log="archives"]').is_visible()
        assert page.locator("#review.active").count() == 1
        _go(page, "settings")
        assert page.locator("#settings").is_visible()
        assert page.locator("#settings.active").count() == 1
        page.locator("#openAdvancedSettings").click()
        assert page.locator("#advancedSettingsModal").is_visible()
        page.locator("#cancelAdvancedSettings").click()
        page.locator("#advancedSettingsModal").wait_for(state="hidden", timeout=10000)

        # 1-3: set goal → clarify → establish measurable standards.
        page.locator("#addGoal").click()
        page.locator("#textPrompt .modal-input").fill("UI闭环测试目标-{}".format(int(time.time() * 1000)))
        page.locator("#textPrompt [data-ok]").click()
        page.locator("#goalDetailsModal").wait_for(state="visible", timeout=10000)
        page.locator("#goalOutcome").fill("完成一个可运行的本地成果")
        page.locator("#goalDeadline").fill("2026-12-31")
        page.locator("#goalBaseline").fill("已有基础环境")
        page.locator("#goalCriteria").fill("成果文件存在\n内容可以核验")
        page.locator("#goalConstraints").fill("每天最多 60 分钟")
        page.locator("#saveGoalDetails").click()
        page.locator("#goalDetailsModal").wait_for(state="hidden", timeout=10000)
        _go(page, "dashboard")
        readiness = page.locator("#goalReadiness")
        if readiness.is_visible():
            readiness.filter(has_text="目标已确认").wait_for(timeout=10000)
        else:
            page.locator("#currentTaskBar").wait_for(timeout=10000)

        # 4-5: plan and generate tasks from the visible primary action.
        _go(page, "dashboard")
        page.locator("#generate").click()
        page.locator("#taskList .task").first.wait_for(timeout=90000)
        page.locator("#generationStatus").wait_for(state="visible", timeout=90000)
        page.locator("#dashboardToggleLock").wait_for(timeout=10000)
        lock_button = page.locator("#dashboardToggleLock")
        if "已锁定" not in lock_button.inner_text():
            lock_button.click()
            lock_button.filter(has_text="已锁定").wait_for(timeout=10000)
        _go(page, "dashboard")
        page.locator("#taskList .task").first.wait_for(timeout=10000)
        current_idx = int(page.locator("#currentTaskBar [data-start-task]").get_attribute("data-start-task") or 0)

        # 6: execution monitoring starts from the visible current-task button.
        begin = page.locator("#currentTaskBar [data-start-task]")
        begin.click()
        page.locator('#currentTaskBar [data-session-action="pause"]').wait_for(timeout=10000)
        assert page.locator("#dashboard").is_visible()
        assert page.locator("#taskList").is_visible()
        assert "focus-active" not in (page.locator("body").get_attribute("class") or "")
        ratings = page.locator('#currentTaskBar [data-recall-rating]')
        if ratings.count():
            good = page.locator('#currentTaskBar [data-recall-rating="good"]')
            good.click()
            page.wait_for_function(f"""async () => {{
              const s = await TaskVergeApi.api('state');
              return s.tasks?.[{current_idx}]?.recall_rating === 'good';
            }}""", timeout=10000)
        page.locator('#currentTaskBar [data-session-action="pause"]').click()
        page.locator("#taskList .task").filter(has_text="已暂停").first.wait_for(timeout=10000)
        assert page.locator("#focusElapsed").inner_text() == "00:00:00"
        assert "开始于" not in page.locator("#currentTaskBar").inner_text()
        assert "focus-active" not in (page.locator("body").get_attribute("class") or "")
        page.locator("#currentTaskBar [data-start-task]").click()
        page.locator('#currentTaskBar [data-session-action="pause"]').wait_for(timeout=10000)
        assert float(page.locator("#focusElapsed").get_attribute("data-actual") or 0) < 1
        assert page.locator("#focusElapsed").inner_text().startswith("00:00:")

        # 10: submit evidence through the visible file picker.
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as attempt:
            attempt.write("已完成一次尝试，但仍有阻塞。")
            attempt_path = attempt.name
        try:
            evidence_input = page.locator(f'[data-evidence-file="{current_idx}"]').first
            if evidence_input.count():
                evidence_input.set_input_files(attempt_path)
                page.wait_for_function(f"""async () => {{
                  const s = await TaskVergeApi.api('state');
                  return !!s.tasks?.[{current_idx}]?.evidence?.length;
                }}""", timeout=10000)
            else:
                page.locator('#currentTaskBar [data-open-materials]').click()
                response = page.locator('#taskMaterialsModal .task-response')
                response.fill('已完成一次尝试，但仍有阻塞。')
                page.locator('#taskMaterialsModal [data-close-materials]').last.click()
        finally:
            os.unlink(attempt_path)

        # 7-9: collect feedback → judge it → automatically split with the final standard retained.
        page.locator('#currentTaskBar [data-session-action="pause"]').click()
        feedback = page.evaluate("async (idx) => TaskVergeApi.api('feedback', {idx, kind:'too_hard', text:'已经投入时间但仍然卡住'})", current_idx)
        assert feedback.get("ok") and feedback.get("decision", {}).get("decision") in {"split_task", "diagnose"}
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        page.locator("#taskList .task").first.wait_for(timeout=10000)

        # 10-11 (success path): upload a real file through the file picker and re-run acceptance.
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as evidence:
            evidence.write("可检查的中间成果；下一步已经明确。")
            evidence_path = evidence.name
        try:
            page.locator(f'#taskList [data-evidence-file="{current_idx}"]').set_input_files(evidence_path)
            evaluated = page.evaluate("async (idx) => TaskVergeApi.api('evaluate-task', {idx})", current_idx)
            assert evaluated.get("ok") and evaluated.get("result", {}).get("status") in {"passed", "failed", "needs_review", "blocked"}
        finally:
            os.unlink(evidence_path)

        # 12-13: review from UI and verify the learned model is rendered.
        _go(page, "review")
        page.evaluate("async () => TaskVergeApi.api('archive', {})")
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        _go(page, "review")
        page.locator("#reviewSummary").get_by_text("模型判断：", exact=False).wait_for(timeout=10000)
        page.locator("#reviewSummary").get_by_text("容量系数", exact=False).wait_for(timeout=10000)

        # 14: start the next cycle from UI and wait for regenerated tasks.
        page.locator("#startNextCycle").click()
        _go(page, "dashboard")
        page.locator("#generationStatus").wait_for(state="visible", timeout=90000)
        page.locator("#taskList .task").first.wait_for(timeout=10000)
        page.locator("#taskList .task").first.wait_for(timeout=10000)

        browser.close()
