# deep_research 子 agent 工作报告索引

本目录存放 `deep_research/` 模块每一波子 agent 完工后写下的工作报告，目的是让总工程师快速溯源每一处实现来自哪个子 agent、做了什么决策、覆盖了 AGENTS.md 哪几节。

命名规范：`SA-NN-<short-name>.md`，N 从 00 起算。

每份报告必须含且仅含 5 节：What / Files / Decisions / Verification / Spec Alignment。详见 `../../.claude/plans/agent-md-deepresearch-agent-md-agent-mutable-ladybug.md`。

## 索引

- SA-00 contracts 合同与规范同步（本次实现）
- SA-01 pure & scratchpad — triage + investigation_policy + research_scratchpad 三个纯数据层落盘，21 个单测全绿
- SA-02 base agent & prompts — BaseResearchAgent + 4 zh YAML + 本地 PromptManager 全部就位，6 个 prompt 测试全绿
- SA-03 decomposer — Phase 1 Decomposer 落盘，5 个单测覆盖 happy / 不可达 anchor / short cap / JSON 兜底 / polyglot 双向触发
- SA-04 investigator — Investigator + InvestigationDecision 落盘，5 个单测覆盖 happy path / 白名单降级 / 解析失败 done / done 强制清空 / notes_history 渲染
- SA-05 note taker — Phase 2 NoteTaker 落盘（call_llm 温度 0.4，不传 response_format），5 个单测覆盖 read_file_range 行号锚点 / list_dir 仅 path / JSON 剥离 / 600 字符硬截 / 空文本 success+failure 双路兜底
- SA-06 composer — Phase 3 Composer + ComposeOutput 落盘，marker-aware 流式拆分器与 1-3 条 suggestion 解析器，5 个单测覆盖 marker 末段拆分 / 跨 chunk 拆分 / 无 marker / 截断到 3 / 空流占位
- SA-07 deep research loop — `DeepResearchLoop` 编排 4 阶段全部落地，串接 SA-01..SA-06 的纯数据层与 4 个 agent；5 个集成测试覆盖事件序列 / ChatMessage 形状 / cancellation 传播 / short 分支 / TurnLoop 签名一致性
- SA-08 wiring & auto trigger — `api/app.py` 用真实 `DeepResearchLoop`（自带本地 PromptManager + 4 agent）替换 `_DeepResearchPlaceholder`；`api/routes/repositories.py:_run_parse_pipeline` 在 `_publish_repo_connected` 之后追加 `_kickoff_repo_onboarding(...)` 自动触发 DEEP/REPO_ONBOARDING 系统 turn，启动失败一律吞错；3 个 auto-trigger 单测 + 1 个 wiring smoke 测试，全套 69 个 new_kernel 测试无回归
- SA-09 docs sync — `new_kernel/AGENTS.md` 在 `### Deep Research` 末尾追加 1 个指针 bullet；`web_v4_interface_protocol.md` §5 加 `report_kind` 请求字段 + `kind` 响应字段，§4 末新增 §4.4 自动 onboarding 触发协议（SSE 事件序列 / 不挂 `auto_turn_id` / 重复触发语义）；`INTERFACES.md` §3.10 用与 `deep_research_loop.py` 1:1 的 `__init__` + `run` 签名替换旧占位
- SA-10 integration verify — 全套 60 个 deep_research / contracts / app_config 测试 + 69 个 new_kernel 全量测试一次绿；§11.1 import 纪律 0 违例（仅 stdlib + `agents.base_agent` + `contracts` + `tools.tool_protocol` + 模块内相对引用）；§16 自动化覆盖 4/6（mode=chat 不受影响 ✅、cancellation ≤5s ✅、老师腔反模式禁止 ✅、自动触发 SSE 序列 ✅），余 5 支柱覆盖 / 架构节较长 / 二次连仓共 3 项需人工验证
  - FIX-01 structural scratchpad split — 修复 RECON-FINAL 主因：`SessionState.scratchpad` 拆为 `teaching_scratchpad: Scratchpad` + `research_scratchpad: ResearchScratchpad | None`；`TurnRuntime._run_turn` 通过 `_select_scratchpad(state, mode)` 按 mode 选取并 lazy-create research scratchpad；`state.scratchpad` 保留为 property alias 兼容旧测；`module_interaction_spec.md §8` 状态表与 §13 `turn/*` import 白名单同步更新；新增 `tests/test_deep_research_session_integration.py` 3 项 E2E 集成测填补 SA-07 缺口
  - FIX-02 decomposer LLM-exception fallback — 按 RECON-FINAL 候选 #2 把 `agents/decomposer.py:69-75` 的裸 `await self.call_llm(...)` 包进 `try/except Exception: return _fallback_subtopics(report_shape)`，与 SA-04 Investigator 同款 silent-fallback 语义把 §3.2"JSON 解析失败兜底"扩到 LLM HTTP 异常（401/402/限流/4XX）；新增 1 个测试 `test_decomposer_falls_back_to_default_pillars_on_llm_exception`（5 → 6），锁 5 默认 ids/titles 顺序 + `calls == 1` 不重试；不动 session/turn/api 任一文件，diff ≈ +5 行 prod / +35 行 test
  - FIX-03 arch 节稳定列目录（Option B 主推 + Option A 兜底）— 落地 RECON-D 主推方案：(B) 在 `_run_investigate_phase` 的每个 sub-topic 起点、`subtopic.id == "arch"` 时确定性预投喂 `list_dir({"path":"."})`，把 raw 落到 `scratchpad.first_round_raw("arch")` + 写一段教师腔 prefab 笔记（首句"我们先扫了一眼仓库的顶层布局"），后续 ReAct 从 round 2 起跑；(A) 顺手修复 `_make_overview_proxy` 漏解析 `- top_level_paths:` / `- entry_candidates:` 的小问题（RECON-B Severity-3），并把 Decomposer 的 `arch` 默认 anchors 改由 `_arch_default_anchors(reachable)` 从 `top_level_paths` 头 6 个目录派生。零 prompt yaml 改动、零 system_prompt / user_template 改动；prod diff ≈ +85 行（loop 57 / decomposer 28）；新增 4 个 loop 测试 + 改 2 个 decomposer 测试 + 改 2 个 loop 集成测试断言；arch sub-topic 总成本反降（prefab 替代 1 次 NoteTaker LLM 调用）
