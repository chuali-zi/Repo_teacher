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
  "client_message_id": "client_msg_001"
}
```

`mode=chat`：短教学回答，目标是解释一个当前点。  
`mode=deep`：深度研究报告，目标是完整结构分析，允许更长时间和更多阶段事件。

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
| `repo_connected` | `parseState=done`，写入仓库完成消息，设置首个代码片段 |
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
