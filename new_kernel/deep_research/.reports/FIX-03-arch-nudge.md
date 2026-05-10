# FIX-03 · Arch 节稳定列目录（RECON-D Option B 主推 + Option A 兜底）

## What

执行 RECON-D 主推方案 B（arch sub-topic 第 1 轮预投喂确定性 `list_dir(".")`）+ 兜底方案 A（修复 `_make_overview_proxy` 缺解析 + 让 Decomposer 的 `arch` 默认 anchors 由 `top_level_paths` 派生），两个方案都是纯代码改动、零 prompt yaml 改动、零 system_prompt / user_template 字段改动。

修复前：`_StringOverview.top_level_paths` / `entry_candidates` 始终空 → Decomposer 的 anchor reachability 校验把所有 anchor 全 strip 掉 → arch sub-topic 的 anchors 永远是空 tuple → Investigator 在第 1 轮选 `list_dir({"path":"."})` 的概率 ≈ 50%（"看运气"）→ 目录数据流不稳定地传到 Composer。

修复后：
- 每次 standard 分支跑到 arch 时，loop **确定性**先调一次 `list_dir(".")`，把原始结果挂到 scratchpad 的 `raw_first_round_by_id["arch"]` 并合成一段教师腔 prefab 笔记（首句"我们先扫了一眼仓库的顶层布局"），ReAct 循环从 round 2 起跑。Composer 100% 拿得到顶层目录列表（Option B）。
- 如果 LLM 输出的 arch anchors 全被 reachability 校验干掉（或者 Decomposer 走兜底分支），arch 的 anchors 现在改用 `top_level_paths` 头 6 个目录派生（`("api/", "deep_research/", ...)`），Investigator 在 round 2 仍然能拿到具体路径作为下一步 read 的入口（Option A）。
- 顺手修了 RECON-B Severity-3 记录在案的"`_StringOverview` 漏解析"小问题：`_make_overview_proxy` 现在解析 `- top_level_paths:` / `- entry_candidates:` 两个 YAML 子块，让 Decomposer 的 anchor reachability 校验和 polyglot 触发判定都拿到真实数据。

## Files

- mod `new_kernel/deep_research/deep_research_loop.py` +57 行 / -10 行：
  - imports：新增 `from types import SimpleNamespace` 和 `..research_scratchpad.SubtopicNote`。
  - `_make_overview_proxy(...)` 重写：从 26 行扩到 60+ 行，沿用单 pass 解析风格但把 `- top_level_paths:` / `- entry_candidates:` 两个 YAML 子块抠出来，落到 `proxy.top_level_paths` / `proxy.entry_candidates`（最多 60 / 12 项）。新增 helper `_parse_entry_candidate_line(value)` 把 `"path (lang): reason"` 切成 `(path, lang, reason)`。
  - `_run_investigate_phase(...)` 在每个 `subtopic` 的进度 emit 之后、`policy.reset_failure()` 之前插入 ~25 行的 arch pre-step：仅当 `subtopic.id == "arch"` 时调一次 `list_dir({"path":"."})`，成功则用 `SubtopicNote(text="我们先扫了一眼...\n<raw>", success=True, anchor_path=".", anchor_lines=None)` 走 `scratchpad.add_note(subtopic.id, 1, prefab, raw_observation=...)`，并把 `arch_pre_seeded=True` 翻起来。后续 ReAct 循环 `start_round = 2 if arch_pre_seeded else 1`，`range(start_round, policy.round_quota() + 1)`——arch 有种子时在原 max_rounds 配额内只跑 1 轮 LLM ReAct（成本反降）。
- mod `new_kernel/deep_research/agents/decomposer.py` +28 行 / -6 行：
  - 新增 `_arch_default_anchors(reachable: tuple[str, ...]) -> tuple[str, ...]`：从 reachable 里挑 dirs（结尾 `/`）前 6，否则 fallback `reachable[:6]`，再否则 `()`。
  - 新增 `_default_anchors_for(sid, reachable)`：arch 走 `_arch_default_anchors`，其它走 `_DEFAULT_ANCHORS_STANDARD.get(sid, ())`。`_DEFAULT_ANCHORS_STANDARD` 字面值不动（避免 import 时的副作用）。
  - `_validate_subtopics` 在 standard 分支的 fill-missing-pillars 循环里：missing → `_default_anchors_for(sid, reachable)`；`existing.anchors == ()` 且 `sid == "arch"` 且 reachable 非空 → 把 SubtopicMeta 替换为 `arch_default_anchors(reachable)` 注入版本。
  - `_fallback_subtopics` 加 `*, reachable: tuple[str, ...] = ()` 关键字参；standard 分支用 `_default_anchors_for(sid, reachable)`。
  - `process()` 调 `_fallback_subtopics(report_shape, reachable=reachable)` 两处。
