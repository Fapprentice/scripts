# Task Verge — 动效与动画审计报告

> 历史审计快照；部分问题已经修复，当前实现以 `web/app.css` 和 `web/app.js` 为准。

审计人：motion-engineer（动效工程师）｜审计对象：D:\work_S\scripts\web\app.css（2308 行）、app.js（1687 行）、index.html + ui-mission-control-qa.png
审计标准：顶级动效设计（时长 150–300ms、一致缓动语言、微交互质感、性能、prefers-reduced-motion）

---

## 一、动画清单（位置 / 类型 / 参数 / 当前生效状态）

### CSS Keyframes（8 个）
| Keyframe | 位置 | 参数 | 使用处 | 当前状态 |
|---|---|---|---|---|
| orbDrift | app.css:285 | 20–25s ease-in-out infinite，translate±40px + scale 0.94–1.08 | .ambient-orb（:254） | **死代码** — .ambient-bg 被 display:none（:115、:1949） |
| pageIn | app.css:574 | 0.4s cubic-bezier(0.16,1,0.3,1)，opacity 0→1 + translateY(10px→0) | .page.active（:572） | **生效** — 页面切换唯一主力动效 |
| scaleIn | app.css:1794 | 0.25s bezier，scale(0.95→1)+fade | .catalog-picker（:1228，设置页选择器） | 生效 |
| fadeIn | app.css:1793 | 0.4s ease，纯 opacity | .ai-brief（:1409）、.crash-notice（:1680） | 生效（crash-notice 在设置页） |
| overlayIn | app.css:1795 | 0.22s ease / 0.4s ease | .modal-overlay（:1563）、.exit-overlay（:1601） | 生效 |
| modalIn | app.css:1796 | 0.35s / 0.5s bezier，scale(0.93)+translateY(12px)→(1,0) | .modal-box（:1572）、.exit-box（:1605） | 生效 |
| spin | app.css:1797 | 1s linear infinite | .exit-spinner（:1611） | 生效（退出屏唯一加载指示） |
| pulse | app.css:1798 | 1.6s ease-out，opacity 0.5→1→0.8 | .toast-pulse（:1619） | 半失效 — #statusPill 所在 .dash-top 被隐藏 |

### CSS Transitions（31 处，去重后 20 组）
| 分组 | 位置 | 参数 | 状态 |
|---|---|---|---|
| 通用 button/select | :353 | **all** 0.22s bezier(0.16,1,0.3,1)；:active scale(0.97) | 生效，但 hover transform 被覆盖为 none（:127、:2031） |
| 主按钮 .primary | :377-384 | filter brightness + translateY(-1px) + scale(0.97) | 生效（filter 动画 = paint 开销） |
| .nav-item | :483 | **all** 0.22s bezier | 生效（背景/文字色），transform:none（:1956） |
| .theme-toggle | :310 | **all** 0.25s bezier；hover scale(1.06)、active scale(0.94) | **死代码** — index.html 无此按钮 |
| .hero / .work-desktop | :592/:757 | box-shadow+border-color 0.3s ease | 死代码 — .dash-top display:none、.work-desktop display:none |
| #progressArc | :624 | stroke-dashoffset **1.2s** bezier + drop-shadow filter | 死代码（环被隐藏）；若恢复则 1.2s 过长 |
| #statusPill | :683 | all 0.25s ease | 死代码（被隐藏） |
| 输入类（10 处） | :711/:1004/:1025/:1072/:1140/:1239/:1286/:1493/:1583/:1694 | border-color/box-shadow 0.2s ease | 生效 — 全 app 最一致的一组 |
| .desktop-app / .desktop-app i / .desktop-dock | :817/:843/:885 | all 0.25s bezier、opacity 0.2s、all 0.2s ease | 死代码（work-desktop 隐藏） |
| .panel | :906 | all 0.3s ease | 生效（但扁平覆盖后 hover 变化极小） |
| .task | :947 | **all** 0.25s bezier；hover translateY(-1px)+shadow-md | 半生效 — transform:none（:2011），box-shadow 仍过渡 |
| .task-edit-row | :1111 | all 0.25s bezier；hover translateY(-1px) | 生效（设置页） |
| .catalog-group/.catalog-app | :1183/:1206 | all 0.25s ease；hover translateY(-1px) | 生效（设置页） |
| .time-block/.coach-msg/.action-preview | :1436 | all 0.25s bezier；hover translateY(-2px) | 生效（教练页） |
| .insight | :1454 | all 0.25s bezier；hover translateY(-2px) | 生效（教练页） |
| .log-item | :1517 | all 0.25s bezier；hover translateX(3px) | 生效（复盘弹窗） |
| .upload-file-button | :1646 | all 0.22s ease | 生效 |
| .onboarding-box b | :1630 | color 0.2s ease | 生效 |
| prefers-reduced-motion | :1939-1945 | 全局 * 动画/过渡时长 0.01ms + iteration 1 | 生效（见问题 P1-6） |

