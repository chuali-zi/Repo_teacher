# DeepTutor Agents 实现逻辑侦察报告

> 侦察对象：`DeepTutor/deeptutor/agents/`。  
> 配套入口：`DeepTutor/deeptutor/capabilities/*.py`、`DeepTutor/deeptutor/core/`、`DeepTutor/deeptutor/runtime/`。  
> 目的：把 DeepTutor 的具体 agent 实现方式沉淀为 `new_kernel` 可复用的设计材料。

## 1. 总结判断

DeepTutor 的 `deeptutor/agents` 不是一个单一通用 agent loop，而是一组领域 pipeline：

```text
TurnRuntimeManager
  -> UnifiedContext
  -> ChatOrchestrator
  -> Capability.run(context, StreamBus)
  -> domain pipeline / coordinator
  -> leaf agents + ToolRegistry + artifact services
  -> StreamBus events + result payload
```

关键分层是：

| 层 | 代码位置 | 职责 |
|---|---|---|
| turn/session runtime | `deeptutor/services/session/turn_runtime.py` | 持久化 turn、装配上下文、订阅和重放事件 |
| capability wrapper | `deeptutor/capabilities/*.py` | 对外能力合同、阶段声明、配置校验、StreamBus 桥接 |
| concrete agents | `deeptutor/agents/**` | 每个能力自己的推理、工具、状态和产物逻辑 |
| shared agent base | `deeptutor/agents/base_agent.py` | LLM 配置、prompt 加载、调用封装、token 统计、trace callback |
| tool kernel | `deeptutor/runtime/registry/tool_registry.py` | 工具发现、schema、prompt hint、执行 |
| stream/trace | `deeptutor/core/stream_bus.py`, `deeptutor/core/trace.py` | UI 可渲染的统一事件与 trace metadata |

因此，DeepTutor 的真实设计不是“一个 AgentOS”，而是“统一 turn + capability 分发 + 多个领域专用 pipeline”。

## 2. 共同实现套路

### 2.1 Capability 是外部合同，Agent 是内部实现

内置能力由 `deeptutor/runtime/bootstrap/builtin_capabilities.py` 注册：

| capability | wrapper | agents/pipeline |
|---|---|---|
| `chat` | `capabilities/chat.py` | `agents/chat/agentic_pipeline.py` |
| `deep_solve` | `capabilities/deep_solve.py` | `agents/solve/main_solver.py` |
| `deep_research` | `capabilities/deep_research.py` | `agents/research/research_pipeline.py` |
| `deep_question` | `capabilities/deep_question.py` | `agents/question/coordinator.py` |
| `visualize` | `capabilities/visualize.py` | `agents/visualize/pipeline.py` |
| `math_animator` | `capabilities/math_animator.py` | `agents/math_animator/pipeline.py` |

`CapabilityManifest` 提供对外可见的 `name / stages / tools_used / request_schema / config_defaults`。  
`agents/**` 内部可以复杂、异步、多阶段、有状态，但外面只看统一的 `run(context, stream)`。

### 2.2 BaseAgent 负责叶子 LLM 调用

`deeptutor/agents/base_agent.py` 是大部分叶子 agent 的公共基类，提供：

- 从当前 settings / env 解析 LLM provider、model、base_url、api_key、api_version。
- 从 `agents.yaml` 读取模块级 temperature、max_tokens、retry。
- 通过 PromptManager 加载 `agents/<module>/prompts/{zh,en}/<agent>.yaml`。
- `call_llm()` 和 `stream_llm()`，统一接入 `deeptutor.services.llm.complete/stream`。
- 自动处理 `response_format` 支持判断、token limit 字段兼容、多模态附件适配。
- `set_trace_callback()`，把 LLM running/streaming/complete/error 事件交给 capability wrapper 转成 StreamBus 事件。
- token 统计同时支持外部 TokenTracker 和模块级共享 `LLMStats`。

例外：`agents/chat/agentic_pipeline.py` 没有继承 `BaseAgent`，而是直接使用 `llm_stream` 和 OpenAI/Azure 原生 client 来支持 native tool calling。

