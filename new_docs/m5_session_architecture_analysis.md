# m5_session 架构解析

本文聚焦 `backend/m5_session/`，目标是回答 5 个问题：

1. m5 的架构边界是什么
2. m5 内部每个文件实际做什么
3. m5 在整个后端里的真实作用是什么
4. m5 的核心数据如何流动
5. m5 与上下游模块如何衔接

如果只先记一句话：

> `m5_session` 是整个后端的“会话编排中枢”。它不负责直接读仓库源码，也不直接实现 LLM 推理；它负责把仓库接入、文件树扫描、教学状态、聊天回合、SSE 事件、错误恢复和上下文拼接组织成一个可连续运行的单会话系统。

---

## 1. m5 的定位

从目录名看，`m5_session` 容易被误解成“只是一个 session 管理模块”。实际不是。

它至少同时承担了 6 类职责：

1. 管理全局唯一的活动会话
2. 驱动初始化分析流程和聊天回合流程
3. 维护教学导向的会话状态，而不只是消息历史
4. 维护状态机，保证前后端视图切换合法
5. 产出运行时事件，并把这些事件喂给 SSE
6. 负责断线重连时的最小恢复

所以 m5 更接近：

`Session Orchestrator + Teaching State Coordinator + Event Backbone`

而不是传统意义上的 `session CRUD service`。

---

## 2. m5 在整体后端中的位置

围绕 m5 的主链路可以压缩成下面这张图：

```text
HTTP Routes
  -> SessionService
     -> AnalysisWorkflow / ChatWorkflow
        -> TeachingService
           -> llm_tools.context_builder
              -> agent_runtime.context_budget
        -> m1_repo_access / m2_file_tree / deep_research / m6_response
     -> RuntimeEventService
        -> RuntimeEvent list on SessionContext
           -> ReconnectQueryService
              -> event_mapper
                 -> SSE DTO
                    -> frontend EventSource
```

这里最关键的是两点：

1. 路由层很薄，真正的应用逻辑集中在 m5。
2. m5 不自己完成所有工作，而是把 M1、M2、deep_research、M6、tool runtime 串成一个连续工作流。

---

## 3. 目录内各文件的实际职责

### 3.1 门面与总调度

#### `backend/m5_session/__init__.py`

- 导出全局单例 `session_service`
- 路由层几乎都通过它进入 m5

#### `backend/m5_session/session_service.py`

这是 m5 的门面，也是全系统最重要的编排入口。

核心职责：

- 创建新会话 `create_repo_session`
- 接收用户消息 `accept_chat_message`
- 提供快照 `get_snapshot`
- 清理会话 `clear_session`
- 启动初始化分析 `run_initial_analysis`
- 启动聊天回合 `run_chat_turn`
- 对外暴露重连查询和最近事件查询

它本身不深入实现分析和聊天，而是把工作下发给：

- `AnalysisWorkflow`
- `ChatWorkflow`
- `TeachingService`
- `RuntimeEventService`
- `SessionRepository`
- `ReconnectQueryService`

可以把它理解成 m5 的“应用服务根对象”。

### 3.2 两条主工作流

#### `analysis_workflow.py`

负责初次进入仓库后的整条初始化分析链。

它做的事情按顺序是：

1. 校验并接入仓库 `access_repository`
2. 切状态到 `analyzing`
3. 扫描文件树 `scan_repository_tree`
4. 识别降级条件，比如大仓库、非 Python
5. 初始化教学状态
6. 根据模式分支：
   - `DEEP_RESEARCH + Python` 走 `deep_research`
   - 否则走 LLM 初始报告生成
7. 生成 `InitialReportAnswer`
8. 把结果落为 `MessageRecord`
9. 切状态到 `chatting / waiting_user`
10. 产出 `message_completed` 事件

#### `chat_workflow.py`

负责后续每一轮聊天。

它做的事情按顺序是：

