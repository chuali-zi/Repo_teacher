# FIX-07 · Composer max_tokens budget 4000 → 8000

## What

Phase 3 Composer streamed reports were getting truncated mid-paragraph. Root cause is the hard `max_tokens=4000` budget on the single `stream_llm(...)` call at `agents/composer.py:114`. AGENTS.md §7.2 targets 3500-5000 中文字符 for the body; with DeepSeek's tokenizer (Chinese ≈ 1 char/token) plus markdown headings/bullets/backticks (~10-15% overhead) plus the trailing `<<SUGGESTIONS>>\n- …\n` block, the realistic worst case is ~5500-6000 tokens — squarely above 4000. The cap was clipping the tail (and sometimes eating the marker line itself, which is why `last_output.suggestions` occasionally came back empty too).

This fix raises the budget to 8000, the highest safe value under DeepSeek-chat's 8192 output cap. Voice prompt, response_format, temperature unchanged. Only the **output** budget moves; the **input** budget table in §12.3 is untouched (input ≤ 30KB stays valid).

## Files

- mod  `new_kernel/deep_research/agents/composer.py` (+7 / -1, line 110-115 → 110-121):
  - `max_tokens=4000` → `max_tokens=8000` inside `Composer.stream(...)`'s lone `stream_llm(...)` call.
  - 6-line comment above the value records the rationale (3500-5000 字 target, 1 char ≈ 1 token, markdown overhead, suggestions block, 8192 cap headroom) so the next maintainer doesn't re-shrink it.
- new  `new_kernel/deep_research/.reports/FIX-07-composer-budget.md`: this report.

未触：`llm/client.py`、prompt YAML（`prompts/zh/compose.yaml` 等四份）、`agents/decomposer.py`、`agents/investigator.py`、`agents/note_taker.py`、`tests/test_deep_research_composer.py` 及其余测试、`AGENTS.md`、`module_interaction_spec.md`、`.reports/README.md`。

## Decisions

1. **Deployed model = `deepseek-v4-flash`** (read from `C:\Users\chual\vibe\Irene\llm_config.json`: `"base_url": "https://api.deepseek.com"`, `"model": "deepseek-v4-flash"`). 所有 DeepSeek 系 OpenAI 兼容端点共享 8192 token output cap（DeepSeek 官方文档 + chat completions API spec），`-flash` 变体未公开缩减此上限，按 8192 取齐。
2. **Why 8000 specifically.** Body target 5000 中文字符 → ~5000 tokens (DeepSeek BPE 对 CJK 大致 1:1)。markdown 加粗 / 列表 / `## ` 标题 / 代码反引号 ≈ +10-15% → +500-750 tokens。`<<SUGGESTIONS>>` 标记 + 3 条短建议 ≈ 80-150 tokens。最坏情况 ~5800-5900 tokens；8000 留 ~2000 token 安全裕度，仍距 8192 硬上限 192 token 远（避免极端尾巴吃满后服务端返回 `finish_reason="length"` 截断）。
3. **Why not 8192 minus 1.** 把所有裕度榨干会让 `finish_reason="length"` 重新成为常态——只是从 4000 移到 8191；8000 留出明确的"模型偶尔超调"缓冲。同时 8000 是整数好读、便于运维 grep。
4. **No test changes.** `tests/test_deep_research_composer.py` 的 `_FakeLLMClient.stream_llm` 把 `max_tokens` 记到 `self.calls` 但**从不 assert** 其值（grep 验证：仅 `test_deep_research_scratchpad.py:120` 出现字面 `4000`，那是 `"N" * 4000` note size，与本 fix 无关）。Edit 2 整体 skip。
5. **Why not also raise decomposer / investigator / note_taker.** 他们的 `max_tokens` 是分别按"输出严格 JSON 4-6 个对象"、"输出 1 个决策 JSON"、"输出 200-400 字笔记"裁剪过的——出语义即停。把它们的预算放大反而会鼓励 LLM 写水分笔记、撑爆 §12.3 的 30KB 输入预算。本 fix 严格只触 composer。
6. **Comment style follows existing FIX-N convention.** Inline 解释为什么不是 4000，引用 AGENTS.md §7.2 + DeepSeek 8192 上限——与 FIX-03 / FIX-05 在 prompt YAML 里嵌注释的风格一致，让 surgeon-out-of-context 看一眼就懂。

## Verification

```
PS> python -m compileall C:\Users\chual\vibe\Irene\new_kernel\deep_research\agents\composer.py
Compiling 'C:\\Users\\chual\\vibe\\Irene\\new_kernel\\deep_research\\agents\\composer.py'...
[exit 0, no SyntaxError]

PS> python -m pytest -q new_kernel\tests\test_deep_research_composer.py
.....                                                                    [100%]
5 passed in 0.55s

PS> python -m pytest -q (Get-ChildItem new_kernel\tests\test_deep_research_*.py)
......................................................................   [100%]
70 passed, 2 warnings in 1.48s
```

5/5 composer 测试 + 70/70 整套 deep_research 测试全绿。`compileall` 出 0 退出码且无 SyntaxError 输出。两个 deprecation warning 是 `api/app.py:86` 的 `@app.on_event("shutdown")`（FastAPI lifespan 迁移），与本 fix 无关。

### 硬约束自检

| 约束 | 满足证据 |
| --- | --- |
| 只触 `composer.py`（+ 可选 test）| `git diff` 仅 `composer.py`；test 文件未编辑 |
| ≤ 10 行 prod diff | +7 / -1，净 +6 行 |
| 不动 prompt YAML | `prompts/zh/compose.yaml` 等未编辑 |
| 不动 decomposer / investigator / note_taker | 三文件未编辑 |
| 不动 `llm/client.py` | 未编辑 |
| 不改 temperature / system_prompt / response_format | `temperature=0.7` 与 `system_prompt=self.get_prompt("system")` 行原样保留 |
| 不更 `.reports/README.md` | 未编辑 |

## Spec Alignment

- **AGENTS.md §7.2 "长度建议 3500-5000 中文字符"**: 报告主体长度建议项现在能真正写到 5000 字而不被服务端在 4000 token 处截尾。注意 AGENTS.md §13 末行明确"**不写**字数下限 assertion"——本 fix 只放宽**输出 token 上限**这个 service-side 硬截断，并没有引入字数 assertion，与该约束相容。
- **AGENTS.md §3.4 输出约束**: `<<SUGGESTIONS>>` 标记 + 1-3 条建议必须在 stream 末尾出现；4000 token 时偶尔被截掉导致 `last_output.suggestions == ()`，8000 token 后此问题随主体一并解除。
- **AGENTS.md §12.3 上下文预算表**: 该表全部条目都是 **input** 预算（compose.yaml system prompt < 3KB / 单 sub-topic 笔记 ≤ 1.5KB / raw_observation ≤ 2KB / 总输入 ≤ 30KB），未提 output 预算；本 fix 改的是 output cap，与表内任何条目无冲突。
- **`module_interaction_spec.md §13` import 白名单**: 未引入任何新 import；`composer.py` 唯一 import 链 `agents.base_research_agent` 未变。
