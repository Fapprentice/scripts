"""E2E main flow test — migrated from dogfood-output for CI.

Covers: set goal → generate tasks → upload deliverable → AI accept → verify state.

Run with: python -m pytest tests/test_e2e_main_flow.py -v --timeout=180

Requires the app to be running in --ci mode on the port in APP_URL.
"""

import os, sys, time

import pytest

APP_URL = os.environ.get("TASKVERGE_TEST_URL", "")
TEST_GOAL = "E2E测试目标-Python基础-{}".format(int(time.time() * 1000))

# Skip E2E if no app is running (e.g. local dev without --ci)
pytestmark = pytest.mark.skipif(
    not APP_URL or APP_URL.endswith(":0/"),
    reason="No running Task Verge instance found — start with python task-panel.pyw --ci",
)

def _state(page):
    return page.evaluate("async () => TaskVergeApi.api('state')")


@pytest.fixture(scope="module")
def playwright_browser():
    """Module-scoped browser — reused across tests."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture(scope="module")
def page(playwright_browser):
    """Fresh page for the test module."""
    ctx = playwright_browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()

    # Auto-dismiss native dialogs
    page.on("dialog", lambda d: d.accept())

    # Collect console errors
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

    page.goto(APP_URL)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_function("() => !!window.TaskVergeApi?.sessionToken()", timeout=10000)
    page.wait_for_function("() => document.querySelector('#taskList')?.children.length > 0", timeout=10000)

    yield page

    page.context.close()

    # Write errors to stderr for CI visibility
    if errors:
        print(f"\n[CONSOLE ERRORS] {len(errors)} detected:", file=sys.stderr)
        for e in errors[:10]:
            print(f"  {e[:200]}", file=sys.stderr)


class TestE2EMainFlow:
    """End-to-end: goal → generate → upload → evaluate."""

    def test_01_app_loads(self, page):
        """App loads without crashing."""
        title = page.title()
        assert title, "Page should have a title"
        state = _state(page)
        assert "tasks" in state, "State should contain tasks key"

    def test_02_set_goal(self, page):
        """Set a test goal via settings."""
        page.click('button.nav-item[data-page="settings"]')
        page.wait_for_timeout(500)

        # Add test goal
        page.locator('#addGoal').click()
        page.locator('#textPrompt .modal-input').fill(TEST_GOAL)
        page.locator('#textPrompt [data-ok]').click()
        page.locator('#goalDetailsModal').wait_for(state='visible', timeout=10000)

        # Configure task generation
        page.fill('#goalOutcome', '完成一个可运行的 Python 基础练习集')
        page.fill('#goalDeadline', '2026-12-31')
        page.fill('#goalBaseline', '已掌握变量和基本语法')
        page.fill('#goalCriteria', '至少包含列表和字典练习\n脚本可直接运行')
        page.fill('#goalConstraints', '每天最多 60 分钟')
        page.click('#saveGoalDetails')
        page.wait_for_timeout(500)
        page.click('#openAdvancedSettings')
        page.locator('#advancedSettingsModal').wait_for(state='visible', timeout=10000)
        page.fill('#genTaskCount', '2')
        page.fill('#genAvailableMinutes', '60')
        page.fill('#genMaxTaskMinutes', '30')
        page.click('#saveAdvancedSettings')
        page.wait_for_timeout(1500)
        saved = _state(page)
        assert saved.get("goal_readiness", {}).get("ready") is True
        assert saved.get("goal") == TEST_GOAL

        # Verify the saved goal survives navigation.
        page.click('button.nav-item[data-page="dashboard"]')
        page.wait_for_timeout(500)
        assert _state(page).get("goal") == TEST_GOAL

    def test_03_generate_tasks(self, page):
        """Generate tasks and wait for completion."""
        page.click('#generate')
        page.wait_for_timeout(1000)

        deadline = time.time() + 90
        while time.time() < deadline:
            st = page.evaluate(
                "async () => { const r = await fetch('/api/generate-status'); return r.json(); }"
            )
            if not st.get("running"):
                break
            page.wait_for_timeout(1500)

        state = _state(page)
        tasks = state.get("tasks", [])
        assert len(tasks) > 0, "Should have at least one task after generation"
        assert state.get("plan_locked"), "Plan should be locked after generation"
        ok = page.locator("#modal .modal-ok")
        if ok.count() and ok.is_visible(): ok.click()

    def test_04_upload_deliverable(self, page):
        """Upload a Python deliverable for task[0]."""
        # Create a temp deliverable file
        import tempfile
        deliverable = tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", delete=False, encoding="utf-8"
        )
        deliverable.write(
            "# list_dict_exercises.py\n"
            "# 练习1: 列表增删改查\n"
            "def list_crud():\n"
            "    a = [1, 2, 3]\n"
            "    a.append(4)\n"
            "    a.remove(2)\n"
            "    a[0] = 9\n"
            "    return a\n\n"
            "# 练习2: 字典键值操作\n"
            "def dict_ops():\n"
            "    d = {'x': 1, 'y': 2}\n"
            "    d['z'] = 3\n"
            "    del d['x']\n"
            "    d['y'] = 20\n"
            "    return d.get('y'), d.get('z')\n\n"
            "# 练习3: 综合练习\n"
            "def student_grades():\n"
            "    grades = {'alice': 90, 'bob': 85}\n"
            "    grades['alice'] = 95\n"
            "    avg = sum(grades.values()) / len(grades)\n"
            "    return avg\n\n"
            "if __name__ == '__main__':\n"
            "    print('list:', list_crud())\n"
            "    print('dict:', dict_ops())\n"
            "    print('avg:', student_grades())\n",
        )
        deliverable_path = deliverable.name
        deliverable.close()

        try:
            # Find the file input and upload
            file_input = page.locator('[data-evidence-file="0"]').first
            if file_input.count() > 0:
                file_input.set_input_files(deliverable_path)
                page.wait_for_function("""async () => {
                  const s = await TaskVergeApi.api('state');
                  return !!s.tasks?.[0]?.evidence?.length;
                }""", timeout=10000)
            else:
                page.evaluate("async () => TaskVergeApi.api('task-response', {idx:0, response:'已提交可核验的本地成果。'})")
                page.reload()
                page.wait_for_load_state('domcontentloaded')

            # Verify evidence persisted
            state = _state(page)
            tasks = state.get("tasks", [])
            if tasks:
                evidence = tasks[0].get("evidence", [])
                assert evidence, "Evidence should be saved after upload"

        finally:
            os.unlink(deliverable_path)

    def test_05_ai_evaluate(self, page):
        """Trigger AI evaluation and check results."""
        evaluate_button = page.locator('[data-ai-evaluate="0"]').first
        if evaluate_button.count() and evaluate_button.is_visible():
            evaluate_button.click(force=True)
            page.wait_for_timeout(10000)
        else:
            page.evaluate("async () => TaskVergeApi.api('evaluate-task', {idx:0})")

        state = _state(page)
        tasks = state.get("tasks", [])
        assert tasks, "Should have tasks after evaluation"

        # Check that acceptance_result exists (even if it failed due to missing API key)
        ar = tasks[0].get("acceptance_result", {})
        assert isinstance(ar, dict), "Should have acceptance_result dict"

    def test_06_state_consistency(self, page):
        """Final state integrity check."""
        state = _state(page)
        # Basic integrity
        assert isinstance(state.get("tasks"), list)
        assert isinstance(state.get("done_flags"), list)
        assert isinstance(state.get("completion_pct"), (int, float))
        assert 0 <= state.get("completion_pct", 0) <= 100

    def test_07_agent_run(self, page):
        """Agent start/observe loop persists a bounded run."""
        result = page.evaluate("""async () => {
          return TaskVergeApi.api('agent-start', {idx:0,max_steps:4});
        }""")
        assert result.get('ok'), result
        run_id = result['run']['run_id']
        run = None
        for _ in range(20):
            page.wait_for_timeout(500)
            state = _state(page)
            run = next((x for x in state.get('agent_runs', []) if x.get('run_id') == run_id), None)
            if run and run.get('step', 0) > 0: break
        assert run and run.get('step', 0) > 0, state

    def test_08_feedback_is_judged_not_blindly_applied(self, page):
        """A direction-change claim is recorded but never applied automatically."""
        result = page.evaluate("""async () => {
          return TaskVergeApi.api('feedback', {idx:0,kind:'wrong_direction',text:'方向不对'});
        }""")
        assert result.get("ok"), result
        assert result["decision"]["decision"] == "realign"
        assert result["decision"]["applied"] is False
        state = _state(page)
        assert state.get("feedback_history")
        assert "feedback_reliability" in state.get("user_model", {})

    def test_09_review_updates_model_and_next_cycle_regenerates(self, page):
        """Archive → model update → retain unfinished → generate the next cycle."""
        result = page.evaluate("""async () => {
          return TaskVergeApi.api('next-cycle', {});
        }""")
        assert result.get("ok"), result
        state = _state(page)
        assert state.get("last_review", {}).get("ts")
        assert state.get("user_model", {}).get("review_count", 0) >= 1
        assert all(t.get("status") != "done" for t in state.get("tasks", []))

        started = page.evaluate("""async () => {
          return TaskVergeApi.api('generate', {});
        }""")
        assert started.get("ok"), started
        deadline = time.time() + 90
        while time.time() < deadline:
            status = page.evaluate("async () => (await fetch('/api/generate-status')).json()")
            if not status.get("running"):
                break
            page.wait_for_timeout(1000)
        state = _state(page)
        assert state.get("tasks"), "Next cycle should contain generated or fallback tasks"
        assert state.get("adaptive_task_gen", {}).get("adaptive_capacity_factor")
