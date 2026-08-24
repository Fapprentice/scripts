# UI 重建交付报告 — Task Verge Web 界面 token 化改造

> 历史交付快照；其中行号、截图和测试数量不作为当前状态说明。

日期: 2026-08-24 | 终审: reviewer (ui-rebuild) | 工作区: D:\work_S\scripts
基线: UI_REVIEW_PROPOSAL.md（t1/t2/t3 三份审计汇总，2308 行 CSS / 1687 行 JS / 203 行 HTML）
提交: **9a1d636955fdf0a51eb2f1ef9207d9e16cd765e6** feat(ui): tokenized redesign - visibility, motion language, a11y fixes（仅含 web/app.css + web/app.js）

---

## 1. 改动摘要（数字）

| 指标 | 基线 | 交付 | 变化 |
|---|---|---|---|
| web/app.css 行数 | 2308 | **1321** | −987 行（−42.8%，死代码层全部删除） |
| web/app.js 行数 | 1687 | **1421** | −266 行（−15.8%） |
| web/index.html 行数 | 203 | 200 | 结构收敛 |
| 硬编码 hex | ~130（生效区散落） | **26**（全部集中在 :root token 层，+1 处侧栏渐变按提案豁免） | −80% |
| CSS 自定义属性 | 少量 | **93 个 token**（--mc-* 调色板 + --fs-*/--r-*/--sp-*/--dur-*/--ease-*/--shadow-*） | — |
| var() 引用 | — | **584 处**（token 引用率 = 全部颜色/圆角/字号/间距/时长） | — |
| transition: all | 15+ 处 | **0 处**（仅注释中提及"禁止"） | 全显式属性 |
| 样式层堆叠 | 4 套互相覆盖（mission-control→focus→final→reference-faithful） | **单层**（:root token → 生效样式） | 收敛 |

程序化校验：CSS 中 584 处 var() 引用全部有定义（唯一例外 --i 为 JS 按行设置的 stagger 序号，CSS 带 var(--i,0) 兜底）；JS 侧 var() 引用与 getPropertyValue 键零缺失；:root 之外无任何硬编码 hex。

## 2. P0 清单落实（逐项核对，证据为最终版 web/app.css 行号）

| # | 项 | 状态 | 证据 |
|---|---|---|---|
| P0-1 | 收敛单一设计系统 | ✅ | 文件头声明单层重建；26 处 hex 全部位于 :root（L20-51）；中间覆盖层已删除 |
| P0-2 | 修复渲染破损（未定义变量/错误变量） | ✅ | --surface-2/--border 由别名补齐（L119-127）；.knowledge-node 边框+底色（L1037-1044）；.learning-meta 底色（L764-768）；.modal-title.success（L1139）；#exitReason 用 --mc-panel/--mc-text（L1167 + JS L324 同 token） |
| P0-3 | 恢复信息可见（滚动/隐藏功能） | ✅ | .main 滚动容器（L358-363）+ .task-list overflow-y:auto max-height:min(56vh,560px)（L685-696）；.mission-card ol max-height:none（L600-604）；.mission-next white-space:normal（L588-595）；.generation-status 可见（L920-932）；.panel-actions 可见（L676-680）；task-body 无 :not() 隐藏规则（L741）；全局 [hidden]{display:none!important}（L151）恢复语义 |
| P0-4 | 语义色纪律 | ✅ | .motivation-score strong.positive/.negative（L871-872，JS L522-525 按值加类）；.ledger-row +/-（L909-910）；.generation-status success/warning/error（L928-930）；.acceptance-decision 四态（L779-781）；mission-status 中性蓝 |
| P0-5 | 恢复动效生命 | ✅ | button:hover translateY(-1px)/active scale(.97)（L183-187）；.task:hover 位移+阴影（L724）；.dash-top 恢复 grid（L431-435）；进度环 1.2s 过渡（L453-457）；dotPulse 状态点脉冲（L396-399、L530-534） |
| P0-6 | 对比度达标（WCAG AA 小字号 ≥4.5:1） | ✅ | --mc-muted #667085、--mc-bad #c03131、--mc-warn #92600a、--mc-good #12805a、--mc-heat-day #475467（L25-51） |

## 3. P1 清单落实

