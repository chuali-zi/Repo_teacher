# DeepTutor core stream 事件协议侦察报告

> 侦察对象：`DeepTutor/deeptutor/core/stream.py`、`stream_bus.py` 及其在 runtime、capability、WebSocket、前端中的真实使用。
> 目标：把 DeepTutor 内部 stream 协议拆清楚，并沉淀为 `new_kernel` 可复用的事件内核设计。

## 1. 总结

DeepTutor 的 core stream 不是简单的“LLM token 流”。它是一个单 turn 内部事件协议，用同一套 `StreamEvent` 承载：

- 阶段生命周期：`stage_start` / `stage_end`
- 模型思考、观察、最终回答：`thinking` / `observation` / `content`
- 工具轨迹：`tool_call` / `tool_result`
- 进度、来源、结构化结果、错误、会话、终止：`progress` / `sources` / `result` / `error` / `session` / `done`

核心闭环是：

```text
Capability / Agent / Tool callback
  -> StreamBus helper
  -> StreamEvent
  -> ChatOrchestrator yield
  -> TurnRuntimeManager 补齐 session_id/turn_id/seq
  -> SQLite turn_events + workspace events.jsonl + live WebSocket subscriber
  -> Web 前端按 type + metadata 渲染正文、trace、状态和恢复点
```

最关键的判断：

1. `StreamEventType` 是跨能力的语义层，不绑定 chat、solve、research 等具体业务。
2. `StreamBus` 是单 turn fan-out，不负责持久化、不分配 seq、不知道 WebSocket。
3. `TurnRuntimeManager` 才是事件落库和补流中心。
4. 前端不是按事件类型“一刀切显示”。正文只拼接符合条件的 `content`，trace 面板依赖 `metadata.call_id / call_kind / trace_role / trace_kind / call_state`。
5. `metadata` 虽然是自由 dict，但实际上已经承担了半结构化 trace 协议职责。

## 2. 数据结构

`deeptutor/core/stream.py` 定义了统一事件：

| 字段 | 语义 | 生成位置 |
|---|---|---|
| `type` | `StreamEventType` 枚举值 | producer 必填 |
| `source` | 事件来源，如 `chat`、`deep_solve`、`deep_research`、`turn_runtime` | producer 填 |
| `stage` | 当前能力内部阶段，如 `thinking`、`acting`、`responding` | producer 填 |
| `content` | 人类可读文本；正文、思考片段、工具结果、进度文案都可能放这里 | producer 填 |
| `metadata` | 结构化补充信息；工具参数、trace id、状态、sources、错误状态等 | producer 填 |
| `session_id` | 会话 id | `TurnRuntimeManager._persist_and_publish()` 补齐 |
| `turn_id` | turn id | `TurnRuntimeManager._persist_and_publish()` 补齐 |
| `seq` | 单 turn 内递增序号 | `SQLiteSessionStore.append_turn_event()` 补齐 |
| `timestamp` | 创建时间戳 | `StreamEvent` 默认工厂生成 |

`to_dict()` 会把枚举转成字符串，输出给 SQLite、JSONL、WebSocket 和前端。

## 3. StreamBus 行为

`deeptutor/core/stream_bus.py` 的职责非常窄：

- `_history` 保存当前 bus 已发事件。
- `_subscribers` 保存多个 `asyncio.Queue`，实现 fan-out。
- `emit(event)`：如果 bus 未关闭，写入 history 并推给所有活跃订阅者。
- `subscribe()`：先 replay history，再等待 live queue；bus close 后退出。
- `close()`：标记关闭，并给所有订阅者投递 `None`。

重要边界：

- bus close 后再 emit 会被忽略。
- late subscriber 可以收到历史事件。
- bus 不生成 `done`。`done` 由 `ChatOrchestrator` 或 `TurnRuntimeManager` 的异常/取消路径生成。
- bus 不负责 seq。seq 必须在持久化时生成，避免多个 producer 或 replay 路径乱序。

## 4. 事件类型逐项分析

### 4.1 `session`

用途：声明当前 stream 绑定的 session/turn。

来源：

- `ChatOrchestrator.handle()` 在 capability 运行前 yield 一个 `SESSION`。
- `TurnRuntimeManager.start_turn()` 也会先持久化一个 `SESSION`，source 为 `turn_runtime`。
- `_run_turn()` 消费 orchestrator 事件时会跳过 orchestrator 的 `SESSION`，避免重复落库。

典型 metadata：

