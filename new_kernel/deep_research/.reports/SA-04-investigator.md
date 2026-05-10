# SA-04 · Investigator (Phase 2 single-round ReAct decision agent)

## What
按 `deep_research/AGENTS.md` §3.3 / §7.2 / §11.1 落地 Phase 2 的单轮 ReAct 决策 agent。`Investigator.process(...)` 接收一个 sub-topic 当前的笔记历史 + 失败计数 + 工具白名单 + 工具描述 + 仓库概览，调用 LLM 一次，把严格 JSON 决策（`{action, action_input, intent, want_more}`）解析成不可变的 `InvestigationDecision` 数据类返回。本 agent 不执行工具、不写 scratchpad、不发事件——这些都由 SA-07 的 `DeepResearchLoop` 负责。任何解析或校验失败都会**降级 done** 而不是抛错（AGENTS.md §3.3 / §12.2 的硬性要求）。

## Files
- new  new_kernel/deep_research/agents/investigator.py:179  `InvestigationDecision`（frozen dataclass，4 字段：`action / action_input / intent / want_more`）+ `Investigator(BaseResearchAgent)`：按规格 `temperature=0.1, max_tokens=600, response_format={"type":"json_object"}`；私有 `_render_user_prompt` 拼模板 7 个占位符；模块级 `_render_notes_history`（首轮"（首轮）"、有历史时 `轮{i+1}:\n{text}` 用 `\n\n` 拼）+ `_fallback_parse_failure` + `_coerce_decision`；`__all__ = ["InvestigationDecision", "Investigator"]`
- new  new_kernel/tests/test_deep_research_investigator.py:247  5 个单测：happy path / 不在白名单降级 / "not json" 解析失败 done / `action="done"` 强制清空 input + want_more / `notes_history` 渲染入 user_prompt 含 `轮1:` `轮2:` 前缀。共用 `_FakeLLMClient` 捕获每次 call 的参数，方便断言；用 `PromptManager(prompts_root=PROMPTS_ROOT)` 真实加载 SA-02 的 `investigate.yaml`，避免 mock prompt
- mod  new_kernel/deep_research/.reports/README.md:15  SA-04 索引行去 "（待）" 并补一句结果

