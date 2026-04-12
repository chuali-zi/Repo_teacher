# Repo Tutor — 接口硬规范 v1

> **文档类型**：接口硬规范
> **面向对象**：后续实现 Agent / 前后端开发 / 模块集成负责人
> **适用范围**：第一版单 Agent、只读、教学型 Repo Tutor
> **日期**：2026-04-12

---

## 索引

| 编号 | 章节 | 说明 |
|------|------|------|
| [API-00](#api-00) | 文档依据与裁决优先级 | 本规范引用来源、版本优先级、冲突处理 |
| [API-01](#api-01) | 总体接口原则 | 全局协议、命名、状态、安全、幂等约束 |
| [API-02](#api-02) | 术语与公共对象 | 所有接口共用字段与公共 envelope |
| [API-03](#api-03) | 前后端 HTTP 接口 | REST 端点、请求响应、错误约束 |
| [API-04](#api-04) | 前后端 SSE 接口 | 事件流格式、事件类型、时序与结束条件 |
| [API-05](#api-05) | 模块间硬契约 | M1-M6 输入输出与禁止行为 |
| [API-06](#api-06) | M5 对话状态裁决 | 状态机、意图、跨轮保持、切仓清理 |
| [API-07](#api-07) | M6 回答生成契约 | PromptBuildInput、输出结构、流式解析约束 |
| [API-08](#api-08) | 前端内部 API / 函数契约 | Store、API Client、SSE 驱动、组件调用约束 |
| [API-09](#api-09) | 错误、降级与超时 | 错误码、降级映射、用户可感知行为 |
| [API-10](#api-10) | 安全硬约束 | 只读、敏感文件、路径越界、日志与 prompt 边界 |
| [API-11](#api-11) | 验收清单 | 后续 Agent 开发前后必须核对的接口验收点 |

---

## <a id="api-00"></a>API-00 文档依据与裁决优先级

### 直接依据

1. `docs/PRD_v5_agent.md`
2. `docs/interaction_design_v1.md`
3. `docs/technical_architecture_v2.md`
4. `docs/data_structure_design_v2.md`

### 优先级

1. 产品边界与输出要求：`PRD_v5_agent.md`
2. 交互行为与展示结构：`interaction_design_v1.md`
3. 技术分层、模块职责、通信方式：`technical_architecture_v2.md`
4. 结构化数据对象与枚举：`data_structure_design_v2.md`
5. 本文：对以上文档未明确处做接口层裁决；不得推翻上位文档边界

### 裁决结论

1. 前后端通信统一使用 `HTTP REST + SSE`，不使用 WebSocket。
2. 后端仍只维护单个 `active_session`，但对外接口显式返回并要求传递 `session_id`，用于防止前端持有过期流连接。
3. `data_structure_design_v2.md` 中“只定义内部 RuntimeEvent、不定义接口协议”的空缺，由本文补齐为稳定外部协议映射。
4. 所有前端展示内容必须源于结构化对象或其受控渲染结果，不能让前端自行猜测状态或补字段。

---

## <a id="api-01"></a>API-01 总体接口原则

### 协议原则

1. HTTP 请求与响应统一使用 `application/json; charset=utf-8`。
2. SSE 统一使用 `text/event-stream`。
3. 所有时间字段使用 ISO 8601 字符串。
4. 所有对象字段命名使用 `snake_case`。
5. 列表为空时返回空数组，不返回 `null`。
6. 可缺失单值字段才允许返回 `null`。

### 会话原则

1. 第一版后端仅允许一个活跃会话。
2. 客户端必须在所有需要会话上下文的请求中传 `session_id`。
3. 若 `session_id` 与当前活跃会话不一致，后端必须返回 `invalid_state`。
4. 切换仓库后，旧 `session_id` 立即失效。

### 状态原则

1. 服务端 `SessionStatus` 是唯一全局状态真源。
2. 前端 `currentView` 必须由服务端状态映射，不允许本地自由猜测。
3. `chatting + waiting_user` 时，输入框可用。
4. `chatting + agent_thinking/agent_streaming` 时，输入框与建议按钮必须禁用。

### 输出原则

1. 首轮报告必须按 PRD OUT-1 顺序输出。
2. 多轮回答必须遵守六段式结构顺序。
3. 所有候选性结论必须保留“候选/可能/启发式/基于当前证据推断”等措辞。
4. 非 Python 降级时，不得伪造 Python 入口、import、流程或分层。

---

## <a id="api-02"></a>API-02 术语与公共对象

### 公共请求头

| 字段 | 必填 | 说明 |
|------|------|------|
| `Content-Type: application/json` | POST/DELETE 是 | JSON 请求 |
| `X-Session-Id` | 除 `/api/repo/validate` 外按接口要求 | 活跃会话 ID |

### 成功响应 Envelope

```json
{
  "ok": true,
  "session_id": "sess_xxx",
  "data": {}
}
```

### 失败响应 Envelope

```json
{
  "ok": false,
  "session_id": "sess_xxx_or_null",
  "error": {
    "error_code": "analysis_failed",
    "message": "分析过程出错，请重试或尝试其他仓库",
    "retryable": true,
    "stage": "analyzing",
    "input_preserved": true
  }
}
```

### 公共对象来源

1. `RepositoryContext`、`FileTreeSnapshot`、`AnalysisBundle`、`TeachingSkeleton`、`ConversationState`、`PromptBuildInput`、`StructuredAnswer` 直接沿用 `data_structure_design_v2.md`。
2. 外部接口只暴露前端需要的最小字段，不直接回传完整内部对象，除非本文明确要求。

---

## <a id="api-03"></a>API-03 前后端 HTTP 接口

### 1. `POST /api/repo/validate`

用途：执行输入格式校验，不创建会话，不访问仓库内容。

请求：

```json
{
  "input_value": "https://github.com/owner/repo"
}
```

成功响应：

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

失败响应：

```json
{
  "ok": false,
  "session_id": null,
  "error": {
    "error_code": "github_url_invalid",
    "message": "请输入本地仓库路径或 GitHub URL",
    "retryable": true,
    "stage": "idle",
    "input_preserved": true
  }
}
```

硬约束：

1. 只做格式层校验。
2. 不检查路径是否存在。
3. 不调用 `git`。

### 2. `POST /api/repo`

用途：创建或重置活跃会话，启动仓库接入、扫描、分析、首轮报告生成。

请求：

```json
{
  "input_value": "C:\\repo\\demo"
}
```

成功响应：

```json
{
  "ok": true,
  "session_id": "sess_123",
  "data": {
    "status": "accessing",
    "view": "analysis",
    "repository": {
      "display_name": "demo",
      "source_type": "local_path",
      "input_value": "C:\\repo\\demo"
    }
  }
}
```

硬约束：

1. 调用成功仅表示“已接受并启动流程”，不表示分析已完成。
2. 首轮报告、进度、降级、错误必须通过 `/api/analysis/stream` 推送。
3. 若已存在活跃会话，服务端必须先按切仓清理顺序清理旧会话，再创建新会话。

### 3. `POST /api/chat`

用途：提交用户对话消息或显式目标切换/深浅调整指令。

请求头：`X-Session-Id: sess_123`

请求：

```json
{
  "message": "只看入口"
}
```

成功响应：

```json
{
  "ok": true,
  "session_id": "sess_123",
  "data": {
    "accepted": true,
    "status": "chatting",
    "sub_status": "agent_thinking",
    "user_message_id": "msg_user_001"
  }
}
```

硬约束：

1. 仅 `status=chatting` 且 `sub_status=waiting_user` 时允许调用。
2. 空消息、纯空白消息必须拒绝，返回 `invalid_state` 或参数错误类 4xx。
3. 真正回答内容必须通过 `/api/chat/stream` 推送。
4. 后端必须先写入 `MessageRecord(role=user, message_type=user_question)`，再启动 M6。

### 4. `DELETE /api/session`

用途：切换仓库，清空当前活跃会话。

请求头：`X-Session-Id: sess_123`

成功响应：

```json
{
  "ok": true,
  "session_id": null,
  "data": {
    "status": "idle",
    "view": "input",
    "cleanup_completed": true
  }
}
```

硬约束：

1. 必须先停止所有与该会话相关的流式输出。
2. 如存在临时 clone 目录，必须执行清理并更新 `cleanup_status`。
3. `conversation.depth_level` 必须重置为 `default`。

---

## <a id="api-04"></a>API-04 前后端 SSE 接口

### 1. `GET /api/analysis/stream`

用途：订阅仓库接入、分析、首轮报告生成阶段事件。

请求参数：`session_id`

事件格式：

```text
event: analysis_progress
data: {json}

```

事件类型与 payload：

1. `status_changed`

```json
{
  "session_id": "sess_123",
  "status": "accessing",
  "view": "analysis",
  "occurred_at": "2026-04-12T10:00:00Z"
}
```

2. `analysis_progress`

```json
{
  "session_id": "sess_123",
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

3. `degradation_notice`

```json
{
  "session_id": "sess_123",
  "degradation": {
    "type": "large_repo",
    "reason": "source_code_file_count > 3000",
    "user_notice": "仓库较大，优先输出结构总览和阅读起点"
  }
}
```

4. `answer_stream_start`

```json
{
  "session_id": "sess_123",
  "message_id": "msg_agent_init_001",
  "message_type": "initial_report"
}
```

5. `answer_stream_delta`

```json
{
  "session_id": "sess_123",
  "message_id": "msg_agent_init_001",
  "delta_text": "## 仓库概览\n这个仓库...",
  "structured_delta": null
}
```

6. `message_completed`

```json
{
  "session_id": "sess_123",
  "message": {
    "message_id": "msg_agent_init_001",
    "role": "agent",
    "message_type": "initial_report",
    "raw_text": "...",
    "structured_content": {
      "focus": "先建立入口、模块和分层框架",
      "direct_explanation": "...",
      "relation_to_overall": "...",
      "evidence_lines": [],
      "uncertainties": ["入口候选仍需进一步确认"],
      "next_steps": [
        {"suggestion_id": "s1", "text": "想了解启动流程怎么走？", "target_goal": "flow", "related_topic_refs": []}
      ]
    },
    "suggestions": [
      {"suggestion_id": "s1", "text": "想了解启动流程怎么走？", "target_goal": "flow", "related_topic_refs": []}
    ],
    "streaming_complete": true
  },
  "status": "chatting",
  "sub_status": "waiting_user",
  "view": "chat"
}
```

7. `error`

```json
{
  "session_id": "sess_123",
  "error": {
    "error_code": "analysis_failed",
    "message": "分析过程出错，请重试或尝试其他仓库",
    "retryable": true,
    "stage": "analyzing",
    "input_preserved": true
  }
}
```

结束条件：

1. 收到 `message_completed` 且 `message_type=initial_report` 后，分析流可由服务端主动关闭。
2. 收到 `error` 后，服务端可关闭流。

### 2. `GET /api/chat/stream`

用途：订阅多轮回答流。

请求参数：`session_id`

允许事件：

1. `status_changed`
2. `answer_stream_start`
3. `answer_stream_delta`
4. `message_completed`
5. `error`

硬约束：

1. `message_completed.message.message_type` 只允许 `agent_answer`、`goal_switch_confirmation`、`stage_summary`、`error`。
2. 一个用户消息最多对应一个终态 `message_completed`。
3. 若流式中失败，必须发 `error`；若存在部分文本，`message.error_state.partial_text_available=true`。
4. 前端必须以 `message_id` 聚合同一条流式消息，不能按 chunk 追加成多条消息。

---

## <a id="api-05"></a>API-05 模块间硬契约

### M1 `repo_access`

输入：`input_value: str`

输出：`RepositoryContext | UserFacingError`

硬约束：

1. 本地路径必须是绝对路径。
2. GitHub URL 仅允许 `https://github.com/{owner}/{repo}`。
3. 除 `git clone` 外不得启动任何仓库相关 shell 命令。
4. 成功输出必须补齐 `read_policy`。

### M2 `file_tree_scan`

输入：`RepositoryContext`

输出：`FileTreeSnapshot`

硬约束：

1. 必须应用敏感规则与忽略规则。
2. `sensitive_matches` 只能记录存在，不能带正文。
3. 大仓库必须设置 `repo_size_level=large` 并标注 `degraded_scan_scope`。

### M3 `static_analysis`

输入：`FileTreeSnapshot`

输出：`AnalysisBundle`

硬约束：

1. 不得调用 LLM 生产分析事实。
2. 必须覆盖 PRD ANALYSIS 的 9 项最低产出。
3. 非 Python 降级必须遵守 DS2-07 的空字段约束。
4. 所有确定性或候选结论都必须绑定 `evidence_refs`；无证据时转 `unknown`。

### M4 `teaching_skeleton_assembly`

输入：`AnalysisBundle`

输出：`TeachingSkeleton`

硬约束：

1. 首轮消费顺序必须严格使用 DS2-08 规定的 10 个区块顺序。
2. `topic_index` 必须覆盖 `structure/entry/flow/layer/dependency/module/reading_path/unknown`。
3. 首轮报告不能把 `flow_section`、`layer_section`、`dependency_section` 无节制展开到取代主骨架。

### M5 `dialog_manager`

输入：用户请求 + `SessionContext` + M1-M4 产物

输出：状态变更、`PromptBuildInput`、消息写入、运行时事件

硬约束：

1. M5 是唯一协调者。
2. 其他模块不得绕过 M5 直接改 `ConversationState`。
3. 切换仓库时必须按 DS2-13 清理顺序执行。

### M6 `answer_generator`

输入：`PromptBuildInput`

输出：流式文本 + `StructuredAnswer`

硬约束：

1. 只能消费 `PromptBuildInput`，不得直接读写 `SessionContext` 全对象。
2. 结构化输出必须满足 `OutputContract`。
3. `suggestions` 必须 1-3 条，且应避开已讲解内容。

---

## <a id="api-06"></a>API-06 M5 对话状态裁决

### 状态机

唯一允许的全局状态迁移：

```text
idle -> accessing -> analyzing -> chatting
idle <- access_error
idle <- analysis_error
chatting -> idle
```

说明：

1. `access_error`、`analysis_error` 为错误终态，用户重试后重新走标准路径。
2. 不允许 `chatting -> analyzing`，除非先 `DELETE /api/session` 再重新 `POST /api/repo`。

### 意图分类契约

输入：`user_message: str`

输出：

```json
{
  "intent_type": "follow_up | goal_switch | depth_adjustment | stage_summary | switch_repo",
  "target_goal": "overview | structure | entry | flow | module | dependency | layer | summary | null",
  "target_module_hint": "string | null",
  "depth_change": "shallow | default | deep | null"
}
```

硬约束：

1. 规则匹配优先，未匹配时归入 `follow_up`。
2. `只看某个模块` 必须尝试填 `target_module_hint`。
3. 深浅调整只改 `depth_level`，不得清空学习目标。
4. 阶段性总结不改当前仓库，不清空已讲解内容。

### 跨轮保持最小集

每轮回答后 M5 必须更新：

1. `current_learning_goal`
2. `current_stage`
3. `current_focus_module_id`
4. `current_entry_candidate_id`
5. `current_flow_id`
6. `current_layer_view_id`
7. `explained_items`
8. `last_suggestions`
9. `messages`
10. `history_summary`

---

## <a id="api-07"></a>API-07 M6 回答生成契约

### PromptBuildInput 组装规则

1. `scenario=initial_report` 时，`topic_slice` 可为空，必须携带完整 `teaching_skeleton`。
2. `scenario=follow_up` 时，`topic_slice` 必须来自 `TeachingSkeleton.topic_index` 的受控切片。
3. `scenario=goal_switch` 时，必须同时携带切换后主题切片与切换确认语义。
4. `scenario=stage_summary` 时，重点使用 `explained_items + history_summary`。
5. `scenario=depth_adjustment` 时，回答内容仍走六段式，不单独定义另一套格式。

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

深浅裁决：

1. `shallow` 时 `max_core_points=2`。
2. `default/deep` 时 `max_core_points=4`。
3. `deep` 可增加证据和代码片段，但单段代码不超过 10 行。

### 流式解析契约

1. `llm_caller` 负责文本 chunk 流。
2. `response_parser` 负责在流结束后输出唯一的 `StructuredAnswer`。
3. 若流中无法稳定解析结构化字段，M6 必须回退生成最小合格结构：
   `focus`、`direct_explanation`、`relation_to_overall` 可为字符串汇总；`evidence_lines`、`uncertainties`、`next_steps` 不能为空数组。
4. `StructuredAnswer.used_evidence_refs` 必须为本轮实际引用证据，而不是教学骨架全量证据。

---

## <a id="api-08"></a>API-08 前端内部 API / 函数契约

### Store 契约

前端必须维护单一全局 store：`ClientSessionStore`。

```ts
type ClientSessionStore = {
  sessionId: string | null
  currentView: "input" | "analysis" | "chat"
  status: SessionStatus
  subStatus: ConversationSubStatus | null
  repoDisplayName: string | null
  progressSteps: ProgressStepStateItem[]
  degradationNotices: DegradationFlag[]
  messages: MessageRecord[]
  activeError: UserFacingError | null
}
```

硬约束：

1. `currentView` 只能由服务端状态事件驱动更新。
2. `messages` 必须以 `message_id` 去重。
3. 同一 `message_id` 的流式内容必须原位增量更新。
4. 收到 `DELETE /api/session` 成功后，store 必须整体复位。

### API Client 契约

```ts
interface RepoApiClient {
  validate(inputValue: string): Promise<ValidateRepoResponse>
  submit(inputValue: string): Promise<SubmitRepoResponse>
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

1. `submit` 成功后，前端必须立即建立 `analysis` SSE 连接。
2. `sendMessage` 成功后，前端必须确保 `chat` SSE 已连接；若无连接先重连再等待流。
3. `CloseFn` 必须在切换仓库或组件卸载时调用，防止旧流污染新会话。

### 组件函数契约

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
  suggestions: Suggestion[]
  onPick(suggestionText: string): Promise<void>
}
```

硬约束：

1. `onPick` 语义等同 `onSend(suggestion.text)`。
2. `ChatInput` 在 `disabled=true` 时不得触发发送。
3. `SuggestionButtons` 数量必须限制为 1-3 个。

### 渲染契约

1. 首轮报告必须渲染为一个 `message_type=initial_report` 的单条 Agent 消息。
2. 多轮回答必须渲染为一个 `message_type in {agent_answer, goal_switch_confirmation, stage_summary}` 的单条 Agent 消息。
3. 置信度标签必须忠实显示 `high/medium/low/unknown`，不得自行重命名。
4. 证据路径必须以代码样式展示。

---

## <a id="api-09"></a>API-09 错误、降级与超时

### 错误码映射

必须支持以下 `ErrorCode`：

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

### 降级映射

`DegradationType -> 前端行为`：

1. `large_repo`：分析页展示降级提示；首轮报告展示规模限制说明。
2. `non_python_repo`：首轮报告切换为降级模板。
3. `entry_not_found`：入口区块展示 fallback advice。
4. `flow_not_reliable`：流程区块展示 fallback advice。
5. `layer_not_reliable`：分层区块展示“启发式分层”或“当前未知”。
6. `analysis_timeout`：分析页展示“正在尝试降级分析”。

### 超时裁决

1. Git clone 超时：30 秒。
2. 小型仓库分析总超时：30 秒。
3. 中型仓库分析总超时：90 秒。
4. LLM 超时：60 秒。
5. 超时优先走面向用户错误或降级，不暴露底层异常。

---

## <a id="api-10"></a>API-10 安全硬约束

1. 任何接口不得返回敏感文件正文或疑似密钥。
2. `EvidenceRef.content_excerpt` 若来自敏感文件，必须为 `null`。
3. 前端日志、后端日志、SSE payload 均不得包含 `internal_detail` 以外的堆栈直出给用户。
4. M6 prompt 不得包含：
   `sensitive_skipped` 文件正文、疑似 token、私钥、证书正文。
5. 路径相关外显字段统一使用 `relative_path` 或可展示路径，`root_path` 不直接给用户。
6. 禁止任何接口提供执行仓库代码、安装依赖、运行测试、修改文件的能力。

---

## <a id="api-11"></a>API-11 验收清单

后续 Agent 在实现前后必须逐条核对：

1. `POST /api/repo` 只返回接收成功，不同步阻塞首轮报告全文。
2. 首轮分析进度与首轮报告必须通过 `/api/analysis/stream` 推送。
3. 多轮回答必须通过 `/api/chat/stream` 推送，且按 `message_id` 聚合为单条消息。
4. 全局状态只允许 `idle/accessing/access_error/analyzing/analysis_error/chatting`。
5. 多轮回答必须符合六段式结构，顺序不能乱。
6. 首轮报告必须符合 OUT-1 顺序，不能退化成文件树 dump。
7. 非 Python 降级时，`entry_candidates/import_classifications/flow_summaries` 不得伪造内容。
8. 所有确定性结论必须绑定证据；无证据时输出 `unknown` 或 fallback advice。
9. 敏感文件只允许记录存在，不允许进入证据摘录、日志、提示词或响应正文。
10. 切换仓库时必须终止旧 SSE、清理旧会话、删除临时目录、重置深浅级别。
11. 前端输入框与建议按钮禁用状态必须严格跟随 `sub_status`。
12. 前端不得本地推导学习目标、分层结果、入口候选，必须以服务端结构化数据为准。

---

*本文是 `PRD_v5_agent.md`、`interaction_design_v1.md`、`technical_architecture_v2.md`、`data_structure_design_v2.md` 之间的接口层裁决文档。若后续实现发现与上位文档冲突，应以上位文档为准并回改本文，而不是在代码中私自发明新契约。*
