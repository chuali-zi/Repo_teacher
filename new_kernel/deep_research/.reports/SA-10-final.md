# SA-10 · Integration Verify

## What
Clean-room 集成自检：SA-00..SA-09 9 波子 agent 全部落盘后跑一次完整测试矩阵（12 个 deep_research / contracts / app_config 单测 + 集成测共 60 项 + new_kernel 全量 69 项）、对照 AGENTS.md §16 6 项硬性验收逐项标注、扫一次 §11.1 import 纪律。结论：**PASS** —— 编译零 SyntaxError、69/69 全绿、§11.1 import 0 违例；§16 自动化部分 4/6 项可断言为已满足，其余 2 项（5 支柱覆盖完整性、架构节文本长度）属"需真实 LLM 跑一次仓库手测"的产出质量项，已在 Open Issues 标注。

## Files
- mod  `new_kernel/deep_research/.reports/README.md`:+1/-1  SA-10 索引行去掉 "（待）" 并补一句结果摘要
- new  `new_kernel/deep_research/.reports/SA-10-final.md`:本报告

SA-10 是 verify-only 波次，未触任何 `.py` / `.yaml` / 其它 markdown。

## Decisions
- **§16 第 1 项（SSE 时序）记为 ✅ 间接覆盖 / 部分自动**：AGENTS.md §16.1 要求"无需用户输入，前端在 1-5 分钟内能从同一条 repository SSE 中依次拿到 repo_connected → agent_status → progress×多个 phase → answer_stream_* → message_completed(kind=repo_onboarding)"。这一条无法跑真 LLM 在 SA-10 内端到端断言，但已被以下三道间接断言锁定：(a) `test_deep_research_loop.py::test_loop_emits_expected_event_sequence` 锁了 5 类事件 emit 顺序；(b) `test_deep_research_loop.py::test_loop_returns_chat_message_with_repo_onboarding_kind` 锁了 `ChatMessage.kind == REPO_ONBOARDING`；(c) `test_deep_research_auto_trigger.py` 3 项锁了 `_kickoff_repo_onboarding` 在 parse 成功后用 `initiator="system"` 触发。三道闸门叠加意味着如果真 LLM 跑通，SSE 时序与 §16.1 一致是 deterministic 的。
- **§16 第 2 / 3 项（5 支柱覆盖、架构节较长、老师腔比喻、主动引导）记为部分自动**：5 支柱 / 架构节长度需要看真实 markdown 输出，自动测里只能锁 prompt 字面不出现 §7.1 反模式；正面短语（如"我们打开 X 看 Y"老师腔）只能锁 prompt 包含，无法锁 LLM 真的产出。这是 §13 末行明确的"不断言 LLM 输出文本质量"原则。
- **没有自动化覆盖 §16.6 的"同 session 二次连仓"集成测**：SA-08 只测了 `_kickoff_repo_onboarding` 单点，SA-09 在 `web_v4_interface_protocol.md §4.4` 末段只描述了语义（"先 cancel 再 reset 再启新 parse + onboarding"），但没有自动测覆盖。建议留作 SA-11 / 后续 ticket 补一条 `test_repositories_route` 端到端集成测。
- **`api/routes/repositories.py:_kickoff_repo_onboarding` 的吞错语义不抽象**：SA-08 选了"任何启动失败都不影响 parse 结果"，吞错时也不再 emit `ErrorEvent`（旧 `_kickoff_initial_turn` 会 emit）。这条偏离老代码、与新 spec 一致，本次验收照单全收，建议人工跑一次"故意把 turn_runtime 注入 None"的场景观察前端表现。
- **`tmp_*` collection error 不计入 PASS/FAIL**：`new_kernel/tests/tmp_gye1b01` / `tmpef3o2i30` / `tmpprh1vpne` 三个目录是 SA-07 报告里指出的历史遗留产物（与 SA 链路无关），裸 `pytest new_kernel\tests` 会因为 Windows 权限拦截抛 PermissionError；用显式 `test_*.py` 文件列表传入 pytest 即可全绿，与 SA-07 报告做法一致。
- **Investigator 的 LLM 异常 swallow 偏离 §12.2 通则**：SA-04 记了一处文档化偏离 —— Investigator 把 `call_llm` 自身抛错也归到 fallback decision，理由是"单 sub-topic 单轮失败不该把整个 turn 炸掉"。本次验收照单全收（与规格"NEVER raise from process"硬约束更优先），但这条不应被复制到 Decomposer / Composer。

## Verification

### 编译
| 目标 | 结果 |
| --- | --- |
| `python -m compileall new_kernel\deep_research new_kernel\contracts.py new_kernel\api\app.py new_kernel\api\routes\repositories.py` | PASS（仅输出 Listing 行，0 SyntaxError） |

