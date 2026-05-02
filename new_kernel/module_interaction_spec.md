# new_kernel 模块交互与解耦规范

本文档约束 `new_kernel/` 内所有模块之间如何交互。目标不是让模块彼此不知道对方存在，
而是做到完全解耦：模块只能通过明确、稳定、可替换的公开接口协作，不能读取、修改或依赖
其他模块的内部实现。

本规范用于防止负责不同目录的 agent 跑飞。任何新增功能、迁移或重构，如果需要跨模块交互，
必须先满足本文的依赖方向和接口所有权要求。

## 1. 解耦定义

`new_kernel` 中的“完全解耦”必须同时满足以下条件：

1. 只依赖公开接口：跨模块调用只能使用本文列出的 facade、protocol、contract 或构造函数参数。
2. 不跨模块改状态：一个模块不能直接修改另一个模块拥有的内部状态。
3. 不跨层读取内部结构：不能为了方便读取别的模块对象的私有字段、缓存、队列或临时 dict。
4. 不反向导入：底层模块不能 import 上层模块，业务模块不能 import API 层。
5. 不隐式共享：不能通过全局变量、模块级 singleton、service locator 或环境变量在模块间传递依赖。
6. 可替换测试：任一模块应能用 fake/stub 替换它依赖的外部接口后单独测试。

如果某个交互不满足这些条件，不能实现为“临时直连”；必须先抽出明确接口，再接入。

## 2. 权威边界

公开接口权威顺序：

1. `web_v4_interface_protocol.md`：前端可见协议的最高来源。
2. `contracts.py`：所有公开 HTTP JSON 和 SSE JSON 的 Pydantic 固化版本。
3. `module_interaction_spec.md`：模块之间的依赖方向、调用方式和状态所有权。
4. 各模块文件顶部职责注释与后续实现。

如果公开 HTTP/SSE 字段变化，必须同步更新 `web_v4_interface_protocol.md` 和 `contracts.py`。
如果模块之间新增交互，必须同步更新本文档。

## 3. 依赖方向总图

箭头表示“左侧模块允许导入或依赖右侧模块”。没有出现在图里的反向依赖都禁止。

```text
api
  -> contracts
  -> session
  -> turn
  -> repo
  -> events
  -> agents.sidecar_explainer

turn
  -> contracts
  -> session
  -> events
  -> agents.teaching_loop
  -> deep_research
  -> turn.cancellation

agents
  -> contracts
  -> llm
  -> prompts
  -> memory
  -> tools.tool_protocol
  -> tools.tool_runtime
  -> events protocol/facade only

deep_research
  -> contracts
  -> agents
  -> memory
  -> tools.tool_protocol
  -> tools.tool_runtime
  -> events protocol/facade only

repo
  -> contracts
  -> events protocol/facade only
  -> tools.safe_paths where path safety is shared

session
  -> contracts
  -> events
  -> memory

events
  -> contracts

tools
  -> tools.tool_protocol
  -> tools.safe_paths

memory
  -> no runtime module dependency, except optional contracts value types

prompts
  -> filesystem/yaml only

llm
  -> SDK/client library only

contracts
  -> stdlib + pydantic only
```

禁止依赖示例：

- `tools -> agents` 禁止。
- `tools -> events` 禁止。
- `agents -> api` 禁止。
- `agents -> session` 禁止。
- `repo -> session` 禁止。
- `repo -> api` 禁止。
- `events -> session` 禁止。
- `llm -> prompts/agents/tools` 禁止。
- `contracts -> new_kernel.*` 禁止。

## 4. 组合根

依赖只能在组合根装配，不能在业务模块里临时创建跨模块实例。

允许的组合根：

- `api/app.py`：装配 FastAPI、routes、`SessionStore`、`PromptManager`、LLM client、`ToolRuntime`。
- `api/routes/*.py`：只做 HTTP 适配和调用已经装配好的 service/facade。
- `turn/turn_runtime.py`：为一个 turn 装配 `TeachingLoop` 或 `DeepResearchLoop` 的运行参数。

组合根规则：

- 依赖通过构造函数或显式参数传入。
- 禁止业务模块自己 new `SessionStore`、`EventBus`、LLM client 或 `ToolRuntime`。
- 禁止模块级全局 mutable 单例。
- 可以有纯常量，例如 `contracts.HTTP_ENDPOINTS`、枚举、默认限额。

## 5. 模块所有权