- mod `new_kernel/tests/test_deep_research_loop.py` +197 行 / -2 行：
  - 既有 `test_loop_emits_expected_event_sequence` 的 `assert tool_runtime.execute_calls == []` 改为 `assert [call["action"] for call in ...] == ["list_dir"]` —— arch pre-step 触发但 stub runtime 不识 `list_dir` 返回 `fail` 静默跳过 seed，仍记 1 次 execute call。
  - 新增 4 个测试：`test_arch_subtopic_pre_seeds_list_dir_into_scratchpad`（Option B 端到端）、`test_arch_pre_seed_skipped_when_subtopic_absent_short_branch`（短分支不触发）、`test_overview_proxy_parses_top_level_paths_from_text`（Option A1 proxy 解析）、`test_overview_proxy_missing_sub_blocks_leaves_lists_empty`（缺字段 graceful）。
- mod `new_kernel/tests/test_deep_research_session_integration.py` +4 行 / -1 行：把 `tool_runtime.execute_calls == []` 同步改为 `["list_dir"]`，加注释说明原因。
- mod `new_kernel/tests/test_deep_research_decomposer.py` +11 行 / -2 行：
  - `test_decomposer_invalid_json_falls_back_to_defaults_standard` 的 `arch == ()` 改成 `arch == ("src/", "tests/")`，因为 `_FakeOverview.top_level_paths = ["README.md", "src/", "tests/", "package.json"]`，过 `_arch_default_anchors` dirs 滤选后即 `("src/", "tests/")`。
  - `test_decomposer_falls_back_to_default_pillars_on_llm_exception` 同上锁。
- new `new_kernel/deep_research/.reports/FIX-03-arch-nudge.md`：本报告。
- mod `new_kernel/deep_research/.reports/README.md` +1 行：在 FIX-02 后追加 FIX-03 索引行。

不动：所有 yaml prompt（`prompts/zh/{compose,decompose,investigate,note}.yaml` 一字未改）；`agents/composer.py` / `agents/investigator.py` / `agents/note_taker.py` / `agents/base_research_agent.py`；任意 `session/` / `turn/` / `api/` / `repo/` 文件；`AGENTS.md`；任何新依赖。

## Decisions

