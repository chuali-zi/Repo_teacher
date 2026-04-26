# Repo_teacher 后端 Agent 全面问题分析报告

分析时间：2026-04-22  
分析对象：`https://github.com/chuali-zi/Repo_teacher` 的公开 `main` 分支，重点为 `backend/`、`new_docs/PRD_v6_teaching_first.md`、README 中的运行时说明。  
说明：我尝试在容器中直接 `git clone`，但当前容器 DNS 无法解析 GitHub，因此没有在本地运行测试；本报告基于 GitHub 页面中可见源码、README、PRD 文档与后端文件逐项分析。

## 1. 总结判断

当前问题不只是“模型被限制得太死”，也不只是“工具调用轮数、工具数量、上下文长度”之类的工程参数问题。真正的核心矛盾是：**新 PRD v6 要求系统从“仓库分析器”转为“以源码为教材的持续教学系统”，但当前后端运行时仍然按照“证据优先、导航优先、保守结论优先”的架构在驱动模型。**

所以 Agent 会表现出：先复述 README、文件树、模块名；工具读取后把读到的内容概括一遍；很快进入“证据/不确定性/建议”；缺少像老师一样主动选一个点讲透、解释设计意图、建立概念、用少量源码锚点带用户读懂的能力。

这不是单点 bug，而是多层共同造成的系统性偏差：README 中的运行时设计、M5 教学状态、M6 prompt、输出 contract、解析器、工具上下文、流式输出方式、deep_research 与正式教学链路的割裂，都在把模型推向“取证报告”而不是“讲课”。

最复杂、最关键的问题是：**如何在不牺牲源码真实性的前提下，让 Agent 主动讲课。** 当前系统把“避免幻觉”理解成“没有源码证据就尽量不讲”，结果教学主体被证据链吞掉。PRD v6 的正确方向不是放弃证据，而是改成：**教学优先，证据边界约束；候选结论允许存在，但必须携带 evidence_refs、confidence、unknowns；可见回答中证据压缩为支撑层，而不是主产品。**

## 2. PRD v6 对系统的真实要求

`new_docs/PRD_v6_teaching_first.md` 的要求可以压缩成以下判断标准：

第一，产品不是“回答问题的仓库分析器”，而是“持续教学系统”。Agent 的工作不是把仓库事实列出来，而是带用户读懂仓库。

第二，源码是真实材料，证据用于防止幻觉，但证据不能吞掉教学正文。也就是说，工具读取、路径、文件名、片段引用都只是讲课的材料，不是讲课本身。

第三，每轮要像课堂的一小节：只选一个最值得讲的点，说明为什么现在讲它，解释它在系统中的作用，用少量源码锚点支撑，然后自然给出下一个教学子点。

第四，不允许首轮变成文件树 dump，不允许所有点都浅浅碰一下，不允许只列候选、证据、置信度，不允许把“下一步”做成问题菜单。

第五，状态必须支撑多轮连续教学。后续轮次不能每次从零开始，不能重复上一轮 README/结构概括，也不能因为用户问了一个局部问题就丢掉前面的教学脉络。

第六，PRD 明确要求内部有内容丰富度自检：是否讲透一个点、是否说明角色/为什么、是否只用了必要锚点、是否没有因证据保守而过早停止、是否给出了单一具体的下一个教学点。

当前后端的主要设计与这些要求存在直接冲突。

## 3. 用户观察到的现象与后端机制的对应关系

### 3.1 现象：Agent 基本复述 README 结构

直接原因是：当前初始上下文主要来自 `m1.get_repository_context`、`m2.get_file_tree_summary`、`m2.list_relevant_files` 和 `teaching.get_state_snapshot`。README 也明确说当前没有 M3 静态入口推断、没有 M4 教学骨架、没有 repo_kb、没有后端生成的 likely architecture payload。