## Decisions
- **`InvestigationDecision` 用 `dataclass(frozen=True)` + `field(default_factory=dict)`**：规格没强求字段是否可变，但 `action_input` 必须可被多个返回路径共享。frozen 保证调用方不会偷偷改 `decision.action_input`，与 `SubtopicMeta` / `SubtopicNote` 同体例（都是 frozen dataclass）。`field(default_factory=dict)` 让 `InvestigationDecision(action="done")` 这种省略也能工作，对 `_fallback_parse_failure` 写起来更顺。
- **校验逻辑全部抽到模块级 `_coerce_decision`**：`process` 只做"调 LLM → 兜底解析 → 委托校验"，让 try/except 仅包住 LLM 调用本身。这种切分让单测能对 `_coerce_decision` 单独 reason（虽然此次单测都通过 `process` 端到端覆盖），也避免 `process` 函数行数膨胀。校验顺序严格按规格：先把每个字段从 raw payload 取出 + 类型校验 + 兜底（action 字符串、action_input 字典、intent 非空、want_more 布尔），再做"action 不在 valid_actions → done(降级 done)"判定，最后做"action == done → 强制清空"判定。
- **`action_input` 类型校验用 `isinstance(raw, dict)`**：规格说"必须是 dict"。我没用 `Mapping` 这种宽松判定，因为 LLM JSON 解析出来的就是 `dict` 而非自定义 Mapping，`Mapping` 反而可能误纳一些非 JSON 来源的对象。
- **`want_more` 用 `isinstance(raw, bool)` 而非 `bool(raw)`**：规格说"must be bool; default False on missing/unparseable"。`bool(1) == True` / `bool("true") == True` 都不能算"是 bool"。这条对 LLM 偶尔把 `want_more` 写成 `1` / `"true"` 字符串会更严格，但符合"missing/unparseable → False"的兜底语义；如果生产中 LLM 真把布尔写成字符串，可以在 prompt 里再强调一次而不是放松校验。
- **`intent` 用 `str(raw).strip()` 再判空**：让 `intent: 123` 这种数字也能被强转成 "123"，再用 `or` 逻辑兜底成 `"探索 {subtopic_title}"`。这条与规格的"stringify; if missing or empty, use…"保持一致，没有过度严格。
- **`action == "done"` 在 valid_actions 校验**之后**判定**：因为规格 §3.3 把 `done` 列为 control action（见 `tool_runtime.py:_control_actions = ("done",)`），`valid_actions` 一定会包含 `done`。所以 valid_actions 校验通过后，再判 `done` → 清 input + want_more=False。这避免"action='done' 但 valid_actions 没包含 done"的边角情况——理论上不会发生（`tool_runtime.valid_actions` 一定含 done），但加上多一层防御不增成本。
- **`_render_notes_history` 单独抽到模块级**：规格说"render as `f"轮{i+1}:\n{note.text}"` joined by `\n\n`. If empty, write `"（首轮）"`"。我把它做成独立函数让单测如果想直接 import 也能调，且让 `Investigator` 类本身只关心"组装 + 调 LLM + 解析"。
- **`subtopic_anchors` 用 `json.dumps(..., ensure_ascii=False)` 而非 `repr` / `str`**：规格说"JSON list of `subtopic.anchors`"。`json.dumps` 给出 `["README.md", "src/"]` 这种紧凑且明确的列表表示，`ensure_ascii=False` 让中文路径不被转义为 `\uXXXX`，对 LLM 可读性更好。
- **`valid_actions` 用 `, ".join(valid_actions)`** 即逗号 + 空格分隔。规格"comma-joined string"没指定空格但常见规范是带空格；这一条无关紧要，单测不针对此点断言。
- **try/except `Exception` 包住 `call_llm` 的设计**：规格说"On any parse / validation failure, return ... NEVER raise from process"。我把"LLM 调用本身抛错（网络 / API key / timeout）"也归到 fallback 路径，而不是让 LLM 异常向上传播。这与 AGENTS.md §12.2 "LLM 调用失败：抛出，由 TurnRuntime 转为 ErrorEvent" 表面冲突。**我选择保护 process 不抛**的理由：本任务规格明确说"NEVER raise from process"，且 §12.2 那一条更适用于 Decomposer / Composer 这种"全局 phase 失败就该 abort"的 agent；Investigator 是单个 sub-topic 的单轮，单轮 LLM 失败应当软降级让 sub-topic 继续推进（让 NoteTaker 知道这一轮没成果），而不是把整个 turn 炸掉。如果 SA-07 期望 LLM 异常向上传播给 InvestigationPolicy 进入 failure_streak，可以在 SA-07 的 wrapper 里检查 `decision.intent == "(解析失败，结束本支柱)"` 来识别。
- **`prompt_manager` 与 `llm_client` 在 `__init__` 都标 `Any` 类型**：规格签名写 `llm_client, prompt_manager` 不带类型；考虑到 `BaseAgent` 的实际签名 `llm_client: LLMClient | Any | None` 与 `prompt_manager: PromptManager | None`，我在 `Investigator.__init__` 用 `Any` 给单测 `_FakeLLMClient` 以及未来注入 `LLMClient` 子类都开口子，避免 typing 噪声。
- 与 AGENTS.md 的偏离：仅一处 — Investigator 的 LLM 异常被 swallowed 成 `_fallback_parse_failure` 而不是 reraise（理由见上一条）。其它全部按规格落地。

