# new_kernel/deep_research Agent Instructions

本文件约束 `new_kernel/deep_research/` 内的实现。该模块只服务一件事：
**在仓库接入完成后，自动生成一份面向新手、覆盖 5 大支柱、长度建议 3500-5000 中文字符的入门教学报告**，
通过既有 SSE 通道流式吐给前端。

本模块不是通用深度研究框架，不是 RAG/Agentic-search，不是普通教学回答的高配版；
它是一次性、由系统触发、专门用于"导读一个新接入仓库"的 dedicated 流程。

## 0. 最高约束

1. **目的不变**：导读，大而广，必须覆盖第 §2 节列出的 5 支柱。
2. **不复用现有 agent**：`agents/orient_planner.py`、`agents/reading_agent.py`、`agents/teacher.py`
   不得在本模块被 import。本模块写自己的 4 个 agent。
3. **不引入新工具**：复用 `tools/tool_runtime.py` 暴露的 5 个只读仓库工具，不新增 web search / RAG /
   shell / executor / 任何写工具。
4. **不引入持久化**：所有状态在 `SessionState` + 本模块的 `ResearchScratchpad` 中以内存形式存活；
   进程退出消失。
5. **不破坏现有合同**：实现必须与 `contracts.py`、`web_v4_interface_protocol.md`、
   `module_interaction_spec.md` 一致；任何不一致先改文档再写代码。
6. **不当证据复读机**：见 §7 voice 规范——绝不写"必须严格根据证据"、"无证据请保持沉默"
   一类的 system prompt。

## 1. 必读上下文（开工前按优先级读完）

| 优先级 | 文件 | 用来确认什么 |
| --- | --- | --- |
| 最高 | `../AGENTS.md` | 内核总规、最高解耦/接口要求、第一版范围 |
| 最高 | `../module_interaction_spec.md` | 跨模块依赖方向、import 白名单（§13 已为本模块扩展） |
| 最高 | `../web_v4_interface_protocol.md` | 前端可见 HTTP/SSE 字段；自动触发协议增量见其 §4 |
| 最高 | `../contracts.py` | 公开数据结构；本模块新增字段写在这里 |
| 高 | `../INTERFACES.md` §3.10 | `DeepResearchLoop.run` 签名（与 `TurnLoop` Protocol 一致） |
| 高 | `../turn/turn_runtime.py` | `TurnLoop` Protocol 定义、自动 turn 触发机制 |
| 高 | `../agents/teaching_loop.py` | **只读不抄**——观察 phase 切换/SSE emit/cancellation 检查的样式 |
| 高 | `../agents/base_agent.py` | 本模块的 4 个 agent 都要继承它 |
| 中 | `../tools/tool_runtime.py` | 工具注册、`valid_actions`、`execute(action, action_input, ctx)` |
| 中 | `../memory/scratchpad.py` | **只参考形状**——本模块写自己的 ResearchScratchpad |
| 中 | `../repo/overview_builder.py` | `RepoOverview` 结构（text/entry_candidates/top_level_paths/primary_language/file_count/language_counts） |
| 参考 | `../../DeepTutor/deeptutor/agents/research/` | 三阶段管线的祖本；只学骨架，不抄基础设施 |

## 2. 教学目标与 5 支柱

入门报告必须按下列 5 支柱依次展开：

| 支柱 ID | 标题 | 内容预期 |
| --- | --- | --- |
| `what` | 这个仓库在干什么 | 用一句话 + 一个生活比喻把仓库定位讲清楚；落地到具体能力，不写营销文案 |
| `stack` | 用了哪些技术栈与各自作用 | 列主要技术（语言/框架/运行时/构建工具），逐个用比喻解释它在仓库中扮演什么角色 |
| `why` | 为什么挑这套技术栈 | 推断设计意图与团队品味；允许带轻量"看起来…"、"通常这么选是因为…"标记 |
| `arch` | 整体架构（**重点**） | 模块划分、依赖方向、关键边界；本节篇幅约为其它节的 1.5-2 倍；可写文字结构图（不强制 ASCII/Mermaid） |
| `flow` | 主流程怎么跑通 | 从入口到典型一次执行的链路；带具体文件路径与函数引导 |

可选第 6 支柱（由 decomposer 决定是否追加）：

| 支柱 ID | 触发条件 | 标题 |
| --- | --- | --- |
| `polyglot` | `language_counts` 中次主语言占比 ≥ 25% | 多语言分工与跨语言互调用 |