这意味着模型进入回答时，拿到的是“仓库名、文件树、候选相关文件、轻量教学状态”，而不是“这个仓库作为教材应该怎么教”的结构化材料。因此它最容易生成的内容就是：把文件树或 README 中已经写过的模块说明重新组织一遍。

### 3.2 现象：调用工具读取后，也只是把文件信息复述一遍

读取工具本身没有错。问题是读取结果进入 prompt 后，缺少一个强制性的“读完后要转成教学”的中间层。

当前工具上下文策略强调：这些结果是只读参考材料；优先使用 deterministic tool evidence；证据不完整时标成推断。这个策略保证了安全，但没有要求模型回答：

- 这个文件为什么存在；
- 这个类/函数解决了什么教学问题；
- 这个模块和上层产品目标有什么关系；
- 为什么作者可能这样拆职责；
- 初学者读这里应该先建立什么概念；
- 读完这个锚点后自然应该讲哪一个下一个点。

所以模型读完源码后，默认动作是“总结证据”，而不是“讲课”。

### 3.3 现象：很快进入证据分析

这是输出 contract 直接造成的。`TeachingService._build_output_contract` 要求可见回答覆盖固定部分：`FOCUS`、`DIRECT_EXPLANATION`、`RELATION_TO_OVERALL`、`EVIDENCE`、`UNCERTAINTY`、`NEXT_STEPS`。M6 prompt 又要求“自然覆盖这些部分、标记不确定性、给 1-3 个下一步”。

PRD v6 的方向正好相反：这些维度可以作为内部检查，但不能硬化成可见固定栏目。因为一旦 `EVIDENCE` 和 `UNCERTAINTY` 成为与 `DIRECT_EXPLANATION` 同级的固定栏目，模型就会把教学正文拆碎，并把可见输出变成分析报告。

### 3.4 现象：不像老师，不主动讲课

“老师感”需要三件事：主动选择教学点、围绕一个点讲透、把下一轮连接起来。当前三件事都弱。

当前 `teaching_state.py` 初始化教学计划只有轻量三步：建立整体地图、核实第一个源码起点、沿用户问题继续深挖。这个计划是 `m2_file_tree_only` 生成的，不是真正的 repo teaching skeleton。后续 `build_teaching_decision` 和 `build_teaching_directive` 只决定是回答当前问题、目标切换、阶段总结还是局部问题；它没有生成一个足够强的 `TeachingTurnPlan`，也没有明确本轮“必须讲透的教学单元”。

因此模型收到的控制信息通常是“answer current question with source-grounded repository evidence”，而不是“今天这节课讲 X，为什么先讲 X，用哪些源码锚点，讲到什么深度，讲完接 Y”。

### 3.5 现象：后续轮次重复、断裂或只给建议

这与解析器和状态更新有关。当前 follow-up JSON schema 基本只要求 `next_steps`，结构化教学信息主要靠可见文本解析或 fallback。`response_parser.py` 如果没有结构化 payload，会把整个 visible_text 当成 direct_explanation，还会从文本第一行 fallback 出 evidence。这样会把“看起来像有内容”的回答记录成“已经讲过”，即使它只是复述文件树或证据列表。

状态层随后根据 `direct_explanation`、`related_topic_refs`、`evidence_count` 等信号更新教学进度。由于这些字段不是稳定的教学语义，而是从文本或非常薄的 schema 里猜出来的，后续规划自然容易失真。

### 3.6 现象：即使工具轮数很多，也没有变好

README 中默认工具轮数可到 50，且超时时间较长，但工具轮数不是核心瓶颈。当前 `tool_selection.py` 主要暴露 `m2.list_relevant_files`、`search_text`、`read_file_excerpt`，初始报告额外读取片段；`context_budget.py` 则预置仓库上下文、文件树摘要、相关文件列表、教学状态快照。

