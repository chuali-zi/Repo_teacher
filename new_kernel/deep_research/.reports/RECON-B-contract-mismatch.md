# RECON-B · Contract & Event Mismatch 侦察

## What

枚举 `DeepResearchLoop` 与 auto-trigger 路径上每一个类型化构造点，与 `contracts.py` 真源比对。结论：**所有 SSE 事件 / `ChatMessage` / `AgentStatus` 的构造在字段名、必填、enum 值上都对得上；2 秒失败的最高嫌疑不是 Pydantic 校验，而是 `SessionState.scratchpad` 的对象类型与 `DeepResearchLoop` 期待的接口完全不同**（`set_subtopics` / `add_note` / `notes_for` / `build_compose_context` / `add_skip_reason` 都不存在），会在 Phase 1 第一个 LLM 调用之后立刻 `AttributeError`。

## Checklist (compact table)

| 构造点 | 类 | 必填字段 | 提供字段 | 匹配 |
| --- | --- | --- | --- | --- |
| deep_research_loop.py:425-436 (`_emit_progress` → `_build_event` → 直构) | `DeepResearchProgressEvent` | `event_id, event_type, session_id, occurred_at, turn_id, phase, summary[, completed_units, total_units, current_target]` | 全部 7 必填 + 3 可选都填 (`event_id=evt_*` / `event_type=DEEP_RESEARCH_PROGRESS` / `session_id` / `occurred_at` / `turn_id` / `phase=str` / `summary` / `completed_units` / `total_units` / `current_target`) | ✅ |
| deep_research_loop.py:351-360 (`AnswerStreamStartEvent` 直构) | `AnswerStreamStartEvent` | `event_id, event_type, session_id, occurred_at, turn_id, message_id, mode: ChatMode` | `event_id` / `event_type=ANSWER_STREAM_START` / `session_id` / `occurred_at` / `turn_id` / `message_id` / `mode=ChatMode.DEEP` | ✅ |
| deep_research_loop.py:373-384 (`AnswerStreamDeltaEvent` 直构) | `AnswerStreamDeltaEvent` | `event_id, event_type, session_id, occurred_at, turn_id, message_id, delta_text` | 全部 7 必填都填 | ✅ |
| deep_research_loop.py:387-397 (`AnswerStreamEndEvent` 直构) | `AnswerStreamEndEvent` | `event_id, event_type, session_id, occurred_at, turn_id, message_id` | 全部 6 必填都填 | ✅ |
| deep_research_loop.py:402-411 (终态 `ChatMessage`) | `ChatMessage` | `message_id, role, content, created_at[, mode, kind, streaming_complete, suggestions]` | `message_id` / `role="assistant"` / `mode=ChatMode.DEEP` / `kind=ReportKind.REPO_ONBOARDING` / `content=markdown` / `created_at=datetime.now(UTC)` (tz-aware) / `streaming_complete=True` / `suggestions=list(...)` | ✅ |
| deep_research_loop.py:339-346 (`status_tracker.update_phase`) | `_TurnStatusTracker.update_phase` 协议 | `state, phase, label, pet_mood, pet_message[, current_action, current_target, emit]` | `state=AgentPetState.RESEARCHING` ✓ / `phase=AgentPhase.STREAMING` ✓ / `label="正在撰写导读"` / `pet_mood="research"` ✓ (literal) / `pet_message=...` / `current_action="撰写导读"` | ✅ |
| repositories.py:257-261 (auto-trigger `SendTeachingMessageRequest`) | `SendTeachingMessageRequest` | `message[, mode, client_message_id, report_kind]` | `message=...` / `mode=ChatMode.DEEP` / `report_kind=ReportKind.REPO_ONBOARDING` | ✅ |
| turn_runtime.py:249-256 (auto-trigger 用户消息) | `ChatMessage` | 同上 | `role=initiator="system"` ✓ (`Literal["system","user","assistant"]` 包含 system) / `mode=ChatMode.DEEP` | ✅ |
| turn_runtime.py:419-427 (`_mark_started` for DEEP) | `update_phase` 协议 | 同上 | `state=AgentPetState.RESEARCHING` / `phase=AgentPhase.RESEARCHING` / `pet_mood="research"` | ✅ |
| 全部 enum 取值 | `AgentPhase`/`AgentPetState`/`PetMood` | — | `STREAMING` ✓ / `RESEARCHING` ✓ / `RESEARCHING` (state) ✓ / `"research"` ✓ | ✅ |

