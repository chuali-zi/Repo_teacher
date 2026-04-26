# 现有后端架构分析

本文基于当前 `backend/` 代码整理，目标不是复述目录名，而是说明每个模块、每个文件在运行时实际做什么、彼此怎么连接、主调用链怎么走。

本文覆盖 `backend/**/*.py` 中参与运行或测试的 Python 文件。
不覆盖 `__pycache__/`、`.uvicorn*.log`、`pytest_tmp_refactor/`、`backend/tests/fixtures/**` 里的样例仓库文件，因为这些是缓存、日志或测试输入，不属于后端运行架构本身。

## 1. 后端整体定位

这个后端不是传统的“Controller -> Service -> DB”应用，而是一个“单活会话 + 仓库静态扫描 + SSE 流式讲解 + 只读工具调用”的带读系统。

它的几个关键特点是：

1. 只有一个活跃会话。
2. 会话状态完全保存在内存里，没有数据库持久化。
3. 用户提交仓库后，并不会立刻在 `POST /api/repo` 里完成分析，真正的分析是在消费 `/api/analysis/stream` 这个 SSE 流时触发的。
4. 用户发追问后，也不会在 `POST /api/chat` 里直接拿到回答，真正的回答生成发生在 `/api/chat/stream` 的 SSE 流里。
5. 仓库读取是只读的，默认不执行代码、不安装依赖、不访问私有 GitHub 仓库。
6. LLM 不是直接“盲答”，而是先拿到文件树摘要、教学状态和工具结果，需要时再通过安全工具读取源码片段或搜索文本。

## 2. 架构分层

当前代码大致可以按下面几层理解：

1. API 入口层
2. 会话与工作流编排层
3. 仓库接入层
4. 文件树扫描与安全层
5. 回答生成层
6. 工具注册与工具运行时
7. 深度研究分支
8. 契约层

更具体地说：

| 层 | 目录 | 实际职责 |
| --- | --- | --- |
| 应用入口 | `backend/main.py` | 创建 FastAPI 应用，挂载 router，注册异常处理 |
| 路由层 | `backend/routes/` | 接 HTTP 请求，把请求转给 `session_service` 或 sidecar |
| 契约层 | `backend/contracts/` | 定义全系统枚举、领域模型、API DTO、SSE 事件 DTO |
| 仓库接入 | `backend/m1_repo_access/` | 校验输入，接入本地目录，或 clone 公共 GitHub 仓库 |
| 文件树扫描 | `backend/m2_file_tree/` | 递归扫描、过滤敏感/忽略文件、识别语言、判断仓库大小 |
| 安全层 | `backend/security/` | 路径越界保护、只读策略、敏感/忽略模式匹配 |
| 会话编排 | `backend/m5_session/` | 维护活跃会话、推进状态机、触发分析和聊天工作流、产生运行时事件 |
| 回答生成 | `backend/m6_response/` | 组装 prompt、调用 LLM、解析结构化回答、桥接工具执行 |
| 工具定义 | `backend/agent_tools/` | 定义给 LLM 使用的只读工具和工具注册表 |
| 工具运行时 | `backend/agent_runtime/` | 选择工具、预置工具上下文、执行 tool loop |
| LLM 工具兼容层 | `backend/llm_tools/` | 对外提供工具上下文构建的兼容入口 |
| 深度研究 | `backend/deep_research/` | 对 Python 仓库做确定性的静态“深度研究”首轮报告 |
| Sidecar | `backend/sidecar/` | 提供与主会话解耦的小回答器 |

## 3. 主调用链

### 3.1 提交仓库到初始分析完成

```text
POST /api/repo
-> routes/repo.py
-> SessionService.create_repo_session()
-> 仅创建一个 status=accessing 的内存会话

GET /api/analysis/stream?session_id=...
-> routes/analysis.py
-> event_streams.iter_analysis_events()
-> SessionService.run_initial_analysis()
-> AnalysisWorkflow.run()
-> m1_repo_access.access_repository()
-> m2_file_tree.scan_repository_tree()
-> TeachingService.initialize_teaching_state()
-> 分流：
   - deep_research + Python 仓库
     -> deep_research.pipeline
   - 其他情况
     -> TeachingService.build_initial_report_prompt_input()
     -> answer_generator.stream_answer_text_with_tools()
     -> agent_runtime.tool_loop.stream_answer_text_with_tools()
     -> llm_caller.stream_llm_response_with_tools()
     -> tool_executor.execute_tool_call()
-> AnalysisWorkflow._complete_initial_report()
-> session 切到 chatting / waiting_user
-> runtime event 映射成 SSE 持续发给前端
```