**支柱 ID 集合稳定**（`{what, stack, why, arch, flow, polyglot?}`）以便 composer 兜底；
具体标题文案可由 decomposer 视仓库微调。短报告分支允许收缩，见 §6。

报告语气：老师腔 + 主动引导。详见 §7。  
报告长度：建议 3500-5000 中文字符。**不做代码侧字数检查，不做自动扩写**；仓库小自然短。

## 3. 三阶段架构

```
DeepResearchLoop.run(...)
  ├─ Phase 0  Triage         0 LLM call    判定走 standard 还是 short 分支
  ├─ Phase 1  Decompose      1 LLM call    输出 4-6 个 sub-topic（含 ID + 标题 + anchors）
  ├─ Phase 2  Investigate    顺序：N 个 sub-topic × ≤2 轮 ReAct（每轮 1 LLM + 1 tool + 1 LLM 笔记）
  └─ Phase 3  Compose        1 LLM call    流式输出长正文
```

LLM 调用预算：

| 路径 | LLM call 数 | 工具调用数 | 墙钟典型 |
| --- | --- | --- | --- |
| short 分支 | 4-5 | 1-2 | 30-60s |
| standard 5 支柱 / 每支柱 1 轮 | 12 | 5 | 90-180s |
| standard 5 支柱 / 每支柱 2 轮跑满 | 22 | 10 | 3-5 分钟 |
| standard + polyglot 跑满 | 26 | 12 | 4-6 分钟 |

工具并发度：v1 顺序执行（`max_parallel=1`）。预留配置位但默认串行，避免 git/handle/内存
峰值踩雷。

### Phase 0 Triage（纯函数）

输入：`RepoOverview`。  
输出：`TriageDecision(report_shape: "short" | "standard", reason: str)`。

判定矩阵：

```
file_count == 0                                           -> 不触发 onboarding，emit ErrorEvent
file_count <= 5  AND  primary_language is None            -> short
primary_language in {None, "Markdown", "plaintext"}       -> short
其它                                                       -> standard
```

实现位置：`triage.py`。整文件约 50 行，单测覆盖全部分支。

### Phase 1 Decompose（1 LLM call）

输入：

- `RepoOverview.text`（已是裁剪后的概览文本）
- `RepoOverview.entry_candidates`（top-N 入口候选）
- `RepoOverview.top_level_paths`
- `RepoOverview.primary_language` + `language_counts` + `file_count`
- 来自 Triage 的 `report_shape`

输出（严格 JSON）：

```json
{
  "subtopics": [
    {
      "id": "what",
      "title": "这个仓库在干什么",
      "anchors": ["README.md", "package.json"]
    },
    { "id": "stack", "title": "...",  "anchors": [...] },
    { "id": "why",   "title": "...",  "anchors": [...] },
    { "id": "arch",  "title": "...",  "anchors": [...] },
    { "id": "flow",  "title": "...",  "anchors": [...] }
  ]
}
```

约束：

- `id` 必须落在固定集合 `{what, stack, why, arch, flow, polyglot}` 内。
- `report_shape == "short"` 时只允许 `[what]` 或 `[what, stack]`。
- `report_shape == "standard"` 时必须包含 `[what, stack, why, arch, flow]`；若多语言条件成立，
  允许追加 `polyglot`。
- 每个 anchor 必须是 `top_level_paths` 或 `entry_candidates.path` 的子串可达路径；不达成时
  decomposer 必须丢弃该 anchor，但保留 sub-topic。
- JSON 解析失败 → 走兜底：standard 分支用固定 5 支柱 + 默认 anchors（`README.md` / 顶层 `src/` 等）。

实现位置：`agents/decomposer.py`。

### Phase 2 Investigate（顺序执行）

按 `subtopics` 列表顺序处理。每处理一个 sub-topic：

