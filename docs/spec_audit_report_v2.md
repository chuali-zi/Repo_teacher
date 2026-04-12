# Repo Tutor — 规范整体审计报告 v2

> **审计范围**：`PRD_v5_agent.md`, `interaction_design_v1.md`, `technical_architecture_v3.md`, `data_structure_design_v3.md`, `interface_hard_spec_v3.md`
> **审计日期**：2026-04-12
> **输出裁决**：后续脚手架 Agent 必须从 `CURRENT_SPEC.md` 进入，并以本报告列出的修订后 v3 文档为唯一实现依据。

---

## 结论

当前有效规范的产品方向、接口形态和模块拆分已经基本一致，可以继续作为脚手架输入。

但在二次审计中，仍发现 3 处会直接误导状态模型或会话恢复实现的硬漏洞。它们都不是“实现时注意”级别，而是会让脚手架生成错误字段、错误空值规则或错误同步边界的契约缺口。已直接修正文档。

推荐读取顺序：

1. `CURRENT_SPEC.md`
2. `PRD_v5_agent.md`
3. `interaction_design_v1.md`
4. `technical_architecture_v3.md`
5. `data_structure_design_v3.md`
6. `interface_hard_spec_v3.md`
7. `spec_audit_report_v2.md`

---

## 本轮已修复的问题

### 1. `GET /api/session` 依赖进度快照，但数据结构没有稳定字段

**风险等级**：Critical

接口文档要求页面刷新、分析流重连和前端冷启动都能通过 `GET /api/session` 取回 `progress_steps`。但 `data_structure_design_v3.md` 之前只有短时 `runtime_events`，没有稳定的会话级进度快照字段。脚手架若按数据结构建模，通常会出现两种错误实现：

- 根本不持久保存分析步骤，只能靠 SSE 临时展示。
- 试图从 `runtime_events` 回放推导当前进度，导致刷新后状态不稳定、实现复杂且与接口快照不一致。

**修复**：

- `data_structure_design_v3.md` 新增 `SessionContext.progress_steps`。
- `data_structure_design_v3.md` 新增 `ProgressStepStateItem` 稳定结构和初始化/更新规则。
- `data_structure_design_v3.md` 明确：`GET /api/session` 所需进度不得只靠 `runtime_events` 重建。

### 2. `ConversationState.sub_status` 空值规则与接口状态机冲突

**风险等级**：Critical

接口文档明确规定：`ConversationSubStatus` 只在 `status=chatting` 时有效，其他状态必须为 `null`。但数据结构文档此前把 `ConversationState.sub_status` 写成非空枚举。因为 `SessionContext` 在 `idle/accessing/analyzing/error` 状态下仍持有 `conversation`，脚手架很容易生成错误的非空字段，随后在 `GET /api/session`、状态映射和前端 store 中出现类型冲突。

**修复**：

- `data_structure_design_v3.md` 将 `ConversationState.sub_status` 改为 `ConversationSubStatus | null`。
- `data_structure_design_v3.md` 明确默认值和状态约束：创建/清理后 `sub_status=null`，仅 `chatting` 可非空。
- `data_structure_design_v3.md` 同步补充 `current_learning_goal=overview`、`current_stage=not_started` 的默认口径，避免脚手架自行脑补初始值。

### 3. 架构运行图仍把同步参数校验和异步仓库接入混在一起

**风险等级**：High

`technical_architecture_v3.md` 已在正文中说明 `POST /api/repo` 只同步做请求校验并返回 `202 Accepted`，但运行时流程图仍把 `M1 input_validator` 放在异步链条里，并画出“失败 -> HTTP 错误”的分支。脚手架如果优先依图生成，很容易把格式错误和仓库可访问性错误都做成同一条异步流程，或者反过来把本应走 SSE 的接入失败做成阻塞式 HTTP。

**修复**：

- `technical_architecture_v3.md` 将流程一改为两段：
1. 路由层/M5 同步请求参数校验，失败返回 `400 Bad Request`。
2. 成功后进入异步 M1 可访问性验证、clone、扫描、分析和首轮报告生成，失败统一经 `/api/analysis/stream` 返回。
- 同步补充“初始化进度快照”和“缓存最终进度快照”的架构要求。

---

## 当前有效口径

1. 产品边界、教学目标、安全边界以 `PRD_v5_agent.md` 为准。
2. 页面阶段、交互节奏、展示结构以 `interaction_design_v1.md` 为准。
3. 模块职责、运行流程、同步/异步边界以 `technical_architecture_v3.md` 为准。
4. 内部对象、枚举、生命周期、会话快照字段以 `data_structure_design_v3.md` 为准。
5. 路由、DTO、SSE 事件、状态机和前端恢复策略以 `interface_hard_spec_v3.md` 为准。

---

## 剩余风险

### 1. P0/P1 边界仍需实现时克制

`summary`、更稳定的深浅控制在 PRD 中仍偏 P1，但接口已经给出可落地消息类型和场景。脚手架应做最小可用实现，不要额外扩展复杂 UI 控件、个性化偏好或跨会话记忆。

### 2. `.gitignore` 语义仍未落到具体实现库

规范要求应用 `.gitignore`，但没有强制指定库。脚手架若不引入成熟匹配库，至少必须显式声明支持范围，避免生成“看似支持、实则不完整”的忽略逻辑。

### 3. 验收 fixture 仍未在仓库落地

PRD 的三类固定样例仓库还不在目录中。脚手架阶段应优先补最小 fixture，否则 M3/M4/M6 的验收会继续偏主观。

### 4. 旧版文档仍与当前版本并存

目录里仍保留 v1/v2 文档。脚手架必须只从 `CURRENT_SPEC.md` 进入，不得混用旧版枚举、旧接口或旧路由。

---

## 后续脚手架硬约束

1. 不要从旧版文档生成任何模型、路由或枚举。
2. `GET /api/session` 的 `progress_steps` 必须来自稳定会话快照，不得只靠 SSE 事件回放。
3. `ConversationSubStatus` 在非 `chatting` 状态必须为 `null`。
4. `POST /api/repo` 只同步校验请求参数；仓库可访问性、clone、扫描、分析和首轮生成均为异步。
5. 不要把 M3 事实分析外包给 LLM。
6. 不要让敏感文件正文、绝对真实路径或内部堆栈进入前端、日志或 prompt。