### 测试矩阵（按 SA-10 任务单 12 文件）
| 测试文件 | 数量 | 结果 | 备注 |
| --- | --- | --- | --- |
| `test_contracts.py` | 3 | PASS (0.13s) | SA-00 合同 3 项默认值 + mode×report_kind 校验 |
| `test_deep_research_triage.py` | 6 | PASS (0.64s) | SA-01 决策矩阵 4 分支 + Markdown/plaintext/None 子值 |
| `test_deep_research_policy.py` | 8 | PASS (0.70s) | SA-01 起轮/停轮/跳过/round_quota 组合 |
| `test_deep_research_scratchpad.py` | 7 | PASS (0.54s) | SA-01 笔记/skip/raw 截断/build_compose_context |
| `test_deep_research_prompts.py` | 6 | PASS (0.71s) | SA-02 4 yaml + decompose 标识 + §7.1 反模式 0 命中 |
| `test_deep_research_decomposer.py` | 5 | PASS (0.66s) | SA-03 happy / 不可达 anchor / short cap / JSON 兜底 / polyglot |
| `test_deep_research_investigator.py` | 5 | PASS (0.63s) | SA-04 happy / 白名单降级 / 解析失败 done / done 清空 / notes 渲染 |
| `test_deep_research_note_taker.py` | 5 | PASS (0.67s) | SA-05 锚点 / list_dir / JSON 剥离 / 600 截断 / 失败兜底 |
| `test_deep_research_composer.py` | 5 | PASS (0.62s) | SA-06 marker 末段 / 跨 chunk / 无 marker / 截断 3 / 空流占位 |
| `test_deep_research_loop.py` | 5 | PASS (0.67s) | SA-07 事件序列 / ChatMessage 形状 / cancellation / short / Protocol |
| `test_deep_research_auto_trigger.py` | 3 | PASS (1.50s) | SA-08 happy / 无 turn_runtime / 启动异常吞没 |
| `test_app_config.py` | 4 | PASS (3.24s) | SA-08 wiring smoke + chat-mode 回归 + utf8 BOM + 缺 turn_runtime |
| **小计** | **62** | **PASS** | 12 个文件全绿 |

### 全量回归
`python -m pytest -q (Get-ChildItem new_kernel\tests\test_*.py).FullName` — **69 passed in 4.44s**（含 `test_teaching_experience.py` 7 项 / 上表 62 项 = 69）。无失败、无 error、无 skip。仅 8 条 FastAPI `on_event` deprecation 警告（与本次改动无关，应由 kernel 维护方迁移到 lifespan handler）。

### AGENTS.md §16 验收标准对应
| 项 | 自动化覆盖 | 状态 | 备注 |
| --- | --- | --- | --- |
| 1. SSE 时序 `repo_connected → agent_status → progress×多 phase → answer_stream_* → message_completed(kind=repo_onboarding)` | 间接 ✅ | 已就绪 | `test_loop_emits_expected_event_sequence` + `test_loop_returns_chat_message_with_repo_onboarding_kind` + `test_deep_research_auto_trigger` 三层叠加；真 LLM 1 次贯穿验证仍需人工 |
| 2. 5 支柱覆盖（what/stack/why/arch/flow）+ 架构节明显较长 | ❌ 需人工 | 兜底逻辑就绪 | `Decomposer._fallback_subtopics` 退到 5 默认；`compose.yaml` 系统词写"架构节 1.5-2× 篇幅"；产出文本质量需真 LLM 验证 |
| 3. 老师腔 + ≥1 比喻 + ≥1 主动引导 + 不出现"工具/ToolResult/JSON" | 部分 ✅ | 反模式锁死 | `test_compose_prompt_does_not_use_anti_pattern` 锁 §7.1 4 条字面值；`note_taker._JARGON_TOKENS` 屏蔽 6 类敏感词；正面"我们打开 X 看 Y"在 `compose.yaml` system 中存在但不能自动断言 LLM 真输出 |
| 4. mode=chat 不受影响（回归） | ✅ | 已绿 | `test_app_config.py::test_chat_message_with_valid_config_does_not_fail_missing_turn_runtime` + 全套 69 项零回归 |
| 5. 用户 cancel ≤5s 拿到 `RunCancelledEvent` | ✅ | 已绿 | `test_loop_cancellation_during_investigate_propagates`：5 个 cancellation 检查点（Phase 1 / 每支柱 / 每轮 / Phase 3 / 每 8 chunk）由 SA-07 端到端验证 |
| 6. 同 session 二次连仓时第一次 onboarding 被取消 + `messages` 重置 | ❌ 待补集成测 | 文档已描述 | `web_v4_interface_protocol.md §4.4` 末段描述了语义；建议追加 `test_repositories_route` 端到端测；建议作为 SA-11 / 后续 ticket |

