# Task Verge — 顶级审美 UI 改进方案

> 历史改进提案；部分事项已经实现，当前界面规范以 `README.md` 和实际代码为准。

> 汇总自三份审计：t1 视觉设计审计（ui-designer）、t2 动效与动画审计（motion-engineer）、t3 前端实现与可用性审计（frontend-reviewer）。
> 基准代码：`web/app.css`（2308 行）、`web/app.js`（1687 行）、`web/index.html`（203 行）。
> 原则：去重、冲突时以**视觉一致性**为准；每条给出可直接落地的参数与变量命名。

---

## ① 总体评价

**现状水平**：信息架构清晰、栅格大方向正确、基础 token 层（indigo 品牌色 + surface 灰阶 + 语义色 + 8 档阴影 + focus-visible + prefers-reduced-motion）设计良好，字体搭配正确（Inter + JetBrains Mono），是一份「骨架合格、血肉缺失」的 6/10 分界面。谈不上丑，但明显「未完成」：扁平、死板、无动效、多处硬编码漂移。

**最大短板（按根因排序）**：

1. **四套设计系统叠在一个 CSS 文件里互相覆盖**（app.css 从 :108 起连续堆叠 mission-control → focus → final override → reference-faithful 四层，死代码约 45%，生效样式约 130 处硬编码 hex 绕过 token）。这是视觉、动效、可维护性全部问题的**总根因**：动效被逐层禁用（hover transform 全部置 none、`.dash-top` 直接 display:none 隐藏进度环/statusPill/hero），圆角/字号/边框色各自为政。
2. **信息被主动裁剪**：视口锁死 + 大量 overflow:hidden，任务列表不可滚动、验收标准被硬切、下一步说明被省略号截断——不是信息密度高，是「被砍」。
3. **动效全灭**：用户实际看到的仪表盘没有任何进行中动画，唯一残留是切页 pageIn；状态点静止、数字硬跳变、列表整表重建零过渡。
4. **语义色误用**：负分用绿色（最误导）、紫色同时充当按钮与状态文案、成功弹窗渲染成红色。

一句话：**先把四层覆盖收敛成一套 token 化的设计系统、恢复被禁用的微交互与滚动，审美立刻上一个台阶；再谈质感。**

---

## ② 高优先级修改（P0 — 一眼可见的视觉/动效问题）

> 每条格式：**问题 → 方案 → 具体参数/代码方向**

### P0-1 收敛为单一设计系统（消除 4 层覆盖 + 130 处硬编码）——一切问题的总根因

- **问题**：app.css 内 4 套互相推翻的样式层，同一选择器在 final override 与 reference-faithful 里互相覆盖（如 focus-active 下 `.nav` 先 display:flex!important 又 display:none!important，:2030 vs :2044）；生效区（:1801-2308）约 130 行硬编码 hex（#f7f8fa / #0c1420 / #4b52ff / #5b5ce2 / #667085 / #98a2b3…）。截图 2/3 已出现肉眼可见的对齐偏差。
- **方案**：保留「顶部 token 层（:14-106）+ 最外层 reference-faithful（:2067+）」两段，**删除 :108-151（2026 redesign）与 :1947-2067（final override）两层中间覆盖**（或整体移入 `web/_legacy.css` 备用）。全部硬编码 hex 换成 var()。
- **代码方向**：
  ```css
  /* 单一事实来源：扩展 --mc-* 命名空间，替换硬编码 */
  :root {
    --mc-shell: #0f1115;            /* 侧栏底色（沿用现 nav 渐变底） */
    --mc-nav: #151922;
    --mc-canvas: #f7f8fa;           /* 画布 */
    --mc-panel: #ffffff;            /* 卡片 */
    --mc-text: #111827;
    --mc-muted: #667085;            /* 次级文字（≥4.5:1，见 P0-6） */
    --mc-border: #e4e7ec;           /* 全站唯一边框色（消灭 5 个近似色） */
    --mc-primary: #5b5ce2;          /* 主操作 */
    --mc-primary-hover: #4a4bd6;
    --mc-primary-soft: #eef0ff;     /* 状态 chip 底色 */
    --mc-good: #12805a;             /* 小字号达标绿（≥4.5:1） */
    --mc-bad: #c03131;              /* 小字号达标红 */
    --mc-warn: #92600a;             /* 小字号达标琥珀 */
  }
  ```
  删除时同步删除已无引用的 keyframes（orbDrift :285、theme-toggle、desktop-app 等，见 P2-3）。