```json
{
  "session_id": "unified_xxx",
  "turn_id": "turn_xxx",
  "regenerate": true,
  "regenerated_from_message_id": 12,
  "superseded_turn_id": "turn_old"
}
```

前端行为：

- `UnifiedChatContext` 收到 `session` 后绑定草稿会话到服务端 session id。
- 这个事件是身份/路由事件，不进入 assistant trace。

### 4.2 `stage_start` / `stage_end`

用途：表达一个能力内部阶段的生命周期。

生成方式：

```python
async with stream.stage("thinking", source="chat", metadata=trace_meta):
    ...
```

事件特点：

- `stage_start` 和 `stage_end` 成对出现。
- `stage_end` 在 context manager 的 `finally` 中发出，所以正常异常退出都尽量收口。
- `content` 通常为空，核心信息在 `source`、`stage`、`metadata`。

真实阶段示例：

| source | stage |
|---|---|
| `chat` | `thinking`、`acting`、`observing`、`responding` |
| `deep_solve` | `planning`、`reasoning`、`writing` |
| `deep_research` | `rephrasing`、`decomposing`、`researching`、`reporting` |
| `math_animator` | `concept_analysis`、`concept_design`、`code_generation`、`code_retry`、`summary`、`render_output` |
| `visualize` | `analyzing`、`generating`、`reviewing` |

前端行为：

- `stage_start` 设置 `currentStage`。
- `stage_end` 清空 `currentStage`。
- trace 面板主要还是依赖 `metadata.call_id` 分组，而不是仅靠 stage 分组。

### 4.3 `thinking`

用途：承载不可直接拼入最终回答的模型思考、规划、草稿、内部输出。

典型来源：

- chat 的 `_stage_thinking()` 持续把 LLM chunk 发成 `thinking`。
- solve/research 的 trace callback 在 `llm_call state=streaming` 时把 chunk 发成 `thinking`。
- answer-now 合成过程也会把中间合成 trace 发成 `thinking` 或 `content`，取决于阶段和目标。

典型 metadata：

```json
{
  "call_id": "chat-thinking-...",
  "phase": "thinking",
  "label": "Reasoning",
  "call_kind": "llm_reasoning",
  "trace_role": "thought",
  "trace_group": "stage",
  "trace_kind": "llm_chunk"
}
```

前端行为：

- 不拼入主回答。
- 在 trace panel 中按 `call_id` 聚合，用 `trace_role=thought` 或 `call_kind=llm_reasoning` 显示为 Thought。

### 4.4 `observation`

用途：承载工具结果汇总后的观察、证据综合、阶段性判断。

典型来源：

- chat 的 `_stage_observing()` 把观察 LLM 的 chunk 发成 `observation`。
- solve 的 trace callback 收到 `llm_observation` 时转成 `observation`。
- NotebookAnalysisAgent 也会发 `OBSERVATION`。

典型 metadata：

```json
{
  "call_id": "chat-observing-...",
  "phase": "observing",
  "call_kind": "llm_observation",
  "trace_role": "observe",
  "trace_kind": "observation"
}
```

前端行为：

- 不拼入主回答。
- trace panel 中显示为 Observe。

### 4.5 `content`

用途：承载用户最终可见正文 token 或阶段产物 Markdown。

这是最容易误用的事件。DeepTutor 对 `content` 有两层语义：

1. 没有 `metadata.call_id` 的 `content`：默认可拼入 assistant 正文。
2. 有 `metadata.call_id` 的 `content`：只有 `metadata.call_kind == "llm_final_response"` 才拼入 assistant 正文。

后端规则在 `TurnRuntimeManager._should_capture_assistant_content()`：

```text
event.type != CONTENT -> 不收集
CONTENT 且没有 call_id -> 收集
CONTENT 且 call_kind == llm_final_response -> 收集
其他 CONTENT -> 不收集
```

前端规则在 `web/lib/stream.ts`，和后端保持一致。

这说明 `content` 不是“任何文本都可以发”。如果某个中间阶段也发 `content` 且没带 `call_id`，它会污染最终 assistant message。

推荐约束：

- 最终回答 token：`content + call_kind=llm_final_response`。
- 阶段预览且确实要进入聊天正文：可以无 `call_id`，但要确认它就是用户可见产物，例如 deep_research outline preview。
- 内部草稿：使用 `thinking` 或 `observation`，不要用裸 `content`。

### 4.6 `tool_call`

用途：声明工具调用即将发生，`content` 是工具名，`metadata.args` 是参数。

`StreamBus.tool_call()` 会把参数合并成：

