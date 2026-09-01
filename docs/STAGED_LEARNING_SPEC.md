# 分层学习任务模型落地规范

## 1. 决策状态

状态：已接受并已完成四个实施切片；当前进入评审修复与持续验证阶段。运行实现、Skill Pack、API/UI 和测试已落地，后续变更仍须遵守本规范及其验收矩阵。

学习型目标采用四层模型：

1. 技能节点：最小可独立验收能力，不是最小机械动作。
2. 节点任务：一次只结算一个主技能，可以使用已经合格的支撑技能。
3. 阶段任务：使用 Skill Pack 声明的合法节点组合，在统一新情境中验证协同与迁移。
4. 最终成果任务：直接验证目标合同和成功标准，不能由阶段任务替代。

三类证据独立保存和结算：mastery evidence、integration evidence、criterion evidence。

## 2. 技能节点契约

节点只回答一个问题：用户能否在规定条件下独立表现出这一项能力？

建议必填字段：

    {
      "id": "python.control.loop",
      "title": "用循环处理一组数据",
      "core_behavior": "遍历一组输入并为每项执行处理",
      "demonstration": "practice",
      "estimated_verification_minutes": 20,
      "contract_revision": 1,
      "mastery_evidence": {
        "behavior": "提交循环实现及运行结果",
        "threshold": "全部输入均被处理且输出可复现",
        "counterexample": "手工逐项处理不算掌握"
      }
    }

硬校验：ID 稳定且唯一；core behavior 非空；只有一个主 demonstration；掌握证据的 behavior、threshold、counterexample 均非空；不得自引用；整图无环；先修边有类型和理由；不得因难度或反馈降低 mastery threshold。

粒度信号：5–25 分钟正常；26–45 分钟需要不可再拆理由；超过 45 分钟默认拒绝，除非额外时间来自编译、上传等环境成本。不能用“动词数量”机械判断原子性。

## 3. 节点任务

字段模型：

    {
      "task_kind": "node",
      "skill_id": "python.control.loop",
      "primary_skill_id": "python.control.loop",
      "supporting_skill_ids": ["python.syntax.names", "python.syntax.types"],
      "evidence_target": "mastery",
      "expected_output": "一个可运行的循环实现"
    }

规则：恰好一个 primary skill；skill_id 在迁移期是兼容镜像；supporting skills 必须已经合格且不严重到期；本任务只结算主技能；一个主要交付目标可由多个附件共同证明；难度只能改变场景、材料、提示和输入规模，不能降低核心行为、证据或先修。

## 4. 阶段模板

阶段模板属于版本化 Skill Pack 的 stages，不属于 skills DAG，也不由 AI 自由组合。新增 stages 必须发布新版本，例如 python-intro/v2，不得原地修改 v1。

模板至少声明：id、template revision、required/optional/forbidden skill IDs、max supporting skills、integration behavior、outcome shape、逐节点 skill checks、evidence contract、required/optional 属性。

默认组合 2–4 个 required skills；超过 4 个应拆分或归入最终成果任务。每个 required skill 必须对同一个主要成果有必要贡献，禁止把多道独立练习打包成阶段任务。

阶段资格要求：所有 required skills 已满足掌握合同、不严重到期、无未满足硬先修；pack/version/revision 匹配；材料完整；当日预算容纳最小可行场景。必要未知技能使生成失败；非必要未知技能只能作为不影响通过的可选挑战。

## 5. AI 权限与校验

AI 可以实例化应用场景、材料、测试数据、题目表述、有界难度、提示阶梯、独立检查和迁移问题。

AI 不得删除 required skills、改变硬先修、降低 evidence contract、引入未合格必要技能、改变 integration behavior、直接写入权威状态，或为了自己生成的任务创建节点并立即使用。

生成顺序：严格 Schema 校验 → pack/version/revision 校验 → 节点资格校验 → 材料校验 → 非降级校验 → 统一成果校验。失败最多结构化修复一次；再次失败则不派阶段任务，调度其他合格任务。不得退化为无约束大任务，也不得把内部修复派给用户。

AI 返回的 required_skill_ids 必须与模板完全一致，不允许返回子集。统一成果由结构规则和独立语义裁判共同检查。

## 6. 调度

调度先过硬门槛，再使用可解释评分。建议默认分值：严重到期复习 100；阻塞路线节点 80；失败归因任务 75；等待三学习日的 required stage 65；普通未掌握节点 50；新合格 required stage 45；optional stage 25；普通变式 20。

