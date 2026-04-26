# DeepTutor `core` Capability 侦察报告

> 侦察对象：`DeepTutor/deeptutor/core/` 中的 capability 协议，以及其在 `runtime`、`capabilities`、测试中的落地方式。  
> 输出位置：`new_docs/new_kernel/`。  
> 代码基准：本地工作区 `C:\Users\chual\vibe\Irene\DeepTutor`。

## 1. 总结判断

`deeptutor/core` 里的 capability 不是具体业务能力，而是一个极薄的“能力内核协议层”。它只规定三件事：

1. capability 的静态 manifest 怎么描述。
2. 每次运行接收什么统一上下文。
3. 每次运行如何通过统一事件流向外汇报。

实际能力不在 `core` 内完成，而是在 `deeptutor/capabilities/*.py` 中包装已有 agent pipeline，再由 `deeptutor/runtime` 负责注册、选择和调度。

可以把当前结构理解成：

```text
UnifiedContext
    -> ChatOrchestrator.handle()
    -> CapabilityRegistry.get(active_capability || "chat")
    -> BaseCapability.run(context, StreamBus)
    -> StreamEvent stream
```

这说明当前 capability 内核的重点不是“推理算法”，而是“协议稳定性”：所有能力都必须讲同一种输入语言 `UnifiedContext`，并用同一种输出语言 `StreamBus`。

## 2. Core 内的 capability 协议

核心文件是 `DeepTutor/deeptutor/core/capability_protocol.py`。

### 2.1 `CapabilityManifest`

`CapabilityManifest` 是 capability 的静态描述：

| 字段 | 含义 | 当前用途 |
|---|---|---|
| `name` | capability 注册名 | orchestrator 路由、API/前端选择 |
| `description` | 能力说明 | plugin/capability 列表展示 |
| `stages` | 阶段名列表 | 前端进度、trace 卡片、事件 stage |
| `tools_used` | 该能力可能使用的工具 | UI 工具开关、工具一致性校验 |
| `cli_aliases` | CLI 短别名 | CLI/SDK facade 解析 |
| `request_schema` | 配置 JSON schema | playground、插件 API、请求校验 |
| `config_defaults` | 默认配置 | 目前主要见于 `math_animator` |

这个 manifest 是当前 capability 生态最重要的“目录卡”。但它只是声明，不能保证运行时一定遵守。例如 `tools_used` 是可用工具集合，不等于本次必用工具。

### 2.2 `BaseCapability`

`BaseCapability` 只要求子类提供：

```python
manifest: CapabilityManifest
async def run(self, context: UnifiedContext, stream: StreamBus) -> None
```

它还提供两个便利属性：

- `name` 返回 `manifest.name`
- `stages` 返回 `manifest.stages`

也就是说，能力实现的全部合同都集中在 `run()`。`run()` 不返回业务对象，而是把内容、进度、工具调用、结构化结果全部写入 `StreamBus`。

## 3. 输入协议：`UnifiedContext`

`DeepTutor/deeptutor/core/context.py` 定义 capability 的统一输入。

关键字段如下：

| 字段 | 作用 |
|---|---|
| `session_id` | 会话 ID，缺失时由 orchestrator 生成 |
| `user_message` | 当前用户输入，也是大多数 capability 的主任务文本 |
| `conversation_history` | OpenAI 格式历史消息 |
| `enabled_tools` | 用户本轮启用的 Level 1 工具；`None` 表示未指定，`[]` 表示显式禁用 |
| `active_capability` | 当前选择的能力；空值默认走 `chat` |
| `knowledge_bases` | RAG 目标知识库 |
| `attachments` | 图片、PDF、文件附件 |
| `config_overrides` | capability 级请求配置 |
| `language` | 响应语言 |
| `notebook_context` / `history_context` / `memory_context` / `skills_context` | turn runtime 前置组装的上下文 |
| `metadata` | 运行时扩展信息，如 `turn_id`、follow-up 上下文、压缩后的会话文本 |

这里最值得保留的是 `enabled_tools` 的三态语义：

