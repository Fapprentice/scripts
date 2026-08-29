# 大肥鱼养成规则（历史设计规格）

> 给实现（t3）与测试（t4）的产品规格。对照 `companion-seams.md`。不改 `acceptance.py`，不把 `motivation.points` 映射为精力。
>
> 交付：状态机、数值表、可玩动作、挂钩、UI 文案。短时演出与持久状态分离。无背包、无商城、无等级。

> **当前状态（2026-08-29）**：本文是陪伴功能落地前的 t2 设计快照。后续实现已增加 XP、等级/阶段、饥饿、生命和 spend 动作；戳/喂/说话也已通过 `CompanionService` 持久化。当前行为以 `CONTEXT.md`、`CODE_WIKI.md` 和 `companion_service.py` 为准；本文只保留设计决策与约束的历史记录。

---

## 0. 硬约束（实现不得破）

1. **SQLite 是唯一真源**。精力 / 默契 / 日计数 / 养成事件必须落在库内；刷新、重启、restore 后仍在。`documents.payload` 若快照，须与关系表同事务。
2. **不削弱验收**：路径可挂回调，成功标准、无证据不得通过、补救不改写 `acceptance` 原文，一律不变。
3. **积分 ≠ 精力**：禁止读写 `motivation.points` / `OUTCOME_POINTS`。跳过 -5、失败 -3 已是执行反馈，不得再映射到宠物。
4. **`needs_review` 零成长**：不写养成事件、不改 energy/bond、不庆祝、不打气演出、不标 done。
5. **一只全局鱼**：每安装一份一只「大肥鱼」，不跟目标走。切换目标不重置默契。
6. **无惩罚循环**：失败 / 跳过 / 部分完成 / 分心关窗 / 暂停 **不扣** energy、不扣 bond。衰减是「沉降到日常」，不是死亡或饿死。
7. **无背包 / 商城 / 等级 / 进化 / 经验条**。三种零食是口味按钮，不是库存物品。
8. **日上限与拒绝在 CompanionService**，不在前端。前端可预禁用，但跳过前端仍须被后端拒绝且不涨。
9. **休息回血只认用户/陪伴发起的 `/api/break`**。`quit` / `continue_15` 塞入的 15 分钟 break 不涨养成。
10. **陪伴按钮不能一键完成任务**。完成只经验收。

### 0.1 t1 硬约束清单（必须原样遵守）

t1 `companion-seams.md` 已 pass。实现（t3）与测试（t4）按下表核对，不得弱化。

| # | 硬约束 | 本规格落点 |
|---|---|---|
| 1 | **戳 / 喂 / 说话目前纯内存，必须变成 `companion-event` 写库。** 今日 `playCompanion` 只改 `companionPlay`；v2 必须 `POST /api/companion-event`（kind=`poke`/`feed`/`talk`）由 CompanionService 写 SQLite 陪伴行 + 养成账本，再返回 `play_hint` 给前端播动画。只改前端却画精力条视为违规。 | §2、§4.1、§6 |
| 2 | **不得把 `motivation.points`（`accepted +10` / `partial +2` / `skipped -5` / `failed -3`）映射为精力。** 积分账本已含负分，是执行反馈不是宠物生命值。energy/bond 独立字段、独立事件。 | §0.3、§4、§8 |
| 3 | **`needs_review` 不涨养成、不记 outcome。** 不写养成事件、不改 energy/bond、不庆祝、不打气。与现 `persist_result` 不调 `record_outcome` 对齐；反复提交仍不涨。 | §4.2、§5.1 |
| 4 | **验收挂钩 `persist_result`，养成写入必须与 `evaluate_task` 同一次 `sc()` / 同事务（R1）。** `persist_result` 的 save 是 `save_goal_state` 不写盘；只挂回调却不 `sc()` 会丢成长。不要改 `acceptance.py` 判定。 | §5.1、§9 |
| 5 | **休息沿用 `/api/break` 日限 3，不要另做一套惩罚循环。** 陪伴休息按钮转发现有 break widget；失败/跳过/暂停/分心关窗不扣 energy/bond。`quit`/`continue_15` 的 15 分钟 break 不涨。 | §4.1、§5.3、§0.6 |
| 6 | **先能量 + 默契 + 心情 + 事件账本，不上背包 / 商城。** 三种零食是口味按钮不是库存。无金币、掉落、进化、等级。 | §4.1、§6.2、§8 |