### 3.2 用户追问到回答完成

```text
POST /api/chat
-> routes/chat.py
-> SessionService.accept_chat_message()
-> 只把用户消息写进会话，并把 sub_status 切到 agent_thinking

GET /api/chat/stream?session_id=...
-> routes/chat.py
-> event_streams.iter_chat_events()
-> SessionService.run_chat_turn()
-> ChatWorkflow.run()
-> TeachingService.build_prompt_input()
-> answer_generator.stream_answer_text_with_tools()
-> agent_runtime.tool_loop.stream_answer_text_with_tools()
-> llm_caller.stream_llm_response_with_tools()
-> 可能发生 0~N 轮工具调用
-> response_parser.parse_final_answer()
-> TeachingService.update_teaching_state_after_answer()
-> session 回到 chatting / waiting_user
-> SSE 发出最终 message_completed
```

### 3.3 SSE 与断线重连

```text
routes/analysis.py or routes/chat.py
-> event_streams.py
-> reconnect_queries.py 先回放必要事件
-> 如果流程未结束，再真正执行 workflow
-> event_mapper.py 把 RuntimeEvent 转成 DTO
-> contracts/sse.py 编码成 text/event-stream
```

### 3.4 工具调用链

```text
TeachingService.build_prompt_input()
-> llm_tools.context_builder.build_llm_tool_context()
-> agent_runtime.context_budget.build_llm_tool_context()
-> agent_runtime.tool_selection.select_tools_for_turn()
-> m6_response.prompt_builder.build_messages()
-> agent_runtime.tool_loop.stream_answer_text_with_tools()
-> m6_response.llm_caller.stream_llm_response_with_tools()
-> m6_response.tool_executor.execute_tool_call()
-> agent_tools.registry.DEFAULT_TOOL_REGISTRY.execute()
-> agent_tools.analysis_tools / agent_tools.repository_tools
```

## 4. 核心状态与数据怎么流动

### 4.1 `SessionContext`

`SessionContext` 是整个后端最核心的状态容器，定义在 `backend/contracts/domain.py`。

它承载了：

1. 当前 session id、状态、更新时间。
2. 当前仓库上下文 `RepositoryContext`。
3. 当前文件树快照 `FileTreeSnapshot`。
4. 深度研究进度 `DeepResearchRunState`。
5. 对话状态 `ConversationState`。
6. 当前错误、降级标记、活动 agent 状态。
7. 运行时事件列表 `runtime_events`。

这个对象被 `SessionService` 创建，被 `AnalysisWorkflow` / `ChatWorkflow` 持续修改，被 `/api/session` 和 SSE 输出消费。

### 4.2 `ConversationState`

`ConversationState` 保存的是教学相关的上下文，而不是 HTTP 会话信息。

它包含：

1. 当前学习目标。
2. 当前教学阶段。
3. 已解释过的 topic/item。
4. 历史消息列表 `messages`。
5. 历史摘要 `history_summary`。
6. 教学计划、学生状态、教师工作日志。
7. 当前教学决策和教学指令。

`TeachingService` 和 `teaching_state.py` 负责读写它。

### 4.3 `RepositoryContext` 与 `FileTreeSnapshot`

仓库先由 M1 接入，形成 `RepositoryContext`；随后由 M2 扫描形成 `FileTreeSnapshot`。

这两个对象会继续流入：

1. `deep_research.pipeline`
2. `agent_tools.repository_tools`
3. `agent_runtime.context_budget`
4. `m6_response.prompt_builder`

### 4.4 `RuntimeEvent` 与 `MessageRecord`

后端所有“给前端看的过程状态”都不是直接从 workflow 里拼 SSE，而是先落成内部事件 `RuntimeEvent`。

然后：

