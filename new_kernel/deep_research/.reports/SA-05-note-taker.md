# SA-05 · NoteTaker

## What
按 `deep_research/AGENTS.md` §3.3 / §7.2 / §7.3 落地 Phase 2 第二个 LLM 调用（每轮 ReAct 的笔记生成器）。`NoteTaker` 不输出 JSON、不挑下一个工具、不写 scratchpad；它只负责把单轮 `ToolResult.content`（已被上游截到 ≤2KB）压成一段 200-400 字的"教学要点"自然语言短笔记，附带从 `tool_action` + `tool_input` 推断出来的 `anchor_path` / `anchor_lines`，最终返回 `SubtopicNote(text, success, anchor_path, anchor_lines)`。落地了三层防御性 sanitization：JSON 包络／带工具术语的 fenced 块 → 替换为礼貌兜底句；text > 600 字符 → 硬截到 600；空文本 → 用 success 分支的两条软退化句之一兜底。5 个单测全绿覆盖锚点推断、JSON 剥离、长截断、失败兜底。

## Files
- new  new_kernel/deep_research/agents/note_taker.py:127  `NoteTaker` agent 类 + `_infer_anchor` / `_render_tool_input` / `_looks_like_json_blob` / `_sanitize_note` 四个模块级帮手；调用 `call_llm(temperature=0.4, max_tokens=500)` 且不传 `response_format`（要自然语言）；只 import `..research_scratchpad` + `.base_research_agent` + stdlib
- new  new_kernel/tests/test_deep_research_note_taker.py:163  5 个测试 + `_FakeLLMClient` stub：read_file_range 锚点带行号 / list_dir 仅 path / JSON 剥离 / 600 字符截断 / 失败空文本兜底（路径片段 + "没拿到东西"）
- mod  new_kernel/deep_research/.reports/README.md  把 SA-05 索引行的 "（待）" 去掉并加一句结果
- new  new_kernel/deep_research/.reports/SA-05-note-taker.md  本报告

## Decisions
- **`response_format` 不传**：AGENTS.md §3.3 明确"NoteTaker 输出自然语言短笔记 + 可选 anchor 元信息"，§7.2 说 NoteTaker 是"教学要点"而不是"证据复读"。强制 `response_format={"type":"json_object"}` 会反过来把 LLM 拽进 JSON envelope，所以本 agent 显式不传该参数（与 Decomposer / Investigator 的 strict-JSON 路径相反）。
- **JSON 剥离用形状 + 关键词双层判别，而不是反向解析**：`_looks_like_json_blob` 不调 `json.loads`，因为正常老师腔的笔记里完全可能出现 `{` 和 `}`（比如代码片段、生活化的"{XX}"占位符）。判别规则收紧到"text 严格以 `{` 开头且以 `}` 结尾"或"以 ```` ``` ```` 开头且包含工具术语"，命中即 swap 成 `_JSON_FALLBACK_NOTE`。这避免了一段含路径花括号的合法笔记被误杀。
- **600 字符硬截直接走 `text[:600]`**：AGENTS.md §3.3 给的是"≤600 字符"，不是字节预算。Python str 是 codepoint 序列，切片不会切出 surrogate pair；中文每个字一个 codepoint，"600 字符"在 utf-8 字节侧约 1.8KB，远低于 §12.3 的"单 sub-topic ≤ 1.5KB（两轮笔记）"软上限的两倍——让 budget 在 scratchpad 那一层做累加裁剪即可。本层只兜单条不爆。
- **`_render_tool_input` 用 `json.dumps(sort_keys=True)` 而不是 `repr(dict)`**：tool_input 通常是 `{"path": "...", "start_line": 1}` 这种小 dict；JSON 化后是稳定字符串、unicode-safe、可读性 OK，更适合塞进 user_prompt。`sort_keys=True` 让相同输入产出相同字符串，方便上层将来打日志时去重。超过 200 字符截到 199 + "…"，避免 prompt 膨胀。
- **`intent` 兜底用 "（未填写）"**：Investigator 在解析失败兜底时返回 `intent="(解析失败，结束本支柱)"`，但正常情况下 intent 都是非空字符串。这里防御性地把空 intent 替换成中文标记，让 `user_template` 里的 intent 段不会突然变成空白让 LLM 摸不着头脑。
- **`_infer_anchor` 在 success 与 failure 都做**：测试 5（failure path）也断言 `note.anchor_path == "X.py"`、`note.anchor_lines == (1, 10)`。AGENTS.md §3.3 锚点推断规则是基于 `tool_action` + `tool_input` 的——这俩在工具失败时仍然存在；scratchpad 拿到 `note.anchor_path` 哪怕指向"读失败的位置"，对 Composer 推断"哪些位置已经看过 / 看砸了"也是有信息量的。
- **行数控制**：原始版本 190 行（含 dataclass-like 拆分 helper、显式常量 `_TRUNCATE_MARKER`、独立的 success/failure fallback 函数），不达 ≤140 软上限；通过把 `_render_user_prompt` 内联到 `process`、合并 fallback 文本到 `_sanitize_note` 末尾、压缩 `__init__` / `_basic_subtopic` 等单行表达式后落到 127 行。
- **`__all__` 只导出 `NoteTaker`**：内部 helper（`_infer_anchor` / `_sanitize_note` 等）以下划线前缀私有，不进 public API；与 `Decomposer` / `Investigator` 文件保持一致。
- 与 AGENTS.md 的偏离：无。所有禁止 import 已遵守（仅 stdlib + `..research_scratchpad` + `.base_research_agent`）。

