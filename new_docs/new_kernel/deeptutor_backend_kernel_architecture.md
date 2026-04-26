# DeepTutor 后端与内核架构侦察报告

> 侦察对象：`DeepTutor/` 独立项目目录。  
> 重点范围：后端 API、CLI/SDK 入口、统一 turn runtime、agent-native capability kernel、tool kernel、LLM/RAG/存储服务。  
> 代码基准：本地工作区 `C:\Users\chual\vibe\Irene\DeepTutor`。

## 1. 总览结论

DeepTutor 的后端不是一个单纯的 FastAPI CRUD 服务，而是一个“入口适配层 + 会话运行时 + agent-native 内核”的系统。

核心设计可以概括为：

```text
Web / CLI / Python SDK
    -> DeepTutorApp / WebSocket router / REST router
    -> TurnRuntimeManager
    -> UnifiedContext
    -> ChatOrchestrator
    -> CapabilityRegistry
    -> BaseCapability.run(...)
    -> StreamBus events
    -> SQLite turn_events + WebSocket subscriber
```

真正的“内核”在 `deeptutor/core/`、`deeptutor/runtime/`、`deeptutor/capabilities/`、`deeptutor/services/session/`、`deeptutor/services/llm/` 和 `deeptutor/tools/`。FastAPI 只是其中一个入口，CLI 和 SDK 走同一套 runtime。

最关键的架构判断：

1. `UnifiedContext` 是所有能力和工具共享的输入协议。
2. `StreamBus` 是所有能力向外输出进度、思考、工具调用、结果的统一事件通道。
3. `ChatOrchestrator` 是 capability 分发器，不直接做业务推理。
4. `CapabilityRegistry` 管多阶段能力，`ToolRegistry` 管 LLM 可调用工具。
5. `TurnRuntimeManager` 才是后端请求的真实执行中心：它负责 session、turn、附件、上下文压缩、memory、skills、notebook/history 引用、事件持久化和后台任务调度。
6. LLM 调用已抽象成 provider runtime，支持 OpenAI-compatible、Anthropic、Azure OpenAI、GitHub Copilot、OpenAI Codex 等后端。

## 2. 目录结构与职责

| 路径 | 职责 |
|---|---|
| `deeptutor/api/` | FastAPI 应用、REST routers、WebSocket routers、启动生命周期 |
| `deeptutor_cli/` | Typer CLI，调用同一套 `DeepTutorApp` facade |
| `deeptutor/app/facade.py` | Python/CLI 稳定应用门面，封装 runtime、session、notebook、capability contracts |
| `deeptutor/core/` | 内核协议：`UnifiedContext`、`StreamEvent`、`StreamBus`、`BaseCapability`、`BaseTool` |
| `deeptutor/runtime/` | 编排器、运行模式、capability/tool registry |
| `deeptutor/capabilities/` | 内置能力包装层：chat、deep_solve、deep_question、deep_research、math_animator、visualize |
| `deeptutor/agents/` | 各能力背后的具体 agent pipeline |
| `deeptutor/tools/` | 内置工具实现与工具包装 |
| `deeptutor/services/session/` | 统一 session/turn runtime、SQLite 持久化、上下文压缩 |
| `deeptutor/services/llm/` | LLM 配置、provider 抽象、factory、流式调用、多模态处理 |
| `deeptutor/services/rag/` | RAG 服务入口与 pipeline 工厂 |
| `deeptutor/services/storage/` | 附件等运行时存储 |
| `deeptutor/book/` | BookEngine，和 ChatOrchestrator 平行的另一个大引擎 |
| `deeptutor/tutorbot/` | 独立 TutorBot runtime、channel、agent loop、工具系统 |

## 3. 后端启动与 API 外壳

后端启动入口主要有两个：

1. `deeptutor/api/run_server.py`
   - 设置 Windows Proactor event loop，避免子进程 API 在 Windows 下不可用。
   - 切到项目根目录。
   - 读取 backend port。
   - 用 `uvicorn.run("deeptutor.api.main:app", ...)` 启动。

2. `deeptutor_cli/main.py`
   - `deeptutor serve` 也会启动 `deeptutor.api.main:app`。
   - CLI 默认先 `set_mode(RunMode.CLI)`，serve 时切到 `RunMode.SERVER`。

FastAPI 主应用在 `deeptutor/api/main.py`：

