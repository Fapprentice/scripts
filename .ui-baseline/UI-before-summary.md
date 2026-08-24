# UI Rebuild — Before Baseline (v0.2.0)

Collected: 2026-08-24 (agent: verifier, team ui-rebuild, task t1)

## 1. Test suite baseline

Command: `python -m pytest -q -p no:cacheprovider tests` (Python 3.12.13 via workspace uv venv .ui-venv, pytest 9.1.1 — the same version the repo's cached pyc files were built with).

Result: **117 passed, 27 skipped, 2 failed, 3 errors in 0.80s**

All 5 non-passing items are environment (sandbox) PermissionErrors, not product defects:

- FAILED tests/test_applog.py::TestSetupLogging::test_creates_log_files — PermissionError writing log files (file-policy denied path)
- FAILED tests/test_secretstore.py::TestSecretStore::test_encrypt_decrypt_roundtrip — secretstore.save_key(...) returned False (key-file write denied)
- ERROR tests/test_secretstore.py::TestSecretStore::test_key_file_path — teardown PermissionError: [WinError 5] cleaning %TEMP%\dsh-*\tmp...
- ERROR tests/test_state_store.py::test_json_store_round_trip / test_json_store_keeps_previous_file_on_bad_json — setup/teardown temp-dir PermissionError

Cause: this session runs under DSH workspace-write file policy; the app/tests write to %LocalAppData% / %TEMP% (outside the workspace), which is denied. Full log: pytest-run.log.

## 2. UI before screenshots — NOT captured (explained)

Playwright is not installed (checked python venv and npm global). Attempted fallback: headless Chromium screenshots via installed **Edge** and **Chrome** (--headless=new --screenshot / --dump-dom / CDP Page.captureScreenshot).

All attempts failed with the documented DSH sandbox boundary:

    FATAL:mojo\public\cpp\platform\platform_channel.cc:108] Check failed: . : 拒绝访问。 (0x5)
    crash server failed to launch, self-terminating

Headless Chromium cannot run under the confined file sandbox because its multi-process mojo IPC uses named pipes, which the sandbox denies (same documented EPERM boundary as piped-child-stdout). Approval/escalation is disabled in this session, so this cannot be retried with wider permissions here.

**Alternative "before" artifacts captured instead** (served live from http://127.0.0.1:64161/):

- index.html — current SPA shell (13.8 KB)
- app.js — current UI logic (97 KB)
- app.css — current styles (90 KB)
- state.json — live app state snapshot via /api/state (255 KB: goal, tasks, agents, settings, etc.)

## 3. Current UI structure (v0.2.0) — mapping for the redesign's 5 views

SPA served from web/ (single index.html + app.js + app.css), client-side page switching via nav buttons (.nav-item[data-page]), no hash routing.

| Requested view | Exists in v0.2.0? | Location |
|---|---|---|
| dashboard (总览) | Yes | <section id="dashboard"> — 今日执行/当前任务条, 任务队列 (#taskList), 专注画像, 应用面板 |
| tasks (任务列表) | No standalone page | Task queue lives inside the dashboard #taskList panel |
| apps (应用分类) | No standalone page | pageTitles in app.js references a "rules" page (应用分类) but no nav button or section exists in index.html; only an advanced-settings dialog |
| review (复盘) | Yes | <section id="review"> — 退出记录/事件流/归档 |
| settings (设置) | Yes | <section id="settings"> — 目标、生成参数、休息、退出 |

Nav bar has exactly 3 buttons: dashboard, review, settings. Redesign scope: tasks and apps must become first-class views.

## 4. Baseline commit

Committed as "chore: baseline before UI redesign (v0.2.0)" — see git log -1 for the hash. Only .ui-baseline/ was staged; team/scratch files intentionally left untracked.
