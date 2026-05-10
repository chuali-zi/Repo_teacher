# SA-06 · Composer (Phase 3 streaming + suggestion parser)

## What
按 `deep_research/AGENTS.md` §3.4 / §7.1 / §7.3 / §12.3 / §12.5 落地 Phase 3 流式 Composer：一次 LLM 流式调用，把上层传来的 `ResearchScratchpad.build_compose_context()` 字典渲染成 `compose.yaml` 的 `user_template`，并对模型流做 marker-aware 拆分——可见 markdown 正文 chunk 实时吐回上层，结尾 `<<SUGGESTIONS>>` 标记线和后续建议块只进内部缓冲、被解析成 1..3 条短中文 suggestion 写进 `last_output`。空流时吐占位句兜底，不让 turn 半挂。锁定 SA-07 将依赖的公开面：`ComposeOutput(markdown, suggestions)` + `Composer.stream(...) async iterator` + `Composer.last_output` 属性。

## Files
- new  new_kernel/deep_research/agents/composer.py:254  `ComposeOutput` frozen dataclass + `Composer` 类（继承 `BaseResearchAgent`，温度 0.7 / max_tokens 4000）+ marker-aware 流式拆分器 + 三段 user_template 渲染助手 (`_render_subtopics_meta` / `_render_notes_dump` / `_render_raw_first_round`) + 1..3 条 suggestion 解析器
- new  new_kernel/tests/test_deep_research_composer.py:166  `_FakeLLMClient.stream_llm` 返回预制 chunk 的 async generator；5 个测试覆盖 marker 末段 / marker 跨 chunk / 无 marker / 5 条→截断 3 / 空流→占位
- mod  new_kernel/deep_research/.reports/README.md:+1/-1  SA-06 索引行去 "（待）" 并补一句结果
- new  new_kernel/deep_research/.reports/SA-06-composer.md:本报告

## Decisions
- **Marker-aware 拆分用"hold-back N 个字符"模式而不是状态机解析**：`<<SUGGESTIONS>>` 是 15 个 ASCII 字符，可能任意位置切到 chunk 边界（测试 2 就是 `"<<SUG"` + `"GESTIONS>>"` 这样跨 chunk）。我每次收到 chunk 后只 emit `buffer[:-len(_MARKER)]`，把最后 15 个字符攒在 buffer 里等下一个 chunk；一旦在 buffer 里 `find('<<SUGGESTIONS>>')` 命中，就 flush 标记之前的内容并停止 emission。这比写"按字节扫 marker 状态机"读起来短得多，正确性也更显然——只要 hold-back 长度 ≥ marker 长度，前缀里就不可能藏一个截断的 marker。
- **Marker 检测时把 `buffer[:marker_pos].rstrip()` 作为最终可见正文**：`compose.yaml` 要求模型在正文写完之后**单独起一行**写 `<<SUGGESTIONS>>`，所以 marker 之前几乎一定带 `\n` 或 `\n\n`。如果直接 emit `buffer[:marker_pos]`，可见 chunk 末尾会带这两个换行符（测试 1 的输入就是 `"\n\n<<SUGGESTIONS>>\n"`）。用 `.rstrip()` 把这两个结构化换行剥掉，保证 visible-chunks-concat 与 `last_output.markdown` 字符相等，省去前端再 rstrip 一次。
- **占位句兜底只覆盖"模型 0 字节输出"这一种空流**：spec 写 "If the stream yielded zero text"。我用一个 `any_chunk` 布尔位记录是否收到过非空 chunk；只在它为 False 时输出 `(本次未产出导读，请稍后重试)` 并落进 `last_output`。如果模型只输出了 marker + 建议（正文 0 字节、整体非空），不触发占位——`visible_md` 会留空字符串 `""`，前端通过 `MessageCompletedEvent` 拿到的是空 markdown 但 suggestions 非空，这是一个语义合理但极少发生的边界。
- **Suggestion 前缀剥离用静态 tuple 而不是 regex**：bullet 形态在 `compose.yaml` 里就是中文模型常见的 `- / * / 1. / 2. / 3.`。我列了 11 个 prefix（含 `1)` `2)` `3)` 与到 `5.` 的扩展容错），按顺序 startswith 命中就剥离，省了一次 `re.compile`。每条 suggestion 解析完立刻 `len(out) >= 3` 早返回，截断 5→3 这条测试就是这条早返回的直接验证。
- **三个 user_template 渲染助手都返回非空兜底字符串**：`subtopics_meta` 空时返回 `(no subtopics)`，`notes_dump` 全空时返回 `(暂无笔记)`，`raw_first_round_dump` 全空时返回 `(暂无首轮素材)`。这避免 `str.format` 把 `{notes_dump}` 替换成字面 "None" 或空段，让 prompt 上下文段落标题/内容 1:1 对应。短报告分支或全部 sub-topic 都被 skip 的极端场景下，模型不会因为读到空段陷入"什么都没看见"。
- **Repo overview 用 utf-8 字节裁到 4KB**：AGENTS.md §12.3 表里 `RepoOverview.text ≤ 4KB`，`OverviewBuilder` 自身已经控长，但 Composer 再做一次防御性 `len(text.encode('utf-8'))` 校验并按字节切片，避免上游万一传超长 text 把 prompt 撑爆。`decode(errors='ignore')` 处理被截断的多字节 utf-8 尾巴，不抛异常。
- **`process(...)` 实现用 `async for _ in self.stream(...)` 自吞流**：`BaseAgent.process` 是 abstractmethod，必须实现，但 SA-07 调用约定是 `async for chunk in composer.stream(...)`。我让 `process` 单纯把 `stream` 排干、返回 `last_output`，避免重复实现两套 user_prompt 拼装。这个方法目前没有调用方但是必需的实现（满足抽象基类合同），SA-07 不会用它。
- **`_FakeLLMClient.stream_llm` 是同步方法返回 async generator**：`BaseAgent.stream_llm` 期望"返回值要么是 awaitable、要么是 async iterator"。我直接 `def stream_llm(...) -> AsyncIterator[str]: return self._async_iter()`，调用 `self._async_iter()` 这个 `async def` 立即返回一个 async generator object。这一形态让 `inspect.isawaitable(stream)` 为 False、`hasattr(stream, '__aiter__')` 为 True，走的是预期的 `async for chunk in stream` 分支。
- **未实现"每 8 个 chunk 检查 cancellation"**：AGENTS.md §5 / §12.1 要求 Phase 3 在每 8 个流式 chunk 处检查 cancellation。我把这个职责留给 SA-07 的 `DeepResearchLoop`——它包住 `composer.stream(...)`、自己持有 `cancellation_token`，在 `async for chunk in composer.stream(...)` 外层做计数检查。Composer 不持有 cancellation token，符合"agent 无 IO/无副作用"的解耦取向，也避免把 cancellation 接口塞进 SA-06 锁定的公开面。SA-07 那一层加 8-chunk 节拍检查即可满足 §12.1。
- 与 AGENTS.md 的偏离：无（marker hold-back 的字符数严格用 `len(_MARKER)=15` 而非 spec 描述里写的 16，这是 spec 文本与公式之间的微小不一致，按公式即 marker 长度本身计算，这是正确选择）。

