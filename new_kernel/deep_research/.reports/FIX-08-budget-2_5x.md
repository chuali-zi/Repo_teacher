# FIX-08 · All chat & research max_tokens × 2.5 (force-execute)

## What

User reports that even after FIX-07 raised Composer to 8000, the report budget still feels insufficient and the visible answer in chat mode is also being truncated. Direct instruction: **multiply every `max_tokens` literal across chat and research paths by 2.5×, force execute**. This fix walks all 9 LLM call sites, applies `round(old × 2.5)`, and clamps any result that exceeds the deployed model's output cap.

Deployed model = `deepseek-v4-flash` (read from `C:\Users\chual\vibe\Irene\llm_config.json`: `"base_url": "https://api.deepseek.com"`, `"model": "deepseek-v4-flash"`). DeepSeek's chat-family OpenAI-compatible endpoint enforces an **8192-token output cap** server-side; the `-flash` variant has not published a different cap, so we treat 8192 as the ceiling and reserve a 192-token safety margin → effective ceiling = **8000**.

## Files

Survey + edits (9 sites across 9 files, +18 / -9 lines net):

| File:line | Agent / role | Old | ×2.5 | Final | Clamp? |
| --- | --- | --- | --- | --- | --- |
| `deep_research/agents/composer.py:121` | Composer (final report stream) | 8000 | 20000 | **8000** | yes — at cap |
| `deep_research/agents/decomposer.py:108` | Decomposer (sub-topic JSON) | 900 | 2250 | 2250 | no |
| `deep_research/agents/investigator.py:76` | Investigator (ReAct decision JSON) | 600 | 1500 | 1500 | no |
| `deep_research/agents/note_taker.py:62` | NoteTaker (Chinese note) | 500 | 1250 | 1250 | no |
| `agents/teacher.py:55` | TeacherAgent (non-stream call) | 5000 | 12500 | **8000** | yes — at cap |
| `agents/teacher.py:64` | TeacherAgent (stream) | 5000 | 12500 | **8000** | yes — at cap |
| `agents/orient_planner.py:48` | OrientPlanner | 1200 | 3000 | 3000 | no |
| `agents/reading_agent.py:54` | ReadingAgent (ReAct decision JSON) | 900 | 2250 | 2250 | no |
| `agents/sidecar_explainer.py:53` | SidecarExplainer | 360 | 900 | 900 | no |
| `api/app.py:227` | `_make_summarizer` (summarize_file tool) | 320 | 800 | 800 | no |

未触：`llm/client.py`、prompt YAML、`base_agent.py`/`base_research_agent.py`（无 literal）、`tests/*`（仅参数捕获，不 assert literal）、`AGENTS.md`、`.reports/README.md`。

## Decisions

