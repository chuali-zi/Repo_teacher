# Repo Tutor 技术架构设计 v4

> 文档类型：当前实现架构报告  
> 面向读者：架构师、后端开发、前端开发、后续接手维护者  
> 对应产品文档：`docs/PRD_v5_agent.md`  
> 对应当前代码：`backend/` + `web/`  
> 日期：2026-04-19

## 1. 文档定位

这份文档不是“理想方案草图”，而是**针对当前仓库已落地实现**写的架构报告。目标有三个：

1. 说明系统现在到底由哪些模块组成，而不是沿用旧版文档里的历史模块想象。
2. 说明每个模块具体承担什么责任、依赖谁、输出什么、为什么这样实现。
3. 帮助新同学在不通读全部源码的前提下，先建立一张可靠的系统地图，再决定从哪里继续改造。

这份 v4 文档取代 v3 作为当前“技术架构口径”。如果 v3 与当前代码冲突，以 v4 和代码为准。

## 2. 当前架构一句话总结

Repo Tutor 当前是一个**只读源码教学 Agent**：后端负责建立仓库访问边界、扫描文件树、维护会话和教学状态、给 LLM 提供受控只读工具，并将结果通过 SSE 持续推送给前端；前端负责把这些状态与消息渲染成“提交仓库 -> 分析中 -> 教学对话”的连续体验。

这套系统现在有两条首轮报告路径：

- `quick_guide`：走 LLM + 工具调用的快速首轮报告。
- `deep_research`：对 Python 仓库走确定性的源码深研流水线，先做覆盖、笔记和章节综合，再生成长报告。

## 3. 架构目标与边界

### 3.1 核心目标

- 对仓库建立**只读、安全、可控**的访问边界。
- 让首轮报告和后续问答都尽量建立在**源码证据**上，而不是后台硬编码静态结论。
- 让会话状态、SSE 事件、前端渲染三者之间的契约保持稳定。
- 在不引入复杂基础设施的情况下，保留未来继续演进为更强 Agent 的空间。

### 3.2 明确不做的事

- 不执行仓库代码。
- 不安装仓库依赖。
- 不读取命中的敏感文件正文。
- 不把“猜测的入口、流程、分层”包装成确定事实。
- 不做多租户和分布式会话存储，当前仍是单活内存会话模型。

## 4. 系统总览

### 4.1 逻辑拓扑

```text
Browser (web/)
  -> REST / SSE
FastAPI (backend/main.py + routes/)
  -> Session orchestration (m5_session/)
  -> Repo access (m1_repo_access/)
  -> File-tree scan (m2_file_tree/)
  -> Deep research (deep_research/)
  -> Tool context + tool loop (llm_tools/, agent_tools/, agent_runtime/)
  -> Prompt / parsing / LLM transport (m6_response/)
  -> Sidecar explainer (sidecar/)
  -> Safety boundary (security/)
```

### 4.2 代码分层

```text
backend/
├── contracts/         # 领域模型、DTO、枚举、SSE 契约
├── routes/            # HTTP / SSE 路由层
├── security/          # 只读策略、路径边界、敏感模式
├── m1_repo_access/    # 仓库接入
├── m2_file_tree/      # 文件树扫描与过滤
├── deep_research/     # 深研模式首轮报告流水线
├── m5_session/        # 会话、状态机、工作流、教学状态、SSE 事件
├── agent_tools/       # 只读工具定义与执行
├── agent_runtime/     # 工具选择、上下文预算、工具调用循环
├── llm_tools/         # 对上层暴露的工具上下文门面
├── m6_response/       # Prompt、LLM 调用、解析、建议生成
├── sidecar/           # 辅助短解释能力
└── tests/             # 回归与契约测试

web/
├── index.html         # 页面骨架与模板
├── css/main.css       # 样式
└── js/                # API、状态、视图、插件、错误面板
```

## 5. 三条主运行链路

### 5.1 首轮快速报告链路

1. 前端调用 `POST /api/repo`，提交仓库路径或 GitHub URL，并默认指定 `analysis_mode=quick_guide`。
2. `m5_session.session_service` 创建会话，初始化进度步骤和空教学状态。
3. `m1_repo_access` 负责验证本地路径或执行 shallow clone。
4. `m2_file_tree` 扫描仓库、过滤敏感/忽略文件、识别语言和仓库规模。
5. `m5_session.teaching_service` 基于文件树初始化轻量教学计划、学生状态、教师工作日志。
6. `m6_response` 构造 Prompt，并通过 `agent_runtime.tool_loop` 让模型在首轮报告阶段也能调用只读工具。
7. LLM 输出正文和 `<json_output>` 侧车，后端解析后形成 `initial_report` 消息。
8. 前端通过 `/api/analysis/stream` 持续接收进度和流式文本，最终切入聊天视图。