1. `event_mapper.py` 把 `RuntimeEvent` 转成对外 `SseEventDto`。
2. `contracts/sse.py` 把 DTO 编成 SSE 文本。

真正的最终消息则落在 `ConversationState.messages` 里的 `MessageRecord` 中，再被 `/api/session` 快照和 `message_completed` 事件输出。

### 4.5 `PromptBuildInput` 与 `LlmToolContext`

这两个对象是“教学态 -> LLM 输入”的桥。

流程是：

1. `TeachingService` 根据会话和用户问题推导场景、目标、深度。
2. `agent_runtime.context_budget` 预执行一部分确定性工具，得到精简工具上下文。
3. `PromptBuildInput` 把当前场景、工具上下文、输出契约、对话状态打包给 `prompt_builder.py`。
4. `prompt_builder.py` 再把这些内容拼成真正发给 LLM 的 messages。

## 5. 逐模块、逐文件说明

### 5.1 应用入口与路由层

| 文件 | 实际职责 | 主要上游 | 主要下游 |
| --- | --- | --- | --- |
| `backend/__init__.py` | 包标记文件，没有业务逻辑。 | Python 导入系统 | 无 |
| `backend/main.py` | 创建 FastAPI 应用，配置 CORS，挂载 repo/session/analysis/chat/sidecar 路由，注册请求体验证异常处理。 | `uvicorn` | `routes.*`, `contracts.dto.error_envelope` |
| `backend/routes/__init__.py` | 路由包标记文件，没有业务逻辑。 | `backend.main` | 无 |
| `backend/routes/repo.py` | 提供 `/api/repo/validate` 和 `/api/repo`。前者只做输入分类，后者只创建会话，不做真正分析。 | 前端 HTTP 请求 | `m5_session.session_service` |
| `backend/routes/analysis.py` | 提供 `/api/analysis/stream`，校验 session 后把分析工作流包装成 SSE。 | 前端 SSE 连接 | `event_streams.iter_analysis_events`, `contracts.sse.encode_sse_stream` |
| `backend/routes/chat.py` | 提供 `/api/chat` 和 `/api/chat/stream`。`POST` 只接收消息并切换到思考态，真正回答在 stream 中执行。 | 前端 HTTP/SSE | `session_service.accept_chat_message`, `event_streams.iter_chat_events` |
| `backend/routes/session.py` | 提供 `/api/session` 快照和 `DELETE /api/session` 清理接口。 | 前端 HTTP 请求 | `session_service.get_snapshot`, `session_service.clear_session` |
| `backend/routes/sidecar.py` | 提供与主会话解耦的 `/api/sidecar/explain`。 | 前端 HTTP 请求 | `sidecar.explainer.explain_question` |
| `backend/routes/_errors.py` | 把 `UserFacingError` 包成统一 JSON 错误响应，并映射 HTTP 状态码。 | 各 route | `contracts.dto.error_envelope` |
| `backend/routes/_sse.py` | 把错误包装成单条 SSE error event；必要时补足当前 session 的状态和 view。 | 各 SSE route | `contracts.sse.encode_sse_stream`, `session_service.store` |

### 5.2 契约层

| 文件 | 实际职责 | 主要上游 | 主要下游 |
| --- | --- | --- | --- |
| `backend/contracts/__init__.py` | 把 `domain`、`dto`、`enums` 聚合导出，方便统一 import。 | 运行时代码 | `contracts.*` 使用者 |
| `backend/contracts/enums.py` | 定义全系统枚举，包括 session 状态、消息类型、教学目标、SSE 事件、工具活动阶段、错误码等。 | 所有模块 | 所有使用枚举的模块 |
| `backend/contracts/domain.py` | 定义内部领域模型，是系统真实状态的核心，包括 `SessionContext`、`ConversationState`、`RepositoryContext`、`FileTreeSnapshot`、`RuntimeEvent`、`StructuredAnswer` 等。 | 所有核心模块 | DTO 层、workflow、tool runtime |
| `backend/contracts/dto.py` | 定义对外 API DTO 与 SSE DTO，并提供 `success_envelope` / `error_envelope`。 | routes, event_mapper, session_service | 前端 API / SSE 消费方 |
| `backend/contracts/sse.py` | 把 SSE DTO 编成标准 `event:` / `data:` 文本流。 | `routes/analysis.py`, `routes/chat.py`, `_sse.py` | 浏览器 EventSource |