### `contracts.py`

所有权：

- 公开 HTTP request/response 数据。
- 公开 SSE event 数据。
- 公开枚举、错误码和 endpoint registry。

允许被所有模块导入。禁止导入任何 `new_kernel` 内部模块。

新增公开字段流程：

1. 先加 Pydantic contract。
2. 更新 `web_v4_interface_protocol.md`。
3. 更新对应 route/event factory。
4. 更新本文档中受影响的模块交互。

### `events/`

所有权：

- `EventBus` 的 per-session fan-out。
- `EventFactory` 填充 `event_id / occurred_at / session_id`。
- `AgentStatusTracker` 维护并广播当前 `AgentStatus`。

解耦要求：

- `events` 不知道 FastAPI、SSE 字符串、session store、agent、repo 或 tools。
- 内部模块发布的是 `contracts.SseEvent` 子类，不发布 JSON 字符串。
- `api/sse.py` 是唯一把事件转成 `text/event-stream` 的地方。
- 业务模块如果需要发事件，接收一个 `EventSink` protocol 参数（仅含 `emit(event: SseEvent)` 一个方法），不直接寻找全局 bus。
- `EventFactory`、`AgentStatusTracker`、`EventBus` 是 events 内部实现：业务模块只见 `EventSink` 和 `AgentStatusTracker`（后者作为高层 helper），不直接持有 `EventBus` 或 `EventFactory`。

### `session/`

所有权：

- `SessionState` 是一个 session 的唯一内存状态容器。
- `SessionStore` 只负责 `create_session / get / drop`。
- `snapshot.py` 只负责把 state 组装成 `SessionSnapshotData`。

解耦要求：

- `session` 不启动 repo parse、不启动 turn、不调用 LLM、不调用 tools。
- `SessionState` 可被上层运行时更新，但 `SessionStore` 不包含业务流程。
- 除 `TurnRuntime` 和 repo session 创建流程外，其他模块不能直接写 `active_turn_id`。
- `messages`、`scratchpad`、`current_code` 的写入必须发生在明确的流程阶段，不能由 API route 随手改。

### `api/`

所有权：

- HTTP request validation。
- `ApiEnvelope` 成功/失败包装。
- SSE 连接适配。
- 把请求转发给 session、repo、turn、sidecar 的 facade。

解耦要求：

- API 层不实现业务算法。
- API 层不直接读仓库文件、不执行工具、不拼 prompt、不调用普通 teaching agent。
- API 层不直接构造 SSE JSON 字符串。
- route 只能返回 `ApiEnvelope` 或 SSE stream。
- route 不能跳过 `TurnRuntime` 直接调用 `TeachingLoop`。

### `repo/`

所有权：

- GitHub 输入解析。
- clone 接入。
- 文件树扫描。
- repo overview 构建。
- 首个教学片段选择。

解耦要求：

- `repo` 不 import `session`，不持有 `SessionStore`。
- parse pipeline 返回结构化结果，或通过传入的 state updater/event sink 写结果；不能自己查找 session。
- `repo` 不调用 LLM、不调用 teaching agents、不写 scratchpad。
- `repo` 只能发布 repo parse 相关事件：`repo_parse_log`、`repo_connected`、必要的 `agent_status`。
- `repo` 和 `tools` 共享路径安全规则时，只能依赖 `tools.safe_paths` 的纯函数，不依赖 `ToolRuntime`。

### `turn/`

所有权：

- 一个用户消息的生命周期。
- 单 session 单 active turn 互斥。
- cancel token 创建与清理。
- turn 终态事件：completed、cancelled、error。

解耦要求：

- 只有 `TurnRuntime.start_turn()` 能进入主聊天或 deep research 流程。
- `TurnRuntime` 可以调用 `TeachingLoop` / `DeepResearchLoop`，但不实现 orient/read/teach 细节。
- `TurnRuntime` 清理 `active_turn_id` 是终态 finally 逻辑，不能交给 agent。
- 错误映射为 `ApiError` 后再发布 `ErrorEvent`。
- cancel 通过 `CancellationToken` 协作完成，不能强杀任务。

### `agents/`

所有权：

- `BaseAgent` 的 LLM 调用薄封装。
- `OrientPlanner` 生成 reading plan。
- `ReadingAgent` 生成一次 ReAct 决策。
- `TeacherAgent` 生成唯一可见教学正文。
- `SidecarExplainer` 生成术语解释。
- `TeachingLoop` 编排 orient/read/teach。

