# 后端聊天数据流与教学退化分析

本文专门追踪当前后端里“聊天主线”相关代码，目标不是再写一份目录综述，而是回答两个更具体的问题：

1. 一条聊天消息从 `POST /api/chat` 到 SSE 回流前端，中间真实经过了哪些对象、状态和函数。
2. 为什么当前 agent 明明会多轮工具调用，却仍然容易产出“像 README 一样的宏观废话”，而不是落到源码证据上的教学内容。

本文基于当前仓库代码与本地实测，重点覆盖这些文件：

- `backend/routes/chat.py`
- `backend/routes/session.py`
- `backend/m5_session/session_service.py`
- `backend/m5_session/chat_workflow.py`
- `backend/m5_session/event_streams.py`
- `backend/m5_session/event_mapper.py`
- `backend/m5_session/runtime_events.py`
- `backend/m5_session/teaching_service.py`
- `backend/m5_session/teaching_state.py`
- `backend/m5_session/common.py`
- `backend/contracts/domain.py`
- `backend/contracts/dto.py`
- `backend/llm_tools/context_builder.py`
- `backend/agent_runtime/context_budget.py`
- `backend/agent_runtime/tool_selection.py`
- `backend/agent_runtime/tool_loop.py`
- `backend/agent_tools/analysis_tools.py`
- `backend/agent_tools/repository_tools.py`
- `backend/m6_response/prompt_builder.py`
- `backend/m6_response/llm_caller.py`
- `backend/m6_response/response_parser.py`
- `backend/m6_response/tool_executor.py`
- `backend/m5_session/analysis_workflow.py`

## 1. 结论先行

当前聊天链路的核心形态是：

`路由收消息 -> SessionContext 改状态 -> ChatWorkflow 生成 PromptBuildInput -> 工具上下文预置 -> LLM/tool loop 多轮调用 -> visible text + json sidecar -> parse -> 更新教学状态与会话 -> RuntimeEvent -> SSE`

真正导致回答变成“README 风格宏观空话”的，不是单一 prompt 写得差，而是多处机制叠加：

1. 用户问题经常没有被识别成 `flow / entry / module` 这类需要看源码的问题，而是默认落回 `overview`。
2. 一旦落到 `overview`，可选工具就通常只有 `m2.list_relevant_files` 和 `search_text`，连 `read_file_excerpt` 都不给。
3. 即使进入工具循环，预置上下文仍主要是文件树、相关文件列表、教学状态，而不是源码片段。
4. prompt 里对“教学控制”“输出格式”“JSON sidecar”的要求很多，但对“必须先拿到哪些源码证据才能作答”没有硬门槛。
5. 结构化解析和教学状态更新对低质量答案过于宽容，空泛回答也能被当作“这轮已经讲过了”。
6. 历史摘要保留的是可见文本摘要，不是证据链，上一轮的空话会成为下一轮的上下文。

所以表面上看是“模型做了很多轮工具调用但还是很笨”，实质上更接近：

`问题意图路由错误 + 工具选择偏表层 + 证据绑定缺失 + 状态推进过宽松`

## 2. 关键数据对象

### 2.1 `SessionContext`

聊天主状态容器在 `backend/contracts/domain.py` 中定义。它把一次会话的关键运行态都放在一个内存对象里：

- `status`：整体会话状态，如 `accessing / analyzing / chatting`
- `conversation`：对话内状态
- `repository`：当前仓库元数据
- `file_tree`：扫描后的文件树快照
- `active_agent_activity`：当前 agent 活动提示
- `runtime_events`：供 SSE 回放与断线重连的事件日志
- `last_error`：当前轮失败信息

这不是一个“聊天消息列表”对象，而是一个“单会话运行时快照”。

### 2.2 `ConversationState`

`ConversationState` 不只是存消息历史，还存教学导向状态：

- `current_learning_goal`
- `current_stage`
- `depth_level`
- `explained_items`
- `last_suggestions`
- `history_summary`
- `teaching_plan_state`
- `student_learning_state`
- `teacher_working_log`
- `current_teaching_decision`
- `current_teaching_directive`
- `sub_status`

也就是说，聊天回答不是简单的“读取消息 -> 调 LLM -> 回答”，而是显式地夹带了一个教学控制面。

