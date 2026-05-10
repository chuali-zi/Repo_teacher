# SA-07 · DeepResearchLoop (Phase 0..3 orchestrator)

## What
按 `deep_research/AGENTS.md` §3 / §5 / §9 / §11.1 / §12 落地 `DeepResearchLoop`，把 SA-01 的三个纯数据层（triage / investigation_policy / research_scratchpad）和 SA-03..SA-06 的 4 个 agent（Decomposer / Investigator / NoteTaker / Composer）拼成满足 `turn.turn_runtime.TurnLoop` Protocol 的协调器。`run(...)` 依次跑 Phase 0 Triage → Phase 1 Decompose → Phase 2 顺序 ReAct（每支柱 ≤ `max_rounds_per_subtopic` 轮）→ Phase 3 流式 Compose；每个 phase 起点、每个支柱起点、每轮起点、每 8 个流式 chunk 调一次 `cancellation_token.raise_if_cancelled()`；每次 LLM 调用 + 每次工具调用都通过 `status_tracker.add_metrics(emit=False)` 记账。返回值是一条 `ChatMessage(mode=DEEP, kind=REPO_ONBOARDING, role=assistant, streaming_complete=True)`，把 Composer 解析出的 `<<SUGGESTIONS>>` 块挂在 `suggestions` 字段。

## Files
- mod  new_kernel/deep_research/deep_research_loop.py:+501/-1  把原来 1 行注释占位替换成完整实现：`DeepResearchLoop` 类（构造器接 4 agent + tool_runtime + 可选 event_factory + 可选 message_id_factory）、`run(...)` 公开入口、`_run_investigate_phase` / `_run_compose_phase` 两段封装、`_StringOverview` 把 `repo_overview: str` 解析成 triage / decomposer 期望的对象、5 个 `_build_*_event` 工厂分支（注入 factory 时优先；缺省时用 contracts 直接构造）、`_StubLLMClient` 不在本模块（只在测试里）
- mod  new_kernel/deep_research/__init__.py:+8/-3  re-export `DeepResearchLoop` 并更新模块 docstring（去掉"由 SA-07 接入"的占位说明）
- new  new_kernel/tests/test_deep_research_loop.py:421  5 个集成测试 + 一组共享 stub（_StubLLMClient 按 system_prompt 关键字路由 4 类回应、_StubToolRuntime 暴露 valid_actions + execute、_CapturingSink 记录 emit 顺序、_StubStatusTracker 记账但不发事件）；测试覆盖：完整事件序列 / ChatMessage 形状 / cancel 传播 / short 分支 / TurnLoop 签名一致
- mod  new_kernel/deep_research/.reports/README.md:+1/-1  SA-07 索引行去 "（待）" 并补一句结果
- new  new_kernel/deep_research/.reports/SA-07-loop.md:本报告