1. 要求当前状态必须是 `chatting / agent_thinking`
2. 用 `TeachingService.build_prompt_input()` 构造本轮 Prompt 输入
3. 切状态到 `chatting / agent_streaming`
4. 发出 `answer_stream_start`
5. 选择是否启用工具调用
6. 流式消费 LLM 输出
7. 去掉 `<json_output>...</json_output>` sidecar，只把可见正文流给前端
8. 解析出 `StructuredAnswer`
9. 生成最终 `MessageRecord`
10. 更新教学状态、历史摘要、已解释项
11. 切回 `chatting / waiting_user`
12. 发出 `message_completed`

### 3.3 教学状态与教学决策

#### `teaching_service.py`

这是 m5 最“业务化”的部分。

它不直接回答问题，而是负责把“当前用户想学什么、系统认为该怎么教、这轮该允许什么工具、输出应该长什么样”转换成 LLM 可消费的结构。

主要职责：

- 初始化教学状态
- 推断学习目标 `infer_learning_goal`
- 推断深度 `infer_depth_level`
- 推断场景 `infer_prompt_scenario`
- 构造 `PromptBuildInput`
- 构造 tool context
- 生成教学决策 `prepare_teaching_decision`
- 在回答后更新教学状态
- 维护历史摘要和建议列表
- 记录哪些 topic 已解释过

#### `teaching_state.py`

这是教学状态机的纯逻辑层。

它维护 3 套互相关联的数据：

1. `TeachingPlanState`
   - 系统计划带用户先看什么、后看什么
2. `StudentLearningState`
   - 系统对“用户理解到哪一步”的保守估计
3. `TeacherWorkingLog`
   - 当前教学目标、下一步过渡、风险提醒、近期决策

它还负责：

- 初始教学计划生成
- 初始学生状态生成
- 初始教师日志生成
- 初始报告后状态推进
- 普通回答后状态推进
- 根据状态构造 `TeachingDecisionSnapshot`
- 根据决策构造 `TeachingDirective`

这里体现了 m5 的一个关键设计：  
这个系统不是“纯聊天机器人”，而是“带教学策略的仓库阅读器”。

### 3.4 事件总线与恢复

#### `runtime_events.py`

`RuntimeEventService` 负责统一生成运行时事件。

它处理：

- 状态切换事件
- 进度步骤事件
- agent activity 事件
- degradation 事件
- error 事件
- 聊天回合失败/取消后的统一收尾

它的价值是把“内部流程变化”先规范化为 `RuntimeEvent`，而不是让每个 workflow 自己直接拼 SSE。

#### `event_mapper.py`

- 把内部 `RuntimeEvent` 映射成对外 `SseEventDto`
- 是 m5 内部事件模型到前端协议信封的转换层

#### `event_streams.py`

- SSE 迭代器入口
- 先处理断线重连补发
- 再决定是否真的启动分析或聊天 workflow

这意味着：

> 真正的分析和回答，不是在 `POST /api/repo` 或 `POST /api/chat` 里完成，而是在前端消费 SSE 流时才发生。

#### `reconnect_queries.py`

- 负责断线重连时挑出最小必要事件集
- 分析流重连：补状态、最后进度、最终完成/错误事件
- 聊天流重连：补状态、最后 agent activity，或最终完成/错误事件

### 3.5 存储与规则

#### `repository.py`

名字容易误导。这里不是代码仓库访问层，而是 **session repository**。

职责只有 4 类：

- 读取当前活动会话
- 校验 session id 是否匹配
- 清理活动会话
- 查询最近的关键运行时事件

#### `state_machine.py`

- 定义合法状态迁移
- 定义 `status -> client view` 的映射
- 限制只有 `chatting` 才允许 `sub_status`

#### `common.py`

- 时间戳
- id 生成
- 初始 progress steps
- 学习目标关键词映射

#### `errors.py`

- 统一生成用户可见错误对象
- 把内部异常翻译成 `UserFacingError`

---

## 4. m5 的核心对象模型

理解 m5，先看 6 个核心对象。

### 4.1 `SessionContext`