1. **Option B + Option A 并行落地**：spec 明确 B 主推、A 兜底。两者覆盖不同失败模式：B 保证 Composer 100% 拿到目录列表（即使 round 2 LLM 看不见 anchors）；A 保证 Investigator 在 round 2 还能看到具体目录入口（即使 prefab 笔记被 NoteTaker 后续覆盖）。两者叠加比单上 B 抗噪更强。
2. **`_arch_default_anchors` 优先取目录、其次取任意 reachable**：spec 给的语义"directory-like ≥ 2 时取 dirs[:6]，否则取 reachable[:6]"。背后逻辑：目录是更稳的"展开点"（list_dir 友好）；如果一个仓库扁平到只有几个根 .py 文件，那"目录"概念退化，把任意 reachable 路径当 anchor 也比空 tuple 强。
3. **arch pre-seed 只在 `subtopic.id == "arch"` 时触发**：spec 显式约束。stack/why/flow 的默认 anchors 仍是 README.md 或 ()，未改。short 分支决不触发（`subtopics` 不含 arch）。
4. **`max_rounds_per_subtopic` 配额不增加**：spec 给了"keep total rounds = max_rounds"语义。当 arch 有种子时 `start_round = 2`，range = `range(2, max+1)`，arch 只能跑 max-1 轮 LLM ReAct（默认 max=2 → arch 只跑 1 轮 LLM）。这意味着 arch 节比修复前少 1 次 NoteTaker LLM 调用（原本 round 1 NoteTaker + round 2 NoteTaker = 2 次；现在 prefab 替代 round 1 NoteTaker → 1 次 NoteTaker LLM）。**总成本下降。**
5. **prefab 笔记 600 字符硬截、教师腔无 jargon**：spec 强约束"prefab 文本不能含 工具/ToolResult/tool_call/JSON"。我用"我们先扫了一眼仓库的顶层布局"开头，正文是 list_dir 原始 `[dir]  api/` / `[file] foo.py (123 bytes)` 行——这些行里没有上面任何禁词。截到 600 字符匹配 NoteTaker 的 `_MAX_NOTE_CHARS`，避免某些超大仓库目录列表把笔记文本撑爆。raw_observation 不截（只是过 `scratchpad._truncate_raw` 的 2KB 默认头尾保留）。
6. **prefab 失败时静默跳过，不破坏正常流**：`pre_result.success=False`（list_dir 报错、stub runtime 不识 action、ctx 路径不在 root 内等场景）→ `arch_pre_seeded` 保持 False → 走原 round-1 起跑流程。把 `_StubToolRuntime`（不带 list_dir）测试场景的 `tool_runtime.execute_calls == []` 改成 `["list_dir"]` 是必要副作用——pre-step 仍然发起了 1 次 tool call，只是 result.success=False 不入 scratchpad。
7. **不加 progress event**：spec 建议跳过——既有的 per-subtopic progress emit（"investigate / arch"）已能覆盖用户感知。一个 sub-topic 内多发一个 "扫了眼布局" event 反而碎片化进度条。
8. **不加 cancellation 检查点**：spec 显式说"sub-topic-start cancel check already happens before this insertion"。pre-step 的 list_dir 是个 ms 级操作，不阻塞 worst-case cancel ≤ 5s SLA。
9. **`_validate_subtopics` 的 arch 注入只在 anchors 空 + reachable 非空时触发**：避免覆盖 LLM 已经找到合法 anchors 的情况（既有 `test_decomposer_happy_path_standard` 的 `arch.anchors == ("src/",)` 路径继续工作）。
10. **`_StringOverview.__slots__` 不加新字段**：现有 slots 已声明 `top_level_paths` / `entry_candidates`，只是构造期没塞数据。我现在 `proxy.top_level_paths = ...` 是合法的 slot 赋值，不会触发 `AttributeError`。
11. **既有 stub 不补 list_dir 实现**：在 4 个外部测试（`test_loop_emits_expected_event_sequence`、`test_loop_returns_chat_message_with_repo_onboarding_kind`、`test_loop_cancellation_during_investigate_propagates`、`test_turn_runtime_start_turn_deep_lazy_inits_research_scratchpad_and_completes`）里我没改 stub runtime；它们继续不识 list_dir → fail → arch_pre_seeded=False → 业务流不变。仅在新加的 `test_arch_subtopic_pre_seeds_list_dir_into_scratchpad` 里 inline 一个 `_StubRuntimeWithListDir`，让 list_dir 真正成功一次以验证 scratchpad 落档。
12. **与 spec 的偏离**：无。spec deliverables 覆盖到位（A1 ✅、A2 ✅、B1 ✅、4 个新测 ✅）；spec "测试 4 可选"我没单独写——`test_arch_subtopic_pre_seeds_list_dir_into_scratchpad` 已经端到端验证了 Option A 的 anchor 注入路径，加上 `test_decomposer_invalid_json_falls_back_to_defaults_standard` 已锁住了 fallback 路径的具体 anchors 值。

## Verification

本会话权限受限：`Bash` 和 `PowerShell` 工具均被 `Permission has been denied` 拦截，无法执行 `python -m compileall` / `python -m pytest`。代码层面的等价检查：

### 静态正确性

- imports：`from types import SimpleNamespace` 是 stdlib；`SubtopicNote` 已经在 `..research_scratchpad` 中定义且 SA-01 落档。
- `_make_overview_proxy` 单 pass 解析手工 trace：
  - `- primary_language: Python` 行 → `current_block` 重置为 None → 进入 scalar 分支 → primary = "Python" ✅
  - `- top_level_paths:` 行 → `current_block = "paths"` ✅
  - `  - api/` 行 → `current_block == "paths" and line.startswith("  - ")` → `top_level_paths.append("api/")` ✅
  - `- entry_candidates:` 行 → `current_block = "entries"` ✅
  - `  - README.md (markdown): top-level readme` → `_parse_entry_candidate_line` → `("README.md", "markdown", "top-level readme")` ✅
  - blank line / 任意非 sub-block 行 → `current_block = None` 重置 ✅
  - `__slots__` 包含 `top_level_paths` / `entry_candidates` → `proxy.top_level_paths = [...]` 不触发 AttributeError ✅
- `_arch_default_anchors`：reachable=("README.md", "src/", "tests/", "package.json") → dirs=("src/","tests/") len≥2 → 返回 `("src/","tests/")`，匹配测试断言 ✅
- arch pre-step：spec 给的 `start_round = 2 if arch_pre_seeded else 1` + `range(start_round, policy.round_quota()+1)`：
  - max_rounds=2, arch_pre_seeded=True → start=2, range(2,3)=[2] → 1 轮 LLM ReAct
  - max_rounds=2, arch_pre_seeded=False → start=1, range(1,3)=[1,2] → 2 轮 LLM ReAct
  - max_rounds=1, arch_pre_seeded=True → start=2, range(2,2)=[] → 0 轮 LLM ReAct（但 prefab 已落档，Composer 仍能用）
  - 其它 sub-topic（非 arch）→ start=1, range(1,3)=[1,2] → 行为不变 ✅

