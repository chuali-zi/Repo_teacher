# DeepTutor `deeptutor/tools` 逻辑侦察报告

> 侦察对象：`C:\Users\chual\vibe\Irene\DeepTutor`  
> 主范围：`DeepTutor/deeptutor/tools`、`deeptutor/runtime/registry/tool_registry.py`、核心调用者。  
> 辅助范围：同在 `deeptutor` 包内的 `deeptutor/tutorbot/agent/tools`，用于区分另一套 TutorBot 工具体系。  
> 报告目标：把现有 tools 的真实逻辑、调用边界、风险点和新内核迁移建议沉淀到 `new_docs/new_kernel`。

## 1. 总结判断

DeepTutor 里存在两套名字相近但职责不同的 tools：

1. `deeptutor/tools` 是主产品的 Level 1 工具层。它通过 `BaseTool`、`ToolRegistry`、`ToolResult` 对接 Chat/DeepSolve/DeepResearch 等 capability，也能通过插件 API 直接执行。
2. `deeptutor/tutorbot/agent/tools` 是 TutorBot 的 agent 工具体系。它有独立的 `Tool` 基类和 `ToolRegistry`，返回字符串，支持文件、shell、web、MCP、消息、子代理、团队协作、定时任务，并用 adapter 复用一部分 `deeptutor/tools` 能力。

主工具层不是一个纯目录导出集合，而是三层结构：

```text
core/tool_protocol.py
  -> runtime/registry/tool_registry.py
  -> tools/builtin/__init__.py
  -> tools/*.py and tools/{prompting,question,vision}
```

其中真正注册进主 `ToolRegistry` 的只有 7 个内置工具：

```text
brainstorm
rag
web_search
code_execution
reason
paper_search
geogebra_analysis
```

`tools/question`、`tools/vision`、`tex_chunker.py`、`tex_downloader.py` 虽在 tools 目录下，但多数不是 function-calling tool，而是被 API、agent 或工具包装层直接调用的辅助工具。

## 2. 目录与职责图

| 路径 | 角色 | 是否注册进主 ToolRegistry |
|---|---|---|
| `deeptutor/core/tool_protocol.py` | 工具协议：参数、定义、提示 hints、标准结果、抽象基类 | 协议层 |
| `deeptutor/runtime/registry/tool_registry.py` | 主工具注册器、别名解析、schema 生成、提示文本组装、执行入口 | 注册器 |
| `deeptutor/tools/builtin/__init__.py` | 7 个内置工具的 `BaseTool` wrapper | 是 |
| `deeptutor/tools/prompting/` | 从 YAML 加载工具提示词，渲染 list/table/aliases/phased 格式 | 间接使用 |
| `deeptutor/tools/brainstorm.py` | 单次 LLM 发散思考 | 通过 `BrainstormTool` |
| `deeptutor/tools/rag_tool.py` | RAGService 的轻包装 | 通过 `RAGTool` |
| `deeptutor/tools/web_search.py` | web search service 的 re-export | 通过 `WebSearchTool` |
| `deeptutor/tools/code_executor.py` | Python 代码生成/执行底层 runner | 通过 `CodeExecutionTool` |
| `deeptutor/tools/reason.py` | 单次 LLM 深度推理 | 通过 `ReasonTool` |
| `deeptutor/tools/paper_search_tool.py` | arXiv 搜索与论文元数据归一化 | 通过 `PaperSearchToolWrapper` |
| `deeptutor/tools/question/` | 试卷 PDF 解析、题目抽取、仿题入口 | 否，API/agent 直接调用 |
| `deeptutor/tools/vision/` | 图片下载、GGBScript 解析/修复、BBox 到 GeoGebra 坐标转换 | 部分被 `GeoGebraAnalysisTool` 相关链路使用 |
| `deeptutor/tools/tex_chunker.py` | LaTeX 文本分块 | 否 |
| `deeptutor/tools/tex_downloader.py` | arXiv LaTeX 源码下载与解包 | 否 |

## 3. 核心协议

工具协议定义在 `deeptutor/core/tool_protocol.py`：

