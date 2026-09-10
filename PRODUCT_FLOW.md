# Task Verge 完整产品闭环

本文件是产品行为规范，也是实现验收清单。核心原则：任务路径和颗粒度可以调整，最终目标与验收标准不能因主观反馈自动降低。

| 环节 | 成熟方案 | 当前实现与证据 |
|---|---|---|
| 1. 设定目标 | 一个目标对应独立定义、状态、任务和用户模型 | 设置页目标卡片与详情面板；`norm_goals`、`ensure_goal_state` |
| 2. 澄清目标 | 明确最终成果、期限、当前基础和现实约束；只追问缺失信息 | 每个目标的详情面板；`goal_details`、`goal_readiness` |
| 3. 建立标准 | 成功标准使用多条可核验条件，生成任务不得覆盖 | `success_criteria` 持久化并进入生成提示 |
| 4. 制定计划 | 根据里程碑、历史复盘、未完成项、容量生成阶段策略；学习型目标使用“技能节点 → 节点任务 → 阶段任务 → 最终成果任务”的分层计划 | 当前实现以 `plan_learning_tasks`、`SkillMap.load` 为基础；分层模型详见 `docs/STAGED_LEARNING_SPEC.md` |
| 5. 生成任务 | 节点任务只有一个主技能；阶段任务只能实例化版本化 Skill Pack 的合法组合；最终成果任务逐成功标准收集证据；地图覆盖不足只进入内部受阻/修复路径，不派给用户 | Slice 1 已由 `utils.normalize_task`、`learning._node_task_contract`、`SkillMap` 与 `AcceptanceService` 落地；Slice 2 已由 `python-intro/v2` 阶段模板、`validate_stage_proposal`、`instantiate_stage_task` 与 `evaluate_stage_outcome` 落地；Slice 3 已由 `stage_candidate_pool`、`record_stage_outcome` 和 `integration_evidence` 落地；Slice 4 已由 `outcome_task`、`outcome_eligibility`、`evaluate_outcome` 和 criterion-level evidence 落地 |
| 6. 执行监测 | 记录开始时间、尝试次数、累计实际耗时、前台应用和状态；同一时刻最多一个 `doing` 任务 | `/api/task-state`、`TaskService`、`_fg_loop`、`record_task_outcome` |
| 7. 收集反馈 | 支持太难、太简单、没时间、卡住、方向不对；同时收集被动信号 | 任务卡反馈按钮、`record_feedback`、`passive_review` |
| 8. 判断反馈 | 用户陈述只是线索；综合尝试、耗时、验收、证据和来源计算可信度 | `assess_feedback`；低可信度只安排诊断动作 |
| 9. 自动调整 | 高可信困难拆出最小步骤；时间不足顺延非核心项；方向变化必须确认 | `apply_decision`；原任务验收标准保持不变 |
| 10. 提交证据 | 外部成果支持多文件上传；材料型任务支持页面作答并保存为任务响应 | `/api/upload-evidence`、`/api/task-response`、`task-evidence-list` |
| 11. 验收 | 先跑确定性规则，再对开放式成果调用模型；关键词只是线索；无可信沙箱时程序成果保持阻断，人工确认须有明确理由且不能绕过资格门 | `acceptance.py`、`AcceptanceService`、`evaluate_task`、`SkillMap.apply_outcome` |
| 12. 复盘 | 汇总完成率、验收率、累计耗时偏差、常见阻力和主要应用；归档按周期 ID 幂等 | `complete_review`、`daily_archive`、复盘页 |
| 13. 更新用户模型 | 更新容量系数、合适任务时长、常见阻力和反馈可信度，按目标隔离 | `user_model`、`user_models_by_goal` |
| 14. 生成下一轮任务 | 归档已完成项，稳定保留未完成项的 ID、证据、响应、续接点和累计耗时，用新模型调整任务预算并生成；学习型目标先按节点状态选点，再套容量 | `/api/next-cycle`、`prepare_next_cycle`、`save_diagnostic_plan`、`SkillMap.focus`、`effective_gen_settings` |

## 反馈判断规则

- 单次主观反馈且缺少行为证据：记录反馈，先要求一次最小尝试。
- 尝试至少两次、实际耗时达到预计、验收失败或已有过程证据：提高可信度。
- 太难或卡住：拆出中间成果，原任务继续保留，原验收标准不变。
- 没时间：保留当前核心任务，后续任务顺延。
- 太简单：提高验证深度，而不是增加无关工作。
- 方向不对：不自动修改目标或成功标准，必须由用户确认；确认后只把相关硬先修降为软先修。
- 无主动反馈但累计执行时长超过预计时长 1.5 倍：触发同一判断链；每个信号只处理一次。

## 学习型目标门禁

- 无图或图覆盖失败：不得生成普通学习任务；系统记录规划受阻并保留原任务，补图是内部规划动作，不进入用户任务队列。
- 节点任务必须只有一个主技能；支撑技能必须已经合格，且不通过该任务获得首次掌握。
- 硬先修未掌握：不得生成、不得验收通过该节点任务。
- 阶段任务只能来自版本化 Skill Pack 的合法模板；AI 只能实例化场景和材料，不能删减必需节点或降低验收。
- 阶段通过只产生整合证据，不批量提升节点掌握；阶段失败不批量回退节点。
- 最终成果任务逐成功标准验收；阶段完成不能自动完成目标。
- 基线可以预点亮已会节点，必须留下理由，并允许诊断翻回。
- 太难且可信：补硬缺口或优先软先修，原节点合同与目标成功标准不变。
- 需要复核不产生陪伴成长；阶段通过只产生一次成长事件，不按节点数倍增。

## 下一轮参数

- 完成率低于 50% 或平均耗时超过预计 1.4 倍：下一轮容量按 75% 规划。
- 完成率高于 85% 且未超时：下一轮容量按 110% 规划。
- 其他情况保持当前容量。
- 单任务上限参考已完成任务的平均时长，但仍受用户设置的上限约束。

## 最小验收命令

本轮 B01–B12 的针对性回归位于 `tests/test_business_logic_plan.py`；开放式关键词不再直接放行，LLM 判定必须是布尔类型，合同、目标、周期和计时状态均按稳定身份保存。人工确认是审计记录，不是自动运行验证。

```text
python -m py_compile adaptive.py utils.py task-panel.pyw
python -m ruff check --select E9,F63,F7,F82 .
node --check web/api.js
node --check web/views.js
node --check web/app.js
python -m pytest -q tests
```

## 2026-09-10 残余边界修复

第二轮已补齐：人工复核只信任服务端绑定的目标/任务/证据指纹；阶段人工路径不能绕过 Pack、合同、required skills 或硬先修；成功标准变更会重新生成当前 outcome 并保留旧任务历史；上传尾部和目标保存请求有明确完成标记与请求匹配。仍未宣称 B01–B12 全部完成。

- 人工复核从任务卡进入，理由必填，只记录用户确认，不伪造宿主机或沙箱执行证据。
- 最终成果任务绑定目标契约指纹；目标成果变化会阻断旧任务，即使成功标准文本未变。
- 已绑定技能包的成功标准若存在覆盖缺口，成果资格保持受阻；诊断重生成按现有任务去重。
- 归档身份为目标、日期、周期三元组；拆分中间步骤不结算技能掌握；重复开始同一任务是幂等操作。

隔离端到端测试：启动 `python task-panel.pyw --ci`，设置 `TASKVERGE_TEST_URL`，执行：

```text
python -m pytest -q tests/test_e2e_main_flow.py
```