```text
None -> 未指定，由 capability 使用默认工具集合
[]   -> 用户显式禁用所有可选工具
[...] -> 用户显式选择工具子集
```

当前不是所有能力都同等严格地保留这个语义。`deep_solve`、`deep_question`、`deep_research` 都有自己的归一化逻辑；`chat` 则把更多决策交给 `AgenticChatPipeline`。

## 4. 输出协议：`StreamBus` 和 `StreamEvent`

`DeepTutor/deeptutor/core/stream.py` 定义事件模型，`stream_bus.py` 提供异步 fan-out。

事件类型包括：

| 类型 | 语义 |
|---|---|
| `stage_start` / `stage_end` | 阶段边界 |
| `thinking` | 中间推理、LLM 输出、阶段说明 |
| `observation` | ReAct 观察结果 |
| `content` | 用户可见正文 |
| `tool_call` / `tool_result` | 工具调用和工具结果 |
| `progress` | 进度、状态、警告 |
| `sources` | RAG/web/paper 引用来源 |
| `result` | 最终结构化结果 |
| `error` | 运行错误 |
| `session` | orchestrator 注入的会话元信息 |
| `done` | capability 结束标记 |

`StreamBus` 的关键设计：

1. 每个 turn 一个 bus。
2. bus 保留 `_history`，新 subscriber 会先收到历史事件。
3. producer 用 helper 方法写事件，如 `content()`、`tool_call()`、`result()`。
4. `stage()` 是 async context manager，会自动包 `stage_start` / `stage_end`。
5. `tool_call()`、`tool_result()`、`progress()` 会合并 trace metadata，方便前端按 call_id、trace_role、trace_group 聚合。

这让 capability 可以不关心 WebSocket、CLI、持久化怎么消费事件，只需要按协议发事件。

## 5. Runtime 装配

### 5.1 注册器

`DeepTutor/deeptutor/runtime/registry/capability_registry.py` 负责能力注册。

内置能力路径来自 `runtime/bootstrap/builtin_capabilities.py`：

| 注册名 | 实现类 |
|---|---|
| `chat` | `deeptutor.capabilities.chat:ChatCapability` |
| `deep_solve` | `deeptutor.capabilities.deep_solve:DeepSolveCapability` |
| `deep_question` | `deeptutor.capabilities.deep_question:DeepQuestionCapability` |
| `deep_research` | `deeptutor.capabilities.deep_research:DeepResearchCapability` |
| `math_animator` | `deeptutor.capabilities.math_animator:MathAnimatorCapability` |
| `visualize` | `deeptutor.capabilities.visualize:VisualizeCapability` |

注册器还支持 plugin capability：

- 尝试导入 `deeptutor.plugins.loader`
- 调用 `discover_plugins()`
- 跳过 `entry.endswith("tool.py")` 的 tool 插件
- 用 `load_plugin_capability(manifest)` 加载能力

这里的 plugin 机制是“可选软依赖”：loader 不存在或加载失败不会阻塞内置能力。

### 5.2 Orchestrator

`DeepTutor/deeptutor/runtime/orchestrator.py` 的 `ChatOrchestrator.handle()` 是 capability 分发入口。

主要流程：

1. 若 `context.session_id` 为空，生成 UUID。
2. 读取 `context.active_capability`，为空则使用 `chat`。
3. 从 `CapabilityRegistry` 取 capability。
4. 先发一个 `SESSION` 事件。
5. 创建 `StreamBus`，后台 task 执行 `capability.run(context, bus)`。
6. 将 bus 里的事件逐个 yield 给调用方。
7. capability 正常或异常结束后都发 `DONE` 并关闭 bus。
8. 最后向全局 `EventBus` 发布 `CAPABILITY_COMPLETE`。

错误策略比较明确：

- 未知 capability：直接输出 `ERROR`，内容含可用能力列表。
- capability 抛异常：捕获后输出 `ERROR`，再输出 `DONE`。
- `answer_now_context` 场景下，如果原 capability 已不存在，会尝试降级到 `chat`。

## 6. 内置 capability 矩阵