### 2.3 `PromptBuildInput`

`PromptBuildInput` 是 M5 到 M6 的桥接载体，里面包含：

- `scenario`
- `user_message`
- `tool_context`
- `conversation_state`
- `history_summary`
- `depth_level`
- `output_contract`
- `enable_tool_calls`
- `max_tool_rounds`

M6 不直接读取 `SessionContext`，而是吃这个中间对象。

### 2.4 `LlmToolContext`

`LlmToolContext` 由两部分组成：

- `tools`：本轮允许被模型调用的函数 schema
- `tool_results`：在真正进 tool loop 之前就预塞进去的参考结果

这个设计意图是让模型在“还没调用工具之前”先看到一批只读材料。

### 2.5 `StructuredAnswer`

聊天回合最终要求落成 `StructuredAnswer`：

- `structured_content.focus`
- `structured_content.direct_explanation`
- `structured_content.relation_to_overall`
- `structured_content.evidence_lines`
- `structured_content.uncertainties`
- `structured_content.next_steps`
- `related_topic_refs`
- `used_evidence_refs`

前端看到的是 `raw_text`，但系统内部判断“这一轮讲了什么”的主要依据其实是这个结构化对象。

### 2.6 `RuntimeEvent`

整个聊天 SSE 流不是直接发字符串，而是发 `RuntimeEvent` 转出来的 DTO：

- `STATUS_CHANGED`
- `AGENT_ACTIVITY`
- `ANSWER_STREAM_START`
- `ANSWER_STREAM_DELTA`
- `ANSWER_STREAM_END`
- `MESSAGE_COMPLETED`
- `ERROR`

这意味着前端消费到的是“事件流”，不是“最终整包回答”。

## 3. 主调用链

### 3.1 聊天入口其实分成两段

聊天不是一个 HTTP 请求里完成的，而是两段式：

1. `POST /api/chat`
2. `GET /api/chat/stream?session_id=...`

对应代码在 `backend/routes/chat.py`：

- `send_message()` 只负责调用 `session_service.accept_chat_message(...)`
- `chat_stream()` 才真正触发 `iter_chat_events(session_id)`

所以 `POST /api/chat` 只是“写入用户消息并把状态切到 thinking”，真正生成回答是在 SSE 被消费时发生。

### 3.2 `accept_chat_message()` 只做状态推进，不做回答生成

`backend/m5_session/session_service.py` 中的 `accept_chat_message()` 主要做这些事：

1. 校验 session id 和当前状态是否允许发消息。
2. 新建一条 `MessageRecord(role=user, message_type=user_question)` 追加到 `conversation.messages`。
3. 清空上次错误。
4. 把 `conversation.sub_status` 切到 `AGENT_THINKING`。
5. 填一个 `active_agent_activity`，摘要类似“正在理解你的问题”。
6. 记录一个 `AGENT_ACTIVITY` runtime event。
7. 返回 `chat_stream_url` 给前端。

这里没有任何 LLM 调用。

### 3.3 `GET /api/chat/stream` 才会跑 `ChatWorkflow`

`backend/m5_session/event_streams.py` 的 `iter_chat_events()` 做了三件事：

1. 先吐出断线重连需要补发的历史事件。
2. 如果已经到了 `MESSAGE_COMPLETED` 或 `ERROR`，直接结束。
3. 如果当前状态仍是 `status=chatting && sub_status=agent_thinking`，才调用 `session_service.run_chat_turn(session_id)`。

也就是说，SSE 是真正的执行触发器。

## 4. 从用户消息到 PromptBuildInput

### 4.1 `ChatWorkflow.run()` 是聊天主线核心

`backend/m5_session/chat_workflow.py` 的主流程是：

1. 取 session。
2. 检查当前是否处于 `chatting + agent_thinking`。
3. 调 `teaching.build_prompt_input(session)`。
4. 先切状态到 `AGENT_STREAMING`。
5. 发 `ANSWER_STREAM_START`。
6. 决定走普通 LLM 流还是带工具的 tool loop。
7. 一边收 chunk 一边发 `ANSWER_STREAM_DELTA`。
8. 流结束后拼出原始文本 `raw_text`。
9. 调 `parse_answer(prompt_input, raw_text)`。
10. 把解析后的结果写回 `conversation.messages`。
11. 更新 teaching state、history summary、last suggestions。
12. 切回 `WAITING_USER`。
13. 发 `MESSAGE_COMPLETED`。