## Decisions
- **`repo_overview: str` 用解析器代理而非新增 kwarg**：spec 备注里给了两个选项，明确写"Take option (a)"——保持 `TurnLoop` Protocol 签名不变，在 loop 内部 `_make_overview_proxy(text)` 扫两条已知行 `primary_language: <X>` 和 `file_count: <N>` 拼出最小 overview-like 对象。`primary_language` 取值是 `unknown` / `none` / `null` / 空时归一为 `None`，触发 triage 的 short 分支。`top_level_paths` / `entry_candidates` / `language_counts` 留空，decomposer 的 `_anchor_reachable` 自然会把 anchor 列表清空但保留 sub-topic（已有 SA-03 测试覆盖）。这层选择避免对 `TurnLoop` Protocol 做侵入式改动，让 SA-08 的占位替换零额外参数。
- **`file_count` 缺省提升到 1 而非 0**：`TurnRuntime._repo_overview()` 在 repository 为 None 时不会写 `file_count` 行，但本 loop 已经被 `start_turn` 启动，意味着 `_ensure_repository_ready` 已通过。如果解析不到 file_count，把它当 1 而非 0，避免 triage 抛 `EmptyRepositoryError` 把整个 turn 顶死——空仓应该在更上游被拦截，loop 入口不该承担"判定空仓"的二级职责。这条偏离写下来是为了让 SA-08/SA-10 集成时一眼能看到。
- **顺序而非并行执行 sub-topic（v1）**：AGENTS.md §3 / §0 / §14 强制 v1 顺序执行（`max_parallel_subtopics=1`）；构造器接受 `max_parallel_subtopics` 参数但只当存档位用，实际循环写死 `for index, subtopic in enumerate(subtopics)`。这与 spec "v1 = 1; ignored if other than 1" 对齐，也避免不同支柱共享 InvestigationPolicy 时的状态竞争（`failure_streak` / `skip_subtopic_ids` 都是 per-policy 单实例共享）。
- **每个支柱在进入 round 循环前发一次 `investigate` ProgressEvent**：spec 要求"5× DeepResearchProgressEvent(investigate)"。我把 emit 放在 `for round_idx in ...` 之前的一行，所以即使第一轮 Investigator 立刻 `done`，仍然有一条 progress 事件落到 sink。这让前端能稳定按 `completed_units / total_units` 推进度条，不依赖 Investigator 决策。
- **进入 Phase 3 前发一次 `update_phase(STREAMING)`**：与 TeachingLoop 对齐——Phase 3 进入前用 `AgentPetState.RESEARCHING` + `AgentPhase.STREAMING` + `pet_mood='research'` 的状态，标签写"正在撰写导读"。`update_phase` 默认 `emit=True`（spec 没让我们关掉），所以 sink 会拿到一条 `agent_status` 事件——这是 spec §4.2 时序图里 "agent_status (researching)  # 进入 compose" 那一行的具体落地。测试用 stub tracker 不广播，所以 sink 里看不到这条；真实 `_TurnStatusTracker` 会把它送出去。
- **8-chunk cancellation 节拍写在 loop 而非 Composer**：SA-06 的 Composer 自身不持有 `cancellation_token`（保留 agent "无 IO/无副作用"风格）。Loop 在 `async for delta in self._composer.stream(...)` 外层做 `chunk_count` 计数，每 8 次 raise；空 chunk 不计数，避免 Composer 占位句兜底引入伪 chunk。这条被 spec 明确点名，所以单写一段注释也要讲清楚。
- **NoteTaker 的 observation 截到 2KB 再传，scratchpad 里第 1 轮 raw 持原长**：spec 表 §12.3 写"NoteTaker 必须把 ToolResult.content 压到上限以内"。我在 loop 层把传给 NoteTaker 的 `observation` 用 `[:2048]` 切；但传给 `scratchpad.add_note(..., raw_observation=observation_text)` 的是原始字符串，由 SA-01 的 `_truncate_raw` 自己保留头尾各 1KB。这两个截断是不同语义：一个是 prompt 输入预算，一个是 Composer 二级证据预算。
- **`event_factory` 注入是 5 个独立分支，不是单一 dispatch dict**：每个 event 类型都有 `_factory_method(factory, "deep_research_progress_event")` 这样的探针。注入时若工厂提供该方法就用注入版本；缺省走 `contracts.<EventClass>(...)` 构造。这与 `events.event_factory.EventFactory` 的方法名一一对齐，所以 SA-08 装配时把同一个 `EventFactory()` 直接塞进来就能用，不需要写 adapter。
- **不 import `events.*`**：AGENTS.md §11.1 禁令。`event_factory` 注入点是 `Any | None`，运行时鸭子类型，缺省直接使用 `contracts.AnswerStreamStartEvent(...)` 等模型。
- **Cancellation 在 ToolResult 之后立刻吐 NoteTaker 并写 scratchpad，不在工具失败时拦截**：AGENTS.md §3.3 / §12.2 明确说"工具失败转 observation 写入 scratchpad，不让单次工具失败终止 turn"。我让 `tool_result.success=False` 也走 NoteTaker 一遍（NoteTaker 的失败兜底就是为这个准备的），失败计数由 `policy.bump_failure()` 推进；连续 N 次失败才走 `mark_skipped`+`add_skip_reason`，进下一个支柱。
- **测试 stub 用 system prompt 关键字路由 4 类调用**：`_StubLLMClient.call_llm` 不持有 agent 引用，但每个 agent 都通过 `system_prompt=self.get_prompt("system")` 传 YAML system prompt。我用 `Decomposer` / `Investigator` / `NoteTaker` 等关键字 + `<<SUGGESTIONS>>` / `want_more` / `subtopics` 等 user prompt 关键字组合识别 kind，在测试里写四套 canned response。这比给每个 agent 单独写 stub 客户端短得多，也保证测试只验证 Loop 自己的编排，不重测 agent 内部细节。
- **`test_loop_satisfies_turnloop_protocol_signature` 用 `inspect.signature` 而非 isinstance**：`TurnLoop` 是 `Protocol` 不是 `runtime_checkable`，无法 `isinstance` 校验。`inspect.signature(DeepResearchLoop.run)` 拿到全部 9 个 keyword-only 参数 + 返回标注是 `ChatMessage` 字符串引用（`from __future__ import annotations`）就够了，足以保证 SA-08 的占位替换不会因签名错位失败。
- 与 AGENTS.md 的偏离：无（cancellation 检查点全部覆盖，metrics 计数与 §12.6 对齐，stream chunk 不进 markdown 体的语义由 Composer 自己保证）。