- startup 生命周期执行：
  - `validate_tool_consistency()`：检查 capability manifest 引用的 tools 是否都注册。
  - 初始化 LLM client。
  - 启动全局 `EventBus`。
  - 自动启动 TutorBots。
- shutdown 生命周期执行：
  - 停止 TutorBots。
  - 停止 EventBus。
- 挂载 `/api/outputs`，但通过 `SafeOutputStaticFiles` 和 `PathService.is_public_output_path()` 只暴露白名单产物。
- 注册大量 REST router。
- 注册统一 WebSocket：`/api/v1/ws`。

后端外壳的重点不是业务逻辑，而是把请求送入 session/turn runtime。

## 4. 统一 WebSocket 与 Turn Runtime

`deeptutor/api/routers/unified_ws.py` 提供 `/api/v1/ws`，支持这些消息：

| type | 作用 |
|---|---|
| `message` / `start_turn` | 启动一个新 turn |
| `subscribe_turn` | 订阅某个 turn 的事件，可用 `after_seq` 补流 |
| `subscribe_session` | 订阅 session 当前 active turn |
| `resume_from` | 断线后从指定 seq 恢复 |
| `unsubscribe` | 取消订阅 |
| `cancel_turn` | 取消运行中的 turn |
| `regenerate` | 重新运行上一条用户消息 |

WebSocket router 本身不执行 agent。它调用：

```text
get_turn_runtime_manager()
    -> TurnRuntimeManager.start_turn(...)
    -> subscribe_turn(...)
```

`TurnRuntimeManager` 在 `deeptutor/services/session/turn_runtime.py`，是后端最关键的调度类。

### 4.1 start_turn 做了什么

`start_turn(payload)` 的核心步骤：

1. 读取 capability，默认 `chat`。
2. 拆分 runtime-only config：
   - `_persist_user_message`
   - `_regenerate`
   - `_regenerated_from_message_id`
   - `_superseded_turn_id`
   - `followup_question_context`
   - `answer_now_context`
3. 用 `validate_capability_config()` 校验公开 config。
4. 确保 session 存在。
5. 保存 session preferences：
   - capability
   - tools
   - knowledge_bases
   - language
6. 创建 turn 记录。
7. 发布一个 session event。
8. 创建后台 task 执行 `_run_turn()`。

这说明一个用户请求在 DeepTutor 中不是直接同步返回，而是被建模为一个持久化 turn。

### 4.2 _run_turn 的执行管线

`_run_turn()` 是真正的数据装配中心：

1. 处理附件：
   - 先写入 `AttachmentStore`。
   - 然后用 `extract_documents_from_records()` 抽取 PDF/DOCX/XLSX/PPTX 等文档文本。
   - DB 中清理 base64，避免消息行膨胀。
2. 构建上下文：
   - `ContextBuilder.build()` 压缩历史并生成 bounded conversation history。
   - `memory_service.build_memory_context()` 读取轻量记忆。
   - `skill_service.auto_select()` 或按请求加载 skills。
   - notebook references 经过 `NotebookAnalysisAgent` 生成上下文。
   - history references 会读取其他 session 并分析/压缩。
   - question notebook references 渲染成 Question Bank context。
3. 拼装 `effective_user_message`：
   - `[Attached Documents]`
   - `[Notebook Context]`
   - `[History Context]`
   - `[Question Bank Context]`
   - `[User Question]`
4. 持久化用户消息。
5. 创建 `UnifiedContext`。
6. 调用 `ChatOrchestrator.handle(context)`。
7. 将 StreamEvent 序列化、持久化到 `turn_events`，同时推给 live subscribers。
8. 收集 assistant content 和 events，写入 messages 表。
9. 更新 turn 状态。
10. 非 regenerate 情况下刷新 memory。

这是 DeepTutor 后端最核心的运行闭环。

## 5. SQLite 持久化模型

`deeptutor/services/session/sqlite_store.py` 使用 SQLite 存储统一聊天状态，数据库位于 `PathService.get_chat_history_db()`，默认在 `data/user/chat_history.db`。

主要表：

