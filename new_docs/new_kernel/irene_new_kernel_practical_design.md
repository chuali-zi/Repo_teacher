# Irene `new_kernel` 实际设计建议

本文基于 `new_docs/` 内现有全部设计、问题分析、PRD v6、旧改造方案，以及 `new_kernel/` 下 DeepTutor 样板代码侦察报告整理。

它的目的不是再写一份泛化架构愿景，而是给 Irene/Repo Tutor 的新内核一个可以实际开工的设计建议：保留现有系统里可靠的只读、事件、会话和工具边界，吸收 DeepTutor 的 turn runtime / stream / capability 经验，但把第一版目标严格收敛到“一个可靠的仓库教学 turn”。

## 1. 一句话结论

Irene 的新内核应该做成：

```text
持久化 TurnRuntime
  + 统一 KernelEvent / replay
  + RepoTutor 单一 capability
  + 显式 ToolContext 和只读 repo tools
  + EvidenceStore / EvidenceDigest
  + TeacherWriter 最终收敛
  + rule-based QualityGate
```

第一版不要做通用 AgentOS，不要做大型多 agent 平台，不要做证据报告生成器，也不要把 LLM 重新塞进大 JSON 教学骨架。

真正的产品交付是：

```text
用户问仓库问题。
内核读最少必要代码。
证据进入内部账本。
TeacherWriter 把证据转成自然教学。
系统保留事件、证据、诊断用于 replay、调试和评测。
```

## 2. 已读材料的合并判断

### 2.1 现有 Repo Teacher 的核心问题

当前后端已经有可用骨架：

- M1 仓库接入和只读安全边界。
- M2 文件树扫描和敏感文件过滤。
- M5 单活会话、SSE 工作流、教学状态入口。
- M6 prompt、LLM 调用、tool loop、sidecar JSON parser。
- `agent_runtime` 的工具选择、seed context、超时降级和活动事件。

但它实际更像：

```text
安全仓库读取器 + 文件树索引器 + 会话状态 + LLM 证据型回答生成器
```

而不是 PRD v6 要的持续教学系统。

主要退化链路是：

```text
文件树/README/相关文件列表
  -> evidence-first prompt
  -> list/search/read 取证工具
  -> 固定 Evidence / Uncertainty / NextSteps 可见栏目
  -> parser fallback 把弱回答包装成结构化结果
  -> teaching state 误以为已经讲过
  -> 后续轮次重复、跳点、变成证据报告
```

最关键的五个故障点：

1. **没有稳定的本轮教学计划**：`TeachingDirective` 只能约束“不要乱说”，不能决定“这一轮教什么、为什么现在教、讲到什么程度”。
2. **证据和最终回答混在一起**：工具结果、文件列表、片段摘要太容易进入可见正文。
3. **输出 contract 把教学变成报告**：Evidence/Uncertainty/NextSteps 被抬成固定可见栏目。
4. **parser 过度宽容污染状态**：没有有效 sidecar 或 evidence 时，也会从 visible text 猜 direct explanation / evidence。
5. **streaming 在质量检查之前发生**：坏回答已经发给用户后，后端才解析和更新状态。

### 2.2 旧改造方案中应保留的经验

旧方案反复提出 `RepoTeachingSkeleton`、`TeachingTurnPlan`、`QualityGate`，方向是对的，但新内核需要收敛：

- `TeachingTurnPlan` 必须保留，它是每轮教学的驾驶舱。
- `QualityGate` 必须保留，它是避免坏回答外露的唯一硬门槛。
- `RepoTeachingSkeleton` 可以保留为内部“证据化教材”，但不能变成 LLM 填表式大 JSON。
- `next_steps[]` 应升级为单一 `next_teaching_point`。
- 状态更新必须 fail-closed：没有关键结构化字段，就不推进覆盖状态。

需要修正的旧倾向：

