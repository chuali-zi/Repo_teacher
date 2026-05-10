# RECON-F · onboarding 报告与后续 chat 对话连续性 侦察

## What

证实用户直觉：onboarding markdown 与其证据池**完全没有**进入后续 `mode=chat` turn 的 prompt。M1（state.messages 不入 prompt）与 M2（research_scratchpad 不向 teaching_scratchpad 桥接）**都成立**——chat agent 在 onboarding 完成后第一次回答时，它的 OrientPlanner 与 TeacherAgent 看到的 prompt **与 onboarding 从未发生过完全一致**。

## 数据流证据链

### Task 1: state.messages → 后续 turn 的 prompt 是否传递

**TurnRuntime 入参**（`turn/turn_runtime.py:355-365`）：
```
assistant_message = await loop.run(
    session_id=...,
    turn_id=...,
    user_message=request.message,        # ← 仅当前 user 这一条
    scratchpad=scratchpad_for_turn,       # ← 仅 _select_scratchpad 出来的 pad
    repo_overview=_repo_overview(state),
    repo_root=...,
    sink=...,
    status_tracker=...,
    cancellation_token=...,
)
```
- 关键：`state.messages` **从未作为入参**传给 `loop.run(...)`。
- `state.messages` 在 turn_runtime 里只在 `:261`（append user）和 `:371`（append assistant）出现，没有任何 read 路径把它喂给 loop。
- 同等显示在 `TurnLoop` Protocol（`turn/turn_runtime.py:117-130`）里没有 messages 参数。

**TeachingLoop 内部**（`agents/teaching_loop.py:112-236`）：
- `run(...)` 签名（`:112-124`）：`user_message: str` + `scratchpad` + `repo_overview` + 运行环境，无 history。
- OrientPlanner 调用（`:136-141`）：
  ```
  plan = await self._orient.process(
      question=user_message,
      repo_overview=repo_overview,
      previous_covered=scratchpad.covered_points,   # ← 取自 teaching pad
      tool_descriptions=...,
  )
  ```
  没有任何 `state.messages` 派生入参。
- TeacherAgent 调用（`:209-215`）：
  ```
  output = await self._teacher.process(
      question=user_message,
      scratchpad=scratchpad,
      previous_covered=scratchpad.covered_points,
      next_anchor_hint=_next_anchor_hint(steps),
      on_chunk=on_chunk,
  )
  ```
  同样没有历史消息。

**OrientPlanner 看到的**（`agents/orient_planner.py:54-69`）：4 个占位符 `question / repo_overview / previous_covered / tool_descriptions`，全部不含 history。`prompts/zh/orient.yaml:22-35` 的 `user_template` 同样仅这四占位符。

**TeacherAgent 看到的**（`agents/teacher.py:82-97`）：4 个占位符 `question / scratchpad_evidence / previous_covered / next_anchor_hint`。`prompts/zh/teach.yaml:25-38` 同确认零 history 占位符。

**`scratchpad.covered_points` 在 chat 模式启动时的形态**：第二轮 chat 调用 `scratchpad.reset_for_turn(user_message)`（`memory/scratchpad.py:148-154`），它**保留** `covered_points` dict。但这个 dict 上一轮如果是 onboarding（DEEP），写的是 `state.research_scratchpad`（不同对象）；写到 teaching pad 的 `covered_points` 永远是空的——直到第一次 chat 被 `_record_covered_point` 写一次（`agents/teaching_loop.py:227, 350-360`）。

**结论 M1 成立**：TeachingLoop 在 prompt 层完全看不到 `state.messages`，包括 onboarding 那条 `kind=REPO_ONBOARDING` 的 ChatMessage。

### Task 2: research_scratchpad → teaching_scratchpad 桥接

**grep 结果**：
- `add_covered_point` 的写入点：仅 `tests/test_deep_research_scratchpad.py:138-140` 与 `research_scratchpad.py:90-96` 自身定义。`deep_research_loop.py` 全文**零次**调用 `add_covered_point`，也零次写 `state.teaching_scratchpad.update_covered_points`。
- `teaching_scratchpad` 仅在 `session/session_state.py:66, 91, 95`（field/property）、`session/session_store.py:60`（构造）、`turn/turn_runtime.py:716`（读出来 dispatch）、tests 里有出现；**没有任何业务模块写它**，也没有任何模块从 `state.research_scratchpad` 读后写到 `state.teaching_scratchpad`。
- 关键字 `conversation_history|previous_messages|onboarding_summary|prior_messages` 全仓零命中。