- `ToolParameter`：单个参数元数据，能转为 JSON Schema property。
- `ToolDefinition`：工具名、描述、参数列表，`to_openai_schema()` 生成 OpenAI function-calling schema。
- `ToolAlias` / `ToolPromptHints`：提示词层元数据，不参与运行时校验。
- `ToolResult`：统一返回结构，包含 `content`、`sources`、`metadata`、`success`。
- `BaseTool`：所有主工具 wrapper 必须实现 `get_definition()` 和 `execute()`，可覆盖 `get_prompt_hints()`。

这层设计偏“LLM function tool”，而不是完整沙箱或权限模型。当前协议没有显式 `ToolContext`，所以 session、turn、workspace、KB、附件、event sink 等运行时上下文都是通过 `**kwargs` 临时塞进工具。

## 4. 注册与别名解析

主注册器在 `deeptutor/runtime/registry/tool_registry.py`：

1. `load_builtins()` 遍历 `BUILTIN_TOOL_TYPES` 实例化工具。
2. `register()` 以 `tool.name` 覆盖写入 `_tools`。
3. `_resolve_request()` 先查直接命中，再查 `TOOL_ALIASES`。
4. `get_enabled()` 会把用户给的名字解析成真实工具，并按 canonical name 去重。
5. `build_openai_schemas()` 把工具定义转成 OpenAI tools schema。
6. `build_prompt_text()` 把 YAML prompt hints 渲染成 list/table/aliases/phased。
7. `execute()` 负责别名解析后调用对应 `tool.execute(**kwargs)`。

当前别名：

| 别名 | 真实工具 | 默认参数 |
|---|---|---|
| `rag_hybrid` | `rag` | `mode=hybrid` |
| `rag_naive` | `rag` | `mode=naive` |
| `rag_search` | `rag` | 无 |
| `code_execute` | `code_execution` | 无 |
| `run_code` | `code_execution` | 无 |

额外逻辑：如果解析后是 `code_execution` 且参数里有 `query`，会把 `query` 改成 `intent`。这让 ReAct 风格的 `Action Input` 也能兼容代码执行工具。

## 5. Prompt Hints 逻辑

`deeptutor/tools/prompting/__init__.py` 从 `tools/prompting/hints/{language}/{tool}.yaml` 读取工具提示信息：

- `load_prompt_hints(tool_name, language)`：语言归一化，中文缺失时回退英文。
- `ToolPromptComposer.format_list()`：短列表，常用于 thinking/responding 系统提示。
- `format_table()`：ReAct action 表格，支持追加 `done`、`replan` 等控制动作。
- `format_aliases()`：把工具别名展示给模型。
- `format_phased()`：按 exploration、expansion、synthesis、verification 等阶段组织。

提示层与执行层是分离的。YAML 能影响模型选择工具的倾向，但不会改变 `ToolRegistry.execute()` 的权限或参数校验。

## 6. 7 个内置工具的真实行为

| 工具 | wrapper | 实际后端 | 核心输入 | 输出结构 | 关键失败路径 |
|---|---|---|---|---|---|
| `brainstorm` | `BrainstormTool` | `tools/brainstorm.py` | `topic`、可选 `context` | `content=answer`，metadata 保留 topic/model | 没有模型配置时抛错 |
| `rag` | `RAGTool` | `RAGService` -> LlamaIndex | `query`、`kb_name`、透传额外参数 | `content=answer/content`，sources 只放 query/kb_name，metadata 放完整 result | 无 KB 时可能向下游传 `None` 并失败；外层 chat 捕获成 tool error |
| `web_search` | `WebSearchTool` | `services/search.web_search()` | `query`、`output_dir`、`verbose` | `content=answer`，sources 来自 citations | provider 配置错误或网络错误会抛异常 |
| `code_execution` | `CodeExecutionTool` | `tools/code_executor.run_code()` | `intent` 或 `code`、`timeout`、workspace 上下文 | stdout/stderr/artifacts 拼成 content，metadata 含代码和执行目录 | 校验失败、超时、进程异常都返回 `success=False` 或异常 |
| `reason` | `ReasonTool` | `tools/reason.py` | `query`、可选 `context` | `content=answer` | 没有模型配置时抛错 |
| `paper_search` | `PaperSearchToolWrapper` | `ArxivSearchTool` | `query`、`max_results`、`years_limit`、`sort_by` | markdown 摘要，sources 为 arXiv 条目 | 多数 arXiv 错误被底层吞掉并表现为无结果 |
| `geogebra_analysis` | `GeoGebraAnalysisTool` | `VisionSolverAgent` | `question`、`image_base64`、`language` | 几何摘要 + GeoGebra commands，metadata 为各阶段计数 | 无图片直接 `success=False`；pipeline 异常返回错误文本 |