### 4.2 `TeachingService.build_prompt_input()` 在这里做了“意图路由”

聊天质量好坏，第一关其实不是模型，而是 `build_prompt_input()`：

- `infer_learning_goal(session, user_text)`
- `infer_depth_level(current_depth, user_text)`
- `infer_prompt_scenario(user_text)`
- `prepare_teaching_decision(...)`
- `build_tool_context(...)`

这个阶段会决定：

- 本轮到底算 `overview / entry / flow / module / layer / dependency / summary`
- 本轮深度是 `default / deep / shallow`
- 这是不是一次 `goal_switch / depth_adjustment / stage_summary`

如果这里路由错了，后面的工具选择和 prompt 方向都会跟着错。

### 4.3 当前意图路由很容易把复杂链路问题打回 `overview`

学习目标推断依赖 `backend/m5_session/common.py` 里的 `GOAL_KEYWORDS`。

当前关键词覆盖面偏窄：

- `ENTRY`：入口、启动、`main`、`app`、`route`
- `FLOW`：流程、调用链、请求、数据流、`flow`
- `MODULE`：模块、文件、类、函数、`module`
- `LAYER`：分层、架构、层、`layer`
- `STRUCTURE`：结构、目录、先看哪里、阅读顺序

但用户常见的真实表达并不只这些，例如：

- 聊天主线
- 调用路径
- 链路
- 数据怎么走
- 从 route 到 tool loop 到 parser
- backend chat pipeline

本地实测当前仓库上，问题：

`追踪后端代码的与聊天的聊天主线，为什么 agent 的回答像 README 一样空泛？`

在 `build_prompt_input()` 之后的结果是：

- `current_learning_goal = overview`
- `scenario = follow_up`
- `focus_topics = ['overview', 'structure']`
- `turn_goal = "Answer the question while staying aligned with 建立仓库整体地图."`

这会把本该沿调用链追代码的问题，路由成“先讲仓库整体地图”的高层讲解。

## 5. 从 PromptBuildInput 到真正发给模型的消息

### 5.1 `build_tool_context()` 先做一轮只读预置

`TeachingService.build_tool_context()` 调的是 `backend/llm_tools/context_builder.py`，再下钻到 `backend/agent_runtime/context_budget.py`。

这里会先构造一批预置 tool results，而不是直接裸 prompt。

对于 follow-up 问题，默认的 seed plan 大致是：

- `m1.get_repository_context`
- `teaching.get_state_snapshot`
- 视 goal 决定是否加 `m2.get_file_tree_summary`
- 视 goal 决定是否加 `m2.list_relevant_files`
- 如果 `needs_source_tools(user_text)` 返回 true，再额外塞 starter excerpts

问题在于：这个 starter excerpt 触发条件很脆。

### 5.2 当前问题经常拿不到任何源码 excerpt

本地实测当前仓库，对问题：

`追踪后端代码的与聊天的聊天主线，为什么 agent 的回答像 README 一样空泛？`

构造出的 seeded tool results 是：

- `m1.get_repository_context`
- `teaching.get_state_snapshot`
- `m2.get_file_tree_summary`
- `m2.list_relevant_files`

没有：

- `read_file_excerpt`
- starter excerpts

也就是说，模型在开始作答前看到的是：

- 仓库元信息
- 文件树摘要
- 相关文件列表
- 教学状态

它还没看到任何真正的源码片段。

### 5.3 工具选择也会受 goal 路由影响

`backend/agent_runtime/tool_selection.py` 的规则是：

- 默认总会给 `m2.list_relevant_files` 和 `search_text`
- 只有当 goal 属于 `ENTRY / FLOW / MODULE / DEPENDENCY / LAYER`，才额外给 `read_file_excerpt`
- 或者 `needs_source_tools(user_text)` 返回 true，才补给 `read_file_excerpt`

对上面的真实问题，本地实测得到的可用工具只有：

- `m2.list_relevant_files`
- `search_text`

没有 `read_file_excerpt`。

这意味着模型哪怕进入多轮 tool loop，也只能：

- 列相关文件
- 搜关键词

