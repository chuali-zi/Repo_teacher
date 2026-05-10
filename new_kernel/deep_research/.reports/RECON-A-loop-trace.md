# RECON-A · Loop Trace 侦察

## What

调研 deep_research 自动 onboarding 在真实 LLM (DeepSeek-Chat) 下接入仓库后约
2 秒就 fail 的根因。从 `repositories.py:_kickoff_repo_onboarding` 开始,逐行
trace 到 `DeepResearchLoop.run` 的 Phase 0/1,把所有"在 2 秒内可能 raise"的点
列出来并按可能性排序。**不修代码**。

## Methodology

读了下列文件全文:

- `new_kernel/deep_research/deep_research_loop.py` (511 行)
- `new_kernel/deep_research/agents/decomposer.py` (197 行)
- `new_kernel/deep_research/agents/composer.py` (254 行)
- `new_kernel/deep_research/agents/investigator.py` (178 行)
- `new_kernel/deep_research/agents/note_taker.py` (127 行)
- `new_kernel/deep_research/agents/base_research_agent.py`
- `new_kernel/agents/base_agent.py`
- `new_kernel/turn/turn_runtime.py` (full)
- `new_kernel/turn/cancellation.py`
- `new_kernel/api/routes/repositories.py` (full)
- `new_kernel/api/app.py` (`_build_default_runtime` / `_build_deep_research_loop`)
- `new_kernel/contracts.py` (event shapes)
- `new_kernel/events/event_bus.py` / `event_factory.py`
- `new_kernel/llm/client.py` (异常映射: `_create_completion` 第 301-323 行)
- `new_kernel/session/session_state.py` / `session_store.py`
- `new_kernel/repo/parse_pipeline.py` (片段: 188-216 行,确认 `status=READY`)
- `new_kernel/deep_research/triage.py`
- `new_kernel/deep_research/research_scratchpad.py`
- `new_kernel/deep_research/prompts/zh/decompose.yaml`
- `new_kernel/tests/test_deep_research_loop.py` (确认 stub 行为)

辅证:

- `git diff HEAD --stat` 显示本次修改集中在 `deep_research_loop.py` (+509 行)
  和 `api/routes/repositories.py` (+79 / -42 改写自动触发)。
- `llm_config.json`: provider 是 DeepSeek (`base_url: https://api.deepseek.com`,
  `model: deepseek-chat`)。

构建执行轨迹的方法:从 `start_turn(initiator="system")` 拿到的 task,沿
`_run_turn -> deep_loop.run -> Phase 0 triage -> 第一个 emit_progress ->
Phase 1 cancellation_token.raise_if_cancelled -> Decomposer.process` 走,
对每一步问"能 raise 吗?多久?"。Phase 0 是纯函数,2 秒内一定到了
Decomposer 的 LLM call。

## Top-3 hypotheses (ranked by likelihood)

### 1. Decomposer 的 LLM 调用直接抛异常,Phase 1 没有 fallback 兜底

- **触发点**: `deep_research/agents/decomposer.py:69-75`(`await self.call_llm(...)`)
  → `DeepResearchLoop.process` (loop.py:189-192) → 直接被 TurnRuntime
  `except Exception` 接住 (turn_runtime.py:390-400)。
- **失败模式**: Phase 0 triage 是纯函数,1 ms 内出第一个
  `DeepResearchProgressEvent(phase="triage")`;接着 Phase 1
  `cancellation_token.raise_if_cancelled()` 通过;然后立刻打 LLM。**这就是 2 秒**。
  DeepSeek `chat/completions` 大概 0.5-1.5 秒内可能拒绝(HTTP 400 / 422 / 401),
  也可能因为请求体结构错误立刻拿到 `BadRequestError`/`AuthenticationError`,
  又或者你的 `api_key` 已用完 (DeepSeek 余额耗尽返回 402)。
  对照 `llm/client.py:301-323`,这些异常被裹成 `LLMClientError` /
  `LLMAuthenticationError` / `LLMRateLimitError` 后**继续 raise**。
  Decomposer 对此 **完全没有 try/except** (对比 Investigator 第 69-78 行就有),
  异常一路上抛到 TurnRuntime,变成 `ErrorEvent`。