### 2.3 StreamBus 是 UI 合同，trace callback 是桥

多数 pipeline 内部不会直接知道前端协议。它们只发出两类东西：

- 自己的 progress callback，如 `{"status": "block_started", ...}`。
- BaseAgent trace callback，如 `{"event": "llm_call", "state": "streaming", ...}`。

`capabilities/*.py` 中的 bridge 再把这些 callback 转成：

- `stream.progress(...)`
- `stream.thinking(...)`
- `stream.observation(...)`
- `stream.tool_call(...)`
- `stream.tool_result(...)`
- `stream.content(...)`
- `stream.result(...)`
- `stream.error(...)`

这让 chat、solve、research、question、visualize、math_animator 的 UI trace 可以共用同一种 `StreamEvent`。

### 2.4 Answer-now 是每个 capability 自己实现的 fast path

`deeptutor/capabilities/_answer_now.py` 提供共享工具：

- 读取 `answer_now_context`。
- 压缩既有 stream events。
- 生成统一 trace metadata。
- 用单次 LLM synthesis 产出快速结果。

但“跳过哪些阶段、还保留哪些产物”由各 capability 自己决定：

| capability | answer-now 行为 |
|---|---|
| `chat` | 直接合成最终回答 |
| `deep_solve` | 跳过 planning/reasoning，直接 writer synthesis |
| `deep_research` | 跳过 rephrase/decompose/research，直接 report synthesis |
| `deep_question` | 跳过 ideation，单次 JSON 生成题目 |
| `visualize` | 跳过 analyze/review，单次生成可渲染代码 |
| `math_animator` | 跳过 analysis/design/summary，但保留 code_generation + render |

这个设计说明：中断式快速回答不能放在 orchestrator 统一兜底，否则结构化能力会丢失自己的产物合同。

## 3. Chat Agentic Pipeline

文件：`DeepTutor/deeptutor/agents/chat/agentic_pipeline.py`

Chat 是默认能力，也是最接近通用 agent 的实现。阶段固定为：

```text
thinking -> acting -> observing -> responding
```

### 3.1 thinking

`_stage_thinking()`：

- 根据启用工具和 KB 状态构造 thinking system prompt。
- 拼入 `context.memory_context`、`context.skills_context` 和 `conversation_history`。
- 通过 `llm_stream()` 流式生成思考文本。
- 对不支持 vision 的模型，会在附件被剥离时发出提示。
- 输出 `StreamEventType.THINKING`。

### 3.2 acting

`_stage_acting()` 有两条路径：

1. 支持 native tool calling 的 provider：
   - `registry.build_openai_schemas(enabled_tools)` 生成 OpenAI tools schema。
   - 调用 OpenAI/Azure client 的 `chat.completions.create(..., tools=..., tool_choice="auto")`。
   - 最多执行 `MAX_PARALLEL_TOOL_CALLS = 8` 个工具调用。
   - 通过 `asyncio.gather()` 并发执行工具。

2. 不支持 native tool calling 的 provider：
   - 切到 ReAct fallback。
   - 要求模型输出 JSON：`{"action": "...", "action_input": {...}}`。
   - 只执行一个工具或 `done`。

工具调用前会用 `_augment_tool_kwargs()` 注入运行时上下文：

| tool | 注入内容 |
|---|---|
| `rag` | `kb_name`, `mode="hybrid"` |
| `code_execution` | `intent`, `feature="chat"`, `session_id`, `turn_id`, `workspace_dir` |
| `reason` / `brainstorm` | thinking 阶段结果作为 `context` |
| `paper_search` | 默认 `max_results=3`, `years_limit=3`, `sort_by="relevance"` |
| `web_search` | 默认 query 和 task 级 output_dir |

### 3.3 observing

`_stage_observing()` 把 thinking 文本和 tool traces 汇总给模型，让模型生成一段 observation。  
这一步把工具原始结果压缩成“回答前的观察层”，避免最终回答直接堆工具输出。