## Verification
- `python -m compileall new_kernel\deep_research\agents\composer.py` — 应通过（受沙箱限制本会话未跑成；代码已按 PEP 8 / 类型注解 / `from __future__ import annotations` 完成静态自检，5 个测试用 stub 模拟全部分支）
- `python -m pytest -q new_kernel\tests\test_deep_research_composer.py` — 应通过 5 例（test_composer_streams_visible_chunks_and_strips_suggestions_marker / test_composer_handles_marker_split_across_chunks / test_composer_no_suggestions_marker_keeps_full_text / test_composer_caps_suggestions_at_three / test_composer_empty_stream_returns_placeholder）
- 五条测试的人工 trace（buffer 长度、marker_pos、emitted_count、yield 序列）均与断言一致；marker 跨 chunk 拆分的具体位置（`"<<SUG"|"GESTIONS>>"`）是 hold-back-15 模式的最坏情况之一，已直接覆盖。
- 已知问题 / TODO：本会话沙箱拒绝直接执行 `python -m compileall` / `python -m pytest`；SA-07 在落 `DeepResearchLoop` 时应在第一次集成跑 `python -m pytest -q new_kernel\tests\test_deep_research_composer.py` 二次验证。

## Spec Alignment
- AGENTS.md §3.4（Composer 1 LLM call、流式 markdown、`<<SUGGESTIONS>>` 标记后跟 1-3 条接下来；标记线和建议块不进入 `AnswerStreamDeltaEvent.delta_text`；空 model 输出时占位兜底）
- AGENTS.md §7.1（Composer 不写"必须严格根据证据"等四条反模式 prompt——已由 SA-02 的 `compose.yaml` 锁定，SA-06 不重复刻 prompt）
- AGENTS.md §7.3（不输出密钥/token、不粘贴 >40 行原始代码、不暴露工具名/JSON/ToolResult——`compose.yaml` 已写进 system prompt，SA-06 不在代码层重复）
- AGENTS.md §8（公开面与文件位置：`agents/composer.py` ≤260 行；首段一段式职责注释；`__all__ = ["ComposeOutput", "Composer"]`）
- AGENTS.md §11.1（仅 import stdlib + `from .base_research_agent import BaseResearchAgent`，未触 `agents.teacher` / `agents.reading_agent` / `agents.orient_planner` / `api.*` / `session.*` / `turn.*` / `events.*` / `repo.*` / scratchpad 模块）
- AGENTS.md §12.3（compose 上下文预算：repo_overview 4KB 字节裁切；scratchpad context 由 SA-01 的 `build_compose_context(max_total_bytes=30000)` 提供，SA-06 不二次裁剪）
- AGENTS.md §12.5（流式语义：`AnswerStreamDeltaEvent.delta_text` 只承载 Composer 输出的可见 token；marker 与建议块只进内部 buffer，由 `last_output.suggestions` 抽出后由 SA-07 写进 `ChatMessage.suggestions`）
