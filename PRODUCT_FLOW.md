# Task Verge 完整产品闭环

本文件是产品行为规范，也是实现验收清单。核心原则：任务路径和颗粒度可以调整，最终目标与验收标准不能因主观反馈自动降低。

| 环节 | 成熟方案 | 当前实现与证据 |
|---|---|---|
| 1. 设定目标 | 一个目标对应独立定义、状态、任务和用户模型 | 设置页目标卡片与详情面板；`norm_goals`、`ensure_goal_state` |
| 2. 澄清目标 | 明确最终成果、期限、当前基础和现实约束；只追问缺失信息 | 每个目标的详情面板；`goal_details`、`goal_readiness` |
| 3. 建立标准 | 成功标准使用多条可核验条件，生成任务不得覆盖 | `success_criteria` 持久化并进入生成提示 |
| 4. 制定计划 | 根据里程碑、历史复盘、未完成项、容量生成阶段策略 | `build_task_prompt`、`task_generation`、`effective_gen_settings` |
| 5. 生成任务 | 每项必须有动作、预计时长、交付物和验收标准；依赖特定输入时必须同时生成执行材料 | `validate_ai_tasks`、`ensure_task_materials`、`fit_task_budget`；无模型时本地模板兜底 |
| 6. 执行监测 | 记录开始时间、尝试次数、实际耗时、前台应用和状态 | `/api/task-state`、`fgwatcher`、`record_task_outcome` |
| 7. 收集反馈 | 支持太难、太简单、没时间、卡住、方向不对；同时收集被动信号 | 任务卡反馈按钮、`record_feedback`、`passive_review` |
| 8. 判断反馈 | 用户陈述只是线索；综合尝试、耗时、验收、证据和来源计算可信度 | `assess_feedback`；低可信度只安排诊断动作 |
| 9. 自动调整 | 高可信困难拆出最小步骤；时间不足顺延非核心项；方向变化必须确认 | `apply_decision`；原任务验收标准保持不变 |
| 10. 提交证据 | 外部成果支持多文件上传；材料型任务支持页面作答并保存为任务响应 | `/api/upload-evidence`、`/api/task-response`、`task-evidence-list` |
| 11. 验收 | 先跑确定性规则，再对无法确定的内容调用模型；无证据不得通过 | `acceptance.py`、`cli_eval` |
| 12. 复盘 | 汇总完成率、验收率、耗时偏差、常见阻力和主要应用 | `complete_review`、`daily_archive`、复盘页 |
| 13. 更新用户模型 | 更新容量系数、合适任务时长、常见阻力和反馈可信度，按目标隔离 | `user_model`、`user_models_by_goal` |
| 14. 生成下一轮任务 | 归档已完成项，保留未完成项，用新模型调整任务预算并生成 | `/api/next-cycle`、`prepare_next_cycle`、`effective_gen_settings` |

## 反馈判断规则

- 单次主观反馈且缺少行为证据：记录反馈，先要求一次最小尝试。
- 尝试至少两次、实际耗时达到预计、验收失败或已有过程证据：提高可信度。
- 太难或卡住：拆出中间成果，原任务继续保留，原验收标准不变。
- 没时间：保留当前核心任务，后续任务顺延。
- 太简单：提高验证深度，而不是增加无关工作。
- 方向不对：不自动修改目标，必须由用户确认。
- 无主动反馈但执行超过预计时长 1.5 倍：触发同一判断链；每个信号只处理一次。

## 下一轮参数

- 完成率低于 50% 或平均耗时超过预计 1.4 倍：下一轮容量按 75% 规划。
- 完成率高于 85% 且未超时：下一轮容量按 110% 规划。
- 其他情况保持当前容量。
- 单任务上限参考已完成任务的平均时长，但仍受用户设置的上限约束。

## 最小验收命令

```text
python -m py_compile adaptive.py utils.py task-panel.pyw
node --check web/app.js
python -m pytest -q tests
```

隔离端到端测试：启动 `python task-panel.pyw --ci`，设置 `TASKVERGE_TEST_URL`，执行：

```text
python -m pytest -q tests/test_e2e_main_flow.py
```
