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
- SA-10 integration verify — 全套 60 个 deep_research / contracts / app_config 测试 + 69 个 new_kernel 全量测试一次绿；§11.1 import 纪律 0 违例；§16 自动化覆盖 4/6
  - FIX-01 structural scratchpad split — `SessionState.scratchpad` 拆为 `teaching_scratchpad` + `research_scratchpad: ResearchScratchpad | None`；`TurnRuntime._run_turn` 通过 `_select_scratchpad(state, mode)` 按 mode 选取并 lazy-create research scratchpad；`state.scratchpad` 保留为 property alias
  - FIX-02 decomposer LLM-exception fallback — 把 `agents/decomposer.py:69-75` 的裸 `await self.call_llm(...)` 包进 `try/except Exception: return _fallback_subtopics(report_shape)`；新增 1 个 LLM-exception 测试（5 → 6）
  - FIX-03 arch 节稳定列目录（Option B 主推 + Option A 兜底）— (B) `subtopic.id == "arch"` 时确定性预投喂 `list_dir({"path":"."})` 写入 round-1 raw + prefab 教师笔记；(A) 修 `_make_overview_proxy` 解析 top_level_paths/entry_candidates + Decomposer 默认 arch anchors 由 `_arch_default_anchors(reachable)` 派生；零 yaml 改动；prod ≈ +85 行；4 新 loop 测试
  - RECON-E arch 不读源码倾向 侦察 — 工具层完全支持读源码（`read_file_range / search_repo / find_references` 都返回原代码 + 行号）；问题全在 anchor 选择层：FIX-03 后 arch anchors 仍是纯目录 + prefab 末尾全 `[dir]` 行 + `investigate.yaml` 软规则倾向 list_dir，三者叠加把 arch round 2 锁进了 `list_dir(子目录/)`，0 行源码引用。给出 D1/D3/D4 三候选，主推 D1+D3
  - RECON-F onboarding 与后续 chat 割裂 侦察 — (M1) `state.messages` 从未被串进 OrientPlanner / TeacherAgent prompt（`turn_runtime.py:355-365` 仅传 `user_message`）；(M2) `research_scratchpad` ↔ `teaching_scratchpad` 无桥接，AGENTS.md §5 line 325/330 covered_points 合同未兑现。主推方案 (b) scratchpad 桥接 helper
  - FIX-04 D1 arch 默认 anchors 混入文件路径 — `_arch_default_anchors(reachable)` 重写为 ≤3 dirs + ≤3 files 共 ≤6 项（dirs 在前）；签名不变；3 个新单测 + 改 2 个旧 anchor 期望；prod ≈ +14 行；零 yaml 改动
  - FIX-05 D3 arch prefab 笔记加"挑一个文件读"引导 — FIX-03 prefab 末尾追加教师腔引导句指向具体 `<path>`，由新 helper `_pick_arch_drill_target(overview)` 按"非 markdown/text entry → 任意 entry → 非目录 top_level → None"选；保持 600 字硬截上限；2 个新 loop 测试覆盖"有目标"+"无目标 graceful 跳过"；零 yaml 改动
  - FIX-06 Plan B research → teaching scratchpad 桥接 — `turn/turn_runtime.py` 加私有 helper `_bridge_research_to_teaching(state)`，在 `_run_turn` 成功路径 `mode == ChatMode.DEEP` 后调用：把 research_scratchpad 各 sub-topic 笔记摘要 + 标题写进 `teaching_scratchpad.covered_points` + 合成一条 `ReadEntry`；bridge 失败 swallow 不污染 ErrorEvent；幂等；2 个 E2E 集成测试；兑现 AGENTS.md §5 + §11.2；零 yaml 改动