```
emit DeepResearchProgressEvent(
  phase="investigate",
  summary=subtopic.title,
  completed_units=k,
  total_units=N,
  current_target=subtopic.title,
)

InvestigationPolicy.start(subtopic) -> 起轮 / 跳过

for round in 1..max_rounds:               # max_rounds 默认 2
  cancellation_token.raise_if_cancelled()

  decision = Investigator.process(
    subtopic=subtopic,
    history=scratchpad.notes_for(subtopic.id),
    failure_streak=policy.failure_streak,
    valid_actions=tool_runtime.valid_actions,
    tool_descriptions=tool_runtime.build_reader_description(),
  )
  # decision = {action, action_input, intent, want_more: bool}

  if decision.action == "done":
    break

  result = await tool_runtime.execute(decision.action, decision.action_input, ctx=ctx)

  note = await NoteTaker.process(
    subtopic=subtopic,
    intent=decision.intent,
    tool_action=decision.action,
    tool_input=decision.action_input,
    observation=result.content,
    success=result.success,
  )
  # note = SubtopicNote(text, anchor_path?, anchor_lines?, success: bool)

  scratchpad.add_note(subtopic.id, round, note, raw_observation=result.content if round <= 1 else None)
  # 关键：第 1 轮的 raw_observation 一并保留给 Composer，避免 NoteTaker 单点信息丢失

  if not result.success:
    policy.bump_failure()
    if policy.should_skip(subtopic):
      scratchpad.add_skip_reason(subtopic.id, "工具连续失败")
      break
  else:
    policy.reset_failure()

  if not decision.want_more:
    break
```

`InvestigationPolicy`（`investigation_policy.py`，纯函数 + dataclass，约 60 行）：

- `max_rounds`：默认 2，可由本模块 caller 调高（不暴露给前端）。
- 停轮条件：`round == max_rounds` ∨ Investigator 返回 `action="done"` ∨ Investigator 返回 `want_more=false` ∨ 连续 2 次工具失败。
- 跳过条件：连续 2 次工具失败 → 该 sub-topic 不再起轮，写入 skip_reason。
- 失败 sub-topic 不删除，让 Composer 知情。

实现位置：

- `agents/investigator.py`：单轮决策（≤1 个工具调用），输出 `InvestigationDecision`。
- `agents/note_taker.py`：把 `ToolResult` 压成 200-400 字 sub-topic 笔记；用 voice 节口吻
  ，**不抽取 JSON**，输出自然语言短笔记 + 可选 anchor 元信息。
- `investigation_policy.py`：起轮/停轮/跳过决策，纯函数。

### Phase 3 Compose（1 LLM call，流式）

输入：

- `subtopics` 元信息（id + 标题 + skip_reason?）
- 每个 sub-topic 的全部 `SubtopicNote`（200-400 字×每轮）
- 第 1 轮的 `raw_observation`（受截断保护，单 sub-topic ≤ 2KB）—— 让 Composer 拿到二级证据，
  避免 NoteTaker 信息丢失链路单点
- `RepoOverview.text` 轻上下文
- 系统 voice prompt（见 §7）

输出：流式 markdown。Composer 不返回 JSON。

流程：

```
emit AnswerStreamStartEvent(turn_id, message_id, mode=DEEP)
async for chunk in composer.process(...):   # composer 内部 stream_llm
    每 8 个 chunk 检查一次 cancellation_token
    emit AnswerStreamDeltaEvent(turn_id, message_id, delta_text=chunk)
emit AnswerStreamEndEvent(turn_id, message_id)
return ChatMessage(
    role="assistant",
    mode=ChatMode.DEEP,
    kind=ReportKind.REPO_ONBOARDING,
    content=完整 markdown,
    suggestions=[Composer 在结尾解析出的 1-3 条"接下来"],
)
```

`MessageCompletedEvent` 由 `TurnRuntime` 在 loop 返回后统一发出（与 TeachingLoop 一致）。

**Composer 在 prompt 中明确以下内容会一起进上下文，避免它把工具术语漏给学生：**

- 笔记和 raw observation 是"我们一起看到的素材"，不要复述工具名 / JSON / `tool_call` 字样。
- skip_reason 不直接展示；如该支柱缺料，简短说明仓库里没有典型的对应代码即可，并继续推进。

实现位置：`agents/composer.py`。

## 4. 自动触发协议

### 4.1 触发链路

```
POST /api/v4/repositories
  -> repositories.py 创建 session, asyncio.create_task(_run_parse_pipeline(...))
  -> parse pipeline 走完所有阶段
  -> connected_sink(data) 写入 state.repository / state.current_code
  -> _publish_repo_connected -> emit RepoConnectedEvent
  -> 紧接着同一 task 中调用：
       turn_runtime.start_turn(
           state=session,
           request=SendTeachingMessageRequest(
               message="<由 DeepResearchLoop 内部生成的 prompt seed，前端不展示>",
               mode=ChatMode.DEEP,
               report_kind=ReportKind.REPO_ONBOARDING,
           ),
           initiator="system",
       )
```

