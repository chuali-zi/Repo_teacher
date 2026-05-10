# SA-09 · Docs Sync

## What
按 SA-09 任务包要求，把 SA-00..SA-08 的代码事实同步到三份上层 markdown 文档：(a) `new_kernel/AGENTS.md` 在既有 `### Deep Research` 5 个 bullet 之后追加一行单 bullet 指针，把所有实现细节、Phase 切分、prompt 基调、自动触发流程、合同字段全权交回 `deep_research/AGENTS.md`，避免父文档与子文档双源；(b) `new_kernel/web_v4_interface_protocol.md` §5 `POST /api/v4/chat/messages` 的请求体补 `report_kind` 字段（含枚举 / 默认值 / mode×report_kind 组合校验），`message_completed.message` JSON 例子加入 `kind` 字段并配文段说明渲染分流（`answer` 走常规对话流、`repo_onboarding` 走"模块阅读指南"面板），§4 `repo_connected` 段落更新为"前端无需任何额外字段，turn_id 在后续 answer_stream_start 暴露"，新增 §4.4 `自动 onboarding 触发协议`（触发条件 / SSE 事件序列 / 前端读取规约 / 重复触发语义），并显式说明不挂 `auto_turn_id`；(c) `new_kernel/INTERFACES.md` §3.10 `DeepResearchLoop.run` 把旧的"签名与 TeachingLoop.run 一致"占位段落换成与 `deep_research/deep_research_loop.py` 实际签名 1:1 对齐的 `__init__` + `run` 严格 keyword-only 签名，并补四条行为约束（4 phase 走法、5 个取消点、ChatMessage 形状、错误透传）。三处编辑都按任务约束严格附加 / 替换占位，不动任何 `.py` 代码、不动 `deep_research/AGENTS.md`、不改其它无关章节文字。

## Files
- mod  `new_kernel/AGENTS.md`:+1  `### Deep Research` 段尾追加 1 个 bullet 指针 `具体实现细节、Phase 切分、prompt 基调、自动触发流程、合同字段（ReportKind / ChatMessage.kind / SendTeachingMessageRequest.report_kind）：见 deep_research/AGENTS.md。`
- mod  `new_kernel/web_v4_interface_protocol.md`:+58/-4
  - §4 `repo_connected` 例子之后的解释段落改写：保留 `initial_message` 的语义说明，附加"`RepoConnectedEvent` 字段列表保持稳定 / 不挂 `auto_turn_id` / `turn_id` 在 `AnswerStreamStartEvent` 暴露 / 详见 §4.4"
  - §4 末尾新增 `### 4.4 自动 onboarding 触发协议` 子节：触发条件（parse 全程成功 + `connected_data is not None`）、服务端内部 `TurnRuntime.start_turn(initiator="system", request=SendTeachingMessageRequest(message=<seed>, mode=DEEP, report_kind=REPO_ONBOARDING))` 调用样式、前端只订阅 `repositories/stream` 一条流的 SSE 事件序列、`turn_id` 取自 `AnswerStreamStartEvent`、`kind="repo_onboarding"` 是渲染分流的唯一依据、用户 cancel ≤5s emit `RunCancelledEvent`、同 session 二次连仓先 cancel 再 reset 再启新 parse + onboarding
  - §5 `POST /api/v4/chat/messages` 请求 JSON 例补 `"report_kind": "answer"`；其下新增 `report_kind 字段（可选，默认 "answer"）` 描述段（类型 / 默认值 / mode×report_kind 校验规则 / `repo_onboarding` 不要前端主动传）
  - §5 `message_completed` 例子的 `message` 块插入 `"kind": "answer"`；其下新增 `message.kind 字段` 描述段（覆盖响应里所有 `ChatMessage` 出场点 / 旧消息默认 `answer` / `kind="repo_onboarding"` 走"模块阅读指南"面板）
