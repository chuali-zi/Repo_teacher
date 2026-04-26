# Repo_teacher 现有实际架构和主要问题架构

分析时间：2026-04-22  
分析范围：`backend/` 现有公开源码、README 运行时说明、`new_docs/PRD_v6_teaching_first.md`。  
说明：本文件描述“当前实际架构是什么”以及“为什么这个架构天然会产生不讲课、复述 README、过早证据分析”的问题。

## 1. 当前后端的实际产品形态

当前后端表面上叫 Repo Tutor / Repo Teacher，但实际运行时更接近：

```text
安全仓库读取器 + 文件树索引器 + 会话状态 + LLM 证据型回答生成器
```

它的优点是保守、安全、可控：不直接执行仓库代码，不把不确定的入口/流程/依赖说成事实，工具只读，并要求源码证据。

它的缺点也来自同一个方向：它没有把仓库加工成“教材”，而只是把仓库加工成“可检索材料”。因此 LLM 面对的主要输入是文件树、README 摘要、相关文件列表、少量源码片段、教学状态快照。模型输出自然偏“仓库分析报告”，而不是“老师讲课”。

## 2. 顶层模块结构

README 和 `backend/` 目录显示，当前后端主要模块包括：

```text
backend/
  main.py
  routes/
  contracts/
  m1_repo_access/
  m2_file_tree/
  m5_session/
  m6_response/
  agent_tools/
  agent_runtime/
  deep_research/
  llm_tools/
  security/
  sidecar/
  tests/
```

按职责理解：

| 模块 | 当前职责 | 对“老师感”的贡献 | 当前不足 |
|---|---|---|---|
| `main.py` / `routes` | FastAPI 应用与路由注册 | 提供 API/SSE 入口 | 不是问题核心 |
| `m1_repo_access` | 仓库访问、校验、基本上下文 | 给出仓库基本信息 | 不产生教学结构 |
| `m2_file_tree` | 文件树扫描、摘要、相关文件列表 | 给 LLM 导航材料 | 容易诱导文件树复述 |
| `m5_session` | 会话、教学状态、prompt input、chat workflow | 负责“教学状态”的入口 | 状态语义太粗，计划太轻 |
| `m6_response` | prompt 构造、LLM 调用、响应解析 | 决定 Agent 说什么 | prompt/contract/schema 仍 evidence-first |
| `agent_tools` | 工具注册与源码读取工具 | 支撑真实性 | 工具偏取证，不偏课程组织 |
| `agent_runtime` | 工具选择、工具循环、上下文预算 | 控制 LLM 如何查证 | 工具循环天然导向证据收集 |
| `deep_research` | 深度分析雏形 | 可成为 skeleton 来源 | 与正式教学状态未充分打通 |

## 3. 当前初始化流程

根据 README 的运行时说明，初始流程可以概括为：

```text
POST /api/repo
  -> M1：校验并建立 RepositoryContext
  -> M2：扫描文件树，建立 FileTreeSnapshot
  -> M5：建立轻量 Session / TeachingState
  -> M6：构造 initial report prompt
  -> agent_runtime：允许工具调用读取仓库材料
  -> M6：解析初始报告
  -> 前端展示
```

关键点是：M5 初始化的教学计划来自文件树，并不是来自 repo teaching skeleton。`build_initial_teaching_plan` 的实际语义是：

```text
1. 先建立仓库整体地图
2. 再核实第一个源码起点
3. 再沿用户关心的问题继续深挖
```

这是一条“读仓库流程”，不是“课程设计”。它没有回答：

- 这个仓库最值得先教哪个点；
- 为什么这个点适合第一轮；
- 哪个源码锚点能最小成本讲清它；
- 本轮讲到什么程度算完成；
- 下一个自然教学点是什么。

所以首轮很容易变成“这个仓库由 backend、frontend、new_docs 组成……”这类结构概览。

## 4. 当前 follow-up 聊天流程

实际 follow-up 流程大致是：

```text
/api/chat 或 /api/chat/stream
  -> 保存用户消息
  -> TeachingService.build_prompt_input(session)
       -> 推断 goal/depth/scenario
       -> build_teaching_decision
       -> build_teaching_directive
       -> build_llm_tool_context
       -> build_output_contract
  -> ChatWorkflow.run
       -> ANSWER_STREAM_START
       -> stream_answer_text_with_tools 或 stream_answer_text
       -> 边收到 delta 边向前端发送 ANSWER_STREAM_DELTA
       -> 流结束后 parse_answer
       -> ensure_answer_suggestions
       -> record_explained_items
       -> update_teaching_state_after_answer
       -> update_history_summary
       -> ANSWER_STREAM_END / completion events
```