### 5.3 仓库接入层 `m1_repo_access`

| 文件 | 实际职责 | 主要上游 | 主要下游 |
| --- | --- | --- | --- |
| `backend/m1_repo_access/__init__.py` | 对外暴露 `access_repository()`，负责根据输入类型在“本地路径”与“GitHub clone”之间分发。 | `AnalysisWorkflow` | `input_validator`, `local_repo_accessor`, `github_repo_cloner` |
| `backend/m1_repo_access/input_validator.py` | 只做输入形态识别和归一化，不检查路径是否存在，也不访问网络。 | `routes/repo.py`, `SessionService`, `m1_repo_access.__init__` | 返回 `ValidateRepoData` |
| `backend/m1_repo_access/local_repo_accessor.py` | 校验本地目录输入的安全性、存在性、目录属性和可读性，生成 `RepositoryContext`。 | `m1_repo_access.__init__` | `security` 风格约束，返回 `RepositoryContext` |
| `backend/m1_repo_access/github_repo_cloner.py` | clone 公共 GitHub 仓库到临时目录，并把 timeout/git 不可用/仓库不可访问等异常映射成用户可见错误。 | `m1_repo_access.__init__` | `git`, `TempResourceSet`, `RepositoryContext` |

### 5.4 文件树扫描与安全层

| 文件 | 实际职责 | 主要上游 | 主要下游 |
| --- | --- | --- | --- |
| `backend/m2_file_tree/__init__.py` | 暴露 `scan_repository_tree`，是 M2 的对外入口。 | `AnalysisWorkflow` | `tree_scanner.py` |
| `backend/m2_file_tree/tree_scanner.py` | 递归扫描目录，生成 `FileNode`，应用过滤规则，检测主语言和仓库大小，最终形成 `FileTreeSnapshot`。 | `AnalysisWorkflow` | `file_filter`, `language_detector`, `repo_sizer`, `security.safety` |
| `backend/m2_file_tree/file_filter.py` | 合并内置忽略规则、敏感规则和 `.gitignore`，把节点标成 `normal`、`ignored`、`sensitive_skipped`。 | `tree_scanner.py` | 过滤后的 `FileNode` / `IgnoreRule` / `SensitiveFileRef` |
| `backend/m2_file_tree/language_detector.py` | 根据扩展名统计语言分布并推断主语言。 | `tree_scanner.py` | `FileTreeSnapshot.language_stats` |
| `backend/m2_file_tree/repo_sizer.py` | 根据源码文件数判断 small/medium/large，大仓库时产出降级扫描范围说明。 | `tree_scanner.py` | `FileTreeSnapshot.repo_size_level`, `degraded_scan_scope` |
| `backend/security/__init__.py` | 包标记与模块说明，无业务逻辑。 | Python 导入系统 | 无 |
| `backend/security/safety.py` | 定义默认只读策略、路径越界保护、敏感与忽略模式匹配，是整个仓库读取安全边界的基础。 | M1、M2、repository_tools | `ReadPolicySnapshot`, 路径校验、pattern 匹配 |

### 5.5 会话与工作流层 `m5_session`

