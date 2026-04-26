# new_kernel Agent Instructions

本文件约束 `new_kernel/` 内的后续实现、迁移和重构。这个目录是 Irene/Repo
Tutor 的新内核草案，目标是跑通一个可靠的仓库教学 turn，而不是建设通用
AgentOS。

## 最高优先级：Complete Decoupling

除前后端接口合同外，本目录的死要求是模块之间必须完全解耦。交互规范的权威文档是
`module_interaction_spec.md`；任何负责单个目录的 agent 在改动前必须先读它，并按其中的
依赖方向、状态所有权、事件链路和禁止事项检查自己的方案。

完全解耦在本目录中的含义：

- 跨模块只能通过公开 contract、facade、protocol、构造函数参数或明确 dataclass 交互。
- 不能读取或修改别的模块内部状态，不能横传未建模 dict，不能靠全局 singleton 或环境变量偷传依赖。
- 依赖方向必须单向；底层模块不能反向 import 上层模块，业务模块不能 import `api/`。
- 新增任何跨模块交互前，必须先更新 `module_interaction_spec.md`。
- 如果为了方便想直接跨层调用，先停下重画接口；临时直连视为实现错误。

## 最高优先级：Interface First

`interface` 是本目录最高文档要求。任何实现、重构、迁移都不能破坏前后端接口合同。

接口权威来源按以下顺序理解：

1. `web_v4_interface_protocol.md`：HTTP、SSE、状态流、前端可见行为的最高协议。
2. `contracts.py`：上述协议的 Pydantic 固化版本，所有公开 JSON 必须从这里的模型派生。
3. `module_interaction_spec.md`：模块之间的依赖方向、状态所有权和交互规范。
4. 本目录各模块文件的职责注释和已有实现。

如果修改公开接口，必须同步更新 `web_v4_interface_protocol.md` 和 `contracts.py`。不要只改路由、
只改前端字段，或在模块内部临时拼未建模的接口 dict。

## 迁移参考优先级

负责 `agents/`、`tools/`、`prompts/` 模块的 agent，开始改动前必须按这个顺序查资料：

1. `migration_plan.md`
2. `../DeepTutor/` 的真实源码
3. `../new_docs/new_kernel/` 内的侦察报告

其中 `migration_plan.md` 对第一版范围有最高约束力。DeepTutor 源码用于学习可迁移的 agent/tool/prompt
骨架，不用于照搬它的通用平台、RAG、web search、code execution、插件或多 provider 配置层。

推荐阅读点：

- `../DeepTutor/deeptutor/agents/base_agent.py`
- `../DeepTutor/deeptutor/agents/solve/tool_runtime.py`
- `../DeepTutor/deeptutor/core/tool_protocol.py`
- `../DeepTutor/deeptutor/agents/solve/memory/scratchpad.py`
- `../DeepTutor/deeptutor/agents/solve/agents/planner_agent.py`
- `../DeepTutor/deeptutor/agents/solve/agents/solver_agent.py`
- `../DeepTutor/deeptutor/agents/solve/agents/writer_agent.py`
- `../DeepTutor/deeptutor/agents/solve/main_solver.py`

## 第一版范围

第一版只服务仓库教学：

```text
用户问题
  -> orient / plan
  -> read-only repo tools
  -> scratchpad evidence
  -> TeacherAgent visible answer
  -> next teaching point
```

必须保留：

- 一个 session 同时只允许一个 active turn。
- 所有 REST 响应使用 `ApiEnvelope`。
- 所有 SSE 事件使用 `contracts.py` 中的 `SseEvent` 子类。
- 工具结果只进入 `Scratchpad.read_entries[].observation`，不能直接进入可见正文。
- 可见正文只来自 `TeacherAgent` 或深度研究最终 writer 阶段。
- 仓库工具只能读，不能写、执行、联网或安装依赖。

第一版不要引入：

- 数据库持久化、SQLite event store、账号系统。
- shell、code execution、filesystem write。
- web search、RAG、embedding、知识库。
- skill、MCP、插件 marketplace。
- 复杂 provider factory、`.env` 配置层、token tracker。
- DeepTutor 的通用 runtime/orchestrator 全套平台。

## 数据结构规范

### Public Contracts

`contracts.py` 是公开数据结构边界。

- 所有公开模型继承 `ContractModel`，保持 `extra="forbid"`。
- 新增 HTTP 响应字段时，先建 Pydantic 字段，再更新文档和路由。
- `ApiEnvelope` 必须保持三态互斥：成功有 `data` 无 `error`，失败有 `error` 无 `data`。
- 错误必须映射到 `ApiError(error_code, message, retryable, stage, input_preserved, internal_detail)`。
- 新 endpoint 必须登记到 `HTTP_ENDPOINTS`，并在 `api/routes/` 中落到对应文件。