这个流程中最重要的问题是：**可见答案在质量检查之前就已经流给用户了。**

也就是说，如果模型一开始就复述 README，或者开始列证据，后端没有机会拦截并重写。解析器和状态更新只能在事后处理。

## 5. 当前工具上下文架构

### 5.1 seed context

`context_budget.py` 会把一些工具结果预先塞进 prompt。初始报告默认包括：

```text
m1.get_repository_context
m2.get_file_tree_summary
m2.list_relevant_files(limit=60)
teaching.get_state_snapshot
```

follow-up 则通常包括：

```text
m1.get_repository_context
teaching.get_state_snapshot
```

如果当前目标是 overview/structure，会追加文件树摘要和相关文件；如果目标是 entry/flow/module，会追加相关文件列表。

这种设计的实际效果是：模型每一轮都能看到“仓库上下文 + 状态快照 + 文件树/相关文件”。这能保证它不会完全脱离仓库，但也会不断把它拉回“仓库结构复述”。

### 5.2 可选工具

`tool_selection.py` 的候选工具主要是：

```text
m2.list_relevant_files
search_text
read_file_excerpt（初始报告、entry/flow/module/dependency/layer 或用户问源码时追加）
```

这些工具的共同点是：它们都回答“证据在哪里”。它们不回答“应该怎样教”。

因此工具循环的内在动作是：列文件 -> 搜索 -> 读片段 -> 证据总结。它缺少：

```text
teaching.get_repo_skeleton
teaching.get_current_turn_plan
teaching.get_topic_card
teaching.get_anchor_pack
teaching.get_covered_points
m3.get_entry_candidates
m3.get_candidate_flows
m3.get_module_cards
```

没有这些工具，LLM 即使愿意讲课，也没有高质量的课程材料。

## 6. 当前 prompt 架构

`prompt_builder.py` 的核心由几部分组成：

```text
system rules
scenario guidance
teaching_directive
tool guidance
strict output requirements
JSON schema
payload
```

### 6.1 system rules 的实际导向

系统规则中确实写了“像老师一样回答”“每轮只讲少量核心点”“给下一步”。但是更强、更具体的规则是：

- 优先文件树、源码工具、教学状态和用户问题；
- 入口、流程、分层、依赖没有源码证据只能说候选/未知；
- 给轻量阅读建议，不要给事实性固定顺序；
- 要在 Markdown 后输出 `<json_output>`。

这会使模型形成“保守证据助理”的行为，而不是“主动老师”的行为。

### 6.2 teaching_directive 太薄

默认 directive 的语义大致是：

```text
turn_goal: Answer current question with source-grounded repository evidence
mode: answer
focus: current learning goal
answer_user_first: true
allowed_new_points: 1 or 2
must_anchor_to_evidence: true
avoid_repeating: recent explained items
```

这个对象缺少教学轮次计划的核心字段：

```text
current_teaching_point
why_now
teaching_depth
source_anchors
teaching_moves
must_explain_design_reason
must_explain_system_role
next_teaching_point
quality_constraints
```

所以它只能约束“不乱说”，不能驱动“讲得像老师”。

### 6.3 strict output requirements 与 PRD v6 不匹配

当前 strict output requirements 要求：

- 自然覆盖 contract parts；
- 核心点数量受限；
- 标记不确定性；
- 输出 1-3 个可点击下一步；
- 不要填充语。

问题是，它没有强制：

- 本轮必须讲透一个点；
- 必须解释为什么现在讲；
- 必须解释这个点在系统中的角色；
- 必须有设计意图/职责关系解释；
- 证据只占辅助比例；
- next step 必须是一个教学子点；
- 读完文件后不能只总结文件。

结果就是“答得谨慎但不像老师”。

## 7. 当前输出 contract 架构

`TeachingService._build_output_contract` 要求 follow-up 可见回答覆盖以下部分：

```text
FOCUS
DIRECT_EXPLANATION
RELATION_TO_OVERALL
EVIDENCE
UNCERTAINTY
NEXT_STEPS
```

这是一种“结构化分析报告”的 contract，而不是“自然讲课”的 contract。

