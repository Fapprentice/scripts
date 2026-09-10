# Task Verge 残余业务逻辑修复报告（2026-09-10）

此前“B01–B12 全部完成”的结论撤回。本报告只确认这次重新复现并修复的 7 个残余项；没有把旧结论当作本轮证据。

| 编号 | 旧红灯 | 修复后的绿灯证据 |
|---|---|---|
| B03 | 人工复核标记经 panel 保存/重载后丢失，且页面没有可用入口。 | `normalize_task` 保留 `manual_review`；任务卡展示“人工确认并填写理由”，理由必填，只调用 `/api/manual-accept`。`test_b03_manual_review_survives_panel_roundtrip`；真实 Playwright 回归包含该流程并通过。 |
| B04 | 只改最终 outcome、保留相同 criteria 时，旧成果任务可继续验收。 | 成果任务绑定 `contract_fingerprint`，当前契约变化直接 `blocked`，不调用旧证据判定。`test_b04_outcome_change_same_criteria_stays_blocked`。 |
| B06 | 已绑定 `python-intro@v1` 且 criteria 无覆盖时，空依赖仍返回 `eligible=True`。 | 对已绑定 Pack 的未覆盖 criteria 增加资格门；返回 `coverage_gaps`，不生成/放行成果验收。`test_b06_outcome_eligibility_blocks_uncovered_pack_contract`。 |
| B09 | 重复生成诊断计划为同一未完成动作创建新 ID。 | 生成前按现有任务标题去重，保留原 ID、状态和证据。`test_b09_repeated_diagnostic_generation_deduplicates_tasks`。 |
| B10 | 同一 `cycle_id` 跨日归档会覆盖前一天；按 cycle 删除会误删多日记录。 | 归档去重键改为 `(goal_id, date, cycle_id)`；前端删除提交三元身份，后端按三元身份删除。`test_b10_same_cycle_is_kept_across_days`。 |
| B11 | 拆分出的中间步骤继承 skill identity，完成它会提前结算 mastery。 | 中间步骤清除技能身份，标记为 intermediate/legacy；只有原父节点任务结算技能。`test_b11_split_intermediate_does_not_grant_mastery`。 |
| B12 | 对已 `doing` 任务重复发送 `doing` 会关闭并重置计时段。 | `TaskService.set_status` 对重复 `doing` 做幂等返回，不改变 `started_at`、attempts 或累计时长。`test_b12_duplicate_doing_is_idempotent_with_real_normalizer`。 |

## 验证

```text
D:\work_S\scripts\.ui-venv\Scripts\python.exe -m pytest -q
298 passed, 38 skipped

node --check web/app.js
py_compile utils.py learning.py adaptive.py task_service.py acceptance_service.py task-panel.pyw
PASS

真实浏览器（临时 LOCALAPPDATA、TASKVERGE_PORT=0、Playwright Chromium）
tests/test_e2e_regressions.py: 6 passed
```

其余既有回归也由上述完整单测覆盖；未重启、未发布、未操作用户现有桌面实例。未重新宣称 B01–B12 全部验收完成，后续若需要发布仍应按完整产品验收清单复核。

## 变更边界

本次没有添加新依赖或后台自动批准路径。人工确认始终要求用户理由；程序/阶段的真实执行证据门禁仍然有效。

## 第二轮复核（2026-09-10）

第二轮业务验收继续沿用“先红后绿”。本轮确认并修复 4 个 P1 边界，以及 1 个浏览器保存竞态；没有恢复“B01–B12 全部完成”的旧结论。

| 项目 | 旧红灯复现 | 新绿灯证据 |
|---|---|---|
| 人工复核信任边界 | 人工标记可由 `/api/tasks` 的任务替换直接注入；旧人工记录在契约或证据变化后仍可通过。 | 人工记录单独按目标保存，并绑定任务、当前契约和任务/证据指纹；任务替换会清除客户端标记，导入备份会要求重新本机复核。`test_b01_manual_review_expires_when_contract_changes`、`test_b02_client_task_replacement_cannot_inject_manual_review`。 |
| 阶段人工确认 | 阶段人工路径先于阶段合同、Pack、required skills 和硬先修检查。 | `stage_eligibility` 在人工入口和阶段结果落库处双重执行；`test_b03_stage_manual_review_keeps_hard_eligibility_gate`。 |
| 成功标准变更后的生成 | 同标题 outcome 被标题去重吞掉，旧 criteria 留在当前队列，且没有历史。 | 当前 outcome 按契约指纹重新生成，旧任务移入 `task_history`；`test_b04_contract_change_regenerates_current_outcome_and_keeps_history`。 |
| 保存竞态 | 上传尾部的 `task-response` 可能被 pending-save route 当成目标保存请求，导致成功提示等待超时。 | 前端标记上传尾部完成，回归只拦截同时包含本次目标草稿的请求；四套浏览器回归共 `9 passed`。 |

