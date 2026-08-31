# 大肥鱼陪伴接缝调研（历史基线，只读）

> 历史核对日期：2026-08-24。本文件记录陪伴持久化落地前的 v1 接缝调查，不代表当前实现。
> 当前行为以 `CONTEXT.md`、`CODE_WIKI.md`、`companion_service.py` 和 `tests/test_companion.py` 为准。
> 范围：现有 SQLite schema、motivation 账本、AcceptanceService、TaskService、companion UI。不改代码。

> **状态说明**：本文中的“没有 companion 表/API”“纯展示”“schema v2 待实现”等内容，均是当时的设计基线，已经由后续提交实现并取代。保留本文仅用于追溯接缝决策和风险；不要把其中的待办清单当作当前缺失功能。

## 结论（给设计/实现）

当时的大肥鱼是**纯展示 + 前端瞬时演出**。本结论仅适用于 v1 基线；当前版本已经通过 `CompanionService`、schema v3 及 `/api/companion*` 完成持久化养成，并接入任务、休息和验收事务。

硬约束（不可破）：

1. **SQLite 是唯一真源**；`documents.payload` JSON 只是同事务兼容快照。
2. **不得削弱目标验收标准**：路径和颗粒度可改，最终成果 / 成功标准不能因陪伴或积分自动降低。
3. **不得把 `motivation.points` 直接映射为精力**。积分账本已含负分（跳过 -5、失败 -3），那是执行反馈，不是宠物生命值。
4. **`needs_review` 不得涨养成、不得标 done、不得插入补救任务**（现验收已如此）。

交付物给下游：本文件。设计任务应产出 `companion-design.md`；实现任务应新增 `companion_service.py` + schema v3，而不是改 `acceptance.py` 判定规则。

---

## 1. 当前 companion 交互：哪些只在前端内存

UI 宿主：`web/index.html` `#companion`；逻辑：`web/app.js` `companionSnapshot` / `renderCompanion` / `runCompanion` / `playCompanion`。立绘：`web/pets/dafeiyu/{front,side,back,icon}.png`（MIT，来源见 `web/pets/dafeiyu/SOURCE.txt`）。本文引用的是 v1 前端形态；当前持久状态由 `/api/state.companion` 提供。

| 动作 | UI 入口 | 实际效果 | 是否持久化 | 后端 |
|---|---|---|---|---|
| 戳 | `[data-companion=poke]`（立绘舞台） | `playCompanion('poke', …)` 约 1.2s，换 side 图 + 💢 | **否，仅 `companionPlay` 内存** | 无 |
| 喂·小鱼干 / 蛋糕 / 棒棒糖 | `data-companion=feed` + `data-treat` | 同上，约 1.8s，front 图 + emoji | **否** | 无 |
| 说话 | `data-companion=talk` | 约 2.2s 随机台词 | **否** | 无 |
| 开始专注 | primary `focus` | 下一件 `status='doing'`，`POST /api/task-state` | 任务状态是，陪伴不是 | `TaskService.set_status` |
| 暂停 | secondary `pause`（专注中） | `POST /api/task-state` `paused` | 任务状态是 | 同上 |
| 提交验收 | primary `submit`（专注中） | 点击已有 `[data-ai-evaluate]` | 验收结果是（见 §4 落盘风险） | `/api/evaluate-task` |
| 休息 / 结束休息 | secondary `rest` / `end-rest` | 转发 `#quickStartBreak` → `/api/break` 或 `/api/break-end` | `breaks[]` 是 | 休息 API |
| 补救 | primary `recover`（最近 outcome 为 failed/skipped） | `POST /api/recovery` 再 `task-state doing` | 任务是 | 保底任务，**不是** `AcceptanceService` 补救 |
| 去补全目标 | primary `goal` | `switchPage('settings')` | 无陪伴 | 无 |

持久心情**不是**独立状态机，而是每次 `render()` 从任务/休息/积分账本推导：

1. 有 `status==='doing'` 且未 done → mood `focus`
2. 否则 `state.break_active` → `rest`
3. 否则最近 `motivation.history[].outcome==='accepted'` → `happy`（文案用 streak）
4. 否则 `failed` / `skipped` → `cheer`
5. 否则有下一件 → idle/待命
6. 否则无目标 → 待机，引导去设置