修正项：超预算直接不合格；近期同类失败 -20；昨日刚做同一主节点 -15；用户兴趣场景 +10；阶段每多等待一个学习日 +10，上限 +30。权重是待评测校准的默认值，不是领域真理。

轻微到期复习可由阶段任务逐节点兼做，前提是观察点覆盖核心行为、用户独立完成、未使用直接答案、检查通过且证据可归因。不能批量清除所有节点的到期状态。

时间不足时可缩小场景，但不得删除 required skills 或降低验收。最小可行场景仍超预算时，本日不调度。

## 7. 阶段验收与结算

阶段状态：passed、failed、needs_review、blocked、partial。partial 表示整体未通过但部分观察点有可靠证据，不是半通过。

归因顺序：确定性 skill checks → 能归因则安排对应节点最小验证 → 不能归因则语义裁判 → 仍不确定则 needs_review。

阶段失败默认不回退节点掌握；阶段通过或 partial 只保存 integration observation，不替代首次 mastery evidence。只有明确证据显示既有能力失效时才重验对应节点，绝不批量回退。

阶段通过只产生一次 stage_completed companion event，不按节点数倍增。partial、blocked、needs_review 不产生完整成长事件。

## 8. 最终成果任务

资格要求：required criterion coverage 完整；required skills 满足合同；required integration gates 通过；没有未满足硬先修。不要求所有可选节点和 optional stages 完成。

最终成果从目标创建起在 UI 可见，未解锁时只展示资格进度。每条成功标准必须绑定 criterion ID 和独立证据。阶段通过不能自动完成目标。

失败时按“失败标准 → 成果组成部分 → 阶段能力 → 节点观察点 → 最小诊断/复习”回溯，不重置整个 SkillMap。

## 9. 迁移与版本升级

旧任务迁移必须确定性、可重放、可审计，不调用 AI：单一合法 skill_id 迁为 node task；无 skill 或含义不清保留 legacy；旧综合任务不追溯制造 integration evidence；未完成 map_patch 从用户队列迁出并记录 task_migrated_out，转为内部修复，不标记为用户完成。

新目标默认最新稳定 pack；旧目标保持原版本；升级必须预览并由用户确认，不能静默新增 required stage。节点 ID、core behavior 和 threshold 兼容时保留证据；合同增强、行为变化或节点拆分时保留历史但重评 contract_met。

## 10. UI

节点练习、阶段挑战和最终成果共用一个任务流，以类型和视觉层级区分。SkillMap 中圆形表示技能节点，菱形表示阶段门，旗帜表示最终成果；阶段门不是 skill，不写入 skills DAG。

阶段失败只向用户显示可行动的节点级结论，不展示内部规则 ID、评分或模型置信度。最终成果始终可见但未解锁时不可开始。

## 11. 实施切片

1. Slice 1：task_kind=node、primary/supporting skills、单主技能结算和旧任务兼容迁移。
2. Slice 2：创建 python-intro/v2，只打通 python.stage.control-flow 的生成、校验、展示、验收和归因。
3. Slice 3：阶段候选池、学习日 aging、复习替代、integration evidence 和单次 companion event。
4. Slice 4：criterion evidence、最终成果资格、outcome task 和失败最小回溯。

禁止一次性替换整个任务模型。

## 12. 最低验证矩阵

- 节点：单主技能、支撑技能不获首次掌握、未合格支撑技能被拒绝、阈值不降级。
- 阶段资格：required 未掌握/到期、硬先修缺失、版本不匹配、时间不足、optional 不阻塞。
- 阶段生成：AI 删除 required、添加未知必要技能、材料缺失、拼盘、多主要成果、二次修复失败。
- 阶段验收：五种状态、明确/不明确归因、blocked/needs_review 不成长、passed 只成长一次。
- 迁移升级：单 skill、无 skill、旧 map_patch、旧综合任务、v1 保留、v1→v2 预览、合同兼容与不兼容。
- 最终成果：required/optional 差异、标准部分通过、失败最小回溯、不批量回退。

## 13. 明确拒绝

拒绝：把节点无限拆成机械动作；多主技能节点任务；按已学数量机械组合阶段；AI 自由组合或自授权创建必要节点；降低 mastery threshold；阶段通过批量掌握；阶段失败批量回退；按节点数倍增成长；阶段完成等于目标完成；原地修改发布版本；AI 迁移旧数据；失败时退化为大任务或用户补图。