### 5.2 深研首轮报告链路

1. 前端提交 `analysis_mode=deep_research`。
2. M1/M2 完成后，`AnalysisWorkflow` 判断仓库主语言是否为 Python。
3. 如果是 Python，系统进入 `deep_research/` 流水线：
   - 选择相关源码全集
   - 为每个文件生成 `ResearchPacket`
   - 聚合为 `ResearchNote`
   - 综合为章节级 `SynthesisNote`
   - 渲染超长 Markdown 报告，并回填压缩版 `initial_report_content`
4. 如果不是 Python，则深研模式降级为 `quick_guide` 首轮报告，同时保留降级标记和一致的前端进度反馈。

### 5.3 后续问答链路

1. 前端调用 `POST /api/chat`，提交用户问题。
2. `SessionService` 将用户消息写入会话，并把会话子状态切换到 `agent_thinking`。
3. `/api/chat/stream` 启动后，`ChatWorkflow` 构建本轮 Prompt。
4. `agent_runtime.context_budget` 先投喂必要工具结果，`tool_loop` 再按需触发 `search_text` / `read_file_excerpt` 等工具。
5. 模型生成回答，后端过滤掉侧车 JSON，只把正文流式发给前端。
6. 回答落库后，教学状态、历史摘要、建议问题、已解释主题引用一起更新。

## 6. 模块总图

| 模块 | 核心作用 | 上游 | 下游 |
| --- | --- | --- | --- |
| `contracts` | 定义领域模型和前后端契约 | 所有模块 | 所有模块 |
| `routes` | 提供 HTTP/SSE 入口 | `main.py` | `m5_session`、`sidecar` |
| `security` | 提供路径与敏感读取边界 | `m1`、`m2`、`agent_tools`、`deep_research` | 被动依赖 |
| `m1_repo_access` | 建立仓库访问上下文 | `m5_session` | `m2_file_tree` |
| `m2_file_tree` | 生成文件树快照和降级信号 | `m1` | `m5_session`、`agent_tools`、`deep_research` |
| `deep_research` | 生成深研首轮报告 | `m5_session`、`m2`、`security` | `m5_session` |
| `m5_session` | 管理会话、工作流、状态转移、SSE | `routes` | `m1`、`m2`、`deep_research`、`m6_response` |
| `agent_tools` | 定义只读工具 | `agent_runtime`、`m6_response` | `security`、`m2`、`m5` |
| `agent_runtime` | 选择工具、预算上下文、执行工具回路 | `m5`、`m6_response` | `agent_tools` |
| `llm_tools` | 暴露统一工具上下文门面 | `m5` | `agent_runtime` |
| `m6_response` | Prompt 构造、LLM 调用、解析 | `m5` | `agent_runtime`、`agent_tools` |
| `sidecar` | 短解释辅助接口 | `routes` | `m6_response` |
| `web` | 渲染 UI、连接 REST/SSE | 用户 | 后端 API |

## 7. 模块详解

## 7.1 `backend/contracts`

### 模块作用

`contracts` 是整个系统的**统一语言层**。它把“会话里有什么状态”“SSE 事件长什么样”“首轮报告和普通回答分别该带哪些字段”这些问题从实现里抽出来，变成可校验的 Pydantic 模型和枚举。

如果没有这一层，前端、路由、工作流、LLM 解析层就会各自维护自己的对象结构，最终导致状态错位、字段缺失或不同流程之间输出不一致。

### 模块要求

- 领域对象和前端 DTO 必须分层，不能把内部模型直接裸传给前端。
- 关键结构必须带模型校验，例如：
  - `MessageDto` 要校验 `initial_report` 与 `structured_content` 的互斥关系。
  - `SessionContext` 要校验不同 `status` 下允许保留哪些字段。
- 枚举值必须稳定，避免前端和 SSE 订阅端因为字面值改动而失效。

### 依赖关系

- 上游没有业务依赖，它是基础层。
- 下游几乎覆盖整个后端与前端契约：`routes`、`m5_session`、`m6_response`、`web` 都依赖它。