**短时演出与持久状态分开（t1 强制）：** poke/feed/talk 动画（1.2s/1.8s/2.2s，刷新可丢）≠ 持久 energy/bond（SQLite 真源，刷新/重启/restore 必须还在）。

---

## 1. 词汇（与 `CONTEXT.md` 对齐）

| 术语 | 含义 | 不要叫 |
|---|---|---|
| 陪伴 | 全局一只大肥鱼，旁路回应执行 | 宠物养成游戏、积分宠物 |
| 精力 Energy | 0–100 的当下精神，独立字段 | 生命、HP、积分、体力门票 |
| 默契 Bond | 0–100 的熟悉程度，一起做事才涨 | 等级、经验、Lv、进化 |
| 心情 Mood | **推导值**，不是第三根可刷条 | 永久性格、隐藏等级 |
| 陪伴演出 Play | 1.2–2.5s 动画 / 台词 / 表情，刷新可丢 | 持久心情、已存等级 |
| 养成事件 | 独立账本里一条可解释 delta | `events[-300:]`、`POST /api/event` |
| 沉降 Settle | 精力慢慢回到日常水位 50 | 扣血、惩罚、遗忘 |

默契展示只用四段**称呼**，禁止 Lv：

| bond | 称呼 `bond_band` |
|---|---|
| 0–19 | 刚认识 |
| 20–49 | 慢慢熟 |
| 50–79 | 搭档 |
| 80–100 | 很熟 |

---

## 2. 两层状态：演出 ≠ 真源

```
[用户动作 / 验收 / 专注 / 休息]
        │
        ▼
 CompanionService.apply(kind, payload)     ← 日上限、冷却、去重、沉降、clamp
        │
        ├─ 持久：energy, bond, 日计数, 冷却时刻, companion_events 行
        │         经 /api/state.companion 下发；刷新后仍在
        │
        └─ 演出提示 play_hint {kind, treat?, emote?, ms}
                  前端 playCompanion(...) 播放
                  到期或刷新即回到「基础心情」
```

| | 短时演出 | 持久状态 |
|---|---|---|
| 存哪 | 仅 `companionPlay` 内存 | SQLite 陪伴行 + 养成账本 |
| 刷新 | 丢失 | 必须还在 |
| 例子 | 戳的 💢、喂的 🐟、1.2s side 图 | energy=76, bond=23, 今日喂 2/3 |
| UI | 覆盖 moodLabel 为 被戳/进食/碎碎念 | 条、剩余次数、`bond_band`、基础心情 |
| 真源 | 否 | 是 |

规则：**有条必须来自 `/api/state.companion`**。禁止只改前端却画持久精力条。

演出时长（沿用现 UI，不换立绘文件）：

| 演出 | ms | 表情 | 姿势（现有 PNG） |
|---|---|---|---|
| poke | 1200 | 💢 | side |
| feed | 1800 | 🐟 / 🍰 / 🍭 | front |
| talk | 2200 | 💬 | front |
| celebrate / accepted | 2500 | ✨ | front |
| cheer（失败/跳过，无数值） | 2000 | 💪 | front |
| rest overlay | 随休息时段 | （无强制） | back |

演出在日上限用尽后 **仍可播放**（可玩），但 **delta=0 且不写涨幅**。用尽文案见 §7。`needs_review` 连演出提示也不发。

---

## 3. 属性与沉降

### 3.1 范围与默认（v1→v2 迁移建默认行）

| 字段 | 最小 | 最大 | 新安装 / 迁移默认 | 沉降地板 |
|---|---|---|---|---|
| energy | 0 | 100 | **70** | 衰减永不低于 **20** |
| bond | 0 | 100 | **20**（慢慢熟） | **不因时间/失败衰减** |
| mood | （推导） | — | idle / 待机 | — |

整数 delta，写入后 clamp 到 0–100。energy=0 只可能被错误写入；UI 与结算都按「没死」处理，禁止死亡/饿死文案。

### 3.2 精力沉降（衰减，非惩罚）

日常水位 **rest_point = 50**。

在每次 `apply` 开头、以及读快照时先跑 `settle(now)`：

| 条件 | 公式 | 不触发 |
|---|---|---|
| 当前任务 `doing` | **冻结**，不沉降 | — |
| `break_active`（休息进行中） | **冻结** | — |
| energy > 50，距上次结算 ≥ 2 小时 | 每满 2h：energy -= 2，**不低于 50** | 专注中、休息中 |
| 距上次「用户休息开始」与「成功喂食」都 ≥ 18h，且非专注/休息 | 每满 3h：energy -= 1，**不低于 20** | 同上；失败/跳过/分心 **不**加速 |