| 表 | 作用 |
|---|---|
| `sessions` | 会话元信息、压缩摘要、preferences |
| `messages` | 用户/助手/系统消息、capability、events、attachments |
| `turns` | turn 状态：running/completed/cancelled/error |
| `turn_events` | 流式事件持久化，按 `turn_id + seq` 可恢复 |
| `notebook_entries` | Question Notebook 条目 |
| `notebook_categories` | Question Notebook 分类 |
| `notebook_entry_categories` | 条目分类关系 |

这个模型让 WebSocket 断线恢复可行：客户端只要保存 `turn_id` 和 `seq`，重新 `subscribe_turn` 即可补齐漏掉的事件。

## 6. 内核协议：Context、Event、Bus、Capability、Tool

### 6.1 UnifiedContext

`deeptutor/core/context.py` 定义 `UnifiedContext`。它是 capability 和 tool 的公共输入结构，包含：

- `session_id`
- `user_message`
- `conversation_history`
- `enabled_tools`
- `active_capability`
- `knowledge_bases`
- `attachments`
- `config_overrides`
- `language`
- `notebook_context`
- `history_context`
- `memory_context`
- `skills_context`
- `metadata`

设计含义：所有能力都不直接依赖 FastAPI payload，而依赖一个跨入口的统一上下文对象。

### 6.2 StreamEvent

`deeptutor/core/stream.py` 定义事件类型：

- `stage_start`
- `stage_end`
- `thinking`
- `observation`
- `content`
- `tool_call`
- `tool_result`
- `progress`
- `sources`
- `result`
- `error`
- `session`
- `done`

每个事件携带：

- source
- stage
- content
- metadata
- session_id
- turn_id
- seq
- timestamp

### 6.3 StreamBus

`deeptutor/core/stream_bus.py` 是单 turn 的 async fan-out bus：

- producer：capability 调 `stream.content()`、`stream.progress()`、`stream.tool_call()` 等。
- consumer：orchestrator / turn runtime / WebSocket subscriber 订阅事件。
- 内部保存 `_history`，新 subscriber 可以先收到已有事件。

这套协议把 CLI、WebSocket、SDK 的输出统一了。

### 6.4 BaseCapability

`deeptutor/core/capability_protocol.py` 定义：

- `CapabilityManifest`
  - name
  - description
  - stages
  - tools_used
  - cli_aliases
  - request_schema
  - config_defaults
- `BaseCapability.run(context, stream)`

多阶段 agent pipeline 都包装成 capability。

### 6.5 BaseTool

`deeptutor/core/tool_protocol.py` 定义：

- `ToolDefinition`
- `ToolParameter`
- `ToolPromptHints`
- `ToolResult`
- `BaseTool.get_definition()`
- `BaseTool.execute()`

工具通过 OpenAI function-calling schema 暴露给 LLM，也可以由 agent 代码直接调用。

## 7. Orchestrator 与 Registry

`deeptutor/runtime/orchestrator.py` 的 `ChatOrchestrator` 是 capability 分发器。

执行逻辑：

1. 确保 `context.session_id` 存在。
2. 用 `context.active_capability or "chat"` 决定 capability。
3. 从 `CapabilityRegistry` 获取 capability。
4. 如果 capability 不存在但是 `answer_now`，尝试 fallback 到 chat。
5. 先 yield 一个 `SESSION` event。
6. 创建 `StreamBus`。
7. 后台执行 `capability.run(context, bus)`。
8. 从 bus subscribe 并向外 yield event。
9. capability 结束后 emit `DONE`，关闭 bus。
10. 发布 `CAPABILITY_COMPLETE` 到全局 `EventBus`。

`CapabilityRegistry` 在 `deeptutor/runtime/registry/capability_registry.py`：

- 从 `deeptutor/runtime/bootstrap/builtin_capabilities.py` 加载内置能力。
- 尝试加载插件能力。
- 注册对象实例。
- 提供 manifest 列表。

当前内置能力：

| capability | 实现类 |
|---|---|
| `chat` | `deeptutor.capabilities.chat:ChatCapability` |
| `deep_solve` | `deeptutor.capabilities.deep_solve:DeepSolveCapability` |
| `deep_question` | `deeptutor.capabilities.deep_question:DeepQuestionCapability` |
| `deep_research` | `deeptutor.capabilities.deep_research:DeepResearchCapability` |
| `math_animator` | `deeptutor.capabilities.math_animator:MathAnimatorCapability` |
| `visualize` | `deeptutor.capabilities.visualize:VisualizeCapability` |