### 3.4 responding

`_stage_responding()` 用 user question、observation 和 tool trace 生成最终回答，并把 chunk 推到 `stream.content()`。  
最后 result payload 包含：

```text
response
observation
tool_traces
metadata.cost_summary
```

如果工具返回 sources，chat 会额外发送 `stream.sources(...)`。

## 4. Deep Solve Pipeline

入口：`capabilities/deep_solve.py`  
核心：`agents/solve/main_solver.py`

Deep Solve 是明确的 Plan/ReAct/Write 系统：

```text
MainSolver.ainit()
  -> load config
  -> init logger/token tracker
  -> init PlannerAgent + SolverAgent + WriterAgent + SolveToolRuntime

MainSolver.solve(question)
  -> create output_dir
  -> Scratchpad.load_or_create()
  -> PlannerAgent.process()
  -> per-step SolverAgent ReAct loop
  -> SolveToolRuntime.execute()
  -> WriterAgent.process()/process_iterative()
  -> final_answer.md + scratchpad.json + cost_report.json
```

### 4.1 Capability wrapper 的职责

`DeepSolveCapability.run()` 做了几件关键工作：

- 读取 LLM 配置。
- 根据 `context.enabled_tools` 决定工具集合。
- 如果启用了 `rag` 但没有选 KB，主动移除 `rag`，避免下游暴露不可用动作。
- 实例化 `MainSolver`。
- 把 solver 的 trace/progress/content callback 桥接到 StreamBus。
- writer 流式 token 进入 `stream.content(stage="writing")`。

### 4.2 Scratchpad 是 solve 的状态核心

`agents/solve/memory/scratchpad.py` 保存：

- plan
- plan steps
- 每个 step 的 ReAct entries
- thought/action/action_input/observation/self_note/sources
- plan revisions

它是 Planner、Solver、Writer 的共享记忆，也是最终引用和答案生成的证据池。

### 4.3 SolverAgent 的动作空间

`SolveToolRuntime` 把全局 `ToolRegistry` 包装成 solve 专用动作空间：

- 工具名和 tool aliases 都加入 `valid_actions`。
- 额外加入控制动作 `done` 和 `replan`。
- 执行时把单个 `action_input` 映射到工具参数候选：`query / intent / task / prompt / input / code`。
- 对 `rag` 没有 KB 的情况返回结构化失败结果，而不是让 RAG 服务崩。

ReAct loop 每轮：

```text
SolverAgent.process()
  -> action/action_input/thought/self_note
  -> done: 当前 step 完成
  -> replan: PlannerAgent 重新规划
  -> tool action: SolveToolRuntime.execute()
  -> observation + sources 写回 Scratchpad
```

### 4.4 Writer 是最终用户可见答案的唯一出口

解题阶段结束后，`WriterAgent` 读取 Scratchpad 写答案：

- 普通模式：`process()` 一次性写。
- 详细模式：`process_iterative()` 分步增量写。
- capability 通过 `_content_callback` 把 writer token 推到主聊天区域。

这个模式值得复用：复杂推理过程可以丰富，但最终回答要通过单独 writer 收敛。

## 5. Deep Research Pipeline

入口：`capabilities/deep_research.py`  
核心：`agents/research/research_pipeline.py`

Deep Research 是动态主题队列驱动的多 agent 系统：

```text
RephraseAgent
  -> DecomposeAgent
  -> DynamicTopicQueue
  -> ManagerAgent
  -> ResearchAgent + tools
  -> NoteAgent
  -> CitationManager
  -> ReportingAgent
```

### 5.1 Capability 有两段式执行

`DeepResearchCapability.run()` 先校验 request config。然后：

1. 如果没有 `confirmed_outline`：
   - 只跑 planning/decompose。
   - 输出 outline preview。
   - 不进入正式 research loop。

2. 如果已有 `confirmed_outline`：
   - 把确认后的 outline 转成 `pre_confirmed_outline`。
   - 初始化 `ResearchPipeline`。
   - 执行完整 research + report。