### 6.1 Brainstorm

`brainstorm()` 是单次无状态 LLM streaming 调用。它读取全局 LLM 配置，默认使用 `get_agent_params("brainstorm")` 的 `max_tokens=2048`、`temperature=0.8`。系统提示要求输出 5 到 8 个不同角度的方向，每个方向包含 Direction 和 Rationale。

它不调用外部检索，也没有工具内部重试。返回字段只有 `topic`、`answer`、`model`。

### 6.2 Reason

`reason()` 也是单次无状态 LLM streaming 调用。默认读取 `get_agent_params("solve")`，常规默认倾向是更长输出和低温度。它把 `context` 和 `query` 拼成用户提示，系统提示要求逐步推理、数学推导和明确结论。

它是“把当前问题切出一个深推理子任务”的工具，不引入新证据。

### 6.3 RAG

`rag_tool.py` 只是 `RAGService` 的纯包装：

```text
rag_search(...)
  -> RAGService(kb_base_dir, provider)
  -> RAGService.search(...)
  -> LlamaIndexPipeline.search(...)
```

关键事实：

- RAG provider 已经收敛为单一 `llamaindex`。`normalize_provider_name()` 总是返回 `llamaindex`。
- `mode` 参数会在 `RAGService.search()` 和 `LlamaIndexPipeline.search()` 中被 pop 掉，`rag_hybrid`、`rag_naive` 实际只保留兼容意义。
- 搜索结果是向量检索出的 node text 拼接，不再走 LLM 合成。也就是说 wrapper 描述里的 “LLM-synthesised answer” 与当前实现不一致。
- `RAGService.search()` 支持 `event_sink`，会发 summary status，也会捕获部分 raw logs。
- `DeepSolveCapability` 会在没有 KB 时主动移除 `rag`，但 `ChatCapability` 没有同等保护。Chat 中如果启用了 `rag` 但未选择 KB，工具可能失败后被 `_execute_tool_call()` 捕获为错误 observation。

### 6.4 Web Search

`tools/web_search.py` 实际是 `deeptutor.services.search` 的 re-export。主 wrapper 使用 `asyncio.to_thread()` 包住同步搜索函数。

`services/search.web_search()` 的关键逻辑：

1. 读取 `tools.web_search` 配置，如果 disabled，返回固定 disabled 响应。
2. 通过 `resolve_search_runtime_config()` 解析 provider、api_key、base_url、max_results、proxy。
3. 检查 provider 是否支持。`exa`、`baidu`、`openrouter` 虽然文件还在，但已标为 deprecated/unsupported。
4. `brave`、`tavily`、`jina` 缺 key 时降级到 `duckduckgo`。
5. `perplexity`、`serper` 缺 key 时直接抛错。
6. `searxng` 缺 base_url 时降级到 `duckduckgo`。
7. 对不自带 answer 的 raw SERP provider，使用 `AnswerConsolidator` 模板合成 answer；可选用 LLM 合成。
8. 如传入 `output_dir`，会把完整结果保存成 JSON。

风险点：搜索 provider、图片下载和 TeX 下载都能访问外部 URL。当前 web search 主要依赖 provider 自身，image utility 只校验 URL scheme/netloc，没有 SSRF 防护。

### 6.5 Code Execution

`CodeExecutionTool.execute()` 有两条路径：

```text
有 code:
  -> run_code(language="python", code=...)

无 code 但有 intent:
  -> _generate_code(intent)
  -> run_code(...)
```

`_generate_code()` 调用 LLM 生成纯 Python，并剥离 markdown fences。`run_code()` 的底层流程：

1. 只支持 Python。
2. 如果没有 `workspace_dir`，根据 `feature/task_id/turn_id/session_id` 推导 task workspace，否则使用显式 workspace。
3. 创建 `exec_时间戳` 子目录。
4. `ImportGuard.validate()` 做 AST 检查。
5. 把代码写入 `code.py`。
6. 使用 `subprocess.run([sys.executable, "-I", code.py], cwd=execution_dir, timeout=...)` 执行。
7. 保存 `output.log`。
8. 收集执行目录下非 `code.py`、`output.log`、`.gitkeep` 的一层文件作为 artifacts。