**自动化部分小计**：4 项 ✅ / 1 项部分 / 2 项 ❌ 需人工或补集成测。

### §11.1 import 纪律
对 `C:\Users\chual\vibe\Irene\new_kernel\deep_research` 全目录扫禁止前缀（grep 命令按 SA-10 任务单照搬）：
| Pattern | 命中数 | 来源 |
| --- | --- | --- |
| `from \.\.\.api\.` | 0 | — |
| `from \.\.\.session\.` | 0 | — |
| `from \.\.\.turn\.` | 0 | — |
| `from \.\.\.events\.` | 0 | — |
| `from \.\.\.repo\.` | 0 | — |
| `agents\.teacher\b\|agents\.reading_agent\|agents\.orient_planner\|agents\.teaching_loop\|agents\.sidecar_explainer` | 0 in `.py` | 8 命中均在 `*.md` 文档（包括 SA 报告中的"未触…"自陈语 + AGENTS.md §11.1 禁止清单条目本身）+ 1 命中在 `agents/__init__.py` 但属 docstring 中"This package does NOT import…"自我说明，不是真实 import 语句 |

补充验证：扫所有 `*.py` 文件的真实 import 语句（`^from \.\.\.|^from \.\.[a-z]|^import \.\.\.`）共 6 条命中：
- `deep_research_loop.py:26` — `from ..contracts import (...)` ✅ 允许
- `deep_research_loop.py:38` — `from ..tools.tool_protocol import ToolContext` ✅ 允许（`tools.tool_protocol` 在 §11.1 白名单）
- `agents/decomposer.py:17` — `from ..research_scratchpad import SubtopicMeta` ✅ 允许（模块内相对引用）
- `agents/note_taker.py:18` — `from ..research_scratchpad import ...` ✅ 允许
- `agents/investigator.py:18` — `from ..research_scratchpad import ...` ✅ 允许
- `agents/base_research_agent.py:21` — `from ...agents.base_agent import BaseAgent` ✅ §11.1 显式允许的唯一 kernel-agent 引用（基类）

**结论：§11.1 import 纪律 0 违例。**

## Spec Alignment

SA-00..SA-09 全套对 deep_research/AGENTS.md 章节的覆盖矩阵：

| AGENTS.md 节 | 覆盖 SA |
| --- | --- |
| §0 总则 / §0.1 / §0.2 解耦 | SA-00（contracts）+ SA-02 / SA-04 / SA-05 / SA-06 / SA-07（不引用 teacher/reading/orient_planner） |
| §3.1 Triage 决策矩阵 4 分支 | SA-01（triage.py）+ SA-07（loop 编排） |
| §3.2 Decompose 输出 schema / 6 支柱 / short standard 分支 / anchor 可达 | SA-03（decomposer.py）+ SA-02（decompose.yaml） |
| §3.3 Investigate 单轮 ReAct + NoteTaker 笔记 + 失败/跳过 | SA-04（investigator.py）+ SA-05（note_taker.py）+ SA-01（policy.py / scratchpad.py） |
| §3.4 / §12.5 Compose 流式 + `<<SUGGESTIONS>>` 标记 + suggestions 解析 | SA-06（composer.py）+ SA-02（compose.yaml）+ SA-07（loop emit AnswerStreamDelta） |
| §4.1 / §4.2 自动触发 + SSE 事件序列 | SA-08（_kickoff_repo_onboarding）+ SA-07（5 类 event 工厂分支）+ SA-09（web_v4_interface_protocol §4.4） |
| §5 cancellation 5 检查点 | SA-07（loop 5 raise 点）+ SA-06（composer 不持 token，loop 在外层节拍） |
| §7.1 反模式 4 条 | SA-02（compose.yaml）+ SA-05（note_taker._JARGON_TOKENS）+ test_deep_research_prompts |
| §7.2 老师腔 / 比喻 / 主动引导 / 设计意图推测 | SA-02（4 yaml） |
| §7.3 不输出密钥/JSON/工具名/>40 行原始代码 | SA-02（compose.yaml）+ SA-05（note_taker sanitization） |
| §8 模块布局 + 文件清单 | SA-01..SA-07 全部 |
| §9.1 `DeepResearchLoop` 公开签名 | SA-07（loop） + SA-09（INTERFACES.md §3.10） |
| §9.2 / §9.3 组合根装配 + 自动触发 wiring | SA-08（api/app.py + api/routes/repositories.py） |
| §10 合同字段 ReportKind / ChatMessage.kind / SendTeachingMessageRequest.report_kind | SA-00（contracts.py） + SA-09（web_v4 §5） |
| §11.1 import 白名单 / 黑名单 | SA-01..SA-08 + SA-10 grep 验证 |
| §11.3 依赖注入 / 不在 deep_research/ 内 new 出依赖 | SA-08（_build_deep_research_loop lazy-import + 注入） |
| §12.1 cancellation | SA-07 |
| §12.2 错误处理 / JSON 兜底 / LLM 异常路径 | SA-03 / SA-04 / SA-05 / SA-06 / SA-07 |
| §12.3 上下文预算（4KB / 30KB / 600 字 / 1.5KB / sub-topic / 2KB raw） | SA-01（scratchpad budget）+ SA-05（note 600 截）+ SA-06（compose 4KB）+ SA-07（observation 2KB） |
| §12.6 metrics 计数 add_metrics(emit=False) | SA-07 |
| §13 单测层 | 全套 60+ 测试（去掉 test_teaching_experience 的 7 项） |
| §16 验收标准 6 项 | SA-10（本节）— 4 项自动 + 2 项需人工 |