- 不要让可见回答固定套“概念解释 / 仓库映射 / 代码走读 / 证据”等栏目。栏目可以是内部检查，不应成为外显模板。
- 不要让 LLM 输出庞大的 `teaching_blocks` JSON 作为主产品。结构化字段越大，越容易得到静态、机械、像填表机器的答案。
- 不要把 skeleton 当事实库。它只能是带 `evidence_refs / confidence / unknowns` 的候选教材。

### 2.3 DeepTutor 最值得借鉴的部分

DeepTutor 的价值不在具体 agent 数量，而在内核骨架：

```text
TurnRuntimeManager
  -> UnifiedContext
  -> ChatOrchestrator
  -> CapabilityManifest / BaseCapability
  -> StreamBus / StreamEvent
  -> ToolRegistry
  -> LLM provider factory
  -> SQLite turn_events replay
```

最值得迁移到 Irene 的能力：

1. **Turn 先落库再执行**  
   请求不是一次同步回答，而是一个可恢复、可取消、可重放的执行单元。

2. **事件是内部统一协议**  
   UI、CLI、调试、持久化都消费同一种事件，不理解各 pipeline 内部实现。

3. **`turn_events(turn_id, seq)` 是恢复关键**  
   只保存最终 message 不够，必须保存过程事件。

4. **Capability manifest 应是可执行合同**  
   不只是展示 stages，还要声明 request/result schema、tool policy、dependencies、runtime modes。

5. **工具注册表需要 capability-specific runtime 二次包装**  
   全局工具能注册很多，但 `repo_tutor` 第一版只能暴露受限的只读工具。

6. **最终回答应由 writer 收敛**  
   DeepTutor solve 的 Plan/ReAct/Write 经验很重要：复杂过程可以丰富，但最终用户正文必须由 writer 统一生成。

需要避免照搬的 DeepTutor 风险：

- `_run_turn()` 过重。Irene 应拆成 `ContextAssembler`、`RepoContextAssembler`、`MemoryAssembler`、`EventSink`。
- `metadata` 过自由。Irene 要把 trace metadata 收成 schema。
- 工具靠 `**kwargs` 注入上下文。Irene 第一版就要显式 `ToolContext`。
- code execution / web search / shell 等环境工具不应进入第一版 repo tutor。

## 3. 设计目标和非目标

### 3.1 第一版目标

第一版只服务一个能力：

```text
repo_tutor
```

它要稳定完成：

- 读一个本地仓库或已接入仓库。
- 判断用户这一轮想理解什么。
- 制定小范围读码计划。
- 调用只读仓库工具收集最少证据。
- 把证据压缩成 teacher-facing digest。
- 生成自然教学回答。
- 更新已讲概念和下一教学点。
- 持久化事件和结果，支持 replay。

### 3.2 非目标

第一版不要支持：

- shell
- code execution
- filesystem write
- web search
- 外部进程
- 自动安装依赖
- 多仓库联合分析
- 通用插件 marketplace
- 多 agent 编排平台
- trace-first 调试控制台

这些能力会把产品拉向环境代理，削弱“仓库教学 turn”的可靠性。

## 4. 推荐内核结构

建议未来实现路径为 `backend/new_kernel/` 或 `backend/kernel/`。当前 `new_docs/new_kernel/` 继续作为设计材料目录。

```text
backend/new_kernel/
  contracts/
    events.py
    context.py
    capability.py
    tools.py
    evidence.py
    teaching.py
    result.py
  runtime/
    turn_runtime.py
    event_store.py
    context_assembler.py
    orchestrator.py
  capabilities/
    repo_tutor.py
  repo/
    safe_paths.py
    tools.py
    source_index.py
  teaching/
    planner.py
    digest.py
    writer.py
    quality_gate.py
    state.py
  llm/
    provider.py
  tests/
```

运行主线：

```text
API / UI / CLI
  -> TurnRuntime.start_turn()
  -> EventStore.append(session)
  -> ContextAssembler.build()
  -> Orchestrator.dispatch(repo_tutor)
  -> RepoTutorPipeline
       orient
       plan
       inspect
       digest
       teach
       check
  -> EventStore.append(done/result)
```