**没衔接的证据**：`deep_research_loop.py` 只调用 `scratchpad.set_subtopics / add_note / add_skip_reason / notes_for / build_compose_context`（line 248, 345-350, 390-401, 454）。Compose 阶段产出的 markdown 仅落进 `ChatMessage.content`（`:495`）由 TurnRuntime 写到 `state.messages`，并未把信息写入任何被后续 chat 读到的容器。

**与 AGENTS.md §5 的偏差**：`deep_research/AGENTS.md:325, 330` 明确承诺「scratchpad 中 onboarding 的 sub-topic 笔记保留，TeachingLoop 通过 covered_points 复用」「保留全部 sub-topic 笔记 + covered_points，供后续 TeachingLoop 引用」。FIX-01 落地后这条契约**默默破裂**：onboarding 笔记落在 `research_scratchpad._notes`，covered_points 落在 `research_scratchpad._covered_points`（其实从未被 deep loop 写过），而 chat 走的是 `teaching_scratchpad.covered_points`（dict[str, str]，类型都不一样）——两个对象字面互不相通。

**结论 M2 成立**：零自动桥接；teaching pad 在第二轮（chat 第一轮）启动时 `covered_points = {}`，`reading_plan = []`，`read_entries = []`。

### Task 3: 用户视角下的"割裂"具体长什么样

场景（用户报告所述）：repo 接入完成 → 后端自动跑 onboarding → 前端收到 `MessageCompletedEvent(kind=repo_onboarding)`，markdown 含 6 个 sub-topic 的导读 + arch 顶层目录 + suggestions（如 "deep_research 模块到底怎么用？"）。用户随即点击 suggestion，发起 `POST /api/v4/chat/messages mode=chat message="那 deep_research 模块到底怎么用？"`。

第二轮 chat 进入 TeachingLoop 时：
- `user_message`：`"那 deep_research 模块到底怎么用？"`（含一个指代词 "那"，但没有任何上下文界定 "那" 指谁）。
- `scratchpad`：`teaching_scratchpad`，全空（`question="那..."`, `reading_plan=[]`, `read_entries=[]`, `covered_points={}`，`metadata={}`）。
- `repo_overview`：与 onboarding 时相同的 `_repo_overview(state)` 文本，但**不含任何 onboarding 笔记**。
- 不可见：`state.messages` 列表里那条 6000 字 onboarding markdown、suggestions、arch 列出来的顶层目录、其他 5 个 sub-topic 的 NoteTaker 笔记、Composer 的设计原因 / 协作链分析——OrientPlanner 与 TeacherAgent **皆不可见**。

OrientPlanner 拿到的 user_prompt 等价于「全新 session 的第一次提问」：
```
用户问题：那 deep_research 模块到底怎么用？
仓库概览：repo_overview:
- display_name: ...
- primary_language: ...
- file_count: ...
已讲过的点：(none)                ← ← ← 关键瑕疵
可用只读工具：...
```

TeacherAgent 拿到的也类似。LLM 此刻必须从零再做一次 1-3 步阅读计划 + 工具调用 + 教学正文——它再次发现 `deep_research/` 目录、再次解释 four-phase pipeline，对用户而言就是「这段我刚刚读过了为什么又讲一次」「为什么没接住我说的"那"」。

二次问题更糟：连续两个 chat turn 之间也没有 `state.messages` 桥接——TeachingLoop 当前只靠 `_record_covered_point` 给 `covered_points` 累计 1 条 ≤300 字摘要，下一轮 OrientPlanner 看到的 `previous_covered` 也只有这一条。链路对用户的"长期记忆"印象 = `covered_points` 这一行 dict 的累积，而 onboarding 那 6000 字直接被绕过。

## 关键发现

