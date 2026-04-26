# DeepTutor services 装配机制考察报告

> 考察对象：`DeepTutor/deeptutor/services/`
>
> 目标：说明 DeepTutor 内部 services 层如何被组装、如何被入口调用、各服务之间的依赖边界，以及对新内核设计的参考价值。

## 1. 总体结论

`deeptutor.services` 不是一个集中式 DI container，而是一组按用途拆开的服务包。它的装配方式主要有四类：

1. **包级导出与懒加载**：`deeptutor/services/__init__.py` 只直接导出 `PathService`，其他重模块通过 `__getattr__` 懒加载，避免启动期循环依赖。
2. **进程级单例 getter**：`get_path_service()`、`get_llm_client()`、`get_embedding_client()`、`get_sqlite_session_store()`、`get_turn_runtime_manager()`、`get_memory_service()`、`get_skill_service()` 等负责在首次使用时创建进程级实例。
3. **工厂与注册表**：LLM、embedding、RAG、search 通过 provider registry / pipeline factory / adapter map 选择具体实现。
4. **运行时现场装配**：真正把多个服务拼成一次用户请求的是 `services/session/turn_runtime.py` 的 `TurnRuntimeManager._run_turn()`，它在每个 turn 中把附件、历史、memory、skills、notebook、question bank 等前置装配成 `UnifiedContext`，再交给 `ChatOrchestrator`。

核心结构可以概括为：

```text
FastAPI / CLI / SDK
  -> DeepTutorApp or routers
  -> services.session.get_turn_runtime_manager()
  -> TurnRuntimeManager.start_turn()
  -> SQLiteSessionStore + AttachmentStore + ContextBuilder
  -> MemoryService + SkillService + NotebookManager
  -> UnifiedContext
  -> ChatOrchestrator
  -> capabilities / agents
  -> services.llm / services.rag / services.search / tools
  -> turn_events + messages 持久化
```

## 2. services 包自身的装配方式

顶层 `deeptutor/services/__init__.py` 采取“轻入口、懒加载”的方式：

- 直接导出：`PathService`、`get_path_service`。
- 懒加载模块：`llm`、`embedding`、`rag`、`prompt`、`search`、`setup`、`session`、`config`。
- 对 `BaseSessionManager` 也用懒加载，避免导入 `session` 时过早牵出 SQLite、runtime、agent 依赖。

这说明 services 层并不追求启动时一次性初始化全部服务，而是尽量让入口保持轻量。重依赖如 LlamaIndex、provider SDK、turn runtime 都延迟到具体功能需要时再加载。

## 3. 启动期如何把 services 带起来

FastAPI 主入口在 `DeepTutor/deeptutor/api/main.py`。

启动期动作：

1. `validate_tool_consistency()` 检查 capability manifest 声明的 tools 是否都存在于 runtime `ToolRegistry`。
2. `get_llm_client()` 提前初始化 LLM client，主要为了让 OpenAI-compatible 环境变量尽早对下游 SDK 可见。
3. 启动全局 `EventBus`。
4. `get_tutorbot_manager().auto_start_bots()` 自动启动配置了 `auto_start` 的 TutorBot。
5. 模块加载时调用 `init_user_directories()`，通过 `PathService` 创建 `data/user` 下的基础目录和默认 settings。
6. 挂载 `/api/outputs`，但由 `PathService.is_public_output_path()` 过滤公开产物。

CLI / SDK 入口在 `DeepTutor/deeptutor/app/facade.py`：

- `DeepTutorApp.__init__()` 直接拿到 `get_turn_runtime_manager()`、`get_sqlite_session_store()`、`get_notebook_manager()`、`get_capability_registry()`。
- `start_turn()` 先解析 capability alias，再调用同一套 `TurnRuntimeManager.start_turn()`。

因此 Web、CLI、SDK 最终都落到 services/session 的 turn runtime，而不是各自维护独立业务流程。

## 4. PathService 是 services 的底座

`DeepTutor/deeptutor/services/path_service.py` 是 runtime 文件布局的单例服务。它决定：

- 用户数据根：`data/user/`
- SQLite 会话库：`data/user/chat_history.db`
- 设置目录：`data/user/settings/`
- workspace：`data/user/workspace/`
- chat 子空间：`chat`、`deep_solve`、`deep_question`、`deep_research`、`math_animator`、`_detached_code_execution`
- notebook、memory、co-writer、book、logs 等目录
- 哪些产物可以通过 `/api/outputs` 暴露