安全边界需要如实看待：

- 代码注释明确说明这不是 OS 级 sandbox。
- `ImportGuard` 只限制 import 根模块、直接调用 `open/exec/eval/compile/__import__/input/breakpoint`，以及 `os/sys/subprocess/socket/pathlib/shutil/importlib/builtins` 的直接属性调用。
- 没有内存、CPU、文件数量、网络、进程树隔离。
- `RUN_CODE_ALLOWED_ROOTS_ENV` 被定义但未实际使用。
- `workspace_dir` 可由调用方传入并直接 `resolve()`、`mkdir()`，主 wrapper 没有根目录白名单校验。
- demo 代码里演示了 `open()` 文件读写，但 `ImportGuard` 实际会拒绝 `open()`。这是文档/示例与真实校验的冲突。

### 6.6 Paper Search

`ArxivSearchTool.search_papers()`：

- 空 query 返回空列表。
- `max_results` 限制到 1 到 20。
- 根据 `sort_by` 选择 relevance 或 submitted date。
- 实际 fetch 数为 `max_results * 2`，上限 30。
- 用 `asyncio.wait_for(asyncio.to_thread(...), timeout=30)` 包住 arXiv client。
- HTTP 429 会 sleep 3 秒重试一次。
- 大部分超时、HTTP、未知异常都会记录日志后返回空列表。

wrapper 层把空列表格式化成 “No arXiv preprints found”。这对用户友好，但会把网络故障和真实无结果混在一起。

### 6.7 GeoGebra Analysis

`GeoGebraAnalysisTool` 是注册进主 `ToolRegistry` 的视觉几何工具，但 chat 默认可选工具中排除了它：

```text
CHAT_EXCLUDED_TOOLS = {"geogebra_analysis"}
CHAT_OPTIONAL_TOOLS = BUILTIN_TOOL_NAMES - excluded
```

它要求 `image_base64`，然后创建 `VisionSolverAgent`，运行视觉解题/检测/脚本/反思链路，最后返回：

- constraints 和 geometric relations 摘要；
- GeoGebra commands block；
- commands_count、bbox_elements、constraints_count、relations_count、reflection_issues 等 metadata。

如果没有图片，直接返回 `success=False`。如果 pipeline 抛异常，会捕获并返回 `Analysis pipeline error: ...`。

## 7. 调用链

### 7.1 API 和 orchestrator

启动时 `deeptutor/api/main.py` 会执行 `validate_tool_consistency()`：

```text
Capability manifests tools_used
  - runtime tool registry list_tools()
  = drift -> startup error
```

这能发现 capability manifest 引用了未注册工具的配置漂移。

`ChatOrchestrator` 自身不执行工具。它只把 `UnifiedContext` 路由给 capability，并提供 `list_tools()`、`get_tool_schemas()` 这类 facade。

`plugins_api.py` 提供直接工具执行：

- `GET /plugins/list`：列出工具 definition、capability、plugin。
- `POST /plugins/tools/{tool_name}/execute`：直接执行工具。
- `POST /plugins/tools/{tool_name}/execute-stream`：执行工具并捕获项目日志作为 SSE。

注意：这些直接接口会绕过 Chat/DeepSolve 的上下文注入和部分防护。如果 API 暴露到不可信环境，`code_execution`、`web_search`、`rag` 都需要额外权限控制。

### 7.2 TurnRuntime 到 UnifiedContext

`TurnRuntimeManager` 把前端/CLI payload 转成 `UnifiedContext`：

```text
payload.tools -> context.enabled_tools
payload.knowledge_bases -> context.knowledge_bases
payload.attachments -> context.attachments
payload.config -> context.config_overrides
turn_id/session_id -> context.metadata
```

文档语义上 `enabled_tools=None` 表示“未指定”，`[]` 表示“显式禁用所有工具”。但 Chat pipeline 当前用 `enabled_tools or []`，所以在 chat 中 `None` 和 `[]` 都会变成无工具。

### 7.3 ChatCapability 工具链

`AgenticChatPipeline.run()` 是四阶段：

```text
thinking -> acting -> observing -> responding
```

工具只在 acting 阶段运行。acting 有两种模式：