- **F1.** TurnRuntime/TeachingLoop 整条 prompt 路径中 `state.messages` 的读路径为零（`turn/turn_runtime.py:355-365` 不传，`agents/teaching_loop.py:112-236` 不收，`prompts/zh/{orient,teach}.yaml` 不展示）——`state.messages` 是**前端历史展示** + 状态快照专用容器，未介入 LLM 上下文。
- **F2.** `state.research_scratchpad` 与 `state.teaching_scratchpad` 在内存里完全两套对象（前者 `ResearchScratchpad`、后者 `memory.Scratchpad`，连 `covered_points` 类型都不同：`tuple[str, ...]` vs `dict[str, str]`），**无任何代码路径**把前者写进后者。
- **F3.** `ResearchScratchpad.add_covered_point` 是死方法：`deep_research_loop.py` 从不调用它；它的 `_covered_points` 永远是 `[]`，所以即便有人未来用属性别名硬桥（`teaching_scratchpad.covered_points |= research_scratchpad.covered_points`），也会发现源端是空的——`covered_points` 必须由 Composer 或 loop 终态显式写入。
- **F4.** `deep_research/AGENTS.md:325, 330` 的契约被 FIX-01 默默破坏；FIX-01 是结构修复（让对象不同名），但没有同步加上"内容继承"——这是一个可在 spec 里追溯的回归。
- **F5.** Onboarding 的最低限度可继承内容**完全可以**抽出来（Composer 已经为每个 sub-topic 在 `notes_by_id[meta.id]` 里聚了 1-N 条 NoteTaker 文本，arch 还有顶层目录 raw、Composer 的最终 markdown 也在内存里——只差一个把它们物化成 `Scratchpad.covered_points` 或 `ReadEntry.observation` 的钩子）。

## 候选改进方向（仅记录，不实现）

### (a) 会话历史注入 prompt
- 改动点：`turn/turn_runtime.py:355-365` 增传 `prior_messages=list(state.messages[:-1])` 或更精炼的 `last_onboarding=state.messages[i]`；`agents/teaching_loop.py:112-141, 209-215` 把它转手给 Orient + Teacher；`agents/orient_planner.py:54-69, prompts/zh/orient.yaml:22-35` 与 `agents/teacher.py:82-97, prompts/zh/teach.yaml:25-38` 各加一个 `{conversation_history}` 或 `{onboarding_summary}` 占位符。
- 污染：3 处 prompt yaml + 3 处 agent code + 1 处 turn_runtime + 2 处 ChatMessage 形态判定（区分 onboarding kind 与普通 answer）。
- 提升：高——所有 ChatMessage（含 onboarding）都能进入下一轮 prompt，等同 ChatGPT 的 conversation memory。
- 反向收益：上下文长度涨 6000-10000 字（每次都要塞 onboarding markdown 进 user_prompt），LLM cost 翻倍；多轮后还需做截断/总结策略。
- 反转性：高（仅删占位符即可回滚）。
- AGENTS.md 兼容：需要给 `agents/teaching_loop.py` 占位符更新 §INTERFACES，以及 `module_interaction_spec.md §8` 加 "TurnRuntime 把 state.messages 暴露给 TeachingLoop"。`turn/*` 不引入新模块依赖，§13 不变。

### (b) Scratchpad 桥接
- 改动点：`deep_research/deep_research_loop.py:_run_compose_phase` 末尾（`:486` 之后、`:490` 之前）新加一段把 `scratchpad.notes_for(sub.id)` + `composer.last_output.markdown` 摘要写到 `state.teaching_scratchpad.covered_points`（key="onb:what" 等）+ 给每个 sub-topic 写一条合成 `ReadEntry`。但 `deep_research_loop.py` 不应直接写 `state.teaching_scratchpad`——按 §11.2 turn_runtime 才是 legal writer，所以新增 1 个公开钩子函数 `bridge_research_to_teaching(state)` 放在 `turn/turn_runtime.py:_run_turn` 在 deep loop 成功 return 后立即调用（约 `turn/turn_runtime.py:367` 之后）。
- 污染：1 个新桥接函数 + 1 个 turn_runtime 调用点；零 yaml 改动；零 agent code 改动；零 prompt 占位符改动。
- 提升：中——下一轮 chat 的 OrientPlanner 看到 `previous_covered` 里有 6 条 onboarding 摘要，能避免重复教 + 知道 "用户已经读过的概念词"；TeacherAgent 的 `scratchpad_evidence` 也能直接看到 ReadEntry。
- 反转性：高（删桥接函数即可，不影响其他模块）。
- AGENTS.md 兼容：直接兑现 `deep_research/AGENTS.md:325, 330` 的承诺，**反而修复**回归。`module_interaction_spec.md §8` 需新增一行 `TurnRuntime` 在 deep 成功 commit 后写 `state.teaching_scratchpad`。`turn/*` 已有 `deep_research.research_scratchpad` import，无新依赖。
- 局限：摘要是 ≤300 字 covered_points + ReadEntry，不是 onboarding 全文；用户问到 onboarding 已展开但被裁掉的细节时，仍要重读源码——但这恰好是设计上想要的（避免重复展开）。

