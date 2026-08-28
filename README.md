# Task Verge

Windows-only local execution system that turns personal goals into measurable tasks, supplies required task materials, tracks focused work, and validates outcomes.

The product loop is: define and clarify a goal → establish measurable standards → plan and generate tasks → monitor execution → judge active and passive feedback → adjust without silently lowering the final standard → collect evidence → accept → review → update the per-goal user model → generate the next cycle. See `PRODUCT_FLOW.md` for the behavior contract.

## Runtime

- Windows desktop app: native WebView2 window backed by the local `task-panel.pyw` service
- Source mode needs Python 3.11+ and `requirements.txt`; add `requirements-dev.txt`, `requirements-e2e.txt`, or `requirements-build.txt` only for tests, browser E2E, or packaging respectively. Packaged `TaskVerge.exe` is self-contained
- DeepSeek API key from `.env` or Hermes env files
- Docker Desktop is required for Python deliverable execution checks (optional — only for AI acceptance)

## Features

- **Per-goal definitions**: every goal keeps its own final outcome, deadline, baseline, measurable success criteria, and real-world constraints
- **AI task generation**: goal-aware structured tasks with expected output and acceptance criteria, generated daily
- **Executable task materials**: quizzes, passages, listening scripts, prompts, and other required inputs are attached to the task and completed in a popup panel
- **AI acceptance**: upload deliverables → AI reads file contents, runs `py_compile` + Docker sandbox, returns pass/fail with missing items and next steps
- **AI coach**: chat-based suggestions (reschedule, regenerate, archive) backed by automatic insight cards (low completion, focus drift, missing evidence)
- **AI app recognition**: two-stage (categories → specific apps) identification of task-relevant applications for a visual "work desktop"
- **Time blocks**: auto-generated daily schedule with 90-minute focus sessions and auto-inserted breaks
- **Foreground tracking**: every 2 seconds, foreground window title sampled and accumulated
- **Break timer**: up to 3 breaks per day, 1–60 minutes
- **Exit guard**: in-app exit requires a reason when tasks are unfinished; the explicit tray “退出” command stops immediately and records the exit
- **Privacy gate**: foreground-window tracking starts only after explicit consent; disabling detailed titles records only the executable name
- **Agent workspace**: file and command tools are restricted to the existing directory selected in Settings
- **Multi-goal isolation**: each goal gets independent tasks, apps, completion percentage, and catalog
- **Learning loop**: FSRS review scheduling, recall-quality feedback, ability diagnostics, and a per-goal knowledge graph
- **AI quality gates**: 26 versioned golden cases score goal quality, task alignment, material/key grounding, evidence acceptance, semantic uncertainty, and repeat stability before release
- **Review view**: daily summary, knowledge graph, current-month execution heatmap with access to the most recent 12 months, and popup history logs
- **Crash recovery**: detects unclean exit on next launch and warns the user
- **Single instance**: PID file + Windows Mutex dual guard; duplicate startups focus or reopen the existing window
- **Backend session lock**: `X-Session` token (8s TTL) prevents concurrent writes from multiple browser tabs
- **System tray**: ctypes `Shell_NotifyIconW` with open/quit menu
- **Startup auto-launch**: writes to `%APPDATA%\Start Menu\Startup`

## Web address and tests

- Normal desktop mode uses `http://127.0.0.1:64161/` by default. Set `TASKVERGE_PORT` to override it; a busy port falls back to a random local port.
- CI mode (`python task-panel.pyw --ci`) binds `TASKVERGE_PORT` when set (use `0` for an OS-chosen port), prints `CI_URL=http://127.0.0.1:<resolved-port>/`, and writes the same URL to `task-panel.url`. Export that resolved URL as `TASKVERGE_TEST_URL` before API or browser tests.
- API and browser E2E suites claim the single backend session; run them against separate CI instances (or run the suites separately).
- The default test command is safe and does not attach to the user's live instance: `python -m pytest -q tests`.
- Syntax gate: `python -m ruff check --select E9,F63,F7,F82 .` plus `node --check web/api.js`, `node --check web/views.js`, and `node --check web/app.js`.
- The AI release gate is `python evaluation.py --run`; it exits non-zero on a regression and is enforced by GitHub Actions.
- CI readiness probes public `/api/heartbeat`; authenticated `/api/state` still requires an `X-Session` token from `/api/claim`.
- AI quality evaluation is a backend and CI capability; it adds no page, button, modal, or first-screen content to the desktop UI.