1. native function-calling：对支持 OpenAI tools 的 provider，调用 `client.chat.completions.create(..., tools=schemas, tool_choice="auto")`。
2. ReAct fallback：对不支持工具调用的 provider，用 prompt table 让模型输出 action JSON。

native 模式关键细节：

- 最大并行工具数为 8。
- 参数 JSON 用 `parse_json_response()` 解析。
- `_augment_tool_kwargs()` 注入运行时参数：
  - `rag`：默认填第一个 KB，默认 `mode=hybrid`。
  - `code_execution`：默认 `intent=context.user_message`，`feature=chat`，`session_id`，`turn_id`，`workspace_dir=task_dir/code_runs`。
  - `reason`/`brainstorm`：默认 `context=thinking_text`。
  - `paper_search`：默认 `max_results=3`、`years_limit=3`、`sort_by=relevance`。
  - `web_search`：默认 `query=context.user_message`，`output_dir=task_dir/web_search`。
- 工具调用用 `asyncio.gather()` 并行执行。
- tool result 作为 event 发给 UI，同时作为 observation/responding 的输入。
- 进入 observation/responding 的 tool trace 会截断到 4000 字符。

### 7.4 DeepSolve 工具链

`DeepSolveCapability` 的 manifest 工具是：

```text
rag, web_search, code_execution, reason
```

这里比 Chat 更严格：如果启用了 `rag` 但没有 KB，会直接移除 `rag` 并发 warning，避免 ReAct loop 暴露不可用动作。

`SolveToolRuntime` 是 DeepSolve 对主 `ToolRegistry` 的适配层：

- 内置控制动作：`done`、`replan`。
- 根据工具 definition 把单字符串 `action_input` 映射到第一个匹配参数：`query`、`intent`、`task`、`prompt`、`input`、`code`。
- 为 RAG、web_search、code_execution、reason 注入 KB、output_dir、reason_context、LLM 参数。
- 如果 `rag` 无 KB，返回结构化 `ToolResult(success=False, metadata={"skipped": True})`，不让底层 RAG 服务崩掉。

### 7.5 DeepResearch 和 DeepQuestion

`DeepResearchCapability` manifest 工具是：

```text
rag, web_search, paper_search, code_execution
```

它会基于 request config 和 enabled tools 生成 research runtime config。若用户选择 KB source 但没有 KB，会降级移除 KB source；如果没有任何 source，直接返回错误。

`DeepQuestionCapability` manifest 工具是：

```text
rag, web_search, code_execution
```

它把 enabled tools 转为 `tool_flags_override` 传给 `AgentCoordinator`。同时 `tools/question` 下的 mimic/PDF/LLM 抽题工具通过 question API 和 coordinator 路径直接调用。

## 8. `tools/question` 辅助工具

`tools/question` 不是主 `ToolRegistry` 的一部分，主要服务试卷仿题：

```text
PDF upload or parsed paper
  -> parse_pdf_with_mineru()
  -> extract_questions_from_paper()
  -> AgentCoordinator.generate_from_exam()
```

### 8.1 PDF Parser

`pdf_parser.py`：

- 用 `magic-pdf --version` 或 `mineru --version` 探测 MinerU。
- 校验 PDF 路径存在且后缀为 `.pdf`。
- 运行 `mineru_cmd -p pdf -o temp_output`。
- 把 MinerU 输出目录移动到 `reference_papers/<pdf_stem>` 或用户指定目录。

优点：`subprocess.run(..., shell=False)`，命令参数不是 shell 拼接。

风险：如果输出目录已存在，直接 `shutil.rmtree(output_dir)`。这在工具自身使用场景可接受，但作为 API 能力时应确保 output_base_dir 是受控目录。

### 8.2 Question Extractor

`question_extractor.py`：

- `_find_parsed_content_dir()` 优先找 `auto`、`hybrid_auto`，再找有 `.md` 或 `*_content_list.json` 的目录。
- `load_parsed_paper()` 读取 markdown、可选 content_list 和 images 目录。
- `extract_questions_with_llm()` 把最多 15000 字符 markdown 和 image 文件列表喂给 LLM，要求返回 JSON。
- 如果 provider 支持 response_format，会请求 JSON object。
- 使用 `parse_json_response()` 解析。
- `save_questions_json()` 保存题目 JSON。