这个交互设计很重要：长任务先让用户确认研究大纲，避免直接进入高成本执行。

### 5.2 Phase 1：rephrase + decompose + seed queue

`ResearchPipeline._phase1_planning()`：

- 可多轮调用 `RephraseAgent` 优化 topic。
- 调用 `DecomposeAgent` 生成 sub_topics。
- 用 sub_topics 初始化 `DynamicTopicQueue`。
- 如果传入 `pre_confirmed_outline`，跳过 rephrase/decompose，直接 seed queue。
- 将 planning progress 写入 JSON 文件并回调前端。

### 5.3 DynamicTopicQueue 是 research 的调度内存

`agents/research/data_structures.py` 定义：

- `TopicBlock`：最小研究单元。
- `ToolTrace`：一次工具调用、原始回答、NoteAgent 摘要和 citation id。
- `DynamicTopicQueue`：保存 block 列表、状态、统计和 JSON 持久化。

block 状态：

```text
pending -> researching -> completed / failed
```

ManagerAgent 可以在研究过程中追加新 topic，因此队列不是静态计划。

### 5.4 Phase 2：series 或 parallel research loop

`_phase2_researching()` 按配置选择：

- `series`：ManagerAgent 逐个取 pending block，ResearchAgent 完成后标记 completed。
- `parallel`：用 `asyncio.Semaphore(max_parallel_topics)` 控制并发，`asyncio.gather()` 跑多个 block，并继续处理过程中新增的 pending block。

单个 block 的执行逻辑：

```text
ResearchAgent.process(
  topic_block,
  call_tool_callback=_call_tool,
  note_agent=NoteAgent,
  citation_manager=CitationManager,
  queue=DynamicTopicQueue,
  manager_agent=ManagerAgent
)
```

工具调用由 `_call_tool()` 统一接入全局 `ToolRegistry`，支持：

- `rag` / `rag_hybrid` / `rag_naive`
- `web_search`
- `paper_search`
- `code_execution` / `run_code`

每个工具调用有 timeout 和 retry。结果被序列化成 JSON 字符串，NoteAgent 再做摘要，CitationManager 管引用。

### 5.5 Phase 3：reporting

`_phase3_reporting()`：

- 给 `ReportingAgent` 设置 `CitationManager`。
- 根据 queue 里所有 completed blocks 写报告。
- 保存最终 Markdown report、queue.json、outline.json 和 metadata。

Research 的核心价值不在单个 LLM call，而在“动态主题队列 + 工具证据 + 摘要 + 引用 + 报告”的状态机。

## 6. Deep Question Pipeline

入口：`capabilities/deep_question.py`  
核心：`agents/question/coordinator.py`

Deep Question 不是完整 ReAct，而是题目生成流水线：

```text
custom topic:
  IdeaAgent batches(max 5)
  -> QuestionTemplate[]
  -> Generator per template
  -> summary.json

mimic exam:
  parse PDF / parsed exam dir
  -> extract QuestionTemplate[]
  -> Generator per template

follow-up:
  FollowupAgent
```

### 6.1 Custom topic

`AgentCoordinator.generate_from_topic()`：

- 每批最多 `BATCH_SIZE = 5` 个模板。
- IdeaAgent 生成 `QuestionTemplate`。
- 通过 `existing_concentrations` 降低重复。
- 逐题调用 Generator。
- 每题生成后通过 ws callback 发 `question_update/result/progress`。

### 6.2 Mimic mode

`generate_from_exam()`：

- upload 模式：调用 MinerU 解析 PDF。
- parsed 模式：直接读取已解析考试目录。
- 用 `extract_questions_from_paper()` 生成 `*_questions.json`。
- 转成 `QuestionTemplate` 后复用 Generator。

### 6.3 Follow-up mode

如果 `context.metadata.question_followup_context` 里已有 question，capability 直接走 `FollowupAgent`，不再生成整套 quiz。

## 7. Visualize Pipeline

入口：`capabilities/visualize.py`  
核心：`agents/visualize/pipeline.py`

Visualize 是轻量三阶段 pipeline：