装配特点：

- `PathService` 使用 `__new__` 单例，`get_path_service()` 返回全局实例。
- `services.config.loader`、`NotebookManager`、`MemoryService`、`SkillService`、`AttachmentStore`、`TutorBotManager` 都依赖它确定存储位置。
- `PathService.is_public_output_path()` 是安全边界：拒绝 `.json`、`.sqlite`、`.db`、`.md`、`.yaml`、`.py`、`.log` 等私有后缀，只允许明确白名单产物公开。

结论：`PathService` 是整个 services 层最底层的“运行时文件系统内核”。

## 5. Config 服务如何装配 LLM / Embedding / Search

配置层位于 `DeepTutor/deeptutor/services/config/`，承担“运行时配置归一化”。

主要组件：

| 文件 | 职责 |
|---|---|
| `loader.py` | 读取 `data/user/settings/*.yaml`，注入 runtime paths，提供 `get_agent_params()`、`get_chat_params()` |
| `env_store.py` | 读写项目 `.env`，并把 env 写回 `os.environ` |
| `model_catalog.py` | 读写 `data/user/settings/model_catalog.json`，管理 llm/embedding/search profile 和 active model |
| `provider_runtime.py` | 把 catalog + `.env` 解析成 `ResolvedLLMConfig`、`ResolvedEmbeddingConfig`、`ResolvedSearchConfig` |
| `knowledge_base_config.py` | 管理 `data/knowledge_bases/kb_config.json`，并把旧 RAG provider 统一归一到 `llamaindex` |
| `test_runner.py` | 用后台线程测试 llm/embedding/search 配置，并可写回 context window 元数据 |

配置解析优先级大致是：

```text
model_catalog.json active profile/model
  + .env compatibility values
  + provider metadata defaults
  -> Resolved*Config
  -> LLMConfig / EmbeddingConfig / Search runtime config
```

需要注意的是 `.env` 仍然是兼容入口。`ModelCatalogService.load()` 会从 `.env` hydrate 缺失的 catalog，也会在 `.env` 键存在时同步 active profile/model。`apply()` 则反过来把 catalog 渲染回 `.env`。

## 6. LLM 服务的装配链

LLM 是 services 层最完整的工厂/注册表结构，主入口在 `DeepTutor/deeptutor/services/llm/__init__.py`。

### 6.1 对外 API

推荐新代码使用：

```text
from deeptutor.services.llm import complete, stream
```

兼容旧代码保留：

```text
get_llm_client() -> LLMClient
LLMClient.complete()
LLMClient.get_model_func()
```

### 6.2 配置解析

`services/llm/config.py`：

1. 模块 import 时执行 `_setup_openai_env_vars_early()`，对 OpenAI-compatible binding 提前设置 `OPENAI_API_KEY` / `OPENAI_BASE_URL`。
2. `get_llm_config()` 优先调用 `resolve_llm_runtime_config()`。
3. resolver 失败时 fallback 到 `.env` 路径。
4. 结果缓存到 `_LLM_CONFIG_CACHE`，可用 `clear_llm_config_cache()` 清理。

### 6.3 Provider metadata 单一来源

`services/provider_registry.py` 是 provider 元数据的权威来源。`ProviderSpec` 包含：

- provider 名称、别名、关键字
- backend 类型：`openai_compat`、`anthropic`、`azure_openai`、`openai_codex`、`github_copilot`
- 默认 base url
- gateway/local/direct/oauth 标记
- api key/base url 自动识别规则
- prompt caching、max_completion_tokens、thinking style、model prefix stripping 等能力标记

`find_by_name()`、`find_by_model()`、`find_gateway()` 被 config resolver 和 LLM factory 共同使用。

### 6.4 Runtime provider 工厂

真实调用链：

```text
services.llm.complete()/stream()
  -> _resolve_call_config()
  -> get_llm_config() 或 caller override
  -> provider_registry.find_by_name/find_by_model/find_gateway()
  -> provider_factory.get_runtime_provider()
  -> provider_core.*Provider
  -> provider.chat_with_retry()/chat_stream_with_retry()
```

`services/llm/provider_factory.py` 根据 `ProviderSpec.backend` 创建：

- `OpenAICompatProvider`
- `AnthropicProvider`
- `AzureOpenAIProvider`
- `GitHubCopilotProvider`
- `OpenAICodexProvider`