一次 settle 按已过完整间隔补扣，写回 `last_settle_at`。UI 若展示变化，只用「精力慢慢回到日常」，**禁止**「你被扣了」。

默契：**无时间衰减、无失败衰减、无分心衰减**。封顶 100。长期不上线只可能让精力走低、心情偏困，默契数字不变。

### 3.3 心情状态机（基础心情，持久层推导）

心情 **不存独立可刷分**。快照每次按优先级取第一条（高优先在上）：

```
doing?                         → focus / 专注中
break_active?                  → rest / 休息中
energy < 28 且非上面两条?       → idle + 文案「困了」（仍用 front 图，不新增美术）
2h 内有 accepted/celebrate 事件? → happy / 开心
2h 内最近工作结果是 failed|skipped，且之后无 accepted?
                               → cheer / 打气
有下一件未完成任务?             → idle / 待命
无目标契约?                    → idle / 待机
否则                           → idle / 待机
```

演出层（前端未到期）可把显示 mood 换成 poke/feed/talk/happy，到期回到上表。

**禁止**用 `motivation.streak` 当默契，也禁止「连续 5 次 = 升级」。streak 仍只出现在执行反馈面板。

---

## 4. 数值表

日界：与 `breaks[].date` **同一本地日历日**。日计数在日界清零（计数清零，energy/bond 不清零）。

冷却单位：秒。日上限 0 表示「不按日限次」（仍可能去重）。

### 4.1 可玩动作（用户可点）

| kind | 入口 | 日上限 | 冷却 | Δenergy | Δbond | 去重键 | 演出 |
|---|---|---|---|---|---|---|---|
| `poke` | 立绘舞台 | **8** | **20s** | 0 | 当日第 1–3 次 **+1**，第 4–8 次 **0** | 每次独立；超限仍可演、delta=0 | poke 1.2s |
| `feed` + 小鱼干 | 零食按钮 | **3**（三种零食**共用**） | **600s** | **+8** | **+2** | 超限 delta=0 | feed 1.8s 🐟 |
| `feed` + 蛋糕 | 同上 | 同上共用 3 | 同上 | **+5** | **+1** | 同上 | 🍰 |
| `feed` + 棒棒糖 | 同上 | 同上共用 3 | 同上 | **+4** | **+1** | 同上 | 🍭 |
| `talk` | 说句话 | **6** | **30s** | 0 | 当日第 1–4 次 **+1**，第 5–6 次 **0** | 超限 delta=0 | talk 2.2s |
| `celebrate` | 开心时「庆祝一下」 | 每条验收通过 **1** | 无 | 0（通过已入账则不再加） | 0（同上） | `celebrate:<acceptance_id>` | happy 2.5s ✨ |
| `rest` | 陪伴「休息一下」→ 现有 `/api/break` | **沿用休息 3 次/日** | 无额外 | 见 §5.3 | 见 §5.3 | `rest:<break.ts>` | mood=rest |

喂食：未知 `treat` → 拒绝，不写账。无库存字段。三种只是口味，小鱼干略优是角色食物，不是稀有度。

戳 / 说在上限内后段 Δbond=0：仍算「今日互动」，用于挡住无意义连点，但动画还在。

### 4.2 工作挂钩（用户不直接点养成，走现有 API）

| kind | 触发 | 日上限 | Δenergy | Δbond | 去重键 | 心情 |
|---|---|---|---|---|---|---|
| `focus_start` | `TaskService.set_status` **成功**变为 `doing` | 每 `task_id` 每个本地日 **1** | **0**（不收专注税） | **+3** | `focus:<task_id>:<date>` | 基础心情=focus |
| `focus_pause` | 成功变为 `paused` | — | **0** | **0** | 不写涨幅；可不写账或写 delta=0 | 回推导 |
| `rest_start` | `POST /api/break` 且来源为用户/陪伴（见 §5.3） | 休息 3 次 | **+6** | 0 | `rest_start:<break.ts>` | rest |
| `rest_end` | `POST /api/break-end`，对应休息已记 `rest_start` | — | 实际休息 **≥4 分钟 +4**，否则 **0** | 实际休息 **≥5 分钟 +1**，否则 **0** | `rest_end:<break.ts>` | 回推导 |
| `accepted` | `persist_result` 且 status=`passed`（含手动通过） | 每 acceptance 身份 **1** | **+6** | **+8** | `accepted:<acceptance_id>` | happy + 庆祝演出 |
| `failed` | `persist_result` 且 `failed` | 每 acceptance 身份 **1** | **0** | **0** | `failed:<acceptance_id>` | cheer 演出；**必须写账说明「养成不变」** |
| `needs_review` | `persist_result` 且 `needs_review` | — | **不调用养成** | **不调用** | **无事件** | **不改** |
| `skipped` / `partial` | `set_status` 记入积分时 | 每次状态变化至多 1（与积分去重同口径） | **0** | **0** | `status:<task_id>:<status>:<date>` | cheer；可写 delta=0 账 |
| `recover` | 陪伴「开始补救」→ `/api/recovery` | — | 0 | 0 | 不因补救插入本身涨；随后 `doing` 走 `focus_start` | — |

