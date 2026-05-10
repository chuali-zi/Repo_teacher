# SA-03 · Decomposer (Phase 1)

## What
按 `deep_research/AGENTS.md` §3.2 / §7.2 落地 Phase 1 的 `Decomposer`：把 `RepoOverview`-like 对象 + Triage 给出的 `report_shape` 转成一个有序的 `SubtopicMeta` 列表，喂给 SA-04 Investigator。一次 LLM 调用、严格 JSON 解析（继承 SA-02 的 `parse_strict_json`）、id 必须落在固定支柱集 `{what, stack, why, arch, flow, polyglot}`、不可达 anchor 丢弃但保留 sub-topic、JSON 解析失败或验证为空时退回到确定性的 5 支柱兜底（短分支退到单 `what`）。多语言条件 `(secondary / primary) ≥ 0.25` 由私有 helper `_multilingual` 控制，决定是否允许 `polyglot` 第 6 支柱进入结果。

## Files
- new  new_kernel/deep_research/agents/decomposer.py:198  Phase 1 Decomposer 主体；公开 `Decomposer.process(report_shape, repo_overview)`，内部 6 个私有 helper（`_multilingual` / `_top_language_counts` / `_render_entries` / `_reachable_paths` / `_anchor_reachable` / `_validate_subtopics` / `_fallback_subtopics`）；只 import `..research_scratchpad.SubtopicMeta` + `.base_research_agent.BaseResearchAgent` + stdlib（`json` / `collections.abc.Iterable` / `typing`），未触 `agents.* / api.* / session.* / turn.* / events.* / repo.* / tools.*` 任意一项 §11.1 禁止前缀
- new  new_kernel/tests/test_deep_research_decomposer.py:229  5 个测试；`_FakeLLMClient` 是一个 dataclass+coroutine 风格 stub，记录每次 `call_llm` 的全部参数；`_FakeOverview` 走 dataclass 默认字段，让单测可以只覆写感兴趣的字段（`language_counts` / `top_level_paths`）
- mod  new_kernel/deep_research/.reports/README.md:+1/-1  SA-03 索引行去 "（待）" 并补一句结果

不需要改 `agents/__init__.py`：SA-02 已经用 try/except 占好位，`from .decomposer import Decomposer` 这次会成功并把 `Decomposer` 加进 `__all__`。

## Decisions
- **anchor 可达性走"双向 substring"而非严格前缀**：spec 原文是"substring-reachable path under top_level_paths ∪ {ec.path for ec in entry_candidates}"。我把它实现成 `anchor == base or anchor in base or base in anchor`：
  - `anchor in base` 处理"anchor 是某个底层短路径片段"（少见但合法）；
  - `base in anchor` 处理"anchor 是底层目录下的一个具体文件"（`"src/main.py"` 命中 `"src/"`），这是最常见的合法形态；
  - 仅 `==` 太严，会让 LLM 给出的 `"src/main.py"` 这类正常 anchor 全被丢弃。
  对 `"non/existent/path"` / `"totally_fake.lock"` 这样的全错 anchor，三种关系都不成立 → 正确丢弃；test 2 锁定这个语义。