所有 provider 都继承 `provider_core/base.py` 的 `LLMProvider`，统一暴露：

- `chat()`
- `chat_stream()`
- `chat_with_retry()`
- `chat_stream_with_retry()`

`LLMProvider` 基类内置短重试、瞬时错误判断、图片失败降级、默认生成参数。

### 6.5 旧 provider registry 的位置

`services/llm/registry.py` 和 `services/llm/providers/*` 仍存在，但主要是旧抽象和测试兼容。当前 `services.llm.factory` 主路径使用的是：

```text
services/provider_registry.py
services/llm/provider_factory.py
services/llm/provider_core/*
```

这点很重要：如果新内核借鉴 DeepTutor 的 LLM 层，应该学习 `provider_core + provider_registry` 这条主路径，而不是旧的 decorator registry。

## 7. Embedding 服务的装配链

Embedding 主入口在 `DeepTutor/deeptutor/services/embedding/`。

装配链：

```text
get_embedding_client()
  -> EmbeddingClient()
  -> get_embedding_config()
  -> resolve_embedding_runtime_config()
  -> EMBEDDING_PROVIDERS metadata
  -> _resolve_adapter_class()
  -> BaseEmbeddingAdapter implementation
```

关键点：

- `provider_runtime.py` 中的 `EMBEDDING_PROVIDERS` 定义 embedding provider metadata。
- `embedding/client.py` 的 `_ADAPTER_MAP` 把 provider spec 的 `adapter` 映射到实现类：
  - `openai_compat` -> `OpenAICompatibleEmbeddingAdapter`
  - `cohere` -> `CohereEmbeddingAdapter`
  - `jina` -> `JinaEmbeddingAdapter`
  - `ollama` -> `OllamaEmbeddingAdapter`
- `EmbeddingClient.embed()` 负责 batch、progress callback、batch delay。
- `get_embedding_client()` 是单例；`reset_embedding_client()` 给 settings/test 流程刷新配置使用。

Embedding 还被 RAG 的 `CustomEmbedding` 包装成 LlamaIndex 的 `BaseEmbedding`，所以 RAG 不直接知道具体 embedding provider。

## 8. RAG 服务的装配链

RAG 主入口在 `DeepTutor/deeptutor/services/rag/`。

当前已经收敛为单一 LlamaIndex pipeline：

```text
RAGService
  -> get_pipeline(kb_base_dir)
  -> LlamaIndexPipeline
  -> LlamaIndex Settings.embed_model = CustomEmbedding
  -> get_embedding_client()
```

关键文件：

- `rag/factory.py`：保留 `get_pipeline()`、`list_pipelines()` 等兼容接口，但无论传什么 provider 都归一为 `llamaindex`。
- `rag/service.py`：统一入口，提供 `initialize()`、`search()`、`delete()`、`smart_retrieve()`。
- `rag/file_routing.py`：集中判断 PDF/text/code/config 等文件类型，避免各调用方重复写扩展名逻辑。
- `rag/pipelines/llamaindex.py`：真实索引和检索实现。

RAG 查询不会强依赖 LLM 生成答案。`LlamaIndexPipeline.search()` 主要走 retriever，返回上下文片段和 sources。`RAGService.smart_retrieve()` 才会在需要生成多 query 或聚合 passages 时调用 `services.llm.complete()`。

RAG 对工具层的输出也做了桥接：`RAGService.search(event_sink=...)` 可以把 raw log 和 summary status 通过 `event_sink` 发回工具事件。

## 9. Search 服务的装配链

Search 主入口在 `DeepTutor/deeptutor/services/search/__init__.py`，对外提供 `web_search()`。

装配链：

```text
web_search(query, provider?)
  -> load_config_with_main("main.yaml")
  -> resolve_search_runtime_config()
  -> _assert_provider_supported()
  -> search.providers.get_provider()
  -> BaseSearchProvider.search()
  -> optional AnswerConsolidator
  -> WebSearchResponse.to_dict()
```

provider 注册机制在 `search/providers/__init__.py`：

- `_register_builtin_providers()` import built-in providers，触发 `@register_provider("...")`。
- 支持 provider：`brave`、`tavily`、`jina`、`searxng`、`duckduckgo`、`perplexity`、`serper`。
- deprecated provider：`exa`、`baidu`、`openrouter`，被显式标记为 unsupported/deprecated。