| 文件 | 实际职责 | 主要上游 | 主要下游 |
| --- | --- | --- | --- |
| `backend/m5_session/__init__.py` | 导出全局单例 `session_service`，这是后端绝大多数路由真正依赖的门面。 | 各 route | `session_service.py` |
| `backend/m5_session/session_service.py` | 系统主门面。创建/清理单活会话，接受用户消息，触发分析与聊天工作流，输出 session 快照。真实职责已经接近“应用编排根”，不只是 session CRUD。 | 各 route | `AnalysisWorkflow`, `ChatWorkflow`, `TeachingService`, `SessionRepository`, `RuntimeEventService` |
| `backend/m5_session/analysis_workflow.py` | 初始分析主流程。负责仓库接入、文件树扫描、降级判定、教学状态初始化、首轮报告生成、状态切换和消息落库。 | `SessionService.run_initial_analysis` | M1、M2、deep_research、M6、teaching、runtime_events |
| `backend/m5_session/chat_workflow.py` | 聊天回合主流程。负责把会话从 thinking 推到 streaming，驱动 LLM 与工具循环，解析回答，更新教学状态，再切回 waiting_user。 | `SessionService.run_chat_turn` | `TeachingService`, `m6_response`, `runtime_events` |
| `backend/m5_session/teaching_service.py` | 教学编排层。根据用户问题推导 learning goal、depth、scenario，构建 `PromptBuildInput`，更新教学状态，裁剪建议。 | `analysis_workflow`, `chat_workflow`, `session_service` | `llm_tools.context_builder`, `teaching_state.py` |
| `backend/m5_session/teaching_state.py` | 纯教学状态机与一组纯函数。负责初始化教学计划/学生状态/教师日志，以及每轮回答后的状态推进。 | `TeachingService` | 返回新的 plan/student/log/decision/directive |
| `backend/m5_session/runtime_events.py` | 运行时事件工厂。负责状态切换、进度步、agent activity、error、degradation 事件的创建和落库。 | `session_service`, `analysis_workflow`, `chat_workflow` | `SessionContext.runtime_events` |
| `backend/m5_session/event_mapper.py` | 把内部 `RuntimeEvent` 映射成对外 `SseEventDto`。 | `event_streams.py` | `contracts.dto.*Event` |
| `backend/m5_session/event_streams.py` | SSE 事件迭代器。先做断线重放，再决定是否真正启动分析或聊天工作流。 | `routes/analysis.py`, `routes/chat.py` | `session_service`, `event_mapper` |
| `backend/m5_session/repository.py` | 这里的 repository 不是仓库访问层，而是 session repository。负责获取 active session、校验 session id、清理临时资源、查找最近事件。 | `SessionService`, `ReconnectQueryService` | `SessionStore`, `TempResourceSet` |
| `backend/m5_session/reconnect_queries.py` | 断线重连查询层。根据当前 session 状态拼出前端恢复所需的最小事件集。 | `event_streams.py` | `SessionRepository`, `RuntimeEventService` |
| `backend/m5_session/state_machine.py` | 定义 session 状态机允许的转换，以及 status -> client view 的映射。 | `SessionService`, `RuntimeEventService`, `_sse.py` | 状态校验和 view 计算 |
| `backend/m5_session/common.py` | 存放生成 id、UTC 时间、初始进度步、goal 关键词等公共函数和常量。 | `m5_session` 内多个模块 | 公共基础函数 |
| `backend/m5_session/errors.py` | 统一构造常见用户可见错误，如 invalid request、analysis failed、llm failed。 | `SessionService`, `RuntimeEventService`, sidecar | `UserFacingError` |

### 5.6 回答生成层 `m6_response`

| 文件 | 实际职责 | 主要上游 | 主要下游 |
| --- | --- | --- | --- |
| `backend/m6_response/__init__.py` | 说明性模块，不承担实际业务逻辑。 | Python 导入系统 | 无 |
| `backend/m6_response/answer_generator.py` | 回答生成的统一入口包装层。负责 build messages、计算输出 token budget、解析最终回答，并 re-export tool loop 类型。 | `analysis_workflow`, `chat_workflow` | `prompt_builder`, `llm_caller`, `response_parser`, `agent_runtime.tool_loop` |
| `backend/m6_response/prompt_builder.py` | 生成 system prompt 和 messages，把教学指令、历史摘要、工具上下文、安全限制打包给 LLM，并做脱敏。 | `answer_generator`, `tool_loop` | LLM 输入消息 |
| `backend/m6_response/llm_caller.py` | 实际对接 OpenAI-compatible chat completions。支持普通流式、非流式文本完成、带 tool_calls 的流式响应。 | `answer_generator`, `tool_loop`, `sidecar.explainer` | 外部 LLM API |
| `backend/m6_response/response_parser.py` | 从“可见 Markdown + `<json_output>` 机器侧车”解析出 `InitialReportAnswer` 或 `StructuredAnswer`，结构缺失时会做 best effort 兜底。 | `analysis_workflow`, `chat_workflow`, `answer_generator` | 结构化回答对象 |
| `backend/m6_response/tool_executor.py` | 工具执行桥接层。把 LLM 的工具名映射到 registry，执行工具，做缓存，并返回 JSON 字符串结果。 | `agent_runtime.tool_loop` | `agent_tools.registry`, `ToolResultCache` |
| `backend/m6_response/sidecar_stream.py` | 在流式输出时增量剥离 `<json_output>`，确保前端只看到可见正文。 | `analysis_workflow`, `chat_workflow` | 用户可见文本流 |
| `backend/m6_response/budgets.py` | 定义输出 token 预算与工具上下文字符预算。 | `answer_generator`, `context_budget` | token / context 限额 |
| `backend/m6_response/suggestion_generator.py` | 根据 topic refs 和当前 goal 生成下一步建议。它是一个可复用辅助模块，但当前主路径里更常见的是直接使用 LLM 返回建议，再由 `TeachingService.ensure_*` 截断到 3 条。 | 潜在建议生成调用点 | `Suggestion` 列表 |