`ToolRegistry` 在 `deeptutor/runtime/registry/tool_registry.py`：

- 加载 `deeptutor.tools.builtin.BUILTIN_TOOL_TYPES`。
- 支持 tool alias 解析。
- 支持构建 OpenAI function schema。
- 支持 prompt hint 组合。
- 支持 `execute(name, **kwargs)`。

## 8. 内置 Capability 实现

### 8.1 ChatCapability

文件：`deeptutor/capabilities/chat.py`

`ChatCapability` 只是薄包装，真正逻辑在 `deeptutor/agents/chat/agentic_pipeline.py`。

`AgenticChatPipeline` 的阶段：

1. `thinking`
2. `acting`
3. `observing`
4. `responding`

它会：

- 从 `ToolRegistry` 获取启用工具。
- 从 prompt manager 加载 `agentic_chat.yaml`。
- 从 `agents.yaml` 读取 per-stage token budget。
- 用 LLM 先推理，再决定是否调用工具。
- 支持最多 `MAX_PARALLEL_TOOL_CALLS = 8` 的并行工具调用。
- 汇总 observation，再生成最终回答。
- 输出 sources 和 tool traces。

Chat 是默认能力，也是工具增强能力。

### 8.2 DeepSolveCapability

文件：`deeptutor/capabilities/deep_solve.py`

包装 `deeptutor/agents/solve/main_solver.py` 的 `MainSolver`。

阶段：

1. `planning`
2. `reasoning`
3. `writing`

能力 manifest 声明工具：

- `rag`
- `web_search`
- `code_execution`
- `reason`

`MainSolver` 内部是：

```text
PlannerAgent
    -> SolverAgent / ReAct
    -> WriterAgent
```

它通过 `SolveToolRuntime` 连接核心 `ToolRegistry`。Capability 层还把 solver 的 callback 转换成 `StreamBus` 事件，例如：

- LLM running/streaming/complete
- tool_call
- tool_result
- tool_log

如果用户启用 `rag` 但没有选择 KB，能力层会主动移除 `rag`，避免下游暴露不可用工具。

### 8.3 DeepResearchCapability

文件：`deeptutor/capabilities/deep_research.py`

包装 `deeptutor/agents/research/research_pipeline.py` 的 `ResearchPipeline`。

阶段：

1. `rephrasing`
2. `decomposing`
3. `researching`
4. `reporting`

核心流程：

1. 校验 research request config。
2. 根据 enabled tools 和 KB 构建 runtime config。
3. 如果还没有 confirmed outline：
   - 只跑 planning/decompose。
   - 输出 outline preview。
   - 等用户确认。
4. 如果已有 confirmed outline：
   - 初始化 `ResearchPipeline`。
   - 跑 research loop。
   - 生成 final report。

`ResearchPipeline` 内部 agents：

- `RephraseAgent`
- `DecomposeAgent`
- `ManagerAgent`
- `ResearchAgent`
- `NoteAgent`
- `ReportingAgent`

它使用 `DynamicTopicQueue` 管理研究子话题，用 `CitationManager` 管理引用，工具来自全局 `ToolRegistry`。

### 8.4 DeepQuestionCapability

文件：`deeptutor/capabilities/deep_question.py`

包装 `deeptutor/agents/question/coordinator.py` 的 `AgentCoordinator`。

主要模式：

- custom topic 生成题目。
- mimic mode 从上传 PDF 或解析后的 exam directory 仿题。
- follow-up mode 围绕已有 question context 继续解释。

阶段：

1. `ideation`
2. `generation`

它会把 coordinator 的 WebSocket callback 和 trace callback 转换成 StreamBus progress/thinking/tool 事件。

### 8.5 MathAnimatorCapability

文件：`deeptutor/capabilities/math_animator.py`

包装 `deeptutor/agents/math_animator/pipeline.py`。

阶段：

1. `concept_analysis`
2. `concept_design`
3. `code_generation`
4. `code_retry`
5. `summary`
6. `render_output`

特点：

- 依赖可选 `manim`。
- 会生成 Manim 代码。
- 执行渲染。
- 支持 retry。
- 产物放在 workspace，并通过白名单输出路径暴露。

### 8.6 VisualizeCapability

文件：`deeptutor/capabilities/visualize.py`

包装 `deeptutor/agents/visualize/pipeline.py`。

阶段：