- **证据 (代码)**:

  ```python
  # decomposer.py:69-75 — 没有 try
  text = await self.call_llm(
      user_prompt,
      system_prompt=self.get_prompt("system"),
      response_format={"type": "json_object"},
      temperature=0.2,
      max_tokens=900,
  )
  ```

  ```python
  # investigator.py:69-78 — 这里有 try,decomposer 没有
  try:
      text = await self.call_llm(...)
  except Exception:
      return _fallback_parse_failure()
  ```

  ```python
  # llm/client.py:315-323 — provider 错误转 LLMClientError 后再 raise
  except AuthenticationError as exc:
      raise LLMAuthenticationError(...) from exc
  except APIRateLimitError as exc:
      raise LLMRateLimitError(...) from exc
  except (APIStatusError, APIError) as exc:
      raise LLMClientError(f"LLM API error: {exc.__class__.__name__}") from exc
  ```

  ```python
  # turn_runtime.py:390-400 — 兜底变 ErrorEvent
  except Exception as exc:
      error = _exception_to_api_error(exc, mode=mode)
      status = await self._mark_failed(status_tracker, error.message)
      await _emit_to_sink(sink, self._event_factory.error_event(...))
  ```

- **期望的错误消息**: 用户能在 SSE `error_event` 里看到
  `error.error_code = "llm_api_failed"`、
  `error.message = "回答生成失败,请稍后重试。"`,
  `error.internal_detail` 形如 `"LLM API error: BadRequestError"` 或
  `"LLM authentication failed"`。
- **验证方式**: 让用户把后端 stderr / 浏览器 SSE 中 `ErrorEvent.error.internal_detail`
  原文贴上来。如果 internal_detail 含 `BadRequestError` / `LLMClientError` /
  `LLMAuthenticationError` / `LLMRateLimitError` /
  `APIStatusError`,直接锁定本假设。也可以临时把 decomposer.py:69 包进
  try/except Exception as e: print(repr(e)) 做单测。

#### 1a. (子假设, 同根源) DeepSeek 不接受当前 prompt 触发 JSON-mode 400

- DeepSeek 的 `response_format={"type":"json_object"}` 文档上要求
  prompt 里**显式包含 `json` 字样**,否则提供商会拒绝并返回 400。看
  `prompts/zh/decompose.yaml:16-19`:
  > 只输出严格的 JSON,不要任何 Markdown
  英文 "JSON" 是大写,DeepSeek 的检测是大小写不敏感,这一项应该能过。但若
  DeepSeek 把 `response_format` 转给后端服务遇到任意空响应/超长输入也会
  返回 400-类错误 → 走第 1 条相同链路。
- **如果是这个**: `internal_detail` 多半含 `BadRequestError`,
  message 包含 DeepSeek 服务端的提示。

### 2. 真实 `repo_overview` 文本未带 `language_counts` 行 → triage 直接走 standard,但 anchor 全部被 dropped 不是问题; 真问题是 `_make_overview_proxy` 对真实 overview 的解析缺字段不会 raise,但 Decomposer 拿到的 prompt 字段比 stub 测试更稀疏

- **触发点**: `deep_research/deep_research_loop.py:93-118` (`_make_overview_proxy`)
  读 `state.repo_overview.text` 时只解析两行 (`primary_language` /
  `file_count`),其它字段 (`language_counts`/`top_level_paths`/`entry_candidates`)
  全部丢失。