- mod  `new_kernel/INTERFACES.md`:+38/-6  §3.10 整段替换：旧版"签名与 TeachingLoop.run 一致"占位段（含错误的 TeacherAgent 引用）整段删除，换成实现位置 + 与 `turn/turn_runtime.py:TurnLoop` 严格一致的 `__init__` 签名（5 keyword-only agent 注入 + `max_rounds_per_subtopic=2` + `max_parallel_subtopics=1` + `event_factory=Any | None = None`）+ `run` 签名（9 keyword-only：session_id / turn_id / user_message / scratchpad / repo_overview / repo_root / sink / status_tracker / cancellation_token）+ 4 条行为约束（4 phase 走法 / 5 个 cancellation 点 / 返回 `ChatMessage(role="assistant", mode=DEEP, kind=REPO_ONBOARDING, ...)` / 错误透传规则）
- mod  `new_kernel/deep_research/.reports/README.md`:+1/-1  SA-09 索引行去掉"（待）"并补一句结果摘要
- new  `new_kernel/deep_research/.reports/SA-09-docs.md`:本报告

## Decisions
- **`new_kernel/AGENTS.md` 只加一行不复述子文档**：任务硬约束"Do not duplicate any content from `deep_research/AGENTS.md`"。我把指针写成单 bullet 形式（与上面 4 个 bullet 同一颗粒度），点名 4 个高频被搜索的关键词："实现细节 / Phase 切分 / prompt 基调 / 自动触发流程 / 合同字段（含 3 个具体类型名）"。这样读者用 grep 搜 `ReportKind` / `自动触发` / `Phase` 任意一个都能从父文档跳到子文档，不需要双向维护。
- **§4.4 走 `### 4.4` 而非 `### POST /api/v4/...` 命名**：§4 既有 3 个 `### POST /...` / `### GET /...` 子节都用 endpoint 路径作标题。新协议不引入新 endpoint，只是**复用** `POST /api/v4/repositories` 与 `GET /api/v4/repositories/stream`，没有合适的 endpoint 路径可挂。任务包给的标题文案是"## 4.X 自动 onboarding 触发协议"，按文档既有"## N. 标题"是顶级、`### 路径` 是子节的层次，新协议属于 §4 的一个语义子节，落地到 `### 4.4` 是最贴近原文档结构的折衷——既保住了"§-number based on existing structure"的提示（4.4 是第 4 个子项），又不破坏 endpoint 路径风格的其它子节标题。
- **§5 请求 JSON 例子保留显式 `"report_kind": "answer"`**：实际后端给的默认值就是 `answer`，前端在普通 `mode=chat` 时不需要也不应该传它（默认即可），但例子里写出来更直观地告诉前端这个字段长什么样、合法值是什么。注释里明说"可选 / 默认 'answer'"避免误导前端实现者以为它必填。
- **§5 `message_completed` 例子也加 `kind`**：尽管 `message.kind` 默认为 `answer`，例子里把它显式写出来更利于前端在写 type definition / TypeScript model 时直接 copy schema，避免漏字段。
- **§4.4 显式列出 `repo_connected -> agent_status -> deep_research_progress -> answer_stream_* -> message_completed -> agent_status` 全序列**：任务包指定要参考 AGENTS.md §4.2 的 SSE 序列。我直接复用那段格式，包括 phase=triage/decompose/investigate 的细分与 `(k/N)` 的进度计数标记，让前端开发者不需要跳到 deep_research/AGENTS.md 也能拿到完整时序图。
- **§3.10 用 `Decomposer / Investigator / NoteTaker / Composer` 类型而非 `Any`**：实际代码里 `tool_runtime: Any` / `event_factory: Any | None = None` 是 `Any`，但 4 个 sub-agent 形参写的就是具体类。文档与代码一对一，让读者点开 INTERFACES 就知道 4 个依赖必须是 `deep_research/agents/*` 里那 4 个具体类（v1 不允许替换）。`tool_runtime` 在文档里写成 `ToolRuntime`（实际代码 `Any` 是为了规避循环 import / 满足 §11.1 解耦约束），文档读者关心"应该传 ToolRuntime 实例"，实际类型保留 `Any` 是实现细节——这条偏离已与 SA-08 的实际接线方式一致（`api/app.py` 传的就是 `ToolRuntime`）。
- **§3.10 显式标注 `max_parallel_subtopics: int = 1   # v1 = 1（顺序执行）`**：代码里只是 `max_parallel_subtopics: int = 1`，没有内联注释。文档里加上"v1 = 1（顺序执行）"是因为 deep_research/AGENTS.md §3 / §14 都明确说"v1 顺序，预留并发位"——读者看 INTERFACES 时能立刻判断"是不是可以传 5 跑并行" = 不行（v1）。
- **§3.10 行为约束部分的 cancellation 检查点用 `/` 分隔列出 5 个**：代码 docstring 已经列了 6 个（turn entry / Phase 1 entry / each subtopic / each ReAct round / Phase 3 entry / every 8 chunks），任务包列了 5 个（去掉了 "turn entry"，因为 turn entry 由 TurnRuntime 而非本 loop 检查）。我按任务包的 5 个写。
- **没有动 contracts.py 的描述**：任务说让我"to confirm `ReportKind`, `ChatMessage.kind`, `SendTeachingMessageRequest.report_kind` shapes for the docs"，意思是从 contracts.py 里读取已有定义来确认字段名 / 类型 / 默认值是否与我写进文档的一致——确认后字段名 / 默认值都对得上，contracts.py 自身不需要改。SA-00 已经把这部分合同改完了，不要再动一遍。
- 与任务包的偏离：§4.4 章节号选择略偏离"## 4.X"的字面写法（实际用 `### 4.4`），原因见上文第 2 条 decision；任务包同时给了"pick the right §-number based on existing structure"的弹性，按"if there's already a §4 numbered list, append"的指示在 §4 末尾追加，符合给定灵活度。