1. `analyzing`
2. `generating`
3. `reviewing`

输出类型：

- SVG
- Chart.js
- Mermaid
- HTML

HTML 模式下跳过 LLM review，改用本地 `is_valid_html_document()` 检查，不合法则生成 fallback HTML。

## 9. Tool 内核

内置工具在 `deeptutor/tools/builtin/__init__.py`。

| tool | 职责 | 下游实现 |
|---|---|---|
| `brainstorm` | 多方向头脑风暴 | `deeptutor.tools.brainstorm.brainstorm` |
| `rag` | 知识库检索与综合 | `deeptutor.tools.rag_tool.rag_search` |
| `web_search` | Web 搜索和 citation | `deeptutor.tools.web_search.web_search` |
| `code_execution` | 生成/执行 Python 代码 | `deeptutor.tools.code_executor.run_code` |
| `reason` | 专门 LLM 深度推理 | `deeptutor.tools.reason.reason` |
| `paper_search` | arXiv 搜索 | `deeptutor.tools.paper_search_tool.ArxivSearchTool` |
| `geogebra_analysis` | 图片数学题转 GeoGebra 命令 | `VisionSolverAgent` |

### 9.1 code_execution 的安全边界

`deeptutor/tools/code_executor.py` 做了几类防护：

- AST import guard，只允许白名单模块。
- 禁用危险调用：
  - `open`
  - `exec`
  - `eval`
  - `compile`
  - `__import__`
  - `input`
  - `breakpoint`
- 禁用危险 attribute base：
  - `os`
  - `sys`
  - `subprocess`
  - `socket`
  - `pathlib`
  - `shutil`
  - `importlib`
  - `builtins`
- 执行时使用 `python -I` 隔离模式。
- 每次执行落到 task-scoped `code_runs/` 目录，保留 `code.py`、`output.log` 和 artifacts。

这不是强沙箱，但比裸执行安全很多。若要面向不可信公网用户，应再加容器/权限隔离。

## 10. LLM Provider 内核

LLM 抽象集中在 `deeptutor/services/llm/`。

### 10.1 配置解析

`deeptutor/services/llm/config.py`：

- 优先从统一 config resolver 读取当前 active provider。
- fallback 到 `.env`：
  - `LLM_BINDING`
  - `LLM_MODEL`
  - `LLM_API_KEY`
  - `LLM_HOST`
  - `LLM_API_VERSION`
- 对 OpenAI-compatible binding 提前设置 `OPENAI_API_KEY` / `OPENAI_BASE_URL`，兼容仍读环境变量的库。
- 有全局 config cache，可 `clear_llm_config_cache()`。

### 10.2 Provider registry

`deeptutor/services/provider_registry.py` 是 provider metadata 单一来源。

`ProviderSpec` 定义：

- name
- keywords
- backend
- env_key
- default_api_base
- gateway/local/direct/oauth 标记
- model overrides
- prompt caching 支持
- thinking style

支持的 backend 类型：

- `openai_compat`
- `anthropic`
- `azure_openai`
- `openai_codex`
- `github_copilot`

### 10.3 Provider factory

`deeptutor/services/llm/provider_factory.py` 根据 `LLMConfig.provider_name` 和 `ProviderSpec.backend` 选择具体 provider：

- `OpenAICompatProvider`
- `AnthropicProvider`
- `AzureOpenAIProvider`
- `GitHubCopilotProvider`
- `OpenAICodexProvider`

`deeptutor/services/llm/factory.py` 提供统一函数：

- `complete(...)`
- `stream(...)`
- `fetch_models(...)`

执行时会：

1. 解析 call config。
2. 找 provider spec。
3. 构建 runtime provider。
4. 处理多模态消息。
5. 根据 provider 能力清理不支持的参数，例如 `response_format`。
6. 统一 retry。
7. 用 `map_error()` 映射 provider 错误。

这使上层 agent 不需要直接知道当前模型来自哪家服务。

## 11. RAG 与知识库

`deeptutor/services/rag/service.py` 是统一 RAG 入口。

`RAGService` 默认使用 `services/rag/factory.py` 的 pipeline，当前注释显示是 LlamaIndex pipeline。

核心能力：

- `initialize(kb_name, file_paths)`
- `search(query, kb_name, event_sink)`
- `delete(kb_name)`
- `smart_retrieve(context, kb_name, query_hints, max_queries)`