解耦要求：

- 单个 agent 子类不 import API、session、repo、events bus。
- `OrientPlanner` 和 `ReadingAgent` 只输出结构化决策，不执行工具。
- `ReadingAgent` 不直接调用 `ToolRuntime.execute()`；执行由 `TeachingLoop` 完成。
- `TeacherAgent` 只消费 scratchpad teacher context，不读取工具或仓库文件。
- 可见正文只来自 `TeacherAgent` 或 deep research 最终 writer/teacher 阶段。
- `TeachingLoop` 可以接收 event sink 来发状态和 stream 事件，但不得知道 SSE 协议细节。
- `SidecarExplainer` 是独立能力，不写 `messages`、`scratchpad`、`active_turn_id`。

### `tools/`

所有权：

- 只读仓库工具协议。
- 工具注册、action 路由和执行。
- 路径越界与敏感文件拦截。

解耦要求：

- tools 不 import API、session、events、agents、repo parse pipeline。
- 工具不能写文件、不能执行代码、不能联网、不能安装依赖。
- 工具不能发布事件，不能写 scratchpad，不能生成可见回答。
- 工具失败返回 `ToolResult(success=false, error_code=...)`，不让单次失败终止 turn。
- `summarize_file` 如果需要 LLM，必须通过构造参数注入 `summarizer: Callable[[str], Awaitable[str]]`；
  禁止把 callable 放进 `ToolContext`（`ToolContext` 是不可变值对象，注入 callable 会破坏可序列化与可缓存性），
  禁止 import `llm.client` 或 `BaseAgent`。注入由组合根 (`api/app.py`) 完成。

### `memory/`

所有权：

- `Scratchpad` 内部证据账本。
- reading context 和 teacher context 压缩。
- `covered_points` 的跨轮内存。

解耦要求：

- `memory` 不调用 LLM、不调用 tools、不发布 events。
- `Scratchpad.add_entry()` 只追加 read 阶段 observation。
- `Scratchpad` 不知道 SSE、API、SessionStore。
- `covered_points` 由 teaching/writer 终态更新，不能被 ReadingAgent 直接推进。

### `prompts/`

所有权：

- 本地 YAML prompt 加载。
- `PromptManager.get(agent_name, section, field=None, fallback="")` 三段查找。

解耦要求：

- prompts 不 import agents。
- prompts 不调用 LLM。
- prompts 不接远程 prompt store、watcher、A/B、版本路由。
- prompt 缺失返回 fallback，不抛出跨模块异常。

### `llm/`

所有权：

- 构造薄 LLM client。
- 提供最小 call/stream 能力给 `BaseAgent`。

解耦要求：

- `llm` 不读 `.env`。
- `llm` 不做 provider factory。
- `llm` 不做 token tracker。
- `llm` 不 import prompt、agent、tool、session。
- API key、model id、client 必须由上层显式传入。

### `deep_research/`

所有权：

- `mode=deep` 的长流程。
- 更多 step 和进度事件。
- 最终 writer/teacher 收敛。

解耦要求：

- deep research 不接 web search、RAG、embedding 或外部知识库。
- deep research 复用只读工具协议，不新增写工具或执行工具。
- 进度通过 `DeepResearchProgressEvent`，最终可见正文仍走 writer/teacher。
- deep research 不直接操作 HTTP route 或 SSE 字符串。

## 6. 公开交互流程

### 仓库接入

```text
POST /api/v4/repositories
  -> api route validates CreateRepositorySessionRequest
  -> SessionStore.create_session()
  -> route/composition root starts repo.parse_pipeline with:
       session_id
       explicit repo input (input_value / branch / mode)
       status_sink:    Callable[[AgentStatus],     MaybeAwaitable[None]]
       log_sink:       Callable[[ParseLogLine],    MaybeAwaitable[None]]
       connected_sink: Callable[[RepoConnectedData], MaybeAwaitable[None]]
  -> 三个 sink 各自把对象交给上层 orchestrator；上层负责
        (a) 写入 SessionState 对应字段
        (b) 通过 EventFactory + EventSink 广播为对应 SseEvent 子类
  -> repo pipeline returns RepoParseResult
  -> owner updates SessionState.repository / current_code / parse_log / agent_status
  -> api/sse.py streams events to frontend
```

禁止：