### JS 驱动动效
| 位置 | 行为 | 评价 |
|---|---|---|
| app.js:1336-1346 | 切页：classList 移除/添加 .active → 重放 pageIn | 只有入场，无出场（旧页瞬间消失） |
| app.js:117/123/156/175 | 弹窗关闭 = 直接 display:none | 无退场动画，生硬 |
| app.js:226 | toast 重触发：remove class + 强制 reflow（offsetWidth）+ add | 正确做法 |
| app.js:316/:1099 | strokeDashoffset 更新（render 时 + 每 2s refreshFg） | 1.2s 过渡在 2s 轮询下永续运动（环当前隐藏） |
| app.js:1640-1642 | setInterval：时钟 1s / refreshLive 2s / heartbeat 4s | 高频 DOM 文本写入，量小可接受 |
| app.js:1207/:1273 | scrollIntoView({behavior:'smooth'}) ×2 | 无 reduced-motion 守卫 |
| app.js:290/:1342 | body.focus-active 类切换（专注模式） | 瞬时切换，无过渡，突兀 |
| app.js:379 | taskList innerHTML 整表重建（每次 load + 每 30s 全量 render） | 行增删零过渡、无 FLIP、状态变化不播放 |

---

## 二、问题清单（严重程度 / 证据 / 为什么）

### P0-1 交付主题下主界面几乎无动效 —— 「设计系统」是 4 层覆盖堆叠，动效被逐层杀死
证据：app.css 自 :108 起连续堆叠 mission-control（:108-151）→ focus（:1293-1397）→ mission final override（:1947-2047）→ reference-faithful（:2067-2308）四套主题；`:2095 .dash-top{display:none!important}` 直接隐藏了进度环、statusPill、hero（即原系统唯一的强动效部件）；`:127/:1956/:2011/:2031` 把 button/nav-item/task 的 hover transform 全部置 none。
为什么：用户实际看到的仪表盘 = 任务卡 + 扁平任务表 + 右侧面板，唯一残留的动画只有切页 pageIn 与次级页面（教练/设置/复盘）的 hover 位移。**动效语言在最重要的界面被整体关闭**，而原玻璃拟态系统（含一致的 0.22-0.25s bezier 语言）被废弃未清理——这是"有没有动效"的根本问题，不是调参问题。

### P0-2 无运动设计令牌（motion tokens），时长/缓动东拼西凑
证据：时长 0.2/0.22/0.25/0.3/0.35/0.4/0.5/1.2/1.6s 九档；缓动混合默认 ease、ease-out、ease-in-out、linear、cubic-bezier(0.16,1,0.3,1) 五种；文件头注释声称 "Tokens preserved for JS compatibility" 但全文件 **0 个 --dur-* / --ease-* 变量**。
为什么：同一"悬停浮起"在 .task（0.25s bezier）与 .panel（0.3s ease）手感不同；hover 用默认 ease（:683/:885/:906/:1183/:1206）收尾拖沓，缺乏一致的运动语言，也无法全局统一调速（reduced-motion 只能一刀切）。