这套工具适合“找证据”，不适合“组织课程”。如果工具只能给文件、搜索、片段，模型只能把自己变成一个源码检索器。要像老师，需要的是教学材料工具：入口候选卡片、模块职责卡片、候选流程骨架、import/source 分析、当前教学点需要的 anchor pack、已讲/未讲 topic graph。

## 4. 根因总表

| 层级 | 当前机制 | 造成的结果 | PRD v6 要求 |
|---|---|---|---|
| 产品定义 | README 强调后端只提供导航、文件树、状态、安全读源码工具，不提供静态教学结论 | 模型缺少教学骨架，只能复述可见结构 | 后端应提供 evidence-bounded 的候选教学骨架 |
| 初始计划 | `m2_file_tree_only` 三步轻量计划 | 首轮容易变成结构概览 | 首轮必须落到一个具体教学点 |
| Prompt | 强调源码证据、候选/不确定、轻量建议 | 讲课冲动被保守性压住 | 教学正文优先，证据辅助 |
| 输出 contract | 固定要求 Evidence / Uncertainty / Next steps | 可见答案变分析报告 | 这些应为内部维度，不是固定可见栏目 |
| JSON schema | follow-up 主要只有 `next_steps` | 状态无法准确知道讲了什么 | schema 应记录教学点、锚点、边界、下个点 |
| Parser | 从可见文本 fallback direct/evidence | 状态被污染，误判“已讲过” | fail closed，缺字段就让质量门重写 |
| Tool context | 文件树、搜索、片段 | 只能取证，不能组织课程 | 增加 teaching skeleton / topic card / anchor pack |
| Streaming | 先把答案流给用户，再解析 | 无法进行质量门改写 | 先生成草稿、质量检查、必要时重写，再发可见答案 |
| Next steps | 1-3 个问题或动作 | 像菜单，不像课堂推进 | 必须一个具体下一教学子点 |

## 5. 具体代码层问题分析

### 5.1 README 的“保守运行时”与新 PRD 的方向冲突

README 的当前运行时说明写得非常明确：后端只提供仓库访问、文件树索引、教学状态、安全源码读取工具；不提供 m3 静态入口推断、不提供 m4 教学骨架/主题索引、不提供 repo_kb、不提供后端写死的 likely architecture payload。

这个设计在“避免后端自作聪明”上是合理的，但它导致系统只剩下“可检索材料”，没有“可教学结构”。PRD v6 不是要后端编造事实，而是要后端生产“带证据边界的候选教学材料”。两者的差别非常重要：

- 错误做法：后端硬说“入口就是 X，调用链就是 Y”；
- 正确做法：后端生成 `entry_candidates=[{path, reason, evidence_refs, confidence, unknowns}]`，让老师围绕候选锚点讲，并在不确定处明确边界。

当前 README 的维护者指令把“候选教学骨架”也一起排除了，导致模型没有讲课地图。

### 5.2 `context_budget.py` 把初始上下文引向文件树复述

`build_llm_tool_context` 会根据场景和学习目标选择 seed results。初始报告会注入：

- `m1.get_repository_context`
- `m2.get_file_tree_summary`
- `m2.list_relevant_files(limit=60)`
- `teaching.get_state_snapshot`

如果用户文本包含“代码/源码/函数/类/实现/.py/路径”等，还会构造 starter excerpt。

这对“快速回答仓库在哪些文件里”有帮助，但对“讲课”不够。因为这些 seed result 没有表达：哪个点最值得先讲、为什么、讲到什么深度、当前用户处于什么认知阶段、哪些锚点只是支撑而不是正文。

### 5.3 `tool_selection.py` 的工具集合偏取证，不偏教学

候选工具名主要是：`m2.list_relevant_files`、`search_text`、必要时 `read_file_excerpt`。这些工具都是证据工具，不是教学组织工具。

这会让模型的内部循环变成：

1. 先列相关文件；
2. 再搜索文本；
3. 再读片段；
4. 最后把证据总结出来。