### Session State

`session/` 持有单进程内存态。

`SessionState` 是一个 session 的唯一状态容器，应包含并只由运行时维护：

- `session_id`
- `repository`
- `agent_status`
- `parse_log`
- `messages`
- `scratchpad`
- `current_code`
- `mode`
- `active_turn_id`
- `event_bus`

`SessionStore` 只负责 `create_session / get / drop`。进程退出后状态消失，这是第一版明确约束。

### Turn State

`turn/` 管理一次用户消息的生命周期。

- `TurnRuntime.start_turn()` 必须检查 `SessionState.active_turn_id`。
- `mode=chat` 调 `TeachingLoop`，`mode=deep` 调 `DeepResearchLoop`。
- 终态必须清空 `active_turn_id`。
- 正常结束发 `MessageCompletedEvent`。
- 错误结束发 terminal `ErrorEvent`，再更新 `AgentStatus`。
- 取消通过 `CancellationToken` 协作完成，发 `RunCancelledEvent`。

### Events

`events/` 是 SSE 的唯一数据源。

- 内部模块不直接写 SSE 字符串，只发布 `contracts.py` 里的事件模型。
- `EventFactory` 负责填 `event_id / occurred_at / session_id`。
- `EventBus` 是 per-session fan-out 队列，`api/sse.py` 只负责转成 `text/event-stream`。
- 进入新阶段时，必须先广播 `agent_status`，再广播该阶段的业务事件。
- `answer_stream_delta` 只能承载最终可见回答 token，不承载工具日志或中间草稿。

### Scratchpad

`memory/Scratchpad` 是内部证据账本和上下文压缩器。

字段：

- `question`
- `reading_plan`
- `read_entries`
- `covered_points`
- `metadata` 如实现需要可加，但必须保持结构化

方法语义：

- `add_entry()` 只追加 read 阶段证据。
- `build_reading_context(max_tokens=4000)` 给 ReadingAgent。
- `build_teacher_context(max_tokens=8000)` 给 TeacherAgent。
- `covered_points` 用于跨轮记忆，不等于事实库；没有足够结构化结果时不要推进覆盖状态。

### Tool Protocol

`tools/tool_protocol.py` 是工具内部合同。

- `BaseTool.execute()` 必须使用显式 `ctx: ToolContext` 参数，不使用 `**kwargs` 注入运行时上下文。
- `ToolContext` 至少包含 `repo_root / max_lines / max_search_hits / language`。
- `ToolResult` 至少包含 `content / metadata / success / error_code`。
- 大输出必须截断，并在 `metadata` 中标记 `truncated=true` 和原始规模。
- 工具失败返回结构化失败结果或 observation 文本，不能让一次失败终止整个 turn。

## 模块交互规范

本节只保留总览。具体的依赖矩阵、状态 owner、允许 import、禁止链路和变更检查清单，
以 `module_interaction_spec.md` 为准。任何实现不得用本节的简写绕过该文档的更严格约束。

核心原则：

- `api/` 只做 HTTP/SSE 边界适配，不实现业务算法。
- `turn/` 只管理 turn 生命周期和 active turn 互斥，不实现 agent 推理细节。
- `agents/` 只做 LLM 推理和 teaching loop 编排，单个 agent 不直接碰 API/session/repo。
- `tools/` 只读仓库并返回 `ToolResult`，不写 scratchpad、不发事件、不生成可见正文。
- `events/` 只承载 `contracts.py` 中的事件模型，不知道 FastAPI、session 或 tools。
- `session/` 只持有单进程状态，不启动 repo parse、turn、LLM 或 tools。
- `repo/` 只做仓库接入流水线，不 import `session`，不写 scratchpad，不调用 teaching agent。
- `llm/` 和 `prompts/` 是薄依赖层，不能反向依赖业务模块。

### API Layer

`api/` 只做 HTTP/SSE 边界适配：

```text
FastAPI route
  -> request contract validation
  -> session / turn / repo service
  -> ApiEnvelope or SSE stream
```

路由职责：

- `routes/github.py`：只解析和验证 GitHub 输入，不创建 session。
- `routes/repositories.py`：创建 session，启动 repo parse pipeline，提供 repo SSE。
- `routes/chat.py`：提交主消息，创建 turn，提供 turn SSE。
- `routes/sidecar.py`：术语解释，不抢占主 agent，不写 scratchpad。
- `routes/agent.py`：返回当前 `AgentStatus`。
- `routes/session.py`：构造刷新恢复快照。
- `routes/control.py`：触发当前 active turn 的取消信号。