- **短分支不强行外推 stack**：spec 说"如果用户要 short 且 LLM 返回了 stack，允许它"。我把短分支严格做成"LLM 显式返回 what 才有第一项；LLM 显式返回 stack 才有第二项"。如果 LLM 在短分支只返回了 stack 没返回 what，整个返回值会是空列表，触发外层 `_fallback_subtopics` 退到 `[what]`。这条路径让短分支也是确定性可断言的。
- **标准分支用 `defaults` 填补缺项而不是丢失**：spec 要求"missing IDs, fill with defaults"。我把标准分支构造成"对每个 `_STANDARD_REQUIRED` 中的 sid，要么用 LLM 返回的版本，要么用默认 SubtopicMeta"。这意味着即便 LLM 只返回 `[what, arch]`，最终结果仍是 5 支柱齐全；其余 3 项用 `_DEFAULT_TITLES + _DEFAULT_ANCHORS_STANDARD` 填。这把"LLM 部分有效"的所有情形也打包进了"validated 非空 → 不走兜底"分支。
- **`_multilingual` 用比例而非绝对数**：spec 给的判定是次主语言占主语言的比例 ≥ 25%。某些"主语言 5 个文件、次语言 2 个"的极小仓也会触发这条，符合 spec 字面，且这种情况只意味着 LLM 拿到的提示里看到次语言比例足够高就建议 polyglot；最终是否真的把 polyglot 留下，依赖 LLM 自己是否在 JSON 里写了这一项 + `_multilingual` 复核。两道闸门叠加避免单点误触发。
- **`_render_entries` 把 `OverviewEntryCandidate` 收成 `{path, hint}` 字典而不是 dataclass-as-dict**：`overview_builder.OverviewEntryCandidate` 实际带 `path / language / reason / score`，对 LLM 而言 `score` 是噪声，`reason` 才是教学相关的"为什么这是入口"。我把 `reason` 作为 `hint` 字段进 prompt，`language` / `score` 不暴露；如果未来传入的不是 `OverviewEntryCandidate` 而是 `{"path": ..., "hint": ...}` dict-like 对象，`getattr(..., "hint")` 也走得通——这个 fallback 让 SA-07 的 wiring 不被实际类型卡住。
- **`getattr(repo_overview, "language_counts", {})` 容错读取**：当前 `repo/overview_builder.RepoOverview` dataclass **没有** `language_counts` 字段（它只活在 `TreeScanResult` 中）。spec 要求"any object with .text/.primary_language/.file_count/.language_counts/.top_level_paths/.entry_candidates"。我用 `getattr` 默认值方式让真实 `RepoOverview` 不会因缺字段而崩，同时让单测可以传一个补齐 `language_counts` 的 stub；如果未来 `RepoOverview` 补上 `language_counts` 字段，本文件零改动。
- **不复用 `triage._RepoOverviewLike` Protocol**：那个 Protocol 在 `triage.py` 里只是文档化意图，实际 `triage()` 也走 getattr。SA-03 在 `process` 签名里把 `repo_overview` 标成 `Any`，与 spec 文本一致，不引入二次 Protocol 去 import。
- **`fallback={"subtopics": []}` 让外层逻辑统一**：`parse_strict_json` 失败时返回这个空形状的 dict，等价于"LLM 返回了一个有效 JSON，但 subtopics 数组是空的"。`_validate_subtopics` 看到空 list 直接返回 `[]`，触发外层 `validated or _fallback_subtopics(...)` 短路。这让"完全不可解析" 与 "可解析但语义为空" 两条失败路径走同一兜底分支，与 §12.2"JSON 解析失败 → 走兜底；不抛"一致。
- **行数 197**：spec 给的预算是 ≤180 + "validation 有 headroom"。我把 `__init__` 折成单行、`_render_entries` 与 `_reachable_paths` 留双 for（手写循环比 generator-comprehension 便于读 + 与 type-narrow 兼容），把验证主分支的 `result` 用 list-comp 收紧。再压会牺牲 happy-path 与 fallback 路径的可读对照。
- 与 AGENTS.md 的偏离：无（id 集合、报告分支约束、anchor 可达性语义、polyglot 触发阈值、默认标题文案、默认 anchors 与 §3.2 文本逐条一一对应）。