补充背景：`ContractModel.model_config = ConfigDict(extra="forbid", use_enum_values=True)`，所以未知 kwarg 会直接抛 `ValidationError`。我把 `DeepResearchLoop._build_event(...)` 中所有 `**fields` 的来源都核对了一遍——没有错字段名（`current_target`/`completed_units`/`total_units`/`message_id`/`delta_text` 都对得上 `contracts.py` 里的字段拼写）。

## Findings ranked by impact

### Severity 1 — definite bug，匹配“2 秒失败”症状

**`SessionState.scratchpad` 的类型不是 `ResearchScratchpad`，而 `DeepResearchLoop` 整个 Phase 1/2/3 都按 `ResearchScratchpad` 接口调用**。

证据链：

- `session/session_state.py:38-43`，`default_scratchpad_factory()`：
  ```python
  def default_scratchpad_factory() -> "Scratchpad":
      try:
          from ..memory.scratchpad import Scratchpad
      except ImportError:
          return _ScratchpadFallback()  # type: ignore[return-value]
      return Scratchpad()
  ```
  返回的是 `memory/scratchpad.py:128` 的 `Scratchpad` 数据类。
- `memory/scratchpad.py:128` 的 `Scratchpad` 提供的写接口是 `set_plan(plan)` / `add_entry(entry)` / `update_covered_points(...)`，**没有** `set_subtopics` / `add_note` / `notes_for` / `add_skip_reason` / `build_compose_context`。
- `deep_research/deep_research_loop.py:193`：`scratchpad.set_subtopics(list(subtopics))` —— 抛 `AttributeError: 'Scratchpad' object has no attribute 'set_subtopics'`。
- 时序：Phase 0 triage 是纯函数 + 一个 SSE event，能在 100ms 内跑完 → Phase 1 `await self._decomposer.process(...)` 触发**1 个真实 LLM 调用**（DeepSeek/OpenAI 通常 1-2s）→ LLM 返回后立刻 `set_subtopics` → 抛错。**这就是“研究开始 → 2 秒后失败”**。
- 这个异常会被 `TurnRuntime._run_turn`（`turn_runtime.py:390-400`）catch 并通过 `error_event` 推 SSE 给前端，前端看到的就是“开始之后突然失败，没有任何流式输出”。

为什么 `test_deep_research_loop.py` 能通过：测试里用 `ResearchScratchpad()` 当 scratchpad（`tests/test_deep_research_loop.py:324`），所以接口是对的。生产路径走 `SessionState.scratchpad` → `memory.Scratchpad`，接口是错的。线上这条路径完全没单测覆盖。

**根因**：`api/app.py:_build_default_runtime` / `session/session_store.py` 没有把每个 session 的 scratchpad 注入为 `ResearchScratchpad`。两条 loop（teaching / deep）共用一个 `SessionState.scratchpad` 字段，但两边用的接口不兼容。

### Severity 2 — 需要在 standard 5-pillar 路径下才可能触发

无。standard 路径上的所有 contract 构造、enum 值、update_phase 形状都正确。

### Severity 3 — 小问题

