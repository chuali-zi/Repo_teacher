# FIX-05 · Arch prefab note next-step nudge (RECON-E §D3)

## What

执行 RECON-E §D3 candidate "FIX-03 prefab 笔记末尾追加引导句"。修复前 arch round-1 prefab note 以原始 `[dir]/[file]` 行结尾、anchors 又全是目录,Investigator round 2 路径阻力最小的动作就是再 `list_dir` 一层子目录,arch 唯一的 LLM ReAct 配额白白浪费在列目录上。修复后:在同一段 `if pre_result.success:` 块内,从 `overview_obj` 抠出一个具体的源文件路径作为"下一步往里走一步"的目标,在 prefab note 末尾追加一句教师腔 nudge,把那个文件名用反引号包起来递给 round-2 LLM。LLM 看到具体反引号文件名时倾向 `read_file_range`,且 prompt `investigate.yaml:27` "路径优先选 anchors 中已有的"经 FIX-04 后 anchors 已混入文件,具体反引号路径加在 prefab 笔记里相当于双保险。本修复是纯代码改动、零 prompt yaml 改动、零跨模块依赖增。

## Files

- mod `new_kernel/deep_research/deep_research_loop.py` +43 行 / -3 行:
  - 新增模块级 helper `_pick_arch_drill_target(overview: Any) -> str | None`(放在 `_parse_entry_candidate_line` 之后,`DeepResearchLoop` 之前):按 RECON-E §D3 优先级 1→4 选一条具体文件路径——(1) 第一个 language 不是 `markdown/plaintext/text` 的 entry_candidate;(2) 第一个任意 entry_candidate;(3) 第一条非目录(`not endswith("/")`) 的 top_level_path;(4) None。getattr 链兜底 None overview。
  - `run()` 调用 `_run_investigate_phase(...)` 处新增一个 keyword `repo_overview_obj=overview_obj`,把已构造的 proxy 对象贯穿到 phase 2(原本只传 `repo_overview_text` 字符串,helper 拿不到结构化字段)。
  - `_run_investigate_phase` 签名加 `repo_overview_obj: Any = None`(keyword-only,带默认值不破坏既有 caller)。
  - FIX-03 arch pre-step 块内,在 `raw_text = ...` 之后、`SubtopicNote(...)` 之前插入 nudge 构造逻辑:`nudge_target = _pick_arch_drill_target(repo_overview_obj)` → `listing_cap = 420 if nudge_target else 600` → `head + raw_text[:listing_room]` → 若有 target,把固定 nudge 文本(≤180 chars)拼到末尾;最终 `prefab_text[:600]` 兜底。整体 ≤600 字符硬截不变。