Search 的 fallback 逻辑在 `provider_runtime.resolve_search_runtime_config()` 和 `web_search()` 中共同完成：

- `brave` / `tavily` / `jina` 缺 key 时 fallback 到 `duckduckgo`。
- `searxng` 缺 base_url 时 fallback 到 `duckduckgo`。
- `perplexity` / `serper` 缺 key 时直接报错。
- raw SERP provider 会用 `AnswerConsolidator` 模板合成 answer；如传 `consolidation_llm_model`，可升级为 LLM synthesis。

## 10. Session / Turn Runtime 是 services 的真实组装中心

`DeepTutor/deeptutor/services/session/` 是 DeepTutor 后端请求的核心 services 层。

### 10.1 SQLiteSessionStore

`SQLiteSessionStore` 使用 `PathService.get_chat_history_db()`，默认存储在：

```text
data/user/chat_history.db
```

主要表：

- `sessions`
- `messages`
- `turns`
- `turn_events`
- `notebook_entries`
- `notebook_categories`
- `notebook_entry_categories`

关键方法：

- `ensure_session()`
- `create_turn()`
- `append_turn_event()`
- `get_turn_events()`
- `add_message()`
- `get_messages_for_context()`
- `update_summary()`
- `get_active_turn()`

所有 DB 操作通过 `_run()` 加 `asyncio.Lock` 并丢到 `asyncio.to_thread()`，避免阻塞 event loop。

### 10.2 ContextBuilder

`ContextBuilder` 从 SQLite 取历史消息，并根据 LLM context window 预算压缩历史：

```text
get_messages_for_context()
  -> count_tokens()
  -> if over budget:
       _ContextSummaryAgent(BaseAgent)
       -> services.llm stream
       -> update_summary()
  -> ContextBuildResult
```

它输出：

- `conversation_history`
- `conversation_summary`
- `context_text`
- `token_count`
- `budget`
- context 压缩过程产生的 `StreamEvent`

### 10.3 TurnRuntimeManager.start_turn()

`start_turn()` 做请求落盘和后台任务调度：

1. 解析 `capability`，默认 `chat`。
2. 从 config 中剥离 runtime-only keys，如 `_persist_user_message`、`_regenerate`、`followup_question_context`。
3. 调用 `validate_capability_config()` 校验公开 config。
4. `ensure_session()`。
5. 写 session preferences：capability、tools、knowledge_bases、language。
6. `create_turn()`，并持久化一个 session event。
7. 创建后台 task 执行 `_run_turn()`。

### 10.4 TurnRuntimeManager._run_turn()

这是最关键的服务组装现场：

```text
payload
  -> AttachmentStore.put()
  -> extract_documents_from_records()
  -> ContextBuilder.build()
  -> MemoryService.build_memory_context()
  -> SkillService.auto_select()/load_for_context()
  -> NotebookManager.get_records_by_references()
  -> NotebookAnalysisAgent.analyze()
  -> question bank context
  -> effective_user_message
  -> SQLite add user message
  -> UnifiedContext(...)
  -> ChatOrchestrator.handle(context)
  -> persist/publish StreamEvent
  -> SQLite add assistant message
  -> MemoryService.refresh_from_turn()
```

也就是说，大部分 capability 不需要自己知道附件、notebook、history、memory、skills 是怎么来的。它们只接收被 services/session 组装好的 `UnifiedContext`。

### 10.5 事件持久化和订阅

`_persist_and_publish()`：

- 给 `StreamEvent` 注入 `session_id`、`turn_id`。
- 写入 `turn_events`，生成递增 `seq`。
- mirror 到 workspace 的 `events.jsonl`。
- 推送给 live subscribers。

`subscribe_turn(turn_id, after_seq)`：

- 先从 DB 补发 backlog。
- 再挂到 live queue。
- 断线恢复只需要 `turn_id + after_seq`。

这是 DeepTutor 服务层最值得借鉴的部分：流式 UI 不是纯内存流，而是“可恢复的持久化事件流”。

## 11. Memory / Skill / Notebook / Storage 的装配

### 11.1 MemoryService

`services/memory/service.py` 维护两个公开 memory 文件：

```text
data/memory/SUMMARY.md
data/memory/PROFILE.md
```

注意：`PathService.get_memory_dir()` 当前把 memory 放到 `project_root/data/memory`，并兼容从旧的 `data/user/workspace/memory` 迁移。