### 5.7 工具定义、工具运行时与兼容层

| 文件 | 实际职责 | 主要上游 | 主要下游 |
| --- | --- | --- | --- |
| `backend/agent_tools/__init__.py` | 聚合导出工具注册表、缓存、截断与基础类型。 | M6、agent_runtime、llm_tools | `agent_tools.*` |
| `backend/agent_tools/base.py` | 定义 `ToolSpec`、`ToolContext`、`SeedPlanItem`，并提供 OpenAI function schema 导出。 | `registry.py`, 具体工具定义 | 工具元数据 |
| `backend/agent_tools/registry.py` | 统一注册分析类工具和仓库读取类工具，支持内部名、alias、API-safe 名之间的映射。 | `tool_executor`, `context_budget`, `llm_tools` | `analysis_tools`, `repository_tools` |
| `backend/agent_tools/analysis_tools.py` | 提供高层只读摘要工具，如仓库上下文、文件树摘要、相关文件列表、教学状态快照；也能生成 starter excerpts。 | `registry.py`, `context_budget` | `ToolResult` |
| `backend/agent_tools/repository_tools.py` | 提供两个真正接触源码的只读工具：`read_file_excerpt` 和 `search_text`。同时负责路径安全、可读性过滤、文件大小限制、脱敏、超时降级。 | `registry.py`, `tool_executor`, `analysis_tools` | 读文件和搜索结果 |
| `backend/agent_tools/cache.py` | 基于 `file_tree.snapshot_id` 做 deterministic tool result 缓存。 | `tool_executor`, `context_budget` | `ToolResultCache` |
| `backend/agent_tools/truncation.py` | 把过大的 tool result 截断到 LLM 上下文预算内。 | `context_budget`, `serialize_tool_result` | 截断后的 payload |
| `backend/agent_runtime/__init__.py` | 聚合导出工具上下文构建与 tool loop 相关类型。 | `answer_generator`, 其他调用方 | `context_budget`, `tool_loop` |
| `backend/agent_runtime/tool_selection.py` | 基于场景、学习目标、用户文本选择本轮允许的工具集合。 | `context_budget`, `tool_loop` | `ToolSelection` |
| `backend/agent_runtime/context_budget.py` | 预执行少量确定性 seed tools，剪裁结果，把它们塞进 `LlmToolContext`，这是“先给模型一些已知证据”的关键层。 | `TeachingService.build_tool_context`, `llm_tools.context_builder` | `agent_tools`, `tool_selection`, `budgets` |
| `backend/agent_runtime/tool_loop.py` | 核心函数调用循环。负责让 LLM 输出 tool_calls、并发执行工具、处理软/硬超时、把 tool 结果回灌给模型，并在达到轮数上限后强制 no-tool 收尾。 | `analysis_workflow`, `chat_workflow`, `answer_generator` | `llm_caller`, `tool_executor`, `tool_selection` |
| `backend/llm_tools/__init__.py` | 旧式 LLM 工具入口的聚合导出。 | `TeachingService` 等 | `context_builder.py` |
| `backend/llm_tools/context_builder.py` | 兼容层。对外暴露 `build_llm_tool_context`、`read_file_excerpt`、`search_text`，但真正预算逻辑已下沉到 `agent_runtime.context_budget`。 | `TeachingService`, 外部兼容调用点 | `agent_runtime.context_budget`, `DEFAULT_TOOL_REGISTRY` |

