# web_v4 前后端接口与沟通协议

本文档是 `web_v4/RepoTutor.html` 对后端的完整接口需求。它不是现有 `backend/`
运行时的增量说明，而是给 `new_kernel` 第一版实现用的前后端契约。

## 1. 页面能力拆解

`web_v4` 当前页面有 8 条用户可见路径，每条都需要后端接口支撑：

| 前端区域 | 前端状态/动作 | 后端职责 |
| --- | --- | --- |
| 顶部 GitHub 输入条 | 输入 `owner/repo` 或 GitHub URL，点击解析 | 规范化 GitHub URL，验证公开可访问，克隆或接入仓库，扫描文件树，创建 session |
| REPO PARSER 日志 | 显示解析进度 | 通过 SSE 推送仓库接入阶段日志、进度、错误 |
| Agent Status + 小宠物 | 渲染 `idle/thinking/acting/scanning/teaching/researching/error` | 提供独立状态钩子 `GET /api/v4/agent/status`，并在 SSE 中推送 `agent_status` |
| 主聊天区 | 普通聊天与教学 agent | 接收用户问题，运行 `orient -> read -> teach`，流式输出回答 |
| 深度研究模式 | 生成长报告 | 使用同一聊天入口，`mode=deep`，额外推送深度研究进度 |
| 左侧术语解释器 | 简短解释术语 | 无需阻塞主 session，独立返回 2-3 句中文解释，可携带 session 上下文 |
| 右侧教学代码框 | 显示当前教学片段 | 在仓库解析完成或聊天过程中推送 `teaching_code` 事件 |
| 底部状态栏 | 显示模式、仓库加载状态、中断提示 | 从 session 状态、agent 状态和 cancel 接口派生 |

## 2. 协议总原则

- 所有 JSON REST 响应使用统一 envelope。
- `session_id` 是前端后端所有主流程的关联键。
- 需要连续渲染的过程一律走 SSE，不用轮询模拟过程日志。
- `GET /api/v4/agent/status` 是明确的状态钩子，给小宠物和状态面板使用；SSE 里的
  `agent_status` 是同一对象的事件版本。
- 主聊天和深度研究共用消息接口，靠 `mode=chat|deep` 区分。
- 副聊天栏术语解释使用独立接口，不改变主聊天状态，不抢占主 agent。
- 后端内部工具日志不能直接进入用户正文；正文只来自 teaching/writer 阶段。

统一响应：

```json
{
  "ok": true,
  "session_id": "sess_abc123",
  "data": {}
}
```

失败响应：

```json
{
  "ok": false,
  "session_id": "sess_abc123",
  "error": {
    "error_code": "github_repo_inaccessible",
    "message": "无法访问这个 GitHub 仓库。",
    "retryable": true,
    "stage": "repo_parse",
    "input_preserved": true,
    "internal_detail": null
  }
}
```

## 3. Agent 状态钩子

### `GET /api/v4/agent/status?session_id=...`

作用：返回当前 agent 状态，前端用于 `AgentStatusPanel`、`DesktopPet`、底部状态栏。

响应 `data`：

```json
{
  "session_id": "sess_abc123",
  "state": "scanning",
  "phase": "scanning_tree",
  "label": "扫描代码",
  "pet_mood": "scan",
  "pet_message": "翻找文件中",
  "current_action": "读取仓库文件树",
  "current_target": "src/",
  "metrics": {
    "llm_call_count": 1,
    "tool_call_count": 4,
    "token_count": 3800,
    "elapsed_ms": 9210
  },
  "updated_at": "2026-04-26T03:30:00Z"
}
```

状态枚举：

| `state` | 前端含义 | 常见后端阶段 |
| --- | --- | --- |
| `idle` | 无任务 | 等用户输入 |
| `thinking` | LLM 正在理解问题 | orient/planning |
| `acting` | 正在调用工具 | read_file/search/list_dir |
| `scanning` | 仓库解析中 | resolve/clone/scan |
| `teaching` | 正在组织教学回答 | writer/streaming answer |
| `researching` | 深度研究中 | deep planning/sweep/report |
| `error` | 当前任务失败 | 任意阶段错误 |

后端必须保证：当主流程进入新阶段时，先写入/广播 `agent_status`，再推送该阶段的其它事件。

## 4. GitHub URL 解析与仓库接入

### `POST /api/v4/github/resolve`

