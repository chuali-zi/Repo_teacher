# SA-01 · Pure Functions & ResearchScratchpad

## What
按 `deep_research/AGENTS.md` §3.1 / §3.3 / §3.4 / §8 落地三个零 LLM、零 I/O 的纯数据层：Phase 0 `triage()`、Phase 2 `InvestigationPolicy` 状态机、以及 sub-topic 感知的 `ResearchScratchpad`（区别于 `memory.Scratchpad`），把它们 re-export 到 `deep_research` 包入口，并补齐三份单测覆盖全部分支与边界条件。

## Files
- new  new_kernel/deep_research/triage.py:69  Phase 0 决策矩阵（empty/short ×3 形态/standard）+ `EmptyRepositoryError` + Protocol
- new  new_kernel/deep_research/investigation_policy.py:80  起轮/停轮/跳过状态机；`mark_skipped` 同时清零 streak
- new  new_kernel/deep_research/research_scratchpad.py:214  sub-topic 笔记 + 第 1 轮 raw（≤2KB 截断）+ skip_reason + covered_points + `build_compose_context` 预算裁剪
- mod  new_kernel/deep_research/__init__.py:+18/-1  re-export 三个层的公开符号；明确 `DeepResearchLoop` 由 SA-07 接入
- new  new_kernel/tests/test_deep_research_triage.py:63  4 条决策分支 + Markdown/plaintext/None 三个子值
- new  new_kernel/tests/test_deep_research_policy.py:93  bump/reset/mark_skipped/can_continue 四类组合 + round_quota
- new  new_kernel/tests/test_deep_research_scratchpad.py:146  set_subtopics 重置 / 未知 id KeyError / 第 2 轮 raw 丢弃 / 截断标记 / build 形状 + 预算 / covered_points
- mod  new_kernel/deep_research/.reports/README.md:+1/-1  索引去掉 SA-01 待标记并补一句结果
- new  new_kernel/deep_research/.reports/SA-01-pure-and-scratchpad.md:本报告

## Decisions
- **Triage Protocol 用结构化类型而非 import `RepoOverview`**：`overview_builder.RepoOverview` 实际未把 `language_counts` 作为字段暴露（它只活在 `TreeScanResult` 里），但 AGENTS.md §3.1 的判定矩阵只用 `file_count` + `primary_language`，所以 `_RepoOverviewLike` Protocol 列出五个字段是声明意图，`triage()` 的实现走 `getattr(..., default)` 容错——既符合 §11.1 不 import `repo.*` 的禁令，也让 SimpleNamespace stub 直接可用。
- **`InvestigationPolicy.mark_skipped` 由 caller 触发**：AGENTS.md §3.3 写 "连续 2 次工具失败 → 该 sub-topic 不再起轮"。我把"是否达到阈值"的判断留给 caller（loop 自己读 `failure_streak >= max_consecutive_failures`），policy 只暴露 `mark_skipped(id)` 这个语义动作并顺手清零 streak；这样 loop 在跳过和"重置进入下一支柱"之间的语义切换显式可控，不靠 policy 内部隐式触发。
- **Scratchpad 不 import `memory.Anchor`**：AGENTS.md §11.1 允许引用 `Anchor`，但本模块的笔记只需要 `(path, (start,end))` 这种轻量结构，引入 `Anchor` 反而把 `_clean_text` 等清洗副作用带进 frozen dataclass 链路。`SubtopicNote.anchor_path / anchor_lines` 直接用裸 str/tuple，等 NoteTaker 真要返回结构化 anchor 时再升级。
- **第 2 轮以后的 raw_observation 静默丢弃**：AGENTS.md §3.3 的伪码就是 `raw_observation=result.content if round <= 1 else None`。我让 `add_note` 接受 round_index ≥ 2 的 raw_observation 但不入库，方便上层无脑传参；如果上层想 enforce，可以自己 assert。
- **预算裁剪的 byte size 不走 JSON 序列化**：AGENTS.md §12.3 给的是用户可见 prompt 字节预算，不是 wire 字节。我只对存进 ledger 的 user-visible 字符串字段累加 utf-8 字节，避免 JSON 引号 / 转义 / 缩进的二阶噪音让裁剪不收敛。
- **裁剪先杀最大 raw 再杀 note 尾**：raw 是"二级证据"，note 是 NoteTaker 提炼的教学要点，丢 raw 损失更小。skip_subtopic_ids 里那些支柱本身已没必要保留 note，所以 `min_keep=0`；非 skip 支柱保留 ≥1 note 是测试断言的 invariant。
- **行数微超**：scratchpad.py 落盘 214 行 vs prompt ≤200 的软上限，超出 14 行集中在 `_enforce_budget` 的两轮裁剪 + `_context_byte_size` 字节累加，这两个函数是 budget 语义的最小完整闭环，再压会牺牲可读性。triage / policy / 三份测试均在或低于预算。
- 与 AGENTS.md 的偏离：无（结构化偏好与 §11.1 一致，所有判定分支与 §3.1/§3.3 文本一致）。

## Verification
- `python -m compileall new_kernel\deep_research` — 通过（4 个 .py 文件全部编译成功，无 SyntaxError）
- `python -m pytest -q new_kernel\tests\test_deep_research_triage.py new_kernel\tests\test_deep_research_policy.py new_kernel\tests\test_deep_research_scratchpad.py` — 通过（21 passed in 0.03s）
- 已知问题 / TODO：`SubtopicNote.anchor_path` / `anchor_lines` 字段 shape 与未来 NoteTaker 实际输出 (`SA-05`) 需要二次对齐；本层只是占位最小集。

## Spec Alignment
- AGENTS.md §3.1（Triage 决策矩阵 4 分支）
- AGENTS.md §3.3（Investigation 状态机：max_rounds / 连续失败 / 跳过；NoteTaker 第 1 轮 raw 入库）
- AGENTS.md §3.4 / §12.3（Compose 上下文预算：raw ≤2KB、Composer 总输入 ≤30KB）
- AGENTS.md §8（模块布局：triage.py / investigation_policy.py / research_scratchpad.py 三层各自独立文件 + 文件首段职责注释）
- AGENTS.md §11.1（不 import `agents.* / api.* / session.* / turn.* / events.* / repo.* / tools.* / llm.*`，已校验全文件 import 仅命中 stdlib）
- AGENTS.md §13（单测层：`Triage` 决策矩阵全分支、`InvestigationPolicy` 起轮/停轮/跳过、`ResearchScratchpad` 写入/序列化/build context）