## 5. 核心合同

### 5.1 Turn

`Turn` 是最小持久执行单位。

```text
turn_id
session_id
capability: repo_tutor
status: running | completed | failed | cancelled | rejected
created_at
updated_at
request
result
diagnostics
```

规则：

- 请求进入时先创建 turn。
- 每个 turn 内事件必须有递增 `seq`。
- 正常结束只有一个 `done(status=completed)`。
- 失败、取消、拒绝必须先发 terminal error，再发 done。

建议第一版直接用 SQLite，而不是只用内存或 JSONL。

原因：

- Python 自带 sqlite，部署成本低。
- DeepTutor 已证明 `turn_events(turn_id, seq)` 对 resume 和调试很关键。
- JSONL 可以作为 mirror/debug，但不应作为唯一权威存储。

最小表：

```text
sessions
turns
turn_events
messages
```

### 5.2 KernelEvent

事件词表采用精简 DeepTutor 版本：

```text
session
stage_start
stage_end
progress
thinking
observation
tool_call
tool_result
sources
content
result
error
done
```

事件 envelope：

```text
type
source
stage
content
metadata
session_id
turn_id
seq
timestamp
```

producer 不手动写 `seq`，由 `EventStore` 分配。

### 5.3 TraceMeta

不要再让 `metadata` 无限自由。第一版定义稳定字段：

```text
call_id
phase
label
trace_kind
trace_role
trace_group
call_state
call_kind
tool_name
error_type
```

推荐 `trace_role`：

```text
orient
plan
read
evidence
teach
tool
warning
```

### 5.4 可见正文规则

最终 assistant 正文只能来自 `teach` 阶段。

规则：

```text
event.type == content
metadata.call_kind == teacher_final
metadata.source_phase == teach
```

以下永远不能进入最终正文：

```text
thinking
observation
progress
tool_call
tool_result
raw evidence
```

这条规则必须同时出现在后端 content collection、前端 stream append 和测试里。

### 5.5 UnifiedContext

第一版字段：

```text
session_id
turn_id
user_message
conversation_history
active_capability
language
repo_root
selected_files
reading_goal
user_level
enabled_tools
tool_budget
teaching_state
covered_concepts
open_questions
attachments
config_overrides
metadata
```

保留 `enabled_tools` 三态：

```text
None  -> 使用 capability 默认工具
[]    -> 用户显式禁用所有工具
[...] -> 只允许指定工具
```

这个语义不能被 `enabled_tools or []` 吞掉。

### 5.6 CapabilityManifest

```text
name
description
stages
request_schema
result_schema
tool_policy:
  available_tools
  default_tools
  forbidden_tools
  max_tool_calls
  max_file_reads
  max_searches
  max_evidence_tokens
dependencies
runtime_modes:
  supports_resume
  supports_cancel
  supports_regenerate
  supports_attachments
```

第一版 `repo_tutor` manifest 应明确：

```text
available_tools:
  repo_tree
  search_repo
  read_file_range
  summarize_file
  find_references

forbidden_permissions:
  filesystem_write
  network
  code_exec
  external_process
```

### 5.7 ToolContext / ToolResult

工具必须显式接收上下文，不再靠 `**kwargs`：

```text
ToolContext:
  session_id
  turn_id
  repo_root
  workspace_root
  selected_files
  language
  user_level
  event_sink
  evidence_store
  permissions
  budgets
  metadata
```

```text
ToolResult:
  success
  content_for_model
  evidence_items
  metadata
  error
```

默认规则：

```text
repo tools 不产生 content_for_user。
```

### 5.8 Evidence

证据是内部一等对象。

```text
EvidenceItem:
  id
  kind: file_range | symbol | search_hit | dependency | test | doc
  path
  start_line
  end_line
  symbol
  snippet
  summary
  purpose
  confidence
  token_count
  metadata
```

```text
EvidenceDigest:
  teaching_facts
  key_paths
  key_symbols
  uncertainties
  optional_refs
```

输出策略：