- `_StringOverview` （deep_research_loop.py:63-91）的 `language_counts={}` / `top_level_paths=[]` / `entry_candidates=[]` 全是空 → Decomposer 的 `_multilingual` 总是返回 False，永远走不到 `polyglot` 支柱；同时 anchors 都被 `_anchor_reachable` 判为不可达而被 strip 掉。功能不会崩，但 Phase 1 LLM 输出的 anchors 全会丢，Phase 2 ReAct 的工具入口少了。和 2 秒失败无直接关系。
- `_make_overview_proxy` 把 `file_count=1` 兜底（line 113-117）。如果上游 `repo_overview` 真没解析出 `file_count` 字段，触发 short branch，OK。

## Synthetic instantiation results

无 Bash/PowerShell 执行权限，无法直接跑 `python -c`，下面给出**静态推断**：

- `DeepResearchProgressEvent(event_id="evt_x", event_type=SseEventType.DEEP_RESEARCH_PROGRESS, session_id="s1", occurred_at=datetime.now(UTC), turn_id="t1", phase="triage", summary="文件 ≤5", completed_units=0, total_units=0, current_target=None)` → **应当成功**。`event_type` 字段写的是 `Literal[SseEventType.DEEP_RESEARCH_PROGRESS]`，传 enum 实例满足 literal；`use_enum_values=True` 会将其序列化为 `"deep_research_progress"`。
- `AnswerStreamStartEvent(... mode=ChatMode.DEEP)` → **应当成功**。`mode: ChatMode` 接受 enum 实例。
- `ChatMessage(message_id=..., role="assistant", mode=ChatMode.DEEP, kind=ReportKind.REPO_ONBOARDING, content=md, created_at=datetime.now(UTC), streaming_complete=True, suggestions=[])` → **应当成功**。`role: Literal["system","user","assistant"]` 接受 `"assistant"`；`created_at: datetime` 接受 tz-aware datetime；`suggestions: list[str]` 接受 `list[str]`。
- `AgentStatus(... pet_mood="research" ...)` → **应当成功**。`pet_mood: Literal["idle","think","act","scan","teach","research","error"]` 包含 `"research"`。
- 用户消息 `ChatMessage(role="system", mode=ChatMode.DEEP, ...)` —— `Literal` 包含 `"system"`，**应当成功**。

## Recommendation

**修复优先级 1：让 deep loop 拿到的 scratchpad 是 `ResearchScratchpad` 而不是 `Scratchpad`**。三种方案任选：

1. **(最小改动)** 在 `DeepResearchLoop.run` 入口把传进来的 `scratchpad` 先适配/替换：检查是否有 `set_subtopics`，没有就实例化一个 `ResearchScratchpad()` 在 loop 内部用，同时把它写回 `state.scratchpad`（让 sidecar 等能读）。
2. **(干净)** `SessionState.scratchpad` 改为 `dict[ChatMode, Scratchpad-like]`，teaching loop 用 `memory.Scratchpad`，deep loop 用 `deep_research.ResearchScratchpad`，由 `TurnRuntime` 在 `start_turn` 时按 mode 切换实际传入 `loop.run` 的 scratchpad。
3. **(替换)** `default_scratchpad_factory` 直接用 `ResearchScratchpad`，但这会把 teaching loop 的 `set_plan/add_entry` 全打断（teaching 里也会 AttributeError）。**不推荐**。

修复方案 1 或 2 之后，2 秒失败应该消失。建议方案 1 先验证症状，方案 2 作为后续清理。

**优先级 2（顺手）**：在 `tests/test_teaching_experience.py` 或新的端到端测试里，加一条 `mode=deep, report_kind=repo_onboarding, initiator=system` 的最小路径，使用真实 `SessionState`（而不是 `_StubStatusTracker` 加裸 `ResearchScratchpad`），就能在单测层面拦下这个错。

**优先级 3（可选）**：`_make_overview_proxy` 改为从仓库元数据真正读 `language_counts` / `top_level_paths` / `entry_candidates`，让 Decomposer 的 anchors 不总是被 strip。这是质量优化，不影响 2 秒失败。