### P0-2 修复真实渲染破损（未定义变量 + 错误变量）

- **问题**：① `var(--surface-2)` 与 `var(--border)`（:1984/1989/1991）在 :root 与 dark 块中**均未定义** → 复盘页 .knowledge-node 无边框无背景、.learning-meta 标签无底色、.knowledge-graph 无分隔线；② 成功弹窗标题渲染成红色——`.modal-title` 只有 .warn/.info 规则（:1574-1576），success 调用（app.js:1226/1389）回落到 var(--bad)；③ 退出页原因输入框 `background:var(--card-bg,#161b22);color:var(--fg)`（app.js:190）两变量未定义 → 深底深字，文字不可见。
- **方案**：① 定义缺失变量：`--surface-2` → `--mc-panel`（或直接补 `--surface-100`），`--border` → `--mc-border`；② 补 success 态；③ 改 app.js:190 为 `background:var(--mc-panel);color:var(--mc-text)`。
- **代码方向**：
  ```css
  .modal-title.success { color: var(--mc-good); }        /* 或 var(--good) */
  .knowledge-node { border:1px solid var(--mc-border); background:var(--mc-panel); }
  .learning-meta { background:var(--mc-primary-soft); }
  ```

### P0-3 恢复信息可见：列表可滚动、被隐藏的功能与进度反馈回来

- **问题**：① `html,body{height:100%;overflow:hidden}`（≥761px，:2226）+ `.task-list{max-height:calc(100% - 37px);overflow:hidden}`（:2252）→ 超量任务不可达；② `.mission-card ol{max-height:clamp(46px,7.2vh,88px);overflow:hidden}`（:2237）→ 验收标准被硬切；③ `.mission-next{white-space:nowrap;…ellipsis}`（:2235）截断下一步；④ `.generation-status{display:none!important}` 与 `.dash-tasks .panel-actions{display:none!important}`（:2148）→ 生成进度/重试、新增/重新生成/锁定按钮全部不可见（app.js 中对应逻辑成死路径）；⑤ `.task-body > :not(.task-title):not(.task-meta){display:none}`（:2161）→ 交付物、验收标准、chip 全隐藏；⑥ `.recovery-box[hidden]{display:block!important}`（:2173）→ 无补救任务时补救卡常驻。
- **方案**：裁剪改滚动、隐藏改显示、hidden 语义恢复。单视口锁死改为「滚动区」策略。
- **代码方向**：
  ```css
  .task-list { overflow-y: auto; scrollbar-width: thin; }        /* 或 #dashboard 行 1 滚动 */
  .mission-card ol { max-height: none; overflow: visible; }      /* 让内容自然展开 */
  .mission-next { white-space: normal; }
  .dash-tasks .panel-actions, .generation-status { display: flex !important; }
  .task-body > * { display: revert; }                            /* 恢复详情 */
  .recovery-box[hidden] { display: none !important; }            /* 删除劫持规则 */
  ```

### P0-4 语义色纪律（最误导人的视觉问题）

- **问题**：① 负分/惩罚显示绿色——`.motivation-score strong{color:#16a36a}` 无条件（:2136），「当前积分 -5」为绿；② 紫色 #5b5ce2 同时用于主操作按钮（#generate）与状态文案/meta 标签（「专注中」像可点击按钮）；③ 橙色用于「待处理」pending（orange 语义是警告）。
- **方案**：积分按正负着色（负=红、正=绿）；状态 chip 用中性蓝/灰，紫色只留给主操作；每个状态在 token 层定义一对一 fg/bg。
- **代码方向**：
  ```css
  .motivation-score strong.negative { color: var(--mc-bad); }   /* JS 按值加类 */
  .motivation-score strong.positive { color: var(--mc-good); }
  .mission-status, .meta-chip { color: var(--mc-text); background: var(--mc-primary-soft); }
  .meta-chip.pending  { color:#475467; background:#f2f4f7; }    /* 中性等待 */
  .meta-chip.success  { color:var(--mc-good); background:var(--good-surface); }
  .meta-chip.warning  { color:var(--mc-warn); background:var(--warn-surface); }
  ```

### P0-5 恢复动效生命（解除「覆盖杀动效」）