问题：文件底部 `main()` 使用 `sys.exit()`，但模块没有导入 `sys`。作为 import 调用不受影响，直接 CLI 执行会触发 `NameError`。

### 8.3 Exam Mimic

`exam_mimic.py` 是薄 wrapper：

- 要求 `pdf_path` 和 `paper_dir` 二选一。
- 读取 LLM config。
- 创建 `AgentCoordinator`。
- 如果有 websocket callback，则桥接 progress。
- 根据 upload/parsed 模式调用 `generate_from_exam()`。
- 返回 success、summary、generated_questions、failed_questions、total_reference_questions。

## 9. `tools/vision` 辅助工具

### 9.1 Image Utils

`image_utils.py`：

- `is_valid_image_url()` 只检查 scheme 是 http/https 且有 netloc。
- `fetch_image_from_url()` 用 httpx 下载，支持 redirect，timeout 30s。
- 支持 jpeg/png/gif/webp，最大 10MB。
- `resolve_image_input()` 优先使用 data URL base64，否则下载 URL 转 base64。

风险：

- 没有私网地址、localhost、metadata IP、DNS rebinding 防护。
- 大小检查发生在 `response.content` 读取后，不是流式限制。

### 9.2 GGBScript Parser/Validator

`block_parser.py` 解析：

````text
```ggbscript[page-id;title]
...
```
````

或 `geogebra` block。解析后会调用 `validate_ggbscript()` 修复常见错误。

`ggb_validator.py` 主要做正则级修复：

- `Point({x,y})` 修成 `(x,y)`。
- `log(10,x)` 修成 `lg(x)`。
- 删除 `#` 注释。
- 把 GeoGebra 标准命令的圆括号改成方括号，如 `Circle(...)` -> `Circle[...]`。
- 对分式二次曲线系数给 warning。

它不是完整 GeoGebra 解释器，只是轻量格式修复器。

### 9.3 Coordinate Transform

`coord_transform.py` 在 BBox 像素坐标和 GeoGebra 坐标之间转换：

- BBox 原点在左上，y 向下。
- GeoGebra 原点在坐标系中心，y 向上。
- 默认范围 `x=[-10,10]`、`y=[-8,8]`。
- 支持 point、segment start/end、polygon vertices、circle center/radius 批量转换。
- 提供平行、垂直、距离、中点、坐标系建议等几何辅助函数。

## 10. TeX 辅助工具

### 10.1 TexChunker

`TexChunker` 用 tiktoken 估算 token，并按如下策略切块：

1. 先按 `\section`、`\subsection`、`\subsubsection` 切。
2. 单 section 过长时按段落切。
3. 单段落过长时按句子切。
4. 新 chunk 可从上一 chunk 末尾拿 overlap token 保持上下文。
5. 超长重复空白和超长单行会被清理/截断以避免 token 估算异常。

### 10.2 TexDownloader

`TexDownloader`：

- 从 arXiv URL 提取 ID。
- 下载 `https://arxiv.org/e-print/{id}`。
- 判断 tar/zip/单 tex。
- 解包后找主 tex：`main.tex`、`paper.tex`、`manuscript.tex`、包含 `\documentclass` 的 tex、最大 tex。
- 复制到 `workspace_dir/paper_{arxiv_id}/main.tex`。

风险：

- tar 解包使用 `os.path.commonprefix()` 判断路径归属，安全性弱于 `os.path.commonpath()`。
- zip 解包直接 `zip_file.extractall(extract_dir)`，没有 ZipSlip 防护。
- `requests.get()` 直接访问 arXiv URL，没有代理/下载大小限制。

## 11. TutorBot 的另一套 tools

`deeptutor/tutorbot/agent/tools` 是独立系统：

- 基类是 `Tool`，不是主系统的 `BaseTool`。
- registry 返回 OpenAI function schema dict，但执行结果是 string。
- `ToolRegistry.execute()` 会做 schema-driven cast 和 validation，失败时返回字符串错误并附加“换方法”的提示。
- `build_base_tools()` 默认注册 filesystem、shell、web_search、web_fetch。
- `AgentLoop._register_default_tools()` 额外注册 message、spawn、team、cron，以及 `BrainstormAdapterTool`、`RAGAdapterTool`、`CodeExecutionAdapterTool`、`ReasonAdapterTool`、`PaperSearchAdapterTool`。