### 关键实现

- `domain.py` 存放领域模型，例如：
  - `RepositoryContext`
  - `FileTreeSnapshot`
  - `ConversationState`
  - `PromptBuildInput`
  - `InitialReportAnswer`
  - `SessionContext`
- `dto.py` 存放 API/SSE 对外结构，例如：
  - `SubmitRepoRequest`
  - `SessionSnapshotDto`
  - `AnalysisProgressEvent`
  - `MessageCompletedEvent`
- `enums.py` 提供全系统共享状态字面量，例如：
  - `AnalysisMode`
  - `SessionStatus`
  - `ProgressStepKey`
  - `MessageType`
- `sse.py` 负责把 Pydantic 事件编码成 SSE 文本流。

### 当前实现特点

- v4 架构里新增了 `AnalysisMode`、`DeepResearchRunState`、`DeepResearchStateDto` 等类型，专门承接深研模式。
- 旧版设计里遗留的很多“静态分析结构体”仍然保留在 `domain.py` 中，但当前运行时已经不再依赖 `m3/m4` 静态模块来填充它们。这意味着 `contracts` 比当前主链更宽，是为了兼容历史接口和后续演进。

## 7.2 `backend/routes`

### 模块作用

`routes` 只负责把 FastAPI 路由映射到会话服务或 sidecar 服务上，属于**非常薄的一层适配器**。它不做业务推理，不在路由里组织复杂状态，也不在这里拼装返回值细节。

### 模块要求

- 路由层必须保持薄，避免业务逻辑散落在控制器里。
- HTTP 错误和用户可见错误必须走统一封装。
- SSE 路由只负责建立流，不直接参与会话工作流。

### 依赖关系

- 上游：`backend.main`
- 下游：`m5_session.session_service`、`sidecar.explainer`
- 配套依赖：`contracts.dto`、`routes._errors`、`routes._sse`

### 关键实现

- `repo.py`
  - `POST /api/repo/validate`
  - `POST /api/repo`
  - 将 `analysis_mode` 直接传入 `session_service.create_repo_session`
- `session.py`
  - `GET /api/session`
  - `DELETE /api/session`
- `analysis.py`
  - `GET /api/analysis/stream`
  - 只建立分析 SSE，不自己跑分析逻辑
- `chat.py`
  - `POST /api/chat`
  - `GET /api/chat/stream`
- `sidecar.py`
  - `POST /api/sidecar/explain`

### 当前实现特点

- 路由层没有引入 service locator 或依赖注入框架，而是直接使用模块级 `session_service` 单例。
- 这种设计让本地运行和测试都更轻，但也意味着将来如果要做多会话池、持久化或多实例部署，需要先把这里抽象出来。

## 7.3 `backend/security`

### 模块作用

`security` 是当前系统里最重要的“底线模块”之一。它不负责业务价值，但负责确保系统在“只读源码教学”这个定位上不越界。

### 模块要求

- 所有文件访问都必须在 repo root 之内。
- 敏感文件只能“知道它存在”，不能读取内容。
- 工具和深研流水线都不能绕过路径安全检查。
- 忽略模式和敏感模式必须可以作为策略快照传入下游。

### 依赖关系

- 上游：`m1_repo_access`、`m2_file_tree`、`agent_tools.repository_tools`、`deep_research.pipeline`
- 下游没有业务依赖，它提供底层安全函数。

### 关键实现

- `build_default_read_policy()` 构建默认只读策略：
  - `read_only=True`
  - `allow_exec=False`
  - `allow_dependency_install=False`
- `assert_path_within_repo()` 和 `resolve_repo_relative_path()` 保证读取路径不会逃逸出仓库根目录。
- `match_repo_pattern()`、`suffix_candidates()` 支撑 `.gitignore` 和敏感模式匹配。

### 当前实现特点

- 当前安全边界主要围绕“路径越界”和“敏感文件正文读取”两类风险。
- 它不是通用沙箱，也不会拦截模型层面的胡乱表述；它负责的是**文件系统边界**，不是**认知边界**。

## 7.4 `backend/m1_repo_access`

### 模块作用

M1 负责把用户提交的“仓库输入”转换成一个可继续分析的 `RepositoryContext`。它解决的是“这个输入能不能当仓库读”“如果是 GitHub 仓库怎么变成本地可读目录”。

### 模块要求