却不能直接读文件片段。

这已经足够解释“为什么它会讲成 README 概览”：因为系统根本没有把它推到“必须读源码片段后再答”的轨道上。

### 5.4 `build_messages()` 的 prompt 负载偏重控制信息

`backend/m6_response/prompt_builder.py` 会把 system message 拼成几大块：

1. `_SYSTEM_RULES`
2. scenario/depth 说明
3. teaching directive 相关约束
4. tool calling guidance
5. strict output requirements
6. JSON sidecar schema
7. 一个大的 JSON payload

这个 payload 又包含：

- `scenario`
- `user_message`
- `depth_level`
- `history_summary`
- `teacher_memory`
- `teaching_directive`
- `output_contract`
- `conversation_state`
- `tool_context`

本地测量当前仓库：

- 一个 follow-up 架构问题的 system prompt 大约 `8826` 个字符
- 初始报告场景的 system prompt 大约 `10989` 个字符

而这些字符里很大一部分不是源码证据，而是：

- 教学控制信息
- 输出合同
- 工具列表
- 预置状态

所以模型在进入回答前，认知重心更像是在“遵守一个复杂对话协议”，而不是“先把代码链路读穿”。

## 6. tool loop 如何工作

### 6.1 总入口

`backend/agent_runtime/tool_loop.py` 的 `stream_answer_text_with_tools()` 是多轮工具调用主循环。

流程大致是：

1. `build_messages(input_data)`
2. `select_tools_for_prompt_input(input_data)`
3. 进入 while loop
4. 调 `tool_streamer(messages, tools=active_tool_schemas, ...)`
5. 如果模型先吐文本，就边流式发边记录
6. 如果模型返回 `tool_calls`，则规范化后执行
7. 把 tool result 作为 `role=tool` 消息追加到 `messages`
8. 再要求模型继续
9. 到达工具轮数上限后，强制进入 final no-tool round

### 6.2 tool loop 的事件是先写入 runtime event，再映射成 SSE

tool loop 内部并不直接管前端，而是通过 `on_activity` 回调把状态写成 `AGENT_ACTIVITY`。

例如会发出：

- `thinking`
- `slow_warning`
- `planning_tool_call`
- `tool_running`
- `tool_succeeded`
- `tool_failed`
- `waiting_llm_after_tool`
- `degraded_continue`

这些再经过：

- `RuntimeEventService.record_agent_activity()`
- `event_mapper.runtime_event_to_sse()`

最后成为前端能看的 agent activity 提示。

### 6.3 工具执行本身是保守的

真正的工具执行在 `backend/m6_response/tool_executor.py`，背后调用 `DEFAULT_TOOL_REGISTRY`。

当前对聊天主线有效的工具主要是：

- `m1.get_repository_context`
- `m2.get_file_tree_summary`
- `m2.list_relevant_files`
- `teaching.get_state_snapshot`
- `read_file_excerpt`
- `search_text`

其中真正能提供源码证据的只有：

- `read_file_excerpt`
- `search_text`

但 `search_text` 给的是命中行片段，不是函数级上下文；`read_file_excerpt` 又经常因为意图路由没选中而根本不给。

### 6.4 多轮工具调用并不等于高质量讲解

当前系统把“发生了多轮工具调用”当成一种过程努力，但没有把“工具证据必须渗透到最终解释”做成强校验。

tool loop 只保证：

- 工具被调了
- 结果被回填到 message 列表了

它不保证：

- 回答引用了哪些工具结果
- 回答是否真的使用了读到的代码
- 回答的 `evidence_refs` 是否和工具结果可对齐

所以完全可能出现：

`多轮搜索 / 多轮列文件 -> 最终仍用高层概括收尾`

## 7. 从模型文本到内部结构化答案

### 7.1 `ChatWorkflow` 同时收集两份文本

在 `backend/m5_session/chat_workflow.py` 中：

- `raw_chunks`：完整原始流，包括 `<json_output>...</json_output>`
- `visible_chunks`：经 `JsonOutputSidecarStripper` 去 sidecar 后的可见文本

最终：

- `raw_text = ''.join(raw_chunks).strip()`
- `visible_text = ''.join(visible_chunks)`

然后：