在 v1 基线中，`companionPlay` 到期后无存储，刷新即消失；当前版本仅保留短时演出为前端状态，精力、默契、饥饿、生命、经验、等级和事件账本由 SQLite 持久化，并由 `/api/state.companion` 返回。

前端已复用、实现必须继续走的挂钩（不要另做一套开始/休息）：

- 专注：`runCompanion('focus')` → `api('task-state',{idx,status:'doing'})`
- 休息：`runCompanion('rest'|'end-rest')` → 现有 break widget（今日最多 3 次）
- 验收：`runCompanion('submit')` → 现有单任务验收按钮，最终 `/api/evaluate-task`

---

## 2. SQLite 真源、schema、账本、备份边界

### 2.1 版本与迁移

- `state_store.py`：历史基线为 **`SCHEMA_VERSION = 1`**、`MIGRATIONS = {1: "initial_schema"}`；当前版本为 schema v3，并包含 companion 与技能先修迁移
- 打开已有库且 `PRAGMA user_version < SCHEMA_VERSION` 时先 `create_backup("pre-migration")`
- 升级循环：`range(current+1, SCHEMA_VERSION+1)` 写入 `schema_migrations`，再 `PRAGMA user_version=SCHEMA_VERSION`
- **库比应用新** → `StorageCorruptionError("database schema is newer than this application")`，禁止用空库覆盖
- 养成必须把版本升到 **2**，并给 `MIGRATIONS[2]` 名字；打开 v1 库必须 pre-migration 备份

### 2.2 表（v1）与投影

`SqliteStore._initialize` 建表后，`save("task-config.json")` 在**同一事务**里 `DELETE` 再投影。JSON `documents` 与关系表一起提交。

当前表：`documents`, `schema_migrations`, `attachments`, `goals`, `success_criteria`, `constraints`, `tasks`, `task_criteria`, `materials`, `answer_keys`, `evidence`, `acceptance_runs`, **`focus_sessions`（只建/只删，从不 INSERT）**, `feedback`, `skills`, `skill_prerequisites`, `review_logs`, `events`, **`motivation_ledger`**, `app_usage_daily`, `eval_samples`, `deleted_items`。

历史基线**没有 companion / pets / energy 表**；当前版本已有 `companions` 与 `companion_events`，并由 `CompanionService` 维护。

投影规则（`_project_state`）：

- 每次保存先清空上列业务表（含 `focus_sessions`、`motivation_ledger`、`events`）
- `motivation_ledger` ← `state.motivation.history[]`（条目可选 `id`；`goal_id` 仅当 history 自带且目标存在）
- `events` ← `state.events[]`
- `acceptance_runs` ← 各任务 `acceptance_result`（每任务一条，不是完整历史）
- `focus_sessions`：**删除后不写回**，死表

实现选择（风险见 §6）：

- **A. 养成只活在关系表**（推荐贴近「JSON 只是快照」）：v2 新表**不要**放进现有无差别 `DELETE` 列表，除非同时从 JSON 重建。独立 `INSERT` 必须与 `documents` 同事务，否则恢复/导出会丢。
- **B. 养成进 `task-config.json` 再投影**：必须进 `CFG0`、`/api/state`，并改 `_project_state`。`ensure_goal_state` / `save_goal_state` 今日**不**切换 `motivation`（见下），不要误把宠物挂到目标快照上。

### 2.3 文档与落盘路径

- 用户数据：`%LOCALAPPDATA%\TaskVerge`（测试 `--ci` 隔离）
- 真源：`taskverge.db`
- 会投影的文档：`task-config.json`、`fgtime.json`（`history.json` 也走 STORE，但不投影业务表）
- `lc()` / `sc()`：读/写配置。`sc()` 递增 `state_revision`，`compact_state`，`cleanup_uploads`，`js(P["cfg"], c)` → SQLite
- `save_goal_state()`：**只**把当前目标的 tasks/flags/user_model/… 写回 `*_by_goal`，**不写盘**。注释写「避免二次 revision」
- 过时注释（`task-panel.pyw` ~197）：仍写「JSON remains the source of truth」；以 `CODE_WIKI.md` §7 为准

### 2.4 Motivation 账本（可解释、但不是宠物）