定义在 `backend/contracts/domain.py`。

它是 m5 的根状态容器，包含：

- `session_id`
- `status`
- `analysis_mode`
- `repository`
- `file_tree`
- `deep_research_state`
- `conversation`
- `last_error`
- `progress_steps`
- `active_degradations`
- `active_agent_activity`
- `runtime_events`
- `temp_resources`

可以把它理解成“单个会话的全部运行时事实”。

### 4.2 `ConversationState`

它不是普通聊天历史，而是“教学化对话状态”。

其中关键字段有：

- `current_learning_goal`
- `current_stage`
- `depth_level`
- `messages`
- `history_summary`
- `explained_items`
- `last_suggestions`
- `teaching_plan_state`
- `student_learning_state`
- `teacher_working_log`
- `current_teaching_decision`
- `current_teaching_directive`
- `sub_status`

所以 m5 的“会话”并不是简单的 `messages[]`，而是：

`消息历史 + 教学计划 + 学生理解估计 + 当前教学指令`

### 4.3 `PromptBuildInput`

这是 m5 输出给 m6 的核心输入对象。

它包含：

- `scenario`
- `user_message`
- `tool_context`
- `conversation_state`
- `history_summary`
- `depth_level`
- `output_contract`
- `enable_tool_calls`
- `max_tool_rounds`

换句话说，m5 的一个重要工作是把 `SessionContext` 压缩成一份 `PromptBuildInput`。

### 4.4 `MessageRecord`

这是会话内最终落地的消息。

它区分两类：

1. `INITIAL_REPORT`
   - 挂 `initial_report_content`
2. 普通 agent 消息
   - 挂 `structured_content`

这说明 m5 不只保存“原始文本”，还保存结构化语义结果。

### 4.5 `RuntimeEvent`

这是 m5 内部事件总线的标准载体。

支持的事件类型包括：

- `status_changed`
- `analysis_progress`
- `degradation_notice`
- `agent_activity`
- `answer_stream_start`
- `answer_stream_delta`
- `answer_stream_end`
- `message_completed`
- `error`

前端看到的 SSE，本质上都来自这里。

### 4.6 三套教学状态

这三套状态共同定义了 m5 的“教学大脑”：

- `TeachingPlanState`: 计划怎么带读
- `StudentLearningState`: 估计用户理解到哪里
- `TeacherWorkingLog`: 当前教学意图与风险记录

---

## 5. 初始化分析链的数据流

### 5.1 触发路径

```text
POST /api/repo
  -> SessionService.create_repo_session()
GET /api/analysis/stream
  -> event_streams.iter_analysis_events()
  -> SessionService.run_initial_analysis()
  -> AnalysisWorkflow.run()
```

### 5.2 详细步骤

#### 第 1 步：创建空会话

`create_repo_session()` 做的事情很有限：

- 校验输入是不是本地路径或 GitHub URL
- 清掉旧会话
- 建一个 `SessionContext`
- 初始状态设为 `ACCESSING`
- 初始化 `ConversationState`
- 初始化 `progress_steps`
- 如果是 GitHub 仓库，标记后续需要清理 clone 目录

这里 **不会真的分析仓库**。

#### 第 2 步：SSE 分析流启动真实分析

`iter_analysis_events()` 被消费后，才会真正调用 `run_initial_analysis()`。

这点很重要，因为整个系统采用的是：

`command by POST, execution by SSE stream consumption`

#### 第 3 步：仓库接入

`AnalysisWorkflow.run()` 首先调用：

```text
access_repository(input_value, read_policy)
```

产出：

- 新的 `RepositoryContext`
- `TempResourceSet`

此时 session 的 `repository` 和 `temp_resources` 被更新。

#### 第 4 步：切换到 analyzing

使用 `RuntimeEventService.transition_status()`：

- `ACCESSING -> ANALYZING`
- 追加 `STATUS_CHANGED` 事件

#### 第 5 步：扫描文件树

调用：

```text
scan_repository_tree(repository)
```

产出：