```json
{
  "args": {"query": "..."},
  "call_id": "...",
  "trace_kind": "tool_call",
  "trace_role": "tool",
  "tool_name": "rag",
  "tool_call_id": "call_1",
  "tool_index": 0
}
```

真实来源：

- chat native tool loop：LLM function calling 计划出的工具。
- chat ReAct fallback：文本解析出的 action。
- solve/research capability：把内部 agent 的 `tool_call` trace callback 桥接成统一事件。

前端行为：

- trace panel 显示工具名和格式化参数。
- 不进入主回答。

### 4.7 `tool_result`

用途：声明工具调用结果，`content` 是工具输出文本，`metadata.tool` 是工具名。

`StreamBus.tool_result()` 合并：

```json
{
  "tool": "rag",
  "trace_kind": "tool_result",
  "trace_role": "tool",
  "sources": [...]
}
```

注意：

- `sources` 可能挂在 `tool_result.metadata.sources`，也可能由单独的 `sources` 事件发出。
- 工具失败有两种表达：有些路径发 `tool_result success=false`，有些路径发 `error`。

前端行为：

- trace panel 展示结果，可能内联 sources。
- 不进入主回答。

### 4.8 `progress`

用途：承载状态、进度、日志、调用状态变化。

这是最“多义”的事件。它既可能是给用户看的状态文案，也可能只是 trace 状态机的一部分。

典型 metadata 模式：

| 模式 | metadata |
|---|---|
| 进度数值 | `current`、`total` |
| LLM 调用状态 | `trace_kind=call_status`、`call_state=running/complete/error` |
| RAG 检索日志 | `trace_role=retrieve`、`trace_group=retrieve`、`trace_layer=raw/summary` |
| warning | `trace_kind=warning`、`reason=...` |
| research 卡片 | `research_stage_card=understand/decompose/evidence/result`、`research_status=...` |

前端行为：

- `call_status` 通常用于 trace 行的 pending/complete，不作为正文。
- 非 `call_status` 且有 content 的 progress 会显示在 trace body。
- research 面板会用 `research_stage_card` 把事件归到四张研究阶段卡。

推荐约束：

- `progress.content` 应该短，可直接展示。
- 机器状态放 metadata，不要把 JSON 塞进 content。
- 长日志用 `trace_layer=raw`，避免污染摘要 UI。

### 4.9 `sources`

用途：单独传递引用来源列表。

`StreamBus.sources()` 把来源放到 `metadata.sources`，`content` 通常为空。

chat 在最终 responding 后，如果工具 trace 收集到了 sources，会发：

```json
{
  "type": "sources",
  "source": "chat",
  "stage": "responding",
  "metadata": {
    "sources": [...]
  }
}
```

注意：

- DeepTutor 没有强制统一 source item schema。常见字段包括 `title`、`url`、`query`、`type`。
- trace panel 主要从 metadata 里读取 inline sources。

### 4.10 `result`

用途：结构化最终结果，不一定用于渲染主回答。

典型 payload：

| source | metadata 内容 |
|---|---|
| `chat` | `response`、`observation`、`tool_traces`、`metadata.cost_summary` |
| `deep_solve` | `response`、`output_dir`、`metadata` |
| `deep_research` | outline preview：`outline_preview`、`sub_topics`、`research_config`；最终：`response`、`metadata` |
| `math_animator` | 产物路径、代码、摘要、渲染信息 |
| `visualize` | 输出类型、代码/HTML/SVG、artifact 信息 |

后端行为：

- `result` 会进入 assistant message 的 `events`，但不会拼进 assistant `content`。
- 如果结果里有 `response`，通常此前已经通过 `content` 流出；`result.response` 更像结构化备份。

推荐约束：

- `result` 作为 machine-readable final envelope。
- 主聊天显示仍以 `content` 为准，避免 UI 从 result 里二次拼接造成重复。

### 4.11 `error`

用途：错误或警告。

两类错误必须区分：

1. 非终止错误/警告：例如 chat 最终回答为空时发 `error`，metadata 里 `turn_terminal=false`。
2. 终止错误：`TurnRuntimeManager` 捕获异常或取消时发 `error`，metadata 里 `turn_terminal=true`，并带 `status=failed/cancelled/rejected`。

典型 metadata：

```json
{
  "turn_terminal": true,
  "status": "failed",
  "reason": "regenerate_busy"
}
```

前端行为：