作用：纯解析和验证输入，不创建 session。用于未来做输入框即时校验。

请求：

```json
{
  "input_value": "owner/repo"
}
```

响应 `data`：

```json
{
  "input_kind": "github_url",
  "is_valid": true,
  "normalized_url": "https://github.com/owner/repo",
  "owner": "owner",
  "repo": "repo",
  "default_branch": "main",
  "display_name": "owner/repo",
  "message": "GitHub 仓库地址有效"
}
```

### `POST /api/v4/repositories`

作用：创建仓库教学 session，并启动仓库接入流程。

请求：

```json
{
  "input_value": "https://github.com/owner/repo",
  "branch": null,
  "mode": "chat"
}
```

响应状态码：`202 Accepted`

响应 `data`：

```json
{
  "accepted": true,
  "session_id": "sess_abc123",
  "repository": {
    "repo_id": "repo_abc123",
    "display_name": "owner/repo",
    "source": "github_url",
    "github": {
      "owner": "owner",
      "repo": "repo",
      "normalized_url": "https://github.com/owner/repo",
      "default_branch": "main",
      "resolved_branch": "main",
      "commit_sha": null
    },
    "primary_language": null,
    "file_count": 0,
    "status": "connecting"
  },
  "agent_status": {
    "session_id": "sess_abc123",
    "state": "scanning",
    "phase": "resolving_github",
    "label": "扫描代码",
    "pet_mood": "scan",
    "pet_message": "翻找文件中",
    "current_action": "解析 GitHub 地址",
    "current_target": "owner/repo",
    "metrics": {
      "llm_call_count": 0,
      "tool_call_count": 0,
      "token_count": 0,
      "elapsed_ms": 0
    },
    "updated_at": "2026-04-26T03:30:00Z"
  },
  "repo_stream_url": "/api/v4/repositories/stream?session_id=sess_abc123",
  "status_url": "/api/v4/agent/status?session_id=sess_abc123"
}
```

### `GET /api/v4/repositories/stream?session_id=...`

SSE 事件名：

- `agent_status`
- `repo_parse_log`
- `repo_connected`
- `teaching_code`
- `answer_stream_start`
- `answer_stream_delta`
- `answer_stream_end`
- `message_completed`
- `deep_research_progress`
- `error`

**事件过滤规则（与 `/api/v4/chat/stream` 互斥，避免双流重复推送）**：

后端在 repo stream 上对每条事件按 `turn_id` 字段过滤后再下发：

| 事件 `turn_id` | 是否在 repo stream 下发 | 场景 |
| --- | --- | --- |
| `null` / 缺省 | ✅ | 解析阶段事件（`agent_status`、`repo_parse_log`、`repo_connected`、解析期 `error` 等） |
| 等于 `session.auto_onboarding_turn_id` | ✅ | §4.4 自动 onboarding turn 的全部事件（`answer_stream_*`、`message_completed`、`deep_research_progress`、`teaching_code`） |
| 任意其它 `turn_id` | ❌ | 用户主动通过 `POST /api/v4/chat/messages` 启动的 turn —— 这些事件**只**通过 `/api/v4/chat/stream?session_id=...&turn_id=...` 下发 |

> **协议不变量**：同一条 SSE 事件**不会同时出现在** repo stream 和 chat stream 上。前端在解析期与 onboarding 期只需订阅 repo stream；用户发送 chat message 后，应订阅 chat stream 接收该 turn 的应答事件。如果前端为了持续监听后台状态保留 repo stream 处于 OPEN，**不会**收到该 chat turn 的 `answer_stream_delta` 重复副本。

`repo_parse_log`：

```json
{
  "event_id": "evt_001",
  "event_type": "repo_parse_log",
  "session_id": "sess_abc123",
  "occurred_at": "2026-04-26T03:30:01Z",
  "log": {
    "line_id": "log_001",
    "stage": "scanning_tree",
    "level": "info",
    "text": "拉取文件树...",
    "path": null,
    "progress": 0.35
  }
}
```

`repo_connected`：