这条链路天然导向“分析报告”，不导向“课堂讲解”。要改变行为，工具层必须给模型一个更高级别的教学材料入口：例如 `teaching.get_current_turn_plan`、`teaching.get_anchor_pack`、`teaching.get_repo_skeleton`。

### 5.4 `prompt_builder.py` 的系统规则仍然是 evidence-first

系统规则有“像老师一样回答”“每轮小核心点”“给下一步”等语言，但它和更强的规则放在一起：必须优先文件树和工具结果；入口/流程/分层/依赖没有源码证据只能作为候选或未知；给轻量阅读建议，不给事实性固定顺序；Markdown 后附 JSON。

这些规则单看都合理，组合起来会产生一个副作用：模型为了避免越界，会把大量精力花在“我能不能这么说”的证据判断上，而不是“我如何把这个点讲懂”。

真正的 v6 prompt 应该把顺序改成：

1. 先完成本轮教学单元；
2. 再用少量证据锚点支撑；
3. 不确定内容只在边界处标注；
4. 不要把证据分析作为主干；
5. 读完源码必须解释“为什么这样设计/在系统中承担什么职责/初学者应该怎么理解”。

### 5.5 `TeachingService._build_output_contract` 把可见答案模板化成分析报告

输出 contract 要求覆盖 `FOCUS`、`DIRECT_EXPLANATION`、`RELATION_TO_OVERALL`、`EVIDENCE`、`UNCERTAINTY`、`NEXT_STEPS`。这就是当前“证据分析味”强的直接原因之一。

PRD v6 明确说这些是“维度”，不是固定可见模块。一个老师讲课时可能自然地说：

“这一轮我们先讲 `Session` 为什么是整套系统的中枢。你可以把它理解成课堂记录本：它不直接分析代码，但它决定每一轮老师知道你学到哪了、下一步该讲什么。源码里你主要看两个地方……”

而不是：

“本轮重点 / 直接解释 / 与整体关系 / 证据 / 不确定项 / 下一步建议”。

固定栏目会破坏教学口吻，也会诱导模型把每个栏目都填一点，形成“多点浅讲”。

### 5.6 `teaching_state.py` 的计划不是课程计划，而是轻量导航计划

`build_initial_teaching_plan` 的三个步骤是：

1. 建立仓库整体地图；
2. 核实第一个源码起点；
3. 沿用户关心的问题继续深挖。

这不是教学课程计划，只是“读仓库流程”。它不知道：

- 这个仓库适合先讲哪个架构概念；
- 哪个模块最能代表设计意图；
- 用户是大一学生时应该先建立什么抽象；
- 哪些 topic 已讲透，哪些只是提过；
- 每轮的“讲透标准”是什么。

这导致 M5 无法给 M6 一个强教学意图，只能给“当前 goal/stage/depth + avoid repeats + answer user first”。

### 5.7 `build_teaching_directive` 控制力太弱

当前 directive 的默认目标大致是：用源码证据回答当前问题；允许 1-2 个新点；必须锚定证据；避免重复；内部状态不要外露。

这个 directive 没有指定本轮课程结构。它不告诉模型：

- 本轮唯一教学点是什么；
- 为什么现在讲它；
- 哪些源码锚点必须用、哪些不要用；
- 教学动作是类比、流程讲解、职责拆解还是代码 walkthrough；
- 讲到什么程度才算完成；
- 下一轮唯一子点是什么。

因此模型没有“教师驾驶舱”，只有“证据回答约束”。

### 5.8 `response_parser.py` 的 fallback 会污染教学状态

解析器在没有结构化 payload 时，会从可见文本中抽取 fixed sections；再失败时，会把整个 visible text 当作 direct explanation；证据 fallback 甚至可能从第一行生成 evidence line。

这会造成两个严重问题：

第一，质量差的回答也可能被记录为已经讲过。比如回答只是“这个仓库有 backend、frontend、new_docs”，也可能被当作 direct explanation。

