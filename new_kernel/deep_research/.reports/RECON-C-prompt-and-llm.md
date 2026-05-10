# RECON-C · Prompt 渲染 + LLM 调用形状 侦察

## What

枚举 4 个 yaml 模板的占位符，与 4 个 agent 里 `template.format(...)` 实际传的 kwargs 做集合差，并核对 `LLMClient.call_llm / stream_llm` 的入参形状。**结论**：`format()` 占位符全对得上，没有 KeyError 风险；`response_format={"type":"json_object"}` 的形状对 OpenAI 与 DeepSeek 都合法，且 decompose / investigate 两份提示里都出现了 "JSON" 字样，满足 DeepSeek 的强制约束；`stream_llm` yield 的是纯字符串，与 Composer 的 `async for chunk in stream` 对得上。**2 秒失败的因不在 prompt 渲染，也不在 LLM 调用形状本身**——更可能在“LLM 配置缺失导致 `turn_runtime` 拿到 `None` loop”、“DeepSeek 把 system 中的 `{}` / 不严格 JSON 输出顶回 BadRequest”，或 RECON-B 已经识别出来的 `Scratchpad` 类型错位。

## Placeholder diff table

下表中“多余”意味着 yaml 模板里没有对应 `{token}`，但 agent 仍然传入；Python `str.format` 会**静默忽略**多余 kwargs，不会抛错。“缺失”意味着 yaml 里有 `{token}` 而 agent 没传，会抛 `KeyError` —— 这才是要警惕的方向。

| Agent | YAML 占位符 | format() kwargs | 缺失 / 多余 |
| --- | --- | --- | --- |
| decomposer | `report_shape, primary_language, language_counts, file_count, top_level_paths, entry_candidates, repo_overview_text` (7 个) | `report_shape, primary_language, language_counts, file_count, top_level_paths, entry_candidates, repo_overview_text` (7 个) | **完全匹配，0 缺失 0 多余** |
| investigator | `subtopic_id, subtopic_title, subtopic_anchors, notes_history, failure_streak, valid_actions, tools_description, repo_overview_text` (8 个) | `subtopic_id, subtopic_title, subtopic_anchors, notes_history, failure_streak, valid_actions, tools_description, repo_overview_text` (8 个) | **完全匹配** |
| note_taker | `subtopic_id, subtopic_title, intent, tool_action, tool_input, observation, success` (7 个) | `subtopic_id, subtopic_title, intent, tool_action, tool_input, observation, success` (7 个) | **完全匹配** |
| composer | `report_shape, repo_overview_text, subtopics_meta, notes_dump, raw_first_round_dump` (5 个) | `report_shape, repo_overview_text, subtopics_meta, notes_dump, raw_first_round_dump` (5 个) | **完全匹配** |

补充检查（`{` `}` 字面量 / re-interpretation 风险）：

- `decompose.yaml:20`（system 块）写了 `{what, stack, why, arch, flow, polyglot}`；`investigate.yaml:18`（system 块）写了 `{}`。但**这两段都在 system 中**，`get_prompt("system")` 读出后**直接交给 `call_llm(system_prompt=...)`，从不进入 `.format()`**，所以这两个字面 `{}` 是安全的。
- `tools_description` 里 `build_reader_description()` 会返回类似 `` | `read_file_range` | `{"path": ..., "start_line": ...}` | `` 的表格，里面有大量 `{...}`。这是**substitution VALUE 的内容**，`str.format` 不会再次解析 substitution 后的字符串，所以**也是安全的**。
- `note_taker._render_tool_input(tool_input)` → `json.dumps(...)` 产物以 `{...}` 包起；同理是 substitution VALUE，无 re-interpretation。
- `notes_history` 由 `_render_notes_history` 拼接 NoteTaker 之前的 `note.text` 自然语言段落而成；即便 LLM 输出里夹带了 `{...}`，也仅作为 substitution 值出现，不会被再次解析。

**结论**：`KeyError` / `IndexError` 由 prompt 模板触发的概率为 0；**不是 2 秒失败的根因**。

## LLMClient shape