`TurnRuntimeManager._run_turn()` 在进入 orchestrator 前调用：

- `build_memory_context()` 注入 `UnifiedContext.memory_context`

turn 完成后调用：

- `refresh_from_turn()` 用 `services.llm.stream()` 改写 profile 和 summary。

### 11.2 SkillService

`services/skill/service.py` 加载用户 skill：

```text
data/user/workspace/skills/<name>/SKILL.md
```

能力：

- CRUD
- frontmatter 解析
- keyword scoring 自动选择
- `load_for_context()` 把选中的 skill body 拼成 `## Active Skills` prompt block

`TurnRuntimeManager` 支持：

- 显式 `payload.skills`
- 或 `["auto"]` / 空值时按用户消息自动选择

### 11.3 NotebookManager

`services/notebook/service.py` 是同步文件服务，存储在：

```text
data/user/workspace/notebook/
  notebooks_index.json
  <notebook_id>.json
```

它不走 SQLite，而是保留 JSON 文件格式供 Web、CLI、runtime 共用。`TurnRuntimeManager` 通过 `get_records_by_references()` 解析用户引用的 notebook records，再交给 `NotebookAnalysisAgent` 生成上下文。

### 11.4 AttachmentStore

`services/storage/attachment_store.py` 提供 `AttachmentStore` Protocol 和默认 `LocalDiskAttachmentStore`。

默认位置：

```text
data/user/workspace/chat/attachments/<session>/<attachment_id>_<filename>
```

装配特点：

- `get_attachment_store()` 单例。
- 文件名 sanitize。
- 写入采用 tmp + replace。
- public URL 形如 `/api/attachments/<sid>/<aid>/<filename>`。
- `TurnRuntimeManager` 先保存原始文件，再让 document extractor 清理 base64，避免 SQLite message row 膨胀。

## 12. Prompt 服务的装配

`services/prompt/manager.py` 的 `PromptManager` 负责多语言 prompt 加载：

```text
get_prompt_manager()
  -> PromptManager singleton
  -> load_prompts(module, agent, language)
  -> candidate prompt dirs
  -> language fallback
  -> YAML cache
```

候选路径支持 current 和 legacy：

- 当前 agent prompt：`deeptutor/agents/<module>/prompts/<lang>/<agent>.yaml`
- 非 agents 模块：`deeptutor/book/prompts/...`、`deeptutor/co_writer/prompts/...`
- legacy：`src/agents/...`、`src/<module>/prompts/...`

语言 fallback：

- `zh -> zh, cn, en`
- `en -> en, zh, cn`

上层 agents 通过 `get_prompt_manager()` 取 prompt，不直接处理路径和语言 fallback。

## 13. TutorBotManager 是并行子系统的 service facade

`services/tutorbot/manager.py` 管理一个相对独立的 TutorBot runtime。

数据位置：

```text
data/tutorbot/<bot_id>/
  config.yaml
  workspace/
  cron/
  logs/
  media/
```

装配链：

```text
get_tutorbot_manager()
  -> TutorBotManager singleton
  -> start_bot()
  -> ensure bot dirs + seed skills/templates
  -> create_deeptutor_provider()
  -> MessageBus
  -> SessionManager(workspace)
  -> AgentLoop(...)
  -> ChannelManager(...)
  -> HeartbeatService(...)
  -> asyncio tasks
```

FastAPI lifespan 调用：

- startup：`auto_start_bots()`
- shutdown：`stop_all()`

TutorBot 和主 chat runtime 并不是同一条执行链。它有自己的 agent loop、channel manager、tools、heartbeat，但 provider 通过 `tutorbot/providers/deeptutor_adapter.py` 复用 services-layer LLM provider runtime。

## 14. services 层的调用关系图

```text
PathService
  <- config.loader
  <- config.model_catalog
  <- SQLiteSessionStore
  <- NotebookManager
  <- MemoryService
  <- SkillService
  <- AttachmentStore
  <- TutorBotManager

Config services
  -> EnvStore
  -> ModelCatalogService
  -> provider_runtime
  -> LLMConfig / EmbeddingConfig / ResolvedSearchConfig

LLM services
  -> provider_registry.ProviderSpec
  -> provider_factory
  -> provider_core providers

Embedding services
  -> provider_runtime.EMBEDDING_PROVIDERS
  -> EmbeddingClient
  -> adapter classes

RAG services
  -> get_pipeline()
  -> LlamaIndexPipeline
  -> CustomEmbedding
  -> EmbeddingClient

Search services
  -> provider_runtime.resolve_search_runtime_config()
  -> search provider registry
  -> BaseSearchProvider
  -> AnswerConsolidator

Session services
  -> SQLiteSessionStore
  -> AttachmentStore
  -> ContextBuilder
  -> MemoryService
  -> SkillService
  -> NotebookManager
  -> ChatOrchestrator
```