| Capability | stages | tools_used | 背后 pipeline | 核心行为 |
|---|---|---|---|---|
| `chat` | `thinking`, `acting`, `observing`, `responding` | `CHAT_OPTIONAL_TOOLS` | `AgenticChatPipeline` | agentic chat，按启用工具自主调用 |
| `deep_solve` | `planning`, `reasoning`, `writing` | `rag`, `web_search`, `code_execution`, `reason` | `MainSolver` | Plan -> ReAct -> Write，多步解题 |
| `deep_question` | `ideation`, `generation` | `rag`, `web_search`, `code_execution` | `AgentCoordinator` / `FollowupAgent` | 题目生成、仿题、题目追问 |
| `deep_research` | `rephrasing`, `decomposing`, `researching`, `reporting` | `rag`, `web_search`, `paper_search`, `code_execution` | `ResearchPipeline` | 研究选题澄清、拆解、证据搜集、报告 |
| `math_animator` | `concept_analysis`, `concept_design`, `code_generation`, `code_retry`, `summary`, `render_output` | 空 | `MathAnimatorPipeline` | Manim 动画/分镜生成和渲染 |
| `visualize` | `analyzing`, `generating`, `reviewing` | 空 | `VisualizePipeline` | 生成 SVG、Chart.js、Mermaid 或 HTML 可视化 |

### 6.1 Chat

`ChatCapability` 是最薄的一层：

- manifest 声明 `CHAT_OPTIONAL_TOOLS`
- `run()` 只创建 `AgenticChatPipeline(language=context.language)`
- 然后把完整 `UnifiedContext` 和 `StreamBus` 交给 pipeline

这意味着 chat 的工具选择、工具循环、RAG 行为主要在 `agents/chat` 内部，而不是 capability wrapper。

### 6.2 Deep Solve

`DeepSolveCapability` 负责把 `UnifiedContext` 适配到 `MainSolver`：

- 读取 LLM config。
- 解析 `detailed_answer`。
- 根据 `enabled_tools` 计算有效工具。
- 如果启用了 `rag` 但没有 KB，会移除 `rag` 并发 `rag_without_kb` warning。
- 只把 image attachment 传给 solver。
- 将 solver 的 progress、trace、tool、observation 事件桥接到 `StreamBus`。
- writer token 可通过 `_content_callback` 流式输出。
- 最终发 `result`，包含 `response`、`output_dir`、`metadata`。

这个能力的 wrapper 较厚，因为它要把老的 solver 回调协议转成统一 stream 事件。

### 6.3 Deep Question

`DeepQuestionCapability` 包三种主要路径：

1. Follow-up：如果 `metadata.question_followup_context` 存在且有 question，则走 `FollowupAgent`，不构造 `AgentCoordinator`。
2. Mimic：根据上传 PDF、`paper_path` 或已抽取文档文本生成仿题。
3. Custom：根据 topic、题量、难度、题型、偏好生成题目。

它还负责：

- 将 `enabled_tools` 转成 `tool_flags_override`。
- 把 coordinator 的 `ws_callback` 转成 `progress`。
- 把 trace callback 转成 `thinking` / `tool_call` / `tool_result` / `error`。
- 将结构化题目结果渲染成 Markdown 内容，同时把原始 summary 放到 `result.metadata`。

### 6.4 Deep Research

`DeepResearchCapability` 是配置转换最重的 capability：

- 使用 `validate_research_request_config()` 校验请求配置。
- 调 `build_research_runtime_config()` 把请求意图、全局 YAML config、启用工具、KB 名称合成 pipeline config。
- 如果 sources 里有 `kb` 但没有知识库，移除 `kb` 并发 `kb_without_kb_name` warning。
- 如果移除后没有任何 source，直接输出 error。
- 未确认 outline 时，只跑 planning/decompose，输出 outline preview 后结束。
- 有 `confirmed_outline` 时运行完整 `ResearchPipeline`。

它的 trace 桥接比较细，会给事件补 `call_id`、`phase`、`label`、`research_stage_card` 等 metadata，方便前端把研究流程展示成阶段卡片。