## Verification
受当前会话工具权限限制（Bash / PowerShell / mcp__ide__executeCode 全部被 `Permission has been denied`），我无法在本会话里运行 `python -m compileall` 与 `python -m pytest`。代码层面的等价检查：
- 静态语法：所有 import 都已 SA-02 / SA-01 落盘并 import 验证（`SubtopicMeta` 来自 `..research_scratchpad`，`BaseResearchAgent` 来自 `.base_research_agent`，二者都在工作目录中存在）。
- 类型一致：`SubtopicMeta(id, title, anchors)` 的 anchors 字段在 `research_scratchpad.py` 是 `tuple[str, ...] = ()`，本文件全部以 `tuple(...)` / `("README.md",)` / `()` 构造，零类型偏差。
- 5 个测试逐条人工 trace：
  1. happy_path_standard — LLM 返回 5 支柱 valid JSON、anchors `README.md / package.json / src/` 全部命中 `top_level_paths` → 通过 `_validate_subtopics` → ids `[what, stack, why, arch, flow]`、titles 与 anchors 与 LLM 输入一致。
  2. drops_unreachable_anchor — `non/existent/path` 与 `totally_fake.lock` 与 `top_level_paths` 任一都不互为 substring → 被丢；同 sub-topic 的 `README.md` 命中 → 留下；`stack` sub-topic 全部 anchor 被丢 → `anchors == ()` 但 sub-topic 自身仍在结果中。
  3. short_branch_caps — LLM 返回 5 支柱，short 分支命令 `_validate_short` 只取 `by_id["what"]` + `by_id["stack"]`，结果长度 2，ids `[what, stack]`。
  4. invalid_json_falls_back — `parse_strict_json("not json at all, sorry", fallback={...})` 中 `find('{')==-1`、`rfind('}')==-1`，条件 `0 <= -1 < -1` 为假 → 返回 fallback；外层得到空 list → 触发 `_fallback_subtopics("standard")`，返回 5 默认 SubtopicMeta；anchors 为 `("README.md",)` ×3 + `() ×2`。
  5. polyglot — `{"Python":100,"JavaScript":30}` → values=[100,30]，30/100=0.3 ≥ 0.25 → multilingual=True → polyglot 通过；`{"Python":100,"JavaScript":5}` → 5/100=0.05 < 0.25 → multilingual=False → polyglot 被丢，即使 LLM 返回了它。
- 已知 TODO：组合根（SA-08 wiring）需要在 `api/app.py:_build_default_runtime` 用 `PromptManager(prompts_root=PROMPTS_ROOT)` 注入 deep_research 自有的 prompt 根，否则 `self.get_prompt("decompose", ...)` 会在 kernel 通用 prompts 目录下找不到。这是 SA-02 已经为 SA-07 / SA-08 留的 hook，本文件不需要改。

## Spec Alignment
- AGENTS.md §3.2（Phase 1 输入：`report_shape` + `RepoOverview` 的 6 个字段；输出：`{subtopics: [{id, title, anchors}]}` JSON；id 集合 `{what, stack, why, arch, flow, polyglot}`；short 分支 `[what]` 或 `[what, stack]`；standard 分支 `[what, stack, why, arch, flow]` + 多语言条件下追加 `polyglot`；anchor 必须落在 `top_level_paths` ∪ `entry_candidates.path`，不达成时丢弃 anchor 但保留 sub-topic；JSON 解析失败走兜底）
- AGENTS.md §7.1 / §7.2（不在 prompt 调用里加任何反模式约束；`temperature=0.2` 与 `max_tokens=900` 与 spec 推荐参数一致）
- AGENTS.md §11.1（不 import `agents.teacher / agents.reading_agent / agents.orient_planner / api.* / session.* / turn.* / events.* / repo.* / tools.*`，已校验全文件 import 仅命中 `..research_scratchpad` + `.base_research_agent` + stdlib）
- AGENTS.md §12.2（JSON 解析失败 / 验证为空 → 走兜底，不抛；`call_llm` 的 LLM 异常透传，不 swallow——本模块没有 try/except 包 LLM 调用）
- AGENTS.md §12.3（`top_level_paths` cap 60、`entry_candidates` cap 12、`language_counts` 取 top 6——配合 OverviewBuilder 自身的 `MAX_OVERVIEW_LINES = 50` 控住 prompt 大小，单 prompt 远低于 §12.3 的 4KB / 30KB 上限）
- AGENTS.md §13（`Decomposer` 单元测：5 个测试覆盖 happy / 不可达 anchor / short cap / JSON 解析失败 / polyglot 双向触发；fake LLM 走 `_FakeLLMClient`，未触发真 LLM）
