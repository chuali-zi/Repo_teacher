# FIX-10 · ReAct 轮预算 ×2，大仓库不被限制死

## What

deep_research sub-topic 与 teaching_loop chat per-step 的 ReAct 轮预算与连续失败
容忍度全部 2 → 4；`max_parallel_subtopics` 维持 1 不变。

## Decisions

- **只翻深度不翻广度**：用户原话"最大调用工具次数也上调，翻一倍，在面对大型仓库
  不要限制死"。AGENTS.md §3「工具并发度 v1 顺序执行（max_parallel=1），避免
  git/handle/内存峰值踩雷」明确锁住广度；所以「不要限制死」映射到深度（rounds），
  不是并发（parallel）。
- **5 个 prod 落点全改**：loop 默认 4、policy `max_rounds`/`max_consecutive_failures`
  默认 4、teaching_loop `max_react_iterations` 默认 4、api/app.py 显式 caller 也写
  4 与默认对齐。caller 仍显式传值，未来想做 per-tier 配置无需重设注入点。
- **失败容忍同步翻倍**：只翻 rounds 不翻 `max_consecutive_failures` 会让大仓库的
  rounds 预算被工具偶发失败提前耗掉；两者必须同向调。
- **Composer 上下文预算（§12.3）caps 不动**：单 sub-topic 笔记仍 ≤1.5KB、单
  raw_observation 旁路仍 ≤2KB；NoteTaker 自身截断逻辑压制每轮笔记长度。Composer
  总输入 ≤ 30KB（n=6 时 21KB），仍在预算内。
- **每 sub-topic 墙钟估算**：standard 单 sub-topic 最坏从「2 LLM round」涨到
  「4 LLM round」；FIX-03 prefab seed 命中后 arch sub-topic = 1 prefab + 3 LLM
  round。§3 表中"standard 5 支柱跑满 3-5 分钟"翻倍后最坏 6-10 分钟；典型工具直接
  返回 done 的路径仍 1-2 LLM round，墙钟不变。

## Changes

- `new_kernel/deep_research/deep_research_loop.py:224`：
  `max_rounds_per_subtopic: int = 2` → `4`。
- `new_kernel/deep_research/investigation_policy.py:17-18`：
  `max_rounds: int = 2` → `4`；`max_consecutive_failures: int = 2` → `4`。
- `new_kernel/agents/teaching_loop.py:86`：`max_react_iterations: int = 2` → `4`。
- `new_kernel/api/app.py:268`：`max_rounds_per_subtopic=2` → `4`。
- `new_kernel/tests/test_deep_research_policy.py:10-21`：
  `test_bump_failure_streak_then_mark_skipped_resets` 触发 loop 2 → 4 次 bump，
  断言 `failure_streak == 4`，与新默认 `max_consecutive_failures=4` 对齐。
  其余测试不显式 pin 旧字面量；`test_can_continue_blocks_when_round_budget_hit`
  显式构造 `max_rounds=2` 是验证 boundary，与默认无关，不动。

## Verify

```
$ python -m compileall new_kernel/deep_research new_kernel/agents new_kernel/api
（4 个文件全部成功编译，无 syntax error）

$ python -m pytest -q new_kernel/tests \
    --ignore=new_kernel/tests/tmp_run --ignore=new_kernel/tests/pytest_tmp_run
100 passed, 8 warnings in 4.49s
```

100/100 全绿，零回归。

## Open

- `max_consecutive_failures=4` 对 git/网络配置烂的环境会让单 sub-topic 耗光 4 轮
  全部失败再放弃，墙钟代价较大；如有反馈可反向把容忍解耦回 2、只保留 rounds=4。
- 未引入 per-tier 分层预算（small/medium/large repo）。一刀切 4 轮；未来 Triage
  注入 int 即可。
- 未把广度从 1 抬到 2+。是 §3 锁住的硬约束，需先解 SA-* 里 git/句柄/内存竞态。
