# Task Verge — Code Wiki

> 当前架构说明，核对日期：2026-08-24。产品行为契约见 `PRODUCT_FLOW.md`，领域词汇见 `CONTEXT.md`。

## 1. 系统形态

Task Verge 是 Windows 本地桌面应用：Python 后端在 `127.0.0.1` 提供本地 HTTP API 和静态资源，原生 HTML/CSS/JavaScript 前端运行在 WebView2 窗口中，并通过系统托盘保持驻留。

- Python 3.11+
- 第三方运行依赖：`fsrs==6.3.1`
- 可选能力：DeepSeek API、Docker Desktop、pywebview
- 用户数据目录：`%LOCALAPPDATA%\TaskVerge`
- 默认地址：`http://127.0.0.1:64161/`；端口占用时自动选择可用端口

## 2. 模块边界

| 模块 | 职责 |
|---|---|
| `task-panel.pyw` | 进程入口、HTTP 路由、桌面窗口、托盘、前台监测与模块编排 |
| `utils.py` | 数据归一化、任务基础模型和通用纯函数 |
| `state_store.py` | JSON 状态的加载、压缩和原子保存 |
| `runtime.py` | 作业队列与运行时辅助能力 |
| `acceptance.py` | 确定性验收规则、材料型任务答案判定 |
| `acceptance_service.py` | 验收用例编排 |
| `adaptive.py` | 目标完整度、能力诊断、自适应任务生成和反馈决策 |
| `learning.py` | FSRS 调度、知识点状态、诊断任务与执行材料生成 |
| `task_service.py` | 任务增删改、状态和证据操作 |
| `feedback_service.py` | 主动/被动反馈的判断与调整 |
| `agent.py` / `agent_service.py` | 有界 Agent 运行及确认流程 |
| `apprules.py` | 应用识别与任务应用匹配 |
| `secretstore.py` | Windows DPAPI 密钥存储 |
| `applog.py` | 结构化日志 |

`task-panel.pyw` 仍是组合入口，但业务逻辑已拆分到上述模块；它不是“单文件、零依赖”架构。

## 3. 前端

`web/index.html`、`web/app.js`、`web/app.css` 构成无构建步骤的 SPA，包含三个一级视图：

- **今日执行**：当前任务、计时、任务材料弹窗、页面作答、证据上传和验收
- **记录**：复盘摘要、知识图谱、最近 12 个月的月度热力图，以及归档/事件/退出记录弹窗
- **设置**：目标卡片；每个目标独立设置最终成果、目标日期、当前基础、成功标准和现实约束；低频运行参数放入详细设置弹窗

前端通过 `X-Session` 会话令牌避免多个页面同时写入。弹窗统一经过 `openModal` / `closeModal` 管理焦点、Esc 和背景禁用状态。

## 4. 目标与任务状态

目标以对象保存，而不是纯字符串：

```json
{
  "id": "goal_0",
  "title": "英语四级",
  "outcome": "通过英语四级考试",
  "deadline": "2027-06-01",
  "baseline": "当前基础说明",
  "success_criteria": ["总分达到目标线"],
  "constraints": ["每天可投入 60 分钟"]
}
```

`active_goal` 指向当前目标。任务、完成标记、应用、生成结果、验收、反馈、用户模型和复盘通过 `*_by_goal` 映射隔离；切换目标时 `ensure_goal_state` 恢复对应快照。

材料型任务在普通任务字段之外使用：

- `materials`: 题目、文章、听力脚本或写作题干
- `interaction`: 页面交互类型和评分方式
- `response`: 用户在页面内保存的答案
- `answer_key`: 确定性验收所需答案

## 5. 核心运行流程

1. 用户创建目标并填写最终成果、成功标准与现实约束。
2. 系统先生成稳定能力维度，再生成诊断任务。
3. 诊断完成后结合目标定义、历史结果、FSRS 状态和容量生成任务。
4. 用户从首页开始、暂停和继续任务；计时累计保存。
5. 材料型任务在弹出面板内作答，外部成果通过文件上传。
6. 验收优先执行确定性规则，必要时再调用 AI。
7. 结果更新积分、FSRS、知识图谱、反馈模型和下一轮容量。

## 6. 主要 API 分组

- 状态与目标：`/api/state`、`/api/settings`、`/api/active-goal`
- 任务：`/api/tasks`、`/api/task`、`/api/task-state`、`/api/task-adjust`
- 材料与证据：`/api/task-response`、`/api/upload-evidence`、`/api/task-evidence-list`
- 生成与验收：`/api/generate`、`/api/generate-status`、`/api/evaluate-task`、`/api/evaluate`
- 学习与反馈：`/api/task-rating`、`/api/feedback`、`/api/next-cycle`
- 运行设置：`/api/focus-policy`、`/api/privacy-consent`、`/api/deepseek-key`
- 历史：`/api/archive`、`/api/archive-delete`、`/api/event`、`/api/export`
- Agent：`/api/agent-start`、`/api/agent-state`、`/api/agent-confirm`、`/api/agent-stop`

完整路由以 `task-panel.pyw` 中的 Handler 为准。

## 7. 本地数据

| 路径 | 内容 |
|---|---|
| `task-config.json` | 目标、任务、设置、学习状态和按目标隔离的数据 |
| `history.json` | 验收历史，最多 500 条 |
| `fgtime.json` | 前台应用聚合时间 |
| `uploads/` | 按目标和任务隔离的交付物 |
| `task-verge.key` | 当前 Windows 用户 DPAPI 加密的 DeepSeek Key |
| `crash.log` / `boot.log` / `watchdog.log` | 恢复和运行诊断 |

所有路径位于 `%LOCALAPPDATA%\TaskVerge`，源代码目录不作为用户数据目录。

## 8. 启动、测试与打包

```powershell
# 桌面运行
python task-panel.pyw

# 安全的默认测试
python -m pytest -q tests

# 前端语法
node --check web/app.js

# 便携包
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -ZipOnly
```

`python task-panel.pyw --ci` 使用随机端口和隔离数据目录，供 API/E2E 测试使用。发布版本由 PyInstaller 构建；安装包额外需要 Inno Setup 6。

## 9. 关键约束

- 仅支持 Windows；Win32、托盘、启动目录和 DPAPI 都是平台边界。
- 任务路径和颗粒度可以根据证据调整，但不能静默降低目标的最终成功标准。
- 材料型任务缺少执行材料时不可进入可执行队列。
- 上传边界必须继续保留大小限制、目录隔离和文件名清洗。
- 高风险 Agent 操作必须经过确认，工作区工具不能越过用户选择的目录。
