# Repo Tutor — 规范整体审计报告 v1

> **审计范围**：`PRD_v5_agent.md`, `interaction_design_v1.md`, `technical_architecture_v2.md`, `data_structure_design_v2.md`, `interface_hard_spec_v2.md`
> **审计日期**：2026-04-12
> **输出裁决**：后续脚手架 Agent 应从 `CURRENT_SPEC.md` 进入，并优先读取 `technical_architecture_v3.md`, `data_structure_design_v3.md`, `interface_hard_spec_v3.md`

---

## 结论

五份规范的产品方向是一致的：第一版是单用户本地运行、只读、安全、面向 Python 仓库优先的教学型 Repo Tutor。

但 v2 之前仍有几处会让脚手架 Agent 生成不兼容代码的硬冲突。已直接生成 v3 文档修复，不建议后续实现继续以 `technical_architecture_v2.md`, `data_structure_design_v2.md`, `interface_hard_spec_v2.md` 作为最终口径。

推荐读取顺序：

1. `CURRENT_SPEC.md`
2. `PRD_v5_agent.md`
3. `interaction_design_v1.md`
4. `technical_architecture_v3.md`
5. `data_structure_design_v3.md`
6. `interface_hard_spec_v3.md`

---

## 已直接修复的问题

### 1. `invalid_request` 错误码只存在于接口文档

**风险等级**：Critical

`interface_hard_spec_v2.md` 新增了接口层错误码 `invalid_request`，但 `data_structure_design_v2.md` 的 `ErrorCode` 枚举没有该值。后续实现如果从数据结构生成后端枚举和前端类型，会出现接口示例可返回、类型系统却不允许的分裂。

**修复**：

- `data_structure_design_v3.md` 将 `invalid_request` 纳入 `ErrorCode`。
- `interface_hard_spec_v3.md` 将 `UserFacingErrorDto.error_code` 从 `ErrorCode | "invalid_request"` 收敛为 `ErrorCode`。

### 2. 架构文档漏掉 `GET /api/session`

**风险等级**：Critical

接口文档要求页面刷新、SSE 重连和前端启动恢复都通过 `GET /api/session`，但 `technical_architecture_v2.md` 的前后端通信表只列出了 `DELETE /api/session`。脚手架 Agent 很可能按架构表生成路由，漏掉恢复接口。

**修复**：

- `technical_architecture_v3.md` 在 M7 前后端通信表中补入 `GET /api/session`。

### 3. 架构附录 docs 清单漏掉数据结构和接口规范

**风险等级**：Critical

`technical_architecture_v2.md` 的建议目录只包含 PRD、交互、架构三份文档，缺少数据结构和接口硬规范。后续脚手架若按附录创建项目，会遗漏最关键的 schema 和 API contract。

**修复**：

- `technical_architecture_v3.md` 的目录建议补入 `data_structure_design_v3.md` 和 `interface_hard_spec_v3.md`。

### 4. `POST /api/repo` 同步/异步边界容易误读

**风险等级**：High

接口文档要求 `POST /api/repo` 只同步创建会话并返回 `202 Accepted`，仓库可访问性、clone、扫描、分析错误走 `/api/analysis/stream`。但架构运行图里写了 M1 失败“返回错误”，容易被实现为阻塞式 HTTP 接口。

**修复**：

- `technical_architecture_v3.md` 在 ARCH-11 明确：M1 可访问性验证、clone、扫描、分析、首轮报告生成均属于异步流程；失败通过分析 SSE 的 `error` 事件返回。

### 5. 深浅调整没有最终消息类型裁决

**风险等级**：High

数据结构有 `PromptScenario=depth_adjustment`，接口允许 `/api/chat` 处理“讲浅一点/讲深一点”，但 `MessageType` 没有 `depth_adjustment_confirmation`。若不裁决，实现可能自行新增消息类型，破坏前端 union。

**修复**：

- `interface_hard_spec_v3.md` 明确 `depth_adjustment` 最终使用 `message_type=agent_answer`，不新增 `MessageType`。

### 6. 运行时版本未裁决

**风险等级**：High

架构使用 `tomllib` 和 `sys.stdlib_module_names` 等能力，但 v2 未明确 Python 版本。后续脚手架若选择较旧 Python，会影响 `pyproject.toml` 解析和标准库 import 判定。

**修复**：

- `technical_architecture_v3.md` 明确 Python 运行时为 `Python 3.11+`，Node 运行时为 `Node.js 20 LTS+`。

---

## 剩余风险

### 1. P0/P1 边界仍需实现时克制

PRD 中“阶段性总结”和“稳定的深浅控制”是 P1，但 OUT-10、交互、架构和接口已经把“总结一下”“讲浅一点/讲深一点”纳入对话能力。建议第一版实现最小可用：能识别并给合格回答即可，不做复杂 UI 控件、长期个性化或额外持久化。

### 2. `.gitignore` 语义没有落到实现库

M2 要应用 `.gitignore`，但规范未指定使用库或简化语义。建议脚手架优先引入 `pathspec` 处理 gitignore 规则；如果不用库，必须在 README 或代码注释中声明支持范围，避免伪完整实现。

### 3. LLM `raw_text` 与结构化载荷可能不一致

接口要求流式 `raw_text` 可先展示，最终由 `message_completed.message` 覆盖为结构化结果。实现必须用测试覆盖：LLM 润色文本不得新增无证据入口、流程、分层或依赖结论。

### 4. 验收 fixture 尚未落地

PRD 要求 3 个固定样例仓库：CLI、Web、library/package。规范已定义验收项，但仓库中尚未看到 fixture 目录。脚手架 Agent 应优先创建最小 fixture，否则 M3/M4/M6 的行为很难稳定验收。

### 5. 旧版本文档仍在目录中

目录中同时存在 v1/v2/v3 文档。后续 Agent 必须明确版本优先级：PRD 使用 `PRD_v5_agent.md`，交互使用 `interaction_design_v1.md`，架构/数据/接口使用 v3。不得混用 `data_structure_design_v2.md` 与 `interface_hard_spec_v3.md` 生成类型。

---

## 后续脚手架硬约束

1. 不要从旧版接口文档生成路由。
2. 不要新增未在 `data_structure_design_v3.md` 中定义的 enum 值。
3. 不要把 `POST /api/repo` 做成阻塞等待分析完成的接口。
4. 不要绕过 `GET /api/session` 做页面恢复。
5. 不要让 M3 调用 LLM 生成分析事实。
6. 不要读取敏感文件正文、绝对真实路径或内部堆栈进入前端、日志或 prompt。