RAG 搜索过程中会通过 `event_sink` 把 raw logs 和 summary status 桥接回工具事件。`rag` tool 再把这些结果转换成 `ToolResult`。

知识库目录默认在：

```text
DeepTutor/data/knowledge_bases
```

运行时用户数据在：

```text
DeepTutor/data/user
```

## 12. 运行时路径与输出暴露

`deeptutor/services/path_service.py` 集中管理运行时路径，根为：

```text
data/user/
```

典型结构：

```text
data/user/
  chat_history.db
  logs/
  settings/
  workspace/
    memory/
    notebook/
    co-writer/
    book/
    chat/
      chat/
      deep_solve/
      deep_question/
      deep_research/
      math_animator/
      _detached_code_execution/
```

`PathService.is_public_output_path()` 明确控制哪些文件可以通过 `/api/outputs` 暴露：

- co-writer audio
- deep_solve artifacts
- math_animator artifacts
- code_runs artifacts
- detached code execution outputs

并且拒绝 `.json`、`.sqlite`、`.db`、`.md`、`.yaml`、`.yml`、`.py`、`.log` 等私有后缀。

附件存储在 `deeptutor/services/storage/attachment_store.py`：

- 默认本地磁盘。
- 路径在 `data/user/workspace/chat/attachments`。
- 文件名做 sanitize。
- 写入时 tmp + replace，避免半写文件被读取。
- public URL 格式：`/api/attachments/<session>/<attachment>/<filename>`。

## 13. BookEngine：平行于 ChatOrchestrator 的大引擎

`deeptutor/book/engine.py` 明确说明 BookEngine 不属于 `BaseCapability`，而是和 `ChatOrchestrator` 平行的顶层 orchestrator。

生命周期：

```text
create_book(...)
    -> BookProposal
confirm_proposal(...)
    -> Spine
confirm_spine(...)
    -> page shells + queued compilation
compile_page(...)
    -> Page
```

它有自己的：

- `BookStorage`
- `BookCompiler`
- per-book `asyncio.Queue`
- background worker
- `BookStream`，底层仍复用 `StreamBus`

这说明 DeepTutor 后端并非只有聊天能力，Book 是一个独立产品引擎，但仍复用内核事件协议。

## 14. TutorBot：独立自治机器人子系统

`deeptutor/tutorbot/` 是另一个相对独立的运行时：

- channel：Slack、Discord、Telegram、Feishu、WeCom、QQ、Email 等。
- agent loop：自己的 `ToolRegistry`，不同于核心 `runtime.registry.ToolRegistry`。
- tools：filesystem、shell、web、message、spawn、cron、MCP、DeepTutor adapter tools。
- service manager：由 `deeptutor/services/tutorbot/manager.py` 管理启动/停止。

FastAPI startup 会自动启动 TutorBots，shutdown 会停止它们。它们和主 ChatOrchestrator 不是同一条执行路径，但能通过 adapter tools 调用 DeepTutor 的核心工具能力。

## 15. 前端与后端交互边界

`web/` 是 Next.js 前端。后端暴露：

- REST APIs：知识库、notebook、book、memory、settings、skills、attachments、plugins、tutorbot 等。
- 统一聊天 WebSocket：`/api/v1/ws`。
- 专用 WebSocket：
  - solve
  - question
  - knowledge progress
  - book
  - vision solver
  - tutorbot

新的核心聊天体验应优先走 `/api/v1/ws`，因为它完整支持 turn、resume、cancel、regenerate、session replay。

## 16. 典型请求链路

### 16.1 Web 聊天请求

```text
Next.js client
  -> WebSocket /api/v1/ws
  -> unified_ws.message/start_turn
  -> TurnRuntimeManager.start_turn
  -> SQLite sessions/turns
  -> _run_turn background task
  -> attachment extraction + context build + memory + skills
  -> UnifiedContext
  -> ChatOrchestrator.handle
  -> CapabilityRegistry.get(active_capability)
  -> capability.run(context, StreamBus)
  -> StreamEvent
  -> turn_events persisted with seq
  -> live WebSocket subscriber
  -> assistant message persisted
```

### 16.2 CLI 请求

