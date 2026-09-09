# Task Verge 优化落地方案

日期：2026-09-07。执行模型：GPT-5.6 Luna。
评审基线：main / `0588ab0e9c9c138d087a841614888117e65ec32a`。

## 目标与执行方式

修复本轮评审确认的 12 项问题，使证据存储安全、验收结论与账本一致、失败后可以重试、执行记录可信，并恢复干净环境的发布能力。

按下面四个阶段顺序实施。每阶段先复现，再修复共享根因，运行相关回归后进入下一阶段。位置行号仅是基线定位，按函数名查找当前代码。开始前阅读 README.md、PRODUCT_FLOW.md、CONTEXT.md、docs/STAGED_LEARNING_SPEC.md 和适用的 AGENTS.md。

采用最小可维护改动，复用现有服务、标准库和测试体系。本次不做页面重设计、全仓拆分或新框架迁移。每项至少补充或修正一个能识别原缺陷的回归检查；涉及归一化、持久化的问题，检查须跨越真实调用边界，不能只测试孤立辅助函数。

全部验证使用临时数据目录、临时交付物与隔离 CI 服务；不得使用用户正在运行的实例或真实存储做破坏性复现。完成代码和必要文档、测试，交付可审查 diff；不自动发布安装包到外部或合并主分支。

## 阶段一：数据安全与证据生命周期

### O01 / P1：备份回收站路径越界删除

- 定位：state_store.py，import_complete（约 748 行）、purge_trash（约 706 行）、maybe_backup。
- 现状：导入跳过 trashed_at 非空记录的路径重定位；清理直接 unlink 数据库中的 stored_path。合法格式、有效完整性摘要的备份仍可以包含恶意绝对路径。
- 修复：将导入数据视为不可信；处理不能恢复的旧回收记录；删除前独立验证规范化后的路径严格位于当前管理回收目录内，包含符号链接/目录联接边界。保留正常回收与备份恢复能力。
- 验收：构造包含过期外部路径记录的备份，导入并触发实际清理，外部临时文件保持不变；正常受管过期文件可清理；异常结果可诊断。

### O02 / P1：归档后交付物被清理

- 定位：task-panel.pyw，cleanup_uploads（约 179 行）、sc、daily_archive、/api/next-cycle。
- 现状：只保留 tasks_by_goal 的附件引用，归档独占引用会在下一次保存时被移入回收站。
- 修复：明确所有持久证据引用的来源，至少覆盖当前任务、历史归档和学习证据账本；仅回收确实不再被引用的附件。避免引入第二套独立引用计数状态。
- 验收：完成任务→归档→下一轮→保存→重读，历史证据仍可读取；多目标共享文件不误删；真正无引用文件仍能正常回收。完整导出/导入后历史证据仍可读取。

## 阶段二：验收与学习闭环

O03、O05 必须一起检查，避免保留一个字段却在下游再次丢失语义。

### O03 / P1：阶段无证据也能通过

- 定位：learning.py，instantiate_stage_task、evaluate_stage_outcome（约 113 行）；utils.py，normalize_task。
- 现状：observations_required=True 在 normalize_task 时丢失；response={"status":"passed"} 可以直接写入通过记录。
- 修复：保留阶段合同必要字段；以受信任版本化模板恢复/验证必须的观察要求。客户端 status 或自报 passed 不是通过依据。使用可验证证据判定，无法确定时进入 needs_review/blocked，不能伪造确定性通过。
- 验收：真实任务归一化与存取后，无附件、无观察、缺少必需技能观察、仅自报 passed 均不得通过；合法且可验证的阶段证据能通过。

### O04 / P1：最终成果把非空列表当作达标

- 定位：learning.py，evaluate_outcome（约 365 行）；task-panel.pyw，task-response、evaluate_task。
- 现状：每条成功标准提交 [null] 或无关文本即可通过，进而 goal_completed=True。
- 修复：验证每条证据的类型、内容与有效引用，再验证其是否满足对应成功标准；复用现有确定性/语义验收能力。语义无法判定或云服务不可用时明确待复核，不能将“有提交”视为“达标”。
- 验收：[null]、空白、失效引用、无关内容不通过；有效标准对应证据通过；语义不确定进入复核；部分标准不达标时目标不能完成。补充可确定通过的正向用例，避免用“永不通过”代替实现。

### O05 / P1：阶段 API 通过但账本为 partial

- 定位：acceptance.py，_check_items（约 353 行）；task-panel.pyw，evaluate_task（约 959 行）。
- 现状：通用检查结果转换丢失 skill_id，再结算时无法关联必需技能，API passed / task done / integration partial 分裂。
- 修复：结构化阶段观察保持完整；验收和持久化使用同一权威结论，展示适配不能改变结算语义。检查阶段后续资格使用的实际账本。
- 验收：完整有效观察经过真实 evaluate_task→规范化→保存→重新读取后，API、task、integration_evidence 三者一致，后续门禁可读取；partial/needs_review 同样一致。

### O06 / P1：首次失败锁死后续重试