- 只要 `error.metadata.turn_terminal` 为真，前端会结束 streaming 并标记状态。
- 普通 `error` 进入 trace panel，不一定结束 turn。

推荐约束：

- 所有能结束 turn 的错误必须显式带 `turn_terminal=true` 和 `status`。
- 普通工具/模型警告应带 `turn_terminal=false` 或不带该字段。

### 4.12 `done`

用途：turn 流终止事件。

来源：

- `ChatOrchestrator` 在 capability run 的 finally 中 emit `DONE`。
- `TurnRuntimeManager` 在取消/异常路径手动补 `DONE`。
- `_persist_and_publish()` 如果 `done.metadata.status` 缺失，会补 `status=completed`。

前端行为：

- 收到 `done` 后 `STREAM_END`。
- 根据 `metadata.status` 标记 `completed`、`failed`、`cancelled` 等。
- 断开当前 WebSocket runner。

注意：

- `done` 是协议终止，不等于 assistant content 完整性。content 是否完整由前面的流和持久化决定。
- 对每个正常 turn 应该最终只有一个持久化 `done`。

## 5. metadata 实际已经是 trace 子协议

虽然 `metadata` 类型是 `dict[str, Any]`，但真实 UI 和 runtime 已经依赖这些键：

| key | 作用 |
|---|---|
| `call_id` | trace 聚合主键；同一次 LLM/tool/retrieve 调用的事件归为一组 |
| `phase` | 逻辑阶段，常与 `stage` 一致 |
| `label` | UI 展示名 |
| `call_kind` | 调用类型，如 `llm_reasoning`、`llm_observation`、`llm_final_response`、`rag_retrieval` |
| `trace_role` | UI 角色，如 `thought`、`observe`、`response`、`tool`、`retrieve` |
| `trace_group` | 聚合层级，如 `stage`、`react_round`、`retrieve` |
| `trace_kind` | 细粒度事件，如 `llm_chunk`、`llm_output`、`tool_call`、`tool_result`、`call_status`、`warning` |
| `call_state` | `running`、`complete`、`error` |
| `tool_name` / `tool_call_id` / `tool_index` | 工具调用标识 |
| `args` / `tool` | tool helper 固定写入 |
| `sources` | 引用来源 |
| `turn_terminal` / `status` / `reason` | 错误和终止状态 |
| `research_stage_card` / `research_status` | deep_research 前端分组 |

new_kernel 如果照搬 DeepTutor 的理念，不能只复制 `StreamEventType`；还需要把这组 trace metadata 升级为明确的内部合同。

## 6. 运行时持久化与补流

`TurnRuntimeManager.start_turn()`：

1. 创建/确保 session。
2. 创建 running turn。
3. 先持久化 `session` 事件。
4. 后台启动 `_run_turn()`。

`_run_turn()`：

1. 处理附件、历史、memory、skills、notebook context。
2. 组装 `UnifiedContext`。
3. 调 `ChatOrchestrator.handle(context)`。
4. 对每个非 orchestrator session 事件调用 `_persist_and_publish()`。
5. 收集 assistant content 和 assistant events。
6. 写 assistant message。
7. 更新 turn 状态。

`_persist_and_publish()`：

1. 补 `session_id`、`turn_id`。
2. 转 dict。
3. 写 SQLite `turn_events`。
4. mirror 到 `data/user/workspace/<capability>/<turn_id>/events.jsonl`。
5. 推给 live subscribers。

`SQLiteSessionStore.append_turn_event()`：

- 如果 event 自带正 seq，则使用它。
- 否则查当前 turn 最大 seq 后加一。
- `turn_events` 以 `(turn_id, seq)` 唯一。
- `get_turn_events(turn_id, after_seq)` 是 WebSocket resume 的基础。

补流协议：

```text
client 保存 activeTurnId + lastSeq
  -> WS reconnect
  -> send {type:"resume_from", turn_id, seq:lastSeq}
  -> runtime.subscribe_turn(turn_id, after_seq=lastSeq)
  -> 先 replay DB backlog，再接 live queue
```

## 7. 前端消费规则

`web/lib/unified-ws.ts` 镜像了 Python `StreamEventType`。

`UnifiedWSClient`：

- 自动重连。
- 保存 `activeTurnId` 和 `lastSeq`。
- 重连后发 `resume_from`。

`UnifiedChatContext`：

- `session`：绑定服务端 session。
- `done`：结束流，按 `metadata.status` 标记状态。
- `error + turn_terminal`：结束流并标记失败/取消/拒绝。
- 其他事件：追加到最后一条 assistant 的 `events`。
- `content` 是否拼正文交给 `shouldAppendEventContent()`。

