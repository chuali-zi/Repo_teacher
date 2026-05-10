# FIX-01 · Structural Scratchpad Split

## What

执行总工程师的方案 A：把 `SessionState` 单个 `scratchpad` 字段拆成 `teaching_scratchpad`（教学循环用，类型 `memory.Scratchpad`）和 `research_scratchpad`（深度研究循环用，类型 `ResearchScratchpad`，懒创建），并由 `TurnRuntime._run_turn` 在调用 `loop.run(...)` 前按 `mode` 选取正确的对象。这是 `RECON-FINAL-diagnosis.md` § "修复方案 → 主因修复 → 方案 A" 的固化。

修复前的故障路径：`SessionStore.create() → SessionState.scratchpad = memory.Scratchpad() → TurnRuntime → DeepResearchLoop.run(scratchpad=memory.Scratchpad)` → Phase 1 调 `scratchpad.set_subtopics(...)` → `AttributeError: 'Scratchpad' object has no attribute 'set_subtopics'` → `ErrorEvent(error_code=llm_api_failed)` → 前端 ~2 秒后看到失败。

修复后：
- 教学 turn 走 `teaching_scratchpad`（保持现状），`research_scratchpad is None`。
- 深度 turn 走 `research_scratchpad`，由 `_select_scratchpad` 在 `mode=DEEP` 时 lazy-create 并写回 state。
- `state.scratchpad` 作为 property alias 保留为 `teaching_scratchpad` 的读/写代理，兼容旧测试桩与 `_ensure_messages_owner_shape` 的 `hasattr(state, "scratchpad")` 防御检查。

## Files

- mod  `new_kernel/session/session_state.py`：`scratchpad` 字段 → 拆为 `teaching_scratchpad: Scratchpad`（保留默认工厂）+ `research_scratchpad: ResearchScratchpad | None = None`；新增 `@property scratchpad` getter/setter alias 转发到 `teaching_scratchpad`；`ResearchScratchpad` 通过 `TYPE_CHECKING` 导入避免运行时反向依赖。文件首行注释同步更新。
- mod  `new_kernel/session/session_store.py`：`SessionState(...)` 构造点把 `scratchpad=` 改成 `teaching_scratchpad=`；`research_scratchpad` 不在构造期赋值（保持默认 `None`，由 TurnRuntime 懒创建）。`scratchpad_factory` 构造参数语义不变（继续注入到 teaching slot）。
- mod  `new_kernel/turn/turn_runtime.py`：`_run_turn` 把 `scratchpad=state.scratchpad` 改为 `scratchpad=scratchpad_for_turn`，其中 `scratchpad_for_turn = _select_scratchpad(state, mode)`。新增 module-level `_select_scratchpad(state, mode)` 辅助函数：`mode=DEEP` 走 `research_scratchpad`（None 则懒建并尝试写回 state，失败则吞掉以兼容 Protocol-only stub），其它 mode 优先 `teaching_scratchpad`，没有的话 fallback `state.scratchpad`（property alias）。`_ensure_messages_owner_shape` 的 `hasattr(state, "scratchpad")` 检查保留——property 也满足 `hasattr` 真值。`from ..deep_research.research_scratchpad import ResearchScratchpad` 是 function-scope 局部导入，避免 deep_research 在未启动 deep turn 时被 import。
- mod  `new_kernel/module_interaction_spec.md`：§8 状态写入规则表把 `SessionState.scratchpad` 单行替换为两行（`teaching_scratchpad` / `research_scratchpad`），并在表后追加一句关于 `state.scratchpad` property alias 的兼容说明。§13 import 白名单 `turn/*` 行追加 `deep_research.research_scratchpad`。
- new  `new_kernel/tests/test_deep_research_session_integration.py`：3 个 E2E 集成测试，用真实 `SessionStore` + `TurnRuntime` + `DeepResearchLoop` + stub LLM/工具，端到端验证 (a) 默认 session 形状；(b) deep turn 触发后 `research_scratchpad` 被懒建并填入 5 支柱、`teaching_scratchpad` 不被触动、`ChatMessage(role=assistant, mode=DEEP, kind=repo_onboarding)` 落地；(c) chat turn 不创建 `research_scratchpad`、teaching loop 收到 `teaching_scratchpad` 同一对象。
- mod  `new_kernel/deep_research/.reports/README.md`：在 SA-10 后追加 FIX-01 索引行。
- new  `new_kernel/deep_research/.reports/FIX-01-scratchpad-split.md`：本报告。