### (c) State-side bootstrap（一次性 promote）
- 改动点：`turn/turn_runtime.py:_run_turn` 入口（`:351` 后）侦测「mode=CHAT 且 state.research_scratchpad is not None 且 state.teaching_scratchpad.covered_points == {}」时，调用 (b) 同款桥接函数；之后清空 `state.research_scratchpad` 或在 metadata 里打 `bridged=True`。
- 污染：与 (b) 类似但触发点搬到 chat turn 入口；把"何时桥"从 deep loop 收尾移到 chat loop 启动；逻辑更复杂（需判断状态机）。
- 提升：中（同 (b)）。
- 反转性：中（多了状态机标志位）。
- AGENTS.md 兼容：与 (b) 相同；但需要在 §3.5 / §5 加 "chat mode 启动时执行 lazy bridge" 的描述。
- 相对 (b) 的劣势：deep loop 失败/取消的半截 state 也会触发桥；需要更细的"桥成功条件"定义。

### (d) 前端 system 注入
- 改动点：`web_v4/RepoTutor.html` 或前端发送层每次 `POST /chat/messages` 前在 message 前缀注入 `<system>` 块包含 onboarding markdown 摘要。
- 污染：仅前端；后端 prompt 路径仍空。
- 提升：低-中——LLM 实际看到的是用户消息里的塞料，但 OrientPlanner 的 `question` 占位符会被一段「上下文 + 问题」混合污染，影响 reading plan 质量；且无法控制每次塞料都同样长。
- 反转性：高。
- AGENTS.md 兼容：违背 web_v4_interface_protocol.md 的契约（前端不应改 message 内容）；不推荐。
- 弱点：失去"代理人理解长上下文"的服务端控制权，难以做截断/优化；与现有 `state.messages` 的去重也不一致。

## 推荐

- **主推 (b) Scratchpad 桥接**：最贴合 AGENTS.md §5 的原始设计意图；改动量极小（1 桥接函数 + 1 turn_runtime 调用点）；零 prompt 改动 = 零 LLM cost 增幅；可逆性高；不违反 §11.x 模块边界。直接消除 M2，让 OrientPlanner 看到 onboarding 已覆盖的点 → 不再重复教 → "割裂感"显著下降。
- **兜底 (a) 会话历史注入**：当 (b) 落地后用户仍报告「连"那"这种代词都接不住」时（说明 covered_points 摘要不够锚定指代），再上 (a)。最小版本可只塞最近 1 条 `kind=REPO_ONBOARDING` 的 markdown 摘要 + 最近 N 条 chat assistant 消息，不必塞全 history，避免 cost 失控。

最优组合预测：先做 (b)，跑一两个真实 session 看用户体感；若仍有指代/上下文断点 → 增量加 (a) 的 onboarding_summary 单一占位符（仅注入 onboarding 那条，不动其他 messages）。

## 待用户确认

1. **保真粒度**：onboarding 应该「整段塞进 prompt」（高保真但贵），还是「沉淀成 covered_points + 关键 ReadEntry」（结构化但裁剪）？(b) 默认走后者；如果用户想要前者，需要走 (a)。
2. **触发时机**：桥接是 deep loop 成功收尾时立即做 (= 我推荐的 (b))，还是 chat 第一次启动时懒做 (= (c))？前者一致性高，后者能容忍 "chat 来不来就两说" 的会话。
3. **跨轮记忆策略**：onboarding 的 `covered_points` 与之后 chat 自己累计的 `covered_points` 是否需要区分命名空间？比如 `onb:*` vs `chat:*`，便于 prompt 里"已讲过的点"段落分组展示，避免老师误把 onboarding 摘要当作上一轮 chat 教学。