## 第二轮验证

```text
D:\work_S\scripts\.ui-venv\Scripts\python.exe -m pytest -q
302 passed, 39 skipped

AI eval: 31 cases, 0 regressions, release=PASS
ruff（E9/F63/F7/F82）、node --check web/app.js、py_compile
PASS

真实浏览器（临时 LOCALAPPDATA、TASKVERGE_PORT=0、Playwright Chromium）
tests/test_e2e_regressions.py
tests/test_ui_start_pending.py
tests/test_ui_evidence_save_pending.py
tests/test_ui_evidence_roundtrip.py
9 passed
```

本轮没有重启、发布或操作用户现有桌面实例；测试服务使用随机端口和临时数据目录。停止测试服务时出现的 `ConnectionAbortedError/WinError 10053` 是浏览器连接被测试关闭后的 harness 噪声，不是业务失败。

## 第三轮复核（2026-09-10）

第三轮独立验收新增 2 个 P1，均先在真实 `normalize → service → save → reload` 链路复现为红灯，再修共享根因。

| 项目 | 红灯复现 | 修复后的绿灯证据 |
|---|---|---|
| 失败重验的状态一致性 | 合法人工 outcome 通过后修改证据，重验返回 `blocked`，但重载后仍是 `status=done`、`done_flags=[True]`、`goal_completed=True`，旧通过结果复活。 | `AcceptanceService.persist_result` 和阶段落库统一把非通过结果改为未完成；当前 outcome 非通过会清除目标完成；归一化时校验结果契约/任务指纹并修复旧 flag。`test_p1_failed_recheck_reconciles_done_state_after_evidence_change` 同时验证无关已完成任务不被撤销。 |
| 旧 outcome 的重复人工确认 | 旧任务绑定“命令行结果”，当前目标改为“网页版结果”且标准不变，再次人工确认仍可通过。 | 人工入口、自动验收、已有人工记录重放共同检查任务契约、完整标准和资格；旧任务直接拒绝，不能用新人工记录换绑当前目标。`test_p1_manual_recheck_cannot_rebind_old_outcome_to_new_contract`。 |
| 阶段账本一致性 | 阶段任务或结果发生变化时，旧 `integration_evidence.status=passed` 可能继续被 outcome 资格读取。 | 阶段结果保存任务指纹；重载校验任务结果与阶段账本的契约/指纹，不一致即撤销阶段完成并阻止 outcome 解锁。既有阶段回归保持通过。 |

## 第三轮完整矩阵验证

```text
D:\work_S\scripts\.ui-venv\Scripts\python.exe -m pytest -q
305 passed, 39 skipped

第三轮业务矩阵：28 passed
AI eval: 31 cases, 0 regressions, release=PASS
ruff（E9/F63/F7/F82）、node --check web/app.js、py_compile
PASS

真实浏览器（临时 LOCALAPPDATA、TASKVERGE_PORT=0、Playwright Chromium）
tests/test_e2e_regressions.py
tests/test_ui_start_pending.py
tests/test_ui_evidence_save_pending.py
tests/test_ui_evidence_roundtrip.py
9 passed
```

矩阵覆盖首次自动/人工通过、相同输入重复验收、改证据/改标准/只改 outcome 后失效、自动重验与重复人工确认、合法新任务重新完成、重载后的 flags/百分比/目标完成、阶段账本以及多个任务下无关完成项保持不变。剩余边界：完整 Ruff 仍包含仓库既有的大量 E701/E702/F401 风格告警，本轮只执行了新增代码相关的致命规则；仍未重启、发布或接触用户真实运行实例。