```text
AnalysisAgent
  -> CodeGeneratorAgent
  -> ReviewAgent / local html validation
  -> fenced code block + structured viewer payload
```

阶段：

- `analyzing`：判断 render_type、视觉目标和数据描述。
- `generating`：生成 SVG / Chart.js / Mermaid / HTML 代码。
- `reviewing`：非 HTML 走 ReviewAgent；HTML 跳过 LLM review，改成本地 `is_valid_html_document()`，失败则 `build_fallback_html()`。

最终 result payload 给前端 viewer：

```text
response
render_type
code.language
code.content
analysis
review
```

这个实现说明：结构化产物能力要把“聊天可见内容”和“前端可渲染 payload”同时产出。

## 8. Math Animator Pipeline

入口：`capabilities/math_animator.py`  
核心：`agents/math_animator/pipeline.py`

Math Animator 是产物型能力，依赖可选 `manim`：

```text
ConceptAnalysisAgent
  -> ConceptDesignAgent
  -> CodeGeneratorAgent
  -> ManimRenderService
  -> CodeRetryManager
  -> SummaryAgent
  -> artifacts payload
```

关键实现点：

- capability 入口先检查 `importlib.util.find_spec("manim")`。
- `validate_math_animator_request_config()` 处理 output_mode、quality、style_hint。
- `CodeRetryManager` 负责 render 失败后的修复循环。
- `ManimRenderService` 负责实际渲染并回传 render progress。
- 可选 `VisualReviewService + VisualReviewAgent` 对渲染结果做视觉审查。
- answer-now 仍然保留 code_generation + render，因为这个能力的核心价值是产出视频/图片，而不是文本总结。

最终 result payload 包含：

```text
summary
code
output_mode
artifacts
timings
render.retry_history
analysis
design
```

## 9. 旁路 Agents

### 9.1 NotebookAnalysisAgent

文件：`agents/notebook/analysis_agent.py`

这是主 capability 前的上下文增强 agent，不是独立 capability。它对选中的 notebook records 跑三阶段：

```text
thinking -> acting(select record ids) -> observing
```

输出 observation，供 TurnRuntimeManager 拼进主能力的 context。  
这说明 DeepTutor 把“上下文选择/压缩”也当成 agent，而不是硬编码在 prompt 里。

### 9.2 VisionSolverAgent

文件：`agents/vision_solver/vision_solver_agent.py`

这是图像数学题到 GeoGebra 的专用 agent：

```text
BBox -> Analysis -> GGBScript -> Reflection -> Tutor response
```

它继承 `BaseAgent`，但使用 markdown prompt 文件和多模态消息。当前更像工具/专用 router 背后的 agent，不在内置 `CapabilityRegistry` 主列表里。

### 9.3 Book Agents 不属于本报告主范围

`deeptutor/book/agents/` 属于 BookEngine，是和 ChatOrchestrator 平行的产品引擎。它复用 DeepTutor 的 prompt/LLM/stream 思路，但不是 `deeptutor/agents/` 主包内的 capability pipeline。

## 10. 对 new_kernel 的可复用设计

### 10.1 不要把所有任务塞进一个 Agent 类

推荐结构：

```text
kernel/
  context.py
  events.py
  trace.py
  capability.py
  tool_registry.py
  agent_base.py
  runtime/
    turn_manager.py
    orchestrator.py
  capabilities/
    chat.py
    teach.py
    research.py
  agents/
    chat/
    teach/
    research/
```

`Capability` 负责对外合同，`agents` 负责内部 pipeline。这样可以避免教学、研究、解题、可视化共用同一个臃肿 agent loop。

### 10.2 统一事件协议比统一内部实现更重要

DeepTutor 内部各 pipeline 差异很大，但都能被 UI 消费，是因为它们最后都转成 `StreamBus` 事件。  
new_kernel 应优先定义稳定事件：

- stage_start/stage_end
- thinking
- observation
- tool_call/tool_result
- content
- sources
- result
- error
- done

每个事件都应携带：