PRD v6 要求这些维度可以存在，但不能强制作为可见固定模块。可见输出应该更像：

```text
这一轮我们先讲 X。
它值得先讲，是因为 Y。
你可以把它理解成 Z。
在这个仓库里，它通过 A/B 两个源码锚点体现出来。
设计上它承担的是 M 职责，不承担 N 职责。
所以你后面读代码时，先抓住这个判断。
下一步自然接：Q。
```

而不是：

```text
本轮重点：...
直接解释：...
与整体关系：...
证据：...
不确定项：...
下一步建议：...
```

当前 contract 把 Evidence 和 Uncertainty 抬到了与 Explanation 同等的位置，所以模型容易“进入证据分析”。

## 8. 当前响应解析与状态更新架构

`response_parser.py` 会做三类解析：

1. 优先解析 `<json_output>`；
2. 如果缺字段，从固定标题中抽取；
3. 如果还失败，用 fallback 从 visible_text 推断 direct_explanation、evidence_lines 等。

这个设计很宽容，但对教学状态有副作用。

### 8.1 direct_explanation fallback 的问题

如果没有结构化 payload，解析器可能把整段 visible_text 作为 direct_explanation。这样状态层会以为“本轮有直接解释”，即使这段话只是文件树摘要。

### 8.2 evidence fallback 的问题

如果没有 evidence lines，解析器可能从可见文本中 fallback 生成 evidence。这样会把普通描述误判成“有证据支撑”。

### 8.3 状态更新的连锁问题

`teaching_state.py` 后续会根据 answer 的结构化内容、related_topic_refs、evidence_count、不确定性等更新计划。由于解析器把弱回答也包装成结构化回答，状态就可能产生：

```text
用户觉得没讲懂
系统状态却认为该点已经讲过
下一轮跳走或重复另一个结构概览
```

这就是多轮教学断裂的根因之一。

## 9. 当前 streaming 架构

`ChatWorkflow.run` 的关键顺序是：

```text
创建 answer_stream
for item in answer_stream:
  如果是文本 delta：
    raw_chunks.append(chunk)
    sidecar_stripper.feed(chunk)
    yield ANSWER_STREAM_DELTA 给前端
流结束后：
  raw_text = join(raw_chunks)
  parse_answer(prompt_input, raw_text)
  更新会话状态
```

`agent_runtime/tool_loop.py` 中，LLM 的 content delta 也会立即进入 queue 并 yield 出去。

这意味着质量控制是在用户看到之后才发生。PRD v6 要求的“内容丰富度自检”在这种架构里只能成为事后记录，不能成为输出前保障。

如果要真正让 Agent 稳定像老师，至少教学型回答应改为：

```text
LLM draft
  -> parse structured payload
  -> quality gate
  -> 如果失败，带失败原因重写一次
  -> 只 stream 最终可见答案
```

## 10. 当前主要问题架构图

### 10.1 当前正向链路

```text
README / file tree / repo context
        │
        ▼
M1 + M2 生成仓库访问与文件树材料
        │
        ▼
M5 基于 file_tree_only 生成轻量教学计划
        │
        ▼
M6 Prompt: evidence-first + fixed output sections
        │
        ▼
Agent tools: list/search/read excerpt
        │
        ▼
LLM 可见回答：结构概览 + 证据 + 不确定项 + next_steps
        │
        ▼
Parser 宽松 fallback
        │
        ▼
TeachingState 误以为某些点已解释
```

### 10.2 问题反馈回路

```text
缺少教学骨架
  -> 首轮只能讲文件树/README
  -> Parser 把弱回答当 direct_explanation
  -> State 记录“已讲过”
  -> 下一轮 directive 避免重复但没有新课程点
  -> 模型继续找证据/列建议
  -> 用户感觉“不像老师”
```

### 10.3 证据过强回路

```text
系统规则强调源码证据和候选/未知
  -> 工具只提供 list/search/read
  -> output contract 要 Evidence/Uncertainty
  -> 模型把证据作为主体
  -> 教学正文比例下降
  -> 回答像审计报告
```

### 10.4 streaming 质量失控回路

```text
LLM 生成 token
  -> 立即发给前端
  -> 结束后才 parse
  -> parse 失败或质量差也已经被用户看到
  -> 无法自动重写
```

## 11. 当前架构中“最危险的错觉”

### 错觉 1：工具轮数越多，老师越强