- 同时支持本地绝对路径和公开 GitHub URL。
- 本地路径必须是绝对路径，禁止 `..` 越界。
- GitHub clone 必须是只读和轻量的，不能拉取整段历史。
- 不允许在这一层执行仓库代码或推断仓库内容。

### 依赖关系

- 上游：`m5_session.analysis_workflow`
- 下游：`m2_file_tree`
- 依赖：`security`、`contracts`、`git` CLI

### 关键实现

- `input_validator.py`
  - 识别输入属于 `local_path`、`github_url` 还是 `unknown`
  - 本地路径判断基于绝对路径特征
  - GitHub URL 使用正则校验 `https://github.com/owner/repo`
- `local_repo_accessor.py`
  - 进一步验证路径存在、是目录、可读取
  - 构建本地仓库版 `RepositoryContext`
- `github_repo_cloner.py`
  - 使用 `git clone --depth=1`
  - clone 到临时目录
  - 返回 `RepositoryContext + TempResourceSet`
- `__init__.py`
  - 对外暴露 `access_repository()`，统一分流本地和 GitHub 访问

### 当前实现特点

- 这一层不做 repo metadata 深度探测，例如默认分支、提交信息、远程状态都不处理。
- 它的目标不是“完整 Git 仓库接入”，而是“为后续只读分析拿到一个安全根目录”。

## 7.5 `backend/m2_file_tree`

### 模块作用

M2 负责把仓库根目录转换成一个结构化、可后续消费的**文件树快照**。这是当前系统最核心的基础事实来源之一，因为后续的工具、教学状态和深研选择都依赖这份快照。

### 模块要求

- 必须遍历仓库并输出稳定的节点列表。
- 必须把“正常文件 / 忽略文件 / 敏感文件 / 不可读文件”区分开。
- 必须输出语言统计和仓库规模分级。
- 规模过大时必须给出降级信号，而不是让下游无控制地全文扫描。

### 依赖关系

- 上游：`m1_repo_access`
- 下游：`m5_session`、`agent_tools`、`deep_research`
- 依赖：`security`

### 关键实现

- `tree_scanner.py`
  - 递归扫描目录
  - 为每个文件/目录生成 `FileNode`
  - 保存扩展名、节点深度、父路径、源文件标记等元数据
- `file_filter.py`
  - 叠加三类规则：
    - 内建 ignore 规则
    - 安全敏感规则
    - 仓库内 `.gitignore` 规则
  - 输出最终节点状态、命中的规则和敏感文件引用
- `language_detector.py`
  - 通过扩展名统计主语言和语言分布
- `repo_sizer.py`
  - 根据源码文件数量输出 `small / medium / large`
  - 大仓库时附带 `degraded_scan_scope`

### 当前实现特点

- M2 的输出已经不是“仅供 UI 展示”的树，而是后续几乎所有智能行为的基础输入。
- 它同时承担了事实建模和风险前置筛查两件事，所以实现里既有扫描逻辑，也有强约束过滤逻辑。

## 7.6 `backend/deep_research`

### 模块作用

`deep_research` 是 v4 架构中新引入的模块。它不负责通用聊天，也不参与后续问答；它只负责一件事：**为 Python 仓库生成超长、章节化、源码覆盖驱动的首轮研究报告**。

### 模块要求

- 必须先确定“相关源码全集”，而不是盲扫所有文件。
- 必须对未纳入首轮研究的文件给出 `skip_reason`。
- 必须跟踪研究进度、覆盖率、当前目标文件，供 SSE 和断线恢复使用。
- 必须输出两个层次的结果：
  - 面向前端展示的长 Markdown `raw_text`
  - 面向兼容逻辑的压缩版 `initial_report_content`

### 依赖关系

- 上游：`m5_session.analysis_workflow`
- 下游：回到 `m5_session` 作为 `InitialReportAnswer`
- 依赖：`m2_file_tree`、`security`、`contracts`

### 关键实现

- `source_selection.py`
  - 从 `FileTreeSnapshot` 中选择研究文件
  - 会纳入业务源码、关键配置、关键仓库文档
  - 会跳过测试、vendor、构建产物、生成文件、敏感文件和不可读文件
- `pipeline.py`
  - `build_research_run_state()` 初始化整体运行态
  - `build_research_packets()` 为每个文件生成研究包
  - `build_group_notes()` 按目录组装模块级研究笔记
  - `build_synthesis_notes()` 汇总成章节级综合笔记
  - `render_final_report()` 渲染最终 Markdown
  - `build_initial_report_answer_from_research()` 同时构造 `InitialReportAnswer`