注意事项：

- **`message` 不是魔法占位符**。`SendTeachingMessageRequest.message` 字段最小长度为 1，由
  `_run_parse_pipeline` 注入一段固定中文 seed（例："请基于刚刚接入的仓库生成一份面向新手的入门导读"），
  这段文本仅作为 `state.messages` 中 `role="system"` 的输入留档，前端凭 `kind` 字段判断
  不渲染到聊天面板。
- 仅当 parse pipeline 完整成功（`connected_data is not None`）才触发；中途失败不触发。
- 触发前须确认 `runtime.turn_runtime is not None`；否则跳过自动触发，记 warning（不阻塞 parse 结果）。

### 4.2 SSE 接续

前端只需订阅 `GET /api/v4/repositories/stream?session_id=...` 一个流，按顺序接收：

```
agent_status (scanning -> ...)            # parse 阶段
repo_parse_log * N
repo_connected
agent_status (researching)                # 自动 turn 启动
deep_research_progress (phase=triage)
deep_research_progress (phase=decompose)
deep_research_progress (phase=investigate, k/N) * N
agent_status (researching)                # 进入 compose
answer_stream_start                       # turn_id 在此事件中暴露
answer_stream_delta * many
answer_stream_end
message_completed                         # message.kind == "repo_onboarding"
agent_status (idle_after_teach)
```

`RepoConnectedEvent` **不增加**任何字段（不加 `auto_turn_id`）。前端从
`AnswerStreamStartEvent.turn_id` 获取 turn_id。

### 4.3 重复触发的语义

- 同 session 二次 `POST /repositories`：`_run_parse_pipeline` 启动前调用
  `turn_runtime.cancel(state, reason="new_repo")` 取消进行中的 onboarding；等取消完成后
  reset state（清 `messages` / `scratchpad` / `repository` / `repo_root` / `current_code` /
  `parse_log`）；再启动新 parse。
- 用户主动 `POST /chat/messages` 带 `mode=deep, report_kind=repo_onboarding`：与自动触发等价，
  允许重新生成。`active_turn_id` 互斥保护已有，无需额外逻辑。

## 5. 状态机与边界

| 场景 | 行为 |
| --- | --- |
| parse 全程成功 | 紧接 emit `RepoConnectedEvent` 后启动 onboarding turn |
| parse 中途失败 | 不触发 onboarding；走现有 ErrorEvent 路径；scratchpad 维持空 |
| onboarding 跑到一半，用户 `POST /chat/messages` | TurnRuntime 现有互斥：返回 `ApiError(INVALID_STATE)`，message: "请先等待入门报告完成或按取消" |
| onboarding 跑到一半，用户 `POST /control/cancel` | `CancellationToken.raise_if_cancelled()` 在每个 phase 起点 + 每 8 个 stream chunk 检查；emit `RunCancelledEvent`；scratchpad **保留半截**；`active_turn_id` 由 TurnRuntime finally 清空 |
| onboarding 跑到一半，前端断 SSE | 后端继续跑完；ChatMessage 写入 `state.messages`；前端重连后 `GET /api/v4/session?session_id=...` 即可看到完整报告 |
| onboarding 已完成，用户 `mode=chat` 提问 | 走 TeachingLoop；scratchpad 中 onboarding 的 sub-topic 笔记保留，TeachingLoop 通过 `covered_points` 复用 |
| 同 session 二次 `POST /repositories` | 见 §4.3 |
| onboarding 中 LLM 502/timeout | 抛错 → TurnRuntime emit `ErrorEvent` + status=error；scratchpad 保留 |
| `mode=deep` 且 `report_kind != repo_onboarding` | v1 直接返回 `INVALID_REQUEST`，message: "深度模式当前仅用于仓库入门报告" |
| 用户主动重生成 onboarding | 允许；`active_turn_id` 互斥保护 |
| onboarding 完成后 scratchpad 处置 | 保留全部 sub-topic 笔记 + `covered_points`，供后续 TeachingLoop 引用 |

### Cancellation 检查点（必须）

- 进入 Phase 1 之前
- 进入每个 sub-topic 之前
- 每轮 ReAct 之前
- 进入 Phase 3 之前
- Phase 3 流式 chunk 计数器每 8 次

不在以上点检查 = bug。

## 6. 短报告分支

Triage 输出 `short` 时：

