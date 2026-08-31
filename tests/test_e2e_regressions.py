"""Browser regressions for the product seams that unit tests cannot observe."""

import os
import tempfile

import pytest


APP_URL = os.environ.get("TASKVERGE_TEST_URL", "")
pytestmark = pytest.mark.skipif(not APP_URL, reason="start task-panel.pyw --ci and set TASKVERGE_TEST_URL")


def state(page):
    return page.evaluate("async () => TaskVergeApi.api('state')")


def post(page, path, payload):
    return page.evaluate("""async ({path,payload}) => {
      await TaskVergeApi.ensureSession();
      const token = TaskVergeApi.sessionToken();
      const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json','X-Session':token}, body:JSON.stringify(payload)});
      return {status:r.status, body:await r.json()};
    }""", {"path": path, "payload": payload})


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        current = context.new_page()
        current.on("dialog", lambda dialog: dialog.accept())
        current.goto(APP_URL)
        current.wait_for_load_state("domcontentloaded")
        current.wait_for_function("() => !!window.TaskVergeApi?.sessionToken()", timeout=10000)
        details = {"outcome": "回归目标结果", "deadline": "2026-12-31",
                   "baseline": "已有基础", "success_criteria": ["结果可核验"],
                   "constraints": ["时间有限"]}
        configured = post(current, "/api/settings", {
            "goals": [{"id": "e2e-regression", "title": "E2E回归目标"}],
            "active_goal": 0, "goal_details": details,
        })
        assert configured["status"] == 200, configured
        unlocked = post(current, "/api/lock-plan", {
            "locked": False, "reason": "E2E regression fixture",
        })
        assert unlocked["status"] == 200, unlocked
        seeded = post(current, "/api/tasks", {"tasks": [{
            "title": "E2E轮询稳定性任务",
            "expected_output": "可核验交付物",
            "acceptance": "必须包含交付物",
            "verification_mode": "evidence",
        }], "reason": "E2E regression fixture"})
        assert seeded["status"] == 200, seeded
        current.reload()
        current.wait_for_load_state("domcontentloaded")
        current.wait_for_function("() => document.querySelector('#taskList [data-task-index]')", timeout=10000)
        yield current
        context.close()
        browser.close()


def test_needs_review_does_not_grow_companion(page):
    """Unresolved semantic rules must not complete or grow a task."""
    seeded = post(page, "/api/tasks", {"tasks": [{
        "title": "语义复核回归任务",
        "expected_output": "alpha beta gamma",
        "acceptance": "必须包含视觉证明",
        "verification_mode": "evidence",
    }], "reason": "E2E regression fixture"})
    assert seeded["status"] == 200, seeded
    target = len(state(page)["tasks"]) - 1
    page.reload()
    page.wait_for_load_state("domcontentloaded")

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as evidence:
        evidence.write("没有任何目标关键词")
        evidence_path = evidence.name
    try:
        before = state(page)
        before_companion = before.get("companion") or {}
        page.locator(f'#taskList [data-evidence-file="{target}"]').set_input_files(evidence_path)
        page.wait_for_function(f"""async () => {{
          const s = await TaskVergeApi.api('state');
          return !!s.tasks?.[{target}]?.evidence?.length;
        }}""")
        page.locator(f'#taskList [data-ai-evaluate="{target}"]').click(force=True)
        page.wait_for_function(f"async () => ['needs_review','passed','failed','blocked'].includes((await TaskVergeApi.api('state')).tasks?.[{target}]?.acceptance_result?.status)", timeout=10000)
        after = state(page)
        result = after["tasks"][target].get("acceptance_result") or {}
        if not result:
            result = page.evaluate(f"async () => (await TaskVergeApi.api('evaluate-task', {{idx: {target}}})).result || {{}}")
        if result.get("status") not in {"needs_review", "blocked"}:
            pytest.fail("fixture did not reach a non-passing review state: {}".format(result))
        after_companion = after.get("companion") or {}
        assert after_companion.get("energy") == before_companion.get("energy")
        assert after_companion.get("bond") == before_companion.get("bond")
        assert len(after_companion.get("events", [])) == len(before_companion.get("events", []))
        assert after["tasks"][target].get("done") is not True
    finally:
        os.unlink(evidence_path)


def test_poll_does_not_replace_task_card(page):
    """The live poll must preserve a task card and its file input DOM node."""
    card = page.locator('#taskList [data-task-index="0"]').first
    file_input = page.locator('#taskList [data-evidence-file="0"]').first
    assert card.count() and file_input.count(), "fixture task card is not editable"
    page.evaluate("""() => {
      window.__e2eCard = document.querySelector('#taskList [data-task-index="0"]');
      window.__e2eFileInput = document.querySelector('#taskList [data-evidence-file="0"]');
    }""")
    page.locator('#taskList [data-evidence-file="0"]').set_input_files(__file__)
    page.wait_for_timeout(3500)
    assert card.evaluate("el => el.isConnected")
    assert file_input.evaluate("el => el.isConnected")
    assert page.evaluate("""() => window.__e2eCard === document.querySelector('#taskList [data-task-index="0"]')""")
    assert page.evaluate("""() => window.__e2eFileInput === document.querySelector('#taskList [data-evidence-file="0"]')""")


def test_goal_rename_preserves_identity(page):
    details = {"outcome": "E2E identity outcome", "deadline": "2026-12-31",
               "baseline": "已有基础", "success_criteria": ["结果可核验"], "constraints": ["时间有限"]}
    first = post(page, "/api/settings", {"goals": [
        {"id": "e2e-goal-a", "title": "E2E目标A"},
        {"id": "e2e-goal-b", "title": "E2E目标B"}], "active_goal": 0,
        "goal_details": details})
    assert first["status"] == 200, first
    before = state(page)
    second = post(page, "/api/settings", {"goals": [
        {"id": "e2e-goal-a", "title": "E2E目标A-改名"},
        {"id": "e2e-goal-b", "title": "E2E目标B"}], "active_goal": 0,
        "goal_details": details})
    assert second["status"] == 200, second
    after = state(page)
    assert [g["id"] for g in before["goal_records"]] == ["e2e-goal-a", "e2e-goal-b"]
    assert [g["id"] for g in after["goal_records"]] == ["e2e-goal-a", "e2e-goal-b"]
    assert after["goal"] == "E2E目标A-改名"


def test_privacy_refusal_stops_monitoring(page):
    result = post(page, "/api/privacy-consent", {"accepted": False})
    assert result["status"] == 200, result
    assert state(page)["privacy"]["monitoring_consent"] is False


def test_backup_restore_requires_confirmation_and_preserves_backup(page):
    backup = post(page, "/api/storage-backup", {})
    assert backup["status"] == 200 and backup["body"].get("ok")
    path = backup["body"]["path"]
    rejected = post(page, "/api/storage-restore", {"path": path, "confirm": False})
    assert rejected["status"] == 400
    restored = post(page, "/api/storage-restore", {"path": path, "confirm": True})
    assert restored["status"] == 200 and restored["body"].get("ok")