错误。工具轮数只增加证据量，不自动增加教学组织能力。没有 TeachingTurnPlan，读 20 个文件也可能只是列 20 个证据。

### 错觉 2：只要 prompt 写“像老师”，就会像老师

错误。模型会被更具体的 contract、tool context、schema、状态更新牵引。当前更具体的牵引是证据和不确定性。

### 错觉 3：不提供后端推断就更安全

只对一半。完全不提供候选骨架会安全但无教学。正确做法是提供候选骨架，并把每个候选都绑定 evidence_refs、confidence、unknowns。

### 错觉 4：固定栏目能保证教学完整

固定栏目能保证“有栏目”，不能保证“讲懂”。而且固定 Evidence/Uncertainty 会破坏自然课堂感。

### 错觉 5：解析器越宽容越稳

对用户可见回答来说宽容可能稳；对教学状态来说宽容会污染状态。状态更新应该宁可缺失，也不要把弱文本误判为讲透。

## 12. 与 PRD v6 的逐项冲突

| PRD v6 要求 | 当前架构表现 | 冲突性质 |
|---|---|---|
| 教学内容是主体 | Evidence/Uncertainty 是固定可见部分 | 直接冲突 |
| 首轮落到一个具体点 | 初始计划先整体地图 | 直接冲突 |
| 每轮一个教学点讲透 | max_core_points + fixed sections 易多点浅讲 | 直接冲突 |
| 下一步是一个教学子点 | next_steps 是 1-3 个问题/动作 | 直接冲突 |
| 少量源码锚点 | list relevant files 可返回几十项 | 容易冲突 |
| 证据不吞正文 | output_contract 抬高证据地位 | 直接冲突 |
| 多轮连续课堂 | 状态基于粗 goal 和 parser fallback | 能力不足 |
| 内容丰富度自检 | 无输出前质量门 | 缺失 |
| 不把教学维度硬化成模板 | 固定 sections | 直接冲突 |

## 13. 当前架构可保留边界

虽然问题明显，但不建议推倒所有模块。合理保留如下：

```text
M1：继续负责 repo access，不做教学结论。
M2：继续负责 file tree 和文件候选，但输出要成为 skeleton 的输入。
agent_tools：继续只读、安全、可审计。
agent_runtime：继续保留工具调用、超时、活动事件，但增加教学工具。
M5：继续作为会话与教学状态中枢，但升级状态语义。
M6：继续负责 LLM prompt/answer/parser，但改成 v6 teacher generator。
```

真正要变的是中间缺失的“教学材料层”和“教学轮次控制层”：

```text
M3 RepoTeachingSkeletonBuilder
M4 TeachingTopicGraph / CurriculumBuilder
M5 TeachingTurnPlanner
M6 QualityGate + TeacherAnswerGenerator
```

## 14. 最小修复版架构

如果短期不想大改，可先做最小修复：

```text
TeachingService
  -> 生成 current_teaching_point / why_now / next_teaching_point
  -> output_contract 去掉固定 Evidence/Uncertainty 可见栏目
PromptBuilder
  -> 教学正文优先，证据最多 2 条
  -> next_teaching_point 必须单一
ResponseParser
  -> 不再从 visible_text fallback evidence/direct_explanation 更新状态
ChatWorkflow
  -> 非流式生成草稿，质量门通过后再 stream
```

这能明显改善“像老师”的程度，但仍不如完整 M3/M4。

## 15. 完整目标架构预览

完整架构应为：

```text
M1 RepoAccess
   │
M2 FileTree + SourceCatalog
   │
M3 RepoTeachingSkeletonBuilder
   │    ├─ ProjectProfile
   │    ├─ EntryCandidates
   │    ├─ ImportSourceSummary
   │    ├─ ModuleCards
   │    ├─ CandidateFlows
   │    └─ Unknowns / EvidenceRefs
   │
M4 TeachingTopicGraph
   │    ├─ TeachingPointCards
   │    ├─ Prerequisite relations
   │    └─ Recommended first lesson
   │
M5 TeachingTurnPlanner
   │    ├─ current point
   │    ├─ why now
   │    ├─ source anchors
   │    ├─ depth / teaching moves
   │    └─ one next point
   │
M6 TeacherAnswerGenerator
   │    ├─ minimal source verification
   │    ├─ teaching-first draft
   │    ├─ evidence compression
   │    ├─ quality gate
   │    └─ final visible teaching answer
```

这就是下一份“更改方案”文档中展开的内容。