### P1-3 大量 transition: all —— 动到不该动的属性
证据：31 处 transition 中 15+ 处为 **all**（:310/:353/:483/:683/:817/:885/:906/:947/:1111/:1183/:1206/:1436/:1454/:1517/:1646）。
为什么：hover 任务行/面板时同时过渡 border-color、box-shadow、background、transform —— 全部触发 paint，在几十行任务列表上每帧重绘；且让未来新增属性自动进动画，不可控。规范做法是显式列出属性。

### P1-4 列表/任务状态零过渡：整表 innerHTML 重建 + 无 FLIP、无 stagger、无空态动效
证据：app.js:379 taskList 每次 render 整表 innerHTML 重建；render() 每 30s 全量跑一次（:1117-1119）；勾选完成 = 重建 DOM，.task.done 渐变（:955）从不播放。
为什么：任务增删/完成/重排在视觉上"闪变"，没有连续性（无 FLIP 保位），新行不进入视野（无 stagger 入场），用户无法感知数据变化路径；完成任务的仪式感（对勾弹出、行变绿）完全缺失。骨架屏/加载 shimmer 全文件 0 处（skeleton/loading grep 均为 0），唯一加载指示是退出屏的 spinner。

### P1-5 弹窗/覆盖层有入场无出场，页面切换单边动画
证据：modal close 直接 display:none（app.js:117/:156/:175）；exit-overlay 动作后 innerHTML 瞬间替换（app.js:205-219）；切页仅 .page.active 播 pageIn（app.css:572），旧页无退场。
为什么：入场 0.35s 缓动优雅，退场瞬间消失 = 视觉"卡一下"；两页切换只有新页上滑淡入、旧页消失，无交叉淡化/方向感，切页观感粗糙。

### P1-6 prefers-reduced-motion 不完整
证据：:1939 全局 * 杀时长已生效（好）；但 app.js:1207/:1273 scrollIntoView smooth 无 matchMedia 守卫；无 scroll-behavior:auto 覆盖。
为什么：偏好减少动态的用户仍会被强制平滑滚动；全局 * !important 一刀切也同时杀掉了"内容浮现"类必要淡入（0.01ms 瞬闪），不如分层降级（保留透明度过渡、杀掉位移/循环）。

### P2-7 进度环 1.2s 过渡 + filter 动画，且 2s 轮询永续运动
证据：:624 stroke-dashoffset 1.2s bezier + drop-shadow filter；JS 每 2s 更新（:1099）。
为什么：1.2s 远超数据读数类动画合理值（≤0.6s）；每 2s 更新一次意味着环永远在动（除非值不变），配合 filter 合成开销 = 持续 GPU/paint 负担。当前环被隐藏是"因祸得福"，恢复时必须改。

### P2-8 状态点全静态、数字跳变 —— 实时感缺失
证据：.sync-state i（:2086）与 .mission-status i（:2104）为静态圆点，无脉冲；积分/连续/百分比（app.js:308-313）直接 textContent 替换，无数值滚动；JS 从未更新 .sync-state（grep sync-state 0 命中，"已同步 刚刚"是写死的）。
为什么：一个宣称"实时"的执行反馈面板，绿色状态点完全静止 + 数字硬跳变，动态质感为零；这是投入最小、观感收益最大的动效点。

### P2-9 专注模式进出瞬时切换
证据：body.focus-active 类切换（app.js:290/:1342）触发 :1369-1388 的 display/grid 重排，无任何过渡。
为什么：专注模式是产品核心仪式场景，当前切换是"啪"一下重排，无缩放/淡入焦点卡片，仪式感缺失。