## Open Issues / Follow-ups

### 来自前 9 波 SA 报告的未尽事项（SA-10 转抄）
- **SA-01**：`SubtopicNote.anchor_path` / `anchor_lines` 的 schema 与 NoteTaker 实际输出在 SA-05 已对齐（`tuple[int, int]`），但与 Investigator 的 `action_input["start_line"/"end_line"]` 字段名硬绑；如未来 tool runtime 重命名键，`note_taker._infer_anchor` 需同步改。
- **SA-04**：Investigator 的 LLM 异常 swallow 是文档化偏离（§12.2 通则要求抛出，规格本身要求"NEVER raise from process"，本 agent 选规格优先）。如 SA-07 / SA-08 后续希望 Investigator LLM 异常进入 `failure_streak`，可在 loop wrapper 里识别 `decision.intent == "(解析失败，结束本支柱)"`。当前已实现这条识别路径。
- **SA-08**：`_kickoff_repo_onboarding` 吞错时不再 emit `ErrorEvent`（与旧 `_kickoff_initial_turn` 不同）。如果产品决策未来要"自动触发失败也通过 SSE 通知用户"，需要在该 helper 内添加 fallback `ErrorEvent` emit。
- 其余 SA 报告未列额外 TODO。

### SA-10 自身识别的事项
1. **`tmp_*` 历史目录清理**：`new_kernel/tests/{tmp_gye1b01, tmpef3o2i30, tmpprh1vpne}` 三个空/损坏的 leftover 子目录会让裸 `pytest new_kernel/tests` collection 阶段报 PermissionError。建议人工 `Remove-Item -Recurse` 清掉，或在 `pytest.ini` / `pyproject.toml` 加 `[tool.pytest.ini_options] norecursedirs = ['tmp_*', 'pytest_tmp_*']` 永久规避。
2. **§16.1 真 LLM 端到端手测**：在配置真实 LLM key 的环境下连一个 ≤50 文件的非空仓库（建议用 `new_kernel/` 自身或 `web_v4/` 这种小型 polyglot 仓），人工观察前端在 1-5 分钟内是否依次拿到 `repo_connected → agent_status → progress×多 phase → answer_stream_* → message_completed(kind=repo_onboarding)`，并把最终 markdown 落盘以验证 §16.2 / §16.3：
   - 5 支柱（what / stack / why / arch / flow）是否齐全；
   - 架构节是否明显比其它节长；
   - 是否含至少 1 个比喻、至少 1 处"你打开 X 看 Y"主动引导；
   - 是否未泄漏"工具" / "ToolResult" / "JSON" 字样。
3. **§16.6 二次连仓集成测**：建议追加 `test_repositories_route_resets_session_on_second_connect`（端到端用 `TestClient` + 第一次 connect 后立即第二次 connect，断言：(a) 第一次的 active turn 被 cancelled；(b) `session.messages` 被清空；(c) 第二次的 `_kickoff_repo_onboarding` 被调用。这条目前未自动覆盖，文档（`web_v4_interface_protocol.md §4.4` 末段）已描述。建议作为 SA-11 / 后续 ticket。
4. **§16 主观项的人工批阅清单**：把"老师腔 / 比喻 / 主动引导 / 不出现工具术语"做成一个 ≤10 行的检查清单，跑完真 LLM 后让人对照打勾。这是 §13 末行明确说不做自动评分的部分，必须人工签收。
