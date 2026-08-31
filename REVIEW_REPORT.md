# Task Verge 项目评审报告（历史快照）

> 本文保留为历史记录，测试数字和架构描述不再作为当前发布依据。

日期：2026-07-14  
范围：全仓结构、源码组织、依赖、测试与构建产物。  
本次重点：过度工程、重复实现、无效文件和维护成本。安全、正确性和性能未做专项审计。

## 1. 结论

项目当前可运行，测试基线为 **126 passed，20 skipped**。核心问题不是缺少功能，而是产品源码、实验脚本、截图、运行缓存和构建产物混在同一目录，且主入口承担过多职责。

建议优先做清理和收敛，不建议继续增加抽象层。

## 2. 项目概况

| 项目 | 现状 |
|---|---|
| 技术栈 | Python 3.11+ 标准库、原生 HTTP、Tkinter、Windows ctypes |
| 主入口 | `task-panel.pyw`，约 3,047 行 |
| 前端 | `web/app.js`、`web/app.css`、HTML 页面 |
| 测试 | `tests/`，约 126 个通过、20 个跳过 |
| 三方运行依赖 | README 声称为零；浏览器测试另依赖 Playwright |
| 平台 | Windows-only |
| 运行数据 | JSON 为主，SQLite mirror 可选 |

## 3. 架构观察

主入口同时包含：

- HTTP API 与 multipart 上传
- 任务生成、验收、教练、Agent 编排
- JSON/SQLite 持久化
- 前台窗口监控
- Windows 单实例、托盘、焦点守卫
- Web 模式、Tkinter fallback、CLI 模式

此外，`task-panel.pyw` 直接包含 DeepSeek 调用和业务逻辑，同时又加载 `aiprovider.py`、`acceptance.py`、`coach.py`、`storage.py` 等模块。这种“主入口内置实现 + 可选外部模块”的模式使真实执行路径依赖多个环境变量和 fallback，维护成本较高。

## 4. 问题清单

### P0：暂无阻断项

没有发现本次范围内会阻止测试通过或阻止应用启动的结构性问题。

### P1：应优先处理

1. **仓库混入大量生成物**  
   `dogfood-output/`、`_e2e_shots/`、根目录审计截图、`__pycache__/`、`.pytest_cache/`、日志和 `junk/x.exe` 均不是运行所需源码。它们造成仓库噪音、增大体积，并掩盖真正的变更。  
   建议：删除；需要保留的审计结果放到独立归档或 CI artifact。

2. **主入口过度集中**  
   `task-panel.pyw` 约 3,047 行，横跨多个运行模式和平台职责。修改一个 API 或状态字段时，容易同时影响 Web、Tk、CLI 和后台线程。  
   建议：短期删除不再使用的 Tk/旧模式；长期只在出现真实变更压力时拆分 HTTP handler 或 Windows 集成，不提前建立完整框架。

3. **重复的 AI provider 实现**  
   `task-panel.pyw` 和 `aiprovider.py` 都实现 DeepSeek 请求、JSON 解析和 key 相关流程。  
   建议：保留 `aiprovider.py` 作为唯一实现，主入口只负责业务参数和错误展示。

### P2：应安排清理

4. **SQLite mirror 与 JSON 主存储并存**  
   `storage.py` 引入同步、降级和大量异常吞噬逻辑，而 README 明确 JSON 仍是主要状态来源。若没有明确的查询或恢复需求，这是一层额外状态复杂度。  
   建议：默认移除 mirror；只有出现可量化性能或查询需求时再恢复。

5. **文档明显过重且容易漂移**  
   `CODE_WIKI.md` 约 54KB，包含大量函数级和流程级实现描述。主入口持续变化时，文档同步成本会超过收益。  
   建议：保留 README 的运行方式、数据目录、测试命令和架构简图，其余改成按需维护的短文档。

6. **空平台模块**  
   `platform/win32.py` 和 `platform/__init__.py` 当前没有实际实现，也没有形成可复用的平台接口。  
   建议：删除；只有出现第二个平台或第二个实现时再抽象。

7. **前端存在重复渲染**  
   `web/app.js` 中 coach 消息先后进行相近的去重和 DOM 写入，逻辑可以合并为一次。  
   建议：保留一次 Map 去重和一次 `innerHTML` 更新。

### P3：低优先级

8. **忽略规则不完整**  
   `.gitignore` 未覆盖 `.env`、上传目录和审计输出目录。当前没有发现已提交 Git 仓库，但若后续纳入版本控制，存在误提交本地密钥和数据的风险。  
   建议：补充 `.env`、`.uploads/`、`dogfood-output/`、审计截图和临时目录。

9. **已弃用上传解析器**  
   当前上传实现仍使用 `cgi.FieldStorage`。当前上传规模小，可以暂不动；升级到 Python 3.13 或上传需求扩大时，改为更小的标准库 multipart 解析路径。

## 5. 建议执行顺序

1. 删除生成物、缓存、日志和无效平台文件。
2. 补齐 `.gitignore`，确认 `.env` 和本地上传数据不进入版本库。
3. 统一 `aiprovider.py`，删除主入口中的重复实现。
4. 确认 SQLite mirror 没有实际消费者；没有则删除。
5. 重新运行 `python -m pytest -q tests`。
6. 只有主入口仍持续膨胀时，再做最小拆分。

## 6. 当前验证

执行命令：

```text
python -m pytest -q tests
```

结果：

```text
126 passed, 20 skipped
```

## 7. 最终判断

项目功能链路已有测试覆盖，当前最值得做的是“删东西”和“收敛唯一实现”，不是继续加抽象、配置或测试框架。