- 定位：learning.py，record_stage_outcome（约 243 行）。
- 现状：发现同 task_id 即返回首次记录，failed 后再 passed 仍为 failed。
- 修复：分开尝试结果与成功事件幂等；支持失败/部分完成/待复核后提交新的有效证据。成功事件与成长只结算一次，保留必要审计信息。
- 验收：同任务 failed→passed 能解锁；partial→passed 能解锁；重复相同成功提交不会重复发奖励或成功事件；历史失败仍可解释。

### O07 / P1：最终成果资格冻结

- 定位：task-panel.pyw，evaluate_task（约 911 行）；learning.py，outcome_eligibility、outcome_task。
- 现状：只读生成时的 locked/eligibility，后续技能达标也无法验收原成果任务。
- 修复：验收前根据当前目标、技能和阶段证据重新计算资格，更新显示状态；不能通过客户端修改旧 eligibility 绕过门禁。
- 验收：生成时锁定→完成所需技能/阶段→同一个成果任务能够进入验收；当前资格不满足时仍被阻止；目标间资格隔离。

### O08 / P1：验收清零累计耗时

- 定位：task-panel.pyw，reset_task_timer（约 900 行）、evaluate_task；adaptive.py，complete_review；task_service.py，set_status。
- 现状：验收清除 actual_seconds，超时任务复盘容量从应有 0.75 变为 1.1。
- 修复：区分本次计时起点和累计实际耗时；验收时正确结算正在进行的时间并停止该段计时，保留累计记录；检查暂停、恢复和重试是否重复计算。
- 验收：预计 30 分钟、实际 60 分钟，完成验收后复盘容量为 0.75；累计耗时保留；暂停/恢复/重复请求不会重复累计；前端显示与后端记录一致。

## 阶段三：Agent 与回归测试可靠性

### O09 / P2：停止被并发步骤覆盖

- 定位：agent.py，step（约 112–141 行）、stop、_put；task-panel.pyw，_agent_loop、/api/agent-stop。
- 现状：规划期间 stop 返回 paused，规划完成后仍执行工具，旧快照保存成 planning。
- 修复：使用现有状态机制增加取消/版本检查，在工具执行前确认状态，阻止旧步骤覆盖用户停止。按每次 run 隔离；不持有会阻塞 stop 的长时间全局锁。明确已开始的外部操作与尚未开始的下一动作的边界。
- 验收：Event 阻塞 planner→stop→释放 planner，工具调用次数为 0、持久状态仍 paused；已有串行停止用例和其他 run 正常执行。

### O10 / P2：API 测试目标 ID 漂移

- 定位：tests/test_api.py，test_goal_delete_archives_goal_and_keeps_tasks（约 233 行）。
- 修复：使用该测试实际创建的稳定目标 ID，验证删除后的目标归档及其任务完整性，而不是只改成弱断言。
- 验收：独立 CI 服务上的完整 API 测试全部通过。

## 阶段四：发布能力

### O11 / P1：干净环境打包提前失败

- 定位：packaging/build.ps1（约 17 行）。
- 修复：写版本信息前创建必需输出目录，保持可重复构建；不依赖工作区残留 build 目录。
- 验收：新检出/隔离目录、没有 build/dist 时可执行到并完成构建；目录创建行为有可重复检查。

### O12 / P1：发布包缺少 Skill Pack

- 定位：packaging/build.ps1（约 52 行）、learning.py 的 pack 路径、.github/workflows/ci.yml 的 release-smoke。
- 修复：将运行时所需 packs 数据纳入 bundle，核对其他实际需要的静态资源；发布 smoke 验证包内解析而非借用源码目录。
- 验收：打包产物能解析 python-intro/v1、v2 和 cet4/v1，找到 python.stage.control-flow；至少运行一次产物的技能规划/解析 smoke。EXE、ZIP 存在只是前置检查。

## 最终验证与交付

评审时基线：基础 tests 为 255 passed / 35 skipped；独立 API 为 19 passed / 1 failed（O10）；evaluation.py --run 为 31 cases / 0 regressions；ruff E9,F63,F7,F82 与三个 JS 语法检查通过。基础跳过项不能当作通过。

1. 运行所有新增针对性回归，再运行 README 中完整基础 tests、Python 静态检查、web/api.js、views.js、app.js 语法检查与 evaluation.py --run、校准命令。
2. 使用独立 LOCALAPPDATA、随机端口的 --ci 实例运行 API；浏览器 E2E 使用另一新实例，避免会话冲突。按测试实际使用的固定会话检查环境问题，修复本次改动引起的回归。
3. 完成隔离打包与产物 smoke。依赖/工具缺失时先利用已有环境或隔离安装；若仍有外部阻碍，明确标记未验证，不声称通过。
4. 更新必要文档，使行为描述与最终实现一致。用 O01–O12 清单报告：修改位置、验证命令及结果、剩余限制；标明分支与 diff。全部已授权修复应持续实施，不在完成方案或第一阶段后停下。

本机原工作区可用 Python：`D:/work_S/scripts/.ui-venv/Scripts/python.exe`，默认 python 命令是失效的 Microsoft Store 别名。独立工作树可复用该解释器运行其工作树文件，或创建隔离环境；不要误在原工作区运行修改脚本。不要假定评审时的缓存或构建产物可作为发布依据。