- **问题**：`button:hover{transform:none}`、`.task:hover{transform:none}`、`button.primary{box-shadow:none}`（:2026-2028/:2141/:2031）——hover 反馈被全部削平，只剩边框变色；`.dash-top{display:none!important}`（:2095）把进度环、statusPill、hero 这组原系统唯一的强动效部件整体隐藏。真实界面 0 个进行中动画（截图确认）。
- **方案**：删除所有 `transform:none` 覆盖；恢复 `.dash-top`（进度环 + 状态胶囊 + hero 统计），或在其位置提供等价动效部件。
- **代码方向**（配合 P1-2 的 motion tokens）：
  ```css
  button:hover { transform: translateY(-1px); }
  button:active { transform: scale(0.97); }
  .task:hover { transform: translateY(-1px); box-shadow: var(--shadow-sm); }
  .dash-top { display: grid; grid-template-columns: minmax(0,1fr) 320px; gap: 18px; }
  ```

### P0-6 对比度达标（WCAG AA，小字号 ≥4.5:1）

- **问题**（t1/t3 实测）：#98a2b3 on #fff = 2.58:1（sync-state/占位/小字）；#b7791f = 3.64（小字号不达标）；#d94f4f = 4.05（小字号不达标）；#16a36a 42px = 3.24（仅大字号）；热力图 level1-2 日号 2.6-3.8:1。
- **方案**：浅灰提示提深、语义色加深（见 P0-1 token 值）、热力图日号改深色或加描边。
- **具体值**：
  ```css
  --mc-muted: #667085;          /* 由 #98a2b3 提深，2.58→4.6:1 */
  --mc-bad:   #c03131;          /* 由 #d94f4f，4.05→4.6:1 */
  --mc-warn:  #92600a;          /* 由 #b7791f，3.64→4.6:1 */
  --mc-good:  #12805a;          /* 小字号绿（大字号可仍用 #16a36a） */
  .heatmap-cell.l1,.heatmap-cell.l2 { color: #475467; }   /* 深色日号 */
  ```

---

## ③ 中优先级（P1 — 质感提升）

### P1-1 Design token 全量重构（字号阶梯 / 圆角尺度 / 间距 / 边框统一）

- **问题**：约 31 个不同字号无阶梯（42px 积分、37px 计时、38px 标题三个大数字互相抢戏）；圆角 12 个不同值 + 9 处 0（按钮 4px 在 10px 卡片上生硬）；边框 5 个近似色并存；无间距 scale。
- **方案**：定义四组 token，全站引用。
- **代码方向**：
  ```css
  :root {
    /* 字号阶梯：12/13/14/15/16/20/24/32/38 */
    --fs-2xs: 12px; --fs-xs: 13px; --fs-sm: 14px; --fs-md: 15px;
    --fs-base: 16px; --fs-lg: 20px; --fs-xl: 24px; --fs-2xl: 32px; --fs-3xl: 38px;
    /* 圆角：6/8/10/12/999（四级 + 胶囊） */
    --r-sm: 6px; --r-md: 8px; --r-lg: 10px; --r-xl: 12px; --r-pill: 999px;
    /* 间距：4 的倍数 */
    --sp-1: 4px; --sp-2: 8px; --sp-3: 12px; --sp-4: 16px;
    --sp-5: 20px; --sp-6: 24px; --sp-8: 32px; --sp-12: 48px;
  }
  /* 应用：按钮/输入 --r-md 8px，卡片/面板 --r-lg 10px，胶囊 999px */
  ```
  删除全部 0-4px 孤值（`border-radius:0` 仅保留在真正需要直角的容器上）。

### P1-2 动效语言统一：motion tokens + 显式 transition

- **问题**：时长 0.2/0.22/0.25/0.3/0.35/0.4/0.5/1.2/1.6s 九档、缓动 5 种混用、**0 个 --dur-*/--ease-* 变量**；31 处 transition 中 15+ 处为 `all`（触发 paint 且不可控）。
- **方案**：建立 motion tokens，transition 全部改显式属性。
- **代码方向**：
  ```css
  :root {
    --dur-instant: 90ms;    /* 按压 */
    --dur-fast: 150ms;      /* hover/focus/小属性 */
    --dur-base: 220ms;      /* 标准进出场、卡片浮起 */
    --dur-slow: 320ms;      /* 页面切换、弹窗 */
    --ease-out: cubic-bezier(0.16, 1, 0.3, 1);        /* 全站唯一出场曲线 */
    --ease-in:  cubic-bezier(0.4, 0, 1, 1);
    --ease-standard: cubic-bezier(0.4, 0, 0.2, 1);    /* 状态变化 */
    --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1); /* 仅 scale 弹跳 */
  }
  /* 示例：按钮 */
  button {
    transition:
      background-color var(--dur-fast) var(--ease-out),
      border-color var(--dur-fast) var(--ease-out),
      color var(--dur-fast) var(--ease-out),
      transform var(--dur-instant) var(--ease-out);
  }
  ```
  逐一替换 15+ 处 `transition:all`（.task/.panel/.nav-item/.insight/.log-item/.upload-file-button…），hover 位移统一 -1px（行内）/-2px（卡片），时长统一 220ms。