- Phase 1 Decompose 强制 `subtopics = [what]` 或 `[what, stack]`。
- Phase 2 Investigate 单 sub-topic、单轮、最多 2 个工具调用（典型：`read_file_range(README.md)` + `list_dir(".")` ）。
- Phase 3 Compose 输出 800-1500 字。
- 全程目标 30-60s。
- 总 4-5 LLM call，1-2 工具调用。
- voice 仍然是老师腔，但篇幅自然收缩，不强行展开技术栈/架构。

适用情形：单文件仓、纯 Markdown 仓、纯配置仓、空骨架仓。

## 7. Voice / Prompt 规范

### 7.1 必须不写的 prompt（反模式）

下列基调一旦进入 system prompt，LLM 立即退化成"对照证据机器人"，绝不允许：

- "你必须严格根据证据"
- "如果没有证据请保持沉默"
- "禁止推测"
- "只复述工具看到的内容"
- "不要做任何延伸"
- "在不确定时不要回答"

### 7.2 必须写的 prompt 基调

```
你是一位资深工程师 + 资深教师，正在带一个新手通读这个仓库。

你的任务是把这个仓库讲活：
- 用比喻、类比、画面感的语言把抽象概念落地（"消息队列像快餐店取餐机"）。
- 大胆推断设计意图、技术品味、团队风格；用"看起来…"、"我猜测…"、
  "通常这么选是因为…" 等轻量带过，但不要因为不确定就闭嘴。
- 主动引导："你现在打开 X 文件，从第 Y 行开始读，注意 Z 这个细节。"
- 引入与新手日常经验的连接（"你写过的 console.log 在这里相当于…"）。
- 宁可写多一点延展讲解、技术品味、行业上下文，也不要变成"工具看到了什么我就复述什么"。

证据使用方式：
- 把笔记和素材当作"我们一起看到的内容"，从素材出发讲设计与意图。
- 当素材没看到某细节但你的工程直觉告诉你"通常这么写"时，可以推测，但要附上
  你推测的理由（"主流 X 框架基本都这么做"）。
- 不要把工具名称、ToolResult、JSON 结构暴露给学生。

报告结构：
1. 首段一句话 + 一个比喻把整个仓库讲清楚（hook）。
2. 按 sub-topic 顺序展开；架构节最重，篇幅约其他节 1.5-2 倍。
3. 每节用 1-2 个引导问句结尾把学生带进下一节。
4. 末尾给 1-3 个具体的"接下来你可以…"学习路径建议。

长度建议：3500-5000 中文字符。仓库小就少写，不要灌水。

不要把以下内容暴露给学生：
- 工具名称、ToolResult、JSON 结构、tool_call 字样。
- "我没有找到证据"、"证据不足"等扫兴句子（除非该信息真的关键）。
- 配置文件中的密钥 / token / API key 字面值。
```

decomposer / investigator / note_taker 的 prompt 用一致基调：**鼓励判断、外推、压成"教学要点"
而不是"证据复读"**。NoteTaker 输出的不是中立摘要而是"教学要点"——一个老师读完这段代码后
打算怎么讲它。

### 7.3 安全护栏（不是证据约束）

下面这些不是"必须根据证据"的约束，是安全规则，必须写进 prompt：

- 不输出仓库中读到的密钥 / token / .env 字面值。
- 不输出可执行的破坏性命令或 shell payload。
- 不在报告中粘贴大段（>40 行）原始代码；用引导"打开 X 看 Y" 替代。

## 8. 模块布局

```
new_kernel/deep_research/
  AGENTS.md                       本文件
  __init__.py                     re-export DeepResearchLoop
  deep_research_loop.py           ~280 行  实现 TurnLoop Protocol，编排 4 个 phase
  research_scratchpad.py          ~160 行  sub-topic 感知的笔记账本（不同于 memory/Scratchpad）
  triage.py                       ~50 行   Triage 决策纯函数 + dataclass
  investigation_policy.py         ~60 行   起轮/停轮/跳过决策纯函数 + dataclass
  agents/
    __init__.py
    base_research_agent.py        ~50 行   BaseAgent 子类，加 stream_to_chunks 和 strict-JSON 辅助
    decomposer.py                 ~110 行  Phase 1
    investigator.py               ~140 行  Phase 2 单轮决策
    note_taker.py                 ~80 行   Phase 2 笔记生成
    composer.py                   ~180 行  Phase 3 流式正文
  prompts/
    zh/
      decompose.yaml
      investigate.yaml
      note.yaml
      compose.yaml
```