- `parse_answer(prompt_input, raw_text)` 用完整文本做结构化解析
- 但存入 message 的 `raw_text` 是 `visible_text`

这解释了为什么前端和内部结构化状态并不完全是同一份内容。

### 7.2 `parse_final_answer()` 对低质量输出过于宽容

`backend/m6_response/response_parser.py` 的策略是“尽量解析，解析不了也构出一个对象”，而不是“结构不合格就拒收”。

如果缺少有效 sidecar，会发生这些 fallback：

- `focus` 取首行
- `direct_explanation` 直接用 visible text
- `relation_to_overall` 填默认句子
- `evidence_lines` 填 fallback evidence line
- `uncertainties` 填 fallback uncertainty
- `next_steps` 可能为空

这让系统几乎总能得到一个 `StructuredAnswer`，哪怕内容并不真的达标。

### 7.3 “必须锚定证据”只是软约束，不是硬检查

虽然 `TeachingDirective` 里有：

- `must_anchor_to_evidence = True`

但这是 prompt 文本约束，不是程序检查。

程序侧没有做这些验证：

- `used_evidence_refs` 是否非空
- `evidence_refs` 是否真实对应某次工具结果
- `direct_explanation` 是否落到了具体文件/函数/行号
- 回答是否包含至少一个源码 excerpt 的可验证信息

因此模型完全可能生成一个“看起来格式正确、实际上没证据”的答案。

## 8. 从结构化答案回写教学状态

### 8.1 结构化答案一旦生成，就会驱动状态推进

`ChatWorkflow.run()` 在成功解析后会做几件关键回写：

- `ensure_answer_suggestions(session, answer)`
- `record_explained_items(session, answer, message_id)`
- `update_teaching_state_after_answer(...)`
- `update_history_summary(session)`

这里最关键的是：教学状态会把这一轮当作“已经完成的教学动作”。

### 8.2 学生状态会被更新，即使回答其实很空

`backend/m5_session/teaching_state.py` 里，`update_after_structured_answer()` 的逻辑是：

- 如果 `related_topic_refs` 为空，就退回 `conversation.current_learning_goal`
- 然后 `_mark_topics(...)`

也就是说，只要成功解析成 `StructuredAnswer`，哪怕没有真实 topic ref，也会默认“本轮覆盖了当前 goal”。

本地实测，用一个完全空泛的回答：

`这是一个很宏观的回答，没有真正落到源码。`

经过 `parse_final_answer()` 后再喂给 `update_teaching_state_after_answer()`，得到的结果是：

- `evidence_ref_count = 0`
- `_answer_is_too_uncertain(answer) = False`
- 当前 topic 的 `coverage_level` 被更新成 `introduced`

这意味着系统会把“空泛回答”也记成“这个主题已经讲过一轮了”。

### 8.3 `_answer_is_too_uncertain()` 的门槛过高

当前“不确定到不能推进计划”的判定是：

1. `evidence_ref_count == 0`
2. `uncertainties` 里还得包含特定关键词，例如“证据不足 / 无法确认 / 不确定 / unknown”

但 parser 的 fallback uncertainty 文案并不稳定命中这些词。

结果就是：

- 没证据
- 但也没触发“太不确定”
- 于是教学状态仍然继续推进

这会让系统不断累积一种错误信念：

`虽然回答质量一般，但教学主线已经往前走了一步`

## 9. 为什么它会产出“README 式宏观废话”

下面按因果链展开。

### 9.1 问题先被错分到 `overview`

很多用户真实想问的是：

- 调用链
- 数据流
- 主线
- 从 route 到 workflow 到 parser 怎么走

但当前 `GOAL_KEYWORDS` 很难稳定识别这些表述，导致 `current_learning_goal` 留在 `overview`。

一旦是 `overview`，回答目标自然会偏向：

- 建立仓库地图
- 讲目录职责
- 给阅读路径建议

这就是 README 风格输出的第一推动力。

### 9.2 错误 goal 会直接收窄工具集

`overview` 场景下通常拿不到 `read_file_excerpt`。

没有 `read_file_excerpt`，模型就很难：

- 顺着函数实现讲
- 逐层追调用链
- 解释具体状态流转

它最多能：

- 列文件
- 搜关键词

所以只能高层总结。

### 9.3 预置上下文更像“元信息包”而不是“证据包”