### P3-10 死代码与性能尾巴
证据：orbDrift/theme-toggle/desktop-app/ring/statusPill 五组动画全部挂在不渲染的元素上（.ambient-bg、.dash-top、.work-desktop display:none）；overlay 用 backdrop-filter blur(10-18px)（:1559/:1596）；.primary hover 用 filter:brightness（:377-382）；全文件 0 处 will-change。
为什么：无用动画规则 + 高成本滤镜共存 = 代码腐化与潜在性能地雷；如果未来某个覆盖层失效，隐藏的 orbDrift（120px blur 三个 600px 圆）或 blur overlay 会直接打在低端机帧率上。

### P3-11 截图观感（ui-mission-control-qa.png）
vision 分析：当前任务卡 + 任务队列 + 执行反馈面板，扁平配色，无任何可见的进行中动画痕迹；"专注中"圆点静止；数字无跳变；任务标题占位显示 "???????????"（占位态无样式处理）；右侧面板拥挤、导航图标对比度弱、任务名与按钮重叠截断。
结论：真实界面上动效缺席可被直接感知——状态点/数字/列表都是"死"的；占位文本说明空态/加载态设计未覆盖，与 P1-4 呼应。

---

## 三、顶级动效改进方案（可直接落地的数值）

### 1. 建立运动令牌（消除 P0-2）
在 :root 追加：
[code]
:root{
  --dur-instant: 90ms;   /* 按压反馈 */
  --dur-fast:   150ms;   /* hover / focus / 小属性 */
  --dur-base:   220ms;   /* 标准进出场、卡片浮起 */
  --dur-slow:   320ms;   /* 页面切换、弹窗 */
  --ease-out:    cubic-bezier(0.16, 1, 0.3, 1);   /* 全 app 唯一出场曲线 */
  --ease-in:     cubic-bezier(0.4, 0, 1, 1);
  --ease-standard:cubic-bezier(0.4, 0, 0.2, 1);   /* 双向/状态变化 */
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1); /* 仅用于 scale 弹跳 */
}
[/code]
并删除 :108-151 与 :1947-2047 两层重复覆盖（保留 reference-faithful 一套 + 顶部的令牌/组件层），消灭"覆盖杀动效"。

### 2. 微交互逐项数值（消除 P1-3 与 hover 不一致）
- **button/select**：transition 改为显式属性：background-color/border-color/color 各 150ms var(--ease-out)，transform 90ms var(--ease-out)；:active scale(0.97) 用 --dur-instant。
- **.primary**：hover 保留 translateY(-1px)，transform 220ms var(--ease-out)；**去掉 filter:brightness**（paint），改用背景色/阴影增强。
- **.nav-item**：background-color/color 150ms；active 指示条 inset 4px 用 box-shadow 200ms 淡入，不加位移。
- **.task 行**：恢复 hover 浮起——transform translateY(-1px) 200ms var(--ease-out)、border-color 150ms、box-shadow 200ms（显式属性，禁 all）；任务表内行 hover 只做背景 150ms + 左侧色条，避免每行 box-shadow 闪烁。
- **卡片（panel/insight/log-item）**：统一 220ms var(--ease-out)，位移统一 -2px；log-item 的 translateX(3px) 改 translateX(2px) 保持一致。

### 3. 页面切换：入场收紧 + 出场（消除 P1-5）
- pageIn 改为 320ms var(--ease-out)，位移 10px→8px。
- 切页前给旧页加 .page-leaving（animation: pageOut 150ms var(--ease-in) both，opacity 1→0），animationend 后再交换 class；或直接用 View Transitions API（document.startViewTransition），跨页自动交叉淡化。
- 弹窗退场：overlay 150ms + box scale(0.98) 150ms var(--ease-in) 后 display:none（close 逻辑从"直接隐藏"改为"加类 + transitionend 后隐藏"，改 app.js:117/:156/:175）。

