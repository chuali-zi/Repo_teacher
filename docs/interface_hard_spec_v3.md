# Repo Tutor — 接口硬规范 v3

> **文档类型**：接口硬规范  
> **面向对象**：后续脚手架 Agent / 前后端开发 / 模块集成负责人  
> **对应上位文档**：`PRD_v5_agent.md`, `interaction_design_v1.md`, `technical_architecture_v3.md`, `data_structure_design_v3.md`  
> **修订来源**：审计 `interface_hard_spec_v1.md`，并同步数据结构 v3 的错误码裁决  
> **适用范围**：第一版单 Agent、只读、教学型 Repo Tutor  
> **日期**：2026-04-12

---

> v3 为 v2 的兼容修订版，保留 `API2-*` 章节锚点，避免已存在的跨文档链接失效。v3 只修复会导致实现分裂的硬契约问题。

## 索引

| 编号 | 章节 | 说明 |
|------|------|------|
| [API2-00](#api2-00) | 审计结论 | v1 是否可接受、v2/v3 修正范围 |
| [API2-01](#api2-01) | 文档依据与裁决优先级 | 与 PRD、交互、架构、数据结构的关系 |
| [API2-02](#api2-02) | 全局协议与会话原则 | HTTP、SSE、Envelope、会话、命名 |
| [API2-03](#api2-03) | 外部 Wire DTO | 前后端传输对象，不要求等同内部对象 |
| [API2-04](#api2-04) | HTTP 路由硬契约 | REST 端点、请求、响应、状态码 |
| [API2-05](#api2-05) | SSE 事件硬契约 | 事件格式、事件 union、时序、关闭条件 |
| [API2-06](#api2-06) | 状态机与视图映射 | 全局状态、子状态、前端视图映射 |
| [API2-07](#api2-07) | 模块间接口契约 | M1-M6 输入输出、调用边界、禁止行为 |
| [API2-08](#api2-08) | M6 与首轮报告契约 | Prompt 输入、回答输出、首轮结构化载荷 |
| [API2-09](#api2-09) | 前端集成契约 | Store、API Client、SSE 聚合、组件边界 |
| [API2-10](#api2-10) | 错误、降级与超时 | 错误码、HTTP status、降级映射 |
| [API2-11](#api2-11) | 安全硬约束 | 只读、敏感文件、路径、日志、prompt |
| [API2-12](#api2-12) | 脚手架验收清单 | 后续 Agent 实现前后必须核对 |

---

## <a id="api2-00"></a>API2-00 审计结论

### 总体判断

`interface_hard_spec_v1.md` 的产品方向基本贴合上位文档：它选择了 `HTTP REST + SSE`、保留单活跃会话、遵守只读与候选措辞、覆盖了仓库提交、分析流、聊天流和切仓接口。

但 v1 作为“脚手架 Agent 的唯一接口输入”不可接受。它仍有若干会导致实现自行脑补的缺口，后续模型很容易生成互相不兼容的路由、事件和前端状态管理代码。

### v1 不可接受缺口

1. **状态机表达错误**：v1 写成 `idle <- access_error` / `idle <- analysis_error`，没有明确 `accessing -> access_error`、`analyzing -> analysis_error` 和错误态如何重试。
2. **SSE 事件格式不够硬**：示例固定写 `event: analysis_progress`，但实际又列出多种事件；缺少 `event_type` 字段、事件 union、重连/过期 session 行为。
3. **首轮报告结构化载荷缺口**：PRD OUT-1 和 IX-08 要求首轮报告按特定区块输出；v1 的 `message_completed` 示例只给六段式 `structured_content`，不足以指导前端渲染首轮报告。
4. **缺少会话状态查询接口**：架构明确 REST 用于状态查询，v1 没有 `GET /api/session`，刷新页面、SSE 重连、旧流污染都缺少统一裁决。
5. **同步/异步边界模糊**：`POST /api/repo` 到底同步校验到哪一步、哪些错误走 HTTP、哪些错误走 SSE 没有说清。
6. **HTTP 状态码和错误 envelope 未裁决**：实现 Agent 可能全部返回 200，也可能混用 400/500，前端无法稳定处理。
7. **内部对象与外部 DTO 边界模糊**：v1 一方面说沿用数据结构，另一方面又说只暴露最小字段，但没有定义 wire DTO。
8. **前端 store 与 SSE 聚合规则不足**：只说明按 `message_id` 聚合，没有定义初始快照、结束事件、旧 session 事件丢弃规则。

### v2/v3 修正策略

v2 不推翻 v1 的方向，而是把 v1 的原则补成可执行契约；v3 在 v2 基础上同步数据结构错误码，并补充深浅调整的消息类型裁决：

- 明确 HTTP 路由、请求响应、状态码。
- 明确 SSE 事件格式和事件 union。
- 增加 `GET /api/session`。
- 修正状态机。
- 增加 `MessageDto.initial_report_content`，让首轮报告符合 OUT-1。
- 明确 wire DTO 与内部 DS2 对象的关系。
- 明确脚手架目录中每类接口的落点。
- 明确 `invalid_request` 属于 `data_structure_design_v3.md` 的 `ErrorCode`，不再作为接口层临时 union 值。
- 明确 `depth_adjustment` 场景的最终消息使用 `message_type=agent_answer`，不新增 `MessageType`。

---

## <a id="api2-01"></a>API2-01 文档依据与裁决优先级

### 直接依据

1. `docs/PRD_v5_agent.md`
2. `docs/interaction_design_v1.md`
3. `docs/technical_architecture_v3.md`
4. `docs/data_structure_design_v3.md`

### 优先级

1. 产品边界、教学输出、安全边界：`PRD_v5_agent.md`
2. 页面、交互、展示顺序：`interaction_design_v1.md`
3. 模块职责、运行流程、技术选型：`technical_architecture_v3.md`
4. 内部数据对象、枚举、生命周期：`data_structure_design_v3.md`
5. 本文：只裁决接口层未明确处，不得扩展 v1 范围外能力。

### v3 裁决

1. 前后端通信只使用 `HTTP REST + SSE`。`technical_architecture_v3.md` 中若出现旧式“HTTP/WebSocket”表述，以技术栈表和 ADR-02 的 SSE 裁决为准。
2. 后端只维护一个 `active_session`，但外部接口必须传递并校验 `session_id`，避免旧 SSE 事件污染新会话。
3. `RuntimeEvent` 是内部对象；SSE 对外暴露的是本文定义的 `SseEventDto`。
4. `MessageRecord` 是内部消息对象；前端使用本文定义的 `MessageDto`。`MessageDto` 可以是内部对象的受控投影。
5. 首轮报告必须暴露结构化 `initial_report_content`，不能只靠 Markdown 文本。
6. 接口层参数错误码 `invalid_request` 已同步纳入 `data_structure_design_v3.md` 的 `ErrorCode`。

---

## <a id="api2-02"></a>API2-02 全局协议与会话原则

### 协议

1. HTTP 请求和响应统一使用 `application/json; charset=utf-8`。
2. SSE 响应统一使用 `text/event-stream; charset=utf-8`。
3. 所有对象字段使用 `snake_case`。
4. 所有时间字段对外序列化为 ISO 8601 字符串。
5. 列表字段为空时返回 `[]`，不返回 `null`。
6. 只有明确可缺失的单值字段允许返回 `null`。

### HTTP Envelope

所有非 SSE HTTP 响应必须使用统一 envelope。

成功：

```json
{
  "ok": true,
  "session_id": "sess_123",
  "data": {}
}
```

失败：

```json
{
  "ok": false,
  "session_id": "sess_123_or_null",
  "error": {
    "error_code": "invalid_state",
    "message": "当前状态不允许该操作",
    "retryable": true,
    "stage": "chatting",
    "input_preserved": true
  }
}
```

### 会话

1. 第一版只有一个活跃会话：`SessionStore.active_session`。
2. `POST /api/repo/validate` 不创建会话。
3. `POST /api/repo` 创建新会话；若已有旧会话，服务端必须先执行切仓清理。
4. 除 `POST /api/repo/validate` 和 `POST /api/repo` 外，HTTP 请求必须携带 `X-Session-Id`。
5. SSE 因浏览器 `EventSource` 不能稳定携带自定义 header，必须通过 query 传 `session_id`。
6. 任何请求携带的 `session_id` 与当前活跃会话不一致时，服务端必须返回 `invalid_state`，SSE 场景必须发送 `error` 事件后关闭。

### 同步与异步边界

1. `POST /api/repo/validate` 只做格式校验，不访问文件系统，不访问 GitHub，不调用 `git`。
2. `POST /api/repo` 只同步完成请求参数校验、旧会话清理、新会话创建和流程启动，成功返回 `202 Accepted`。
3. 仓库可访问性错误、clone 错误、扫描错误、分析错误、LLM 首轮生成错误都通过 `/api/analysis/stream` 推送。
4. `POST /api/chat` 只同步接收用户消息并启动回答流程，成功返回 `202 Accepted`。
5. 多轮回答内容、回答失败、流式完成都通过 `/api/chat/stream` 推送。

---

## <a id="api2-03"></a>API2-03 外部 Wire DTO

本节定义前后端传输对象。内部实现可以使用 `data_structure_design_v3.md` 的对象，但对外只能暴露本文 DTO 中定义的字段。

### `SessionSnapshotDto`

```ts
type SessionSnapshotDto = {
  session_id: string | null
  status: SessionStatus
  sub_status: ConversationSubStatus | null
  view: ClientView
  repository: RepositorySummaryDto | null
  progress_steps: ProgressStepStateItem[]
  degradation_notices: DegradationFlagDto[]
  messages: MessageDto[]
  active_error: UserFacingErrorDto | null
}
```

约束：

1. `view` 必须由 [API2-06](#api2-06) 的映射表服务端生成。
2. `messages` 只返回当前会话内消息，不跨会话持久化。
3. `repository` 不得包含 `root_path` 或绝对真实路径。

### `RepositorySummaryDto`

```ts
type RepositorySummaryDto = {
  display_name: string
  source_type: "local_path" | "github_url"
  input_value: string
  primary_language: string | null
  repo_size_level: "small" | "medium" | "large" | null
  source_code_file_count: number | null
}
```

### `ProgressStepStateItem`

```ts
type ProgressStepStateItem = {
  step_key:
    | "repo_access"
    | "file_tree_scan"
    | "entry_and_module_analysis"
    | "dependency_analysis"
    | "skeleton_assembly"
    | "initial_report_generation"
  step_state: "pending" | "running" | "done" | "error"
}
```

### `MessageDto`

```ts
type MessageDto = {
  message_id: string
  role: "user" | "agent" | "system"
  message_type:
    | "initial_report"
    | "user_question"
    | "agent_answer"
    | "goal_switch_confirmation"
    | "stage_summary"
    | "error"
  created_at: string
  raw_text: string
  structured_content: StructuredMessageContentDto | null
  initial_report_content: InitialReportContentDto | null
  related_goal: LearningGoal | null
  suggestions: SuggestionDto[]
  streaming_complete: boolean
  error_state: MessageErrorStateDto | null
}
```

硬约束：

1. `message_type=initial_report` 时，`initial_report_content` 必须非空。
2. `message_type in {agent_answer, goal_switch_confirmation, stage_summary}` 时，`structured_content` 必须非空。
3. `role=user` 的消息 `structured_content` 和 `initial_report_content` 必须为 `null`。
4. 前端可以先渲染 `raw_text` 流式增量，但最终必须以结构化字段校正展示。

### `InitialReportContentDto`

对应 PRD OUT-1 与 IX-08 首轮报告结构。

```ts
type InitialReportContentDto = {
  overview: {
    summary: string
    confidence: ConfidenceLevel
    evidence_refs: string[]
  }
  focus_points: {
    title: string
    reason: string
    topic: LearningGoal
  }[]
  repo_mapping: {
    concept: LearningGoal
    explanation: string
    mapped_paths: string[]
    confidence: ConfidenceLevel
    evidence_refs: string[]
  }[]
  language_and_type: {
    primary_language: string
    project_types: {
      type: ProjectType
      reason: string
      confidence: ConfidenceLevel
      evidence_refs: string[]
    }[]
    degradation_notice: string | null
  }
  key_directories: {
    path: string
    role: string
    main_path_role: MainPathRole
    confidence: ConfidenceLevel
    evidence_refs: string[]
  }[]
  entry_section: {
    status: DerivedStatus
    entries: EntryCandidateDto[]
    fallback_advice: string | null
  }
  recommended_first_step: {
    target: string
    reason: string
    learning_gain: string
    evidence_refs: string[]
  }
  reading_path_preview: ReadingStepDto[]
  unknown_section: UnknownItemDto[]
  suggested_next_questions: SuggestionDto[]
}
```

硬约束：

1. 字段顺序必须按上面顺序生成和渲染。
2. 不允许用完整文件树 dump 替代 `key_directories`。
3. 非 Python 降级时，`entry_section.entries` 必须为空，`entry_section.fallback_advice` 必须说明当前语言暂不完整支持。

### `StructuredMessageContentDto`

对应 PRD OUT-11 六段式多轮回答。

```ts
type StructuredMessageContentDto = {
  focus: string
  direct_explanation: string
  relation_to_overall: string
  evidence_lines: EvidenceLineDto[]
  uncertainties: string[]
  next_steps: SuggestionDto[]
}
```

硬约束：

1. 六个字段语义顺序固定，渲染顺序不得改变。
2. `next_steps` 必须 1-3 条。
3. 如当前确实没有不确定项，`uncertainties` 必须包含一句“当前没有额外不确定项”，不能返回空数组。
4. 如当前没有可展示证据，`evidence_lines` 必须包含一条说明并关联 `confidence=unknown`，不能伪造证据。

### 最小复用 DTO

```ts
type SuggestionDto = {
  suggestion_id: string
  text: string
  target_goal: LearningGoal | null
}

type EvidenceLineDto = {
  text: string
  evidence_refs: string[]
  confidence: ConfidenceLevel | null
}

type EntryCandidateDto = {
  entry_id: string
  target_type: EntryTargetType
  target_value: string
  reason: string
  confidence: ConfidenceLevel
  rank: number
  evidence_refs: string[]
}

type ReadingStepDto = {
  step_no: number
  target: string
  target_type: ReadingTargetType
  reason: string
  learning_gain: string
  skippable: string | null
  next_step_hint: string | null
  evidence_refs: string[]
}

type UnknownItemDto = {
  unknown_id: string
  topic: UnknownTopic
  description: string
  related_paths: string[]
  reason: string | null
}

type DegradationFlagDto = {
  degradation_id: string
  type: DegradationType
  reason: string
  user_notice: string
  related_paths: string[]
}

type UserFacingErrorDto = {
  error_code: ErrorCode
  message: string
  retryable: boolean
  stage: SessionStatus
  input_preserved: boolean
}

type MessageErrorStateDto = {
  error: UserFacingErrorDto
  failed_during_stream: boolean
  partial_text_available: boolean
}

type ApiEnvelope<T> =
  | {
      ok: true
      session_id: string | null
      data: T
    }
  | {
      ok: false
      session_id: string | null
      error: UserFacingErrorDto
    }

type ValidateRepoData = {
  input_kind: "local_path" | "github_url" | "unknown"
  is_valid: boolean
  normalized_input: string | null
  message: string | null
}

type SubmitRepoData = {
  accepted: true
  status: SessionStatus
  sub_status: ConversationSubStatus | null
  view: ClientView
  repository: RepositorySummaryDto
  analysis_stream_url: string
}

type SendMessageData = {
  accepted: true
  status: "chatting"
  sub_status: "agent_thinking"
  user_message_id: string
  chat_stream_url: string
}

type ClearSessionData = {
  status: "idle"
  sub_status: null
  view: "input"
  cleanup_completed: boolean
}

type ValidateRepoResponse = ApiEnvelope<ValidateRepoData>
type SubmitRepoResponse = ApiEnvelope<SubmitRepoData>
type GetSessionResponse = ApiEnvelope<SessionSnapshotDto>
type SendMessageResponse = ApiEnvelope<SendMessageData>
type ClearSessionResponse = ApiEnvelope<ClearSessionData>
```

---

## <a id="api2-04"></a>API2-04 HTTP 路由硬契约

### 1. `POST /api/repo/validate`

用途：仓库输入的即时格式校验。

请求：

```json
{
  "input_value": "https://github.com/owner/repo"
}
```

成功响应：`200 OK`

```json
{
  "ok": true,
  "session_id": null,
  "data": {
    "input_kind": "github_url",
    "is_valid": true,
    "normalized_input": "https://github.com/owner/repo",
    "message": null
  }
}
```

格式不合法也返回 `200 OK`，但 `is_valid=false`：

```json
{
  "ok": true,
  "session_id": null,
  "data": {
    "input_kind": "unknown",
    "is_valid": false,
    "normalized_input": null,
    "message": "请输入本地仓库绝对路径或 https://github.com/owner/repo 格式的公开仓库 URL"
  }
}
```

硬约束：

1. 不创建会话。
2. 不检查本地路径是否存在。
3. 不访问 GitHub。
4. 不调用 `git`。

### 2. `POST /api/repo`

用途：创建或重置活跃会话，并启动仓库接入、扫描、分析和首轮报告生成。

请求：

```json
{
  "input_value": "C:\\repo\\demo"
}
```

成功响应：`202 Accepted`

```json
{
  "ok": true,
  "session_id": "sess_123",
  "data": {
    "accepted": true,
    "status": "accessing",
    "sub_status": null,
    "view": "analysis",
    "repository": {
      "display_name": "demo",
      "source_type": "local_path",
      "input_value": "C:\\repo\\demo",
      "primary_language": null,
      "repo_size_level": null,
      "source_code_file_count": null
    },
    "analysis_stream_url": "/api/analysis/stream?session_id=sess_123"
  }
}
```

请求参数非法：`400 Bad Request`

```json
{
  "ok": false,
  "session_id": null,
  "error": {
    "error_code": "invalid_request",
    "message": "请输入本地仓库绝对路径或 GitHub 公开仓库 URL",
    "retryable": true,
    "stage": "idle",
    "input_preserved": true
  }
}
```

硬约束：

1. 成功返回不表示分析完成。
2. 成功后前端必须立即连接 `analysis_stream_url`。
3. 如果旧会话存在，服务端必须先执行 [DS2-13](data_structure_design_v3.md#ds2-13) 清理顺序。
4. 仓库不存在、GitHub 不可访问、clone 超时等错误不得在成功响应中提前伪装成功结果；它们必须通过分析 SSE 的 `error` 事件发送。

### 3. `GET /api/session`

用途：查询当前活跃会话快照，用于页面刷新、SSE 重连、前端启动恢复。

请求头：

```text
X-Session-Id: sess_123
```

无活跃会话：`200 OK`

```json
{
  "ok": true,
  "session_id": null,
  "data": {
    "session_id": null,
    "status": "idle",
    "sub_status": null,
    "view": "input",
    "repository": null,
    "progress_steps": [],
    "degradation_notices": [],
    "messages": [],
    "active_error": null
  }
}
```

有活跃会话且 `X-Session-Id` 缺失：`200 OK`，返回当前活跃会话的 `SessionSnapshotDto`。这是第一版单用户本地部署的恢复裁决，用于页面刷新或前端内存状态丢失。

有活跃会话且 `X-Session-Id` 匹配：`200 OK`，返回 `SessionSnapshotDto`。

有活跃会话但 `X-Session-Id` 不匹配：`409 Conflict`，返回 `invalid_state`。

硬约束：

1. 该接口不得触发分析、LLM 调用或文件扫描。
2. 该接口不得返回敏感正文、绝对 `root_path` 或内部堆栈。
3. 前端不得用本地状态替代该快照作为真源。
4. 只有 `GET /api/session` 允许在有活跃会话时缺失 `X-Session-Id` 并返回当前快照；其他会话接口仍必须传入匹配的 `session_id`。

### 4. `POST /api/chat`

用途：提交用户追问、目标切换、深浅调整或阶段总结请求。

请求头：

```text
X-Session-Id: sess_123
```

请求：

```json
{
  "message": "只看入口"
}
```

成功响应：`202 Accepted`

```json
{
  "ok": true,
  "session_id": "sess_123",
  "data": {
    "accepted": true,
    "status": "chatting",
    "sub_status": "agent_thinking",
    "user_message_id": "msg_user_001",
    "chat_stream_url": "/api/chat/stream?session_id=sess_123"
  }
}
```

硬约束：

1. 仅 `status=chatting` 且 `sub_status=waiting_user` 时允许调用。
2. 空消息或纯空白消息返回 `400 Bad Request` + `invalid_request`。
3. 状态不匹配返回 `409 Conflict` + `invalid_state`。
4. 后端必须先写入 `MessageRecord(role=user, message_type=user_question)`，再启动 M6。
5. 真正回答内容只通过 `/api/chat/stream` 推送。

### 5. `DELETE /api/session`

用途：切换仓库或清空当前会话。

请求头：

```text
X-Session-Id: sess_123
```

成功响应：`200 OK`

```json
{
  "ok": true,
  "session_id": null,
  "data": {
    "status": "idle",
    "sub_status": null,
    "view": "input",
    "cleanup_completed": true
  }
}
```

硬约束：

1. 必须终止该会话所有未完成 SSE 流。
2. 必须清理 GitHub clone 临时目录。
3. 必须重置 `conversation.depth_level=default`。
4. 旧 `session_id` 立即失效。

---

## <a id="api2-05"></a>API2-05 SSE 事件硬契约

### 基础格式

所有 SSE 事件必须使用事件名作为类型，不得固定写成 `analysis_progress`。

```text
event: <event_type>
data: {"event_id":"evt_001","event_type":"<event_type>","session_id":"sess_123","occurred_at":"2026-04-12T10:00:00Z",...}

```

### `SseEventDto` 公共字段

```ts
type SseEventDto = {
  event_id: string
  event_type: RuntimeEventType
  session_id: string
  occurred_at: string
}
```

所有事件的 `data` JSON 必须包含 `event_type`，即使 SSE 原生 `event:` 已经写了事件名。

前端类型别名必须按流区分：

```ts
type AnalysisSseEvent =
  | StatusChangedEvent
  | AnalysisProgressEvent
  | DegradationNoticeEvent
  | AnswerStreamStartEvent
  | AnswerStreamDeltaEvent
  | AnswerStreamEndEvent
  | MessageCompletedEvent
  | ErrorEvent

type ChatSseEvent =
  | StatusChangedEvent
  | AnswerStreamStartEvent
  | AnswerStreamDeltaEvent
  | AnswerStreamEndEvent
  | MessageCompletedEvent
  | ErrorEvent
```

上述具体 event 类型字段以本节 JSON 示例为准；脚手架实现时应生成显式 TypeScript discriminated union，判别字段为 `event_type`。

### 允许事件

#### `status_changed`

```json
{
  "event_id": "evt_001",
  "event_type": "status_changed",
  "session_id": "sess_123",
  "occurred_at": "2026-04-12T10:00:00Z",
  "status": "analyzing",
  "sub_status": null,
  "view": "analysis"
}
```

#### `analysis_progress`

```json
{
  "event_id": "evt_002",
  "event_type": "analysis_progress",
  "session_id": "sess_123",
  "occurred_at": "2026-04-12T10:00:01Z",
  "step_key": "file_tree_scan",
  "step_state": "done",
  "user_notice": "文件树扫描完成",
  "progress_steps": [
    {"step_key": "repo_access", "step_state": "done"},
    {"step_key": "file_tree_scan", "step_state": "done"},
    {"step_key": "entry_and_module_analysis", "step_state": "running"},
    {"step_key": "dependency_analysis", "step_state": "pending"},
    {"step_key": "skeleton_assembly", "step_state": "pending"},
    {"step_key": "initial_report_generation", "step_state": "pending"}
  ]
}
```

#### `degradation_notice`

```json
{
  "event_id": "evt_003",
  "event_type": "degradation_notice",
  "session_id": "sess_123",
  "occurred_at": "2026-04-12T10:00:02Z",
  "degradation": {
    "degradation_id": "deg_001",
    "type": "large_repo",
    "reason": "source_code_file_count > 3000",
    "user_notice": "仓库较大，优先输出结构总览和阅读起点",
    "related_paths": []
  }
}
```

#### `answer_stream_start`

```json
{
  "event_id": "evt_004",
  "event_type": "answer_stream_start",
  "session_id": "sess_123",
  "occurred_at": "2026-04-12T10:00:03Z",
  "message_id": "msg_agent_init_001",
  "message_type": "initial_report"
}
```

#### `answer_stream_delta`

```json
{
  "event_id": "evt_005",
  "event_type": "answer_stream_delta",
  "session_id": "sess_123",
  "occurred_at": "2026-04-12T10:00:04Z",
  "message_id": "msg_agent_init_001",
  "delta_text": "## 仓库概览\n这个仓库...",
  "structured_delta": null
}
```

#### `answer_stream_end`

```json
{
  "event_id": "evt_006",
  "event_type": "answer_stream_end",
  "session_id": "sess_123",
  "occurred_at": "2026-04-12T10:00:05Z",
  "message_id": "msg_agent_init_001"
}
```

#### `message_completed`

```json
{
  "event_id": "evt_007",
  "event_type": "message_completed",
  "session_id": "sess_123",
  "occurred_at": "2026-04-12T10:00:06Z",
  "message": {
    "message_id": "msg_agent_init_001",
    "role": "agent",
    "message_type": "initial_report",
    "created_at": "2026-04-12T10:00:03Z",
    "raw_text": "...",
    "structured_content": null,
    "initial_report_content": {
      "overview": {
        "summary": "这是一个 Python Web 项目候选。",
        "confidence": "medium",
        "evidence_refs": ["ev_001"]
      },
      "focus_points": [],
      "repo_mapping": [],
      "language_and_type": {
        "primary_language": "Python",
        "project_types": [],
        "degradation_notice": null
      },
      "key_directories": [],
      "entry_section": {
        "status": "heuristic",
        "entries": [],
        "fallback_advice": null
      },
      "recommended_first_step": {
        "target": "README.md",
        "reason": "先确认项目用途和运行入口线索。",
        "learning_gain": "建立项目整体方向。",
        "evidence_refs": ["ev_001"]
      },
      "reading_path_preview": [],
      "unknown_section": [],
      "suggested_next_questions": []
    },
    "related_goal": "overview",
    "suggestions": [],
    "streaming_complete": true,
    "error_state": null
  },
  "status": "chatting",
  "sub_status": "waiting_user",
  "view": "chat"
}
```

#### `error`

```json
{
  "event_id": "evt_008",
  "event_type": "error",
  "session_id": "sess_123",
  "occurred_at": "2026-04-12T10:00:07Z",
  "error": {
    "error_code": "analysis_failed",
    "message": "分析过程出错，请重试或尝试其他仓库",
    "retryable": true,
    "stage": "analyzing",
    "input_preserved": true
  },
  "status": "analysis_error",
  "sub_status": null,
  "view": "input"
}
```

### `/api/analysis/stream`

用途：订阅首次仓库接入、扫描、分析、首轮报告生成。

请求：

```text
GET /api/analysis/stream?session_id=sess_123
```

允许事件：

1. `status_changed`
2. `analysis_progress`
3. `degradation_notice`
4. `answer_stream_start`
5. `answer_stream_delta`
6. `answer_stream_end`
7. `message_completed`
8. `error`

结束条件：

1. 发送 `message_completed` 且 `message.message_type=initial_report` 后，服务端必须关闭分析流。
2. 发送 `error` 后，服务端必须关闭分析流。
3. 旧会话被 `DELETE /api/session` 清理时，服务端必须关闭旧分析流。

重连要求：

1. 客户端连接后，服务端必须先发送当前 `status_changed` 快照。
2. 若已产生进度，必须发送最新 `analysis_progress` 快照。
3. 若首轮报告已经完成，必须直接发送最终 `message_completed` 后关闭。

### `/api/chat/stream`

用途：订阅多轮回答流。

请求：

```text
GET /api/chat/stream?session_id=sess_123
```

允许事件：

1. `status_changed`
2. `answer_stream_start`
3. `answer_stream_delta`
4. `answer_stream_end`
5. `message_completed`
6. `error`

硬约束：

1. `message_completed.message.message_type` 只允许 `agent_answer`, `goal_switch_confirmation`, `stage_summary`, `error`。
2. 深浅调整属于 `agent_answer`，不得自行新增 `depth_adjustment_confirmation` 或其他消息类型。
3. 一个用户消息最多对应一个终态 `message_completed`。
4. 流式失败时必须发送 `error`；如已有部分文本，最终 `MessageDto.error_state.partial_text_available=true`。
5. 旧会话被清理时必须关闭旧聊天流。

---

## <a id="api2-06"></a>API2-06 状态机与视图映射

### 全局状态

唯一允许状态迁移：

```text
idle -> accessing -> analyzing -> chatting
accessing -> access_error
analyzing -> analysis_error
access_error -> accessing
analysis_error -> accessing
chatting -> idle
access_error -> idle
analysis_error -> idle
```

说明：

1. `access_error -> accessing` 和 `analysis_error -> accessing` 只允许由新的 `POST /api/repo` 触发。
2. `chatting -> idle`、`access_error -> idle`、`analysis_error -> idle` 只允许由 `DELETE /api/session` 或新仓库提交前的清理触发。
3. 不允许 `chatting -> analyzing`。重新分析必须先清理旧会话，再创建新会话。

### 对话子状态

`ConversationSubStatus` 只在 `status=chatting` 时有效。

| `status` | 允许 `sub_status` |
|------|------|
| `idle` | `null` |
| `accessing` | `null` |
| `access_error` | `null` |
| `analyzing` | `null` |
| `analysis_error` | `null` |
| `chatting` | `waiting_user`, `agent_thinking`, `agent_streaming` |

### 前端视图映射

| `status` | `sub_status` | `view` |
|------|------|------|
| `idle` | `null` | `input` |
| `accessing` | `null` | `analysis` |
| `analyzing` | `null` | `analysis` |
| `chatting` | 任意 | `chat` |
| `access_error` | `null` | `input` |
| `analysis_error` | `null` | `input` |

### 输入禁用映射

| 场景 | 仓库输入 | 对话输入 | 建议按钮 |
|------|------|------|------|
| `idle` | 可用 | 不存在 | 不存在 |
| `accessing/analyzing` | 禁用 | 不存在 | 不存在 |
| `chatting + waiting_user` | 不存在 | 可用 | 可用 |
| `chatting + agent_thinking/agent_streaming` | 不存在 | 禁用 | 禁用 |
| 错误态 | 可用 | 不存在 | 不存在 |

---

## <a id="api2-07"></a>API2-07 模块间接口契约

### 路由层

路由层只负责：

1. 解析 HTTP 请求。
2. 校验 `session_id`。
3. 调用 M5。
4. 将 M5 产生的运行事件映射为 SSE。
5. 返回本文定义的 HTTP envelope。

路由层不得直接调用 M2/M3/M4/M6 绕过 M5。

### M1 `repo_access`

输入：`input_value: str`

输出：`RepositoryContext | UserFacingError`

硬约束：

1. 本地路径必须是绝对路径。
2. GitHub URL 仅允许 `https://github.com/{owner}/{repo}`。
3. 除 `git clone --depth=1` 外，不得启动任何仓库相关 shell 命令。
4. 成功输出必须补齐 `read_policy`。
5. M1 错误必须映射为 `UserFacingError`，不得抛出堆栈给路由层。

### M2 `file_tree_scan`

输入：`RepositoryContext`

输出：`FileTreeSnapshot`

硬约束：

1. 必须应用敏感文件规则与忽略规则。
2. `sensitive_matches.content_read` 必须为 `false`。
3. 不得读取 `sensitive_skipped` 文件正文。
4. 大仓库必须设置 `repo_size_level=large` 并标注 `degraded_scan_scope`。

### M3 `static_analysis`

输入：`FileTreeSnapshot`

输出：`AnalysisBundle`

硬约束：

1. 不得调用 LLM 生成分析事实。
2. 必须覆盖 PRD ANALYSIS 的 9 项最低产出。
3. 所有确定性或候选结论都必须绑定 `evidence_refs`；无证据时转入 `unknown_items`。
4. 非 Python 降级必须遵守 DS2-07：不得伪造 Python 入口、import、流程或分层。

### M4 `teaching_skeleton_assembly`

输入：`AnalysisBundle`

输出：`TeachingSkeleton`

硬约束：

1. 首轮骨架消费顺序必须对应 `InitialReportContentDto` 字段顺序。
2. `topic_index` 必须覆盖 `structure/entry/flow/layer/dependency/module/reading_path/unknown`。
3. `flow_section`, `layer_section`, `dependency_section` 可被首轮引用，但不得无节制展开取代主线。

### M5 `dialog_manager`

输入：用户请求 + `SessionContext` + M1-M4 产物

输出：状态变更、运行事件、`PromptBuildInput`、消息记录

硬约束：

1. M5 是唯一协调者。
2. 其他模块不得绕过 M5 直接改 `ConversationState`。
3. 每轮回答后必须更新 OUT-9 的跨轮状态最小集。
4. 切换仓库时必须按 DS2-13 清理顺序执行。
5. M5 必须把内部 `RuntimeEvent` 映射为本文 `SseEventDto`。

### M6 `answer_generator`

输入：`PromptBuildInput`

输出：流式文本 + `StructuredAnswer`

硬约束：

1. 只能消费 `PromptBuildInput`，不得直接读写完整 `SessionContext`。
2. 结构化输出必须满足 `OutputContract`。
3. `suggestions` 必须 1-3 条。
4. M6 prompt 不得包含敏感文件正文或内部错误堆栈。

---

## <a id="api2-08"></a>API2-08 M6 与首轮报告契约

### PromptBuildInput 组装

1. `scenario=initial_report`：必须携带完整 `TeachingSkeleton`，`topic_slice` 可为空。
2. `scenario=follow_up`：`topic_slice` 必须来自 `TeachingSkeleton.topic_index` 的受控切片。
3. `scenario=goal_switch`：必须携带目标切换后的主题切片，并生成一条 `goal_switch_confirmation`。
4. `scenario=depth_adjustment`：只改变 `depth_level`，不清空学习目标；最终 `MessageDto.message_type` 使用 `agent_answer`，`structured_content.focus` 明确说明讲解深度已调整，不新增 `MessageType`。
5. `scenario=stage_summary`：重点使用 `explained_items + history_summary`。

### OutputContract 默认值

```json
{
  "required_sections": [
    "focus",
    "direct_explanation",
    "relation_to_overall",
    "evidence",
    "uncertainty",
    "next_steps"
  ],
  "max_core_points": 4,
  "must_include_next_steps": true,
  "must_mark_uncertainty": true,
  "must_use_candidate_wording": true
}
```

深浅规则：

1. `shallow`：`max_core_points=2`，减少术语和代码片段。
2. `default`：`max_core_points=4`。
3. `deep`：`max_core_points=4`，可增加证据和最多 10 行的代码片段，但仍必须标注不确定项。

### 首轮报告生成

首轮报告有两个并行产物：

1. `raw_text`：用于 Markdown 流式展示。
2. `initial_report_content`：用于最终结构化渲染和前端验收。

硬约束：

1. `initial_report_content` 必须由 `TeachingSkeleton` 受控映射生成。
2. LLM 可以润色 `raw_text`，但不得新增没有证据支持的入口、流程、分层或依赖结论。
3. `message_completed` 时必须同时携带完整 `raw_text` 和完整 `initial_report_content`。
4. 首轮报告不得使用六段式 `structured_content` 替代 `initial_report_content`。

### 多轮回答生成

多轮回答有两个产物：

1. `raw_text`：用于流式展示。
2. `structured_content`：用于六段式最终渲染。

硬约束：

1. `structured_content.next_steps` 必须 1-3 条。
2. `structured_content.evidence_lines` 不得包含敏感文件正文。
3. 若用户要求“讲深一点”，仍不得把候选流程说成真实运行链。
4. 若 M6 无法稳定解析结构化区块，必须回退生成最小合格六段式，不得只返回一段自由文本。

---

## <a id="api2-09"></a>API2-09 前端集成契约

### Store

前端维护单一全局 store。

```ts
type ClientSessionStore = {
  sessionId: string | null
  currentView: "input" | "analysis" | "chat"
  status: SessionStatus
  subStatus: ConversationSubStatus | null
  repoDisplayName: string | null
  progressSteps: ProgressStepStateItem[]
  degradationNotices: DegradationFlagDto[]
  messages: MessageDto[]
  activeError: UserFacingErrorDto | null
}
```

硬约束：

1. `currentView` 只能由服务端响应或 SSE 事件更新。
2. `messages` 必须按 `message_id` 去重。
3. 同一 `message_id` 的 `answer_stream_delta` 必须原位追加，不得生成多条 Agent 消息。
4. 收到 `message_completed` 后，必须用完整 `MessageDto` 覆盖本地临时流式消息。
5. 收到旧 `session_id` 的事件必须丢弃。

### API Client

```ts
interface RepoApiClient {
  validate(inputValue: string): Promise<ValidateRepoResponse>
  submit(inputValue: string): Promise<SubmitRepoResponse>
  getSession(sessionId?: string): Promise<GetSessionResponse>
  clearSession(sessionId: string): Promise<ClearSessionResponse>
}

interface ChatApiClient {
  sendMessage(sessionId: string, message: string): Promise<SendMessageResponse>
}

interface StreamClient {
  connectAnalysis(sessionId: string, onEvent: (evt: AnalysisSseEvent) => void): CloseFn
  connectChat(sessionId: string, onEvent: (evt: ChatSseEvent) => void): CloseFn
}
```

硬约束：

1. `submit` 成功后必须立即连接 `analysis_stream_url`。
2. `sendMessage` 成功后必须确保 `chat_stream_url` 已连接。
3. `CloseFn` 必须在切换仓库、组件卸载、session 失效时调用。
4. 页面启动时应先调用 `getSession`，再决定进入 input/analysis/chat 视图。

### 组件调用

```ts
type RepoInputViewProps = {
  inputValue: string
  validationMessage: string | null
  submitting: boolean
  onChange(value: string): void
  onValidate(value: string): Promise<void>
  onSubmit(value: string): Promise<void>
}

type ChatInputProps = {
  disabled: boolean
  placeholder: string
  onSend(message: string): Promise<void>
}

type SuggestionButtonsProps = {
  disabled: boolean
  suggestions: SuggestionDto[]
  onPick(suggestionText: string): Promise<void>
}
```

硬约束：

1. `onPick` 等同于 `onSend(suggestion.text)`。
2. `ChatInput` 在 `disabled=true` 时不得触发发送。
3. `SuggestionButtons` 只渲染 1-3 条。
4. 首轮报告按 `initial_report_content` 区块渲染，多轮回答按 `structured_content` 六段渲染。

---

## <a id="api2-10"></a>API2-10 错误、降级与超时

### HTTP 状态码

| 状态码 | 场景 |
|------|------|
| `200 OK` | 同步完成的查询、校验、删除成功 |
| `202 Accepted` | 已接受并启动异步流程：`POST /api/repo`, `POST /api/chat` |
| `400 Bad Request` | 请求体缺字段、空消息、格式无法解析 |
| `409 Conflict` | `session_id` 不匹配、当前状态不允许操作 |
| `500 Internal Server Error` | 非流式请求内部失败，且无法映射到更具体错误 |

### 错误码

必须支持 `data_structure_design_v3.md` 的错误码：

1. `local_path_not_found`
2. `local_path_not_directory`
3. `local_path_not_readable`
4. `github_url_invalid`
5. `github_repo_inaccessible`
6. `git_clone_timeout`
7. `git_clone_failed`
8. `path_escape_detected`
9. `analysis_timeout`
10. `analysis_failed`
11. `llm_api_failed`
12. `llm_api_timeout`
13. `invalid_state`

接口层额外必须支持：

14. `invalid_request`

`invalid_request` 只用于 HTTP 请求参数错误，不用于仓库内容分析错误。

### 降级映射

| `DegradationType` | 前端行为 |
|------|------|
| `large_repo` | 分析页展示降级提示；首轮报告说明规模限制 |
| `non_python_repo` | 首轮报告使用非 Python 降级模板 |
| `entry_not_found` | 入口区块展示 fallback advice |
| `flow_not_reliable` | 流程相关回答展示 fallback advice，不伪造流程 |
| `layer_not_reliable` | 分层区块展示“启发式分层”或“当前未知” |
| `analysis_timeout` | 分析页展示“正在尝试降级分析” |

### 超时

| 场景 | 超时 |
|------|------|
| Git clone | 30 秒 |
| 小型仓库分析 | 30 秒 |
| 中型仓库分析 | 90 秒 |
| LLM 调用 | 60 秒 |

超时必须优先转换为面向用户的错误或降级，不得把底层堆栈发给前端。

---

## <a id="api2-11"></a>API2-11 安全硬约束

1. 任何 HTTP 响应、SSE payload、前端日志、后端用户可见日志都不得包含敏感文件正文或疑似密钥。
2. `EvidenceRef.content_excerpt` 若来自敏感文件，必须为 `null`。
3. 外显路径优先使用 `relative_path`；`root_path`、`real_path` 不直接展示给用户。
4. M6 prompt 不得包含 `sensitive_skipped` 文件正文、疑似 token、私钥、证书正文、内部堆栈。
5. 禁止任何接口提供执行仓库代码、安装依赖、运行测试、修改文件、生成 commit/PR 的能力。
6. 除 GitHub 公开仓库 shallow clone 外，不允许调用仓库相关外部命令。
7. 后端清理临时目录时只允许清理 M1 创建并登记在 `TempResourceSet.clone_dir` 的目录。

---

## <a id="api2-12"></a>API2-12 脚手架验收清单

后续脚手架 Agent 在实现前后必须逐条核对：

1. 路由文件包含 `/api/repo/validate`, `/api/repo`, `/api/session`, `/api/analysis/stream`, `/api/chat`, `/api/chat/stream`, `DELETE /api/session`。
2. `POST /api/repo` 和 `POST /api/chat` 返回 `202 Accepted`，不阻塞等待完整报告或完整回答。
3. SSE 的 `event:` 必须等于具体 `event_type`，`data` 内也必须包含 `event_type`。
4. 分析流和聊天流都按 `message_id` 聚合同一条 Agent 消息。
5. `message_completed` 会用完整 `MessageDto` 覆盖流式临时消息。
6. 首轮报告必须携带 `initial_report_content`，不能只携带六段式 `structured_content`。
7. 多轮回答必须携带六段式 `structured_content`。
8. 状态机必须使用 API2-06，不得使用 v1 的错误态箭头。
9. 页面刷新时必须通过 `GET /api/session` 恢复状态。
10. 旧 `session_id` 的 HTTP 请求返回 `409 invalid_state`；旧 SSE 事件必须关闭或被前端丢弃。
11. 非 Python 降级时不得伪造 Python 入口、import、流程或分层。
12. 所有确定性或候选结论必须绑定证据；无证据时进入 `unknown` 或 fallback advice。
13. 敏感文件只允许记录存在，不允许进入证据摘录、日志、prompt 或响应正文。
14. 切换仓库必须终止旧 SSE、清理旧会话、删除临时 clone 目录、重置深浅级别。
15. 前端输入框和建议按钮禁用状态必须由 `status + sub_status` 映射得到。
16. 前端不得自行推断入口、流程、分层、学习目标；必须消费服务端 DTO。
17. M3 不得调用 LLM 生成分析事实；M6 不得直接读写完整 `SessionContext`。
18. 首轮报告顺序必须是：概览、先抓什么、仓库映射、语言与类型、关键目录、入口候选、推荐第一步、阅读路径、不确定项、下一步建议。

---

*本文作为 `interface_hard_spec_v2.md` 的兼容修订版。后续脚手架 Agent 应优先引用 `docs/interface_hard_spec_v3.md`。若实现中发现本文与上位文档冲突，应回改本文或上位数据结构文档，而不是在代码中发明第三套契约。*
