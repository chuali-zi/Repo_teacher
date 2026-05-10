# FIX-02 · Decomposer LLM-Exception Fallback

## What
按 `RECON-FINAL-diagnosis.md` 候选 #2：`deep_research/agents/decomposer.py:69-75` 直接 `await self.call_llm(...)` 没有 try/except，任何同步 LLM 异常（DeepSeek 401/402 余额不足/`response_format` 不支持/限流/网络）都会跑到 `TurnRuntime._exception_to_api_error` → 前端拿到 `ErrorEvent(error_code=llm_api_failed)`。Investigator (`agents/investigator.py:69-78`) 早就用了 `try/except Exception: return _fallback_parse_failure()` 模式，FIX-02 把同一精神扩展到 Decomposer：把 `call_llm` 包进 `try/except Exception:`，捕获后复用模块内已有的 `_fallback_subtopics(report_shape)` 兜底分支（与"JSON 解析失败"走完全相同的默认 5 支柱路径）。AGENTS.md §3.2 原本只规定 JSON 解析失败 → 兜底；FIX-02 把这一精神延伸到 LLM HTTP 异常，避免一次 4XX 把整次 onboarding turn 炸掉。Decomposer.process 的公开签名、其它 helper、prompt yaml、所有其它 agent 模块零改动。

## Files
- mod  `new_kernel/deep_research/agents/decomposer.py`:69-82  +5 行 / -0 行：在原 `text = await self.call_llm(...)` 上方放 3 行注释 + 1 行 `try:`；原 8 行 `await` block 缩进保持不变；下方加 `except Exception:\n    return _fallback_subtopics(report_shape)` 共 2 行；总 diff ≈ +5 行。`process()` 函数总长由 39 行变成 44 行，远低于 spec 给的 ~10 行预算。
- mod  `new_kernel/tests/test_deep_research_decomposer.py`:227-261  +35 行 / -0 行：在原 5 个测试之后、`if __name__ == "__main__"` 之前追加第 6 个测试 `test_decomposer_falls_back_to_default_pillars_on_llm_exception`；内部新建 `_RaisingLLMClient`（`async def call_llm` 计数 +1 后抛 `RuntimeError`），复用现有 `_FakeOverview` / `_run` / `PromptManager(prompts_root=PROMPTS_ROOT)` / `Decomposer` import；断言三件事：(a) 5 默认 ids `[what, stack, why, arch, flow]` 顺序、(b) 5 默认 titles 与 `_DEFAULT_TITLES` 一致、(c) `calls == 1` 即未重试。
- new  `new_kernel/deep_research/.reports/FIX-02-decomposer-fallback.md`:本报告
- mod  `new_kernel/deep_research/.reports/README.md`:+1/-0  在 SA-10 后新增 FIX-02 索引条目

不需要改 `agents/__init__.py` / 任一 prompt yaml / 任一 session/turn/api 文件 / `investigator.py` / `note_taker.py` / `composer.py`。