### P1-3 列表动效：stagger 入场 + FLIP 保位 + 完成动画 + 骨架屏

- **问题**：app.js:379 每次 render 整表 innerHTML 重建，行增删零过渡、无 FLIP、无 stagger；.task.done 渐变从不播放；骨架屏/shimmer 全文件 0 处；唯一加载指示是退出屏 spinner。
- **方案**：
  - **stagger 入场**：渲染时每行设 `--i`，CSS 动画 `taskIn 260ms var(--ease-out) both; animation-delay: calc(var(--i) * 28ms)`（i≥8 截断）。
  - **FLIP**：重建前记录每行 getBoundingClientRect()，重建后反向 translate(dx,dy)，rAF 后清除并让 transform 200ms 过渡（封装 helper 供 app.js:379/:1392 复用）。
  - **完成动效**：勾选加 .done：`border-left-color + background 300ms var(--ease-standard)`；checkbox 换自定义勾选框做 `scale(1→1.15→1) 240ms var(--ease-spring)`（原生 accent-color 无法动画）。
  - **骨架屏**：首次 load 渲染 3 行骨架 + shimmer：
    ```css
    .skeleton { background: linear-gradient(100deg,#f5f8ff 40%,#e8edff 50%,#f5f8ff 60%);
                background-size:200% 100%; animation: shimmer 1.6s linear infinite; border-radius: var(--r-md); }
    @keyframes shimmer { to { background-position: -200% 0; } }
    ```
  - **空态**：「还没有任务」占位加 fadeIn 300ms + 图标 2.4s 呼吸（scale 1→1.06）。

### P1-4 页面/弹窗进出场完整化

- **问题**：切页只有 pageIn 入场（0.4s），旧页瞬间消失；弹窗关闭直接 display:none（app.js:117/156/175），有入场无退场。
- **方案**：
  - pageIn 收紧为 320ms var(--ease-out)、位移 10px→8px；切页前给旧页加 `.page-leaving`（`pageOut 150ms var(--ease-in) both`，opacity 1→0），animationend 后交换 class；或直接用 View Transitions API（`document.startViewTransition`）。
  - 弹窗退场：overlay 150ms fade + box `scale(0.98) 150ms var(--ease-in)` 后 display:none（close 逻辑改为「加类 + transitionend 后隐藏」）。

### P1-5 层级修正 + 布局归位

- **问题**：定时器（clamp 29-37px JetBrains Mono）压过任务标题 h2（clamp 25-38px），是页面最大元素；右侧栏用绝对定位 + padding:396px 预留「留洞」，非栅格（≤1100px 时又变 static，同一页面两套布局）。
- **方案**：
  - 定时器降为次级：`font-size: clamp(22px, 2.2vw, 28px)`、`color: var(--mc-muted)`、`font-variant-numeric: tabular-nums`，标题承担视觉层级。
  - 右侧栏回归栅格：`#dashboard{grid-template-columns:minmax(0,1fr) 348px}`，删除绝对定位与 padding 预留；宽度随断点收窄 348→300→1fr。

### P1-6 实时感：状态点脉冲 + 数字计数 + sync-state 真实驱动

- **问题**：状态点是静态圆点；积分/连续/百分比直接 textContent 硬跳变；.sync-state 在 JS 中零引用，永远显示「已同步 刚刚」（写死），轮询失败被 catch{} 吞掉。
- **方案**：
  ```css
  .sync-state i, .mission-status i {
    animation: dotPulse 2.4s ease-in-out infinite;
  }
  @keyframes dotPulse { 0%,100% { opacity:1; } 50% { opacity:.55; } }  /* 只动 opacity */
  ```
  数字变化用 400ms rAF 计数滚动（一次函数 easing）；JS 真正写 .sync-state 文案与错误态。

### P1-7 prefers-reduced-motion 分层降级

