# Task Verge 项目调查最终报告

> 汇总来源：researcher（t1 项目结构与用途调查）、engineer（t2 git 状态与 GitHub 痕迹检查、t3 GitHub 仓库定位），reviewer（t4）复核关键证据后成稿。
> 调查对象：`D:\work_S\scripts` 本地仓库（Windows 环境，工作区干净，分支 main）。

---

## ① 项目是什么

**Task Verge（专注控制台）** —— 一个 Windows 本地桌面专注力管控工具，闭环为：制定目标 → 生成每日任务 → 前台时间跟踪 → AI 验收/教练/应用识别 → 证据收集与复盘 → 更新用户模型 → 进入下一周期（行为契约见 `PRODUCT_FLOW.md`）。

**主要功能**
- **AI 任务生成**：按目标生成带预期产出与验收标准的每日任务
- **AI 验收**：上传交付物 → AI 读取文件、跑 `py_compile` + Docker 沙箱 → 返回通过/缺失项/下一步
- **AI 教练**：聊天式建议（改期/重生成/归档），配自动洞察卡片（完成率低、专注漂移、缺证据）
- **AI 应用识别**：两阶段（分类→具体应用）识别任务相关应用，构建可视化"工作桌面"
- **时间块**：自动生成每日日程（90 分钟专注时段 + 自动休息）
- **前台跟踪**：每 2 秒采样前台窗口标题并累计
- **休息计时 / 退出守卫 / 隐私门**：最多 3 次休息；任务未完成时应用内退出需理由；前台跟踪需显式同意、可只记可执行文件名
- **Agent 工作区**：文件/命令工具限定在设置中选择的目录内

**技术栈**
- Python 3.11+，以标准库为主（`http.server` / `ctypes` / `subprocess`）；唯一 pip 依赖 `fsrs==6.3.1`（`learning.py` 做 FSRS 调度 + 知识图谱，`requirements.txt` 已核实）
- 前端：无构建的原生 HTML/CSS/JS SPA（`web/`，5 页）
- 桌面壳：WebView2 原生窗口（pywebview）+ 系统托盘
- 外部服务：DeepSeek API（密钥在 `.env` 或 Hermes env）；lianyue.fun pc-stats
- 打包：PyInstaller + Inno Setup，当前版本 **v0.2.0**（仓库内有 `task-verge-setup-v0.2.0-win-x64.exe` 与 portable zip）
- CI：GitHub Actions（pytest + Playwright E2E，`.github/workflows/ci.yml`）

**目录结构（顶层已核实）**
- `task-panel.pyw`（2844 行）主入口：HTTP 服务 + 托盘 + CLI
- `utils.py` / `runtime.py` / `state_store.py` / `applog.py` 基础设施
- `agent.py` + `agent_service.py` 有界 agent 运行时；`acceptance.py` + `acceptance_service.py` 规则优先验收
- `feedback_service.py` / `task_service.py` 与 HTTP 解耦；`learning.py` / `adaptive.py` FSRS + 自适应目标循环；`apprules.py` 确定性应用识别；`secretstore.py` DPAPI 密钥
- `web/` 前端（5 页 SPA）；`tests/` 19 个测试文件；`packaging/`（installer.iss、build.ps1 等）打包脚本
- `design/`、`audit-ui/`、`design-qa.md` 设计稿与 UI QA；`build/ + dist/` PyInstaller 产物
- ⚠️ `task-verge-redesign/`：**存在但为空壳**（仅 `assets/icons/apple/`、`pages/`、`partials/` 5 个空目录，0 个文件；git 不跟踪空目录故 status 不可见）——researcher 原称"不存在"，复核修正为"存在但无任何内容"，与"未找到实质目录"的结论实质一致

**关键发现 / 注意事项（来自 t1）**
1. `CODE_WIKI.md` 已过时：仍称"单文件零依赖"，实际已重构为模块化，且 `requirements.txt` 含 fsrs
2. `coach/fgwatcher/aiprovider/winadapter/storage` 源码已删除，仅剩 `__pycache__` 残留
3. `dist/` 打包了 torch/transformers/cv2/timm 等重库，与 `requirements.txt`（仅 fsrs）不一致，疑为旧构建残留
4. 文档行数漂移（1737→2328→实际 2844）

---

## ② GitHub 仓库链接结论

### 结论

**最可能的 GitHub 仓库 URL：`https://github.com/Fapprentice/scripts.git`（Fapprentice/scripts，分支 main，tag v0.2.0）**

但该仓库**对匿名/公开访问不可见**（探测返回 "Repository not found"）→ 极大概率是**私有仓库**（无法排除已删除/改名）。**未找到任何公开匹配的 Task Verge 仓库**。

### 证据链