这套体系有更强的“环境操作”能力，包含文件写入、shell、MCP、子代理、团队协作。它通过 adapter 复用 `deeptutor/tools`，但不是主 `ToolRegistry` 的插件扩展。新内核如果要统一工具层，需要先决定两者是合并协议，还是保持“主学习产品工具”和“TutorBot 环境代理工具”分层。

## 12. 测试覆盖现状

已有测试覆盖：

- `tests/core/test_builtin_tools.py`：内置 wrapper 参数传递、结果包装、GeoGebra 成功路径、别名解析。
- `tests/tools/test_rag_tool.py`：RAG provider 收敛为 llamaindex，旧 provider 名被忽略。
- `tests/core/test_code_executor_safety.py`：拒绝 `open()` 和不安全模块访问的最小安全测试。
- `tests/tools/test_code_executor.py`：task workspace 解析。
- `tests/tools/test_web_search.py`：search 类型、provider registry、deprecated provider 校验。
- `tests/api/test_question_router.py`：question WebSocket mimic 的基础交互。

明显缺口：

1. Chat `enabled_tools=None` 是否应使用 manifest 默认工具，没有测试。
2. Chat 启用 `rag` 但无 KB 的行为，没有端到端测试。
3. `code_execution` 的 `workspace_dir` 根目录约束没有测试，因为当前没有约束。
4. `RUN_CODE_ALLOWED_ROOTS_ENV` 未使用，没有测试暴露。
5. `TexDownloader` tar/zip 解包安全没有测试。
6. `ImageUtils` URL SSRF/私网地址拒绝没有测试。
7. `paper_search` 网络错误与真实无结果没有区分测试。
8. `question_extractor.py` 直接 CLI 执行缺少 smoke test，否则 `sys` 未导入问题会漏掉。

## 13. 关键问题清单

1. **工具协议缺少显式运行时上下文**  
   现在 context 信息靠 `**kwargs` 注入，不同调用者注入不一致。Chat、DeepSolve、direct API、TutorBot adapter 的行为容易漂移。

2. **Chat manifest 与实际默认工具语义不一致**  
   `ChatCapability.manifest.tools_used=CHAT_OPTIONAL_TOOLS`，但 `AgenticChatPipeline._normalize_enabled_tools()` 对 `None` 和 `[]` 都返回空工具。`UnifiedContext` 注释里的“None 表示未指定”没有被 Chat 实现保留。

3. **RAG 描述与实现不一致**  
   wrapper 描述说返回 LLM synthesized answer，但当前 LlamaIndex pipeline 返回的是检索 chunks 拼接。应把“retrieved context”和“generated answer”拆开命名。

4. **RAG mode/legacy provider 参数是兼容壳**  
   `rag_hybrid`、`rag_naive` 会设置 `mode`，但后端直接忽略。保留兼容没问题，但 UI/提示词不应暗示真的有多种检索模式。

5. **Code execution 不应被称为真正 sandbox**  
   它是 best-effort restricted runner。AST guard 可被绕过，且没有 OS 资源隔离。面向不可信用户时风险很高。

6. **代码执行 workspace 缺少强制根目录约束**  
   `workspace_dir` 可由调用方传入。直接工具 API 或未来插件如果传入任意路径，runner 会创建目录并执行。

7. **外部 URL 工具缺少统一网络安全策略**  
   web search、image fetch、TeX downloader、provider fetch 各自处理网络，没有统一 allow/deny、私网阻断、大小流式限制、代理策略。

8. **工具错误语义不统一**  
   有的工具抛异常，有的返回 `ToolResult(success=False)`，有的底层吞掉错误返回空列表。上层很难区分“没结果”“配置错”“网络错”“工具不可用”。

9. **TeX 解包有路径穿越风险**  
   tar 检查方式不够稳，zip 没有检查。虽然当前未注册成 LLM tool，但一旦接入 agent 自动下载论文源码，就会成为高风险路径。

10. **TutorBot tools 与主 tools 重复但协议不兼容**  
    两边都有 registry、schema、执行逻辑。adapter 复用一部分能力，但结果结构、权限模型、错误处理都不同。

## 14. 新内核落地建议

### 14.1 引入显式 ToolContext

建议新内核把工具执行入口改为：

```python
await tool.execute(args: dict, context: ToolContext) -> ToolResult
```