- **问题**：CSS 全局 `*` 一刀切（0.01ms + iteration 1）已生效，但 JS 两处 scrollIntoView smooth（app.js:1207/1273）无守卫；一刀切也杀掉「内容浮现」类必要淡入。
- **方案**：
  ```css
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
      animation-duration: 0.01ms !important;
      animation-iteration-count: 1 !important;
      transition-duration: 0.01ms !important;
      scroll-behavior: auto !important;
    }
  }
  ```
  JS：`const rm = matchMedia('(prefers-reduced-motion: reduce)')`，scrollIntoView 的 behavior 按 rm.matches 切换；数字计数与 stagger 延迟跳过。

### P1-8 弹窗体系与无障碍基础

- **问题**：showModal/promptDlg/askEvidence 无 role/aria/焦点管理/Esc；advanced-settings-dialog 有 role=dialog 但无焦点陷阱、无初始焦点、无 Esc、背景不 inert；键盘可 Tab 逃逸；原生 window.confirm 混用 8 处（无标题、阻塞 UI）。
- **方案**：统一走自研 modal 基座（role=dialog + aria-modal + labelledby + 焦点陷阱 + 初始焦点 + Esc 关闭 + 背景 inert），危险操作加危险态样式；confirmDlg 全部替换。

---

## ④ 低优先级（P2 — 锦上添花）

1. **暗色主题二选一**（t1 M4）：接线 theme-toggle（HTML 无按钮、app.js 无任何 theme 引用、override 硬编码浅色）使 [data-theme=dark]（:156-228，token 完整）真正生效；否则删除该块避免误导。
2. **专注模式仪式感**（t2 P2-9）：body.focus-active 切换时给当前任务条加 `focusIn 320ms var(--ease-out)`（opacity 0→1 + scale 0.98→1），退出反向 200ms。
3. **死代码清理**（t2 P3-10 / t3 P2-17）：删除挂在不渲染元素上的动画（orbDrift/theme-toggle/desktop-app/ring/statusPill）与整块死功能（drawHistory 画布图表、coach 工作区、legacyRender 系列、renderPrimaryAction 空实现、不可达的 generate 分支、rules 页残留）。
4. **toast 独立化**（t3 P2-15）：toast() 现在改写 hero 内 statusPill（与状态文字互相覆盖、4s 还原）；改为独立 fixed 定位容器 + aria-live="polite"。
5. **字体加载修复**（t3 P2-20 / t1 L3）：app.css:9 @import 与 index.html:10 link 双份加载二选一；本地桌面应用建议内置/本地字体文件避免离线回退跳动；font-weight 650/750 依赖 Inter 可变轴，弱网回退时不稳定——关键元素给 600/700 档位即可。
6. **占位文本空态设计**（t1 L2 / t2 P3-11）：截图中的「???????????」、「---;---」是运行时数据兜底缺失；给空态设计占位样式（见 P1-3 空态呼吸图标）。
7. **原生对话框替换**（t3 P1-12 收尾）：window.confirm 8 处（删归档/清数据/退出/隐私提示）全改自研 modal（并入 P1-8）。
8. **按钮与图标规范**（t3 P2-21）：全站按钮补 type=button；图标 img 补 alt；反馈按钮 min-height 提至 36px+（现 26px，WCAG 目标 44px）。
9. **性能收尾**（t2 P2-7/P3-10）：进度环若恢复，过渡改 700ms var(--ease-out)、去掉 drop-shadow filter；will-change: transform 仅加给 .modal-box 与入场中的 task 行（结束后移除）；30s 全量 render 改为只 diff 任务状态；热力图月份切换补键盘可达（现仅 onwheel）。
10. **微调细节**：.primary hover 去掉 filter:brightness（paint），改背景色/阴影增强；overlay 的 backdrop-filter 保持静态不参与过渡；nav 激活指示条 inset 4px 用 box-shadow 200ms 淡入。

---

## ⑤ 设计方向愿景：如果推倒重来

> 产品叙事：**Task Verge 是一台「任务执行仪表盘」**——用户的核心动作是「专注 → 完成 → 得分」。设计系统应服务于「冷静、聚焦、可扫读」，视觉上做减法，动效上做「仪式感」，一切围绕任务完成与实时反馈。

### 5.1 配色方案（浅色主 + 深色规范）

延续「深靛蓝 + 中性灰」家族但收敛为**单一主色 + 3 语义色**，全部走 token：