### 当前实现特点

- 当前深研流水线是**确定性实现**，不是四次独立在线 LLM 协同。
- 它会对 Python 文件做 AST 解析，提取顶层函数、类、import 关系，用这些确定性素材生成研究结构。
- 深研状态通过 `DeepResearchRunState` 存在会话里，并通过 `analysis_progress` 事件里的 `deep_research_state` 实时推送给前端。
- 非 Python 仓库不会强行进入深研，而是显式降级到 quick guide。

## 7.7 `backend/m5_session`

### 模块作用

M5 是整个后端真正的**中控层**。如果说 `contracts` 解决的是“长什么样”，那 `m5_session` 解决的是“什么时候做什么、状态怎么流转、事件怎么发出去”。

### 模块要求

- 管理从 `idle -> accessing -> analyzing -> chatting` 的完整会话状态。
- 支持首轮分析与后续聊天两条工作流。
- 支持 SSE 断线重连。
- 支持错误恢复和 GitHub clone 临时目录清理。
- 把教学状态与消息状态统一到一个会话对象里。

### 依赖关系

- 上游：`routes`
- 下游：`m1_repo_access`、`m2_file_tree`、`deep_research`、`m6_response`
- 依赖：`contracts`、`security`

### 关键实现

- `session_service.py`
  - 模块级入口服务
  - 负责创建会话、读取快照、接收用户消息、启动分析或聊天工作流
- `analysis_workflow.py`
  - 负责首轮链路
  - 在 quick guide 与 deep research 之间分流
- `chat_workflow.py`
  - 负责后续问答链路
  - 维护 streaming 生命周期与超时控制
- `runtime_events.py`
  - 负责写入 `RuntimeEvent`
  - 提供状态切换、进度更新、活动记录、错误落地
- `event_mapper.py`
  - 把内部事件映射成对前端公开的 SSE DTO
- `event_streams.py`
  - 把“当前快照 + 可能的重连恢复 + 后续新事件”组合成 SSE 迭代器
- `reconnect_queries.py`
  - 定义断线恢复时应该回放哪些关键事件
- `repository.py`
  - 包装当前活动会话的内存存储和清理
- `state_machine.py`
  - 限制状态迁移合法性
- `teaching_service.py` 与 `teaching_state.py`
  - 维护教学计划、学生理解状态、教师工作日志和决策指令

### 当前实现特点

- 这一层采用**单活会话模型**，`SessionStore.active_session` 只维护一个活动会话。
- 优点是结构简单、便于本地调试、测试容易。
- 代价是它天然不是多用户服务端架构，如果要上远程部署，首先需要把这里改成持久化会话仓库。

## 7.8 `backend/m5_session.teaching_service` 与 `teaching_state`

### 模块作用

这部分不是“教学生成内容”，而是维护系统内部的**教学控制面**。它告诉模型当前用户大概在学什么、上一轮讲到了哪里、下一轮应该往哪个主题推进，以及哪些话题需要补强。

### 模块要求

- 教学状态必须服务于回答组织，但不能直接泄露到用户可见文本。
- 初始教学计划必须轻量，不能伪装成静态分析事实。
- 每轮回答后都要更新计划、学生状态和教师工作日志。
- 用户显式切换目标或深浅时，系统必须感知并反映到 Prompt。

### 依赖关系

- 上游：`analysis_workflow`、`chat_workflow`
- 下游：`m6_response.prompt_builder`
- 依赖：`llm_tools.build_llm_tool_context`

### 关键实现

- `build_initial_teaching_plan()`
  - 基于文件树初始化三个轻量步骤：建图、核实一个起点、继续按用户问题深挖
- `build_initial_student_learning_state()`
  - 为 overview、structure、entry、flow 等主题初始化理解状态
- `build_initial_teacher_working_log()`
  - 记录当前教学目标、为何现在讲这个、风险点和计划中的过渡
- `update_after_initial_report()` / `update_after_structured_answer()`
  - 回答后更新计划与学生状态
- `build_teaching_decision()` / `build_teaching_directive()`
  - 为 Prompt 提供“本轮该怎么讲”的控制对象

### 当前实现特点