## Verification
- `python -m compileall new_kernel\deep_research` — 通过（5 个 .py 全部编译成功，无 SyntaxError）
- `python -m pytest -q new_kernel\tests\test_deep_research_loop.py` — 通过 5 例（test_loop_emits_expected_event_sequence / test_loop_returns_chat_message_with_repo_onboarding_kind / test_loop_cancellation_during_investigate_propagates / test_loop_short_branch_with_two_files_repo / test_loop_satisfies_turnloop_protocol_signature）
- `python -m pytest -q new_kernel\tests\test_deep_research_*.py new_kernel\tests\test_contracts.py` — 55 passed in 0.86s（SA-00..SA-07 全部测试 + contracts 测试都绿；SA-07 的 5 个新测试 + SA-01..SA-06 的 50 个旧测试无回归）
- `python -m pytest -q new_kernel\tests\test_*.py` — 65 passed in 4.10s（含 test_app_config.py / test_teaching_experience.py 等其它套件，本次未触及）
- 已知问题 / TODO：`new_kernel/tests/tmp_*` 三个目录是历史遗留（与本会话无关），裸 pytest 会因为它们抛 collection 错误；用 `tests/test_*.py` 通配过滤即可。SA-08 在装配 `DeepResearchLoop` 时直接用 `EventFactory()` 注入到 `event_factory=` 参数即可（5 个 build 分支会自动走注入路径）。

## Spec Alignment
- AGENTS.md §3（4 phase 架构：Phase 0 Triage 纯函数 0 LLM / Phase 1 Decompose 1 LLM / Phase 2 Investigate 顺序 N 支柱 × 每轮 1 LLM + 1 tool + 1 LLM / Phase 3 Compose 流式 1 LLM）
- AGENTS.md §5（cancellation 检查点：Phase 1 入口 / 每个支柱入口 / 每轮 ReAct 入口 / Phase 3 入口 / 流式每 8 chunk）
- AGENTS.md §9.1（公开签名严格匹配 `TurnLoop` Protocol：9 个 keyword-only 参数 + 返回 `ChatMessage`；测试用 `inspect.signature` 校验）
- AGENTS.md §11.1（仅 import `contracts` / `tools.tool_protocol` / `agents.composer` / `agents.decomposer` / `agents.investigator` / `agents.note_taker` / `investigation_policy` / `research_scratchpad` / `triage`，未触 `api.*` / `session.*` / `turn.*` / `events.*` / `agents.teacher` / `agents.reading_agent` / `agents.orient_planner` / `repo.*`）
- AGENTS.md §12.1（cancellation 检查点 5 处全部覆盖）
- AGENTS.md §12.2（工具失败写 scratchpad 不终止 turn / LLM 异常不 swallow 让 TurnRuntime 转 ErrorEvent）
- AGENTS.md §12.5（`AnswerStreamDeltaEvent.delta_text` 只承载 Composer 输出的可见 token；`<<SUGGESTIONS>>` 标记后内容由 Composer 内部捕获，loop 不二次处理）
- AGENTS.md §12.6（每次 LLM 调用 `status_tracker.add_metrics(llm_call=1, emit=False)`，每次工具调用 `tool_call=1, emit=False`；不主动 emit，由 TurnRuntime 终态广播）