## Decisions
- **复用 `_fallback_subtopics(report_shape)` 而不是新造一条路径**：`decomposer.py:188` 已有这个函数，short → `[what]`、standard → 5 默认 SubtopicMeta。spec 的硬要求是"用 SAME default-fallback path"。如果再写一个 `_default_subtopics(report_shape, top_level_paths, language_counts)`，就会与现有的 `validated or _fallback_subtopics(report_shape)` 末段路径产生两套兜底，违反"不重复"原则。catch 点拿到的 `report_shape` 已是 `process()` 的形参，`_fallback_subtopics` 也只需这一个参数 → 零变量提升、零行膨胀。
- **bare `except Exception` 而非具体类**：spec 显式要求"Use bare `Exception` like Investigator does"。Investigator 选这个是因为 LLMClient 后端可以是 DeepSeek / OpenAI / Anthropic / Azure 任一，每个 SDK 抛的错误类不同（`openai.AuthenticationError` / `httpx.HTTPStatusError` / `requests.ConnectionError` / 自家 `LLMClientError`），追列白名单维护代价高。`Exception` 不会吞 `KeyboardInterrupt` / `SystemExit` / `BaseException` 子类的 cancellation，与 §5 cancellation 的 `CancelledError`（`BaseException` 子类）路径不冲突。
- **不加日志、不加 metric、不 re-raise**：spec 明确要求"Silent fallback only"，与 Investigator 一致。日志会让"5 支柱齐全 + 用户拿到合理报告"路径与"LLM 出错被吞 + 用户拿到默认兜底报告"路径在用户体验上一致，但 ops 层无可见；这条偏离 §12.2 通则（"LLM 调用失败：抛出，由 TurnRuntime 转为 ErrorEvent；本模块不 swallow LLM 异常"）。SA-04 给 Investigator 选 swallow 也是同一个规格 vs 通则取舍，FIX-02 跟随 SA-04 的判例（详 SA-10 Decisions §"Investigator 的 LLM 异常 swallow 偏离 §12.2 通则"）。这条文档化偏离继承自 SA-04 + RECON-FINAL 候选 #2 fix 建议。
- **注释带 §3.2 引用 + FIX-02 票号**：未来读到 try/except 的人能立刻定位到 spec 第几节、为什么这个 catch 存在、是哪个修复票引入的。3 行注释、零运行成本。
- **`_RaisingLLMClient.calls` 用类变量而不是实例 attr**：spec 给的 reference 写法就是 `type(self).calls += 1`，这个写法在测试里 access 是 `_RaisingLLMClient.calls`（不需要持有实例引用），与 spec 给的 `assert _RaisingLLMClient.calls == 1` 形态对得上。`_FakeLLMClient` 用实例 attr 是因为它单测内构造在 `_make_decomposer(...)` 内部，外层没法拿到实例；FIX-02 测试既然在外层显式构造，就两种写法都能用，照 spec 文本走。
- **断言完整 5 默认 titles 而不只断 ids**：让本测试也充当"如果未来有人改了 `_DEFAULT_TITLES` 字面值"的回归闸门。原 `test_decomposer_invalid_json_falls_back_to_defaults_standard` 已锁过 5 默认 titles 字面值；FIX-02 测试再锁一次，是因为它走的是另一条入口（LLM 抛错 vs LLM 返回乱码）；两条入口最终都汇到 `_fallback_subtopics("standard")`，但前者短路在 try/except，后者短路在 `validated or` 末段。锁同一份默认 titles 让两条路径行为强制同步。
- **不断 anchors 全部 5 项**：只锁 `what == ("README.md",)` + `arch == ()` 两项，覆盖"非空 anchor"与"空 anchor"两种形态。锁 5 项会与 `test_decomposer_invalid_json_falls_back_to_defaults_standard` 完全重复，价值低且增加未来维护成本（如果某天 spec 改了 `_DEFAULT_ANCHORS_STANDARD["why"]` 默认值，要同步改 N 处）。
- 与 spec 的偏离：无（FIX-02 任务单 deliverables 4 条全部命中：edit 1 ✅ / edit 2 ✅ / 不动其它文件 ✅ / 不打印不日志 ✅）。

## Verification
本会话的 `Bash` / `PowerShell` 工具均被 `Permission has been denied` 拦截（`python -m compileall` / `python -m pytest` 都跑不出），与 SA-03 报告记录的会话权限状态一致。代码层面的等价检查：

### 静态正确性
- `decomposer.py` 编辑后：所有 import 不变（`json` / `Iterable` / `Any, Literal` / `..research_scratchpad.SubtopicMeta` / `.base_research_agent.BaseResearchAgent`）；`_fallback_subtopics` 早在 `decomposer.py:188` 定义，`process()` 在 `decomposer.py:46` 内，作用域内可见。
- 缩进：try block 内的 `text = await self.call_llm(...)` 比原代码多 4 个空格缩进；`except Exception: return _fallback_subtopics(report_shape)` 与 `try:` 同列；后续 `payload = self.parse_strict_json(text, ...)` 缩进与原代码一致（仍在 `process()` 函数体内 8 空格）。
- 语法：`try/except` 后面的 `payload = ...` 行，`text` 名字仍在作用域内（try 子块的局部变量在 except-fallthrough 之后仍可见），无 UnboundLocalError 风险——因为 except 路径直接 `return`，不再触达 payload 行。

### 6 个 decomposer 测试逐条 trace（5 老 + 1 新）
1. `test_decomposer_happy_path_standard` — `_FakeLLMClient` 返回 5 支柱 valid JSON 字符串 → `try` 内 `await call_llm` 不抛 → `text` 拿到字符串 → `parse_strict_json` 拿到 dict → `_validate_subtopics` 返回 5 SubtopicMeta → 输出与原行为完全一致。✅
2. `test_decomposer_drops_unreachable_anchor_keeps_subtopic` — 同上，`try` 不抛；不可达 anchor 在 `_anchor_reachable` 检查里被丢；sub-topic 自身保留。✅
3. `test_decomposer_short_branch_caps_to_what_or_what_stack` — 同上，`try` 不抛；short 分支取 `[what, stack]`。✅
4. `test_decomposer_invalid_json_falls_back_to_defaults_standard` — `_FakeLLMClient` 返回 `"not json at all, sorry"`，**不抛**（成功返回了一个非 JSON 字符串）→ `try` 不抛 → `parse_strict_json` 退到 fallback `{"subtopics": []}` → `_validate_subtopics` 返回 `[]` → `validated or _fallback_subtopics(report_shape)` 触发 5 默认。这条路径与 FIX-02 的 try/except 路径**互斥**（前者是"LLM 成功但内容垃圾"，后者是"LLM 直接抛错"）；前者保留原"在 try 之后兜底"的行为不变。✅
5. `test_decomposer_polyglot_appended_when_multilingual` — 同 #1，`try` 不抛；5+1 / 5 两个分支都不动。✅
6. `test_decomposer_falls_back_to_default_pillars_on_llm_exception`（**新**）— `_RaisingLLMClient.call_llm` 在第一次 await 时 `calls += 1` 然后 `raise RuntimeError`；`BaseAgent.call_llm` 内 `result = method(...)` 拿到 coroutine → `if inspect.isawaitable: result = await result` 这行抛出 `RuntimeError`；`process()` 的 `except Exception:` 捕获 → 直接 `return _fallback_subtopics("standard")` → 拿到 5 默认 SubtopicMeta；外层断言：(a) ids 顺序对、(b) titles 与 `_DEFAULT_TITLES` 5 项字面值对、(c) `_RaisingLLMClient.calls == 1`（即没有重试循环）、(d) `anchor_map["what"] == ("README.md",)` + `anchor_map["arch"] == ()` 锁两种 anchor 形态。**未触达** `parse_strict_json` / `_validate_subtopics` 任一行。✅