- **`call_llm(user_prompt: str = "", *, system_prompt, messages, model_id, temperature, max_tokens, top_p, stop, response_format, timeout_seconds, **request_kwargs) -> str`**（`new_kernel/llm/client.py:134-164`）。所有 4 个 agent 当前用到的 4 个关键字（`system_prompt` / `response_format` / `temperature` / `max_tokens`）都被显式接受。
- **`stream_llm(user_prompt, *, system_prompt, messages, model_id, temperature, max_tokens, top_p, stop, response_format, timeout_seconds, **request_kwargs) -> AsyncGenerator[str, None]`**（`client.py:217-258`）。返回值是**纯字符串异步生成器**——每次 `yield delta_text`，其中 `delta_text` 是 `str` 类型（`_extract_delta_text` 取 `delta.content`，非 str 一律返回 `None` 并被过滤）。Composer 的 `async for chunk in stream:` 拿到的就是 `str`，与 `BaseAgent.stream_llm`（`agents/base_agent.py:62-105`）做的 `yield str(chunk)` 形状一致。
- **`response_format` 行为**：`client.py:293-294` `if response_format is not None: kwargs["response_format"] = dict(response_format)`，**会原样透传给 OpenAI SDK 的 `chat.completions.create(...)` **。OpenAI 接受 `{"type":"json_object"}`；DeepSeek 也接受同样的 shape（DeepSeek API 与 OpenAI 完全兼容）。**唯一需要满足的硬约束**：当传 `response_format={"type":"json_object"}` 时，**prompt 中（system+user 任一处）必须出现 "json" 字样**，否则返回 400 BadRequestError。
  - 我直接 `grep` 了两份 yaml：`decompose.yaml` 在 system L17（"严格的 JSON"）、user_template L69-70（"严格 JSON"、"只输出 JSON"）都出现；`investigate.yaml` 在 system L14（"严格 JSON"）、user_template L60（"严格 JSON 决策。只输出 JSON"）都出现。**这个约束是满足的**。
- **已知不支持/可能拒绝的字段**：
  - `default_temperature=0.2` 在 client 构造时校验 0..2，OpenAI/DeepSeek 都 OK；4 个 agent 用的 0.1 / 0.2 / 0.4 / 0.7 也全在范围内。
  - `top_p` 仅在显式传入时进 kwargs，**4 个 agent 都不传**，无问题。
  - `temperature` 默认 0.2，`max_tokens` 上限取决于模型；compose 用 4000、decompose 用 900、investigate 用 600、note 用 500——都在 deepseek-chat 的 8192 context 上限内。
  - **请求重试**：连接错误 / 超时只重试 1 次（`client.py:302-309`），其余错误一次抛出。
  - **超时**：默认 30s（API runtime 给的 60s 来自 `llm_config.json`），与 2 秒失败的时序完全对不上 —— 不是 timeout。
- **API key / model 来源**：`api/app.py:_build_llm_client`（`api/app.py:307-350`）按下列顺序解析：
  1. `create_app(...)` 显式 kwargs（`llm_api_key` / `llm_model_id` / `llm_base_url` / `llm_timeout_seconds`）；
  2. 项目根 `llm_config.json`（默认路径 `<project_root>/llm_config.json`，由 `_default_llm_config_path` 解析为 `api/app.py.parents[2]/llm_config.json`，即 `C:/Users/chual/vibe/Irene/llm_config.json`）；
  3. **缺一即返回 None**，整个 `turn_runtime` 也会因 `llm_client is None` 而**不构造 deep_loop**（见 `api/app.py:158-173` 的 `if llm_client is not None:`），最终 `turn_runtime` 留下 `deep_loop=None`。
  - 实测 `C:/Users/chual/vibe/Irene/llm_config.json` 已存在，配置：`api_key=sk-6480d0e9...` / `base_url=https://api.deepseek.com` / `model=deepseek-chat` / `timeout_seconds=60`。**配置应该正常**。

补充：composition root 的 `_default_llm_config_path` 走 `api/app.py.parents[2]`：

- `api/app.py` -> `api/` -> `new_kernel/` -> `Irene/`，所以读到的是 `Irene/llm_config.json` ✓。

## Top hypotheses ranked by likelihood

### 1. 与 RECON-B 同根：`Scratchpad` 类型错位，2 秒后崩在 `set_subtopics`