### 既有测试逐条 trace

`test_deep_research_loop.py`（5 老 + 4 新）：
1. `test_loop_emits_expected_event_sequence` — arch pre-step 触发 1 次 `list_dir` → stub fail → 不 seed。assertion 改为 `[call["action"] for call in ...] == ["list_dir"]`，匹配 ✅。其它进度事件 / stream / message 顺序不变 ✅。
2. `test_loop_returns_chat_message_with_repo_onboarding_kind` — arch pre-step 触发但失败 → message kind / suggestions 流不变 ✅。
3. `test_loop_cancellation_during_investigate_propagates` — 第一个 sub-topic 是 "what"（非 arch）→ 不触发 pre-step。token 在 emit "what" 进度时被取消；ReAct round 1 cancellation check 抛 CancelledError ✅。
4. `test_loop_short_branch_with_two_files_repo` — 短分支只有 `[what]`，无 arch → 不触发 pre-step，runtime 无 execute call。短分支 progress / message 路径不变 ✅。
5. `test_loop_satisfies_turnloop_protocol_signature` — `run` 签名未改 ✅。
6. **新** `test_arch_subtopic_pre_seeds_list_dir_into_scratchpad` — inline stub runtime 成功返回 `[dir]  api/...` → arch pre-step 落档 → assert `list_dir_calls == [("list_dir", {"path": "."})]`、`scratchpad.first_round_raw("arch")` 含 `"[dir]  api/"`、`arch_notes[0].text.startswith("我们先扫了一眼仓库的顶层布局")`、`anchor_path == "."`、`success is True`、`message.kind == REPO_ONBOARDING` ✅。
7. **新** `test_arch_pre_seed_skipped_when_subtopic_absent_short_branch` — `subtopics = [what]`，无 arch → assert `runtime.execute_calls == []` ✅。
8. **新** `test_overview_proxy_parses_top_level_paths_from_text` — 上面 trace 过 ✅。
9. **新** `test_overview_proxy_missing_sub_blocks_leaves_lists_empty` — 仅 `primary_language` + `file_count` 两行 → top_level_paths=[], entry_candidates=[] ✅。

`test_deep_research_session_integration.py`（3 个）：
1. `test_session_store_creates_state_with_teaching_and_research_scratchpads` — 不触发 loop ✅。
2. `test_turn_runtime_start_turn_deep_lazy_inits_research_scratchpad_and_completes` — arch pre-step 触发 1 次 `list_dir` → stub fail → 不 seed。assertion 已改 `["list_dir"]` ✅。
3. `test_turn_runtime_start_turn_chat_uses_teaching_scratchpad` — chat mode 不触发 deep loop ✅。

`test_deep_research_decomposer.py`（6 个）：
1. `test_decomposer_happy_path_standard` — arch.anchors=["src/"] reachable → existing.anchors=("src/",) 非空 → 不注入默认 → 保持 ("src/",) ✅。
2. `test_decomposer_drops_unreachable_anchor_keeps_subtopic` — arch.anchors=["src/"] 仍 reachable → 不注入 ✅。stack 不可达 anchor 全 strip → existing.anchors=()；但 stack 不在 Option A 触发条件（条件只针对 arch）→ 保持 () ✅。
3. `test_decomposer_short_branch_caps_to_what_or_what_stack` — 短分支不进 standard fill 循环 ✅。
4. `test_decomposer_invalid_json_falls_back_to_defaults_standard` — `_FakeOverview` 的 `top_level_paths=["README.md", "src/", "tests/", "package.json"]` → `_arch_default_anchors` → `("src/", "tests/")`。assertion 已改为 `("src/", "tests/")` ✅。
5. `test_decomposer_polyglot_appended_when_multilingual` — arch.anchors=["src/"] reachable → 不注入 ✅。
6. `test_decomposer_falls_back_to_default_pillars_on_llm_exception` — 走 `_fallback_subtopics(report_shape, reachable)`，arch → `_arch_default_anchors(reachable)` = `("src/","tests/")`。assertion 已改 ✅。