- `repo.parse_pipeline` 自己从 `SessionStore` 查 session。
- `repo.parse_pipeline` 自己 import `events` 模块或自己构造 SseEvent；事件构造由 sink 的上层 orchestrator 完成。
- `api` 自己扫描文件树。
- `events` 根据 event 反向修改 session。

### 普通教学 turn

```text
POST /api/v4/chat/messages
  -> api route validates SendTeachingMessageRequest
  -> TurnRuntime.start_turn(session, request)
  -> TurnRuntime checks and sets active_turn_id
  -> TurnRuntime appends user ChatMessage
  -> TeachingLoop.run(...)
       -> OrientPlanner.process()
       -> for each step:
            ReadingAgent.process()
            ToolRuntime.execute()
            Scratchpad.add_entry()
       -> TeacherAgent.process(stream)
       -> Scratchpad.covered_points update
  -> TurnRuntime emits MessageCompletedEvent
  -> TurnRuntime clears active_turn_id
```

禁止：

- API route 直接调用 `OrientPlanner`、`ReadingAgent` 或 `TeacherAgent`。
- `ReadingAgent` 直接执行工具。
- 工具结果直接进入 `answer_stream_delta`。
- `TeacherAgent` 读取 repo 文件或执行工具。

### 深度研究 turn

```text
POST /api/v4/chat/messages(mode=deep)
  -> TurnRuntime.start_turn()
  -> DeepResearchLoop.run(...)
  -> DeepResearchProgressEvent for progress
  -> final writer/teacher visible answer
  -> MessageCompletedEvent
  -> active_turn_id cleared
```

禁止：

- 新增 web search / RAG / embedding。
- 绕开 `TurnRuntime` 开第二条 active turn。

### 术语解释 sidecar

```text
POST /api/v4/sidecar/explain
  -> api route validates SidecarExplainRequest
  -> reads optional session snapshot fields only
  -> SidecarExplainer.process()
  -> SidecarExplainData
```

禁止：

- 写 `messages`。
- 写 `scratchpad`。
- 写 `active_turn_id`。
- 改 `AgentStatus`。
- 启动 repo parse 或 teaching turn。

### 取消

```text
POST /api/v4/control/cancel
  -> api route finds active CancellationToken through TurnRuntime-owned registry
  -> token.cancel(reason)
  -> TeachingLoop/DeepResearchLoop observes token at checkpoint
  -> TurnRuntime emits RunCancelledEvent
  -> TurnRuntime clears active_turn_id
  -> route returns CancelRunData
```

禁止：

- route 直接清空 task 不发 terminal event。
- agent 自己决定修改 `active_turn_id`。

## 7. 数据传递规则

跨模块数据只能有四类：

1. Public contract：`contracts.py` 中的 request/response/event/status/message 模型。
2. Internal protocol：`ToolContext`、`ToolResult`、`ToolDefinition`、未来明确命名的 protocol/dataclass。
3. Explicit dependency：构造函数或函数参数传入的 LLM client、PromptManager、ToolRuntime、event sink。
4. Immutable primitive：字符串、数字、枚举、路径等只读值。

禁止：

- 在模块间传未建模的任意 dict。
- 传整个 `SessionStore` 给 agent/tool/repo。
- 传 `EventBus` 给工具。
- 让工具返回前端 event。
- 让 prompt YAML 持有运行时对象名。

## 8. 状态写入规则

| 状态 | 唯一 owner | 允许写入者 |
| --- | --- | --- |
| `SessionStore.sessions` | `session` | `SessionStore` |
| `SessionState.repository` | `session` state | repo 接入流程的上层 orchestrator |
| `SessionState.agent_status` | `events.AgentStatusTracker`/turn/repo orchestrator | 状态 tracker 或明确状态 writer |
| `SessionState.parse_log` | repo 接入流程 | repo orchestrator |
| `SessionState.messages` | turn runtime | `TurnRuntime` |
| `SessionState.scratchpad` | teaching/deep loop | `TeachingLoop` / `DeepResearchLoop` |
| `SessionState.current_code` | repo/teaching focus owner | repo orchestrator / TeachingLoop |
| `SessionState.mode` | session creation / turn request | route via validated request |
| `SessionState.active_turn_id` | turn runtime | `TurnRuntime` only |
| `EventBus` queues | events | `EventBus.publish/subscribe` only |

任何新状态必须先写明 owner，再实现。

## 9. 事件规则

