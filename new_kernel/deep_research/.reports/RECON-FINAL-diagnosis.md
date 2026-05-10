# RECON-FINAL · 2 秒失败诊断（A/B/C 三方合成）

## What
人工接入仓库后 deep_research 在约 2 秒后失败。三个并行侦察 agent（A 链路追踪 / B 合同与事件 / C prompt 与 LLM）独立调查，**收敛到同一根因**。

## 根因（高置信度）

### 主因：Scratchpad 类型错配

- `new_kernel/session/session_state.py:43,65` —— `SessionState.scratchpad` 由 `default_scratchpad_factory()` 创建，类型为 `memory.Scratchpad`（教学循环用的账本，方法是 `set_plan / add_entry / build_reading_context / build_teacher_context`）。
- `new_kernel/turn/turn_runtime.py:354,358` —— `TurnRuntime._run_turn` 把 `state.scratchpad` 原样转交：`scratchpad=state.scratchpad`。
- `new_kernel/deep_research/deep_research_loop.py` Phase 1 收到 Decomposer 结果后立刻调 `scratchpad.set_subtopics(subtopics)`，Phase 2 调 `scratchpad.notes_for(...) / add_note(...) / add_skip_reason(...)`，Phase 3 调 `scratchpad.build_compose_context(...)`。这些方法**仅存在于** `deep_research/research_scratchpad.py` 的 `ResearchScratchpad`。
- 实际运行轨迹：
  1. 触发 → triage 0ms（纯函数）
  2. Phase 1 Decompose LLM call ~1–2s
  3. LLM 返回 → `scratchpad.set_subtopics(...)` → **`AttributeError: 'Scratchpad' object has no attribute 'set_subtopics'`**
  4. TurnRuntime `_exception_to_api_error` 把它包成 `ErrorEvent(error_code=llm_api_failed, internal_detail="AttributeError: 'Scratchpad' object has no attribute 'set_subtopics'")`，状态切 FAILED

时间线完全对应"约 2 秒后失败"。

### 为什么单测全绿但生产挂

`tests/test_deep_research_loop.py` 直接传 `ResearchScratchpad()` 给 `loop.run(scratchpad=...)`，绕过了 `SessionState`。
生产路径走 `SessionStore.create() → SessionState.scratchpad=Scratchpad() → TurnRuntime → deep_loop.run`。这条 production 链没有任何测试覆盖。

### SA-07 已知并 documented 这个隐患

`deep_research_loop.py` 的注释里写了 `scratchpad: Any` 是为了与 `TeachingLoop` 一致，但没人在装配根上把"deep mode 用不同 scratchpad"接好。

## 候选 #2（次因，独立的 bug，需一并修）

`deep_research/agents/decomposer.py:69-75` —— `Decomposer.process` 直接 `await self.call_llm(...)`，**没有 try/except**。`Investigator` 有 `except Exception: return _fallback_parse_failure()`，`Decomposer` 没有。

如果 DeepSeek 同步抛任意异常（401 / 402 余额不足 / 400 BadRequest / `response_format` 不被支持 / 限流 / 网络），不到 1 秒就会跑出 `LLMClientError`，被 TurnRuntime 抓走 → `ErrorEvent(error_code=llm_api_failed)`。也能解释 ~2 秒症状（实际可能更短）。

## 已排除