```text
deeptutor run deep_research "topic"
  -> deeptutor_cli.main.run_capability
  -> DeepTutorApp.start_turn
  -> TurnRuntimeManager.start_turn
  -> same runtime as Web
  -> DeepTutorApp.stream_turn
  -> CLI renderer
```

### 16.3 Tool 调用

```text
AgenticChatPipeline / SolveToolRuntime / ResearchPipeline
  -> ToolRegistry.get/execute
  -> BaseTool.execute
  -> ToolResult
  -> StreamBus.tool_call/tool_result
  -> persisted turn_events
```

### 16.4 LLM 调用

```text
BaseAgent / AgenticChatPipeline / tool
  -> services.llm.complete or stream
  -> _resolve_call_config
  -> provider_registry.ProviderSpec
  -> provider_factory.get_runtime_provider
  -> provider.chat_with_retry / chat_stream_with_retry
  -> mapped response/errors
```

## 17. 架构优点

1. **入口统一**：Web、CLI、SDK 都能复用 `TurnRuntimeManager` 和 `ChatOrchestrator`。
2. **事件协议统一**：所有能力输出同一种 `StreamEvent`，便于 UI、CLI、持久化、断线恢复共用。
3. **能力插件化**：新增多阶段能力只需实现 `BaseCapability` 并注册 manifest。
4. **工具插件化**：工具有统一 schema、prompt hint、执行结果。
5. **Provider 解耦**：agent 不直接依赖某个 LLM SDK。
6. **上下文装配集中**：附件、notebook、history、memory、skills 都在 `_run_turn()` 前置装配，capability 更干净。
7. **断线恢复友好**：`turn_events` 的 seq 持久化让 WebSocket resume 简单。
8. **运行时路径集中**：`PathService` 限制用户数据、workspace 和 public output 边界。

## 18. 架构风险与注意点

1. **`TurnRuntimeManager._run_turn()` 过重**
   - 它同时处理附件、文档提取、上下文构建、memory、skills、notebook、history、orchestrator、事件持久化。
   - 后续维护时应警惕继续膨胀。

2. **Capability 包装层存在大量 callback 桥接代码**
   - deep_solve、deep_research、deep_question 都有自己的 trace/progress normalization。
   - 好处是 UI 事件统一，坏处是 callback schema 不是强类型合同。

3. **code_execution 不是强隔离沙箱**
   - 虽然有 AST guard、import 白名单、`python -I`、workspace 限制，但仍是同机子进程。
   - 多租户或公网不可信执行需要容器、seccomp、权限用户、资源限制。

4. **插件加载路径在代码中存在但当前目录未明显展开**
   - `CapabilityRegistry.load_plugins()` 尝试加载 `deeptutor.plugins.loader`。
   - 本地树中主要内置能力已经覆盖主功能；插件机制需要进一步确认实际插件目录和 manifest 是否完整。

5. **BookEngine 与 ChatOrchestrator 平行**
   - 这不是坏事，但意味着“统一能力模型”并未覆盖所有产品引擎。
   - 如果未来要把 Book 也纳入同一 capability runtime，需要额外抽象。

6. **TutorBot 有自己的工具系统**
   - TutorBot 的 `ToolRegistry` 和核心 `runtime.registry.ToolRegistry` 不同。
   - 需要避免未来出现能力重复、权限边界不一致。

7. **配置依赖 runtime settings**
   - `load_config_with_main("main.yaml")` 现在期望配置在 `data/user/settings/`。
   - 部署/迁移时如果 settings 缺失，部分 agent 初始化会失败。

## 19. 可复用到 Irene/Repo Tutor 的设计启发

1. **把请求先落成 turn，再异步执行**
   - 这比直接 SSE/WS 推流更适合恢复、取消、重试和审计。

2. **把 StreamEvent 作为内部统一协议**
   - UI 不需要知道 deep_solve、deep_research、chat 内部差异，只看 event type/source/stage。

3. **用 CapabilityManifest 做能力合同**
   - 前端可以从 manifest 获得 stages、tools、request_schema、config_defaults。

4. **上下文装配前置**
   - notebook/history/memory/skills/attachments 统一进入 `UnifiedContext`，避免每个 agent 重复实现。

5. **工具注册表和 prompt hint 分离**
   - Tool schema 用于 function calling，prompt hint 用于自然语言策略，两者都很有价值。

6. **LLM provider 单一工厂**
   - 对多 provider 应用很关键，尤其是 response_format、max token 字段、thinking blocks、多模态兼容差异。