### 6.5 Math Animator

`MathAnimatorCapability` 有一个重要前置检查：

- 如果找不到 `manim`，直接抛出 RuntimeError，提示安装 optional dependency。

正常路径：

1. 校验 `MathAnimatorRequestConfig`。
2. 运行 concept analysis。
3. 运行 concept design。
4. 生成 Manim code。
5. 渲染并自动 retry。
6. 总结。
7. 输出 artifacts、code、render metadata、analysis、design、timings。

它没有使用 `tools_used`，因为渲染链路是 pipeline 内部能力，不走 Level 1 ToolRegistry。

### 6.6 Visualize

`VisualizeCapability` 负责：

1. 分析可视化需求，决定 `svg`、`chartjs`、`mermaid` 或 `html`。
2. 生成代码。
3. review/优化代码。
4. 对 HTML 特判：跳过 LLM review，先本地校验；无效时用 fallback HTML。
5. 以 fenced code block 发 `content`，并用结构化 `result` 给前端 viewer。

这个能力也不使用 Level 1 tools。

## 7. Answer Now 快路径

`deeptutor/capabilities/_answer_now.py` 是跨 capability 的“中途抢答”辅助层。

约定：

- payload 在 `context.config_overrides["answer_now_context"]`
- 至少要有 `original_user_message`
- 可包含 `partial_response`
- 可包含已捕获 stream events

共享函数负责：

- 提取 payload。
- 将历史 stream events 压缩成 prompt-friendly trace summary。
- 加载各 capability 的 `answer_now.yaml` prompt。
- 调 LLM stream 做一次综合回答。
- 生成跳过阶段的用户可见 notice。

但最终产物由每个 capability 自己决定：

| Capability | Answer Now 行为 |
|---|---|
| `deep_solve` | 跳过 planning/reasoning，直接 writing 综合答案 |
| `deep_question` | 跳过 ideation，用结构化 JSON 生成题目 |
| `deep_research` | 跳过 rephrase/decompose/research，直接综合报告 |
| `math_animator` | 跳过 analysis/design/summary，但仍保留 code generation + render |
| `visualize` | 跳过 analysis/review，单次结构化 LLM 输出代码 |
| `chat` | 由 chat pipeline 自己处理 |

这套设计比 orchestrator 统一降级到 chat 更合理，因为结构化能力需要保持自己的 result envelope。

## 8. 请求配置与 schema

`DeepTutor/deeptutor/capabilities/request_contracts.py` 是 capability config 的公共合同层。

它为内置能力定义：

- Pydantic request config
- JSON schema
- config validator
- runtime-only key 清理

runtime-only key 包括：

```text
_persist_user_message
followup_question_context
answer_now_context
```

`validate_capability_config()` 的行为：

- 内置能力：用对应 Pydantic model 校验，禁止多余字段。
- 未知/plugin 能力：只清理 runtime-only key，然后原样返回。

这意味着内置 capability 的 public config 是严格合同，plugin capability 的 config 则比较宽松。

## 9. 测试覆盖

相关测试说明了当前内核合同：

| 测试文件 | 覆盖点 |
|---|---|
| `tests/runtime/test_orchestrator.py` | capability 路由、默认 chat、unknown error、异常转 error、session_id、answer_now fallback |
| `tests/core/test_capabilities_runtime.py` | chat/deep_solve/deep_question/deep_research/visualize wrapper 与 stream 事件桥接 |
| `tests/core/test_math_animator_capability.py` | math animator pipeline 与结果 envelope |
| `tests/capabilities/test_rag_consistency.py` | deep_solve/deep_research 在无 KB 时的 RAG/source 归一化 |
| `tests/capabilities/test_answer_now.py` | 各 capability 的 answer_now 快路径 |

测试倾向于 mock 背后 agent pipeline，重点锁定 wrapper 合同，而不是测试 LLM 质量。

## 10. 当前边界与隐患