`TracePanels`：

- 用 `metadata.call_id` 聚合事件。
- 用 `call_kind / trace_role / trace_group / trace_kind / call_state` 决定标题、图标、展开体、pending 状态和 raw logs。
- `llm_final_response` trace 不显示在 trace panel，因为它已经进主回答。

这意味着后端事件协议和 UI trace 渲染是紧耦合的：新增事件类型可以很少，但新增 metadata 语义必须同步前端。

## 8. 各能力的事件风格

### 8.1 chat

chat 是最完整的事件样板：

```text
stage_start thinking
  progress call_status=running
  thinking llm_chunk*
  progress call_status=complete
stage_end thinking

stage_start acting
  progress
  tool_call / tool_result / retrieve progress*
stage_end acting

stage_start observing
  progress call_status=running
  observation*
  progress call_status=complete
stage_end observing

stage_start responding
  progress call_status=running
  content llm_final_response*
  progress call_status=complete
stage_end responding

sources?
result
done
```

### 8.2 deep_solve

deep_solve 把 `MainSolver` 内部 callback 转成统一事件：

- `llm_call running` -> `progress call_status=running`
- `llm_call streaming` -> `thinking llm_chunk`
- `llm_call complete` -> `thinking llm_output` 或 `progress call_status=complete`
- `llm_observation` -> `observation`
- `tool_call` -> `tool_call`
- `tool_result` -> `tool_result`
- writer token -> `content stage=writing`
- final envelope -> `result`

特殊逻辑：

- 如果启用 rag 但没有 knowledge base，会发 warning `progress`，并从 enabled tools 移除 rag。
- answer-now 会跳过 planning/reasoning，直接在 writing 阶段合成回答。

### 8.3 deep_research

deep_research 有两种路径：

1. 未确认 outline：
   - 跑 planning/decompose。
   - 发 `content` 输出 outline Markdown。
   - 发 `result`，metadata 含 `outline_preview=true` 和 `sub_topics`。
2. 已确认 outline：
   - `stage researching` 包住 pipeline.run。
   - progress callback 映射 research 状态卡。
   - trace callback 映射 LLM/tool 轨迹。
   - `stage reporting` 发 final report `content`。
   - `result` 发结构化 response。

特殊 metadata：

- `research_stage_card` 控制前端四阶段卡片。
- `research_status` 保留 pipeline 原始状态。

### 8.4 math_animator / visualize

这两类更接近 artifact pipeline：

- 多阶段 `stage`。
- `progress` 用于渲染、检查、重试、产物路径状态。
- `thinking` 承载 LLM 生成/审查过程。
- `content` 承载摘要或可显示产物说明。
- `result` 承载 artifact 元数据。
- render/raw log 类事件一般通过 `trace_layer=raw` 区分。

## 9. 对 new_kernel 的落地建议

建议 new_kernel 把 stream 内核拆成三层，而不是让一个事件类承担所有隐式规则：

### 9.1 Event Envelope

保留 DeepTutor 的基本 envelope：

```python
class KernelEvent:
    type: EventType
    source: str
    stage: str
    content: str
    metadata: dict
    session_id: str
    turn_id: str
    seq: int
    timestamp: float
```

但把 `seq/session_id/turn_id` 明确规定为 runtime 写入字段，producer 不应该手动填。

### 9.2 Trace Metadata Contract

把下列字段定义成稳定 schema：

```python
class TraceMeta:
    call_id: str | None
    phase: str | None
    label: str | None
    call_kind: str | None
    trace_role: Literal["thought", "observe", "response", "tool", "retrieve", ...]
    trace_group: str | None
    trace_kind: str | None
    call_state: Literal["running", "complete", "error"] | None
```

避免未来 UI、runtime、agent 各自发明 key。

### 9.3 Visible Content Rule

把 `shouldAppendEventContent()` 作为协议文档的一部分：

```text
只有以下 content 进入 assistant 正文：
1. content 且无 call_id
2. content 且 call_kind == llm_final_response
```

同时规定：

- 中间 LLM chunk 必须用 `thinking` / `observation`。
- 最终回答必须带 `call_kind=llm_final_response`，除非是明确的非 trace 正文产物。

### 9.4 Terminal Rule

明确终止语义：