- 这是当前系统里很有特色的一层：它既不是传统对话 history，也不是知识库，而是一个围绕“教学过程”组织的中间控制面。
- 这层越稳定，Prompt 越容易保持一致风格；但如果它膨胀过度，也会让系统过度复杂。

## 7.9 `backend/agent_tools`

### 模块作用

`agent_tools` 定义系统允许模型使用的**只读工具集合**。它解决的是“模型能查什么事实、通过什么参数查、返回什么格式”。

### 模块要求

- 工具必须是只读的。
- 工具返回必须结构化、可序列化、可裁剪。
- 工具名称必须能同时支持内部名字和 OpenAI function 名字。
- 对高频、确定性的工具结果要支持缓存。

### 依赖关系

- 上游：`agent_runtime`、`m6_response.tool_executor`
- 下游：`m2_file_tree`、`m5_session`、`security`

### 关键实现

- `base.py`
  - 定义 `ToolSpec`、`ToolContext`、`SeedPlanItem`
- `registry.py`
  - 注册全部工具，支持别名和 API 名归一化
- `analysis_tools.py`
  - 提供分析类工具：
    - `m1.get_repository_context`
    - `m2.get_file_tree_summary`
    - `m2.list_relevant_files`
    - `teaching.get_state_snapshot`
- `repository_tools.py`
  - 提供源码读取类工具：
    - `read_file_excerpt`
    - `search_text`
- `cache.py`
  - 提供 deterministic tool result cache
- `truncation.py`
  - 负责把超大工具结果裁剪到可注入 Prompt 的大小

### 当前实现特点

- 工具集刻意保持小而硬，不再暴露旧版里“直接返回静态结论”的分析工具。
- 当前工具层更像“源码证据接口”，而不是“结论接口”。

## 7.10 `backend/agent_runtime`

### 模块作用

`agent_runtime` 是“工具如何进入 Prompt、模型如何循环调用工具并继续回答”的运行层。它不定义工具，也不定义 Prompt 内容，但它决定模型是否能在有限预算里拿到足够证据。

### 模块要求

- 首轮和跟进问答都必须能根据场景选择合适工具。
- 工具上下文必须做预算控制，避免 Prompt 膨胀。
- 工具执行必须有超时、降级和活动事件。
- 当工具失败时，模型必须被明确要求“保守继续”。

### 依赖关系

- 上游：`m5_session`、`m6_response`
- 下游：`agent_tools`
- 依赖：`m6_response.budgets`

### 关键实现

- `tool_selection.py`
  - 决定当前回合把哪些函数 schema 暴露给模型
  - 当前最大工具数为 `5`
- `context_budget.py`
  - 先根据场景和学习目标生成种子工具计划
  - 再把工具结果裁剪进预算
  - 在需要时为用户问题准备 starter excerpts
- `tool_loop.py`
  - 管理工具调用循环
  - 支持活动事件、thinking notice、soft timeout、hard timeout、最终无工具收尾回合

### 当前实现特点

- 这层已经不是简单的“一次 prompt + 一次函数调用”，而是完整的小型 Agent loop。
- 但它依然是**保守版 Agent loop**：工具少、预算固定、超时硬、降级明确。

## 7.11 `backend/llm_tools`

### 模块作用

`llm_tools` 现在更像一个**门面层**。它的职责不是再实现一遍工具，而是把 `agent_runtime.context_budget` 和默认工具注册表包装成上层更容易调用的接口。

### 模块要求

- 对 `TeachingService` 提供稳定入口。
- 不重复造工具执行逻辑。
- 保持与历史调用方式兼容。

### 依赖关系

- 上游：`m5_session.teaching_service`
- 下游：`agent_runtime.context_budget`、`agent_tools.registry`

### 关键实现

- `build_llm_tool_context()` 直接转发到 `agent_runtime.context_budget.build_llm_tool_context()`
- `read_file_excerpt()` 和 `search_text()` 则作为门面调用默认工具注册表

### 当前实现特点

- 这个包本身不复杂，但它承接了旧架构到新工具化架构的过渡。
- 如果未来再做一轮架构清理，这一层有机会继续收薄，甚至并回更明确的 runtime/service 层。

## 7.12 `backend/m6_response`

### 模块作用

M6 负责“怎么跟 LLM 说”和“怎么把 LLM 回答变成系统内结构化对象”。它是模型交互层，不拥有仓库事实，但拥有输出组织规则。

### 模块要求