1. `core` 协议极薄，优点是简单，缺点是约束力有限。`run()` 里可以做任何事，因此 stage、result envelope、工具策略主要靠约定和测试约束。
2. `tools_used` 是静态声明，运行时还会被 `enabled_tools`、KB 是否存在、request sources 等二次改写。新内核需要区分“可用工具”“默认工具”“本轮有效工具”“实际调用工具”。
3. `enabled_tools=None` 和 `enabled_tools=[]` 的语义很关键，但各 capability 的处理位置不统一。建议在新内核里沉到公共 policy/normalizer。
4. RAG/KB 一致性现在散在 `deep_solve`、`deep_research`。`chat` 是否有同等保护取决于 chat pipeline 内部。
5. trace metadata 没有强 schema。不同 capability 会写 `trace_kind`、`trace_role`、`trace_group`、`research_stage_card`、`call_state` 等字段，但缺少统一类型定义。
6. 部分源码注释/字符串出现编码乱码痕迹，例如一些中文提示被 mojibake。新内核重写文档和 prompt 时需要统一 UTF-8。
7. Plugin capability 可以绕过内置 config schema，仅做 runtime-only key 清理。灵活但也意味着插件配置错误更晚暴露。
8. `math_animator` 的 optional dependency 检查在运行时触发，manifest 无法表达“需要 manim”。新内核 manifest 可以加入 dependency/capability requirements。

## 11. 对 new kernel 的落地建议

### 11.1 保留三件核心资产

新内核应保留：

1. `UnifiedContext` 作为唯一 turn 输入。
2. `CapabilityManifest` 作为能力目录和 UI/schema 来源。
3. `StreamBus` / `StreamEvent` 作为唯一输出通道。

这些是当前系统已经跑通的稳定边界。

### 11.2 加强 manifest

建议把 manifest 从“展示信息”升级成“可执行合同”：

```text
name
description
stages
request_schema
result_schema
tool_policy:
  available_tools
  default_tools
  requires_kb_for
dependencies:
  python_extras
  external_binaries
runtime_modes:
  supports_answer_now
  supports_attachments
  supports_kb
```

这样前端、API、测试和 runtime 可以共享同一份能力事实源。

### 11.3 抽公共 normalizer

建议把这些逻辑从各 capability wrapper 中抽出：

- `enabled_tools` 三态归一化
- RAG without KB 降级
- source without provider 降级
- attachment 过滤策略
- runtime-only config 清理
- warning event 标准格式

目标是让 capability wrapper 更接近：

```text
normalize request
build pipeline adapter
bridge pipeline events
emit result envelope
```

### 11.4 为 trace metadata 建 schema

当前前端已经依赖很多 metadata 字段。建议给 trace metadata 建轻量 schema：

```text
call_id
trace_id
phase
label
trace_kind
trace_role
trace_group
call_state
call_kind
```

研究、解题、题目生成可以扩展 domain-specific 字段，但基础字段应统一。

### 11.5 明确 result envelope

当前各 capability 的 `result.metadata` 形状不完全一样：

- 文本类：`response`
- 题目类：`response` + `summary`
- 可视化类：`response` + `render_type` + `code` + `analysis` + `review`
- 动画类：`response` + `summary` + `code` + `artifacts` + `render`

建议新内核定义：

```text
result:
  response: string
  kind: text | quiz | report | visualization | animation
  payload: object
  artifacts: []
  diagnostics: object
```

前端 viewer 再按 `kind` 和 `payload` 渲染。

## 12. 结论

`deeptutor/core` 的 capability 内核现在是一个小而有效的协议层。它没有把业务能力写死在 core 里，而是通过 `BaseCapability.run(context, stream)` 把 chat、deep_solve、deep_question、deep_research、math_animator、visualize 统一到同一个输入/输出模型。

新内核不需要推翻这套模型。更务实的方向是：保留 `UnifiedContext + Manifest + StreamBus`，把工具策略、配置校验、trace schema、result envelope 从各 capability wrapper 里上提成公共合同。这样既能维持当前 agent pipeline 的可复用性，也能让前端、API、插件和测试获得更稳定的能力边界。