7. **turn_events 持久化 seq 是断线恢复关键**
   - 只保存最终 assistant message 不够，必须保存流式事件。

## 20. 关键文件索引

| 文件 | 为什么重要 |
|---|---|
| `DeepTutor/deeptutor/api/main.py` | FastAPI app、lifespan、router 注册、输出白名单 |
| `DeepTutor/deeptutor/api/run_server.py` | Uvicorn 启动脚本 |
| `DeepTutor/deeptutor/api/routers/unified_ws.py` | 统一 WebSocket 协议 |
| `DeepTutor/deeptutor/app/facade.py` | CLI/SDK 稳定 facade |
| `DeepTutor/deeptutor/services/session/turn_runtime.py` | turn 执行中心 |
| `DeepTutor/deeptutor/services/session/sqlite_store.py` | session/message/turn/event SQLite 模型 |
| `DeepTutor/deeptutor/services/session/context_builder.py` | 历史上下文预算和压缩 |
| `DeepTutor/deeptutor/core/context.py` | `UnifiedContext` |
| `DeepTutor/deeptutor/core/stream.py` | `StreamEvent` 协议 |
| `DeepTutor/deeptutor/core/stream_bus.py` | 单 turn 事件总线 |
| `DeepTutor/deeptutor/core/capability_protocol.py` | capability 抽象 |
| `DeepTutor/deeptutor/core/tool_protocol.py` | tool 抽象 |
| `DeepTutor/deeptutor/runtime/orchestrator.py` | capability 分发器 |
| `DeepTutor/deeptutor/runtime/registry/capability_registry.py` | capability 注册表 |
| `DeepTutor/deeptutor/runtime/registry/tool_registry.py` | tool 注册表 |
| `DeepTutor/deeptutor/runtime/bootstrap/builtin_capabilities.py` | 内置能力清单 |
| `DeepTutor/deeptutor/capabilities/*.py` | 内置能力包装层 |
| `DeepTutor/deeptutor/agents/chat/agentic_pipeline.py` | 默认 chat agentic pipeline |
| `DeepTutor/deeptutor/agents/solve/main_solver.py` | Deep Solve Plan/ReAct/Write |
| `DeepTutor/deeptutor/agents/research/research_pipeline.py` | Deep Research 多 agent pipeline |
| `DeepTutor/deeptutor/tools/builtin/__init__.py` | 内置工具 schema 与包装 |
| `DeepTutor/deeptutor/tools/code_executor.py` | 代码执行工具与安全边界 |
| `DeepTutor/deeptutor/services/llm/config.py` | LLM 配置 |
| `DeepTutor/deeptutor/services/provider_registry.py` | provider metadata 单一来源 |
| `DeepTutor/deeptutor/services/llm/factory.py` | complete/stream 统一入口 |
| `DeepTutor/deeptutor/services/llm/provider_factory.py` | provider runtime 选择 |
| `DeepTutor/deeptutor/services/rag/service.py` | RAG 服务入口 |
| `DeepTutor/deeptutor/services/path_service.py` | 运行时路径与 public output 边界 |
| `DeepTutor/deeptutor/services/storage/attachment_store.py` | 附件持久化 |
| `DeepTutor/deeptutor/book/engine.py` | BookEngine 平行引擎 |
| `DeepTutor/deeptutor_cli/main.py` | CLI 入口 |

## 21. 一句话架构图

```text
DeepTutor = FastAPI/CLI/SDK adapters
  + TurnRuntimeManager(session, context, persistence, replay)
  + ChatOrchestrator(capability dispatch)
  + CapabilityRegistry(multi-agent pipelines)
  + ToolRegistry(function tools)
  + LLM provider factory
  + RAG/storage/path/session services
```

如果只抓“内核最小闭环”，就是：

```text
UnifiedContext -> ChatOrchestrator -> BaseCapability -> StreamBus -> TurnRuntimeManager -> SQLite/WebSocket
```

## 22. 补充侦察

- `deeptutor_agents_implementation_logic.md`：专门记录 `DeepTutor/deeptutor/agents/` 的具体实现逻辑，包括 chat、deep_solve、deep_research、deep_question、visualize、math_animator、notebook 和 vision_solver 的 pipeline 结构，以及可迁移到 new_kernel 的设计结论。