- 所有 SSE 事件必须是 `contracts.SseEvent` 子类。
- `EventFactory` 是填 `event_id / occurred_at / session_id` 的唯一位置。
- 进入新阶段时，先广播 `agent_status`，再广播该阶段业务事件。
- `answer_stream_delta` 只能承载最终可见回答 token。
- 工具日志、ReAct thought、中间草稿、trace 不允许进入 `answer_stream_delta`。
- run 失败时，必须有 terminal `ErrorEvent`。
- run 取消时，必须有 `RunCancelledEvent`。

## 10. 工具调用规则

唯一合法链路：

```text
ReadingAgent.process()
  -> returns {action, action_input}
TeachingLoop
  -> validates action in ToolRuntime.valid_actions
  -> ToolRuntime.execute(action, action_input, ctx)
  -> ToolResult
TeachingLoop
  -> Scratchpad.add_entry(... observation=ToolResult.content ...)
TeacherAgent
  -> consumes Scratchpad.build_teacher_context()
```

禁止链路：

```text
ReadingAgent -> read_file_range
TeacherAgent -> ToolRuntime.execute
ToolRuntime -> Scratchpad.add_entry
Tool -> EventBus.publish
Tool -> ChatMessage
Tool -> ApiEnvelope
```

## 11. Prompt 与 LLM 规则

- prompt 由 agent 自己组装，不由 API 或 route 组装。
- `PromptManager` 只返回模板字符串，不知道运行时上下文。
- `BaseAgent` 只封装 `call_llm / stream_llm / get_prompt / process`。
- `OrientPlanner` 和 `ReadingAgent` 输出严格 JSON。
- `TeacherAgent` 输出自然语言正文，不输出 JSON。
- LLM client 必须显式注入，禁止隐藏读取 `.env`。

## 12. 变更检查清单

任何负责单个目录的 agent，在改代码前必须回答：

1. 我负责的模块 owner 是什么？
2. 我要导入的模块是否在依赖方向总图中允许？
3. 我是否在读取或修改别的模块内部状态？
4. 我是否传递了未建模 dict？
5. 我是否绕过了 `contracts.py`、`ToolResult`、`Scratchpad` 或 `EventFactory`？
6. 我是否让工具日志或中间推理进入可见正文？
7. 我是否新增了全局 singleton、环境变量读取或隐式依赖？
8. 新交互是否已经写进本文档？

任一答案不满足，先停下改设计。

## 13. 允许的跨模块 import 清单

这是最小清单。实现时如需增加，必须同步更新本文档。

| 发起模块 | 允许导入 |
| --- | --- |
| `api/*` | `contracts`, `api.envelope`, `api.errors`, `api.sse`, `session.*`, `turn.turn_runtime`, `repo.github_resolver`, `repo.parse_pipeline`, `agents.sidecar_explainer`, `events.*` |
| `turn/*` | `contracts`, `session.session_state`, `events.*`, `agents.teaching_loop`, `deep_research.deep_research_loop`, `turn.cancellation` |
| `agents/*` | `contracts`, `llm.client`, `prompts.prompt_manager`, `memory.scratchpad`, `tools.tool_protocol`, `tools.tool_runtime` |
| `deep_research/*` | `contracts`, `agents.teacher`, `agents.reading_agent`, `memory.scratchpad`, `tools.tool_protocol`, `tools.tool_runtime` |
| `repo/*` | `contracts`, `tools.safe_paths`（事件通过传入的 sink callable 发，不直接 import `events`） |
| `session/*` | `contracts`, `events.event_bus`, `memory.scratchpad` |
| `events/*` | `contracts` |
| `tools/*` | `tools.tool_protocol`, `tools.safe_paths`, stdlib file/search helpers |
| `memory/*` | stdlib, optional `contracts` value models only |
| `prompts/*` | stdlib, yaml parser |
| `llm/*` | stdlib, selected SDK |

## 14. 解耦验收

实现或重构完成后，至少检查：

```text
python -m compileall new_kernel
```

推荐补充静态检查：

```text
rg -n "from .*api|import .*api" agents tools repo session events memory llm prompts
rg -n "from .*session|import .*session" agents tools repo events memory llm prompts
rg -n "from .*agents|import .*agents" tools repo events session memory llm prompts
rg -n "from .*events|import .*events" tools llm prompts memory
```

这些命令出现命中不一定全部错误，但必须逐条按本文档解释。无法解释的就是耦合泄漏。