seeded tool results 里占大头的是：

- 仓库元信息
- teaching state snapshot
- 文件树摘要
- 相关文件列表

这些都对“建立整体地图”有帮助，但对“解释 chat 主线如何在代码里流动”帮助有限。

真正需要的是：

- `routes/chat.py`
- `session_service.py`
- `chat_workflow.py`
- `teaching_service.py`
- `tool_loop.py`
- `prompt_builder.py`
- `response_parser.py`

这些文件的关键 excerpt。

当前系统没有把这些 excerpt 作为此类问题的默认证据。

### 9.4 prompt 把注意力分散到了协议遵循

当前模型同时要处理：

- 教学角色约束
- 输出合同
- JSON sidecar
- tool calling guidance
- teaching directive
- history summary
- tool context

这会让模型在有限注意力里优先学会：

- 回答要像老师
- 需要有几个 section
- 要输出 JSON
- 要保守表达不确定性

但不一定优先学会：

- 为了回答这个问题，先把哪几个源码文件读透

于是就出现一种典型产物：

- 结构规整
- 口吻像老师
- 术语很多
- 但没有代码链路密度

### 9.5 tool loop 没有“证据闭环”

当前架构只实现了：

- `模型可以调工具`
- `工具结果会被回填`

但没有实现：

- `最终回答必须引用工具得到的具体证据`
- `如果没形成证据闭环，就拒绝完成`

换句话说，系统保证了“做过事”，没有保证“做过的事进了答案”。

### 9.6 parser 和 teaching state 会把低质量回答也纳入正反馈

这一步尤其关键。

因为当前逻辑是：

- 只要能 parse 成 `StructuredAnswer`
- 就更新 student state
- 就更新 history summary
- 就让系统认为本轮完成了某种教学覆盖

于是空泛回答不会被系统识别为“失败样本”，反而会被当作正常教学推进。

这会产生连续多轮退化：

1. 第一轮讲空
2. 系统认为这个 topic 已介绍
3. 历史摘要也记下这轮空话
4. 下一轮模型继续基于这份高层摘要往下说
5. 整个对话越来越像“概览叠概览”

### 9.7 next-step 建议缺少确定性兜底

仓库里其实存在两个兜底建议生成器：

- `backend/m5_session/teaching_state.py -> plan_based_suggestions()`
- `backend/m6_response/suggestion_generator.py -> generate_next_step_suggestions()`

但当前聊天主线并没有真正把它们接到失败兜底路径上。

`ensure_answer_suggestions()` 只是截断 suggestion 数量，不会在模型没给出好建议时补全。

这意味着：

- 如果模型没产出好 `next_steps`
- 系统也不会基于当前教学计划自动兜底

结果是对话缺少强引导，只剩高层解释。

### 9.8 当前运行模型也是风险放大器

从 `llm_config.example.json` 与本地 `llm_config.json` 看，当前默认/实际配置是：

- `base_url = https://api.deepseek.com`
- `model = deepseek-chat`

这意味着系统依赖一个通用聊天模型同时完成：

- 多轮工具调用
- 长 system prompt 遵循
- 中文教学口吻
- 结构化 sidecar 输出
- 保守不确定性表达

这不是代码里的直接 bug，但它会放大上述架构问题。

这里的判断属于运行时推断，不是单靠源码就能证明的绝对结论；但结合当前 prompt 复杂度，它是一个合理的次级风险项。

## 10. 对“聊天主线”的精确数据流图