`adaptive.record_outcome`（`adaptive.py`）：

```
OUTCOME_POINTS = {"accepted": 10, "partial": 2, "skipped": -5, "failed": -3}
state.motivation = {points, streak, best_streak, history[-100:]}
history 项：{outcome, points, ts}
并回写 user_model.motivation_points / user_model.streak
```

调用方：

- `AcceptanceService.persist_result`：`passed` → `accepted`；`failed` → `failed`；**`needs_review` 不记 outcome**
- `TaskService.set_status`：状态变化且新状态 ∈ `{partial, skipped}` 时记一次（重复同状态不重复记）

隔离现状：

- `motivation` 在 `CFG0` **顶层**，`ensure_goal_state` / `save_goal_state` **不按目标切换**
- `user_model` **按目标**隔离
- 于是积分账本跨目标累积，而 `user_model.motivation_points` 随目标切换，**二者会分叉**
- 前端 `renderMotivationScore` / `#heroStreak` 读的是顶层 `motivation`

**养成不要复用这套 points。** 可**观察** `history[].outcome` 作为挂钩输入（今日 UI 已这样做），但 energy/bond 必须独立字段与独立事件。负分已构成惩罚循环，再映射到精力会违反「no-punishment-loop」。

### 2.5 备份 / 恢复 / 导入导出

| 能力 | 行为 | 对养成的含义 |
|---|---|---|
| 滚动备份 | automatic 48 / daily 14 / weekly 8 / monthly 12 / pre-migration 5 / pre-restore 10 + manual | v2 升级走 pre-migration |
| `restore_backup` | 先 pre-restore；`confirm:true`；损坏件保留 | 宠物必须在 db 内，restore 后 energy/bond 仍在 |
| `export_complete` / `import_complete` | `.tvbackup` = 库 + 附件 + 哈希 | 新表会随库走；不要把养成放到附件目录 |
| 完整性 | 启动 quick check；坏库不空写，列备份等确认 | 应用 id 必须仍是 `0x54564745` |
| 测试锚点 | `tests/test_state_store.py`：同事务投影 counts、restore、完整导入 | v2 后 counts/投影测试必须仍绿 |

`/api/state` 已返回 `motivation`、`break_active`、`breaks`、`events`、`focus_guard`、`last_acceptance`。v2 应**附加** `companion` 快照，不要替换这些键。

---

## 3. 现有状态字段（与养成相关）

### 3.1 已持久、可复用（不要重新发明）

| 字段 | 位置 | 含义 | 养成用法 |
|---|---|---|---|
| `tasks[].status` | 每目标 | `pending|doing|paused|partial|skipped`；通过后 `done` | 专注中 / 暂停挂钩 |
| `tasks[].started_at` / `actual_seconds` / `ended_at` / `attempts` | 任务 | 计时；暂停累加秒 | 可解释「守过一次专注」；**不要**用秒数当经验直接加成到积分 |
| `done_flags[]` | 每目标 | 与 tasks 对齐 | 仅 `status==passed` 为 true |
| `tasks[].acceptance_result` | 任务 | `explainable_result`：status/reason/missing/next_steps/overridden/… | 只在 `passed`/`failed` 记养成；`needs_review` 不涨 |
| `breaks[]` | **全局** | `{date, ts, until, minutes, reason, ended?}` | 休息中 mood；每日上限 3 |
| `break_active` | 计算字段 | 任一条 `until > now` | companion rest |
| `events[]` | 全局，截断 300 | `{ts, kind, message, ...extra}` | 审计；养成事件应另表，避免 300 截断丢成长史 |
| `motivation.*` | 全局 | 积分账本 | **只读参考，禁止当 energy** |
| `focus_guard` | 全局 | 分心策略与 stats | 与宠物无关；不要把关窗次数写成惩罚 |
| `last_acceptance` | 每目标 | 最近验收摘要 | 展示用 |
| `product_funnel` | 全局 | 隐私安全漏斗计数 | 可在 first_task_accepted 旁记陪伴，但漏斗白名单目前不含 companion |

`TaskService.set_status` **不允许**直接设 `done`；完成只经验收。陪伴按钮不能开「一键完成」。

### 3.2 今日不存在、v2 需要新增（设计填数值）