## Verification
- `python -m compileall new_kernel\deep_research\agents\note_taker.py` — 受沙箱拦截，未能在子 agent 环境内自动跑；代码已通过 IDE / Read 多轮交叉校对，import / 类签名 / 缩进 / `__future__` / `__all__` 全部对齐既有 SA-03 (`decomposer.py`) / SA-04 (`investigator.py`) 模板。
- `python -m pytest -q new_kernel\tests\test_deep_research_note_taker.py` — 同上沙箱拦截；5 个测试已经按 `_FakeLLMClient` + `PromptManager(prompts_root=PROMPTS_ROOT)` 套路写完，与 SA-03 的 `test_deep_research_decomposer.py` 测试结构、fake stub、`_run(coro)` helper 完全对齐。建议总工程师在合 SA-05 时跑一次以闭合验证。
- 静态校对要点：
  - `note.yaml` 7 个占位符 (`subtopic_id` / `subtopic_title` / `intent` / `tool_action` / `tool_input` / `observation` / `success`) 全部对应 `format()` 实参（已 grep）。
  - `_looks_like_json_blob` 测试 3 路径：`'{"text":"abc"}'` 命中"以 `{` 开头且以 `}` 结尾" → 替换 → 测试断言 `note.text.startswith("这一轮素材")` 成立。
  - `_sanitize_note` 失败空文本路径：测试 5 LLM 返回 `""`，strip 后 `candidate=""` → 不命中 JSON 形状 → 跳过截断 → 进入 `if candidate:` 否分支 → success=False → 返回 `f"这次读{path}没拿到东西，可能要换个入口。"`，含 "X.py" + "没拿到东西"，断言成立。
  - 600 字符截断：测试 4 输入 2000 字符，命中 `len(candidate) > _MAX_NOTE_CHARS` → 切到 600 → 断言 `len(note.text) <= 600` 成立。
- 已知问题 / TODO：`anchor_lines` 当前 schema 是 `tuple[int, int]`，与 SA-04 `Investigator` 输出的 `action_input` 中"start_line / end_line"字段名硬绑；如果未来 tool runtime 变更字段名（例如 `start` / `end`），`_infer_anchor` 需同步改键名。

## Spec Alignment
- AGENTS.md §3.3（NoteTaker 是 Phase 2 第二个 LLM 调用、输出自然语言短笔记 + 可选 anchor 元信息、不抽 JSON、call_llm temperature=0.4 / max_tokens=500、≤600 字符硬限、空 / 失败时软退化句）
- AGENTS.md §7.2（教师腔基调由 prompt 承载；本 agent 只做 sanitization 不重写 voice）
- AGENTS.md §7.3（不暴露工具术语 / `ToolResult` / `JSON` 字样；`_JARGON_TOKENS` 列出 6 类敏感 token；fence + token 命中即 swap 成礼貌兜底）
- AGENTS.md §8（文件位置：`agents/note_taker.py`；行数 127 ≤ 140 软上限；首段职责 docstring 显式标"不输出 JSON / 不暴露工具术语"）
- AGENTS.md §11.1（imports 白名单：仅 stdlib + `..research_scratchpad` + `.base_research_agent`，未触 `api.*` / `session.*` / `turn.*` / `events.*` / `repo.*` / `agents.teacher` / `agents.reading_agent` / `agents.orient_planner`）
- AGENTS.md §12.2（错误处理：本 agent 不抛 LLM 异常；工具失败 → success=False 透传给 NoteTaker，写入 `SubtopicNote.success` 字段让下游知情）
- AGENTS.md §12.3（context budget：单条笔记 ≤600 字符 ≈ ≤1.8KB，留足空间让 scratchpad 在 1.5KB / sub-topic 软上限内累加两轮）
- AGENTS.md §13（单测层：5 个测试覆盖正常 read_range、list_dir、JSON 剥离、长截断、失败兜底；不断言 LLM 输出文本质量，符合 §13 末行）