- `FileTreeSnapshot`

并回填到：

- `session.file_tree`
- `session.repository.primary_language`
- `session.repository.repo_size_level`
- `session.repository.source_code_file_count`

#### 第 6 步：判断降级

`maybe_create_degradation(file_tree)` 会在两种情况下打标：

1. 大仓库
2. 非 Python 主仓库

降级信息会写入：

- `session.active_degradations`
- `RuntimeEventType.DEGRADATION_NOTICE`

#### 第 7 步：初始化教学状态

`TeachingService.initialize_teaching_state(session)` 会生成：

- 初始教学计划
- 初始学生状态
- 初始教师工作日志
- 对应的教学 debug events

#### 第 8 步：生成初始报告

分两条路：

##### 路径 A：Deep Research

条件：

- `analysis_mode == DEEP_RESEARCH`
- `file_tree.primary_language == "Python"`

流程：

```text
build_research_run_state
-> build_research_packets
-> build_group_notes
-> build_synthesis_notes
-> build_initial_report_answer_from_research
```

##### 路径 B：LLM 初始报告

流程：

```text
TeachingService.build_initial_report_prompt_input()
-> build_llm_tool_context()
-> PromptBuildInput
-> stream_answer_text_with_tools() or stream_answer_text()
-> parse_answer()
-> InitialReportAnswer
```

这里有几个细节：

- 初始报告默认开启工具调用
- 输出流里的 `<json_output>` sidecar 不会原样传给前端
- m5 一边收流式文本，一边缓存完整原文用于解析结构化答案

#### 第 9 步：写入消息并进入聊天态

`_complete_initial_report()` 会：

- 生成 `MessageRecord`
- 挂到 `conversation.messages`
- 刷新 `last_suggestions`
- 切 `current_stage = INITIAL_REPORT`
- 更新教学状态
- 追加 `MESSAGE_COMPLETED`

随后整体状态变成：

```text
status = CHATTING
sub_status = WAITING_USER
```

---

## 6. 聊天回合链的数据流

### 6.1 触发路径

```text
POST /api/chat
  -> SessionService.accept_chat_message()
GET /api/chat/stream
  -> event_streams.iter_chat_events()
  -> SessionService.run_chat_turn()
  -> ChatWorkflow.run()
```

### 6.2 `accept_chat_message()` 做了什么

这个接口也不会立即生成答案。它只负责：

- 校验当前必须处于 `chatting / waiting_user`
- 记录一条 user `MessageRecord`
- 清理上一轮错误
- 切到 `chatting / agent_thinking`
- 写入一条 `AGENT_ACTIVITY` 事件

所以 `POST /api/chat` 的语义是：

`提交下一轮用户问题`

而不是：

`同步获得回答`

### 6.3 `ChatWorkflow.run()` 的执行链

```text
TeachingService.build_prompt_input(session)
  -> infer goal / depth / scenario
  -> prepare_teaching_decision()
  -> build_tool_context()
  -> build PromptBuildInput

PromptBuildInput
  -> m6.prompt_builder.build_messages()
  -> agent_runtime.tool_loop.stream_answer_text_with_tools()
  -> parse_answer()
  -> StructuredAnswer
```

### 6.4 聊天回合中 m5 的关键职责

#### 1. 判断这一轮“在教什么”

`TeachingService` 会推断：

- 学习目标是不是变了
- 深度是不是要切深/切浅
- 是普通追问、目标切换、深度调整，还是阶段总结

#### 2. 生成教学决策和教学指令

`prepare_teaching_decision()` 会基于当前状态生成：

- `TeachingDecisionSnapshot`
- `TeachingDirective`

这些对象控制模型回答的方式，例如：

- 先答用户当前问题
- 最多展开几个新点
- 必须锚定证据
- 不要暴露内部 teaching state
- 不要无谓重复之前的解释

#### 3. 构造工具上下文

`build_tool_context()` 最终调用 `agent_runtime.context_budget.build_llm_tool_context()`。

它会：