`acceptance_id`：能稳定标识这一次验收结果即可（任务 id + 结果时间戳，或 `acceptance_runs` 主键）。同一 run 重放不连加。

**专注时长不换算默契。** 5 分钟与 50 分钟的 `focus_start` 都是 +3，且每日每任务一次。`actual_seconds` 只属于任务计时。

**分心守卫 `focus_*` 次数不入养成。**

### 4.3 日增益天花板（由上表自然形成，实现按动作限次即可）

| 来源 | 理论日上限（未 clamp） |
|---|---|
| 玩：poke 默契 | +3 |
| 玩：talk 默契 | +4 |
| 玩：feed 默契 | 最多 +6（三次小鱼干） |
| 玩：精力 | 三次小鱼干 +24 |
| 休息：精力 | 最多 3×(6+4)=+30 |
| 休息：默契 | 最多 +3 |
| 专注 / 验收 | **不另设日封顶**（真实工作）；总 clamp 100 |

不要再加「今日默契已满」挡住验收加成。

### 4.4 冷却与超限时的返回（服务端）

成功涨：`{ok:true, applied:true, delta_energy, delta_bond, snapshot, play_hint, reason}`

超限 / 冷却中：`{ok:true, applied:false, delta_energy:0, delta_bond:0, snapshot, play_hint 仍可给, reason}`  
HTTP 仍 200（可玩），**不要 500**。非法 treat、未知 kind：4xx，无账。

目标未就绪导致 `doing` 被拒：**不**记 `focus_start`。

---

## 5. 挂钩细则

### 5.1 验收（旁路，不改判定）

插入点：`AcceptanceService.persist_result` 在结果规范化之后、`save` 之前的可选回调。`evaluate_task` 必须让验收与养成 **同一次 `sc()` / 同事务**（接缝风险 R1）。

| 验收 status | 养成 |
|---|---|
| `passed` | `accepted`：energy+6, bond+8，庆祝演出。手动 `/api/manual-accept` 同样（它已走 persist_result）。 |
| `failed` | `failed`：0/0，cheer 演出，账本 reason=「验收没过，养成不扣，先补证据」。补救任务插入 **不**再加一笔。 |
| `needs_review` | **return 提前**：不回调或回调内直接 no-op。无事件、无 play_hint、无条变化。反复提交仍不涨。 |

禁止：把 needs_review 显示成开心或失败打气。禁止庆祝按钮在 needs_review 后出现。

### 5.2 专注

- 只在 `set_status` **成功**且新状态为 `doing` 时 `focus_start`。
- `paused`：0/0，不惩罚。
- 不得把 `focus_sessions` 死表当会话真源。
- 陪伴「开始专注」继续 `POST /api/task-state`，不平行实现一套专注。

### 5.3 休息

继续现有 `/api/break`（1–60 分，当日 ≥3 则 400）与 `/api/break-end`。陪伴按钮只转发现有控件。

**记养成的休息**须同时：

1. 来源是用户点「休息一下」/ `#quickStartBreak` / 教练明确休息动作；
2. **不是** `quit` / `quit_continue` / `continue_15` 写入的 break。

过滤建议：仅当 `reason` 不含退出仪式标记，或显式 `source=user|companion|coach_rest`。设计不锁定字段名，测试必须覆盖「退出续 15 分钟不涨精力」。

`rest_end` 的分钟数用 `until - ts` 与 `ended=true`，提前结束不到 4 分钟则没有 +4 精力（开始那 +6 保留，鼓励真的歇一下，而不是惩罚早归）。

### 5.4 补救两条线（禁止双计）