- **失败模式**: 对真实 `RepoOverview.text`,**proxy 永远不会 raise**——它只
  做 `.splitlines()` + 子字符串匹配。所以 Phase 0 triage 一定出 `standard`
  (因为 primary_language 真实仓库一般都不是 None/Markdown)。然后传给
  Decomposer 的 `repo_overview` 是这个 proxy。Decomposer 用
  `top_level_paths=[]` 和 `entry_candidates=[]` 渲染 user prompt,实际请求
  prompt 长度仍然几百 tokens,**LLM 调用本身不会因这个失败**。
- **真正的次级风险**: prompt 内容比 stub 测试更短,DeepSeek 看到 prompt 提到
  "顶层路径列表: []" 之后可能产出空 JSON 或非法格式,但这不会 raise——
  `parse_strict_json` 有 fallback,`_validate_subtopics` 也有
  `_fallback_subtopics`,**只有当 LLM 网络/API 调用本身抛错才会 fail**。
  所以这个假设只能与 Top-1 共谋。如果 LLM 成功返回任何东西(哪怕乱码),
  loop 都会继续到 Phase 2,远不止 2 秒。
- **证据**: 见 `_make_overview_proxy` 整段;以及 decomposer.py:79-85 的兜底。
- **期望的错误消息**: 不会单独触发错误事件;只能与 1 共谋。
- **验证方式**: 不需要单测;看 decomposer 的 LLM 实际请求体即可。

### 3. Composer 的 streaming `response_format` 非显式,不是问题; 但 `Composer.stream_llm` 对空 chunk 流量保护; 真正的次级 raise 来自 `_build_event` Pydantic 校验失败 (低概率)

- **触发点**: `deep_research_loop.py:413-437` `_emit_progress` 构造
  `DeepResearchProgressEvent`。
- **失败模式**: 第一次 `_emit_progress(...)` 时如果传入的 `summary` 是 None
  (来自 `decision.reason`,但 `triage()` 总是返回非空 str,所以**不会** None);
  如果 `phase` 不是 str(它就是 `"triage"`,不会失败);如果 `current_target`
  是 None,字段允许 None,也没问题。**这条路径几乎不可能 raise**。
- **次假设 - `AnswerStreamStartEvent` 的 mode 字段**: 模型 `mode: ChatMode`,
  `use_enum_values=True`。传入的是 `ChatMode.DEEP`,Pydantic 接受 enum 实例。
  不会 raise。
- **证据**: contracts.py:333-337(`AnswerStreamStartEvent` 字段) +
  ContractModel 配置 (`extra="forbid"`)。所有传入字段都在 schema 内。
- **结论**: 排在 #3 是因为我把"非 LLM 抛异常"的概率穷举完后,只剩这一类
  Pydantic-style validation,在当前代码里几乎封闭。
- **验证方式**: 不重要;若 `internal_detail` 包含 `ValidationError` 或
  `pydantic.error_wrappers` 才考虑。

## Other candidates (less likely)

- **(C4)** `state.repository.status` 不是 `"ready"`: 已证伪——
  `parse_pipeline.py:195` 显式写 `RepositoryStatus.READY`,且
  `_run_parse_pipeline` 在 `_kickoff_repo_onboarding` 之前 set 这个 repository。
- **(C5)** `state.event_bus` 缺失: 已证伪——`SessionStore.create()`
  必然实例化 `EventBus()` 并赋给 `event_bus` 字段。
- **(C6)** `state.scratchpad` 缺失: 已证伪——SessionState dataclass 默认
  `scratchpad=Scratchpad()`,不是 `None`。但注意:**TurnRuntime 把
  `state.scratchpad` 当作 `Any` 传给 deep_loop**——它实际是 `memory.Scratchpad`,
  不是 `ResearchScratchpad`!`DeepResearchLoop.run` 第 193 行调
  `scratchpad.set_subtopics(...)`,而 `memory.Scratchpad` 多半没有这个方法。
  这会导致 **AttributeError → TurnRuntime 接住 → ErrorEvent**。**这其实是一个
  和 Top-1 并列严重的怀疑点**!但它发生在 Phase 1 末尾(decomposer 已成功
  返回之后),时序上比 Top-1 LLM 调用更晚——只有当用户的真实 LLM 是流畅
  返回的、Phase 1 拿到 subtopics 后才会触发。**如果 internal_detail 含
  `'Scratchpad' object has no attribute 'set_subtopics'` 就是 C6**。