### 5.8 深度研究分支与 sidecar

| 文件 | 实际职责 | 主要上游 | 主要下游 |
| --- | --- | --- | --- |
| `backend/deep_research/__init__.py` | 聚合导出深度研究相关函数。 | `analysis_workflow` | `pipeline.py`, `source_selection.py` |
| `backend/deep_research/source_selection.py` | 从 `FileTreeSnapshot` 中挑选“第一轮值得研究”的 source/config/doc 文件，排除测试、vendor、生成物、敏感文件。 | `pipeline.py` | `RelevantSourceFile` 列表 |
| `backend/deep_research/pipeline.py` | 深度研究主流程的实现。它不是 agent 式研究，而是确定性的静态文件阅读、AST outline、分组总结、综合报告生成。 | `AnalysisWorkflow` | `source_selection`, `security.safety`, `InitialReportAnswer` |
| `backend/sidecar/__init__.py` | 聚合导出 `explainer`。 | `routes/sidecar.py` | `explainer.py` |
| `backend/sidecar/explainer.py` | 独立的小回答器，只根据用户当前一句问题生成 120 字内解释，不看仓库上下文。 | `routes/sidecar.py` | `m6_response.llm_caller.complete_llm_text` |

## 6. 模块之间的真实依赖关系

如果把依赖关系压缩成几条主线，可以这样看：

### 6.1 HTTP 主线

`main.py` -> `routes/*.py` -> `m5_session.session_service`

路由层非常薄，几乎不写业务逻辑，主要职责是：

1. 接请求。
2. 调 `session_service`。
3. 把错误包装成统一 JSON 或 SSE。

### 6.2 分析主线

`SessionService` -> `AnalysisWorkflow` -> `m1_repo_access` -> `m2_file_tree` -> `TeachingService` -> `deep_research` 或 `m6_response` -> `RuntimeEventService`

这条线说明：

1. `session_service` 是调度入口。
2. 真正的分析顺序在 `analysis_workflow.py`。
3. 分析前半段是确定性的仓库接入和静态扫描。
4. 分析后半段要么走深度研究分支，要么走 LLM 首轮报告分支。
5. 全流程都通过 runtime events 对外暴露进度。

### 6.3 聊天主线

`SessionService` -> `ChatWorkflow` -> `TeachingService` -> `m6_response.answer_generator` -> `agent_runtime.tool_loop` -> `agent_tools`

这条线说明：

1. 聊天不是简单“把用户问题转给 LLM”。
2. 先由 `TeachingService` 判断这轮究竟是在讲结构、入口、流程还是总结。
3. 再根据场景和目标选择工具、构建工具上下文、决定是否允许 tool calling。
4. 最后才进入实际 LLM/tool loop。

### 6.4 事件主线

`workflow` -> `RuntimeEventService` -> `SessionContext.runtime_events` -> `ReconnectQueryService` -> `event_mapper.py` -> `contracts/sse.py`

这条线说明：

1. 事件是内部一等公民。
2. 前端看到的所有状态变化，本质上都来自 `RuntimeEvent`。
3. 断线重连不是重新执行全部流程，而是尽量回放必要事件。

## 7. 命名和真实职责的偏差

下面这些地方如果只看文件名，容易误判：

| 文件 | 文件名给人的直觉 | 实际职责 |
| --- | --- | --- |
| `backend/m5_session/repository.py` | 像仓库访问层 | 实际是 session repository，只管理内存中的 active session 和 runtime events |
| `backend/m5_session/session_service.py` | 像一个普通 service | 实际是整个后端的应用门面和组合根 |
| `backend/routes/repo.py` 中的 `POST /api/repo` | 像“提交后立刻分析” | 实际只创建 session，真正分析在 SSE stream 被消费时触发 |
| `backend/llm_tools/context_builder.py` | 像工具核心实现 | 实际主要是兼容入口，真正的预算与 seed 逻辑在 `agent_runtime/context_budget.py` |
| `backend/deep_research/pipeline.py` | 像 agent 自主研究 | 实际是确定性的静态研究流水线 |
| `backend/m6_response/tool_executor.py` | 像纯 M6 逻辑 | 实际是 M6 和 `agent_tools` registry 的桥接层 |
| `backend/m6_response/suggestion_generator.py` | 像主流程关键模块 | 当前更像可复用辅助模块，主路径对建议更依赖 LLM 输出加 `TeachingService.ensure_*` 截断 |