- 根据学习目标和场景选工具
- 预执行一些确定性 seed tools
- 按预算裁剪 tool results
- 在用户问题明显需要源码时自动补 starter excerpts

因此 m5 送给模型的不是“空 prompt”，而是“带预装证据包的 prompt”。

#### 4. 执行 tool-aware LLM loop

如果 `enable_tool_calls=True`，就走：

```text
stream_answer_text_with_tools()
```

这个循环会：

- 传入选中的函数 schema
- 允许多轮 tool call
- 并发执行工具
- 记录 `planning_tool_call / tool_running / tool_succeeded / tool_failed / slow_warning`
- 工具失败时要求模型保守继续
- 达到工具轮数上限后强制 no-tool 收尾

#### 5. 收尾并回写状态

回答完成后，m5 会：

- 解析 `StructuredAnswer`
- 生成 agent `MessageRecord`
- 记录已解释项 `record_explained_items`
- 更新教学状态
- 更新历史摘要
- 清空 `active_agent_activity`
- 回到 `waiting_user`

---

## 7. 事件流与 SSE 的关系

这是 m5 另一个核心价值。

### 7.1 内部先产出 RuntimeEvent

无论是：

- 状态切换
- 分析步骤推进
- agent 正在思考
- 工具正在运行
- 文本增量
- 最终消息完成
- 错误

都先变成 `RuntimeEvent`，追加到 `session.runtime_events`。

### 7.2 再映射成 SSE DTO

流程是：

```text
RuntimeEvent
-> runtime_event_to_sse()
-> SseEventDto
-> contracts.sse.encode_sse_stream()
-> text/event-stream
```

这样做的好处是：

1. workflow 不需要知道前端协议细节
2. 断线重连可以基于已记录事件做恢复
3. `/api/session` 快照与 SSE 共享同一套底层状态

### 7.3 断线重连不是重新执行全流程

`ReconnectQueryService` 的策略是：

- 先补一个状态快照事件
- 再补最后一个关键进度/活动/终态事件
- 只有在流程确实还没结束时，才继续跑 workflow

所以重连语义更接近：

`先补状态，再决定是否续跑`

而不是：

`每次重连都从头再分析一次`

---

## 8. m5 与上下游关系

## 8.1 上游：谁调用 m5

直接上游主要是路由层。

### `routes/repo.py`

- `POST /api/repo/validate` -> `validate_repo_input`
- `POST /api/repo` -> `create_repo_session`

### `routes/analysis.py`

- `GET /api/analysis/stream` -> `iter_analysis_events`

### `routes/chat.py`

- `POST /api/chat` -> `accept_chat_message`
- `GET /api/chat/stream` -> `iter_chat_events`

### `routes/session.py`

- `GET /api/session` -> `get_snapshot`
- `DELETE /api/session` -> `clear_session`

因此，前端看到的大部分会话行为，最终都汇入 `SessionService`。

## 8.2 下游：m5 调用谁

### 仓库接入与扫描

- `backend.m1_repo_access.access_repository`
- `backend.m2_file_tree.tree_scanner.scan_repository_tree`

### 深度研究分支

- `backend.deep_research.*`

### 工具上下文和工具执行

- `backend.llm_tools.context_builder`
- `backend.agent_runtime.context_budget`
- `backend.agent_runtime.tool_selection`
- `backend.agent_runtime.tool_loop`

### 回答生成与解析

- `backend.m6_response.answer_generator`
- `backend.m6_response.prompt_builder`
- `backend.m6_response.response_parser`
- `backend.m6_response.sidecar_stream`

### 安全与错误

- `backend.security.safety`
- `backend.m5_session.errors`

### 领域对象与外部协议

- `backend.contracts.domain`
- `backend.contracts.dto`
- `backend.contracts.enums`

---

## 9. m5 的真实作用

如果从业务结果倒看，m5 的实际作用不是“保存会话”，而是：

### 9.1 把一次仓库教学拆成两个阶段

1. 初始分析阶段
2. 持续追问阶段

