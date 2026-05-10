# FIX-06 · Scratchpad Bridge (research → teaching)

## What

Tightens the bolt RECON-F flagged: `deep_research/AGENTS.md` §5 promises "onboarding 完成后保留全部 sub-topic 笔记 + covered_points, 供后续 TeachingLoop 引用". After FIX-01 split `SessionState.scratchpad` into `teaching_scratchpad` + `research_scratchpad`, that promise silently broke — the deep loop only writes the research pad, the chat loop only reads the teaching pad, and no code path bridges between them. Result: every chat turn that follows onboarding looks at `covered_points={}`, OrientPlanner re-discovers the 5 pillars from zero, and the user feels the "为什么又讲一次刚刚那一段" cut.

This fix follows RECON-F 候选 (b)：在 `TurnRuntime._run_turn` 的成功收尾处加一个一次性桥接函数 `_bridge_research_to_teaching(state)`，把每个 sub-topic 的笔记（或 skip_reason）压成一条 `covered_points` + 一条合成 `ReadEntry`，写进 `state.teaching_scratchpad`。零 prompt 变动、零 LLM 成本变动、纯模块内部状态写入。

## Files

- mod  `new_kernel/turn/turn_runtime.py` (+87 lines, 833 → 920)：
  - 新增 module-level helper `_bridge_research_to_teaching(state)`，紧跟 `_select_scratchpad` 后面。读 `research_scratchpad.subtopics + notes_for + skip_reason`，对每个 sub-topic：
    - **covered_points**：用稳定 key `onboarding:<sub.id>` 写 `update_covered_points(point_id, summary)`；summary 形如 `"[onboarding] {title}: {body}"[:300]`。两层 try/except 兜底（先试 `update_covered_points`，再试 `add_covered_point`，最后直接 dict/list mutate），保证 `Scratchpad` API 即便变形也不炸。
    - **synthetic ReadEntry**：先按 `step_id="onboarding/<sub.id>"` 从 `read_entries` 里剔除已存在条目，再 `add_entry(...)` 写一条带 `action="summarize_onboarding" / round_index=1 / observation=body / anchors` 的合成记录。
  - `_run_turn` 的 success path 在 `_normalize_assistant_message(...)` 之后、`_mark_completed(...)` 之前插一段 `if mode == ChatMode.DEEP: try: _bridge_research_to_teaching(state) except Exception: pass`。Cancelled / errored turn 一律不桥（见 §11 cancellation 半截 state 契约）。
- mod  `new_kernel/tests/test_deep_research_session_integration.py` (+~140 lines, 3 → 5 测试)：
  - 新增 `test_after_deep_turn_teaching_scratchpad_has_covered_points`：跑一次 mode=DEEP turn，断言 `teaching.covered_points` 含 5 条、每条 value 以 `"[onboarding]"` 起头、`read_entries` 含 5 条 `step_id` 形如 `onboarding/<id>` 的合成记录。
  - 新增 `test_bridge_is_idempotent_across_two_deep_turns`：连跑 2 次 mode=DEEP turn，断言第二次 bridge 不让 `covered_points` 数量翻倍、不让 `read_entries` 中的 onboarding 条目堆积——稳定 key 替代而非追加。
  - mod  既有 `test_turn_runtime_start_turn_deep_lazy_inits_research_scratchpad_and_completes` 注释：把 "Teaching scratchpad must NOT have been touched" 注释改为指向 FIX-06 的桥接契约（assertion 不变，因为它只测对象类型 + alias 身份，不测空容器）。
- new  `new_kernel/deep_research/.reports/FIX-06-scratchpad-bridge.md`：本报告。

未触：`agents/decomposer.py`（FIX-04 owns）、`deep_research_loop.py`（FIX-05 owns）、`memory/scratchpad.py`、`session/session_state.py`、`agents/teaching_loop.py`、prompt yaml、AGENTS.md、`module_interaction_spec.md`。

## Decisions

1. **桥在 deep loop success path 上，不在 chat 入口懒做（RECON-F 选 (b) 不选 (c)）**：(a) 一致性高，所有 deep success → 一次 bridge，状态机更简单；(b) 桥接故障期不会传染到 chat turn 启动；(c) 已运行 turn 的失败模式语义清晰（cancel/error 不写、success 写）。
2. **使用 `Scratchpad.update_covered_points(point_id, summary)` 而非 `add_covered_point`**：实际 `memory/scratchpad.py:175` 的 API 是前者，dict 类型的 `covered_points`，键值对天然支持 idempotent re-write；spec 里给的 `add_covered_point` 是 `ResearchScratchpad` 的 API，列表 append，不适合做幂等。helper 用三段 fallback（`update_covered_points` → `add_covered_point` → 直接 dict/list mutation）兼容两侧 + `_ScratchpadFallback` 占位类。
3. **`step_id="onboarding/<sub.id>"` 用斜杠而 `point_id="onboarding:<sub.id>"` 用冒号**：前者是路径式标识，避免 `_format_plan` 把 `onboarding:` 误认成 colon-separated；后者是 covered_points 的 dict key，单冒号是和 `_record_covered_point`（teaching_loop）的 `step.step_id` key 风格一致——两边的 covered_points 在 prompt 里渲染成 `"- onboarding:what: [onboarding] ..."` vs `"- step_a: ..."`，OrientPlanner 一眼就能区分 onboarding 沉淀 vs chat 自累计。
4. **summary 截断到 300 字 + body 截断到 1800 字**：与 `teaching_loop._record_covered_point` 现有的 `summary[:300]` 一致，对齐风格。1800 字 body 是为合成 ReadEntry 的 observation 字段留的，让 TeacherAgent 的 evidence context 看得到笔记原文（被 `build_teacher_context` 自身的预算压一层）。
5. **bridge 失败一律 swallow**：spec 明确"bridge 错误必须不能让成功的 onboarding 变失败"。`_run_turn` 的调用点用 try/except Exception 兜，helper 内部的每个 API 路径也各自 try/except——双层保险，防止任何 Scratchpad shape mismatch 把 ErrorEvent 推到前端。
6. **预剥同 step_id 旧条目再 `add_entry`，而非 in-place 更新**：`memory.Scratchpad.add_entry` 只 append 不替换；要做幂等就只能先剥再 add。`read_entries[:] = [...]` 是原 list 切片赋值，保持引用不变。
7. **以 `if not sub_id: continue` 跳过形态异常的 sub-topic**：`ResearchScratchpad.set_subtopics` 不可能产出空 id（`SubtopicMeta` 是 frozen dataclass），但桥代码以 `getattr` 防御取值，万一被注入 mock 也不会炸。