- 原始证据不进入正文。
- 正文最多自然提 1 到 3 个 source anchor。
- 完整证据留在 result / trace / diagnostics。

## 6. RepoTutor Pipeline

第一版 pipeline：

```text
orient -> plan -> inspect -> digest -> teach -> check
```

### 6.1 orient

目的：

- 判断用户真实意图。
- 决定是否需要工具。
- 识别关注对象和问题类型。

输出小型内部对象：

```text
intent:
  architecture_tour
  local_explanation
  trace_flow
  compare
  follow_up
  debug_understanding

needs_tools
focus_terms
candidate_paths
```

重要修复点：

- “主线 / 链路 / 数据怎么走 / route 到 parser / workflow / stream / SSE / tool loop”必须能路由到 `trace_flow`。
- 如果用户问代码链路，默认允许 `read_file_range`，不能只给文件列表和搜索。

### 6.2 plan

目的：

- 选定本轮唯一教学点。
- 决定需要哪些最小源码锚点。
- 设定停止读码条件。

建议 `TeachingTurnPlan`：

```text
point_id
point_title
why_now
user_question_relevance
target_depth
teaching_moves
source_anchor_plan
must_explain
avoid
evidence_budget
next_teaching_point
```

`TeachingTurnPlan` 是代码控制对象，不是让 LLM 生成完整回答的 JSON。

### 6.3 inspect

目的：

- 在预算内执行只读工具。
- 读取本轮教学需要的最少代码。
- 将结果写入 EvidenceStore。

规则：

- 优先 `search_repo` 和 `read_file_range`。
- 避免默认 `list_relevant_files(limit=60)`。
- 证据够用立即停止。
- 工具失败不一定让 turn 失败，可以把不确定性传给 writer。

第一版预算建议：

```text
max_tool_calls = 8
max_file_reads = 4
max_searches = 3
max_snippet_lines = 120
max_evidence_tokens = 4000
max_turn_seconds = 45
```

### 6.4 digest

目的：

- 把 EvidenceStore 压成 teacher-facing digest。
- 清理无关工具输出。
- 给 writer 准备“可教学事实”，而不是“证据清单”。

Digest 必须回答：

```text
本轮从代码里确认了什么？
哪些事实直接服务当前教学点？
哪些说法仍需收窄或标注不确定？
```

### 6.5 teach

目的：

- 由 `TeacherWriter` 生成最终可见教学正文。

输入：

```text
user_message
conversation_history
reading_goal
user_level
teaching_state
teaching_turn_plan
evidence_digest
tool_diagnostics
language
```

要求：

- 先答用户当前问题。
- 一次讲清一个核心点。
- 用代码事实支撑，不堆代码事实。
- 解释设计意图、职责边界和为什么。
- 证据不足时缩小 claim，而不是停止教学。
- 结尾最多一个自然的下一教学点。
- 不把工具调用过程改写成正文。

### 6.6 check

目的：

- 质量检查。
- 更新教学状态。
- 生成 result envelope。

第一版用规则质量门，不依赖第二个模型评审。

检查项：

```text
one_teaching_point
why_now_present
system_role_present
source_anchor_count_between_1_and_3_when_needed
evidence_ratio_under_25_percent
not_file_tree_dump
not_fixed_evidence_report
single_next_teaching_point
payload_enough_for_state_update
```

失败行为：

- 若只是可修复写作问题：重写一次。
- 若证据不足：缩小回答边界，仍可完成教学。
- 若 repo 范围不清或安全阻断：返回需要用户澄清的教学型回答，不推进 coverage。

## 7. 状态模型

不要继续用粗粒度 `LearningGoal` 表示“讲过什么”。需要 point-level coverage。

```text
TeachingState:
  current_goal
  current_point_id
  covered_points
  last_next_teaching_point
  user_profile_notes
  open_questions
```

```text
CoveredPoint:
  point_id
  title
  status: not_started | introduced | explained | needs_reinforcement
  depth_reached
  anchor_paths_used
  summary
  remaining_gaps
  last_turn_id
```