- Prompt 必须携带场景、教学指令、工具上下文和输出契约。
- 输出必须区分“可见正文”和“机器侧车 JSON”。
- 必须兼容普通流式回答和 function-calling 回答。
- 必须把模型输出解析成 `InitialReportAnswer` 或 `StructuredAnswer`。

### 依赖关系

- 上游：`m5_session`
- 下游：`agent_runtime`、`agent_tools`
- 依赖：`llm_config.json` 或环境变量

### 关键实现

- `prompt_builder.py`
  - 构造 system prompt 和完整 payload
  - 注入 teaching directive、tool context、history summary、output contract
  - 去除 root path、internal detail 等敏感字段
- `llm_caller.py`
  - 读取模型配置
  - 提供普通流式接口和带工具的流式接口
  - 兼容 OpenAI SDK 与 stdlib HTTP fallback
- `response_parser.py`
  - 从 `<json_output>` 中抽取结构化内容
  - 解析失败时提供 best effort fallback
- `sidecar_stream.py`
  - 在流式输出阶段把 `<json_output>` 从用户可见正文中剥掉
- `tool_executor.py`
  - 把模型请求的 function name 映射回工具注册表并执行
- `suggestion_generator.py`
  - 根据当前主题引用和教学状态生成后续问题建议
- `budgets.py`
  - 管理 output token budget 和 tool context budget

### 当前实现特点

- 当前首轮 quick guide 仍然依赖 LLM 来组织文本。
- 深研模式则不依赖 `prompt_builder` 去生成大报告正文，而是由 `deep_research` 直接构造最终 `InitialReportAnswer`。这意味着 M6 已经不再是所有首轮报告的唯一出口，而是“快速模式和后续问答的模型交互层”。

## 7.13 `backend/sidecar`

### 模块作用

`sidecar` 是一个非常小但很实用的旁路能力：当用户只问一句局部困惑时，它可以给出不依赖仓库上下文的超短解释。

### 模块要求

- 回答必须短。
- 不能假装自己看过仓库。
- 失败时要返回标准用户错误。

### 依赖关系

- 上游：`routes/sidecar.py`
- 下游：`m6_response.llm_caller.complete_llm_text`

### 关键实现

- `explainer.py`
  - 构建一个高度收敛的 system prompt
  - 将输出截断到 `120` 字以内
  - 不使用仓库上下文，也不使用工具

### 当前实现特点

- 这是一个典型的“旁路微能力”：不影响主链，却提升用户体验。
- 它和主 Agent 共用 LLM transport，但拥有完全不同的 prompt 约束。

## 7.14 `web`

### 模块作用

`web/` 是当前线上使用的前端实现。它不是 React 项目，而是一个**无构建步骤的原生 ES Modules 前端**，重点在轻量、调试方便、状态清晰。

### 模块要求

- 支持三态视图：输入、分析中、聊天。
- 支持 REST + SSE 联动。
- 支持消息流式更新，而不是整页重渲染。
- 出错时必须有显式调试信息，便于本地开发。

### 依赖关系

- 上游：浏览器
- 下游：FastAPI API

### 关键实现

- `main.js`
  - 启动应用
  - 恢复会话快照
  - 初始化插件和错误面板
- `state.js`
  - 维护全局状态
  - 状态结构与 `SessionSnapshotDto` 对齐
- `api.js`
  - 封装 REST 与 SSE
  - 在提交仓库时带上 `analysis_mode`
- `views.js`
  - 负责渲染输入页、分析页、聊天页
  - 处理 SSE 事件并更新本地状态
  - 深研模式下会展示专门的研究进度卡，并从报告标题生成目录
- `errors.js`
  - 永久在线错误面板
- `plugins.js`
  - 提供事件总线和轻量插件机制
- `dom.js`
  - 提供无框架的 DOM helper

### 当前实现特点

- 这套前端不是“设计系统驱动”的复杂 SPA，而是“状态机驱动”的工程型 UI。
- 它的核心价值不在复杂交互，而在把后端的状态、流式输出和调试信息准确呈现出来。

## 7.15 `backend/tests`

### 模块作用

测试不是运行时模块，但在当前仓库里，它承担了非常强的**契约保护**职责。很多设计不是靠注释维持的，而是靠测试保证的。

### 模块要求

- 契约改动必须同步更新测试。
- 路由、SSE、工具循环、深研模式都要有回归覆盖。

### 当前实现特点