## 8. 测试文件地图

`backend/tests/` 不是运行时架构的一部分，但它能反映当前后端认为哪些行为是“必须守住的契约”。

| 文件 | 主要验证内容 |
| --- | --- |
| `backend/tests/test_routes.py` | 路由 envelope、idle 快照、stale session SSE、repo mode、sidecar API 等基础契约 |
| `backend/tests/test_m1_repo_access.py` | 输入分类、本地路径接入、GitHub clone 成功/失败/超时映射 |
| `backend/tests/test_m2_file_tree.py` | 文件树扫描、忽略/敏感规则、主语言识别、大仓库降级 |
| `backend/tests/test_security_safety.py` | 只读策略、路径越界检测、pattern 匹配 |
| `backend/tests/test_m5_session.py` | 初始分析、聊天回合、教学状态推进、tool activity、超时和 sidecar 剥离 |
| `backend/tests/test_m6_response.py` | prompt payload、teaching directive、预算、response parser、LLM config 读取 |
| `backend/tests/test_tool_calling.py` | tool schema、工具执行、tool loop 多轮调用、超时降级、轮数上限后的 no-tool 收尾 |
| `backend/tests/test_llm_tools.py` | tool context 预算、starter excerpt、cache 并发安全、只读与脱敏 |
| `backend/tests/test_deep_research.py` | relevant file selection、deep research 流程、非 Python 仓库降级 |
| `backend/tests/test_sidecar_explainer.py` | sidecar prompt、长度裁剪、空输入、LLM 错误映射 |
| `backend/tests/test_agent_architecture_refactor.py` | 验证架构已从旧的静态骨架演进到当前 m1/m2 + tool-aware 方案 |
| `backend/tests/test_web_contracts.py` | 约束前端消费的后端消息契约 |
| `backend/tests/test_web_v2_contracts.py` | 约束 web_v2 消费的后端消息契约 |

补充说明：

1. `backend/tests/fixtures/source_repo/**` 和 `backend/tests/fixtures/secret_repo/**` 是测试输入样例仓库，不是后端运行代码。
2. 这些测试覆盖面很像一份“后端架构验收清单”，可以反过来帮助理解主流程边界。

## 9. 一句话总结每个大模块到底在做什么

为了方便快速复习，可以把整个 backend 压成下面这几句：

1. `main.py + routes/` 只负责接请求和输出协议。
2. `contracts/` 定义全系统状态、消息和事件的统一形状。
3. `m1_repo_access/` 负责把“用户输入的仓库”安全地变成可读仓库上下文。
4. `m2_file_tree/ + security/` 负责只读扫描、过滤和安全边界。
5. `m5_session/` 是核心调度层，维护单活会话、工作流和事件流。
6. `m6_response/` 负责把教学状态变成 LLM 输入，再把 LLM 输出还原成结构化回答。
7. `agent_tools/ + agent_runtime/ + llm_tools/` 负责让 LLM 在只读、安全、可控的范围内查看源码证据。
8. `deep_research/` 是 Python 仓库首轮报告的确定性静态研究分支。
9. `sidecar/` 是脱离主会话的小型解释器。

## 10. 当前架构最重要的理解点

如果只记住三件事，建议记这三件：

1. 这是一个“单活会话 + SSE 驱动工作流”的系统，很多真正的工作不是在 POST 请求里做，而是在 stream 被消费时做。
2. `SessionService` 和 `m5_session/*Workflow` 才是后端主心骨；路由层很薄，M1/M2/M6/agent runtime 都是在被它们编排。
3. 回答生成并不是单次 LLM 调用，而是“教学状态 + 预置工具上下文 + 可选 tool loop + 结构化解析”的组合过程。