```json
{
  "event_id": "evt_020",
  "event_type": "repo_connected",
  "session_id": "sess_abc123",
  "occurred_at": "2026-04-26T03:30:08Z",
  "repository": {
    "repo_id": "repo_abc123",
    "display_name": "owner/repo",
    "source": "github_url",
    "github": {
      "owner": "owner",
      "repo": "repo",
      "normalized_url": "https://github.com/owner/repo",
      "default_branch": "main",
      "resolved_branch": "main",
      "commit_sha": "abc123"
    },
    "primary_language": "TypeScript",
    "file_count": 128,
    "status": "ready"
  },
  "initial_message": "仓库「owner/repo」解析完成，可以开始提问。",
  "current_code": {
    "snippet_id": "code_001",
    "path": "src/core/scheduler.ts",
    "language": "typescript",
    "start_line": 1,
    "end_line": 42,
    "title": "首个教学片段",
    "reason": "这是当前仓库最适合作为入口的核心调度代码。",
    "code": "type Priority = 'immediate' | 'normal' | 'low';\n..."
  }
}
```

`initial_message` 只是仓库连接完成提示，用于前端更新解析状态或展示连接完成文案；它本身不表示
后端追加了普通 chat message。`RepoConnectedEvent` 字段列表保持稳定——前端无需任何额外字段；
后端不在此事件上挂 `auto_turn_id` 之类的占位字段，自动 onboarding 的 `turn_id` 在后续
`AnswerStreamStartEvent` 事件中暴露。详见 §4.4。

### 4.4 自动 onboarding 触发协议

仓库接入完成后，后端会自动触发一条 `mode=deep, report_kind=repo_onboarding` 的系统 turn，
向前端流式吐一份"模块阅读指南"。整套链路只占用既有的 `repositories/stream` SSE 通道，无新增
HTTP 接口、无新增事件类型、无新增字段。

触发条件：

- `POST /api/v4/repositories` 创建会话且 parse pipeline 全程成功（后端内部 `connected_data is not None`）。
- parse 中途任意阶段失败，不触发自动 onboarding，直接走常规 `error` 事件路径。
- 服务端在 emit `repo_connected` 事件之后，紧接着内部调用：
  ```
  TurnRuntime.start_turn(
      state=session,
      initiator="system",
      request=SendTeachingMessageRequest(
          message="<由后端注入的中文 seed，前端不渲染>",
          mode=ChatMode.DEEP,
          report_kind=ReportKind.REPO_ONBOARDING,
      ),
  )
  ```
- 前端不需要主动调用任何接口，只需保持订阅 `GET /api/v4/repositories/stream?session_id=...` 一个流。

事件序列（与 `deep_research/AGENTS.md` §4.2 一致）：

```
agent_status (scanning -> ...)              # parse 阶段
repo_parse_log * N
repo_connected
agent_status (researching)                   # 自动 turn 启动
deep_research_progress (phase=triage)
deep_research_progress (phase=decompose)
deep_research_progress (phase=investigate, k/N) * N
agent_status (streaming/researching)         # 进入 compose
answer_stream_start                          # turn_id 在此事件中暴露
answer_stream_delta * many
answer_stream_end
message_completed                            # message.kind == "repo_onboarding"
agent_status (idle_after_teach)
```

前端读取规约：

- 从 `AnswerStreamStartEvent.turn_id` 取本次 onboarding 的 `turn_id`；不要去 `repo_connected`
  上找 `auto_turn_id`，它不存在也不会被加入。
- `message_completed.message.kind == "repo_onboarding"` 是判定本条消息走"模块阅读指南"
  渲染分支的唯一依据；普通对话用 `kind == "answer"`。
- 用户可以随时 `POST /api/v4/control/cancel` 主动中断；后端在 ≤5s 内 emit
  `RunCancelledEvent`，并把 agent_status 落回 idle/cancelled。

重复触发：

- 同 session 二次 `POST /api/v4/repositories`（用户换仓）：服务端先 cancel 当前
  onboarding turn，等其自然走完 finally；随后 reset session state（清 `messages` /
  `scratchpad` / `repository` / `repo_root` / `current_code` / `parse_log`）；再启动新一轮
  parse + 自动 onboarding。
- 用户主动 `POST /api/v4/chat/messages` 带 `mode=deep, report_kind=repo_onboarding`：
  与自动触发等价，允许重新生成；`active_turn_id` 互斥保护已有，不需要前端额外逻辑。

## 5. 主聊天与教学 agent

### `POST /api/v4/chat/messages`

作用：提交主聊天消息。普通教学和深度研究都走这个接口。

请求头：

```text
X-Session-Id: sess_abc123
```

请求：

```json
{
  "message": "这个仓库的调度器怎么工作？",
  "mode": "chat",
  "client_message_id": "client_msg_001",
  "report_kind": "answer"
}
```