状态更新只接受 `check` 阶段产生的结构化结果。禁止从 visible text 猜测。

## 8. 最小实现路径

### M0：合同层

交付：

- `KernelEvent`
- `TraceMeta`
- `UnifiedContext`
- `CapabilityManifest`
- `ToolDefinition`
- `ToolContext`
- `ToolResult`
- `EvidenceItem`
- `TeachingTurnPlan`
- `TeachingState`
- `TeachingResult`

测试：

- event 可序列化。
- trace metadata 字段稳定。
- `enabled_tools` 三态保留。
- tool permission policy 能拒绝 forbidden tool。

### M1：TurnRuntime + EventStore

交付：

- SQLite `sessions / turns / turn_events / messages`。
- `start_turn()`。
- `append_event()` 自动分配 seq。
- `subscribe_turn(after_seq)`。
- cancel/regenerate 先留接口，第一版可以只实现状态。

测试：

- seq 单调递增。
- after_seq replay 正确。
- completed/failed/cancelled 终止语义正确。
- 一个正常 turn 只有一个 done。

### M2：只读 repo tools + EvidenceStore

交付：

- `repo_tree`
- `search_repo`
- `read_file_range`
- `summarize_file`
- `find_references` 可先用搜索降级实现。
- 路径越界和敏感文件拦截。
- 工具错误统一。
- 工具结果写 EvidenceStore。

测试：

- 不读敏感文件正文。
- 不允许越过 repo root。
- 大文件截断。
- 工具失败不污染最终正文。

### M3：RepoTutorPipeline MVP

交付：

- `orient -> plan -> inspect -> digest -> teach -> check`。
- `TeacherWriter` 只输出 `content(call_kind=teacher_final)`。
- `check` 更新 `TeachingState`。
- `result` 返回 response、concepts、files_touched、evidence_refs、diagnostics。

测试：

- 工具调用后最终必须有教学回答。
- `tool_result` 不进入正文。
- 链路问题会读文件片段。
- 没证据不推进 coverage。

### M4：质量与教学评测

交付：

- 规则质量门。
- 坏草稿重写一次。
- golden prompts。

核心 golden prompts：

```text
1. 这个仓库先理解什么最重要？
2. 后端聊天主线从 route 到 stream 是怎么走的？
3. 为什么 session state 和 response generator 要拆开？
4. 讲深一点，不要重复刚才的话，带我看一段代码。
5. 如果证据不足，你会怎么收窄说法？
```

验收：

- 不 dump 文件树。
- 每轮一个教学点。
- 证据占比不超过 25%。
- 结尾只有一个 next teaching point。
- 5 轮内不重复同一角度。

### M5：接入现有后端

建议不要一开始替换现有 M5/M6 主链。先并行接入一个新能力路径：

```text
/api/new-kernel/turn
/api/new-kernel/turn/{turn_id}/events
```

稳定后再将 `web_v3` 的 repo tutor 入口切换到 new kernel。

## 9. 与现有模块的迁移关系

保留并复用：

```text
m1_repo_access -> repo root access 思路
m2_file_tree -> file tree / sensitive filter 思路
security.safety -> 路径与敏感文件规则
agent_tools.repository_tools -> read/search 的安全经验
agent_runtime.tool_loop -> activity / timeout / degraded_continue 经验
m5 runtime_events -> 内部事件到前端协议的经验
m6 sidecar_stream -> 不把机器字段暴露给用户的经验
```

不要直接复用为 new kernel 核心的部分：

```text
固定 OutputContract sections
visible_text parser fallback
next_steps[] 主语义
文件树主导 seed context
先 stream 正文再质量检查
宽松 StructuredAnswer 推进 teaching state
```

DeepTutor 参考但需改造：

```text
TurnRuntimeManager -> 拆成 TurnRuntime + ContextAssembler + EventStore
StreamEvent -> 保留词表，收紧 visible content rule
ToolRegistry -> 增加 ToolContext / permissions / error schema
CapabilityManifest -> 升级为可执行合同
Provider factory -> 可作为后续多模型抽象，不阻塞 M0-M3
```