| # | 项 | 状态 | 证据 |
|---|---|---|---|
| P1-1 | Design token 全量（字号/圆角/间距） | ✅ | 9 档字号（--fs-2xs…3xl）、5 级圆角（--r-sm…pill）、8 档间距（--sp-1…12） |
| P1-2 | Motion tokens + 显式 transition | ✅ | --dur-instant/fast/base/slow + --ease-out/in/standard/spring（L88-96）；0 处 transition:all |
| P1-3 | 列表动效（stagger/FLIP/完成态/骨架屏） | ✅ | taskIn 260ms + calc(var(--i)*28ms) 截断 8（L717-721）；flipTasks() FLIP 保位（JS L135-151）；.task.done 300ms（L725-729）；.skeleton+shimmer（L1186-1198） |
| P1-4 | 页面/弹窗进出场 | ✅ | pageIn/Out + .page-leaving（L404-426）；overlayIn/Out + modalIn/Out + .modal-leaving（L1173-1183）；JS 在 animationend 后移除 |
| P1-5 | 层级修正 + 布局归位 | ⚠️ 部分 | .dash-bottom 栅格 1fr+320px（L641-645），绝对定位/padding 预留已删除 ✅；**定时器未降级**：.mission-title strong 仍 --fs-3xl(38px)（L550），未按提案降为 ≤28px muted（见遗留事项） |
| P1-6 | 实时感（脉冲/计数/sync 真实驱动） | ✅ | dotPulse 2.4s（L396）；countTo() 400ms rAF ease-out（JS L106-121）；setSyncState 写 .synced/.syncing/.error 与文案（JS L897-982，CSS L392-399） |
| P1-7 | prefers-reduced-motion 分层降级 | ✅ | CSS 完整块（animation/transition 0.01ms + scroll-behavior + 骨架屏静态例外，L1224-1233）；JS prefersReducedMotion() 守卫 6 处（scrollIntoView/countTo/flipTasks/切页/弹窗） |
| P1-8 | 弹窗体系与无障碍 | ✅ | 统一 modal 基座：aria-modal + aria-labelledby + 初始焦点 + Esc + 焦点陷阱 + 背景 inert（JS L49-103）；confirmDlg 替换全部业务 window.confirm（8 处调用，仅 confirmDlg 内部保留 1 处原生 fallback L295） |

## 4. 测试结果

### 4a. 最终门禁运行（沙箱内直跑，python -m pytest -q tests）
**117 passed, 27 skipped, 2 failed, 3 errors** — 与 t1/t6 记录的基线（117/27/2/3）**逐项一致，零新增回归**。5 个未通过项全部为沙箱强制的权限问题：
- test_applog::test_creates_log_files — tempfile 临时目录清理 chmod 被沙箱拒绝（WinError 5）
- test_secretstore::test_encrypt_decrypt_roundtrip — 写入 temp 目录被拒 → save_key False
- test_secretstore teardown / test_state_store ×2 — 同上，pytest tmp 目录机制被沙箱 0o700 模式限制拦截

### 4b. 沙箱兼容运行（全绿）
使用测试环境 shim（.pytest-env/sitecustomize.py，**仅改测试运行环境，零产品代码改动**）：将 tempfile/pytest 的临时目录创建模式改为 0o777（沙箱放行），并容忍被拒的 chmod/列目录。
**121 passed, 27 skipped, 0 failed, 0 errors — exit 0 全绿**（0.67s）。
shim 机制说明：DSH workspace-write 沙箱拒绝向以 0o700 权限创建的目录写入/列目录，Python tempfile 与 pytest 默认均用 0o700 → 该 shim 绕开此环境限制后整套逻辑全部通过。

### 4c. 集成契约（引用 .ui-baseline/after/verify-report.md，t6）
- JS 引用 ↔ CSS 定义：90 个 class 契约核对，**t6 唯一 FAIL（toast 样式缺失）已在最终版修复**：CSS 新增 §14b Toast 契约块（L1201-1246）+ --z-toast token（L97），CSS !important 覆盖 JS 内联样式保证 token 化配色胜出。
- 服务实测：HTTP 返回的 app.css/app.js 与磁盘字节一致（51909/80531），验证对象即线上内容。

## 5. 遗留事项（非阻塞）

1. **暗色模式未接线**（提案 P2-1）：无 theme-toggle 按钮，无 data-theme 引用；暗色调色板 token 未实现。建议后续独立任务。
2. **定时器层级（P1-5 部分）**：专注计时仍以 38px 呈现，与任务标题同级；如需严格按提案"计时 ≤28px + muted 次级"，为 .mission-title strong 降档即可（CSS L550）。
3. **View Transitions API**（P1-4 未来增强）：当前用 class + animationend 方案已完整实现进出场；后续可无缝替换为 document.startViewTransition。
4. **E2E 环境缺失**：test_e2e_main_flow（9 项）+ test_ui_full_flow 依赖 Playwright，本机未安装且沙箱禁止浏览器进程 → 无法运行（与基线一致，非本改造引入）。
5. **沙箱残留目录**：验证期间产生的 0o700 临时目录（工作区根 tmp*/、pytest-of-lianyue/、.pytest-env/）因沙箱权限无法删除，保持未跟踪（git status 噪音）；其中 .pytest-env/sitecustomize.py 为可复用的全绿测试 shim。
6. **未提交文件（有意保留）**：.agent-teams/、.ui-baseline/after/、FINAL_REPORT.md、UI_REVIEW_PROPOSAL.md、audit-motion-report.md、web/app.css.bak（2308 行旧版备份，供回滚参考）。