第二，状态层根据这些字段推进 teaching plan，可能跳过本应继续讲透的点。用户看到的是“它没讲课”，状态里却可能以为“它讲过了”。

正确做法应该是 fail closed：如果 JSON 中没有明确 `teaching_point_covered`、`source_anchors`、`next_teaching_point` 等字段，就不能更新“已讲透”状态；应该触发质量门或标记为未完成。

### 5.9 `ChatWorkflow` 和 `tool_loop.py` 先流式输出，再解析，无法做质量门

当前 chat workflow 会边收到 LLM delta 边发 `ANSWER_STREAM_DELTA` 给前端，等流结束后再 parse_answer、更新状态。`tool_loop.py` 同样会把可见文本 delta 直接 yield 出去。

这意味着后端没有机会在用户看到之前判断：

- 是否只是在复述 README；
- 是否证据占比过高；
- 是否没有讲透一个点；
- 是否有多个 next steps；
- 是否固定模板过重；
- 是否没有解释设计意图。

PRD v6 的“内容丰富度自检”如果要落地，就不能在已经发给用户之后才做。至少 follow-up 教学答案应改成“生成草稿 -> 质量检查 -> 必要时重写 -> 再 stream 最终答案”。

### 5.10 `next_steps` 的产品语义错误

当前输出 schema 和 parser 都围绕 `next_steps`，而且是 1-3 个可点击问题/动作。PRD v6 要的是“下一个教学子点”，不是菜单。

老师不会在每小节结束时给学生 3 个按钮让学生决定路线；老师应该主动推进：

“下一步我会接着讲：为什么这个系统把工具调用和教学状态拆开，而不是让 LLM 自己记住所有东西。”

可以保留 UI 点击能力，但后端语义应该是 `next_teaching_point`，而不是 `next_steps[]`。

## 6. 现有方案中真正应该保留的部分

当前后端并非整体错误。以下部分是有价值的，应该保留：

第一，读源码工具只读、安全、受路径限制，这对可信教学非常重要。

第二，工具调用过程有活动事件、超时、降级，这对 UX 和稳定性有价值。

第三，M1/M2/M5/M6 分层基本清晰，适合在中间插入 M3/M4，而不是推倒重来。

第四，已有 teaching state、history summary、goal inference、stage decision 等基础设施，虽然语义不够强，但可以升级为 v6 teaching state。

第五，deep_research 目录中已有更深分析的雏形，可以改造成 skeleton builder 的材料来源。

所以改造重点不是“把证据系统删掉”，而是把证据系统降级为教学支撑层，同时补上教学规划层和质量门。

## 7. P0 问题清单

### P0-1：缺少 RepoTeachingSkeleton

没有一个结构化对象把仓库转成“可教学材料”：项目画像、入口候选、import 来源、模块职责、候选流程、层次关系、主题卡片、unknowns、evidence_refs。

这是所有复述 README 问题的源头。

### P0-2：缺少 TeachingTurnPlan

每轮没有一个强制执行的教学计划对象。Agent 不知道本轮唯一教学点、为什么现在讲、讲到多深、用哪些锚点、下个点是什么。

### P0-3：输出 contract 与 PRD 冲突

固定 Evidence/Uncertainty/NextSteps 栏目让可见答案变成报告，而不是课堂。

### P0-4：follow-up schema 太薄

只靠 `next_steps` 无法支撑多轮教学状态。状态更新需要明确的教学语义字段。

### P0-5：parser fallback 误伤状态

把普通 visible text 当作 direct explanation/evidence 会造成状态污染。

### P0-6：没有内容质量门

流式输出先发给用户，无法阻止“README 复述、证据堆叠、没讲透、菜单式下一步”。

### P0-7：next step 语义错误

应从 `next_steps[]` 改为 `next_teaching_point`，最多再附一个“用户可改方向”的轻选项。

## 8. P1/P2 问题清单