## Runtime modes

| Command | Mode |
|---------|------|
| `python task-panel.pyw` | Desktop mode (default) — HTTP server + tray + native WebView2 window |
| `python task-panel.pyw --generate` | CLI — generate daily tasks via DeepSeek |
| `python task-panel.pyw --evaluate` | CLI — evaluate completion via DeepSeek (with file reading + Docker checks) |
| `python task-panel.pyw --stats` | CLI — collect and report PC stats to lianyue.fun |

## Local Data

- `%LOCALAPPDATA%\TaskVerge\taskverge.db`: SQLite is the only source of truth. JSON documents inside the database are compatibility snapshots, not a second writable store.
- `%LOCALAPPDATA%\TaskVerge\attachments\`: SHA-256-addressed, deduplicated task deliverables
- `%LOCALAPPDATA%\TaskVerge\backups\`: automatic, daily, weekly, monthly, manual, pre-migration, and pre-restore database backups. Restore and complete import first write a pre-restore snapshot so the previous database can be put back.
- `%LOCALAPPDATA%\TaskVerge\trash\`: recoverable attachment deletions retained for 30 days
- `%LOCALAPPDATA%\TaskVerge\exports\`: complete `.tvbackup` packages containing the database, attachments, and integrity manifest
- `%LOCALAPPDATA%\TaskVerge\legacy-json\`: read-only copies made when legacy JSON data is imported
- `%LOCALAPPDATA%\TaskVerge\crash.log`: crash recovery marker (`running` / `clean exit` / traceback)
- `%LOCALAPPDATA%\TaskVerge\task-panel.pid`: current running process info for single-instance guard
- `%LOCALAPPDATA%\TaskVerge\icon-cache\`: extracted app icons (SHA1-named PNGs)
- `%LOCALAPPDATA%\TaskVerge\boot.log`: startup diagnostics log
- `%LOCALAPPDATA%\TaskVerge\watchdog.log`: start/stop/error log
- `%LOCALAPPDATA%\TaskVerge\task-verge.key`: current-user DPAPI-encrypted DeepSeek key (never written to `.env`)
- `%LOCALAPPDATA%\TaskVerge\eval-samples.jsonl`: privacy-safe AI incident metadata; raw goal, answer, material, and evidence content is not retained by default

## Main views

- **今日执行**: current task, timer, task-material entry, evidence upload, acceptance, and execution feedback
- **记录**: review summary, knowledge graph, monthly heatmap, archives, event stream, and exit history
- **设置**: goal cards and per-goal definitions; infrequently changed runtime, focus, privacy, workspace, and API settings stay in popup panels

## Notes

This is not cross-platform despite using Python. It calls Windows APIs, `tasklist`,
tray APIs, Startup folder paths, and browser app windows. Keep that explicit.

## Build the Windows app

For signed releases, set `TASKVERGE_SIGNING_THUMBPRINT` to a code-signing certificate in `Cert:\CurrentUser\My`. Optionally set `TASKVERGE_TIMESTAMP_URL`; an invalid signature fails the build.

Install packaging tools with `python -m pip install -r requirements-build.txt`, then run:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -ZipOnly
```

This creates `dist\TaskVerge\TaskVerge.exe` and a portable ZIP. Install Inno Setup 6
and run the script without `-ZipOnly` to additionally create the Windows installer.

`cgi.FieldStorage` is still used for the small multipart upload endpoint. Replace it
when upgrading to Python 3.13 or when upload handling grows beyond this single file.