总计约 1100 行 Python + 4 份 YAML。

每个 .py 文件首行必须有职责注释（与本目录其它文件保持一致），点出"本文件做什么、不做什么"。

## 9. 公开接口

### 9.1 `DeepResearchLoop.run`

签名严格匹配 `turn/turn_runtime.py:TurnLoop` Protocol：

```python
class DeepResearchLoop:
    def __init__(
        self,
        *,
        decomposer: Decomposer,
        investigator: Investigator,
        note_taker: NoteTaker,
        composer: Composer,
        tool_runtime: ToolRuntimeProtocol,
        max_rounds_per_subtopic: int = 2,
        max_parallel_subtopics: int = 1,                   # v1 = 1
        event_factory: EventFactory | None = None,
    ) -> None: ...

    async def run(
        self,
        *,
        session_id: str,
        turn_id: str,
        user_message: str,
        scratchpad: Any,                                    # 实际是 ResearchScratchpad；保持 protocol 上的 Any 与 TeachingLoop 一致
        repo_overview: str,                                 # TurnRuntime._repo_overview 的产物
        repo_root: Path,
        sink: EventSink,
        status_tracker: StatusTracker,
        cancellation_token: CancellationToken,
    ) -> ChatMessage: ...
```

返回的 `ChatMessage` 由 `TurnRuntime` 写入 `state.messages` 并 emit `MessageCompletedEvent`。
本 loop 不直接发 `MessageCompletedEvent`，与 TeachingLoop 一致。

### 9.2 注入点

`api/app.py:_build_default_runtime` 把 `_DeepResearchPlaceholder()` 换成真实
`DeepResearchLoop` 实例。其余装配逻辑（LLM client / PromptManager / tool_runtime）已就绪。

### 9.3 自动触发位置

`api/routes/repositories.py:_run_parse_pipeline` 末尾——在
`_publish_repo_connected(...)` 之后、函数返回前，新增一段：

```python
turn_runtime = runtime.turn_runtime
if turn_runtime is not None and connected_data is not None:
    try:
        await turn_runtime.start_turn(
            state=session,
            request=SendTeachingMessageRequest(
                message="请基于刚刚接入的仓库生成一份面向新手的入门导读。",
                mode=ChatMode.DEEP,
                report_kind=ReportKind.REPO_ONBOARDING,
            ),
            initiator="system",
        )
    except Exception as exc:
        # 自动触发失败不影响 parse 结果；记 warning，靠用户主动调 chat 接口兜底
        ...
```

异常吞没只针对 onboarding 触发；parse 阶段本身的错误仍按现有路径走。

## 10. Contract 改动

新增最小集（写入 `../contracts.py`）：

```python
class ReportKind(StrEnum):
    ANSWER = "answer"
    REPO_ONBOARDING = "repo_onboarding"


class ChatMessage(ContractModel):
    # 既有字段保持不变
    kind: ReportKind = ReportKind.ANSWER       # 新增；默认值确保向后兼容


class SendTeachingMessageRequest(ContractModel):
    message: str = Field(min_length=1)
    mode: ChatMode = ChatMode.CHAT
    client_message_id: str | None = None
    report_kind: ReportKind = ReportKind.ANSWER   # 新增
```

校验规则（写在 route 层而非 contract 层）：

- 若 `mode == ChatMode.DEEP` 且 `report_kind != ReportKind.REPO_ONBOARDING` → 返回
  `ApiError(INVALID_REQUEST, "深度模式当前仅用于仓库入门报告")`。
- 若 `mode == ChatMode.CHAT` 且 `report_kind != ReportKind.ANSWER` → 同上拒绝。

`MessageCompletedEvent` 不需改动（它已携带完整 `ChatMessage`，前端读 `message.kind`）。  
`RepoConnectedEvent` 不增加任何字段。

## 11. 解耦与依赖

### 11.1 允许 import（写入 `../module_interaction_spec.md` §13）

`deep_research/*` 允许导入：

```
contracts
agents.base_agent           # 仅作基类
llm.client                  # 通过组合根注入；本模块不读 .env
prompts.prompt_manager
memory.scratchpad           # 仅引用值类型 Anchor；本模块自己的账本不依赖它
tools.tool_protocol
tools.tool_runtime
```

**禁止**导入：