建议独立于 motivation / user_model（名称供设计，不是实现锁定）：

- 宠物行：`id`, `name`（大肥鱼）, `energy`, `bond`, `mood`, `updated_at`, 日计数（poke/feed/talk）, 冷却时间戳
- 养成事件：`id`, `ts`, `kind`, `delta_energy`, `delta_bond`, `reason`, 可选 `task_id` / `goal_id` / `dedupe_key`
- `/api/state.companion` 只读快照：当前属性 + 今日剩余次数 + 短时演出提示（演出本身仍可前端播放）

短时演出（poke 动画）与持久状态必须分离：刷新后动画可丢，energy/bond 不能丢。

### 3.3 目标隔离注意

| 数据 | 隔离？ |
|---|---|
| tasks / done_flags / user_model / last_acceptance / feedback | 是（`*_by_goal`） |
| motivation / breaks / events / focus_guard | **否，全局** |
| companion（未建） | 产品是一只鱼：建议 **每安装一份、全局一只**，不要跟目标走；切换目标不应重置默契 |

---

## 4. 事件种类

### 4.1 `evlog` 已有 kind（`state.events` → 表 `events`）

来自 `task-panel.pyw` 字面量：

`ability_diagnostic`, `adaptive_adjust`, `ai_apps`, `ai_apps_skipped`, `ai_apps_failed`, `app_catalog`, `app_catalog_failed`, `archive`, `archive_delete`, `break`, `break_end`, `clear_fg`, `coach_action`, `coach_chat`, `coach_plan`, `fallback_gen`, `first_task_started`, `focus_policy`, `fsrs_rating`, `goal_archive`, `next_cycle`, `plan_lock`, `plan_unlock`, `plan_locked`, `quit`, `quit_continue`, `quit_defer`, `recovery_task`, `remediation_task`, `request_app`, `task_adjust`, `task_edit`, `task_evidence`, `task_response`, `user_feedback`

动态：

- `focus_{kind}`：分心守卫 `FocusGuard._record`（`distraction`, `distraction_seconds`, `closed_windows`, `temporary_allows`, `permanent_allows`, `paused`）
- `/api/event`：客户端任意 `kind`，默认 `ui_event`，截断 40 字符 —— **不要**把养成写到这条开放入口，无法去重、会挤掉 300 条窗口

服务对象内（经 `event=` 回调，同样进 `evlog`）：

- `TaskService`: `task_state` + 新 status
- `AcceptanceService`: `task_acceptance` + `passed|failed|needs_review|...`

### 4.2 养成应新增的事件 kind（建议独立表，不挤 `events[-300:]`）

与 UI 动作对齐，供设计细化数值：

| kind | 触发 | 现有挂钩 | 备注 |
|---|---|---|---|
| `poke` | 戳 | 无，需新 API | 日上限 |
| `feed` | 喂，payload 含 treat | 无 | 三种零食，无背包 |
| `talk` | 说话 | 无 | |
| `focus_start` | 开始专注 | `TaskService.set_status(..., "doing")` | 与 `task_state` 并存，不要改任务语义 |
| `focus_pause` | 暂停 | `set_status(..., "paused")` | |
| `rest_start` / `rest_end` | 休息 | `/api/break`, `/api/break-end` | 已有 `break` / `break_end` |
| `accepted` | 验收通过 | `persist_result` + outcome `accepted` | 可庆祝演出 |
| `failed` | 验收失败 | `persist_result` + outcome `failed` | 记事件；**不要扣 energy 致死循环** |
| `needs_review` | 语义不确定 | `persist_result` **不**调 `outcome` | **不创建养成事件、不涨 bond/energy** |
| `partial` / `skipped` | 任务状态 | `set_status` | 已记积分；陪伴应打气而非惩罚 |

去重：同一 `acceptance_run` / 同一休息时段不要连写。`needs_review` 反复提交仍不涨。

---

## 5. 与验收 / 专注 / 休息的挂钩点

### 5.1 验收（不得改判定，只旁路记成长）

链路：