并保证两个阶段共用同一个上下文和教学状态。

### 9.2 把“教学策略”从 Prompt 拼装里抽出来

`TeachingService + teaching_state.py` 让系统能够：

- 知道当前在讲什么
- 控制下一轮讲什么
- 保守估计用户理解程度
- 让回答既跟着用户走，又不完全失去带读节奏

### 9.3 把模型输出改造成“可恢复的流式产品行为”

如果没有 m5，系统只会剩下：

- 接收问题
- 调 LLM
- 返回文本

有了 m5，系统才有：

- 进度条
- thinking/tool activity
- 结构化消息
- 断线重连
- 错误恢复
- 会话快照

### 9.4 把多个后端模块装配成一个产品闭环

m5 是以下模块的装配层：

- M1: 仓库接入
- M2: 文件树扫描
- deep_research: 深度首轮报告
- M6: Prompt/LLM/解析
- agent_runtime: tool loop

没有 m5，这些模块只是零散能力；有了 m5，它们才成为“可交互教学流程”。

---

## 10. 数据流总图

### 10.1 初始化分析流

```text
user input repo
-> SessionService.create_repo_session
-> SessionContext(status=accessing)
-> GET /api/analysis/stream
-> AnalysisWorkflow.run
-> access_repository
-> RepositoryContext + TempResourceSet
-> scan_repository_tree
-> FileTreeSnapshot
-> TeachingService.initialize_teaching_state
-> PromptBuildInput / deep_research inputs
-> InitialReportAnswer
-> MessageRecord(initial_report)
-> update teaching states
-> RuntimeEvent(message_completed)
-> SessionContext(status=chatting, sub_status=waiting_user)
```

### 10.2 聊天回合流

```text
user question
-> accept_chat_message
-> MessageRecord(user_question)
-> sub_status=agent_thinking
-> GET /api/chat/stream
-> ChatWorkflow.run
-> TeachingService.build_prompt_input
-> infer goal/depth/scenario
-> build teaching_decision + teaching_directive
-> build_llm_tool_context
-> PromptBuildInput
-> tool loop / llm
-> StructuredAnswer
-> MessageRecord(agent_answer)
-> update explained_items + teaching states + history_summary
-> RuntimeEvent(message_completed)
-> sub_status=waiting_user
```

### 10.3 事件流

```text
workflow state change
-> RuntimeEventService
-> SessionContext.runtime_events
-> ReconnectQueryService
-> event_mapper
-> SSE event DTO
-> frontend
```

---

## 11. 设计特征与边界

### 11.1 单活动会话

`SessionStore` 里只有一个 `active_session`。  
这不是多会话架构，而是单会话、内存态架构。

### 11.2 无持久化

会话、消息、事件、教学状态都在内存中。  
进程重启后会话直接消失。

### 11.3 分析和回答都由 SSE 驱动

这是 m5 最容易被忽略的实现特征。

- `POST /api/repo` 不分析仓库
- `POST /api/chat` 不生成回答

真正工作都发生在对应的 stream 被消费时。

### 11.4 教学状态是第一等公民

系统不仅保留 messages，还保留：

- plan
- student state
- teacher log
- decision
- directive

这决定了 m5 的核心抽象不是“聊天”，而是“教学化的代码阅读”。

### 11.5 m5 不直接操作源码

m5 自己不读文件内容，不做搜索，不拼 AST，不直接连 LLM API。  
它把这些动作下发给下游模块，然后组织结果。

---

## 12. 对 m5 的一句准确评价

`m5_session` 不是一个辅助模块，而是当前后端的主心骨。

它把：

- 仓库接入
- 文件树分析
- 教学策略
- Prompt 输入
- Tool 调用
- 流式输出
- 断线恢复
- 错误处理

统一收敛到一个单会话编排层里。

如果以后要重构后端，m5 是最不能只看文件名、也最不能用“session 管理器”这种过轻标签来理解的模块。它实际上定义了整个产品的运行时交互模型。