`ToolContext` 至少包含：

- `session_id`
- `turn_id`
- `feature`
- `workspace_root`
- `output_root`
- `knowledge_bases`
- `attachments`
- `language`
- `event_sink`
- `permissions`
- `llm_config`

这样 Chat、DeepSolve、direct API、TutorBot adapter 都能走同一上下文协议。

### 14.2 给工具增加权限标签

每个工具定义应声明能力等级：

| 权限标签 | 示例工具 |
|---|---|
| `llm_call` | brainstorm, reason, code_generation |
| `retrieval` | rag |
| `network` | web_search, paper_search, image fetch, tex downloader |
| `code_exec` | code_execution |
| `filesystem_read` | tex/read, question parser |
| `filesystem_write` | code artifacts, question outputs |
| `external_process` | MinerU parser |

执行前由 policy engine 判断是否允许，而不是散落在各 capability。

### 14.3 把 RAG 结果类型改清楚

建议 RAG 返回：

```json
{
  "retrieved_context": "...",
  "chunks": [...],
  "sources": [...],
  "provider": "llamaindex",
  "answer": null
}
```

如果需要 synthesis，单独建 `rag_answer` 或由 responding 阶段统一合成，避免工具名义上“回答”但实际只是上下文。

### 14.4 收紧 code execution

最低改造：

- 实现并测试 `RUN_CODE_ALLOWED_ROOTS_ENV` 或改为 `ToolContext.workspace_root` 强制约束。
- 禁止 direct API 覆盖任意 `workspace_dir`。
- 在 executor 内校验最终 execution_dir 必须位于允许根目录内。
- 增加 max output、max artifact count、max artifact size。
- 明确文案：restricted runner，不是 sandbox。

更彻底改造：

- 使用容器、微 VM、nsjail/firejail、Windows Job Object 等 OS 隔离。
- 禁止网络或提供显式 network permission。
- 分离 code generation 与 code execution，让用户/策略能控制是否执行。

### 14.5 统一网络访问安全

建议抽 `SafeHttpClient`：

- 禁止 localhost、私网、link-local、metadata IP。
- DNS 解析后校验 IP。
- 限制 redirect 次数并对 redirect 目标重复校验。
- 流式下载并限制字节数。
- 统一 timeout、proxy、user-agent、重试。
- 所有 web/image/tex/provider fetch 走同一层。

### 14.6 统一错误语义

建议 `ToolResult.metadata.error` 标准化：

```json
{
  "error": {
    "type": "network_timeout | config_missing | validation_error | no_result | permission_denied",
    "message": "...",
    "retryable": true
  }
}
```

这样上层 observation 能告诉模型“换 query”还是“请用户配置 API key”，而不是把所有失败都当作 no result。

### 14.7 主 tools 与 TutorBot tools 的合并策略

建议不要直接硬合并。更稳的方案：

1. 先定义共同 `ToolDefinition`、`ToolContext`、`ToolResult`。
2. 主工具保留结构化 `ToolResult`。
3. TutorBot 工具通过 adapter 转成结构化结果。
4. filesystem/shell/MCP/team/message 归为 “environment tools”，默认不进入学习产品 chat。
5. DeepTutor 学习工具归为 “learning tools”，可进入 chat/solve/research。

## 15. 建议优先级

短期优先：

1. 修正 Chat `enabled_tools=None` 语义，或明确要求调用方总是传工具列表。
2. RAG 无 KB 时在 Chat 层也做和 DeepSolve 相同的禁用/跳过处理。
3. 把 RAG 描述改为“retrieved passages/context”，不要写 LLM-synthesised answer。
4. 修复 `question_extractor.py` 缺少 `import sys`。
5. 给 `code_execution` 增加 workspace 根目录校验。

中期优先：

1. 建立 `ToolContext`。
2. 建立 tool permission policy。
3. 统一错误类型。
4. 把 direct tool execution API 加权限/禁用危险工具开关。
5. 加 SafeHttpClient，替换 image/tex/web 的散装网络访问。

长期优先：

1. 使用真正隔离的代码执行环境。
2. 统一主 tools 与 TutorBot tools 的协议层。
3. 把辅助工具也纳入可观测性和审计日志。
4. 将工具 prompt hints、capability manifest、实际 registry 做一致性测试。