1. **本地 remote 直接配置（最强证据）**：`D:\work_S\scripts\.git\config` 含 `origin → https://github.com/Fapprentice/scripts.git`（fetch+push），`branch.main` 跟踪 `origin/main`；本地 **0 ahead / 0 behind**（`git status --short --branch` 已复核为 `## main...origin/main` 无领先/落后标记），含已推送的 tag `v0.2.0` → 该 remote 真实存在且曾成功推送过
2. **公开可达性验证（engineer）**：经本地代理 127.0.0.1:7897 用 `git ls-remote` 逐一探测 6 个候选名（Fapprentice/scripts、task-verge、task_verge、TaskVerge、task-verge-redesign、taskverge），GitHub 全部返回 "Repository not found" + Authentication failed；GitHub 对"不存在"与"私有"统一返回 not found（隐私保护），无法从响应区分，但结合证据 1 最可能是私有
3. **作者身份佐证**：提交邮箱 `49852004+Fapprentice@users.noreply.github.com` → GitHub 用户名 Fapprentice、用户 ID 49852004；另一提交身份为 `codex@openai.com`（Codex，AI agent 提交）
4. **提交历史（已核实 refs）**：main → `91aaef0`（HEAD，"fix: streamline UI and task execution flow"，2026-08-24）；tag v0.2.0 → `9020cbee`；历史由两棵根提交（Codex 基线 1fa6555 + Fapprentice "Initial commit" 6f1b027）经 9a0adf8 合并而成 → 仓库是 GitHub 上的 Fapprentice/scripts 与本地 Task Verge 基线拼接
5. **web_search 无公开匹配**：'task-verge github'、'"Task Verge" github deepseek'、'Fapprentice task verge' 等只返回无关项目（TaskWeaver、clash-verge、TaskVanguard 等）
6. **其他痕迹**：仓库文档中无任何 github.com 链接/徽章；`apprules.py:45` 的 "githubdesktop.exe" 仅为应用识别名录；无 gitlab/gitee/codeberg 痕迹；无本地 HTTPS 凭据可做需登录的私有确认

> ⚠️ 复核修正：t1 称 `task-verge-redesign/` 不存在，实际该目录存在但为空壳脚手架（见①），与 t3 探测同名仓库 not found 不矛盾。

---

## ③ 如需把本地仓库推送到 GitHub 的步骤建议

当前仓库已配置 origin 指向 `Fapprentice/scripts` 且完全同步，若目标是"公开化"或"重建/换名公开仓库"：

**A. 如果只是要确保与现有（私有）origin 同步**
1. 检查凭据可用：`git push origin main --tags`（应显示 up-to-date）；如需 HTTPS 凭据，配置 Git Credential Manager 或 PAT
2. 若尚未推送：`git push -u origin main && git push origin v0.2.0`

**B. 如果要新建一个公开仓库（推荐路径，避免触碰可能私有的 Fapprentice/scripts）**
1. 在 GitHub 新建空仓库（如 `task-verge`，建议**不勾选** README/.gitignore/license 以免冲突）
2. `git remote set-url origin https://github.com/<你的用户名>/task-verge.git`（或 `git remote add public ...` 保留原 origin）
3. 推送前先做仓库卫生（见下），然后 `git push -u origin main --tags`

**推送前的仓库卫生建议（重要）**
1. **删除无关大件**：`dist/ build/ task-verge-setup-v0.2.0-win-x64.exe`、portable zip 已被 .gitignore 忽略但**已跟踪则需 `git rm -r --cached`**；`dist/` 内 torch/transformers 等重库若已入库会显著膨胀仓库
2. **清理残留**：删除 `task-verge-redesign/` 空壳目录（0 文件，可安全删除）；清理 `__pycache__/` 残留（已 ignore）
3. **敏感信息检查**：`.env`（DeepSeek API key）、`task-verge.key`（DPAPI 密钥）已在 .gitignore，推送前 `git ls-files | grep -iE 'env|key|secret'` 再确认一遍
4. **更新过时文档**：修正 `CODE_WIKI.md`（"单文件零依赖"已过时，实际模块化 + fsrs 依赖）；补齐 README 的 GitHub 徽章/链接（当前无任何仓库链接）
5. **确认提交身份**：当前 local user.name/email 为 Codex/codex@openai.com，若希望以本人身份提交：`git config user.name "你的名字" && git config user.email "你的邮箱"`（提交历史不变，仅影响后续提交）
6. **CI 验证**：推送后确认 GitHub Actions 的 pytest + Playwright E2E 通过（ci.yml 已就绪）

**C. 如果想把现有私有 Fapprentice/scripts 转公开**
1. GitHub Web：仓库 Settings → General → Danger Zone → Change repository visibility → Make public（需有该仓库管理员权限；注意公开后泄露风险，先做 B 步骤的卫生检查）

---

*报告生成时间：由 reviewer 汇总 t1/t2/t3 输出并复核 git remote、README、目录结构、git refs、`task-verge-redesign/` 空壳等关键事实后撰写。*