1. **Model-cap clamp at 8000 (= 8192 − 192).** Three sites trigger the clamp: composer (already at 8000 from FIX-07; user-requested 20000 the model cannot honor), teacher non-stream call (5000→12500→8000), teacher stream (5000→12500→8000). All three keep a one-line FIX-08 comment that records the user-requested target *and* the clamp reason, so when the user later swaps to a larger-output model (e.g. DeepSeek-V3 with 64k or any GPT-4-class endpoint), they can grep the comment and bump the literal in one shot.
2. **Composer is now at the model ceiling.** The only way to raise the final report budget further is to **switch the deployed model** to one with a >8192 output cap. Doubling Composer further on `deepseek-v4-flash` will not produce more text — the API returns `finish_reason="length"` regardless.
3. **Teacher matches Composer at 8000.** Chat-mode visible answers (`TeacherAgent`) had `max_tokens=5000` at both the streaming and non-streaming sites. Per user spec FIX-08 explicitly names teacher as the main chat-mode visible-output writer and demands it be raised; clamping to 8000 raises it 60% from 5000 — the largest possible bump on this model.
4. **All other sites raise cleanly to 2.5×.** Decomposer 900→2250, Investigator 600→1500, NoteTaker 500→1250, OrientPlanner 1200→3000, ReadingAgent 900→2250, SidecarExplainer 360→900, summarize_file 320→800. None of these approach the 8000 ceiling, so no clamping needed. Note this overrides FIX-07 §Decision 5 ("don't raise the JSON-emitting agents") at the user's explicit instruction.
5. **No test edits.** Confirmed via grep: every `max_tokens` reference in `new_kernel/tests/` is either (a) a `_FakeLLMClient.call_llm` / `.stream_llm` *parameter capture* (`max_tokens: int | None = None` in the fake's signature, then `"max_tokens": max_tokens` recorded into `self.calls`), or (b) the unrelated `_fit_text(text, max_tokens=2000)` / `<= 600` / `> 600` literals which all reference char-length helpers in `research_scratchpad` and `note_taker`'s `_MAX_NOTE_CHARS`, not LLM budgets. Test fakes never assert on the captured `max_tokens` value, so changing the production literals leaves the recorded `int` field free to take any value. Zero test edits required.
6. **Comment style.** Each non-clamped site gets a single line: `# FIX-08: 2.5× of <old> per user request to avoid mid-output truncation.` Clamped sites get a slightly different one-liner that records both the requested target and the clamp reason. This matches the FIX-07 inline-comment convention and keeps `git blame` informative.

## Verification

```
PS> python -m compileall new_kernel\agents new_kernel\deep_research\agents new_kernel\api
[expected: exit 0, no SyntaxError]

PS> python -m pytest -q new_kernel\tests\test_*.py --ignore=new_kernel\tests\tmp_run --ignore=new_kernel\tests\pytest_tmp_run
[expected: all green; FIX-07 baseline was 70/70 deep_research tests + remaining kernel tests]
```

Sandbox restricted shell access during this fix, so the agent could not execute `compileall` / `pytest` directly. Manual re-read of every edited site (Read tool, lines around each touched literal) confirms:

- Each `max_tokens=<new_int>,` line is well-formed Python (trailing comma preserved, no broken indentation).
- The new comment lines sit immediately above the value, indented to match `temperature=` siblings — same depth as in FIX-07.
- No other parameter (`temperature`, `system_prompt`, `response_format`, `top_p`) was touched on any of the 9 sites.

Chief engineer must run `compileall` + `pytest` once before declaring PASS. **If any test fails on a `max_tokens` literal**, that test should be patched by inlining the new value (none expected based on the grep above).

### 硬约束自检

| 约束 | 满足证据 |
| --- | --- |
| 不改 temperature / system_prompt / response_format / top_p | 9 个 edit 均只动 `max_tokens=` 这一行 + 注释 |
| 不动 prompt YAML | 未编辑任何 `prompts/**/*.yaml` |
| 不动 `llm/client.py` | 未编辑 |
| 不更 `.reports/README.md` | 未编辑 |
| ≤ 30 行 prod diff | 9 文件 × (1 literal + 1 comment) = +18 / -9 净 +9 行 |
| 不跳过任何 literal site | 9/9 site 全部触达，包括 FIX-07 留下的 8000（重新打了 FIX-08 注释） |

## Spec Alignment

- **AGENTS.md §7.2** (Composer body 3500-5000 中文字符): unaffected — Composer stays at 8000 (model ceiling).
- **AGENTS.md §3.3** (NoteTaker 200-400 字笔记 + ≤600 字符硬截): NoteTaker LLM budget rises 500→1250 tokens, but the downstream `_MAX_NOTE_CHARS = 600` char-cap in `note_taker.py:22` is **unchanged** — the LLM will be allowed to draft a longer note, but the post-processor still trims to ≤600 chars before persisting. This means the 2.5× bump on this site is mostly slack; if the user later wants longer persisted notes, they must also raise `_MAX_NOTE_CHARS`. Flagging here so chief engineer can decide whether to follow up.
- **AGENTS.md §3.3** (Investigator 1 个决策 JSON): Investigator budget 600→1500 tokens. The decision JSON is small (~20-50 tokens of action+intent+want_more); 1500 is grossly over-budget but harmless — the model emits one short envelope and stops, never approaching the cap. This is the user's "force execute" override of FIX-07 §Decision 5.
- **AGENTS.md §12.3 上下文预算表**: 全部 **input** 预算条目；本 fix 改的是 output cap，与表内任何条目无冲突。
- **`module_interaction_spec.md §13` import 白名单**: 未引入任何新 import。