1. 前端 `[data-ai-evaluate]` 或 companion `submit` → `POST /api/evaluate-task`
2. `evaluate_task()`：无证据且 `verification_mode!="none"` → 失败；否则 `acceptance.check_evidence`；需要时 LLM；**无证据不得通过**
3. `AcceptanceService.persist_result`：写入 `acceptance_result`；仅 `passed` 将 done_flag/status=`done`；`failed` 插入一条 `source=remediation` 任务且 **`acceptance` 原文不变**；调 `record_outcome` / `record_learning_outcome`；`event(task_acceptance)`；`save=save_goal_state`（**只同步目标映射**）
4. 批量 `/api/evaluate`、手动 `/api/manual-accept`（`overridden=true`，仍走 `persist_result` → `accepted`）
5. `/api/remediate-task` → `ensure_remediation`（与 companion `recover` 的 `/api/recovery` 保底任务不是同一条路）

**必须保持：**

- `acceptance.py` 规则、无证据失败、`needs_review` ≠ 通过/失败（`CONTEXT.md`）
- 补救任务复制 `original_acceptance`，不降低标准（`PRODUCT_FLOW.md` §9/§11，`tests/test_acceptance_service.py`）
- `needs_review` 不 done、不补救、**不** `record_outcome` —— 养成同样不涨
- 学习任务手动通过前必须有 recall rating

**挂钩插入点（推荐）：** `AcceptanceService.persist_result` 在结果规范化之后、`save` 之前增加可选 `companion` 回调；**不要**改 `check_evidence`。`evaluate_task` 在 `persist_result` 之后应 `sc()`（见风险 R1），陪伴写入必须与任务验收同一次 `sc()`/同事务。

### 5.2 专注（任务状态，不是 focus_sessions 表）

- 写路径：companion / 任务条 → `POST /api/task-state` → `TaskService.set_status`
- 合法状态：`pending|doing|paused|partial|skipped`（无 `done`）
- `doing` 且目标未就绪 → 拒绝「请先补全目标契约」
- `doing`：写 `started_at`、attempts++、可能 `first_task_started`
- 离开 `doing`：累加 `actual_seconds`
- 然后 `save_goal_state` + **`compact=sc`（写盘）** + `evlog task_state`
- `focus_sessions` 表当前未使用；不要误当成已有专注会话真源
- `/api/focus-policy` 只改 `focus_guard`（暂停拦截、清例外），与宠物心情无关
- 前台守卫 `focus_*` 事件是分心统计，默认不要扣默契（惩罚循环）

挂钩：在 `set_status` 成功且 status 变为 `doing` / `paused` 时记 companion 事件。目标未就绪被拒时不要记成长。

### 5.3 休息

- `POST /api/break`：`minutes` 1–60，**当日 `breaks` 条数 ≥ 3 则 400**；追加 `{date, ts, until, minutes, reason}`；`evlog break`；`sc()`（breaks 全局，无需 `save_goal_state`）
- `POST /api/break-end`：进行中休息 `until=now`, `ended=true`；`evlog break_end`
- `break_active(c)`：任一 `until > now`
- 教练 `coach-action` 也可写 `break`
- `quit` / `continue_15` 会塞一条 15 分钟 break —— 养成若把任意 break 当「休息回血」，会被退出仪式误伤；应过滤 `reason` 或只认用户/陪伴发起的休息

挂钩：companion rest 按钮必须继续走这套上限，不要平行实现休息。

---

## 6. 风险清单