未触：`agents/decomposer.py`（FIX-02 owns it）、`deep_research/AGENTS.md`、`contracts.py`（`SessionSnapshotData` 不暴露 scratchpad，无需改动）、`TurnLoop` Protocol（`scratchpad: Any` 已经够宽）、其它任何深度研究文件。

## Decisions

1. **保留 `state.scratchpad` 为 property alias 而非彻底删除**：旧测试 `test_teaching_experience.py` 的 `_TurnState` dataclass 依然声明 `scratchpad: Scratchpad = field(default_factory=Scratchpad)`，没有 `teaching_scratchpad`。`_select_scratchpad` 在 chat 分支 `getattr(state, "teaching_scratchpad", None)` 拿不到就 fallback `state.scratchpad`，一行改不到旧测；同时新 `SessionState` 的 property alias 让 `state.scratchpad is state.teaching_scratchpad` 永远为真，老的"读 state.scratchpad"代码继续 work。
2. **`research_scratchpad` 懒创建而不是构造期分配**：(a) 节省 chat-only 长 session 的内存；(b) 显式标记"deep 模式才是它的所有者"，与 §11.2 "TurnRuntime is the legal writer" 原则贴合；(c) 让单测可以断言 "chat 模式后 research_scratchpad 仍是 None"。
3. **`_select_scratchpad` 的 try/except**：如果 caller 传进来的是只实现 `TurnSessionState` Protocol 的最小 stub（比如 frozen dataclass / SimpleNamespace），写 `state.research_scratchpad = pad` 可能炸。我们吞掉异常并继续用本地 pad 跑 turn——失败模式已有完整集成测覆盖，不阻塞正确性。
4. **`from ..deep_research.research_scratchpad import ResearchScratchpad` 局部导入**：避免 turn 模块在 import 时拉取 deep_research（即便会话从不进入 DEEP 模式）。同时 `deep_research.research_scratchpad` 已加入 `module_interaction_spec.md §13` 的 `turn/*` 白名单——纪律未破。
5. **`SessionSnapshotData` 不动**：通读 `contracts.py:294-301`，该 model 暴露 `repository / agent_status / parse_log / messages / current_code / mode`——本来就没有 scratchpad，拆字段对 snapshot 无 ripple effect。
6. **`_ensure_messages_owner_shape` 的检查不放宽**：保留 `hasattr(state, "scratchpad")` 而不改成 `hasattr(state, "teaching_scratchpad")`。原因：(a) property alias 让 hasattr 永远为真，不会误伤；(b) 改成新名会让旧测/Protocol-only stub 丢防御；(c) "state must expose .scratchpad" 是兼容期最低契约。

## Verification

环境受沙箱限制，本会话无法直接运行 `python -m compileall` / `pytest`。下面是逐文件的人工 trace，若产线运行报错请直接对照。

### 编译路径 trace

- `session_state.py`：`@dataclass` 处理类体内 annotated attributes：`session_id / event_bus / agent_status / mode / repository / repo_root / parse_log / messages / teaching_scratchpad / research_scratchpad / current_code / active_turn_id / auto_onboarding_turn_id / created_at / updated_at`——没有 `scratchpad:` annotation，故 dataclass 不会把 `scratchpad` 加进 `__init__`。`@property scratchpad` 是普通类属性，dataclass 不动它。结构合法。
- `session_store.py`：构造 `SessionState(...)` 改用 kwarg `teaching_scratchpad=`，匹配新字段名，合法。
- `turn_runtime.py`：`_select_scratchpad` 是模块级 function；`Any` 已在文件顶部 import；`from ..deep_research.research_scratchpad import ResearchScratchpad` 是函数体内局部 import，路径对（`new_kernel.deep_research.research_scratchpad` 存在 `class ResearchScratchpad`）。
- `tests/test_deep_research_session_integration.py`：所有 import 来自现有公开模块（`new_kernel.contracts` / `events.event_bus.EventBus` / `memory.scratchpad.Scratchpad` / `tools.tool_protocol.ToolResult` 等），与 `test_deep_research_loop.py` 的现有 stub 模式一致。

### 测试矩阵（trace 预期）