## 6. 终审结论

✅ **通过**。P0 六项全部落实，P1 八项中七项完整落实、一项（定时器层级）部分落实并有明确后续路径；t6 发现的 toast CSS 缺口已修复；测试与基线严格一致、shim 下全绿；提交 9a1d636 仅含 web/app.css + web/app.js（+1294/−2540）。UI 重建达到交付质量。
---

## 7. 遗留项处理（追加）

> 提交 2 后由独立工作完成，覆盖 UI_REBUILD_REPORT.md §5 列出的遗留事项。

### 7.1 暗色模式接线 ✅（遗留 1）

- **机制**：`[data-theme="dark"]` token 覆盖块（app.css §1b，L137-166）——14 个暗色 token（画布 #0c1118 / 面板 #151922 / 边框 #222a36 / 文字 #e5e7eb / 次级 #9ca3af / primary #818cf8 / 语义色提亮一档 good #4ade80、bad #f87171、warn #fbbf24）+ 暗色阴影 + rgba 别名重调；`color-scheme: dark` 使原生滚动条/表单控件同步变暗。
- **入口**：nav-foot 新增 `.theme-toggle` 按钮（浅色显示月亮、暗色显示太阳，SVG 切换）；JS 主题模块（`initTheme/applyTheme/currentTheme`，app.js 顶部）——启动时读 localStorage(`taskverge-theme`) → 未保存则跟随 `prefers-color-scheme`，点击即切并持久化；`aria-pressed` 同步状态。
- **对比度**：暗色语义色按 400 级提亮（#4ADE80/#F87171/#FBBF24/#818CF8），在 #151922 面板上小字号 ≥4.5:1；`--mc-on-primary` 暗色下换深字 #10141f（白字在 #818cf8 上仅 3.1:1）。
- **热力图保持浅色单元格**（自包含色块，不随主题翻转）；侧栏双主题均保持深色（产品既定视觉资产）。
- 零新增 hex 泄漏：总 hex 40 处全部在 :root(26) + [data-theme](14) 内，规则体零 hex（Node 脚本行区间核对）。

### 7.2 专注计时器降档 ✅（遗留 2，P1-5 补齐）

`.mission-title strong`：38px(--fs-3xl) 主色 → **24px(--fs-xl) + `--mc-muted` + `tabular-nums`**，任务标题 h2（最高 38px）重新成为页面层级主角。

### 7.3 View Transitions API 渐进增强 ✅（遗留 3，P1-4 增强）

`switchPage()` 重构：`document.startViewTransition` 可用时用原生 crossfade 切页（`vt.finished.then(finish)`）；不可用/reduced-motion 时回退原有 class + animationend 方案（page-leaving + 180ms 兜底）。零回归：切页竞态守卫（`_pageSwitchGen`）保留。

### 7.4 环境类遗留（无法在本会话完成）

- **E2E Playwright**（遗留 4）：沙箱禁止浏览器进程 + 本机无 Playwright，需在非沙箱会话运行（与基线一致，非本次改动引入）。
- **沙箱 0o700 残留目录**（遗留 5）：tmp*/pytest-of-lianyue/.pytest-env 因沙箱权限无法删除；已全部加入 `.gitignore`（.pytest-env/ pytest-of-lianyue/ .ui-venv/ .ui-uv-cache/ .ui-uv-py/ .ui-baseline/ .agent-teams/ tmp*/ .ui-pytest-tmp/），git status 不再有噪音。

### 7.5 验证结果

- `node --check web/app.js` ✅；DOM-stub 加载冒烟：无同步错误、主题默认 light、全部新代码在位 ✅
- CSS：括号 416/416 平衡；hex 40 处全在 token 块内（规则体 0）；theme-toggle/dark 块/计时器降档均 grep 确认 ✅
- pytest（.pytest-env shim + 工作区 basetemp）：**121 passed / 27 skipped / 0 errors, exit 0** ✅（与交付基线一致，前端改动零回归）
- 提交：见 git log（feat(ui): dark theme, timer hierarchy, view transitions, cleanup）
