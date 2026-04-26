# 协议说明

本文只描述当前 live 运行时的通信协议：`backend/routes/` 与 `web_v3/js/services/api.js`
之间的 REST、Header、Envelope、SSE 和 sidecar 交互。

## 通用约定

### 基础地址

- 默认后端：`http://127.0.0.1:8000`
- `web_v3` 通过 `meta[name="rt-api-base"]` 覆盖 API base
- 如果没有显式 meta，前端默认拼接 `http://{hostname}:8000`

### 成功 / 失败 Envelope

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
  "session_id": "sess_123",
  "error": {
    "error_code": "invalid_request",
    "message": "message text",
    "retryable": true,
    "stage": "idle",
    "input_preserved": true
  }
}
```

### Header 与 Query 约定

- `X-Session-Id`
  - `GET /api/session`
  - `DELETE /api/session`
  - `POST /api/chat`
- `session_id` query
  - `GET /api/analysis/stream?session_id=...`
  - `GET /api/chat/stream?session_id=...`

## REST 端点

### `POST /api/repo/validate`

请求：

```json
{
  "input_value": "C:\\repo\\demo"
}
```

成功 `data`：

```json
{
  "input_kind": "local_path",
  "is_valid": true,
  "normalized_input": "C:\\repo\\demo",
  "message": null
}
```

### `POST /api/repo`

请求：

```json
{
  "input_value": "https://github.com/owner/repo",
  "analysis_mode": "quick_guide"
}
```

成功 `data`：

```json
{
  "accepted": true,
  "status": "accessing",
  "sub_status": null,
  "view": "analysis",
  "analysis_mode": "quick_guide",
  "repository": {
    "display_name": "owner/repo",
    "source_type": "github_url",
    "input_value": "https://github.com/owner/repo"
  },
  "analysis_stream_url": "/api/analysis/stream?session_id=sess_xxx"
}
```

语义：

- 这个请求只负责建会话和返回流地址
- 返回的 `view` 已经是后端 `ClientView.ANALYSIS`
- 真正的扫描与回答生成发生在后续 analysis SSE 连接里

### `GET /api/session`

Header：

```text
X-Session-Id: sess_xxx
```

语义：

- 如果当前没有 active session，返回 `status=idle` 的空快照
- 如果提供了 `X-Session-Id`，会校验它是否匹配当前 active session

### `DELETE /api/session`

Header：

```text
X-Session-Id: sess_xxx
```

成功 `data`：

```json
{
  "status": "idle",
  "sub_status": null,
  "view": "input",
  "cleanup_completed": true
}
```

### `POST /api/chat`

Header：

```text
X-Session-Id: sess_xxx
```

请求：

```json
{
  "message": "请带我看启动流程"
}
```

成功 `data`：

```json
{
  "accepted": true,
  "status": "chatting",
  "sub_status": "agent_thinking",
  "user_message_id": "msg_user_xxx",
  "chat_stream_url": "/api/chat/stream?session_id=sess_xxx"
}
```

### `POST /api/sidecar/explain`

请求：

```json
{
  "question": "什么是 SSE？"
}
```

成功 `data`：

```json
{
  "answer": "..."
}
```

## Session 生命周期

### 初始分析

1. `POST /api/repo`
2. 前端保存 `session_id`
3. 前端连接 `/api/analysis/stream`
4. 后端可能经历：
   - `accessing`
   - `analyzing`
   - `chatting / waiting_user`
5. 终止事件是 `message_completed` 或 `error`

### 后续聊天

1. `POST /api/chat`
2. 后端切到 `chatting / agent_thinking`
3. 前端连接 `/api/chat/stream`
4. 后端可能经历：
   - `agent_activity`
   - `answer_stream_start`
   - 多个 `answer_stream_delta`
   - `answer_stream_end`
   - `message_completed`
5. 终止事件仍是 `message_completed` 或 `error`

## SSE 编码

`backend/contracts/sse.py` 的输出格式是：

```text
event: answer_stream_delta
data: {"event_type":"answer_stream_delta", ...}