| Token | 值 | 用途 |
|---|---|---|
| `--mc-canvas` | #F6F7F9 | 画布背景 |
| `--mc-panel` | #FFFFFF | 卡片/面板 |
| `--mc-border` | #E4E7EC | 全站唯一边框（hover #CDD2DA） |
| `--mc-text` | #111827 | 主文字 |
| `--mc-muted` | #667085 | 次级文字（4.6:1） |
| `--mc-primary` | #5B5CE2 | 主操作/激活态（hover #4A4BD6） |
| `--mc-primary-soft` | #EEF0FF | chip/选中底色 |
| `--mc-good` | #12805A | 完成/奖励（dim #E7F4EE） |
| `--mc-bad` | #C03131 | 失败/惩罚（dim #FBEAEA） |
| `--mc-warn` | #92600A | 警告/待处理（dim #FDF3E3） |
| 侧栏渐变 | `linear-gradient(180deg,#11151D,#0C1118)` | 保持，是当前最成功的视觉资产 |

阴影 3 档足够：`--shadow-sm: 0 1px 2px rgba(16,24,40,.04)`、`--shadow-md: 0 4px 12px rgba(16,24,40,.06)`、`--shadow-lg: 0 12px 28px rgba(16,24,40,.08)`。**层级用「白卡 + 1px 边框 + 轻阴影」表达，不堆背景色。**

### 5.2 字体

- 正文：**Inter**（可变轴 opsz 14..32 / wght 400-700），12-16px 用 400/500，标题与强调 600/700，**字距 -0.01em~-0.04em**，行高 1.5-1.6。
- 数字/计时器：**JetBrains Mono** + `font-variant-numeric: tabular-nums`（计时、积分、连续天数）。
- 字号阶梯：12 / 13 / 14 / 15 / 16 / 20 / 24 / 32 / 38（--fs-2xs…--fs-3xl，见 P1-1）。**同一屏最多 3 个大数字**：积分 38px（唯一 hero 数字）、计时 ≤28px muted、标题 24px。
- 字体加载：本地打包（桌面应用），禁止运行时依赖 Google Fonts。

### 5.3 间距与栅格

- 间距 scale：**4 的倍数** 4/8/12/16/20/24/32/48（--sp-1…--sp-12）。卡片内 padding 统一 20px（--sp-5），区块间距 24px（--sp-6），页面边距 24-28px。
- 栅格：主区 + 右侧固定 348px（<1100px 收 300px，<900px 单列）。**禁止绝对定位 + padding 预留**；所有列用 grid-template-columns 表达。
- 圆角：**6/8/10/12/999 五级**——按钮/输入 8px，卡片/面板 10px，弹窗 12px，状态 chip/胶囊 999px。单一尺度家族即高级感来源。

### 5.4 动效语言

- 时长三档 + 一档按压：**150ms**（hover/focus）· **220ms**（标准进出场/浮起）· **320ms**（页面切换/弹窗）· **90ms**（按压）。唯一出场曲线 `cubic-bezier(0.16,1,0.3,1)`（easeOutQuint 风格，快起慢收）；状态变化用 `cubic-bezier(0.4,0,0.2,1)`；scale 弹跳才用 `cubic-bezier(0.34,1.56,0.64,1)`。
- 规则：**只动 transform/opacity**（杜绝 filter/backdrop 动画）；transition 显式列属性、禁 all；位移 hover ≤2px；列表入场 stagger 28ms/行；数据变化用计数/脉冲而非跳变；所有动效在 prefers-reduced-motion 下分层降级（保留淡入、杀位移/循环）。

### 5.5 暗色主题规范

- 底色：画布 #0C1118 / 面板 #151922 / 边框 #222A36 / 文字 #E5E7EB / 次级 #9CA3AF（≥4.5:1）。
- 语义色提亮一级：good #4ADE80、bad #F87171、warn #FBBF24、primary #818CF8（400 级，深底上保证对比）。
- 阴影加深：rgba(0,0,0,.25-.6)（现有 dark 块 :218-223 已备好，接线即可）。
- 切换方式：`data-theme` 属性 + 顶部 theme-toggle（记忆 localStorage），**所有生效样式必须走 token**，硬编码 hex 清零后暗色才能成立。
- 侧栏在任何主题下保持深色（现渐变即暗色规范的一部分），实现「浅色画布 + 深色导航」的稳定框架。

### 5.6 一句话愿景

> **「白卡 + 深导航 + 靛蓝单 accent + 一套 150/220/320ms 的克制动效」**——删掉四层覆盖、删掉 45% 死代码、恢复滚动与微交互，Task Verge 就能从「企业后台模板」变成「有性格的任务驾驶舱」：视觉安静、反馈即时、完成有仪式感。
