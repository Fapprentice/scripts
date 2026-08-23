"""Full product loop through visible UI only; no direct business API calls."""

import os
import tempfile

import pytest


APP_URL = os.environ.get("TASKVERGE_TEST_URL", "")
pytestmark = pytest.mark.skipif(not APP_URL, reason="start task-panel.pyw --ci and set TASKVERGE_TEST_URL")


def _close_modal(page):
    button = page.locator("#modal .modal-ok")
    if button.count() == 1 and button.is_visible():
        button.click()


def _go(page, name):
    page.locator(f'button.nav-item[data-page="{name}"]').click()


def test_complete_adaptive_product_loop_from_ui():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(APP_URL)
        page.wait_for_load_state("networkidle")
        assert page.locator('button.nav-item[data-page="tasks"]').count() == 0

        # Navigation pages are mutually exclusive even when dashboard keeps focus-first state.
        _go(page, "review")
        assert page.locator("#review").is_visible()
        assert page.locator("#activityHeatmap .heatmap-month").count() == 1
        assert page.locator('[data-review-log="archives"]').is_visible()
        assert not page.locator("#dashboard").is_visible()
        _go(page, "settings")
        assert page.locator("#settings").is_visible()
        assert not page.locator("#dashboard").is_visible()
        page.locator("#openAdvancedSettings").click()
        assert page.locator("#advancedSettingsModal").is_visible()
        page.locator("#cancelAdvancedSettings").click()
        assert not page.locator("#advancedSettingsModal").is_visible()

        # 1-3: set goal → clarify → establish measurable standards.
        page.locator("#goalsText").fill("UI闭环测试目标")
        page.locator("#goalOutcome").fill("完成一个可运行的本地成果")
        page.locator("#goalDeadline").fill("2026-12-31")
        page.locator("#goalBaseline").fill("已有基础环境")
        page.locator("#goalCriteria").fill("成果文件存在\n内容可以核验")
        page.locator("#goalConstraints").fill("每天最多 60 分钟")
        page.locator("#genTaskCount").fill("2")
        page.locator("#genAvailableMinutes").fill("60")
        page.get_by_text("隐私控制", exact=True).click()
        page.locator("#privacyCloudAI").uncheck()
        page.locator("#saveSettings").click()
        page.locator("#goalReadiness").filter(has_text="目标定义完整").wait_for(timeout=10000)

        # 4-5: plan and generate tasks from the visible primary action.
        _go(page, "dashboard")
        page.locator("#generate").click()
        page.locator("#taskList .task").first.wait_for(timeout=90000)
        page.locator("#generationStatus").filter(has_text="本地模板").wait_for(timeout=90000)
        page.locator("#dashboardToggleLock").wait_for(timeout=10000)
        lock_button = page.locator("#dashboardToggleLock")
        if "已锁定" not in lock_button.inner_text():
            lock_button.click()
            lock_button.filter(has_text="已锁定").wait_for(timeout=10000)
        _go(page, "dashboard")
        page.locator("#goalUnderstanding").wait_for(timeout=10000)

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
            page.wait_for_function("""async () => {
              const r = await fetch('/api/state', {headers:{'X-Session': sessionToken}});
              const s = await r.json();
              return s.tasks?.[0]?.recall_rating === 'good';
            }""", timeout=10000)
        page.locator('#currentTaskBar [data-session-action="pause"]').click()
        page.locator("#taskList .task").filter(has_text="已暂停").first.wait_for(timeout=10000)
        assert page.locator("#focusElapsed").inner_text() == "00:00:00"
        assert "开始于" not in page.locator("#currentTaskBar").inner_text()
        assert "focus-active" not in (page.locator("body").get_attribute("class") or "")
        page.locator("#currentTaskBar [data-start-task]").click()
        page.locator('#currentTaskBar [data-session-action="pause"]').wait_for(timeout=10000)
        assert page.locator("#focusElapsed").get_attribute("data-actual") == "0"
        assert page.locator("#focusElapsed").inner_text().startswith("00:00:")

        # 10: submit evidence through the visible file picker.
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as attempt:
            attempt.write("已完成一次尝试，但仍有阻塞。")
            attempt_path = attempt.name
        try:
            page.locator('#currentTaskBar [data-evidence-file="0"]').set_input_files(attempt_path)
            page.wait_for_function("""async () => {
              const r = await fetch('/api/state', {headers:{'X-Session': sessionToken}});
              const s = await r.json();
              return !!s.tasks?.[0]?.evidence?.length;
            }""", timeout=10000)
        finally:
            os.unlink(attempt_path)

        # 7-9: collect feedback → judge it → automatically split with the final standard retained.
        page.locator('#currentTaskBar [data-session-action="pause"]').click()
        hard = page.locator('#taskList [data-feedback="too_hard"]').first
        hard.click()
        page.locator("#textPrompt .modal-input").fill("已经投入时间但仍然卡住")
        page.locator("#textPrompt [data-ok]").click()
        page.locator("#modal .modal-title").filter(has_text="已自动调整").wait_for(timeout=10000)
        assert "可信度" in page.locator("#modal .modal-msg").inner_text()
        _close_modal(page)
        page.locator("#taskList").get_by_text("最小步骤：", exact=False).first.wait_for(timeout=10000)

        # 10-11 (success path): upload a real file through the file picker and re-run acceptance.
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as evidence:
            evidence.write("可检查的中间成果；下一步已经明确。")
            evidence_path = evidence.name
        try:
            page.locator('#taskList [data-evidence-file="0"]').set_input_files(evidence_path)
            page.locator('#taskList [data-ai-evaluate="0"]').click()
            page.locator("#modal .modal-title").filter(has_text="验收").wait_for(timeout=90000)
            _close_modal(page)
            page.locator("#taskList .task-compact").first.wait_for(timeout=10000)
        finally:
            os.unlink(evidence_path)

        # 12-13: review from UI and verify the learned model is rendered.
        _go(page, "review")
        page.locator("#archiveToday").click()
        page.locator("#reviewSummary").get_by_text("模型判断：", exact=False).wait_for(timeout=10000)
        page.locator("#reviewSummary").get_by_text("容量系数", exact=False).wait_for(timeout=10000)

        # 14: start the next cycle from UI and wait for regenerated tasks.
        page.locator("#startNextCycle").click()
        _go(page, "dashboard")
        page.locator("#generationStatus").filter(has_text="本地模板").wait_for(timeout=90000)
        page.locator("#taskList .task").first.wait_for(timeout=10000)
        page.locator("#taskList .task").first.wait_for(timeout=10000)

        browser.close()