### 全套 deep_research 测试影响范围
| 测试文件 | 影响 |
| --- | --- |
| `test_deep_research_decomposer.py` | +1 测试（5 → 6），其它 5 个不受影响（trace 见上） |
| `test_deep_research_triage.py` | 0（不 import decomposer） |
| `test_deep_research_policy.py` | 0 |
| `test_deep_research_scratchpad.py` | 0 |
| `test_deep_research_prompts.py` | 0（不 import decomposer，只读 yaml） |
| `test_deep_research_investigator.py` | 0（投资者已有同模式 try/except） |
| `test_deep_research_note_taker.py` | 0 |
| `test_deep_research_composer.py` | 0 |
| `test_deep_research_loop.py` | 0（loop 用 fake 注入的 Decomposer，try/except 在内部，外部行为不变） |
| `test_deep_research_auto_trigger.py` | 0 |
| `test_app_config.py` | 0 |
| `test_contracts.py` | 0 |
| `test_teaching_experience.py` | 0（与 deep_research 解耦） |

预期总测试数：旧 69 项 + 1 项 = **70 项**，全绿。

### 用户最终验证（需用户跑命令）
```
python -m compileall new_kernel\deep_research\agents\decomposer.py
python -m pytest -q new_kernel\tests\test_deep_research_decomposer.py
python -m pytest -q new_kernel\tests\test_deep_research_*.py
```
预期：第 1 条 0 SyntaxError；第 2 条 6 passed；第 3 条 全绿（含 6 项 decomposer + 其它 deep_research 测试）。

## Spec Alignment
- AGENTS.md §3.2（Phase 1 Decompose 输入/输出/约束/JSON 解析失败兜底）— 改动**扩展**了"JSON 解析失败 → 走兜底"语义到"LLM HTTP 异常 → 走同一条兜底"，前者由原代码末段 `validated or _fallback_subtopics(...)` 实现、后者由 FIX-02 新加的 try/except 实现，两者最终都汇到 `_fallback_subtopics(report_shape)`，行为对等。
- AGENTS.md §12.2（错误处理通则："LLM 调用失败：抛出，由 TurnRuntime 转为 ErrorEvent；本模块不 swallow LLM 异常"）— FIX-02 是**文档化偏离**：跟随 SA-04 Investigator 的同款偏离判例（详见 SA-10 Decisions §"Investigator 的 LLM 异常 swallow 偏离 §12.2 通则"），优先级是"用户体验比 ops 可见性更重要"。RECON-FINAL §候选 #2 修复方向也明确建议这条偏离。
- AGENTS.md §11.1（import 纪律）— 0 改动，仍只 import `json` / `collections.abc.Iterable` / `typing.Any, Literal` / `..research_scratchpad.SubtopicMeta` / `.base_research_agent.BaseResearchAgent`，未引入任何新模块。
- AGENTS.md §13（测试策略）— 新增 1 个测试覆盖"LLM 同步抛错"分支，使用 fake LLM client（不触发真 LLM）；测试规模 ~25 行 ≤ spec 预算。
- RECON-FINAL-diagnosis.md §候选 #2 / §修复方向 / §如何 1 步分辨主因 vs 候选 #2 — FIX-02 实现了候选 #2 的修复建议；与 FIX-01（scratchpad 类型错配，主因）正交、独立。两条 fix 同时合入后，`internal_detail` 包含 `LLMClientError` / `BadRequestError` / `AuthenticationError` / `InsufficientBalance` / `RateLimitError` / `HTTP 4XX/5XX` 任一字面值的故障形态都不再走到 `ErrorEvent`，而是用户拿到 5 默认支柱的 onboarding 报告。