| 线 | API | 养成 |
|---|---|---|
| 验收失败插入 `source=remediation` | persist_result 内部 | 只记 `failed` 那一笔 0/0 |
| 陪伴保底 `role=recovery` | `/api/recovery` | 插入不涨；用户对其 `doing` 才可能 `focus_start` |

---

## 6. 养成事件与快照（给实现的契约，非表名锁定）

### 6.1 事件行（独立表，不挤 `events[-300:]`）

`id, ts, kind, treat, delta_energy, delta_bond, reason, task_id, goal_id, dedupe_key, source`

`reason` 必须人类可读，例如：

- 「戳了一下，默契 +1」
- 「今天戳得够多了，养成到此为止（动画还能看）」
- 「喂了小鱼干，精力 +8，默契 +2」
- 「开始专注当前任务，默契 +3」
- 「验收通过，精力 +6，默契 +8」
- 「验收没过，养成不变，只打气」
- 「这次还要复核，不记养成」—— **此句只可出现在日志/调试，不写表**（因为根本不插行）
- 「用户休息开始，精力 +6」
- 「休息结束满 5 分钟，精力 +4，默契 +1」

### 6.2 `GET /api/state` 附加 `companion`（不替换现有键）

```json
{
  "id": "dafeiyu",
  "name": "大肥鱼",
  "energy": 76,
  "bond": 23,
  "energy_max": 100,
  "bond_max": 100,
  "mood": "idle",
  "mood_label": "待命",
  "bond_band": "慢慢熟",
  "today": {
    "date": "2026-04-08",
    "poke_used": 1, "poke_limit": 8,
    "feed_used": 0, "feed_limit": 3,
    "talk_used": 0, "talk_limit": 6,
    "rest_used": 0, "rest_limit": 3
  },
  "cooldowns": { "poke_until": null, "feed_until": null, "talk_until": null },
  "last_event": {
    "kind": "poke",
    "reason": "戳了一下，默契 +1",
    "delta_energy": 0,
    "delta_bond": 1,
    "ts": "..."
  }
}
```

**禁止字段：** `level`, `xp`, `exp`, `points`, `inventory`, `coins`, `hp`, `dead`。

建议另有 `POST /api/companion-event` 处理 poke/feed/talk/celebrate；focus/rest/验收走现有 API 旁路，不强迫前端为专注再打一枪养成接口。

---

## 7. UI 文案

语气保持现有毒舌护短。全部可直接用。

### 7.1 条与提示（新增，勿暗示等级）

| 位置 | 文案 |
|---|---|
| 精力标签 | 精力 |
| 精力 hint | 现在还精神不精神，不是积分。 |
| 默契标签 | 默契 |
| 默契 hint | 一起做事才会熟，不是经验等级。 |
| 小节标题 | 专注伙伴（沿用，不要改成「宠物养成 Lv」） |
| 剩余次数 | 今日还可戳 {n} 次 / 零食 {n}/3 / 说句话 {n} 次 |

### 7.2 超限 / 冷却（Toast 或 line，不禁用到无反馈）

| 情况 | 文案 |
|---|---|
| 戳满 | 今天戳够了。动画还能看，养成到此为止。 |
| 戳冷却 | 等一下再戳。我又不会跑。 |
| 喂满 | 零食今日额度用完了。不是没库存，是今天喂够了。 |
| 喂冷却 | 还在嚼。过几分钟再喂。 |
| 说满 | 今天话够多了。去干活，我看着。 |
| 说冷却 | 让我想想下句毒舌…… |
| 庆祝但无最近通过 | 过了再庆祝。没有证据的开心，我不认。 |
| 休息已 3 次 | 沿用现有 break 400 文案；不要说「精力买完了」 |

### 7.3 基础心情 line（持久层，替换会暗示等级的句子）

现有 `companionSnapshot` 里「连续完成 N 次」可保留在 **执行反馈**，陪伴 line 改为不谈升级：

| mood | mood_label | line（持久） |
|---|---|---|
| idle 无任务 | 待机 | 还没有进行中的任务时，我会在这里等你开始。 |
| idle 有下一件 | 待命 | 待开始：{任务}。开始专注我会记一笔默契。 |
| idle 无目标 | 待机 | 去设置页补全最终成果和成功标准，我才能跟着验收。 |
| idle 困了 | 困了 | 有点困，不是生气。休息或吃点东西就好。 |
| focus | 专注中 | 正在做：{任务}。提交可检查结果后我会高兴——标准不会因此变松。 |
| rest | 休息中 | 休息不是逃。缓完从最小可执行步骤接着做。 |
| happy | 开心 | 这下对上了。默契涨了，成功标准没降。 |
| cheer | 打气 | 没过也别散。养成没扣，先补一个可验证的小动作。 |