```text
User
  -> POST /api/chat
     -> routes/chat.send_message
        -> SessionService.accept_chat_message
           -> append user MessageRecord
           -> sub_status = AGENT_THINKING
           -> append RuntimeEvent(AGENT_ACTIVITY)
           -> return chat_stream_url

Frontend EventSource
  -> GET /api/chat/stream?session_id=...
     -> routes/chat.chat_stream
        -> event_streams.iter_chat_events
           -> SessionService.run_chat_turn
              -> ChatWorkflow.run
                 -> TeachingService.build_prompt_input
                    -> infer goal / depth / scenario
                    -> prepare teaching decision + directive
                    -> build tool context
                       -> context_budget.build_llm_tool_context
                          -> seed tool results
                          -> choose callable tools
                 -> RuntimeEvent(STATUS_CHANGED: AGENT_STREAMING)
                 -> RuntimeEvent(ANSWER_STREAM_START)
                 -> agent_runtime.tool_loop.stream_answer_text_with_tools
                    -> prompt_builder.build_messages
                    -> llm_caller.stream_llm_response_with_tools
                    -> [0..N rounds]
                       -> tool_executor.execute_tool_call
                       -> append role=tool messages
                    -> stream visible deltas
                 -> JsonOutputSidecarStripper
                 -> response_parser.parse_final_answer
                 -> append agent MessageRecord
                 -> update teaching state / history summary
                 -> RuntimeEvent(STATUS_CHANGED: WAITING_USER)
                 -> RuntimeEvent(MESSAGE_COMPLETED)
           -> event_mapper.runtime_event_to_sse
              -> SSE DTO
                 -> frontend render
```

## 11. 修复优先级建议

### P0：先修“意图路由 -> 工具集”这条链

建议直接扩展或重写 goal routing，不要再只靠静态关键词：

- 增加这些高频表达：`主线`、`链路`、`调用路径`、`数据怎么走`、`route 到 ...`、`pipeline`、`workflow`
- 对包含 `route / workflow / parser / tool loop / session / stream / sse` 的问题优先路由到 `FLOW`
- 当用户问题显式要求“追踪代码”“调用链”“数据流”时，强制给 `read_file_excerpt`

不解决这一层，后面调 prompt 只会继续头痛医头。

### P0：为链路问题预置源码 excerpt，而不是只给文件列表

对架构/链路类问题，应在 seed plan 中直接预置 2 到 4 个 excerpt：

- `routes/chat.py`
- `m5_session/session_service.py`
- `m5_session/chat_workflow.py`
- `agent_runtime/tool_loop.py`

这会把模型从“看文件名猜结构”直接推到“看代码讲链路”。

### P0：把“证据闭环”改成硬门槛

至少增加两个程序检查：

1. follow-up 回答若 `used_evidence_refs` 为空且 `read_file_excerpt/search_text` 本轮被调用过，则标记为低质量输出。
2. 若 `direct_explanation` 中不包含任何具体文件/函数/状态对象，而问题又是链路类问题，则不推进教学状态。

### P0：低质量回答不能推进 student state

当前 `update_teaching_state_after_answer()` 太宽松，建议改成：

- 没有有效 evidence refs
- 或没有 topic refs
- 或 parser 走了 fallback

则：

- `coverage_level` 不升级
- `teaching_plan` 不推进
- `history_summary` 不写入或降权写入

### P1：压缩 prompt 中的元控制信息

建议减少 system prompt 里的教学元信息，把 prompt 重心重新拉回源码证据：

- teaching state snapshot 只保留最小字段
- history summary 做更强裁剪
- tool_context 里的文件列表长度收紧
- JSON schema 尽量缩短

### P1：真正接上 suggestion fallback

当模型不给 `next_steps` 或给出明显空话时，应该使用：

- `plan_based_suggestions()`
- 或 `generate_next_step_suggestions()`

做 deterministic fallback，而不是直接留空。

### P2：补一类专门防“README 式空话”的回归测试

建议新增行为测试：

- 输入“追踪聊天主线 / 数据流 / route 到 parser 怎么走”
- 断言 goal 被路由到 `FLOW`
- 断言可用工具里包含 `read_file_excerpt`
- 断言 seeded tool results 含至少一个源码 excerpt
- 断言回答中出现具体文件名与状态对象
- 断言无有效 evidence 时 student state 不推进

## 12. 最终判断

当前 agent 看起来“像个笨蛋机器人”，并不是因为它不会调工具，而是因为系统把它训练成了一个更擅长：

- 维护教学姿态
- 遵守结构化输出
- 讲仓库整体地图

却没有强制它在关键问题上：

- 正确识别为链路问题
- 主动读取关键源码
- 用证据驱动解释
- 在没有证据时拒绝推进教学状态

所以现象才会是：

`tool calls 很多`，但 `教学信息密度仍然很低`

如果只改 prompt 文案，这个问题不会根治。真正该动的是：

`意图路由 -> 工具可用性 -> seed 证据 -> 输出验收 -> 状态推进`

这五个环节。