### 4. 列表动效：FLIP + stagger 入场 + 完成动画（消除 P1-4）
- **stagger 入场**：渲染时每行设置 --i 索引，CSS：animation: taskIn 260ms var(--ease-out) both; animation-delay: calc(var(--i) * 28ms)；@keyframes taskIn { from { opacity:0; transform: translateY(6px) } }（i≥8 不再延迟）。
- **FLIP 保位**：innerHTML 重建前记录每行 getBoundingClientRect()，重建后反向 apply translate(dx,dy)，rAF 后清除并让 transform 200ms 过渡（封装 helper 供 app.js:379/:1392 使用）。
- **完成动效**：勾选时行加 .done：border-left-color + background 300ms var(--ease-standard)；checkbox 换自定义圆角勾选框（原生 accent-color 无法动画）做 scale(1→1.15→1) 240ms var(--ease-spring)。
- **空态**："还没有任务"占位加 fadeIn 300ms + 图标 2.4s 呼吸（scale 1→1.06，transform-origin center）。

### 5. 加载/骨架屏（消除 P1-4 空窗）
- .generation-status（生成最长 5 分钟）加 shimmer：background: linear-gradient(100deg, #f5f8ff 40%, #e8edff 50%, #f5f8ff 60%); background-size: 200% 100%; animation: shimmer 1.4s linear infinite。
- 首次 load 时 taskList 渲染 3 行骨架（灰块 + shimmer 1.6s），数据到达后换真实行（配合 stagger）。
- 退出屏 spinner 0.8s 旋转（更快进入注意）。

### 6. 实时感：状态点 + 数字（消除 P2-8）
- .sync-state i, .mission-status i { animation: dotPulse 2.4s ease-in-out infinite }，keyframes 只动 opacity .55→1（不缩放、不动 layout）。
- 数字（积分/连续/百分比）变化时用 400ms rAF 计数滚动（一次函数 easing）。
- JS 真正驱动 .sync-state 文案（目前写死"刚刚"）。

### 7. 专注模式仪式化（消除 P2-9）
- body.focus-active 切换时给 .current-task-bar 加 animation: focusIn 320ms var(--ease-out)（opacity 0→1 + scale 0.98→1），退出反向 200ms。

### 8. prefers-reduced-motion 分层降级（消除 P1-6）
[code]
@media (prefers-reduced-motion: reduce){
  *, *::before, *::after{
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
[/code]
JS 侧：const rm = matchMedia('(prefers-reduced-motion: reduce)')；两处 scrollIntoView 的 behavior 改为 rm.matches ? 'auto' : 'smooth'；数字计数与 stagger 延迟跳过。

### 9. 性能收尾（消除 P2-7 / P3-10）
- 全部 transition:all 改显式属性（见第 2 节）；will-change: transform 仅加给 .modal-box、.ring、入场中的 task 行（动画结束后移除）。
- 进度环若恢复：过渡改 700ms var(--ease-out)，去掉 drop-shadow filter 或改为静态。
- overlay 的 backdrop-filter 保持静态不参与过渡；删除 .ambient-bg / .theme-toggle / .desktop-app / .work-desktop 全部死规则与对应 keyframes。
- setInterval 时钟保留（1s 文本写入可忽略）；refreshLive 2s 轮询保留，但 30s 全量 render 改为只 diff 任务状态（或改用推送，彻底免轮询）。

---

## 四、优先级建议
1. **先做**：motion tokens + 显式 transition（P0-2/P1-3）—— 一次重构消除不一致与 paint 浪费。
2. **再做**：taskList FLIP + stagger + 完成动画 + 骨架 shimmer（P1-4）—— 用户感知最直接的提升。
3. **随后**：页面/弹窗退场（P1-5）、状态点脉冲 + 数字滚动（P2-8）、reduced-motion 补全（P1-6）。
4. **最后**：清理 4 层覆盖与死代码（P3-10）、专注模式仪式感（P2-9）、进度环参数（P2-7）。

一句话结论：**Task Verge 有一套参数正确的"骨架"（bezier(0.16,1,0.3,1) 与 transform/opacity 关键帧都选对了），但被四层主题覆盖压死在交付界面之外；当务之急不是新增炫技，而是统一令牌、恢复被禁用的微交互、并给列表与加载态补齐连续性动效。**