## Verification
- `python -m compileall new_kernel` — 通过（markdown 改动不影响 Python 编译，但作为 sanity check 跑过；输出末段确认 `compileall` 全部 listing 完毕，无 SyntaxError 抛出）
- `Grep -p "具体实现细节、Phase 切分、prompt 基调、自动触发流程、合同字段" new_kernel/AGENTS.md` — 命中 1 行（`#319`）
- `Grep -p "report_kind|kind|repo_onboarding|4\.4 自动 onboarding" new_kernel/web_v4_interface_protocol.md` — 命中 13 行（其中 §4.4 标题 1 行 / `report_kind` 字段段 5 行 / `repo_onboarding` 出现在 SSE 序列与渲染规约 4 行 / `kind` 出现在 message_completed 例 + 字段段共 3 行；与预期一致）
- `Grep -p "3\.10 \`DeepResearchLoop\.run\`|max_rounds_per_subtopic|REPO_ONBOARDING" new_kernel/INTERFACES.md` — 命中 3 行（`#556` 标题 / `#572` __init__ 签名 / `#596` 行为约束里的 ChatMessage 形状）
- 视觉走查：三份 markdown 的代码块栅栏（` ``` `）开闭一一对应、heading 层级递增（`##` -> `###`）、JSON 例子结构闭合无缺尾逗号
- 已知问题 / TODO：无；SA-10 接力时无需再回头补 docs，三份文件已与 SA-00..SA-08 实现完全 1:1。

## Spec Alignment
- `deep_research/AGENTS.md` §3（4 phase 走法）、§4（自动触发协议 / SSE 事件序列）、§5（cancellation 检查点）、§9.1（`DeepResearchLoop.run` 签名与 `TurnLoop` Protocol 一致）、§10（合同字段 `ReportKind` / `ChatMessage.kind` / `SendTeachingMessageRequest.report_kind`）— 全部映射到 web_v4_interface_protocol.md §4.4 / §5 与 INTERFACES.md §3.10
- `new_kernel/AGENTS.md` `### Deep Research` 既有 5 bullet 不动，仅追加 1 bullet 指针；维持父子文档单源原则
- `new_kernel/contracts.py` §69 / §153 / §246-§250 已固化的合同字段与文档描述完全一致（`ReportKind = answer | repo_onboarding` / `ChatMessage.kind` / `SendTeachingMessageRequest.report_kind` 默认值 `answer`）
- `new_kernel/deep_research/deep_research_loop.py` §131-§169 实际 `__init__` 与 `run` 签名与 INTERFACES.md §3.10 文档签名 1:1 对齐（参数名 / 顺序 / 默认值 / keyword-only 全部一致）
- 任务硬约束：未改 `deep_research/AGENTS.md`、未改任何 `.py` 文件、未删除或改写既有段落（§4 既有 3 个子节、§5 请求 / 响应主体、INTERFACES §3.1-§3.9 / §3.11-§3.12 全部原文保留）