- ❌ Pydantic 合同字段不匹配：所有 `DeepResearchProgressEvent / AnswerStreamStartEvent / AnswerStreamDeltaEvent / AnswerStreamEndEvent / ChatMessage / AgentStatus` 构造点字段名、必填项、枚举值（`AgentPhase.STREAMING`、`AgentPetState.RESEARCHING`、`pet_mood="research"`、`role="assistant"`、`mode=ChatMode.DEEP`、`kind=ReportKind.REPO_ONBOARDING`）全都对。
- ❌ Prompt 占位符 KeyError：4 个 yaml `{token}` 集合与 `template.format(...)` kwargs 集合**完全相等**；system 块里的字面 `{}` 不会被 `.format()` 处理。
- ❌ LLMClient 形状：`call_llm` / `stream_llm` 签名与 BaseAgent 期望一致；`response_format={"type":"json_object"}` DeepSeek 支持（且 prompt 已含"JSON"字样满足其严格模式条件）。
- ❌ 配置缺失：`Irene/llm_config.json` 存在，`api/app.py.parents[2]` 路径解析正确。
- ❌ Phase 0 Triage：`_StringOverview` 解析 `_repo_overview()` 文本对 `file_count`/`primary_language` 字段，不会抛 `EmptyRepositoryError`。
- ❌ Cancellation：`raise_if_cancelled()` 不主动取消。
- ❌ EventBus.emit：用的是注入的 sink，序列化由 SSE 层做，不会同步抛。

## 如何 1 步分辨主因 vs 候选 #2

**最快路径**：让用户贴出后端 stderr 的 traceback 末行，或前端 SSE 流里 `error_event.error.internal_detail` 字段的字面字符串。

| internal_detail 包含 | 根因 | 修复方向 |
|---|---|---|
| `'Scratchpad' object has no attribute 'set_subtopics'` | 主因（Scratchpad 错配） | 在装配根/TurnRuntime 注入正确 scratchpad，或在 deep_loop.run 入口做 type-check + 替换 |
| `LLMClientError`、`BadRequestError`、`AuthenticationError`、`InsufficientBalance`、`RateLimitError`、HTTP 4XX/5XX | 候选 #2（Decomposer 未兜底） | 给 Decomposer 加 try/except，参考 Investigator 的模式 |

## 修复方向（仅建议，不在本次任务范围）

### 主因修复（结构性）
两条路二选一：

**A. 在装配根挑 scratchpad（推荐）**：`SessionState` 把 `scratchpad` 拆成 `teaching_scratchpad: Scratchpad` 与 `research_scratchpad: ResearchScratchpad | None`；`TurnRuntime._run_turn` 在 `mode=DEEP` 时传后者并按需 lazy-create。改动面：`session/session_state.py` + `session/session_store.py` + `turn/turn_runtime.py`。

**B. deep_loop 入口适配（最小手术）**：`DeepResearchLoop.run` 起手判断 `if not hasattr(scratchpad, "set_subtopics"): scratchpad = ResearchScratchpad()`，并在 turn 终态再回写到 state。这条不动 session 层但 scratchpad 的归属感稍弱。AGENTS.md §0.4 要求"内存形式"，B 不违规。

### 候选 #2 修复
`Decomposer.process` 把 `await self.call_llm(...)` 包进 `try/except Exception: return _default_subtopics_for(report_shape)`，与 Investigator 风格一致。AGENTS.md §3.2 已要求"JSON 解析失败 → 走兜底"，把 LLM 异常一并兜底是同精神。

## What I would ask the user

1. SSE 流里 `error_event.error.internal_detail` 字段的字面值是什么？
2. 后端 stderr 是否有 Python traceback？最后一行/抛出处是什么？
3. 用的 LLM 提供商和模型 id？余额是否足？

## Spec alignment

- AGENTS.md §0.4（内存形式状态）— 主因不违反约束；只是装配错位
- AGENTS.md §3.2（JSON 解析兜底）— 候选 #2 已部分覆盖（JSON），未覆盖 HTTP 异常
- AGENTS.md §11.3（组合根装配）— 主因是组合根忽略了 scratchpad 类型差异
- AGENTS.md §13（测试策略）— 单测路径未覆盖生产 SessionStore → TurnRuntime → deep_loop 链路

## 参考文件

- 三份侦察报告：`.reports/RECON-A-loop-trace.md`、`.reports/RECON-B-contract-mismatch.md`、`.reports/RECON-C-prompt-and-llm.md`
- 关键证据：`session/session_state.py:43,65`、`turn/turn_runtime.py:354-358`、`deep_research/deep_research_loop.py` Phase 1+2+3 全部 scratchpad 调用、`deep_research/agents/decomposer.py:69-75`