- 正常结束：`done(status=completed)`
- 取消：`error(turn_terminal=true,status=cancelled)` + `done(status=cancelled)`
- 失败：`error(turn_terminal=true,status=failed)` + `done(status=failed)`
- 输入拒绝：`error(turn_terminal=true,status=rejected, seq=0 或不落 turn)`，是否再发 done 要统一

### 9.5 Replay Rule

必须保留：

- `turn_events(turn_id, seq unique)`
- `subscribe_turn(after_seq)`
- replay backlog 后接 live queue
- client 保存 `turn_id + lastSeq`

这是 DeepTutor stream 设计最有迁移价值的部分。

## 10. new_kernel 最小事件表

如果 Irene/new_kernel 要实现一个精简版，建议先保留这些事件：

| 类型 | 必要性 | 用途 |
|---|---:|---|
| `session` | 必须 | 绑定 session/turn |
| `stage_start` / `stage_end` | 必须 | UI 状态和 pipeline 结构 |
| `progress` | 必须 | 状态、日志、调用状态 |
| `thinking` | 必须 | 中间推理/规划 |
| `observation` | 建议 | 工具后观察，利于教学 trace |
| `content` | 必须 | 最终可见回答 |
| `tool_call` / `tool_result` | 必须 | agent 工具轨迹 |
| `sources` | 建议 | RAG/Web 引用 |
| `result` | 必须 | 结构化最终产物 |
| `error` | 必须 | 非终止警告和终止错误 |
| `done` | 必须 | 流结束 |

可以暂缓 `SESSION` 之外更复杂的全局 EventBus，不影响 core stream 闭环。

## 11. 风险点

1. `metadata` 过自由，已经形成隐式协议。后续应收敛 schema。
2. `content` 双语义容易污染最终消息。必须强制 visible content rule。
3. `progress` 多义，UI 如果不看 `trace_kind` 会显示噪声。
4. `result.response` 和 `content` 存在重复信息，渲染时只能选一个权威来源。
5. `done` 和 terminal `error` 的组合需要严格约定，否则前端可能提前结束或重复结束。
6. `stage_start/stage_end` 是结构事件，不适合作为 trace 聚合唯一依据；真正聚合要靠 `call_id`。
7. `sources` schema 未统一，迁移时最好定义 `title/url/snippet/source_type/query` 等字段。

## 12. 关键源码索引

| 文件 | 作用 |
|---|---|
| `DeepTutor/deeptutor/core/stream.py` | `StreamEventType` 与 `StreamEvent` |
| `DeepTutor/deeptutor/core/stream_bus.py` | 单 turn async fan-out bus 与 producer helpers |
| `DeepTutor/deeptutor/runtime/orchestrator.py` | capability 调度、bus 生命周期、`session/done/error` 桥接 |
| `DeepTutor/deeptutor/services/session/turn_runtime.py` | turn 创建、事件持久化、补流、assistant content 收集 |
| `DeepTutor/deeptutor/services/session/sqlite_store.py` | `turn_events` schema、seq 分配、after_seq replay |
| `DeepTutor/deeptutor/api/routers/unified_ws.py` | `/api/v1/ws`、start/subscribe/resume/cancel/regenerate 协议 |
| `DeepTutor/deeptutor/agents/chat/agentic_pipeline.py` | 最完整的 chat 事件生产样板 |
| `DeepTutor/deeptutor/capabilities/deep_solve.py` | solver callback 到 StreamBus 的桥接 |
| `DeepTutor/deeptutor/capabilities/deep_research.py` | research progress/trace 到 StreamBus 的桥接 |
| `DeepTutor/web/lib/unified-ws.ts` | 前端事件类型镜像、重连和 resume |
| `DeepTutor/web/lib/stream.ts` | 前端 visible content rule |
| `DeepTutor/web/context/UnifiedChatContext.tsx` | session/done/error/stream event 消费逻辑 |
| `DeepTutor/web/components/chat/home/TracePanels.tsx` | trace metadata 的真实 UI 合同 |
| `DeepTutor/tests/core/test_stream_bus.py` | StreamBus 行为边界 |
| `DeepTutor/tests/runtime/test_orchestrator.py` | orchestrator 生命周期与错误行为 |
| `DeepTutor/tests/services/session/test_turn_runtime.py` | content 收集规则测试 |

## 13. 一句话内核图

```text
StreamEventType 是词表
StreamEvent 是 envelope
StreamBus 是单 turn 内存通道
ChatOrchestrator 是 capability 到事件流的适配器
TurnRuntimeManager 是 seq/持久化/replay/WebSocket 分发中心
Trace metadata 是 UI 真正依赖的半结构化子协议
```