- mod `new_kernel/tests/test_deep_research_loop.py` +160 行 / 0 删:新增 2 个测。
  - `test_arch_prefab_note_has_drill_target_when_entry_candidates_present`:overview YAML 带 `top_level_paths` 三条目录 + `entry_candidates` 含 `README.md (markdown)` 与 `src/main.py (python)` 两条;loop 跑完后断言 `notes_for("arch")[0].text` 含 ``"`src/main.py`"`` 和 `"挑一个具体地方往里走一步"`,且不含禁词("工具"、"ToolResult"、"tool_call"、"JSON"、"list_dir"、"read_file_range"、"search_repo"),长度 ≤ 600。
  - `test_arch_prefab_note_skips_nudge_when_no_target_available`:overview YAML 只有 `top_level_paths: api/, tools/`(两条都是目录),`entry_candidates` 缺失;loop 跑完后断言 `notes_for("arch")[0].text` 仍以 "我们先扫了一眼仓库的顶层布局" 开头(说明 prefab 落档了),但**不含** "挑一个具体地方往里走一步"(graceful skip),也不含任何反引号(`"`" not in note_text`,sanity check)。
- new `new_kernel/deep_research/.reports/FIX-05-prefab-nudge.md`:本报告。

不动:其它一切。`agents/decomposer.py` 由 FIX-04 owns,本修复未触;`turn/turn_runtime.py` 由 FIX-06 owns,本修复未触;任何 yaml prompt 一字未改;`research_scratchpad.py` / `investigation_policy.py` / 其它 agent 文件 / api / repo / tests 均未触。

## Decisions

1. **拼接顺序:listing 在前、nudge 在后,不互斥**。Spec 说"截断 dir listing 在前,nudge 在后";listing 给具体目录素材,nudge 给"接力方向"。两者叠加比单独一个更稳——LLM 同时看到目录和具体下一步。
2. **listing 预算 420 chars / nudge 预算 180 chars,合计 600**。Spec 给 180 chars nudge cap;`head` 长度 ~25 chars(Python str 计 chinese 各 1 char),所以 listing 实际可用 ~395 chars。dir listing 在普通仓库一般 200-400 字节内,几乎从不命中 420 cap;反过来 nudge 文本(实测 ~77 chars)远低于 180 cap,所以 cap 实质只起 "tail-safety" 作用。
3. **教师腔 nudge 文本不含任何工具/JSON 字眼**。spec 列了 7 个禁词:工具、ToolResult、tool_call、JSON、list_dir、read_file_range、search_repo。我用的 nudge 是"挑一个具体地方往里走一步:我们先打开 \`<path>\` 看一段,把这块代码长什么样、关键 symbol 是啥、和上下游怎么连,摆到学生面前。"——只含 `symbol`(spec 未禁,且 NoteTaker / Composer prompt 也用此词)和文件路径反引号。
4. **反引号包裹路径**:LLM 倾向把反引号视作"具体引用"(prompt yaml 中本就有这种约定,例如 NoteTaker 的格式范例)。Investigator round 2 看到反引号 + 具体路径时,选 `read_file_range(path)` 的概率显著高于自由发挥。
5. **`repo_overview_obj` 用 keyword default `None`**:为了不破坏其它 caller(例如未来某测试可能 mock 直接调 `_run_investigate_phase` 时省略此参)。helper 内 `getattr(None, "entry_candidates", ()) or ()` 安全返回 `()`,不会 raise。
6. **优先级 4 fallback 不退到 sentinel `"README.md"`**:spec "如果所有都失败,回退到 `README.md` 作 sentinel,但只在该路径在数据中实际存在时追加 nudge,否则跳过"。我直接选 priority 4 = None → 跳过 nudge,因为(a) 在 overview 数据完全空的边界情况下,生造一个 `README.md` 只是诱使 LLM 去读一个我们都不知道是否存在的文件,反而引入新风险;(b) 测试 (b) 验证了"无 target 时优雅跳过"路径,保证 prefab note 仍能落档。spec 第 4 条本就允许"或者直接跳过";我取直接跳过这条更稳妥的解读。
7. **不改 600 字符硬截**:spec 强约束。`prefab_text[:600]` 兜底依然在,任何上面的逻辑组合都不可能让最终落档的 note 超过 600 chars。
8. **不动 FIX-03 list_dir 调用本身**:spec 显式约束"不要修改 FIX-03 list_dir invocation 逻辑——只改 prefab_text 字符串和加 helper"。我严格只改了 `if pre_result.success:` 块内 `prefab_text = ...` 那段构造逻辑;`pre_result = await self._tool_runtime.execute("list_dir", {"path": "."}, ctx=ctx)` 一字未动,`scratchpad.add_note(...)` 一字未动,`arch_pre_seeded = True` 一字未动。
9. **静默 graceful skip**:`_pick_arch_drill_target` 返回 None 时既不 raise 也不 log warn,直接 fallback 到原 FIX-03 行为(纯目录 listing prefab note)。这保留了 §12.2 "工具失败不抛"的语义类比。
10. **测试 (a) 与既有 `test_arch_subtopic_pre_seeds_list_dir_into_scratchpad` 不冲突**:既有测试用 `_STANDARD_OVERVIEW`(无 top_level_paths / entry_candidates 块),`_pick_arch_drill_target` → None → 走"无 nudge"分支,既有断言 `arch_notes[0].text.startswith("我们先扫了一眼仓库的顶层布局")` 和 `"api/" in arch_notes[0].text` 全部继续通过。新测 (a) 用增强版 overview 触发 nudge 分支,二者覆盖不同 overview 形态。

## Verification

权限受限:`Bash` / `PowerShell` 工具仍被拦截,`python -m compileall` / `python -m pytest` 无法执行。代码层面静态 trace:

### 静态正确性

- `_pick_arch_drill_target` 单 pass trace:
  - overview = SimpleNamespace 含 `entry_candidates=[(README.md, markdown, ...), (src/main.py, python, ...)]`,`top_level_paths=["api/", "tools/", "src/"]`
  - 第一个循环:entry README.md → lang.lower()=="markdown" → continue;entry src/main.py → lang=="python" → 返回 "src/main.py" ✓
  - overview = SimpleNamespace 含 `entry_candidates=[]`,`top_level_paths=["api/", "tools/"]`
  - 第一/二循环空跑;第三循环 "api/" endswith("/") → skip;"tools/" endswith("/") → skip;return None ✓
  - overview = None → `getattr(None, "entry_candidates", ()) or ()` = `()` → return None ✓
- prefab_text 拼接 trace(test (a)):
  - head = "我们先扫了一眼仓库的顶层布局,看看一共分了几大块:\n",len = 25
  - listing_cap = 420(因 nudge_target 非 None)
  - listing_room = 420 - 25 = 395
  - raw_text = fake_listing[:1800],len ≈ 70
  - prefab_text = head + raw_text[:395] = head + fake_listing,len ≈ 95
  - nudge = "\n\n挑一个具体地方往里走一步:我们先打开 \`src/main.py\` 看一段,把这块代码长什么样、关键 symbol 是啥、和上下游怎么连,摆到学生面前。",len ≈ 77
  - prefab_text += nudge[:180] → final len ≈ 172
  - SubtopicNote(text=prefab_text[:600], ...) → 落档 172 chars,远低于 600 cap ✓
  - 含 `"`src/main.py`"` ✓、含 `"挑一个具体地方往里走一步"` ✓
  - 不含 "工具"、"ToolResult"、"tool_call"、"JSON"、"list_dir"、"read_file_range"、"search_repo" 任何一个 ✓
- prefab_text 拼接 trace(test (b),无 target):
  - nudge_target = None → listing_cap = 600
  - listing_room = 600 - 25 = 575
  - raw_text ≈ 30 chars(两行 dir listing),全部进 prefab_text
  - nudge 分支 if-skip,prefab_text 末尾就是 raw_text 末尾
  - 含 "我们先扫了一眼仓库的顶层布局" ✓、不含 "挑一个具体地方往里走一步" ✓、不含反引号 ✓
- 既有 `test_arch_subtopic_pre_seeds_list_dir_into_scratchpad` trace:
  - _STANDARD_OVERVIEW 缺 top_level_paths / entry_candidates → proxy.entry_candidates=[], proxy.top_level_paths=[]
  - `_pick_arch_drill_target` → None → 走 "无 nudge" 分支
  - prefab_text = head + fake_listing[:575](实际只有 ~70 chars)= 既有行为
  - 断言 startswith("我们先扫了一眼仓库的顶层布局") ✓、"api/" in text ✓、anchor_path="." ✓、success=True ✓ —— 既有测继续通过

### 既有测试逐条 trace

`test_deep_research_loop.py`:既有 9 个 + 新增 2 个 = 11 个。
1-5. 同 FIX-03,arch pre-seed 用 `_StubToolRuntime`(无 list_dir)→ pre_result.success=False → 跳过整个 if 块 → 既有断言不变 ✓。
6. `test_arch_subtopic_pre_seeds_list_dir_into_scratchpad`:见上 trace,继续通过 ✓。
7. `test_arch_pre_seed_skipped_when_subtopic_absent_short_branch`:短分支无 arch → 不进入 pre-step 块 → runtime.execute_calls == [] ✓。
8-9. `test_overview_proxy_*`:仅调用 `_make_overview_proxy`,本修复未改这个函数 → 不变 ✓。
10. **新** `test_arch_prefab_note_has_drill_target_when_entry_candidates_present`:见上 trace ✓。
11. **新** `test_arch_prefab_note_skips_nudge_when_no_target_available`:见上 trace ✓。

`test_deep_research_session_integration.py`、`test_deep_research_decomposer.py`、其它测试文件:本修复仅在 `if pre_result.success:` 块内追加文本拼接 + 一个新模块级 helper,既有断言/逻辑路径都未触及,零回归 ✓。

### 用户最终验证

```
python -m compileall new_kernel\deep_research\deep_research_loop.py
python -m pytest -q new_kernel\tests\test_deep_research_loop.py
python -m pytest -q new_kernel\tests\test_deep_research_*.py
```

预期:第 1 条 0 SyntaxError;第 2 条 11 tests passed(原 9 + 2 新);第 3 条全绿(73 baseline + 2 新 + FIX-04 / FIX-06 增量,具体数字看并行 fix 落地)。

## Spec Alignment

- **AGENTS.md §3.3**(Investigate / ReAct):本修复仅追加 prefab note 文本,不新增 ReAct round、不变 max_rounds_per_subtopic 配额、不影响 cancellation 检查点 ✓。
- **AGENTS.md §3.4**(Compose 输入):Composer 仍读 `notes_by_id["arch"]`,拼出来的 note 多一句"打开 \`src/main.py\` 看一段"教师腔引导,反而更利于 Composer 在 arch 节自然引用具体文件 ✓。
- **AGENTS.md §7.2**(教师腔基调):新加的 nudge 句"挑一个具体地方往里走一步:我们先打开 \`<path>\` 看一段,把这块代码长什么样、关键 symbol 是啥、和上下游怎么连,摆到学生面前。"全部教师腔,无 jargon ✓。
- **AGENTS.md §11.1**(import 纪律):本修复零新增 import;`_pick_arch_drill_target` 是模块内 helper,不跨模块 ✓。
- **AGENTS.md §12.2**(错误处理):`_pick_arch_drill_target` 返回 None 时静默跳过 nudge,不抛异常,不破坏 prefab note 落档路径 ✓。
- **AGENTS.md §12.3**(预算):prefab note ≤600 chars 硬截不变;nudge ≤180 chars cap;listing reserved 420 chars cap;总和不超 600 ✓。
- **RECON-E §D3**:本修复 1:1 落地 spec 给的 D3 candidate;优先级表 1→4 实现完整;教师腔禁词全部规避 ✓。
- **FIX-03 兼容性**:仅在 `if pre_result.success:` 块内追加,FIX-03 的 list_dir invocation / scratchpad.add_note / arch_pre_seeded flag 全部未触动 ✓。
- **FIX-04 共生**:FIX-04 改 `agents/decomposer.py`(arch anchors 混入文件);本修复改 `deep_research_loop.py`(prefab note 加反引号文件路径)。两者同时让"读文件"成为 round 2 LLM 最阻力最小的路径 ✓。
- **FIX-06 隔离**:本修复未触 `turn/turn_runtime.py`,与 FIX-06 文件零交叠 ✓。