- 现有测试覆盖了：
  - 路由与 envelope 契约
  - 会话工作流
  - 工具调用主链
  - Web 契约
  - Deep research 模式新增行为
- 因为当前系统高度依赖状态和事件顺序，测试的价值不仅是“防 bug”，更是“防架构漂移”。

## 8. 当前版本最重要的设计变化

### 8.1 历史上的 `m3 / m4` 已不再是当前运行时主链

旧文档里的 `m3` 静态分析引擎和 `m4` 教学骨架组装器，是更重、也更“后端先替模型下结论”的思路。当前主线已经切换到：

- M2 提供文件树事实
- `agent_tools` 提供只读证据接口
- M5/M6 让模型按需验证源码
- `deep_research` 只在首轮深研模式下走确定性长报告流水线

这意味着当前系统更保守，也更接近“证据优先”的运行哲学。

### 8.2 深研模式是首轮分析的专用支线，不是新的通用对话框架

`deep_research` 的定位非常明确：只负责首轮长报告。后续问答仍然回到原有聊天主链，这样可以避免把所有对话都拖进超重分析模式。

### 8.3 教学状态是当前系统的重要中间层

当前系统不是简单的 QA bot。它会显式维护“教到哪里”“学生对哪个主题可能没跟上”“下轮该从哪个角度继续讲”。这让体验更像带读，而不是纯检索。

## 9. 模块依赖拓扑

```text
contracts
  -> routes
  -> security
  -> m1_repo_access
  -> m2_file_tree
  -> deep_research
  -> m5_session
  -> agent_tools
  -> agent_runtime
  -> llm_tools
  -> m6_response
  -> sidecar

routes
  -> m5_session
  -> sidecar

m5_session
  -> m1_repo_access
  -> m2_file_tree
  -> deep_research
  -> llm_tools
  -> m6_response

llm_tools
  -> agent_runtime
  -> agent_tools

agent_runtime
  -> agent_tools
  -> m6_response.budgets

m6_response
  -> agent_runtime
  -> agent_tools

web
  -> routes exposed over HTTP/SSE
```

## 10. 当前架构的优点

- 分层清楚，后端主链已经形成稳定的“接入 -> 扫描 -> 状态 -> 工具 -> 模型 -> SSE”流程。
- 安全边界清晰，对路径越界和敏感文件做了强约束。
- 深研模式和快速模式能够并存，而不是互相污染。
- 前端很轻，联调速度快，排查问题成本低。
- 测试覆盖对架构约束的保护力度较高。

## 11. 当前架构的代价与风险

- `SessionStore` 还是单活内存模型，不适合多用户服务化。
- `contracts.domain.py` 很大，历史兼容对象和当前主链对象共存，理解成本高。
- `m5_session` 承担的职责较重，是当前系统最明显的中枢模块，也最容易继续膨胀。
- 深研模式当前是确定性流水线，还没有真正接入多角色 LLM 协同研究能力。
- `llm_tools` 与 `agent_runtime` 之间存在门面式重叠，后续仍有进一步收敛空间。

## 12. 后续演进建议

- 第一优先级：把会话存储从单活内存模型抽成可替换仓库层，为多会话和持久化做准备。
- 第二优先级：继续收敛 `contracts.domain.py`，把历史兼容对象与当前主链对象做更明确分区。
- 第三优先级：如果要继续做深研能力，优先补“多阶段模型角色配置”和“章节级证据引用策略”，而不是直接再把 prompt 拉长。
- 第四优先级：如果后续前端复杂度继续增长，再考虑从原生 ES Modules 迁移到有构建链的框架；当前阶段没有这个必要。

## 13. 结论

当前 Repo Tutor 的架构已经从“后端预先做大量静态结论，再让模型转述”转向了“后端建立事实边界和状态中枢，模型通过只读工具验证证据并组织教学表达”。这次 v4 架构最重要的增量，是把**深研首轮报告**明确抽成一条独立流水线，同时保留 quick guide 和后续聊天的轻量主链。

从维护角度看，最值得把握的不是单个函数细节，而是下面这条主逻辑：

**仓库访问边界 -> 文件树事实 -> 会话/教学状态 -> 工具化证据 -> LLM 组织回答 -> SSE 推送到前端。**

只要后续改动始终沿着这条链路保持边界清晰，系统就能继续演进，而不会退回到“代码能跑，但架构口径越来越乱”的状态。