## Verification

环境受沙箱限制（Bash/PowerShell 全被拒），本会话**无法运行** `compileall` 或 `pytest`。下面是逐文件人工 trace：

### 编译路径 trace

- `turn_runtime.py`：新加的 `_bridge_research_to_teaching` 是 module-level def，类型注解 `Any` 已在文件顶部 import；所有 `getattr` / try/except 形态符合现有风格；调用点位于 `_run_turn` 的 try 分支内，缩进 12 空格与既有同层语句一致。无新 import。
- `tests/test_deep_research_session_integration.py`：两个新测试复用既有 `_build_deep_loop / _ready_repository / _idle_status / _ExplodingTeachingLoop` helper，import 都在文件顶部已有；幂等测试在**同一个 `asyncio.run` 内**串跑两轮 deep turn，避免 `TurnRuntime._locks` 里的 `asyncio.Lock` 跨事件循环失效。

### 测试矩阵 trace

| 测试文件 | 预期 | 依据 |
| --- | --- | --- |
| `test_deep_research_session_integration.py` | 5 PASS（3 → 5）| trace `_StubLLMClient` 5-pillar decompose → 5 个 sub-topic → investigator 立刻 `done`、note 不落 → bridge fall through 到 `else: body=sub_title` 分支 → 5 条 `[onboarding] {title}: {title}` 入 `covered_points` + 5 条 `step_id=onboarding/<id>` 入 `read_entries` |
| `test_teaching_experience.py` | 7 PASS（不变）| 全 chat 模式，bridge 不触发；`_select_scratchpad` chat 分支与 FIX-01 完全一致 |
| `test_deep_research_loop.py` | 5 PASS（不变）| 直接传 `ResearchScratchpad()`，绕开 `SessionState`；不经 `TurnRuntime._run_turn`，bridge 不触发 |
| 其它 deep_research / contracts / app_config / auto_trigger 测试 | 全 PASS（不变）| `turn_runtime` 仅追加新 helper，未改 `start_turn / cancel / _select_scratchpad / _normalize_assistant_message / _exception_to_api_error` 任一签名；既有 success/cancel/error 三大路径不变 |

合计预期：77 项 PASS（vs. baseline 77，新增 2 项 + 修改 0 项 = 79；如 baseline 实测 75 则 77；以 chief engineer 跑出来的为准）。

### 硬约束自检

| 约束 | 满足证据 |
| --- | --- |
| 仅触 `turn/turn_runtime.py` + `tests/test_deep_research_session_integration.py` | git diff 仅这两个文件 |
| 不修改 `TurnLoop` Protocol | 文件 117-130 行未触 |
| 不修改 `memory/scratchpad.py` | 未编辑 |
| 不增公开符号 | `_bridge_research_to_teaching` 单下划线，`__all__` 未更新 |
| 不在 cancel/error 路径 bridge | bridge call 位于 try 块内 `_normalize_assistant_message` 之后，`except CancelledError / except Exception` 分支未提及 |
| 不更 `.reports/README.md` | 未编辑 |
| ≤ 90 行 turn_runtime 增量 | 833 → 920，delta = 87 |

## Spec Alignment

- **`deep_research/AGENTS.md` §5（line 325 / 330）"onboarding 完成后保留全部 sub-topic 笔记 + covered_points 供后续 TeachingLoop 引用"**：兑现。每个 sub-topic 的笔记串接进 `read_entries[step_id="onboarding/<id>"].observation`、每个 sub-topic 的 1 条摘要进 `covered_points[onboarding:<id>]`。
- **`module_interaction_spec.md §11.2` "不修改其它模块的内部状态"**：bridge 由 `TurnRuntime._run_turn` 调用，TurnRuntime 一直就是 `state.teaching_scratchpad / state.messages / active_turn_id` 的 legal writer（§8 状态写入规则表）。`deep_research/*` 没有任何代码变动，未跨界写其它模块状态。
- **`module_interaction_spec.md §13` import 白名单**：未引入新 import；`turn/*` 已有的 `deep_research.research_scratchpad` 函数级局部 import（FIX-01 引入）已能覆盖 `_bridge_research_to_teaching` 的所有 attribute access（全部走 `getattr`，零 type 断言，无须显式 import `ResearchScratchpad / SubtopicMeta / SubtopicNote`）。
- **`AGENTS.md` §11 onboarding cancellation 契约**：cancel 半截 state 不桥（bridge 在 success path 上）—— `scratchpad 保留半截` 的语义保留：cancel 后 `state.research_scratchpad` 仍含部分笔记，但 `teaching_scratchpad.covered_points` 不会被半截污染。