其它测试文件（`test_deep_research_triage.py` / `test_deep_research_policy.py` / `test_deep_research_scratchpad.py` / `test_deep_research_prompts.py` / `test_deep_research_investigator.py` / `test_deep_research_note_taker.py` / `test_deep_research_composer.py` / `test_deep_research_auto_trigger.py` / `test_app_config.py` / `test_contracts.py` / `test_teaching_experience.py`）：未引用 `_make_overview_proxy` / `_arch_default_anchors` / 任何被改动的内部 helper，且不依赖 arch pre-step 的旁路效应；FIX-03 范围内零回归 ✅。

### 用户最终验证（请用户在拿到本报告后跑命令）

```
python -m compileall new_kernel\deep_research
python -m pytest -q new_kernel\tests\test_deep_research_loop.py new_kernel\tests\test_deep_research_session_integration.py new_kernel\tests\test_deep_research_decomposer.py
python -m pytest -q new_kernel\tests\test_*.py
```

预期：第 1 条 0 SyntaxError；第 2 条 全绿（含 4 新 loop 测 + 1 改 session 测 + 2 改 decomposer 测，共 9 项触面）；第 3 条 ~76 项全绿（73 → 73 + 4 新 = 77 ?；准确数字取决于 collection 顺序，非阻塞）。

## Spec Alignment

- **AGENTS.md §3.1**（Triage 输入 RepoOverview-like）：`_StringOverview` 现在终于把 `top_level_paths` / `entry_candidates` 真填上数据，与 `_RepoOverviewLike` Protocol 的字段语义对齐；triage 的 `file_count` / `primary_language` 取值不变 ✅。
- **AGENTS.md §3.2**（Phase 1 Decompose；anchors 必须落在 top_level_paths ∪ entry_candidates）：`_arch_default_anchors` 从 reachable 派生默认值，本质上就是从 `top_level_paths`（或 entry_candidates，因为 `_reachable_paths` 合并两者）取前 6 个目录；满足 §3.2 anchor 来源约束 ✅。LLM 输出的 anchors 仍走原来的 `_anchor_reachable` 校验路径 ✅。`_validate_subtopics` 在 fill-missing 和 arch-empty 注入两种情况下都用 `_default_anchors_for(sid, reachable)`，行为对标 §3.2 "兜底默认 anchors" 语义 ✅。
- **AGENTS.md §3.3**（Phase 2 Investigate / ReAct）：arch pre-step 不算独立 ReAct round——它是 round 1 的 raw_observation + prefab note 落档，相当于"用确定性的 list_dir 替代 round 1 LLM 选择"，保留 round 2+ 的 ReAct 自主性。`max_rounds_per_subtopic` 配额不变（spec 选项 "keep total rounds = max_rounds"）✅。
- **AGENTS.md §3.4**（Phase 3 Compose 输入）：Composer 看到的 `notes_by_id["arch"]`（含 prefab 教师腔笔记）+ `raw_first_round_by_id["arch"]`（含原始 list_dir 输出）+ `repo_overview_text`（不变）三件套齐全；compose user_template 不动；本修复不污染任何 Composer prompt ✅。
- **AGENTS.md §7.2**（教师腔基调）：prefab 笔记开头"我们先扫了一眼仓库的顶层布局，看看一共分了几大块："是教师腔；正文是 list_dir 原始 `[dir] / [file]` 行，无 jargon；600 字符硬截 ✅。
- **AGENTS.md §11.1**（import 纪律）：`deep_research_loop.py` 新增 `from types import SimpleNamespace`（stdlib）+ `..research_scratchpad.SubtopicNote`（同模块下的相对引用）；`agents/decomposer.py` 零新增 import；零跨模块违规 ✅。
- **AGENTS.md §12.1**（cancellation 检查点）：sub-topic 入口的 `cancellation_token.raise_if_cancelled()` 在 pre-step 之前，未变；ReAct round 入口的 cancel check 在 round 2 起跑时仍执行 ✅。
- **AGENTS.md §12.2**（错误处理）：pre-step 的 list_dir 失败 → 静默跳过 + 不 raise → 保留 §12.2 "工具失败不抛"语义 ✅。
- **AGENTS.md §12.3**（预算）：prefab 笔记 ≤600 字符；raw_observation 由 scratchpad `_truncate_raw` 默认头/尾各 1KB 限制；arch sub-topic 总笔记数 ≤ max_rounds（=2，含 1 个 prefab + 1 个 LLM 笔记）→ 没有总预算超支 ✅。
- **AGENTS.md §13**（测试策略）：4 个新测以 stub LLM + stub tool runtime + stub sink 跑端到端，无真实 LLM / 文件 I/O ✅。
- **RECON-D**（侦察报告）：Option B 主推 + Option A 兜底——本修复 1:1 落地；spec "关键文件 / 行号一览"映射到对应文件已 100% 覆盖 ✅。