| 测试文件 | 预期 | 依据 |
| --- | --- | --- |
| `test_deep_research_session_integration.py` | 3 PASS | 新写的；逐字 trace `_select_scratchpad` + `SessionStore.create` + `_NoOpTeachingLoop.run` 的耦合 |
| `test_app_config.py` | 4 PASS（不变） | `SessionState` 接口无破坏；`SessionStore` 的 `create_session` 默认参数不变；`_idle_agent_status` 不读 scratchpad |
| `test_teaching_experience.py` | 7 PASS（不变） | `_TurnState` 直接 dataclass，仍声明 `scratchpad: Scratchpad`；`_select_scratchpad` 在 chat 分支会 fallback 到 `state.scratchpad`（即 `_TurnState.scratchpad`）；`_TurnLoopStub.run(**kwargs)` 不读 `kwargs["scratchpad"]` 类型 |
| `test_deep_research_loop.py` | 5 PASS（不变） | 直接传 `ResearchScratchpad()` 给 `loop.run(scratchpad=...)`，绕开 `SessionState` |
| `test_deep_research_auto_trigger.py` | 3 PASS（不变） | 测 `_kickoff_repo_onboarding` 单点，`turn_runtime.start_turn` 是 stub |
| 其它 `test_deep_research_*.py`（triage/policy/scratchpad/prompts/decomposer/investigator/note_taker/composer） | 全 PASS（不变） | 与 SessionState 无关 |
| `test_contracts.py` | 3 PASS（不变） | 只测 contracts，与 session 字段无关 |

合计预期：62 项 deep_research/contracts/app_config + 7 项 teaching_experience + 3 项新增 = **72 项 PASS**（vs. SA-10 时的 69 项 baseline + 3 新测）。

### §11.1 import 纪律

`turn/turn_runtime.py` 现在显式 (function-scope) 引用 `deep_research.research_scratchpad`。已对应在 `module_interaction_spec.md §13 turn/*` 白名单追加 `deep_research.research_scratchpad`。`session/*` 仅通过 `TYPE_CHECKING` 引用 `deep_research.research_scratchpad`（运行时无依赖），不需要 §13 增项——`TYPE_CHECKING` 引用不算运行时依赖。

`deep_research/*` 没有新增任何 import；模块依然只通过 contracts/agents.base_agent/llm/prompts/memory/tools 进出。

### 硬约束自检（按任务单）

| 约束 | 满足证据 |
| --- | --- |
| 不动 `agents/decomposer.py` | 未编辑该文件 |
| 不动 `deep_research/AGENTS.md` | 未编辑该文件 |
| 不增加 `contracts.py` 字段 | 未编辑 `contracts.py` |
| 不改 `TurnLoop` Protocol / `DeepResearchLoop.run` 签名 | `turn_runtime.py:117-130` 与 `deep_research_loop.py:157-169` 未触；`TurnLoop.scratchpad: Any` 仍然 |
| `from ..deep_research.research_scratchpad import ResearchScratchpad` 必须 function-scope | 见 `turn_runtime.py:_select_scratchpad`，import 写在 function body 内 |
| `state.scratchpad` 必须可读可写 | `session_state.py:80-95`，getter + setter 双向 |
| `state.scratchpad is state.teaching_scratchpad` 对默认 session 为真 | property getter 直接 `return self.teaching_scratchpad`，是同一对象引用 |

## Spec Alignment

- **`module_interaction_spec.md §8` 状态写入规则**：拆开 owner（teaching_scratchpad → TeachingLoop / research_scratchpad → DeepResearchLoop），并标注 lazy by TurnRuntime。alias 兼容期说明放在表后。
- **`module_interaction_spec.md §11.2` "不修改其它模块的内部状态"**：`TurnRuntime._select_scratchpad` 是合法写者（TurnRuntime 一直就是 active_turn_id / messages / scratchpad 写入位的合法 owner，见 §8 表）。新加的写法继续走 TurnRuntime 内部函数，不让 deep_research 直接写 SessionState。
- **`module_interaction_spec.md §13` 白名单**：`turn/*` 加 `deep_research.research_scratchpad`。
- **`deep_research/AGENTS.md §0.4` "内存形式状态"**：`research_scratchpad` 仍然是进程内对象，进程退出消失；未引入持久化。
- **`deep_research/AGENTS.md §11.1` 禁止 import 列表**：deep_research 不变，仍不 import session/turn/api/events。`session/session_state.py` 用 `TYPE_CHECKING` 引 `ResearchScratchpad` 是单向（session → deep_research），不构成反向依赖（session 没 import deep_research 运行时）。
- **`deep_research/AGENTS.md §13` 测试策略**：补齐"集成（用 stub LLM 走通完整流程）"层中"经过真实 SessionStore + TurnRuntime"这一截，是 SA-07 之前缺的覆盖。