## 15. 典型请求中的 services 组装

### 15.1 普通 Web/CLI turn

```text
WebSocket / CLI
  -> TurnRuntimeManager.start_turn()
  -> SQLiteSessionStore.ensure_session()
  -> SQLiteSessionStore.create_turn()
  -> background _run_turn()
  -> AttachmentStore
  -> ContextBuilder
  -> MemoryService
  -> SkillService
  -> NotebookManager
  -> UnifiedContext
  -> ChatOrchestrator
  -> capability/agent
  -> services.llm.complete/stream, services.rag/search if tool needs
  -> StreamEvent persisted to turn_events
  -> assistant message persisted
```

### 15.2 RAG tool 请求

```text
Agent/tool runtime
  -> RAGService.search()
  -> get_pipeline()
  -> LlamaIndexPipeline.search()
  -> get_embedding_client()
  -> Embedding adapter API
  -> context + sources
  -> ToolResult / StreamEvent
```

### 15.3 Settings 测试 LLM

```text
settings router
  -> get_config_test_runner().start("llm", catalog)
  -> background thread
  -> temporary_env(rendered catalog)
  -> resolve_llm_runtime_config()
  -> LLMConfig
  -> services.llm.complete()
  -> detect_context_window()
  -> save model_catalog.json
  -> clear_llm_config_cache() + reset_llm_client()
```

## 16. 设计优点

1. **入口统一**：Web、CLI、SDK 都落到 `TurnRuntimeManager`。
2. **重依赖懒加载**：顶层 services 包不会因为 import 就加载 LlamaIndex、provider SDK 或完整 runtime。
3. **配置归一化清晰**：catalog 和 `.env` 兼容，但最终都变成 `Resolved*Config`。
4. **LLM provider 边界清楚**：metadata、config resolve、provider construction、provider implementation 分层明确。
5. **可恢复事件流**：`turn_events` 持久化让 WebSocket resume 成为一等能力。
6. **上下文前置装配**：capability 只消费 `UnifiedContext`，不重复实现 attachments/memory/notebook/skills/history。
7. **路径安全集中化**：`PathService` 统一限定 runtime 数据位置和 public output 白名单。

## 17. 风险和维护成本

1. **`TurnRuntimeManager._run_turn()` 过重**
   - 它同时装配附件、文档抽取、历史压缩、memory、skills、notebook、history、question bank、orchestrator 和事件持久化。
   - 后续扩展容易继续堆逻辑，建议拆出 ContextAssembler / AttachmentAssembler / ReferenceAssembler。

2. **全局单例刷新需要人工记忆**
   - LLM、Embedding、Path、SQLite、Memory、Skill、Notebook、TutorBot 都有单例。
   - settings 修改后必须记得调用对应 reset/cache clear，否则可能读到旧配置。

3. **同步文件服务和 SQLite 并存**
   - notebook、skills、memory、tutorbot config 是文件服务；session/turn/question notebook 是 SQLite。
   - 好处是简单直观，代价是一致性、并发写和事务边界较分散。

4. **LLM provider 有新旧两套抽象**
   - 当前主路径是 `provider_core`，但 `llm/providers` 和 `llm/registry.py` 仍存在。
   - 新开发需要明确避免误用旧路径。

5. **Search provider fallback 分散**
   - 一部分在 `provider_runtime.resolve_search_runtime_config()`，一部分在 `web_search()`。
   - 行为能跑通，但维护时需要同时读两处。

6. **RAG provider 已收敛但接口还保留多 provider 形态**
   - `provider` 参数和 `normalize_provider_name()` 主要是兼容旧配置。
   - 新设计可以直接表达“当前只支持 llamaindex”，避免表面多态。

## 18. 对 new kernel 的直接启示

1. **保留 PathService 类似的路径底座**
   - 所有 runtime 文件、公开产物、安全边界都应走统一服务。