### P1：工具选择缺少教学工具

保留 `search_text/read_file_excerpt`，但必须新增 teaching skeleton / anchor pack / topic card 工具。

### P1：首轮 prompt 目标太泛

“建立整体理解并主动核实一两个关键源码起点”会诱导整体概览。首轮应该是“轻地图 + 选一个最值得讲的点讲透”。

### P1：深度参数没有转换为教学策略

当前 depth 更像回答长度控制，而不是“浅层概念课/正常源码课/深入设计课”的教学动作差异。

### P1：多轮记忆按 LearningGoal 太粗

OVERVIEW/ENTRY/FLOW/MODULE 这类 goal 不足以描述具体学过什么。应该记录 `TeachingPointCoverage`。

### P2：前端展示可以更少暴露工具过程

工具活动可保留，但最终回答不应让用户感觉“老师一直在查证据”。

## 9. 为什么“更开放的 prompt”不能单独解决

可以临时把系统 prompt 改成“更像老师”，这会有改善，但不能根治。原因是：

第一，prompt 仍然拿不到教学骨架。没有 skeleton，再会讲也只能围绕文件树讲。

第二，状态更新仍会误判。没有 schema 和 parser 修复，多轮仍会断。

第三，输出 contract 仍在要求 evidence/uncertainty 同级出现，模型会回到报告格式。

第四，流式质量门缺失。只要一次模型输出差，用户立刻看到。

第五，工具层仍然奖励“找文件、搜文本、读片段”，不奖励“组织课程”。

因此最低可行改法是：prompt + contract + schema + parser + quality gate 同时改；真正完整方案还要补 M3/M4。

## 10. 应采用的核心范式

建议把当前系统从：

```text
仓库文件树 / README / 源码片段
  -> LLM 取证
  -> 可见证据分析
  -> 状态从文本中猜
```

改成：

```text
仓库文件树 / README / 源码片段
  -> RepoTeachingSkeleton（候选、证据、未知边界）
  -> TeachingTurnPlan（本轮唯一教学点）
  -> 最小必要源码锚点
  -> TeacherAnswerDraft（教学正文优先）
  -> QualityGate（内容丰富度、证据比例、next point 单一性）
  -> 可见教学回答
  -> TeachingPointCoverage 状态更新
```

这条链路能同时满足两个目标：

- 不胡说：因为 skeleton 和答案都带 evidence_refs/confidence/unknowns；
- 像老师：因为可见输出围绕一个教学点组织，而不是围绕证据组织。

## 11. 判断后端 Agent 是否修好的验收标准

修复后，拿同一个仓库第一次进入教学，合格回答应该满足：

1. 开头不是文件树 dump，而是说明“这一轮先讲一个最关键点”；
2. 只讲一个点，例如“为什么 Session/TeachingState 是系统中枢”；
3. 解释这个点在产品目标中的作用，而不只是列文件名；
4. 用 1-3 个源码锚点服务讲解；
5. 有设计意图或职责拆分解释；
6. 证据最多占回答 20%-30%，且不压倒正文；
7. 不确定性只标必要边界，不连续免责声明；
8. 结尾只有一个自然的下一教学子点；
9. 第二轮能接着上轮，不重复 README；
10. 五轮后状态能明确记录已讲过的具体教学点，而不是笼统 goal。

## 12. 最终结论

当前后端 Agent 不像老师，是因为系统仍在让它做“带教学包装的源码取证”。PRD v6 要求的是“以源码为材料的持续教学”。这需要从架构上新增/恢复教学骨架、教学轮次计划、教学语义 schema、质量门和证据压缩策略。

最重要的一句话：**不要把 evidence-first 当作安全；应该改为 teaching-first with evidence boundaries。**

这不是放松真实性，而是把真实性从“可见回答主干”移动到“候选材料、锚点、质量检查和边界标注”中。只有这样，Agent 才会主动、持续、像老师一样讲课。