- **(C7)** `_emit_progress` 在 stub 中走 `event_factory=None` 分支;在
  生产中 `_build_deep_research_loop` 也传 `event_factory=None`(loop 内部
  自己造事件 via Pydantic ctor)。两边一致,不引入差异。
- **(C8)** `AgentPhase.STREAMING` 不存在: 已证伪——contracts.py:106
  确有 `STREAMING = "streaming"`,update_phase(phase=AgentPhase.STREAMING) OK。
- **(C9)** `EventBus.emit` 阻塞: `put_nowait + QueueFull -> warning + drop`,
  不会 raise。
- **(C10)** `cancellation_token.raise_if_cancelled` 触发: 用户没主动取消,
  且 token 在 turn 启动时新建,_cancelled 默认 False,排除。
- **(C11)** Decomposer YAML 缺 placeholder/key 导致 `.format` KeyError:
  我对 `decompose.yaml` 第 47-70 行核了一遍,user_template 用到的 key 是
  `{report_shape}` `{primary_language}` `{language_counts}` `{file_count}`
  `{top_level_paths}` `{entry_candidates}` `{repo_overview_text}` —— decomposer.py:60-68
  对应位置全部传齐。**不会 KeyError**。

## What I would ask the user

1. **后端日志/SSE 里 `ErrorEvent.error.internal_detail` 原文是什么?** 这个字段
   是 Top-1 与 C6 的判定关键。如果含 `BadRequestError` / `AuthenticationError`
   / `LLMClientError` / `RateLimit` → Top-1。如果含 `set_subtopics` /
   `AttributeError` / `'Scratchpad' object has no attribute` → C6。
2. **DeepSeek 账号当前余额/配额状态?** `llm_config.json` 显示是
   `deepseek-chat`。如果余额耗尽会返回 402 / `insufficient_balance`,被映射
   为 `LLMClientError`,2 秒内即抛。
3. **后端 stderr 是否有 traceback?** 由于 `_observe_task_result` 主动吞
   exception,只能从 `error_event.internal_detail` 看到错误类名;但
   `LLMClient._create_completion` 第 311 / 313 / 322 行用 `logger.exception`
   会打完整 traceback,看 stderr 应该能直接定位到 `chat/completions`
   响应的 status_code 与 message。

---

## 附:执行轨迹时间线 (估算)

| t (ms) | 动作 | 来自 |
| --- | --- | --- |
| 0 | `_kickoff_repo_onboarding` 调 `start_turn` | repositories.py:262 |
| ~5 | `_run_turn` 异步任务跑起来,emit `agent_status(researching)` | turn_runtime.py:418 |
| ~10 | `DeepResearchLoop.run` 入口,Phase 0 triage(纯函数) | loop.py:172-185 |
| ~15 | emit `DeepResearchProgressEvent(phase=triage)` | loop.py:176 |
| ~16 | Phase 1 `cancellation_token.raise_if_cancelled` (no-op) | loop.py:188 |
| ~16 | **`Decomposer.process` 起调用 `call_llm`** | loop.py:189 |
| 16-2000 | DeepSeek `chat/completions` 网络往返 | llm/client.py:304 |
| ~2000 | DeepSeek 返回错误 → `LLMClientError` raised → 上抛 | llm/client.py:322 |
| ~2005 | TurnRuntime `except Exception` 捕获 → emit `error_event` | turn_runtime.py:390 |

**结论**:用户报告的"2 秒后 fail"完全对应 Decomposer LLM call 失败后被
TurnRuntime 捕获的链路。