| ID | 严重度 | 风险 | 要求 |
|---|---|---|---|
| R1 | 高 | `AcceptanceService.save` 是 `save_goal_state`，**不** `sc()`。`TaskService` 会 compact。`evaluate_task` 在 `persist_result` 后不 `sc()`。陪伴若只挂在 persist_result 内、调用方不写盘，成长会丢。 | 实现时让验收 + 养成同一 `sc()`；补测试：evaluate-task 后重启进程属性仍在 |
| R2 | 高 | 把 `OUTCOME_POINTS` 当 energy。已有 skip/fail 负分，映射即惩罚循环 | 独立 energy/bond；失败最多「打气」；衰减不要写成死亡 |
| R3 | 高 | 改 `acceptance.py` / 放宽无证据通过 / 补救改写 `acceptance` 文本 | 验收模块只读旁路；`tests/test_acceptance*.py` 必须保持 |
| R4 | 高 | v2 新表放进 `_project_state` 的 DELETE 列表却不 INSERT，或只写关系表不进备份事务 | 投影与 `documents` 同事务；restore/完整导入测试覆盖 companion |
| R5 | 中 | 养成塞进 `user_model` 或 `motivation`：前者随目标切换，后者全局且有负分 | 独立键/表，建议每安装一只全局鱼 |
| R6 | 中 | 戳喂只改前端却在 UI 画持久精力条 | `CODE_WIKI` 已禁；有条必须来自 `/api/state.companion` |
| R7 | 中 | 用 `POST /api/event` 记养成：无上限去重，且 `events[-300:]` 会丢 | 独立 ledger + 日上限 |
| R8 | 中 | `/api/recovery`（role=recovery 保底）与 `source=remediation` 补救是两条线 | 设计写清庆祝/打气挂哪条；不要合并导致双计 |
| R9 | 中 | 休息回血误统计 quit-continue 的 15 分钟 break | 过滤发起源 |
| R10 | 低 | `focus_sessions` 死表，易被误用 | 要么 v2 真正投影会话，要么不把它当 API |
| R11 | 低 | 过时「JSON 真源」注释 vs CODE_WIKI | 实现注释/文档与 wiki 对齐 |
| R12 | 低 | 立绘 PNG 在 t3 `outOfScope` | 不要替换美术；只改 html/css/js |
| R13 | 中 | 每日上限若只在前端 | 拒绝必须在 CompanionService，测试不可 skip |
| R14 | 中 | schema 只升 `user_version` 不写 `MIGRATIONS[2]` | 打开 v1 要有默认宠物行且任务数据不变 |

---

## 7. 给下游的接缝清单（最小复用）

设计（t2）应假设：

- 可玩动作已有 UI：戳、三种喂、说话、专注、休息、验收庆祝/打气
- 持久属性今日为 **零**；mood 文案可暂时继续从任务/休息/账本推导，但不得暗示已存等级
- 数值表不要用 `motivation.points`
- `needs_review` 零成长

实现（t3）应改/挂：

| 接缝 | 文件 | 做法 |
|---|---|---|
| schema v3 + 投影/备份 | `state_store.py` | `SCHEMA_VERSION=3`，技能先修含 kind/rationale，pre-migration，新表，健康报告 |
| 状态机 | 新 `companion_service.py` | 日上限、去重、delta、默认行 |
| 编排 | `task-panel.pyw` `run_web` | 与 TASKS/ACCEPTANCE 一起注入；`/api/companion`, `/api/companion-event`；`state()` 加快照 |
| 验收旁路 | `acceptance_service.py` | 可选 callback；不改 `acceptance.py` |
| 专注旁路 | `task_service.py` | `doing`/`paused` 成功后 |
| 休息旁路 | `/api/break` `/api/break-end` | 用户休息后 |
| UI | `web/app.js` `index.html` `api.js` | poke/feed/talk 改为写库；演出仍本地；条数据来自 state |
| 文档 | `CODE_WIKI.md` | 删除「不持久化精力或默契」 |

测试锚点（t4 必须仍绿）：`tests/test_motivation.py`、`test_acceptance_service.py`、`test_task_service.py`、`test_state_store.py`、`test_api.py::test_evaluate_task_does_not_evaluate_siblings`。

---

## 来源

- `CODE_WIKI.md` §3 陪伴纯展示；§7 SQLite 真源与备份；§10 不降低成功标准
- `PRODUCT_FLOW.md` 路径可调、标准不可降；验收先确定性
- `CONTEXT.md` `needs_review` 不得当通过或失败
- `state_store.py` `SCHEMA_VERSION`、建表、`_project_state`、备份
- `adaptive.py` `record_outcome` / `OUTCOME_POINTS`
- `acceptance_service.py` `persist_result` / `ensure_remediation` / `manual_accept`
- `task_service.py` `set_status` / `replace`
- `task-panel.pyw` `CFG0`、`ensure_goal_state`、`save_goal_state`、`sc`/`lc`、`evlog`、`evaluate_task`、`/api/break*`、`/api/task-state`、`/api/recovery`、`run_web` 注入
- `web/app.js` companion 函数；`web/index.html` 结构
- `tests/test_motivation.py`、`test_acceptance_service.py`、`test_task_service.py`、`test_state_store.py`
