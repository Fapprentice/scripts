# Task Verge — Code Wiki

> 专注控制台（Task Verge）：一个面向 Windows 桌面的单文件专注力管控工具。
> 零三方依赖、内置 Web 控制台、结合 DeepSeek AI 进行任务生成、评估验收、应用识别与教练对话。
>
> **文档状态**：本文档基于源码静态分析生成并持续更新；当前运行事实以文末“Current runtime facts”区块和 `README.md` 为准。

---

## 目录

1. [项目概览](#1-项目概览)
2. [整体架构](#2-整体架构)
3. [目录结构](#3-目录结构)
4. [运行模式与启动流程](#4-运行模式与启动流程)
5. [主要模块职责](#5-主要模块职责)
6. [关键类与函数说明](#6-关键类与函数说明)
7. [Web API 接口清单](#7-web-api-接口清单)
8. [前端模块说明](#8-前端模块说明)
9. [数据文件与状态模型](#9-数据文件与状态模型)
10. [依赖关系](#10-依赖关系)
11. [配置与环境变量](#11-配置与环境变量)
12. [关键设计要点](#12-关键设计要点)

---

## 1. 项目概览

| 项目 | 说明 |
|------|------|
| 名称 | Task Verge（专注控制台） |
| 类型 | Windows 桌面专注力管控工具 |
| 形态 | 单文件 Python 脚本（`.pyw`）+ 内置 Web 前端 + 系统托盘 |
| 语言 | Python 3（后端） / 原生 HTML+CSS+JS（前端） |
| 三方依赖 | 无（纯标准库实现） |
| AI 能力 | DeepSeek Chat（任务生成、AI 验收评估、应用识别、应用分类、教练对话、洞察建议） |
| 适用平台 | Windows（部分功能依赖 PowerShell / ctypes / Win32 API / Docker Desktop） |

**核心能力：**

- 按目标（goal）生成每日结构化任务计划，计划可锁定，修改需填写原因
- AI 验收：上传交付物后 AI 读取文件内容，执行 `py_compile` 静态检查和 Docker 沙箱运行，按验收标准判定通过/不通过
- 前台窗口标题每 2 秒采样，统计各应用占用时间
- AI 自动识别当前任务所需应用，构建可视化"工作桌面"
- 应用分类目录（AI 维护 + 用户可调整）
- AI 教练对话：根据当前状态给出调整建议，用户确认后自动执行
- 时间块规划：按任务预计时长自动生成今日时间块（含休息），支持 AI 重排
- 洞察卡：自动检测完成率低、前台时间集中、缺交付物等异常
- 工作时段、休息（每日上限 3 次）、退出拦截（未完成任务需填写原因）
- 每日归档、事件流、历史趋势图表
- 系统托盘图标、开机自启、单实例互斥（Mutex + PID 双重检测）
- 崩溃恢复：启动时检测上次是否异常退出并提示用户

---

## 2. 整体架构

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           task-panel.pyw (~1737 行)                       │
│                                                                          │
│  ┌────────────┐   ┌──────────────┐   ┌────────────────────────┐          │
│  │  CLI 入口  │   │  Web 模式入口 │   │  Tkinter 模式入口      │          │
│  │ --generate │   │  run_web()   │   │  --ci 测试服务         │          │
│  │ --evaluate │   │              │   │                        │          │
│  │ --stats    │   └──────┬───────┘   └────────────────────────┘          │
│  └────────────┘          │                                               │
│                          ▼                                               │
│  ┌───────────────────────────────────────────────────────────────────┐   │
│  │                      WebApp 运行时                                │   │
│  │  ┌───────────┐  ┌──────────────────────────────┐                  │   │
│  │  │ FG 前台循环│  │  AI 作业队列                   │                  │   │
│  │  │ (_fg_loop)│  │  任务生成 / 应用识别 / 分类    │                  │   │
│  │  │ + 教练推送 │  │  教练洞察推送 / 验收评估      │                  │   │
│  │  └───────────┘  └──────────────────────────────┘                  │   │
│  └───────────────────────────────────────────────────────────────────┘   │
│                          │                                               │
│                          ▼                                               │
│  ┌───────────────────────────────────────────────────────────────────┐   │
│  │              http.server.ThreadingHTTPServer                      │   │
│  │                    + Handler (路由)                               │   │
│  │                  + X-Session 会话锁                               │   │
│  └───────────────────────────────────────────────────────────────────┘   │
│                          │                                               │
│       ┌──────────────────┼──────────────────┬──────────────────┐        │
│       ▼                  ▼                  ▼                  ▼         │
│  ┌─────────┐      ┌────────────┐     ┌────────────┐     ┌─────────┐     │
│  │ JSON 状态│     │ /web 静态资源│     │ /icons 缓存│     │ uploads/ │     │
│  │ 文件读写 │      │ (HTML/CSS/JS)│     │  (PNG)     │     │ 交付物    │     │
│  └─────────┘      └────────────┘     └────────────┘     └─────────┘     │
│                          │                                               │
│                          ▼                                               │
│  ┌───────────────────────────────────────────────────────────────────┐   │
│  │           原生 WebView2 桌面窗口（浏览器仅作为故障回退）          │   │
│  │           + 系统托盘（ctypes Shell_NotifyIcon）                   │   │
│  │           + 前端会话锁（localStorage 心跳 + X-Session token）     │   │
│  └───────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
                          │
                          ▼ 外部服务
          ┌────────────────┴────────────────┐
          ▼                                 ▼
  ┌─────────────────┐              ┌─────────────────┐
  │ DeepSeek API    │              │ lianyue.fun     │
  │ (任务/验收/分类 │              │ /api/pc-stats   │
  │  教练/洞察)     │              └─────────────────┘
  └─────────────────┘
```

**架构特点：**

- **单文件后端**：所有后端逻辑集中在 `task-panel.pyw`（约 1737 行），无包结构
- **零三方依赖**：仅使用 Python 标准库（http.server、ctypes、subprocess、urllib、secrets 等）
- **本地 Web 服务**：HTTP 服务监听 `127.0.0.1` 随机端口，浏览器以 `--app` 模式打开
- **前后端分离**：后端提供 JSON API + Multipart 文件上传，前端为纯静态 SPA
- **进程即数据**：所有状态以 JSON 文件持久化在程序目录，原子写入
- **双重单实例**：Windows Mutex + PID 文件双重检测，防止多实例

---

## 3. 目录结构

```
d:\work_S\scripts\
├── task-panel.pyw         # 主程序（后端 + CLI + Tkinter 备用 UI），~1737 行
├── task-panel.url         # 上次运行的 Web 服务 URL 缓存
├── task-panel.pid         # 当前运行实例的进程 ID（单实例检测）
├── task-config.json       # 主配置/状态文件（核心数据）
├── history.json           # 评估历史记录
├── fgtime.json            # 前台窗口时间统计
├── boot.log               # 启动诊断日志（pid、exe、frozen、各阶段标记）
├── watchdog.log           # 启停/错误/JSON 失败日志（文件名沿用）
├── crash.log              # 崩溃恢复标记（running / clean exit / uncaught error）
├── .env                   # DeepSeek API Key 与 PCSTATS_TOKEN（可选，可由 UI 写入）
├── CODE_WIKI.md           # 本文档
├── README.md              # 项目简介
├── USER_REVIEW.md         # 用户视角评审报告（2026-07-05 评审快照，部分问题已修复）
├── web/                   # Web 前端静态资源
│   ├── index.html         # SPA 入口（5 个页面：总览/任务/应用分类/复盘/设置）
│   ├── app.css            # 暗色主题样式
│   └── app.js             # 前端逻辑（状态渲染、API 调用、会话锁、文件上传）
├── uploads/               # 用户上传的交付物文件（按 goal_id/task_id 分目录，按需创建）
├── icon-cache/            # 应用图标 PNG 缓存（SHA1 命名）
├── _e2e_shots/            # E2E 截图目录（测试产物）
├── dist/                  # 构建产物目录
└── dogfood-output/        # 内测/E2E 测试脚本与报告输出目录
```

---

## 4. 运行模式与启动流程

### 4.1 启动入口

主程序通过命令行参数区分 5 种运行模式：

| 命令 | 模式 | 说明 |
|------|------|------|
| `python task-panel.pyw` | Web 模式（默认） | 启动 HTTP 服务 + 系统托盘 + 打开浏览器 |
| `python task-panel.pyw --generate` | CLI 生成 | 调用 DeepSeek 生成今日任务并写入配置 |
| `python task-panel.pyw --evaluate` | CLI 评估 | 调用 DeepSeek 验收完成度（含文件读取 + py_compile + Docker），写入 history.json |
| `python task-panel.pyw --stats` | CLI 上报 | 采集 CPU/内存/GPU/磁盘/温度并上报到 pc-stats |


### 4.2 Web 模式启动流程

```
main()
  ├─ single_instance_guard()
  │    ├─ 读取 task-panel.pid，调用 pid_alive() 检查旧进程是否存活
  │    ├─ 若存活：尝试 focus_window("Task Verge")，失败则读取 .url 打开浏览器后退出
  │    ├─ 否则：写入当前 PID 到 task-panel.pid
  │    └─ 注册 atexit 清理 PID 文件
  ├─ CreateMutexW 创建 Windows 互斥锁 Local\TaskPanel_D_work_S_scripts
  │    └─ 若已存在：同上的聚焦/打开逻辑，退出
  ├─ 注册 excepthook（crash_record + 写入 boot.log）
  ├─ run_web()
  │    ├─ crash_mark_running() + atexit.register(crash_mark_clean)
  │    ├─ WebApp() 初始化
  │    │    ├─ 启动前台窗口采样循环（每 2s / +2s 时间统计）
  │    │    ├─ 每 60s 触发 push_coach_alerts() 推送洞察
  │    │    └─ 启动 AI 应用分类后台作业（start_catalog_job）
  │    ├─ ThreadingHTTPServer 监听 127.0.0.1:随机端口
  │    ├─ 将 URL 写入 task-panel.url
  │    ├─ 启动服务线程 + 托盘线程（web_tray）
  │    ├─ run_native_window(url)：打开 WebView2 原生窗口（1160×760）
  │    └─ 主循环 sleep（等待 Ctrl+C → crash_mark_clean → shutdown）
```

### 4.3 单实例机制（双重检测）

**第一层 — PID 文件**（`task-panel.pid`）：
- `single_instance_guard()` 读取上次 PID，通过 `pid_alive()`（OpenProcess + CloseHandle）判断进程是否存活
- 存活则聚焦已有窗口或打开浏览器，然后 `sys.exit(0)`
- 未存活则覆盖写入新 PID，`atexit` 注册清理

**第二层 — Windows Mutex**（`Local\TaskPanel_D_work_S_scripts`）：
- `CreateMutexW` + `GetLastError() == 183`（ERROR_ALREADY_EXISTS）判断
- 仅在第一层检查之后执行，作为兜底

### 4.4 崩溃恢复流程

```
启动时 crash_mark_running()
  ├─ 内部先调用 crash_read_last() 读取上次状态
  ├─ 若上次 reason == "running" → _LAST_CRASH 置为上次记录（说明上次没正常退出）
  │    └─ WebApp.state() 中 last_crash 字段传给前端，显示崩溃提示
  │    └─ 用户可点击"忽略"调用 /api/dismiss-crash 清除（_LAST_CRASH = None + crash_mark_clean）
  └─ 无论上次状态如何，都覆盖写入 {"reason":"running"}
正常退出 → crash_mark_clean() 写入 {"reason":"clean exit"}（由 atexit 触发）
未捕获异常 → excepthook（_install_excepthook 注册）→ crash_record("uncaught: " + traceback)
```

---

## 5. 主要模块职责

`task-panel.pyw` 内部按职责可分为以下逻辑模块（物理上同为单文件）：

| 模块 | 职责 | 关键符号 |
|------|------|----------|
| **基础设施** | 路径、日志、子进程封装、JSON 原子读写 | `_run`, `_bl`, `APP_DIR`, `P`, `jl`, `js` |
| **配置/状态层** | 加载、保存、归一化配置与目标状态，任务数据模型归一化 | `CFG0`, `lc`, `sc`, `norm_goals`, `ensure_goal_state`, `save_goal_state`, `normalize_task`, `normalize_tasks` |
| **历史/前台数据** | 评估历史、前台时间读写 | `lh`, `ah`, `lf`, `sf` |
| **环境/密钥** | 从 `.env` 读取 DEEPSEEK / PCSTATS_TOKEN，保存/管理 Key | `ev`, `dk`, `pt`, `save_deepseek_key` |
| **JSON 解析** | 容错地从 AI 输出提取 JSON，通用 DeepSeek API 调用（带重试） | `ej`, `deepseek_json` |
| **任务/目标工具** | 任务文本归一化、合并应用列表、验收结果归一化、任务校验 | `task_text`, `value_text`, `task_items`, `merged_task_apps`, `norm_acceptance_result`, `task_payload`, `validate_ai_tasks`, `task_off_goal`, `goal_history`, `gen_settings` |
| **时段/休息/洞察** | 工作时段、休息判定、退出拦截、时间块生成、洞察卡 | `in_work_window`, `break_active`, `unfinished`, `ensure_time_blocks`, `insights_for`, `push_coach_alerts` |
| **教练对话** | AI 教练消息处理、action 执行、本地规则兜底 | `fallback_chat_action` |
| **AI 任务生成** | 调用 DeepSeek 生成/修正任务，含本地兜底 | `gen_tasks`, `fallback_tasks`, `fallback_task_templates`, `build_task_prompt`, `ai_json`, `cli_gen` |
| **AI 任务验收** | 读取交付物内容、py_compile 检查、Docker 沙箱运行、调用 DeepSeek 判定 | `cli_eval`, `evidence_details`, `compact_evidence_basis`, `docker_python_check`, `sync_pct` |
| **AI 应用识别** | 两阶段（分类→选应用）识别任务所需应用 | `infer_task_apps`, `ensure_app_catalog`, `apps_for_labels`, `catalog_labels`, `remember_task_apps`, `normalize_catalog` |
| **应用枚举** | 枚举运行中/已安装应用、图标提取、可用应用过滤 | `applications`, `installed_applications`, `icon_for`, `processes`, `usable_apps`, `find_app` |
| **系统监控** | PC 状态采集与上报 | `cli_stats` |
| **前台采样** | 获取前台窗口标题 | `fg_title` |
| **Web 服务** | HTTP 路由、会话锁（X-Session）、文件上传、业务处理 | `class WebApp`, `class Handler`, `claim_session`, `heartbeat_session`, `check_session` |
| **崩溃恢复** | 崩溃标记读写、异常钩子 | `crash_read_last`, `crash_mark_running`, `crash_mark_clean`, `crash_record`, `crash_last`, `_install_excepthook` |
| **托盘/窗口控制** | 系统托盘、窗口聚焦、浏览器打开 | `web_tray`, `focus_window`, `open_desktop` |
| **自启/设置** | 开机自启、控制台 Python 定位 | `set_autostart`, `console_python` |
| **单实例守卫** | PID 文件 + Mutex 双重单实例检测 | `single_instance_guard`, `pid_alive` |
| **Tkinter UI** | 备用桌面面板 | `class App`, `ico` |
| **CLI 入口** | 命令行分发 | `__main__` 块 |

---

## 6. 关键类与函数说明

### 6.1 全局常量与基础设施

#### `_CNW` / `_run(cmd, **kw)`
- Windows 下使用 `CREATE_NO_WINDOW`（0x08000000）标志启动子进程，避免弹出控制台窗口
- 所有 PowerShell / tasklist / docker 调用均经由 `_run`

#### `APP_DIR` / `P`
- `APP_DIR`：程序所在目录（兼容 PyInstaller frozen 模式）
- `P`：所有数据文件路径的字典，含 `cfg`/`hist`/`fg`/`log`/`url`/`pid`/`icons`/`uploads`/`ico`/`as`/`crash`

#### `CFG0`
默认配置 schema，包含目标、任务、应用、计划锁定、日程、休息、事件、归档、应用目录、教练上下文、教练消息、任务生成参数、时间块、最近验收等全部字段。`lc()` 加载时会用 `setdefault` 补齐缺失字段。

#### `jl(p, d=None)` / `js(p, data)`
- `jl`：JSON 读取，失败时记录到 watchdog.log 并返回默认值
- `js`：JSON 原子写入（先写临时文件再 `os.replace`，Windows 下失败回退到 rename）

#### `lc()` / `sc(c)` / `lh()` / `ah(r)` / `lf()` / `sf(d)`
配置/历史/前台时间的 load/save 快捷封装。——`lc` 和 `sc` 受 `_CFG_LOCK` 保护（`threading.RLock`）。

#### `compact_state(c)` / `cleanup_uploads(c)`
- `compact_state`：限制 events/quit_attempts/breaks/archives 数组容量
- `cleanup_uploads`：扫描 `uploads/` 目录，删除不在任务 evidence 中的文件

#### `ev(n)` / `dk()` / `pt()` / `save_deepseek_key(key)`
- `ev`：依次从 `~/.hermes/.env`、`~/AppData/Local/hermes/.env`、`APP_DIR/.env` 读取环境变量
- `dk`：返回 `DEEPSEEK` 密钥
- `pt`：返回 `PCSTATS_TOKEN`，默认 `pcstats2026`
- `save_deepseek_key`：将 DeepSeek Key 直接写入 `APP_DIR/.env`，支持覆盖和清空

#### `ej(t)`
容错 JSON 解析：依次尝试原文、去除 markdown 代码围栏、正则提取 `{...}`，全部失败抛 `ValueError`。用于解析 AI 返回内容。

#### `AIError` / `deepseek_json(messages, max_tokens, temperature, timeout, retries)`
- `AIError`：携带 `kind` 分类的异常（`missing_key`/`auth`/`rate_limit`/`network`/`bad_response`）
- `deepseek_json`：通用 DeepSeek API 调用封装，POST 到 `https://api.deepseek.com/v1/chat/completions`，自动重试（默认 1 次），返回 `ej()` 解析后的 dict

#### `ai_json(system, prompt, max_tokens)`
`deepseek_json` 的便捷封装：固定 `temperature=0.1`，`timeout=35`，`retries=1`，返回 dict（失败返回 `{}`）。

### 6.2 任务数据模型

#### `task_text(t)` / `value_text(v)` / `as_list(v)`
- `task_text`：从 dict/string/None 提取任务文本，过滤无意义值（"无"/"暂无"/"n/a" 等）
- `value_text`：同 task_text，但对 dict/list 返回空字符串
- `as_list`：将值转为任务文本列表

#### `normalize_task(t, goal_id, idx, done)`
**核心数据模型函数**。将任意任务输入归一化为标准结构：
```jsonc
{
  "id": "task_...",          // 唯一 ID
  "goal_id": "0",            // 所属目标
  "title": "任务标题",       // 显示标题
  "text": "任务标题",        // 同 title
  "description": "",         // 描述
  "type": "practice",        // learn|practice|review|build|write|research
  "status": "pending",       // pending|doing|done|skipped
  "estimated_minutes": 30,   // 预计时长（5-180）
  "required_apps": [],       // 必用应用
  "allowed_apps": [],        // 允许的应用
  "blocked_apps": [],        // 禁用应用
  "expected_output": "",     // 预期交付物
  "acceptance": "",          // 验收标准
  "evidence": "",            // 证据/文件路径
  "acceptance_result": {},   // AI 验收结果
  "difficulty": 2,           // 难度 1-5
  "source": "manual",        // manual|legacy|ai_generated|fallback|fallback_topup
  "locked": false,           // 是否锁定
  "created_at": "..."        // 创建时间
}
```

#### `normalize_tasks(tasks, goal_id, flags)`
批量归一化任务，过滤空任务，对齐 done_flags。

#### `task_items(tasks, flags)`
将任务和 flags 转为前端展示格式（补 done 和 text 字段）。

#### `validate_ai_tasks(goal, tasks, settings)`
AI 生成后校验：过滤偏离目标的任务（调用 `task_off_goal`），补全 missing expected_output/acceptance，限制数量。

#### `task_off_goal(goal, task)`
硬编码关键词匹配，检测任务是否偏离当前目标（例如"四级"任务出现在"python"目标下）。

#### `task_payload(tasks, flags)`
将任务列表转为 AI 调用所需的紧凑 JSON 载荷。

### 6.3 目标与状态管理

#### `norm_goals(c)`
归一化目标列表：合并旧 `goal` 字段与 `goals` 数组，校正 `active_goal` 索引合法性。

#### `gid(c)`
返回当前激活目标的字符串索引（`str(active_goal)`）。

#### `ensure_goal_state(c)`
**核心函数**。按当前 goal 将 `tasks_by_goal[g]`、`flags_by_goal[g]`、`apps_by_goal[g]` 等映射回顶层 `tasks`/`done_flags`/`task_apps`，实现"多目标状态隔离"。首次访问时从旧字段迁移。同时处理 `pct_by_goal` 的映射。

#### `save_goal_state(c)`
反向操作：将顶层字段写回 `*_by_goal[g]`，同步 status 与 done_flags 的互推。

#### `evlog(c, kind, msg, extra)`
追加事件到 `c["events"]`，保留最近 300 条。

#### `unfinished(c)`
是否存在未完成任务（用于退出拦截）。

#### `in_work_window(c)` / `break_active(c)`
- 工作时段判定（支持跨午夜）
- 休息判定（按当日 `until` 时间戳）

### 6.4 AI 任务生成与评估

#### `gen_settings(c)`
合并并校验任务生成参数：`available_minutes`（30-600）、`task_count`（1-8）、`max_task_minutes`（10-180）、`prefer_continuation`、`force_measurable_output`。

#### `build_task_prompt(c)`
构建 AI 生成任务的完整 prompt，包含目标、未完成任务、历史复盘、规则和 return_schema（含 `goal_analysis`、`progress_diagnosis`、`daily_strategy`）。

#### `gen_tasks()`
调用 DeepSeek 生成结构化的多任务计划：
1. 读取目标与未完成任务、历史复盘作为上下文
2. `deepseek_json` → 返回 `{goal_analysis, progress_diagnosis, daily_strategy, tasks:[...]}`
3. `validate_ai_tasks` 过滤偏离目标的任务
4. 若不足 `task_count` → 二次修正（`repair_prompt`）
5. 仍不足 → 用 `fallback_task_templates` 补位（source `"fallback_topup"`）
6. 写入配置、锁定计划（`plan_locked=True`）、记录事件、保存 `task_generation`
7. 返回后由外层触发 `start_infer_apps()` 识别应用

#### `fallback_tasks(c, why)`
无 DeepSeek Key 或生成失败时的本地兜底，使用 `fallback_task_templates` 生成通用任务。

#### `fallback_task_templates(goal, settings)`
本地兜底的任务模板：明确最小成果、专注执行、复盘阻塞点。

#### `cli_eval()`
AI 验收评估：
1. 若所有任务都无 evidence → 直接判定全部不通过
2. 调用 `evidence_details` 解析 evidence 文本中的文件路径（最多 5 个），读取内容（最多 12000 字符/文件）
3. 对 `.py` 文件执行 `py_compile` 静态检查和 `docker_python_check`（Docker 沙箱运行）
4. 搜集前台时间 top 12
5. `deepseek_json` → 返回 `{completion_pct, done:[bool], results:[{pass,reason,missing,next_steps,evidence_refs}]}`
6. 本地二次校验：no_evidence 和交付物校验失败的任务强制设为不通过
7. `sync_pct` → `norm_acceptance_result` → 写入 `history.json`

#### `evidence_details(evidence)` / `compact_evidence_basis(details)` / `docker_python_check(fp)`
- `evidence_details`：用正则从 evidence 文本提取文件路径（双引号/单引号/绝对路径/相对路径），取前 5 个，读取内容（12000 字符上限），对 `.py` 执行 `py_compile` + Docker 检查
- `compact_evidence_basis`：将 evidence_details 的返回结构压成紧凑形式供 AI 使用
- `docker_python_check`：用 `docker run --read-only` 在 `python:3.11-alpine` 中执行目标脚本并返回 stdout/stderr（上限 4000 字符）

#### `norm_acceptance_result(x, passed, reason)`
归一化 AI 验收结果为标准结构：`{pass, reason, missing, next_steps, evidence_refs, basis}`。

#### `sync_pct(c)`
从 tasks 和 done_flags 同步 `completion_pct`（0-100）。

### 6.5 AI 应用识别与分类

#### `ensure_app_catalog(c, apps=None)`
维护应用分类目录：
- 计算应用列表签名（SHA1）
- 签名未变则复用缓存；用户手动维护（`sig=="manual"`）则只补"未分类"
- 否则调用 AI 将应用归入大类/小类（"学习办公/文档写作"等），结果存入 `app_catalog`

#### `infer_task_apps(c)`
**两阶段应用识别**：
1. **选分类**：AI 从目录中选择与任务相关的 1-4 个大类/小类（上限 6）
2. **选应用**：在候选应用中由 AI 精选直接相关的应用（上限 20）
- 使用 `task_app_memory` 记忆历史选择，键为排序后的分类组合

#### `remember_task_apps(c)`
将当前合并应用列表写入 `task_app_memory`，供下次识别复用。

#### `request_task_app(c, action, app_name)`
用户申请增加/移除应用：
- `remove`：直接从 manual/ai 列表移除
- `add`：先在应用列表中查找，再由 AI 判断是否"确实对任务有用"，通过则加入 manual 列表

#### `normalize_catalog(catalog)` / `add_uncategorized(catalog, apps)`
- `normalize_catalog`：清理用户编辑的分类，去重，保留用户定义的结构
- `add_uncategorized`：将未归入任何分类的应用放入"未分类/待整理"

#### `catalog_labels(catalog)` / `apps_for_labels(catalog, labels)`
- `catalog_labels`：提取分类路径列表（"大类/小类"）
- `apps_for_labels`：按分类标签获取对应应用列表

### 6.6 时间块与洞察

#### `ensure_time_blocks(c, force=False)`
根据当前任务和日程生成时间块：
- 按 `schedule.start~end` 的时间窗口
- 对每个未完成的任务分配时长（取 `estimated_minutes` 与 `max_task_minutes` 的较小值）
- 每累计 90 分钟自动插入 15 分钟休息
- `force=True` 时强制重新生成

#### `insights_for(c)`
生成当前状态的洞察卡：
- 完成率 < 40%：`low_completion` 警告
- 前台时间集中（任一应用 ≥45 分钟）：`focus_drift` 警告
- 有未完成且无交付物的任务：`missing_evidence` 提示
- 今天有执行数据但未归档：`daily_review` 提示
- 已忽略的洞察不再重复出现

#### `push_coach_alerts(c)`
每 60 秒由 `_fg_loop` 触发：从洞察中取第一个非 good 级别、今天未推送过的，写入 `coach_messages`。

### 6.7 教练对话

#### `fallback_chat_action(msg, c)`
本地规则兜底（无 DeepSeek Key 或调用失败时使用），按关键词命中返回对应 action：
- `/review` / `复盘` / `归档` → `archive_today`
- `/plan` / `重新计划` / `时间块` → `plan`
- `下午` / `14` → `reschedule_first_pending`（start="14:00"）
- `拆` / `卡` → `regenerate_tasks`
- 无匹配 → `action: null`，返回通用引导话术

### 6.8 系统监控

#### `fg_title()`
通过 `user32.GetForegroundWindow` + `GetWindowTextW` 获取前台窗口标题，再用 `tasklist` 反查进程名，返回 `exe: title` 格式（截断 80 字符）。

#### `applications()`
合并"运行中有窗口的进程"+"开始菜单已安装应用"，为每个应用调用 `icon_for` 提取图标，按"运行中优先 + 名称排序"。包含 `usable_apps` 过滤（排除 taskmgr/explorer/python 等系统应用）。

#### `installed_applications()`
遍历 Start Menu 的 `.lnk` 快捷方式，解析 `TargetPath` 得到已安装应用列表。

#### `icon_for(path)`
用 SHA1 命名缓存图标，通过 PowerShell `System.Drawing.Icon.ExtractAssociatedIcon` 提取 PNG。

#### `cli_stats()`
采集系统状态（内存、CPU、GPU、磁盘、温度）并 POST 到 `https://www.lianyue.fun/api/pc-stats`。

### 6.9 Web 服务与会话锁

#### `class WebApp`
Web 模式运行时，持有前台采样循环（`_fg_loop`：每 2s 采样 + 累加时间 + 每 60s 推送洞察）、`state()` 方法返回前端所需的完整状态快照。

#### `class Handler(http.server.BaseHTTPRequestHandler)`
HTTP 路由处理器：
- `do_GET`：`/api/state`、`/api/insights`、`/api/generate-status`、`/api/claim`、`/api/processes`、`/icons/*`、静态文件
- `do_POST`：所有业务接口（见第 7 节）
- 静默 `log_message`，JSON 统一通过 `send_json` 返回
- 写操作（除 `/api/quit`/`/api/deepseek-key`/`/api/upload-evidence`/`/api/event`）均需 `X-Session` token 校验，不通过返回 409

#### `claim_session()` / `heartbeat_session(tok)` / `check_session(tok)`
后端单实例会话锁：
- `claim_session`：若无活跃会话或已超时（TTL 8 秒），生成新 token（`secrets.token_hex(8)`）
- `heartbeat_session`：续期时间戳
- `check_session`：校验 token；无会话时允许（兼容旧前端）；超时自动释放

#### `open_desktop(url)`
优先使用 pywebview/WebView2 原生窗口（1160×760），浏览器只用于原生窗口不可用时的故障回退。

#### `focus_window(title)`
通过 `EnumWindows` 查找标题包含 `title` 的窗口并置前。

#### `web_tray(url, server)`
用 ctypes 创建系统托盘图标（`Shell_NotifyIconW`），处理左键双击（打开）、右键菜单（打开/退出）。退出时若任务未完成会拦截、记录 `quit_blocked` 事件并拉起面板（`open_desktop`），否则移除托盘图标、shutdown server、`os._exit(0)`。

### 6.10 崩溃恢复

#### `crash_read_last()` / `crash_mark_running()` / `crash_mark_clean()` / `crash_record(reason)` / `crash_last()`
- `crash.log` 文件记录当前会话状态
- 启动时 `crash_read_last` → 若上次为 `"running"` 则 `_LAST_CRASH` 置为非 None
- `run_web()` 开头 `crash_mark_running()` → `atexit.register(crash_mark_clean)`
- 未捕获异常 → `_install_excepthook` → `crash_record("uncaught: ...")`
- `crash_last()` 返回上次崩溃信息，`WebApp.state()` 通过 `last_crash` 字段传给前端

### 6.11 单实例守卫

#### `single_instance_guard()` / `pid_alive(pid)`
- 读取 `task-panel.pid` 中的 PID，通过 `OpenProcess` 检查存活
- 存活则聚焦或打开浏览器后退出
- 否则写入新 PID + 注册 `atexit` 清理

#### `ico()`
程序化生成 32×32 的 `.ico` 文件（T 形图标），写入临时目录，退出时清理。

---

## 7. Web API 接口清单

### 7.1 GET 接口

| 路径 | 说明 |
|------|------|
| `/` | 返回 `web/index.html` |
| `/index.html`、`/app.css`、`/app.js` | 静态资源（从 `WEB_DIR` 提供，带 `Cache-Control: no-store`） |
| `/api/state` | 完整状态快照（目标、任务、应用、历史、事件、教练、洞察、崩溃信息等） |
| `/api/insights` | 当前洞察卡（相当于 `insights_for(c)` 的结果） |
| `/api/generate-status` | AI 任务生成的实时进度（`GEN_STATUS`） |
| `/api/claim` | 申请后端会话 token（X-Session），已有活跃会话时返回 409 |
| `/api/processes` | 运行中应用列表 + 可用应用（含图标） |
| `/icons/<sha1>.png` | 图标缓存 |
| `/favicon.ico` | 返回 204 |

### 7.2 POST 接口

| 路径 | 入参 | 说明 | 锁定/限制 |
|------|------|------|-----------|
| `/api/toggle` | `{idx}` | **已禁用** — 直接返回 400，提示"任务验收由 AI 负责" | — |
| `/api/task` | `{idx,text,reason}` | 编辑单条任务标题 | 计划锁定需 reason |
| `/api/task-evidence` | `{idx,evidence}` | 保存任务的交付物文字（用于 AI 验收前先保存描述） | — |
| `/api/upload-evidence` | Multipart `{idx,file}` | 上传交付物文件到 `uploads/<goal_id>/<task_id>/` | 无需 X-Session |
| `/api/tasks` | `{tasks,reason}` | 批量保存任务 | 计划锁定需 reason |
| `/api/lock-plan` | `{locked,reason}` | 锁定/解锁计划 | — |
| `/api/break` | `{reason,minutes}` | 开始休息 | 每日上限 3 次，1-60 分钟 |
| `/api/quit` | `{reason}` | 申请退出（后台延迟 1.5s 后移除托盘图标、`os._exit(0)`） | 未完成需 reason |
| `/api/archive` | `{}` | 归档今日数据（任务、完成度、前台时间 top 10） | — |
| `/api/settings` | `{goals,goal,active_goal,autostart,task_gen}` | 保存目标、自启、生成参数（`available_minutes`/`task_count`/`max_task_minutes`/`prefer_continuation`/`force_measurable_output`） | — |
| `/api/active-goal` | `{active_goal}` | 切换激活目标（自动 save_goal_state → ensure_goal_state） | — |
| `/api/deepseek-key` | `{key}` | 保存/清空 DeepSeek API Key（写入 `.env`） | 无需 X-Session |
| `/api/catalog` | `{catalog}` | 保存用户调整的应用分类 | 标记为 `manual`，经 `normalize_catalog` 去重 |
| `/api/catalog-regenerate` | `{}` | 清空分类签名并触发 AI 重新分类 | — |
| `/api/request-app` | `{action,app}` | 申请增加/移除工作桌面应用 | 增加需 AI 批准（无 Key 则拒绝） |
| `/api/open-app` | `{exe}` | 启动应用（通过 `subprocess.Popen`） | — |
| `/api/generate` | `{}` | 启动 AI 任务生成后台作业（gen_tasks + start_infer_apps） | 已在运行则拒绝 |
| `/api/evaluate` | `{}` | **直接调用 `cli_eval()`** 进行 AI 验收（同进程内执行） | — |
| `/api/plan` | `{}` | 强制重新生成时间块 | — |
| `/api/chat` | `{message}` | AI 教练对话：根据状态返回 `{reply, action}` | 以 `/` 开头走本地规则兜底 |
| `/api/coach-action` | `{action}` | 执行教练建议的 action（plan/reschedule_first_pending/regenerate_tasks/archive_today） | — |
| `/api/event` | `{kind,message,extra}` | 前端事件流日志写入 | 无需 X-Session |
| `/api/clear-fg` | `{}` | 清除所有前台时间数据 | — |
| `/api/dismiss-crash` | `{}` | 消除崩溃通知（`crash_mark_clean` + `_LAST_CRASH = None`） | — |
| `/api/heartbeat` | `{}` | 会话心跳续期（续 `_SESSION["ts"]`） | — |

---

## 8. 前端模块说明

前端为纯静态 SPA，无构建步骤。

### 8.1 `web/index.html`
5 个页面，左侧导航切换（导航文字与 `pageTitles` 一致）：
- **总览（dashboard）**：环形进度、目标切换、快捷休息组件、AI 目标理解卡片、工作桌面、任务列表、前台时间、历史趋势图、时间块、AI 教练对话区、洞察卡
- **任务（tasks）**：任务工作台（逐条编辑 + 批量编辑 + 计划锁定）
- **应用分类（rules）**：AI 应用分类编辑器（可视化卡片，含搜索/添加/移除应用，按钮"保存分类 / 自动分类"）
- **复盘（review）**：退出记录、事件流（含"归档今日"按钮）、每日归档
- **设置（settings）**：目标列表、生成参数（可用时间/任务数/单任务上限/续接/强制交付物）、休息（5/10/20/30/45 分钟）、申请退出、自启、DeepSeek Key、崩溃通知、隐私说明（含"清除前台时间数据"按钮）

> 注：导航按钮显示文字为"应用"（`title="应用分类"`），`pageTitles` 中标题为"应用分类"，URL hash 与 `id` 仍为 `rules`（历史命名）。

### 8.2 `web/app.js`

#### 会话与网络
| 函数 | 职责 |
|------|------|
| `claimFrontend()` | 通过 `localStorage` 抢占前端身份，2 秒心跳，防止多窗口冲突 |
| `claimBackendSession()` / `ensureSession()` | 申请后端 X-Session token；丢失时自动重试 3 次 |
| `heartbeat()` | 每 4 秒向 `/api/heartbeat` 发心跳续期 |
| `api(path, body)` | 统一 JSON fetch 封装（自动处理 409 冲突弹窗） |
| `uploadApi(path, formData)` | Multipart 上传 fetch 封装（409 时自动重试一次 claim） |
| `logEvent(kind, message, extra)` | 前端事件日志上报到 `/api/event` |

#### 渲染
| 函数 | 职责 |
|------|------|
| `render()` | 全量渲染状态到 DOM |
| `renderOnboarding()` | 新用户引导：无目标 → 去设置页；有目标无任务 → 点生成任务 |
| `renderBreakWidget()` | 休息状态组件（剩余分钟、今日 X/3 次） |
| `ensureCoachWorkspace()` | 懒插入 AI 教练工作区容器到 DOM（dashboard 内动态注入） |
| `renderCoachWorkspace()` / `renderTimeBlocks()` / `renderInsights()` / `renderCoachMessages()` | AI 教练区：时间块、洞察卡、对话历史 |
| `renderCoachAction(action, reply)` | 教练建议的确认/取消操作预览 |
| `renderGoalUnderstanding()` | AI 目标理解卡片（intent、成功标准、避免项、今日策略） |
| `renderCrashNotice()` | 崩溃恢复提示（时间、原因、忽略按钮） |
| `renderReview()` / `renderTaskEditor()` / `renderCatalog()` / `renderDesktop()` | 各子模块渲染 |
| `renderCatalogPicker(row, q)` / `renderAppPicker(box, q)` | 应用选择器浮层（带搜索） |
| `catalogFromEditor()` | 从 DOM 收集分类编辑结果 |
| `editorTasks()` | 从逐条编辑输入框收集任务文本 |
| `drawHistory()` | Canvas 绘制历史趋势折线（≥2 天时显示，<2 天显示提示文字） |
| `run(name)` | 触发 AI 生成/评估，轮询 `generate-status` 显示进度（最多 80 次 × 500ms）；`generate` 完成后若 message 含 `fallback` 弹模态提示 |
| `load()` / `refreshLive()` | 加载状态 / 总览页 2 秒自动刷新 |
| `loadProcesses()` | 加载可用应用列表 |
| `updateClock()` | 左上角实时时钟 |
| `eventName(k)` | 事件类型中文映射 |
| `taskCard(t, i)` | 单条任务卡片（含 AI 验收 checkbox、交付物展示/上传按钮、验收结果） |
| `uploadEvidenceFile(idx, input)` | 交付物文件上传流程（已跳过有文件选中时的任务列表重建） |

#### UI 交互
| 函数 | 职责 |
|------|------|
| `showModal(title, msg, kind)` | 模态弹窗（error/warn 样式） |
| `askEvidence()` | 交付物路径/链接输入弹窗 |
| `confirmDlg(msg, title)` | 浏览器 confirm 封装 |
| `showExitScreen()` | 退出遮罩界面 |
| `toast(msg, good)` | 状态徽章 pulsating 提示 |
| `showPrivacyNotice()` | 首次使用时的隐私提示确认 |
| `escapeHtml(s)` | HTML 实体转义 |

### 8.3 `web/app.css`
暗色主题（`color-scheme:dark`），CSS 变量定义配色：
`--bg`/`--side`/`--panel`/`--panel2`/`--line`/`--text`/`--muted`/`--accent`/`--accent2`/`--good`/`--bad`/`--warn`。

布局以 Grid 为主（`.shell` 侧栏+主区、`.grid` 卡片网格、`.hero` 进度环+文案）。按钮分三级：`.primary`（渐变）、默认、`.danger`（红框）。

响应式断点（4 档）：
- `min-width:1600px`：侧栏加宽到 260px，grid 双列 1.4fr/1fr
- `max-width:1280px`：grid 双列等宽，hero 单列
- `max-width:1024px`：侧栏收窄到 180px，grid 单列
- `max-width:820px`：侧栏收窄到 74px（仅首字母），所有 grid 单列，coach-workspace 单列

另含 `@media (prefers-reduced-motion: reduce)` 减少动画偏好支持。

---

## 9. 数据文件与状态模型

### 9.1 `task-config.json`（核心状态）

```jsonc
{
  // === 目标 ===
  "goal": "学习python",              // 当前激活目标文本
  "goals": ["备考2027四级考试","学习python"],  // 目标列表
  "active_goal": 1,                 // 激活目标索引
  "blocklist": [],                  // 拦截应用列表（预留）

  // === 任务（当前目标） ===
  "tasks": [...],                   // 当前目标任务列表（normalize_task 结构）
  "done_flags": [false,false,false],// 任务完成标志
  "completion_pct": 0,              // 完成度 0-100
  "plan_locked": true,              // 计划锁定标志

  // === 多目标隔离 ===
  "tasks_by_goal": {"0":[...],"1":[...]},
  "flags_by_goal": {...},
  "pct_by_goal": {...},
  "apps_by_goal": {...},
  "manual_apps_by_goal": {...},
  "ai_apps_by_goal": {...},
  "app_cats_by_goal": {...},

  // === 工作桌面 ===
  "manual_task_apps": [],           // 手动选择的工作桌面应用
  "ai_task_apps": [...],            // AI 识别的应用
  "task_apps": [...],               // 合并后的工作桌面应用
  "task_app_categories": [...],     // AI 选择的分类
  "app_catalog": {"categories":[...]}, // AI 应用分类目录
  "app_catalog_sig": "manual",      // 目录签名（SHA1 或 "manual"）
  "task_app_memory": {...},         // 应用选择记忆（按分类组合键）

  // === 任务生成参数 ===
  "task_gen": {
    "available_minutes": 120,       // 今日可用时间
    "task_count": 3,                // 生成任务数
    "max_task_minutes": 45,         // 单任务上限
    "prefer_continuation": true,    // 优先续接
    "force_measurable_output": true // 强制交付物+验收标准
  },

  // === 最近一次任务生成结果 ===
  "task_generation": {
    "ts": "...",                     // 生成时间
    "goal_analysis": {"intent":"","success_criteria":[],"risks":[]},
    "progress_diagnosis": {"continue":[],"avoid":[]},
    "daily_strategy": ""
  },

  // === 最近一次 AI 验收结果 ===
  "last_acceptance": {
    "ts": "...",                     // 验收时间
    "model": "deepseek-chat",
    "foreground_time": {...},
    "evidence": [...],
    "raw_result": {...}
  },

  // === 日程与时间块 ===
  "schedule": {"enabled":false,"start":"09:00","end":"18:00"},
  "time_blocks": [...],             // 自动生成的时间块（task/break）

  // === AI 教练 ===
  "coach_context": {
    "adjustments_today": 0,         // 今日调整次数
    "ignored_insights": [],         // 已忽略的洞察 ID
    "pushed_insights": []           // 已推送的洞察 ID（含日期前缀）
  },
  "coach_messages": [...],          // 教练对话历史

  // === 记录 ===
  "breaks": [...],                  // 休息记录（保留 100 条）
  "events": [...],                  // 事件流（保留 300 条）
  "quit_attempts": [...],           // 退出尝试（保留 100 条）
  "archives": [...]                 // 每日归档（保留 400 条）
}
```

### 9.2 其他数据文件

| 文件 | 内容 |
|------|------|
| `history.json` | 评估历史数组，每项含 `date`/`goal`/`goal_id`/`tasks`/`completion_pct`/`summary`/`acceptance_results`/`basis`（保留 500 条） |
| `fgtime.json` | 前台时间统计，键为应用名（截断 40 字符），值为累计秒数（每 2s +2） |
| `task-panel.url` | 上次运行的 Web 服务 URL |
| `task-panel.pid` | 当前运行的进程信息 `{pid, ts, script}`（用于单实例检测） |
| `crash.log` | 崩溃恢复标记：`{"reason":"running"}` / `"clean exit"` / `"uncaught: <traceback>"` |
| `boot.log` | 启动诊断日志（pid、exe、frozen、各阶段标记） |
| `watchdog.log` | `START`/`STOP`/`JSON_FAIL` 记录，超过 5MB 时截断保留最近 86400 行 |
| `uploads/` | 用户上传的交付物文件（按 `uploads/<goal_id>/<task_id>/<filename>` 组织） |
| `icon-cache/*.png` | 应用图标缓存（SHA1 命名） |

---

## 10. 依赖关系

### 10.1 Python 标准库

```
copy, csv, hashlib, json, os, re, sys, time, queue, struct, socket,
random, atexit, subprocess, threading, urllib.request, tempfile,
traceback, ctypes, http.server, mimetypes, webbrowser, datetime,
tkinter, secrets
```

> 无任何 `pip` 依赖，可直接用系统 Python 运行。

### 10.2 外部服务

| 服务 | 用途 | 端点 |
|------|------|------|
| DeepSeek | 任务生成、进度评估、应用分类、应用识别、教练对话 | `https://api.deepseek.com/v1/chat/completions` |
| lianyue.fun | PC 状态上报（`--stats`） | `https://www.lianyue.fun/api/pc-stats` |

### 10.3 本地组件（可选）

| 组件 | 用途 |
|------|------|
| Docker Desktop | Python 交付物的 Docker 沙箱执行检查（`docker_python_check`，AI 验收时使用） |

### 10.4 Windows 系统组件

| 组件 | 用途 |
|------|------|
| `powershell.exe` | 系统信息查询、图标提取、已安装应用枚举、前台窗口标题（Tkinter 模式） |
| `tasklist.exe` | 进程枚举、PID→exe 反查 |
| `nvidia-smi` | GPU 温度/利用率/功耗（可选） |
| `ctypes` → `user32.dll` | 前台窗口、窗口枚举、托盘图标、消息循环 |
| `ctypes` → `shell32.dll` | `Shell_NotifyIconW` 托盘管理 |
| `ctypes` → `kernel32.dll` | 互斥锁、模块句柄、进程句柄（pid_alive） |
| WebView2 | 原生桌面窗口承载 Web UI |

### 10.5 模块间依赖

```
CLI 入口 ──► gen_tasks / cli_eval / cli_stats
                       │
                       ▼
                   deepseek_json ──► DeepSeek API
                   ai_json ──┘
                       │
                       ▼
    ensure_app_catalog / infer_task_apps
    ensure_time_blocks / insights_for
                       │
                       ▼
              applications / icon_for ──► PowerShell / tasklist

Web 模式 ──► WebApp
              ├─► _fg_loop ──► fg_title ──► user32
              │               └─► push_coach_alerts (每 60s)
              └─► Handler ──► 配置/历史/前台 读写
                              ├─► start_gen_job ──► gen_tasks + start_infer_apps
                              ├─► start_catalog_job ──► ensure_app_catalog
                              ├─► cli_eval ──► evidence_details + docker_python_check
                              ├─► request_task_app ──► ai_json
                              ├─► /api/chat ──► deepseek_json 或 fallback_chat_action
                              └─► claim_session / check_session ──► X-Session 校验
```

---

## 11. 配置与环境变量

### 11.1 环境变量（从 `.env` 读取）

按顺序查找以下文件：
1. `~/.hermes/.env`
2. `~/AppData/Local/hermes/.env`
3. `APP_DIR/.env`

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEEPSEEK` | DeepSeek API Key（启用 AI 功能） | 空（回退本地兜底 fallback_tasks） |
| `PCSTATS_TOKEN` | pc-stats 上报 Token | `pcstats2026` |

DeepSeek Key 也可通过前端设置页（`/api/deepseek-key`）直接写入 `APP_DIR/.env`。

### 11.2 开机自启

`set_autostart(True)` 会在 `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\task-panel.bat` 写入启动脚本：
- frozen 模式：直接运行 exe
- 脚本模式：`pythonw.exe "task-panel.pyw"`

### 11.3 工作时段

通过 `schedule` 配置记录工作时段（`in_work_window` 判定，支持跨午夜）：
- `enabled: false`：不启用时段限制（默认）
- `enabled: true`：仅在 `start`~`end` 时段内视作工作时间

> 注：前端设置页已移除工作时段编辑入口，但 `schedule` 字段仍存在于 `task-config.json` 与 `state()` 返回中，可由用户手动编辑配置文件或通过 `/api/settings` 写入。该字段当前仅影响 `in_work_window()` 判定，不触发任何拦截行为（守护进程已移除）。

### 11.4 任务生成参数

通过 `task_gen` 配置（前端设置页可编辑）：
- `available_minutes`：今日可用时间，30-600
- `task_count`：每次生成任务数量，1-8
- `max_task_minutes`：单任务上限，10-180
- `prefer_continuation`：优先续接上一条未完成任务
- `force_measurable_output`：每个任务强制包含 `expected_output` 和 `acceptance`

---

## 12. 关键设计要点

### 12.1 数据安全
- **原子写入**：所有 JSON 通过 `tempfile.mkstemp` + `os.replace` 写入，避免崩溃导致文件损坏
- **失败容错**：`jl` 读取失败时记录日志并返回默认值，不抛异常
- **字段自愈**：`lc()` 加载时用 `CFG0` 补齐缺失字段，兼容旧版本配置
- **上传清理**：`cleanup_uploads` 每次 `sc()` 时扫描 `uploads/` 目录，删除无人引用的文件

### 12.2 单实例与窗口管理
- **双重检测**：PID 文件（`pid_alive` + `OpenProcess`）+ Windows Mutex（`CreateMutexW`）
- 重复启动时自动聚焦已有窗口或重新打开浏览器
- **前端会话锁**：`localStorage` 心跳（2 秒）+ 后端 `X-Session` token（TTL 8 秒，409 冲突）双保险
- 后端会话锁超时自动释放，避免前端异常关闭后死锁

### 12.3 计划锁定机制
- `plan_locked=True` 时，编辑任务必须填写 `reason`
- 锁定由 AI 生成任务时自动启用，防止用户随意修改 AI 计划
- 可在任务页手动解锁（需填写解锁原因）
- 填写的 `reason` 写入事件日志供追溯

### 12.4 退出拦截
- 任务未完成时退出需填写原因，记录到 `quit_attempts`
- 托盘退出同样受此约束，被拦截时记录 `quit_blocked` 事件并**拉起面板**（`open_desktop`）
- Web 退出通过 `/api/quit` → 延迟 1.5s → 移除托盘图标 → `os._exit(0)`

### 12.5 多目标隔离
- 每个目标独立维护 `tasks`/`flags`/`apps`/`pct`/`categories`
- 切换目标时通过 `save_goal_state` + `ensure_goal_state` 完成上下文切换
- 应用选择记忆 `task_app_memory` 按分类组合键持久化

### 12.6 AI 调用策略
- **任务生成两阶段**：首次生成 → 不足 task_count 时二次修正（`repair_prompt`） → 仍不足用 `fallback_task_templates` 补位
- **AI 验收三重度校验**：
  1. 无 evidence 直接不通过
  2. 交付物文件不存在 / `py_compile` 失败 / `docker_python_check` 失败 → 本地强制不通过
  3. DeepSeek 审核剩余部分
- **两阶段应用识别**：先选分类（控制范围），再选具体应用（精确匹配），避免 AI 一次性返回过多无关应用
- **分类目录缓存**：通过应用列表 SHA1 签名判断是否需要重新分类；用户手动调整后标记为 `manual`，不再被 AI 覆盖（仅补未分类）
- **记忆复用**：`task_app_memory` 按分类组合记忆历史选择，提升后续识别速度与一致性
- **降级处理**：无 Key 或调用失败时回退到 `fallback_tasks`，教练对话回退到 `fallback_chat_action` 本地规则

### 12.7 崩溃恢复
- `crash.log` 文件在启动时写入 `"running"`，正常退出时覆盖为 `"clean exit"`（atexit），异常退出时由 excepthook 写入 traceback
- 下次启动时若上次为 `"running"`，前端显示崩溃提示（时间 + 建议检查数据完整性）
- 用户可点击"忽略"调用 `/api/dismiss-crash` 清除标记

### 12.8 数据保留策略

持久化上限（`compact_state` / `ah` 等写入时裁剪）：

| 字段/文件 | 持久化上限 | `state()` 返回上限 |
|-----------|-----------|--------------------|
| `events` | 300 条 | 80 条（`[-80:]`） |
| `breaks` | 100 条 | 20 条（`[-20:]`） |
| `quit_attempts` | 100 条 | 50 条（`[-50:]`） |
| `archives` | 400 条 | 30 条（`[-30:]`） |
| `coach_messages` | 无显式上限 | 20 条（`[-20:]`） |
| `history.json` | 500 条 | 10 条（`[-10:]`） |
| `fgtime.json` | 全量（按应用名键） | top 8（按值降序，排除 `"n/a"`） |
| `watchdog.log` | — | 超过 5MB 时截断保留最近 86400 行 |

> 注：`compact_state` 在每次 `sc()` 时对 events/breaks/quit_attempts/archives 做容量裁剪；`history.json` 由 `ah(r)` 写入时限制 500 条。`state()` 返回的是经过切片的子集，供前端展示。

### 12.9 兼容性
- 同时支持 PyInstaller frozen（exe）与脚本（.pyw）两种运行形态
- `_app_dir()` / `set_autostart` / `console_python` 等均针对两种形态做分支处理
- Tkinter 模式作为 Web 模式的备用，便于在浏览器不可用时使用
- `cgi.FieldStorage` 仍用于 Multipart 上传（Python 3.13 将移除，届时需替换）

---

> 本文档基于源码静态分析生成并持续更新，反映仓库当前状态。如代码发生变更，请同步更新本文档。
# Current runtime facts (verified 2026-07-12)

The authoritative runtime details are:

- `task-panel.pyw` is about 2328 lines; frontend assets live in `web/`.
- Normal desktop mode uses `http://127.0.0.1:64161/` by default. CI mode uses a random local port.
- User data is stored under `%LOCALAPPDATA%\TaskVerge`; `WEB_DIR` remains beside the entry script.
- Static assets load without an API session; API data and write endpoints require `X-Session` when strict auth is enabled.
- Safe default checks: `python -m pytest -q tests`; API/E2E checks require an isolated CI instance and `TASKVERGE_TEST_URL`.

Some earlier sections may describe the previous random-port and script-directory layout; use this block and `README.md` for current operations.