`mode=chat`：短教学回答，目标是解释一个当前点。  
`mode=deep`：深度研究报告，目标是完整结构分析，允许更长时间和更多阶段事件。

`report_kind` 字段（可选，默认 `"answer"`）：

- 类型：枚举字符串 `"answer" | "repo_onboarding"`。
- 默认值：`"answer"`，与既有 chat 行为完全一致。
- 校验规则：`mode=deep` 必须搭配 `report_kind=repo_onboarding`；`mode=chat` 必须搭配 `report_kind=answer`。其它组合后端返回 `ApiError(error_code=invalid_request)`。
- `repo_onboarding` 路径只服务于"仓库接入完成后自动生成入门导读"，前端通常不需要主动传，由后端在 §4.4 描述的链路中自行注入；用户主动重生成 onboarding 时也可显式传 `mode=deep, report_kind=repo_onboarding`。

响应状态码：`202 Accepted`

响应 `data`：

```json
{
  "accepted": true,
  "session_id": "sess_abc123",
  "turn_id": "turn_001",
  "user_message_id": "msg_user_001",
  "chat_stream_url": "/api/v4/chat/stream?session_id=sess_abc123&turn_id=turn_001",
  "agent_status": {
    "session_id": "sess_abc123",
    "state": "thinking",
    "phase": "planning",
    "label": "思考中",
    "pet_mood": "think",
    "pet_message": "努力思考中",
    "current_action": "理解问题并规划阅读路径",
    "current_target": null,
    "metrics": {
      "llm_call_count": 1,
      "tool_call_count": 0,
      "token_count": 900,
      "elapsed_ms": 100
    },
    "updated_at": "2026-04-26T03:31:00Z"
  }
}
```

### `GET /api/v4/chat/stream?session_id=...&turn_id=...`

事件顺序要求：

1. `agent_status(state=thinking)`
2. 可选 `agent_status(state=acting)`，每次工具调用前后都要更新摘要
3. `agent_status(state=teaching|researching)`
4. `answer_stream_start`
5. 多个 `answer_stream_delta`
6. 可选 `teaching_code`
7. `answer_stream_end`
8. `message_completed`
9. `agent_status(state=teaching)` 或 `agent_status(state=idle)`，取决于是否保持教学态

`answer_stream_delta`：

```json
{
  "event_id": "evt_101",
  "event_type": "answer_stream_delta",
  "session_id": "sess_abc123",
  "occurred_at": "2026-04-26T03:31:04Z",
  "turn_id": "turn_001",
  "message_id": "msg_agent_001",
  "delta_text": "这个调度器的核心是把任务按 deadline 排序，"
}
```

`message_completed`：

```json
{
  "event_id": "evt_130",
  "event_type": "message_completed",
  "session_id": "sess_abc123",
  "occurred_at": "2026-04-26T03:31:10Z",
  "message": {
    "message_id": "msg_agent_001",
    "role": "assistant",
    "mode": "chat",
    "kind": "answer",
    "content": "完整教学回答...",
    "created_at": "2026-04-26T03:31:10Z",
    "streaming_complete": true,
    "suggestions": [
      "接下来可以看 scheduler 如何被组件层调用。"
    ]
  },
  "agent_status": {
    "session_id": "sess_abc123",
    "state": "teaching",
    "phase": "idle_after_teach",
    "label": "教学中",
    "pet_mood": "teach",
    "pet_message": "等待你的下一个问题",
    "current_action": "等待追问",
    "current_target": null,
    "metrics": {
      "llm_call_count": 3,
      "tool_call_count": 5,
      "token_count": 7600,
      "elapsed_ms": 10300
    },
    "updated_at": "2026-04-26T03:31:10Z"
  }
}
```

`message.kind` 字段（在响应里出现的 `ChatMessage`，包括 `MessageCompletedEvent.message`、`session` 快照里的历史消息列表等）：

- 类型：枚举字符串 `"answer" | "repo_onboarding"`。
- 历史 / 兼容默认值：`"answer"`，旧消息和新写入的普通教学消息一律落到这一档。
- 渲染规约：前端依据 `kind` 决定面板归属——`kind="repo_onboarding"` 通常渲染为"模块阅读指南"面板（导读卡片），`kind="answer"` 仍走常规对话流。`mode` 字段保留原义（`chat | deep`），不替代 `kind`。