### 7.4 演出台词（可继续用现 `COMPANION_LINES`，补庆祝 / 失败）

沿用 poke / feed / talk / focus / rest。新增：

**celebrate**

- 过了就过了，别让我再核一次。
- 证据齐了才许开心。
- 默契涨一点。标准还是那些。

**cheer（失败，无数值）**

- 先做最小一步。
- 没过也别散，拆小一点。
- 证据不够就补证据。养成没扣你的。

**needs_review**（仅 Toast，鱼不庆祝不哭）

- 这次还要复核，大肥鱼先不庆祝。

禁止出现：升级、进化、经验、商城、库存不足、饿死、扣血、失败-3 精力、用积分喂鱼。

### 7.5 主按钮（不新增流程，只在开心态加庆祝）

| 情境 | primary | secondary |
|---|---|---|
| 有下一件 | 开始专注 | 休息一下 |
| 专注中 | 提交验收 | 暂停一下 |
| 休息中 | 结束休息 | （隐藏开始专注） |
| 最近通过且 2h 内 | 庆祝一下（`celebrate`）或 开始下一件 | 休息一下 |
| 最近失败/跳过 | 开始补救（现有 recover） | 休息一下 |
| 无目标 | 去补全目标 | （隐藏休息） |

「庆祝一下」在已为该次验收写过 `accepted` 时 **只演戏、不再加数值**（`applied:false` 或 celebrate 去重）。不要做第二个通过按钮。

---

## 8. 明确不做

- 改 `acceptance.py` / 放宽无证据通过 / 补救改写验收原文
- `motivation.points` → energy
- 背包、掉落、商城、金币、抽卡
- 多宠物、换皮付费、进化形态（不替换 `web/pets/dafeiyu` PNG）
- 用 `POST /api/event` 记养成
- 把陪伴挂进 `user_model`（会随目标切换清掉）
- 专注秒数换默契、关窗次数扣默契
- 失败扣精力、连续失败死亡、过夜清零默契
- 前端自己加日上限而不打后端

---

## 9. 实现要点（给 t3，不锁文件内代码）

1. schema v2：默认陪伴行；打开 v1 先 pre-migration 备份；任务数据不变。
2. 新表不要进现有无重建的 `DELETE` 投影列表。
3. `/api/state.companion` 附加键；poke/feed/talk 改走后端后再播演出。
4. 验收回调 + `evaluate_task` 补 `sc()`（R1）。
5. `CODE_WIKI.md` 删除「不持久化精力或默契」。
6. 日上限测试不可 skip。

建议测试向量（t4）：

| id | 断言 |
|---|---|
| T-NR | needs_review 前后 energy/bond 相同，账本无新行 |
| T-FAIL | failed：0/0，有 delta=0 行，motivation 仍按原规则 -3，互不改写 |
| T-OK | passed：+6/+8 一次；重放同一 run 不再加 |
| T-POKE | 第 1–3 次 bond+1；第 4–8 次 0；第 9 次 applied=false |
| T-FEED | 三种零食共用 3；第四次不涨；无 inventory 字段 |
| T-FOCUS | doing 成功 +3；同任务同日再 doing 0；目标未就绪 0 |
| T-REST | 用户休息 +6，满 5 分钟结束 +4/+1；quit-continue 0 |
| T-SETTLE | 空闲 2h 且 energy>50 → 向 50 靠；失败不加速沉降 |
| T-RESTORE | restore / 完整导入后 energy/bond/账本仍在 |
| T-POINTS | 任意养成动作后 `motivation.points` 不变（除非该动作本身是验收/跳过等原有账本事件） |

---

## 10. 验收对照（本设计）

| 标准 | 落点 |
|---|---|
| energy/bond/mood 与每日上限、冷却、衰减数值表 | §3、§4 |
| 验收通过/失败/needs_review、开始专注、休息如何影响；needs_review 不涨 | §4.2、§5.1–5.3 |
| 至少戳、喂（三种零食）、说话、庆祝、休息；无背包商城 | §4.1、§8 |
| UI 文案不暗示未实现持久等级或惩罚循环 | §7 |

本文件是 t2 历史规格，不是当前实现契约。当前实现以 `CONTEXT.md`、`CODE_WIKI.md`、`companion_service.py` 和测试为准。