## 10. 关键设计决定

### 决定 1：第一版 event store 用 SQLite

理由：

- 支持 replay 和断线恢复。
- Python 标准库可用。
- 比 JSONL 更适合作为权威状态。
- 可选 JSONL mirror 用于调试。

### 决定 2：第一版只做 `repo_tutor`

理由：

- 当前最大风险是教学质量，不是能力数量。
- 多 capability 会放大 manifest、tool policy、UI trace 的复杂度。
- 一个可靠教学 turn 比多个半成品能力更有价值。

### 决定 3：不让工具直接产出用户正文

理由：

- 现有系统的主要失败就是证据进入答案。
- TeacherWriter 必须成为唯一最终正文出口。

### 决定 4：不让 LLM 生成大型教学 JSON

理由：

- 旧方案和现有分析都证明大 JSON 会把老师变成填表机器。
- 结构化只服务窄决策和状态更新。

### 决定 5：先用规则 QualityGate

理由：

- 快。
- 可测。
- 不增加另一次模型调用成本。
- 能直接拦住文件树 dump、证据过量、多 next steps、缺 why now。

### 决定 6：M3 skeleton 不作为第一天阻塞项

理由：

- 没有 skeleton 也可以先用 `TeachingTurnPlan + EvidenceDigest + TeacherWriter + QualityGate` 止血。
- skeleton 应作为增强的内部教材层，不应先变成复杂事实库。

## 11. 风险与对策

### 风险：新 kernel 也变成证据报告

对策：

- 工具不产出 `content_for_user`。
- content collection 只收 `teacher_final`。
- 质量门检查 evidence ratio 和 fixed report pattern。

### 风险：回答变模板化

对策：

- 可见答案不固定标题。
- TeacherWriter 输出自然语言。
- 结构化字段只在 result/check 阶段出现。

### 风险：没有 skeleton 时首轮仍空泛

对策：

- plan 阶段强制选择一个教学点。
- inspect 阶段必须读取 1 到 3 个锚点。
- 若无法确定，明确“先讲如何判断入口/主线”这类方法型教学点。

### 风险：SQLite 引入迁移成本

对策：

- 第一版表结构极小。
- 不承诺长期 schema 兼容。
- 加 `schema_version`。

### 风险：用户问具体 bug 时被强行上课

对策：

- `orient` 支持 `local_explanation`。
- `TeacherWriter` 先回答具体问题，再用一小段老师式解释纳入当前点。
- 不强制每轮长篇。

## 12. 验收标准

新内核 MVP 合格标准：

1. 一个用户 turn 会创建持久 turn record。
2. 每个事件有 `turn_id + seq`，可从 `after_seq` replay。
3. `tool_result` 不会进入最终 assistant body。
4. 链路类问题会读取具体源码片段，而不是只列文件。
5. 最终回答不是 Evidence/Uncertainty/NextSteps 固定报告。
6. 每轮只有一个明确教学点。
7. 回答解释“为什么现在讲”和“它在系统中的角色”。
8. 证据可见比例不超过 25%。
9. 缺少有效 payload 或质量门失败时，不推进 `CoveredPoint`。
10. 连续 5 轮不会重复 README/文件树概览。

## 13. 推荐下一步

第一步不要继续扩写愿景文档。建议直接开 M0/M1：

```text
1. 定义 contracts。
2. 实现 SQLite EventStore。
3. 写 turn/event replay 测试。
4. 实现 read-only repo tools + EvidenceStore。
5. 做一个最小 RepoTutorPipeline。
```

只要这条最小闭环跑通，后续再加 skeleton、topic graph、UI trace、provider abstraction 都会更稳。

最终原则：

```text
少一点工具，多一点教学闭环。
少一点可见证据，多一点内部证据。
少一点 LLM 填表，多一点代码控制流程。
少一点平台野心，先让一个 repo_tutor turn 真正像老师。
```