不是 prompt / LLM 形状错。Phase 0 triage 是纯函数，~100ms 内吐 SSE；Phase 1 调一次真实 DeepSeek 调用，约 1-2s 拿到 JSON 文本；返回后立刻 `scratchpad.set_subtopics(list(subtopics))` —— 而 `SessionState.scratchpad` 是 `memory.Scratchpad`，不存在该方法，立刻 `AttributeError`，被 `TurnRuntime._run_turn`（`turn_runtime.py:390-400`）catch 后转成 SSE error event。**这个时序与“开始 → 2 秒后失败”精确匹配**。RECON-B 的报告（`new_kernel/deep_research/.reports/RECON-B-contract-mismatch.md`）已经详细给出修复路径。

### 2. DeepSeek 实际返回非 JSON，但 Decomposer 的 `parse_strict_json` 兜底返回 `{"subtopics": []}`，再被 `_validate_subtopics` 兜底成 `_fallback_subtopics`，**不会** 2s 失败

我把 `parse_strict_json` 看了一遍：会先剥掉 markdown fence，再尝试 `json.loads(...)`，再尝试 `{...}` 之间最大子串再 loads，全失败返回 fallback。**Decomposer 的 LLM 异常本身不会冒泡**——除非 LLM 调用直接抛了 `LLMClientError` 子类，我重读了 `decomposer.py:69-75`，`call_llm` **没有 try/except 包裹**，所以 `LLMAuthenticationError` / `LLMClientError`（包含 BadRequest）**会直接冒泡**。如果 DeepSeek 真的返回了非 200 响应（例如 `model_id` 不在用户账号支持列表、context 超限、prompt 触发了某个 safety 过滤），就会立刻在 ~1-2s 时刻抛错——**和 2 秒失败也吻合**。

可能的诱因：

- `model="deepseek-chat"` 是否仍在用户账号下可用？DeepSeek 已经替换过几次 model id（旧的 `deepseek-chat` 现在大概率可用，但要确认）。
- 我没在代码里看到对 `response_format` 的能力检测；如果换成不支持 JSON mode 的 deepseek-coder 之类，会返回 BadRequest。

### 3. `Investigator` 的 `tools_description` 里 markdown 表头里 pipe `|` + 反引号 `` ` `` 干扰 DeepSeek，但 Investigator 又被 try/except 包住

`investigator.py:69-78` 是**整个 4 agent 中唯一一个**给 `call_llm` 套了 try/except 的；任何 LLM 异常都会降级成 `_fallback_parse_failure() → action=done`。所以即便 Investigator 因 markdown noise 让 DeepSeek 返回奇怪输出，也不会抛——**这个不是 2 秒失败的根因**。但我把它列在这里是因为 Investigator 在 standard 5-pillar 路径上要被调 5 次，每次降级 done 会导致 Phase 2 一片空白，**Composer 拿到全空 scratchpad 后产物质量极差**——属于 follow-up 隐患而不是当前症状。

## What I would ask the user

- 后端启动时打印的 LLM 配置：`model_id` 是不是确实是 `deepseek-chat`？`base_url` 是不是 `https://api.deepseek.com`？API key 头几位匹不匹配 `sk-6480d0e9`？
- 后端 stderr / 日志里有没有以下任一关键字：
  - `AttributeError: 'Scratchpad' object has no attribute 'set_subtopics'`（→ 命中假设 1）
  - `BadRequestError`、`HTTP 400`、`Unknown parameter response_format`、`json_object` 不被支持（→ 命中假设 2）
  - `AuthenticationError`、`HTTP 401`、`Invalid API Key`（→ 命中假设 2 的 auth 子分支）
  - `LLM_API_FAILED`、`回答生成失败，请稍后重试`（→ 这是 `_exception_to_api_error` 的兜底文案，配合 `internal_detail` 字段反推真实异常类）
- 前端 SSE 流里第二条事件是不是 `error_event`？`error.error_code` 是 `LLM_API_FAILED` 还是别的？`error.internal_detail` 字符串具体写什么？这是判定假设 1 / 假设 2 最直接的证据。
- 有没有可能 user 在测的是“小仓库”分支（short = [what] 或 [what, stack]）？两条分支都会调一次 Decomposer，2 秒失败位置一样。
- 触发本次研究的 repo 是哪一个、`repo_overview` 文本大致几 KB？如果 `repo_overview_text` 超过 16K 中文字符，DeepSeek 端会返 context 超限 BadRequest，时间也是 1-2s。