- `source`
- `stage`
- `content`
- `metadata.call_id`
- `metadata.trace_kind`
- `metadata.trace_role`
- `metadata.label`

### 10.3 叶子 Agent 应统一 BaseAgent

可复用 `BaseAgent` 的思路：

- 统一 provider 调用。
- 统一 prompt 加载。
- 统一 response_format 能力判断。
- 统一多模态适配。
- 统一 trace callback。
- 统一 token/cost 统计。

但 chat 这种需要 native tool calling 的 pipeline，可以允许绕过 BaseAgent，前提是仍然输出同一套 trace 事件。

### 10.4 工具运行时要按能力二次包装

DeepTutor 的教训是：全局 ToolRegistry 不等于每个能力都可以直接暴露所有工具。  
Solve 用 `SolveToolRuntime` 做了正确的二次包装：

- 控制动作 `done/replan`。
- 工具别名映射。
- 单字符串 action_input 到工具参数映射。
- 按能力注入 workspace/kb/context。
- 对不可用工具做结构化降级。

new_kernel 也应该有：

```text
GlobalToolRegistry
  -> CapabilityToolRuntime
  -> Agent action space
```

### 10.5 长任务需要显式状态对象

DeepTutor 的两个关键状态对象：

- solve：`Scratchpad`
- research：`DynamicTopicQueue`

new_kernel 做教学型源码 Agent 时，也应该有显式状态对象，而不是把所有历史塞进 prompt：

- `TeachingMap`
- `TurnPlan`
- `CoveredConceptLedger`
- `EvidenceStore`
- `OpenQuestionQueue`

状态对象应能持久化、恢复、被 writer/quality gate 读取。

### 10.6 最终回答最好由 writer 收敛

Solve 的 Plan/ReAct/Write 模式值得迁移。  
对 Repo Tutor 教学场景，建议：

```text
planner: 本轮讲什么，为什么现在讲
reader/tool agent: 读取少量源码证据
teacher/writer: 用教学结构输出
quality gate: 检查是否过度证据化、是否有教学推进
```

不要让工具读取阶段直接变成用户可见回答。

## 11. 风险与注意点

1. `capabilities/*.py` 的 bridge 代码重复较多。  
   多个 capability 都在手写 `llm_call/tool_call/tool_result` 到 StreamBus 的转换，未来应抽出 `TraceBridge`。

2. Chat 没有继承 `BaseAgent`。  
   这是为了 native tool calling，但它也导致 LLM 调用、token 估算、prompt 构造和 BaseAgent 不完全一致。

3. 工具执行语义不完全统一。  
   Chat、Solve、Research 都接 `ToolRegistry`，但参数注入、失败处理、RAG 无 KB 降级逻辑各写一套。

4. Research parallel mode 复杂度高。  
   它有 semaphore、async wrappers、动态新增 topic、progress file lock。这个模式适合研究任务，不应无脑搬到短回合教学 agent。

5. Answer-now 是按 capability 分散实现。  
   好处是保留结构化产物合同；代价是每个 capability 都要维护自己的 fast path。

6. 产物型能力要同时管理文本和 artifact。  
   Visualize/MathAnimator 都不是只返回文本，它们必须返回 viewer payload、代码、artifact path、retry history。

7. code execution 仍需要更强隔离。  
   DeepTutor 已做 AST/import/运行目录限制，但不是强沙箱。面向不可信用户时还需要容器、权限用户、资源限制。

## 12. 一句话迁移结论

new_kernel 最该借鉴的不是 DeepTutor 的所有具体 agent，而是这条骨架：

```text
统一 turn runtime
  + CapabilityManifest 对外合同
  + 每个能力自己的 pipeline
  + BaseAgent 统一叶子 LLM 调用
  + ToolRegistry + capability-specific tool runtime
  + StreamBus 统一事件
  + 显式状态对象
  + writer 收敛最终回答
```

对 Irene/Repo Tutor 来说，教学型源码 Agent 应走“单产品体验、多内部阶段”的路线，而不是暴露成多 agent 平台。