## 6. 术语解释副聊天栏

### `POST /api/v4/sidecar/explain`

作用：解释术语，不改变主聊天状态。后端可以读取当前 session 的仓库上下文，但不能启动仓库读取流程。

请求：

```json
{
  "term": "Hook",
  "session_id": "sess_abc123",
  "context": {
    "current_repo": "owner/repo",
    "current_file": "src/core/scheduler.ts"
  }
}
```

响应 `data`：

```json
{
  "term": "Hook",
  "explanation": "Hook 是 React 里让函数组件使用状态和副作用的机制。你可以把它理解成组件和运行时之间的约定入口。",
  "short_label": "状态钩子",
  "related_paths": []
}
```

## 7. 教学代码片段

教学代码片段可以通过两个渠道出现：

- `repo_connected.current_code`：仓库解析完成后的首个入口片段。
- `teaching_code` SSE：聊天或深度研究过程中切换教学焦点。

`teaching_code`：

```json
{
  "event_id": "evt_090",
  "event_type": "teaching_code",
  "session_id": "sess_abc123",
  "occurred_at": "2026-04-26T03:31:03Z",
  "snippet": {
    "snippet_id": "code_002",
    "path": "src/core/reconciler.ts",
    "language": "typescript",
    "start_line": 12,
    "end_line": 38,
    "title": "当前解释片段",
    "reason": "回答正在解释 reconciler 与 scheduler 的关系。",
    "code": "export function reconcile(...) {\n  ...\n}"
  }
}
```

## 8. Session 快照与恢复

### `GET /api/v4/session?session_id=...`

作用：刷新页面后恢复 UI。

响应 `data` 包含：

- `session_id`
- `repository`
- `agent_status`
- `parse_log`
- `messages`
- `current_code`
- `mode`

前端恢复规则：

- `messages` 直接渲染到主聊天。
- `parse_log` 恢复到 REPO PARSER；如果 `repository.status=ready`，`parseState=done`。
- `current_code` 恢复到右侧代码框。
- `agent_status.state` 恢复小宠物状态。

## 9. 中断与错误

### `POST /api/v4/control/cancel`

请求头：

```text
X-Session-Id: sess_abc123
```

请求：

```json
{
  "reason": "user_escape"
}
```

响应 `data`：

```json
{
  "cancelled": true,
  "session_id": "sess_abc123",
  "agent_status": {
    "session_id": "sess_abc123",
    "state": "idle",
    "phase": "cancelled",
    "label": "待机中",
    "pet_mood": "idle",
    "pet_message": "已中断",
    "current_action": null,
    "current_target": null,
    "metrics": {
      "llm_call_count": 0,
      "tool_call_count": 0,
      "token_count": 0,
      "elapsed_ms": 0
    },
    "updated_at": "2026-04-26T03:32:00Z"
  }
}
```

错误事件必须是 terminal event：一个 run 失败时，最后必须推送 `error`，然后推送
`agent_status(state=error)` 或 `agent_status(state=idle)`。

## 10. 前端事件映射

| SSE 事件 | 前端处理 |
| --- | --- |
| `agent_status` | 更新小宠物、状态面板、调用次数、token |
| `repo_parse_log` | append 到 `parseLog` |
| `repo_connected` | `parseState=done`，展示仓库完成提示，设置首个代码片段；不创建聊天消息 |
| `teaching_code` | 更新右侧代码框 |
| `answer_stream_start` | 创建 assistant 占位消息 |
| `answer_stream_delta` | 追加 delta 到占位消息 |
| `answer_stream_end` | 标记流式结束 |
| `message_completed` | 用最终消息替换占位消息 |
| `deep_research_progress` | append 研究进度日志，`agentState=researching` |
| `error` | 展示错误消息，保留用户输入 |

## 11. 后端实现边界

第一版必须实现：

- GitHub URL 解析和公开仓库接入。
- session 内存态。
- agent 状态钩子和 `agent_status` SSE。
- 仓库解析进度 SSE。
- 主聊天 `chat|deep` 两种模式。
- 术语解释副栏。
- 教学代码片段推送。
- 统一错误 envelope 和 terminal error event。

第一版不做：

- 多用户账号。
- 数据库持久化。
- 私有 GitHub OAuth。
- 浏览器端直连 LLM。
- 前端本地 mock 解析日志或 `window.claude.complete`。