```
api.*                       # 反向依赖
session.*                   # 反向依赖
turn.*                      # 反向依赖（Protocol 由 deep_research 满足，不需要 import）
events.*                    # 通过 EventSink 注入；本模块不直接持有 EventBus / EventFactory
repo.*                      # 通过参数接收 repo_overview/repo_root
agents.orient_planner / agents.reading_agent / agents.teacher  # 不复用
```

### 11.2 不修改其它模块的内部状态

- 写 `state.scratchpad`：仅当 caller（TurnRuntime）传入。本模块不直接写 SessionState 字段。
- 写 `state.messages`：本模块不写；由 TurnRuntime 在 `run` 返回后写。
- 发 SSE：仅通过传入的 `sink: EventSink`；不构造 SSE JSON 字符串；事件类型只用
  `contracts.SseEvent` 子类（必要时通过 `event_factory` 工厂函数）。

### 11.3 组合根装配

```
api/app.py
  -> 构造 PromptManager / LLMClient / ToolRuntime（已有）
  -> 构造 4 个 research agent，注入 LLMClient + PromptManager
  -> 构造 DeepResearchLoop，注入 4 agent + tool_runtime
  -> TurnRuntime(teaching_loop=..., deep_loop=DeepResearchLoop(...))
```

不允许在本模块内 `new` 出 `LLMClient` / `PromptManager` / `ToolRuntime`。

## 12. 实现质量门槛

### 12.1 Cancellation

每个 phase 起点、每个 sub-topic 起点、每轮 ReAct 起点、每 8 个 stream chunk 必须调
`cancellation_token.raise_if_cancelled()`。漏一处视为 bug。

### 12.2 错误处理

- 工具失败：`ToolResult.success = False` 时写入 scratchpad（带 `success=False` 标记），
  让 NoteTaker / Composer 知情；不让单次工具失败终止 turn。
- LLM 调用失败：抛出，由 TurnRuntime 转为 `ErrorEvent`；本模块不 swallow LLM 异常。
- JSON 解析失败：decomposer / investigator 走兜底（默认 5 支柱 / 默认 done）；不抛。

### 12.3 上下文预算

| 上游 prompt 部分 | 预算 |
| --- | --- |
| compose.yaml system prompt | < 3KB |
| 单 sub-topic 笔记串接 | 每 sub-topic ≤ 1.5KB（200-400 字×2 轮） |
| raw_observation 旁路（仅第 1 轮） | 每 sub-topic ≤ 2KB |
| `RepoOverview.text` | ≤ 4KB（由 OverviewBuilder 自身限长） |
| Composer 总输入 | ≤ 30KB（5-6 sub-topic × 各 5KB 上限） |

NoteTaker 必须把 `ToolResult.content` 压到上限以内；超长 raw_observation 截断保留头尾。

### 12.4 路径越界

所有传给工具的 `action_input.path` 必须由 `tool_runtime.execute` 内部经过
`safe_paths.resolve_under_root` 校验（这是 ToolRuntime 既有约束，不需要本模块重复实现）。
本模块不直接读文件、不直接拼路径绝对值。

### 12.5 流式输出语义

- `AnswerStreamDeltaEvent.delta_text` 只承载 Composer 输出的可见 token；不承载笔记、工具日志、
  ReAct thought。
- markdown 片段在流式过程中可能未闭合（代码块、列表）；前端需做 progressive parse。
  本模块不为渲染兜底，但 Composer prompt 应避免过深嵌套结构。

### 12.6 metrics

每次 LLM 调用：`status_tracker.add_metrics(llm_call=1, emit=False)`。  
每次工具调用：`status_tracker.add_metrics(tool_call=1, emit=False)`。  
不必 emit；TurnRuntime 在终态会一并广播。

## 13. 测试策略