### Repo Parse Pipeline

`repo/` 的数据流固定为：

```text
GithubResolver
  -> GitCloner
  -> TreeScanner
  -> OverviewBuilder
  -> TeachingSlicePicker
  -> RepoConnectedEvent
```

每一步必须通过 `ParseLogLine` 向 `EventBus` 推进度。仓库接入完成后更新：

- `SessionState.repository`
- `SessionState.current_code`
- `AgentStatus`
- `repo_connected` SSE 事件

仓库扫描和片段选择不能读取敏感文件，不能进入 `.git`、`.env`、secret、依赖构建目录或大型二进制。

### Teaching Loop

`agents/teaching_loop.py` 是一次普通教学 turn 的编排器：

```text
OrientPlanner.process()
  -> for each step:
       ReadingAgent.process()
       ToolRuntime.execute()
       Scratchpad.add_entry()
  -> TeacherAgent.process(stream)
  -> scratchpad.covered_points update
```

约束：

- `OrientPlanner` 一次 LLM 调用输出 1-3 个 reading steps。
- 每个 step 内 `ReadingAgent` 最多 3 轮 ReAct。
- 每轮最多一个工具调用。
- `ReadingAgent.action` 必须在 `ToolRuntime.valid_actions` 内，否则降级为 `done`。
- `TeacherAgent` 一次只讲一个核心点，最多 3 个 source anchors，结尾恰好一个 next teaching point。
- 证据不足时缩小说法，不要编造，也不要把工具错误展示成教学正文。

### Tool Runtime

`tools/tool_runtime.py` 包装只读仓库工具：

```text
ToolRuntime(enabled_tools)
  -> valid_actions = tool names + aliases + done
  -> execute(action, action_input, ctx)
  -> ToolResult
```

第一版工具只包括：

- `read_file_range(path, start_line, end_line)`
- `search_repo(pattern, glob=None)`
- `list_dir(path, recursive=False)`
- `summarize_file(path)`
- `find_references(symbol)`

所有工具执行前必须经过 `safe_paths.resolve_under_root()` 和 `is_sensitive_file()`。不要新增 shell、
write、network、browser、package manager 或 code execution 工具。

### Prompts

`prompts/` 使用本地 YAML，运行时由 `PromptManager` 三段查找：

```text
get(agent_name, section, field=None, fallback="")
```

布局：

```text
prompts/zh/orient.yaml
prompts/zh/read.yaml
prompts/zh/teach.yaml
prompts/zh/sidecar.yaml
```

每个 agent 自己拼：

- `_build_system_prompt()`
- `_build_user_prompt(**ctx)`

`OrientPlanner` 和 `ReadingAgent` 输出严格 JSON。`TeacherAgent` 不输出 JSON，只输出自然语言正文。

### LLM Layer

`llm/` 是薄客户端层。

- 构造时显式传入 api key / model id / client。
- 不读 `.env`。
- 不做 provider factory。
- 不做 token tracker。
- `BaseAgent` 只封装 `call_llm / stream_llm / get_prompt / process`。

### Deep Research

`deep_research/` 可以复用教学 loop 的只读工具和 writer 约束，但允许更多 step 和进度事件。

- `mode=deep` 仍走 `POST /api/v4/chat/messages`。
- 过程中可发 `DeepResearchProgressEvent`。
- 最终可见正文仍必须由 writer/teacher 阶段收敛。
- 不因此引入 web search、RAG 或外部研究工具。

### Sidecar Explainer

`SidecarExplainer` 是副栏能力：

- 单次 LLM 调用。
- 返回 2-3 句中文解释。
- 可读取当前 repo/file 上下文。
- 不修改 `messages`、`scratchpad`、`active_turn_id`。
- 不阻塞主 session，不抢占主 agent 状态。

## 实现质量门槛

改动代码时优先保持小而明确：

- 新公开字段要有 contract、文档、路由使用点。
- 新内部字段要有明确 owner，不要把任意 dict 在模块间横传。
- 工具输出、trace、parse log、visible answer 必须分层，不要混用。
- 异步流程要检查取消点：orient 前、每个 read step 前、teach 前。
- 任何路径输入都按 repo root 解析并做越界检查。
- 用户可见错误使用中文 `message`，内部细节只放 `internal_detail`。

建议验证：

```text
python -m compileall new_kernel
python -m pytest -q -p no:cacheprovider
```

如果只改 `new_kernel/` 且仓库当前没有对应测试，至少运行 compileall 或说明未运行的原因。