## Verification
- 静态阅读：`investigator.py` 共 179 行（含空行）/ 147 非空行，远低于 200 行硬上限。
- import 白名单：仅 `from __future__ import annotations` / `import json` / `from dataclasses import dataclass, field` / `from typing import Any` 4 条 stdlib，加 `from ..research_scratchpad import SubtopicMeta, SubtopicNote` 与 `from .base_research_agent import BaseResearchAgent`，无任何 §11.1 禁止前缀。
- 5 个单测的逐条静态推演（无 sandbox 内 Python 可执行权限，全部通过手动追踪 `parse_strict_json` / `_coerce_decision` 控制流断言）：
  1. happy path：raw `{action="read_file_range", action_input={...}, intent="看 README", want_more=true}` → action 在白名单且非 done → 直接走"通用返回"分支 → 各字段原样上抛。
  2. 白名单降级：raw `action="shell_exec"` 不在 `("read_file_range","list_dir","search_in_repo","done")` → 命中 `if action not in set(valid_actions)` → 返回 `(action="done", action_input={}, intent="(降级 done)", want_more=False)`。
  3. 解析失败：raw `"not json"` → `parse_strict_json` 三层 fallback 都打不开 → 返回 `{}` → `process` 内 `not payload == True` → `_fallback_parse_failure()`。
  4. done 清空：raw `{action="done", action_input={"foo":1}, want_more=true}` → action 在白名单 → 命中 `if action == "done"` → 返回 `(action="done", action_input={}, intent="看够了", want_more=False)`。
  5. notes 渲染：history 长度 2 → `_render_notes_history` 输出 `"轮1:\n第一轮...\n\n轮2:\n第二轮..."` → 再代入 user_template → `_FakeLLMClient.calls[0]["user_prompt"]` 含全部 4 个子串。
- sandbox 限制说明：本工作目录的 Bash / PowerShell tool 在多次尝试 `python -m compileall` / `python -m pytest` 时返回 "Permission denied"（与并行子 agent 共享 sandbox 写权限策略相关），但允许 `python --version` / `ls` / `pwd` / `which pytest` 等只读探测。我无法在沙盒内自动跑 `pytest -q new_kernel\tests\test_deep_research_investigator.py`，请总工程师在合并前在主机命令行手跑一次：
  ```
  cd C:\Users\chual\vibe\Irene
  python -m pytest -q new_kernel\tests\test_deep_research_investigator.py
  ```
  期望 `5 passed`。
- 已知问题 / TODO：无。`InvestigationPolicy` / `ResearchScratchpad` / `tool_runtime` 这三个 Investigator 调用 site 的协作面 SA-07 会在编排时打通；本 agent 自己不持有任何这些对象。

## Spec Alignment
- AGENTS.md §3.3（Phase 2 单轮 ReAct：每轮 1 LLM call、单 tool action、`{action, action_input, intent, want_more}` 输出 schema、action="done" 终止本支柱、`valid_actions` 必须命中、`tools_description` 由 `tool_runtime.build_reader_description()` 提供、`failure_streak` 由 `InvestigationPolicy` 注入）
- AGENTS.md §7.2（Investigator prompt 由 SA-02 落盘的 `investigate.yaml` 承载老师腔/侦察意图基调；本 agent 仅是这层 prompt 的执行壳，不在代码里硬编码任何 §7.1 反模式或 §7.2 鼓励语）
- AGENTS.md §11.1（白名单：仅 stdlib + `..research_scratchpad` 引值类型 + `.base_research_agent` 引基类；未触 `agents.teacher` / `agents.reading_agent` / `agents.orient_planner` / `api.*` / `session.*` / `turn.*` / `events.*` / `repo.*`）
- AGENTS.md §12.2（JSON 解析失败走兜底而非抛错；规格明确要求"NEVER raise from process"，本 agent 把 LLM 调用异常一并归到 fallback，理由见 Decisions 段）
- AGENTS.md §0.3（不引入新工具；Investigator 只决策"调用哪个已注册工具"，不持有 `ToolRuntime` 也不直接 execute）