```

特点：

- `event:` 使用 `event_type`
- `data:` 是 `exclude_none=True` 后的 JSON
- 事件之间用空行分隔

## SSE 事件目录

### `status_changed`

字段：

- `status`
- `sub_status`
- `view`

用途：

- 通知前端切换主视图与整体会话状态

### `analysis_progress`

字段：

- `step_key`
- `step_state`
- `user_notice`
- `progress_steps`
- `deep_research_state`

用途：

- 推进左侧流程步骤
- deep research 模式下同步当前阶段与文件覆盖率

### `degradation_notice`

字段：

- `degradation`

用途：

- 告知大仓库、非 Python 仓库、超时等降级信息

### `agent_activity`

字段：

- `activity.phase`
- `activity.summary`
- `activity.tool_name`
- `activity.tool_arguments`
- `activity.round_index`
- `activity.elapsed_ms`

用途：

- 在前端展示“正在思考 / 正在跑工具 / 工具失败后降级继续”等细粒度活动

### `answer_stream_start`

字段：

- `message_id`
- `message_type`

用途：

- 为即将到来的 agent 消息创建占位消息

### `answer_stream_delta`

字段：

- `message_id`
- `delta_text`
- `structured_delta`

用途：

- 流式追加当前回答正文
- 当前 `web_v3` 只把 `delta_text` 追加到可见文本

### `answer_stream_end`

字段：

- `message_id`

用途：

- 标记增量阶段结束，最终正文以 `message_completed` 为准完成收口

### `message_completed`

字段：

- `message`
- `status`
- `sub_status`
- `view`

用途：

- 发送完整 `MessageDto`
- 让前端用最终消息覆盖占位内容并恢复输入状态

### `error`

字段：

- `error`
- `status`
- `sub_status`
- `view`

用途：

- 统一流式错误终点

## Analysis SSE 与 Chat SSE 的终止条件

### Analysis SSE

- `event_streams.iter_analysis_events()` 会先回放 reconnect 事件
- 如果会话仍处于 `accessing` 或 `analyzing`，则继续实际运行分析
- 一旦遇到 `message_completed` 或 `error`，当前连接结束

### Chat SSE

- `event_streams.iter_chat_events()` 会先回放 reconnect 事件
- 只有当状态是 `chatting` 且 `sub_status == agent_thinking` 时，才继续真正执行新一轮
  `ChatWorkflow`
- 一旦遇到 `message_completed` 或 `error`，当前连接结束

## web_v3 对协议的消费方式

### REST 客户端

`web_v3/js/services/api.js` 暴露：

- `submitRepo`
- `validateRepo`
- `getSession`
- `clearSession`
- `sendMessage`
- `explainSidecar`

### SSE 客户端

`openStream(kind, sessionId, onEvent, onClose)` 会监听 9 个事件名：

- `status_changed`
- `analysis_progress`
- `degradation_notice`
- `agent_activity`
- `answer_stream_start`
- `answer_stream_delta`
- `answer_stream_end`
- `message_completed`
- `error`

### 主可见文本规则

- `app.js` 在 `answer_stream_delta` 时把 `delta_text` 拼接到消息 `raw_text`
- `components.js` 的聊天主线程直接渲染 `msg.raw_text || msg.content || ""`
- 因此主正文来源是 `raw_text` / `delta_text`

### 结构化补充规则

- `structured_content`
- `initial_report_content`
- `suggestions`

这些字段不会在主线程里重新拼装成正文，但会被右侧面板或消息附属区域用于：

- 展示建议问题
- 提取 `evidence_refs`
- 辅助 sidecar / 结构化观察

## Sidecar 协议

- 右侧面板通过 `POST /api/sidecar/explain` 请求短解释
- 请求不依赖 `session_id`
- 返回只有一个核心字段：`answer`
- 失败时沿用统一错误 envelope 与前端报错逻辑

## 当前前端需要依赖的最小稳定字段

- Session：
  - `session_id`
  - `status`
  - `sub_status`
  - `view`
- Repository：
  - `display_name`
  - `input_value`
  - `primary_language`
  - `repo_size_level`
- Message：
  - `message_id`
  - `role`
  - `message_type`
  - `raw_text`
  - `suggestions`
  - `streaming_complete`
  - `structured_content`
  - `initial_report_content`
- SSE：
  - `event_type`
  - `delta_text`
  - `message`
  - `error`

## 维护建议

- 新增端点时，必须同步更新 `backend/routes/`、`backend/contracts/dto.py`、
  `web_v3/js/services/api.js` 和本文档。
- 新增 SSE 事件时，必须同步更新 `RuntimeEventType`、DTO、`event_mapper.py`、
  `api.js` 的订阅列表与 `app.js` 的事件分发。
- 如果前端改变可见正文来源，必须同时更新本文档中“主可见文本规则”一节。