2. **把 turn runtime 作为请求真实入口**
   - 用户请求先落成 session/turn，再异步执行；这比直接 SSE/WS 推流更利于 resume、cancel、regenerate、审计。

3. **把上下文组装从 capability 中抽出来**
   - 附件、history、memory、skills、notebook references 应统一装配成一个 context contract。

4. **LLM provider 建议采用 metadata + factory + provider_core**
   - 不要让 agent 直接依赖 OpenAI/Anthropic SDK，也不要让 provider 选择逻辑散落在各 agent 内。

5. **事件必须持久化**
   - 只保存最终 assistant message 不够。`turn_events(seq)` 是恢复 UI、调试 tool 调用和排查失败的关键。

6. **服务单例要有明确 reset 协议**
   - settings 修改、测试配置、切换 provider 时应有统一的 `reload_runtime_services()` 或 service registry，而不是每处手工 reset。

7. **把重型 `_run_turn()` 拆成装配管线**
   - DeepTutor 当前逻辑可作为参考，但新内核可以更清晰地拆成：

```text
TurnRuntime
  -> AttachmentAssembler
  -> HistoryContextBuilder
  -> ReferenceContextBuilder
  -> MemoryAssembler
  -> SkillAssembler
  -> UnifiedContext
  -> Orchestrator
  -> EventSink
```

## 19. 关键源码索引

| 路径 | 重点 |
|---|---|
| `DeepTutor/deeptutor/services/__init__.py` | services 顶层懒加载入口 |
| `DeepTutor/deeptutor/services/path_service.py` | runtime 路径、public output 安全白名单 |
| `DeepTutor/deeptutor/services/setup/init.py` | 初始化 `data/user` 和默认 settings |
| `DeepTutor/deeptutor/services/config/loader.py` | YAML settings 加载和 runtime paths 注入 |
| `DeepTutor/deeptutor/services/config/env_store.py` | `.env` 读写和兼容层 |
| `DeepTutor/deeptutor/services/config/model_catalog.py` | LLM/embedding/search catalog |
| `DeepTutor/deeptutor/services/config/provider_runtime.py` | Resolved LLM/Embedding/Search config |
| `DeepTutor/deeptutor/services/provider_registry.py` | LLM provider metadata 单一来源 |
| `DeepTutor/deeptutor/services/llm/config.py` | `LLMConfig` 和配置缓存 |
| `DeepTutor/deeptutor/services/llm/factory.py` | `complete()` / `stream()` 主入口 |
| `DeepTutor/deeptutor/services/llm/provider_factory.py` | runtime provider 创建 |
| `DeepTutor/deeptutor/services/llm/provider_core/base.py` | provider 统一接口和 retry |
| `DeepTutor/deeptutor/services/embedding/client.py` | embedding adapter 装配 |
| `DeepTutor/deeptutor/services/rag/factory.py` | RAG pipeline 工厂 |
| `DeepTutor/deeptutor/services/rag/service.py` | RAG 统一服务入口 |
| `DeepTutor/deeptutor/services/rag/pipelines/llamaindex.py` | LlamaIndex pipeline |
| `DeepTutor/deeptutor/services/search/__init__.py` | `web_search()` 装配入口 |
| `DeepTutor/deeptutor/services/search/providers/__init__.py` | search provider registry |
| `DeepTutor/deeptutor/services/session/sqlite_store.py` | SQLite sessions/messages/turns/events |
| `DeepTutor/deeptutor/services/session/context_builder.py` | history budget 和摘要压缩 |
| `DeepTutor/deeptutor/services/session/turn_runtime.py` | 每个 turn 的真实服务组装中心 |
| `DeepTutor/deeptutor/services/memory/service.py` | SUMMARY/PROFILE memory |
| `DeepTutor/deeptutor/services/notebook/service.py` | notebook JSON 文件服务 |
| `DeepTutor/deeptutor/services/skill/service.py` | SKILL.md 读取、选择、注入 |
| `DeepTutor/deeptutor/services/storage/attachment_store.py` | 附件持久化和 URL |
| `DeepTutor/deeptutor/services/tutorbot/manager.py` | TutorBot 生命周期管理 |
| `DeepTutor/deeptutor/api/main.py` | API lifespan 对 services 的启动装配 |
| `DeepTutor/deeptutor/app/facade.py` | CLI/SDK 进入 services runtime 的 facade |

