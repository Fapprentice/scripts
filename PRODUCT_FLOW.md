# Task Verge 完整产品闭环

本文件是产品行为规范，也是实现验收清单。核心原则：任务路径和颗粒度可以调整，最终目标与验收标准不能因主观反馈自动降低。

| 环节 | 成熟方案 | 当前实现与证据 |
|---|---|---|
| 1. 设定目标 | 一个目标对应独立定义、状态、任务和用户模型 | 设置页目标卡片与详情面板；`norm_goals`、`ensure_goal_state` |
| 2. 澄清目标 | 明确最终成果、期限、当前基础和现实约束；只追问缺失信息 | 每个目标的详情面板；`goal_details`、`goal_readiness` |
| 3. 建立标准 | 成功标准使用多条可核验条件，生成任务不得覆盖 | `success_criteria` 持久化并进入生成提示 |
| 4. 制定计划 | 根据里程碑、历史复盘、未完成项、容量生成阶段策略；学习型目标的计划是技能地图上的焦点序列，容量只决定取几个点 | `plan_learning_tasks`、`SkillMap.load`、`build_task_prompt`、`effective_gen_settings` |
| 5. 生成任务 | 每项必须有动作、预计时长、交付物和验收标准；依赖特定输入时必须同时生成执行材料；学习任务必须绑定图中已解锁节点，验收不得弱于该节点掌握证据 | `gen_tasks` 对 pack 目标走 `plan_learning_tasks`；无图只派补图；非学习目标仍走 `validate_ai_tasks` |
| 6. 执行监测 | 记录开始时间、尝试次数、实际耗时、前台应用和状态 | `/api/task-state`、`_fg_loop`、`record_task_outcome` |
| 7. 收集反馈 | 支持太难、太简单、没时间、卡住、方向不对；同时收集被动信号 | 任务卡反馈按钮、`record_feedback`、`passive_review` |
| 8. 判断反馈 | 用户陈述只是线索；综合尝试、耗时、验收、证据和来源计算可信度 | `assess_feedback`；低可信度只安排诊断动作 |
| 9. 自动调整 | 高可信困难拆出最小步骤；时间不足顺延非核心项；方向变化必须确认 | `apply_decision`；原任务验收标准保持不变 |
| 10. 提交证据 | 外部成果支持多文件上传；材料型任务支持页面作答并保存为任务响应 | `/api/upload-evidence`、`/api/task-response`、`task-evidence-list` |
| 11. 验收 | 先跑确定性规则，再对无法确定的内容调用模型；无证据不得通过；任务通过只是出示，技能掌握还须满足节点合同 | `acceptance.py`、`cli_eval`、`SkillMap.apply_outcome` |
| 12. 复盘 | 汇总完成率、验收率、耗时偏差、常见阻力和主要应用 | `complete_review`、`daily_archive`、复盘页 |
| 13. 更新用户模型 | 更新容量系数、合适任务时长、常见阻力和反馈可信度，按目标隔离 | `user_model`、`user_models_by_goal` |
| 14. 生成下一轮任务 | 归档已完成项，保留未完成项，用新模型调整任务预算并生成；学习型目标先按节点状态选点（跳过已会、到期优先），再套容量 | `/api/next-cycle`、`prepare_next_cycle`、`SkillMap.focus`、`effective_gen_settings` |

## 反馈判断规则

- 单次主观反馈且缺少行为证据：记录反馈，先要求一次最小尝试。
- 尝试至少两次、实际耗时达到预计、验收失败或已有过程证据：提高可信度。
- 太难或卡住：拆出中间成果，原任务继续保留，原验收标准不变。
- 没时间：保留当前核心任务，后续任务顺延。
- 太简单：提高验证深度，而不是增加无关工作。
- 方向不对：不自动修改目标或成功标准，必须由用户确认；确认后只把相关硬先修降为软先修。
- 无主动反馈但执行超过预计时长 1.5 倍：触发同一判断链；每个信号只处理一次。

## 学习型目标门禁

- 无图或图覆盖失败：不得生成普通学习任务，只允许补图。
- 硬先修未掌握：不得生成、不得验收通过该节点任务。
- 生成不得发明技能包之外的 `skill_id`，不得把软先修写成硬先修。
- 基线可以预点亮已会节点，必须留下理由，并允许诊断翻回。
- 太难且可信：补硬缺口或优先软先修，原节点合同与目标成功标准不变。
- 任务完成不等于技能已掌握；陪伴仍只跟任务验收，不跟假掌握。

## 下一轮参数

- 完成率低于 50% 或平均耗时超过预计 1.4 倍：下一轮容量按 75% 规划。
- 完成率高于 85% 且未超时：下一轮容量按 110% 规划。
- 其他情况保持当前容量。
- 单任务上限参考已完成任务的平均时长，但仍受用户设置的上限约束。

## 最小验收命令

```text
python -m py_compile adaptive.py utils.py task-panel.pyw
python -m ruff check --select E9,F63,F7,F82 .
node --check web/api.js
node --check web/views.js
node --check web/app.js
python -m pytest -q tests
```

隔离端到端测试：启动 `python task-panel.pyw --ci`，设置 `TASKVERGE_TEST_URL`，执行：

```text
python -m pytest -q tests/test_e2e_main_flow.py
```