| 层 | 测什么 | 怎么测 | 不测什么 |
| --- | --- | --- | --- |
| 单元 | `Triage` 决策矩阵 | pytest 全分支输入 → 输出 | 不测 LLM 输出 |
| 单元 | `InvestigationPolicy` 起轮/停轮/跳过 | 状态机表驱动 | 不测真实工具 |
| 单元 | `ResearchScratchpad` 写入/序列化/build context | 直接构造 | 不测 build 出来的 prompt 文本质量 |
| 单元 | `DeepResearchLoop` 满足 `TurnLoop` Protocol | typing.runtime_checkable + 签名反射 | 不测内部步骤 |
| 集成 | 用 stub LLM 走通完整流程 | 注入 fake LLM 返回最小有效 JSON / 流式片段；断言 SSE 序列：`agent_status × N → deep_research_progress × K → answer_stream_start → answer_stream_delta × N → answer_stream_end → message_completed (kind=repo_onboarding)` | 不断言文本质量 / 不断言长度 |
| 集成 | 边界：空仓 / 单文件 / 二进制仓 | fixture repo + fake LLM 走 short 分支 | 不测 standard 内容 |
| 集成 | 取消语义 | 中途 `cancel(reason=user_escape)`，断言 `RunCancelledEvent` + `active_turn_id` 清空 + scratchpad 半截保留 | |
| 集成 | 同 session 二次连仓 | 模拟连两次，断言第一次被 cancel + state 重置 | |
| 集成 | `mode=deep, report_kind=answer` 拒绝 | 断言返回 `INVALID_REQUEST` | |
| 手测 | 真实 LLM 跑真实仓库（建议拿 `new_kernel` 自身或 DeepTutor 跑） | 由人类执行：读报告，看老师腔/比喻/字数/可读性 | 这层做"质量"判定 |

**不写**字数下限 assertion（如 `assert len(content) >= 4000`）。字数是 voice prompt 的建议项，
不是合同。

## 14. 不做事项（与 `../AGENTS.md` 第一版范围对齐）

- 不引入数据库 / SQLite event store / 持久化报告文件。
- 不引入 web search / RAG / embedding / 知识库。
- 不引入 shell / code execution / write 工具 / network 工具。
- 不引入 token tracker / 多 provider factory / `.env` 读取层。
- 不引入 skill / MCP / 插件 marketplace。
- 不引入 prompt 远程 store / watcher / A/B 路由。
- 不引入"扩写一轮"类自动改稿循环。
- 不引入"coverage_score"等无定义的自适应停轮信号。
- 不引入并发到 5+ sub-topic 的并行（v1 顺序）。
- 不为 `mode=deep` 之外的入口提供 `repo_onboarding` 触发。
- 不在前端协议中加 `auto_turn_id` / 占位魔法字符串。

## 15. 实现顺序建议

按下列顺序最小化阻塞：

1. **Contract 改动先合**：`ReportKind` enum + `ChatMessage.kind` + `SendTeachingMessageRequest.report_kind`
   + `module_interaction_spec.md §13` 的 import 白名单扩展。
2. **写纯函数与数据结构**：`triage.py`、`investigation_policy.py`、`research_scratchpad.py`。
   这层有完整单测，无 LLM 依赖。
3. **写 4 个 agent + 4 份 YAML**：从 `decomposer` 开始，每写完一个就用 stub LLM 跑通。
4. **写 `DeepResearchLoop`**：组装 4 个 agent，跑 stub 集成测。
5. **改 `api/app.py`**：替换 `_DeepResearchPlaceholder`。
6. **改 `api/routes/repositories.py`**：在 parse 成功后追加 `start_turn(initiator="system", ...)`。
7. **改 `web_v4_interface_protocol.md` / `AGENTS.md` / `INTERFACES.md`** 同步描述。
8. **手测真实 LLM + 真实仓库**，照 §13 末行执行。

## 16. 验收标准

第一版合格的硬性标准：

1. 接入一个非空仓库后，**无需用户输入**，前端在 1-5 分钟内能从同一条 repository SSE 中
   依次拿到 `repo_connected` → `agent_status(researching)` → `deep_research_progress×多个 phase`
   → `answer_stream_*` → `message_completed(kind=repo_onboarding)`。
2. 报告内容覆盖 5 支柱（`what / stack / why / arch / flow`），架构节明显比其它节长。
3. 报告语气是老师腔，含至少 1 个比喻、至少 1 处主动引导（"你打开 X 看 Y"）；不出现
   "工具"、"ToolResult"、"JSON" 等术语。
4. `mode=chat` 普通教学回答完全不受影响（回归测）。
5. 用户在 onboarding 期间按取消能在 ≤5 秒内拿到 `RunCancelledEvent` 并恢复 idle。
6. 同 session 第二次连新仓时，第一次的 onboarding 被取消、`messages` 被重置。

不验收：

- 字数硬指标（不强求 ≥4000）。
- 报告"质量"自动评分。
- 多用户并发 / 多 session 隔离压测。
- 私有仓库 OAuth。
- 跨 session 持久化。
