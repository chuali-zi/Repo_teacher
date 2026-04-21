# Repo Tutor 后端教学输出增强方案

> 目标：让 Agent 的回答真正像老师在带读源码，而不是“1 句结论 + 一大堆证据/免责声明 + 反复重复”。
>
> 分析基准：公开 GitHub `main` 分支的后端代码、`README.md`、`docs/PRD_v5_agent.md`。我没有在公开 `main` 分支看到 `new_docs/` 目录，所以本文按当前公开 PRD `docs/PRD_v5_agent.md` 处理；如果你本地有未推送的 `new_docs`，可以把里面的 PRD 条款替换进本文同一套方案。

---

## 0. 结论先说

当前问题不是“模型不聪明”，也不是单纯“prompt 写得不够狠”。真正的问题是后端现在缺少三个东西：

1. **教学内容规划器**：每轮回答前没有明确规定“这轮要教会什么、展开哪些知识块、证据最多占多少、如何自主拓展”。
2. **仓库教学骨架**：PRD v5 要求能稳定产出入口、分层、依赖、候选主流程、阅读路径等教学骨架；但当前 README 说明 live runtime 故意不提供 `m3/m4` 静态入口推断、教学 skeleton、repo_kb，也不暴露返回 inferred module map / reading path / teaching skeleton 的工具。
3. **回答质量闸门与反重复记忆**：现在前端展示的是模型流式吐出的 `raw_text`；解析、结构化、状态更新发生在流结束之后。即使后端事后发现“证据太多、教学太少、重复上一轮”，也来不及修正文案。

所以推荐的核心改造是：

> **把 Agent 从“证据优先的源码问答器”改成“候选教学骨架 + 教学 turn plan + 教学块回答 + 证据压缩 + 质量闸门”的老师型系统。**

一句话落地版：

> 每轮先生成 `TeachingTurnPlan`，规定本轮必须包含 `概念解释 / 仓库映射 / 代码走读 / 为什么这样设计 / 自主拓展 / 压缩证据 / 下一步`，并用质量闸门确保“教学句子 ≥ 65%，证据句子 ≤ 20%，重复度低于阈值”。

---

## 1. 当前实现和 PRD 的核心矛盾

### 1.1 PRD v5 想要什么

PRD v5 明确说，Repo Tutor 是“面向初学者的只读源码仓库教学 Agent”，要帮助用户建立最小工程认知，识别入口、模块、分层、依赖来源、候选数据流/主流程和阅读顺序，并主动引导深入。

PRD 的教学主线也不是“你问我答”，而是：

1. 先建立观察框架：入口、模块、分层、依赖、主流程分别是什么。
2. 再映射到当前仓库：这些东西在这个仓库里分别体现在哪里。
3. 再给阅读起点：先看哪里，为什么先看这里。
4. 再沿候选数据流/主流程展开。
5. 再补充模块关系与局部实现细节。

P0 还要求首轮教学报告、3–6 步阅读路径、候选数据流/主流程骨架讲解、模块关系讲解、教学式分层视图、多轮上下文保持等能力。

### 1.2 当前 README 描述的 live runtime 是什么

当前 README 说明 live backend 是保守的：只提供仓库访问、文件树索引、教学状态和安全源码读取工具，不生成静态入口、流程、分层、依赖结论给 Agent 复述。

README 还明确说当前后端不做：

- `m3` 风格的静态入口推断
- `m4` 风格的教学 skeleton 或 topic index
- 静态 `repo_kb` 查询层
- 后端编写的 “likely architecture” payload

当前工具也主要是：

- `m1.get_repository_context`
- `m2.get_file_tree_summary`
- `m2.list_relevant_files`
- `teaching.get_state_snapshot`
- `search_text`
- `read_file_excerpt`

并且 README 说 backend 不应该暴露返回 inferred entry points、module maps、reading paths、teaching skeleton facts 的工具。

### 1.3 矛盾在哪里

PRD v5 要“教学可用骨架”，当前 live runtime 则刻意不提供这类骨架。于是模型只能临场拿文件树、搜索结果和源码片段拼回答。为了不幻觉，它会过度强调“证据/不确定/候选”，但它没有稳定的“老师讲课材料”。

这就自然导致你观察到的现象：

- 结论很短，因为模型不敢多讲。
- 证据很长，因为后端和 prompt 一直强调 evidence-first。
- 教学内容少，因为没有强制教学块、没有教学比例约束。
- 回答重复，因为 memory 只知道“可能讲过某个 topic”，但不知道上次具体讲了哪个角度、哪段代码、哪个例子。
- 每次问得不一样还重复，因为 Agent 只在当前问题附近重新搜证据，没有稳定的课程进度和知识点覆盖账本。

---

## 2. 根因清单：为什么一大段话只有几句在教学

### 根因 A：系统规则是 evidence-first，不是 teaching-first

`backend/m6_response/prompt_builder.py` 当前系统规则大意是：

- 优先基于文件树、源码工具结果、当前教学状态和用户问题回答。
- 入口、流程、分层、依赖没有源码证据只能写成候选/推测/不确定。
- 可以给很轻的阅读建议。
- 每轮只展开少量核心点。

这些规则没错，但它们会把模型推向“谨慎、短、证据优先”。里面没有硬性要求：

- 至少几个教学块。
- 至少多少句真实讲解。
- 证据最多占多少。
- 必须举例或做代码走读。
- 必须自主拓展一个和当前问题相关的知识点。

所以模型安全感来自“多贴证据、少讲推断”，这就是废话堆证据的直接原因。

### 根因 B：follow-up 的 JSON schema 只强制了 `next_steps`

`prompt_builder.py` 里 `_json_schema_for_scenario()` 对首轮报告有比较完整的 `initial_report_content` schema；但是对普通 follow-up，只要求：

```json
{
  "next_steps": [
    {
      "suggestion_id": "sug_1",
      "text": "下一步建议",
      "target_goal": "overview|structure|entry|flow|module|dependency|layer|summary|null"
    }
  ]
}
```

也就是说，模型在普通问答里并没有被机器侧 schema 强制输出：

- `focus`
- `direct_explanation`
- `relation_to_overall`
- `teaching_blocks`
- `evidence_summary`
- `uncertainties`
- `autonomous_expansion`
- `used_evidence_refs`
- `related_topic_refs`
- `coverage_updates`

可见文本虽然要求“自然覆盖本轮重点、直接解释、与整体关系、证据、不确定项、下一步建议”，但结构化侧没有强制。结果是：后端很难知道这轮到底教了什么，也很难稳定更新“已讲过什么”。

### 根因 C：Parser 的 fallback 会让状态更新失真

`backend/m6_response/response_parser.py` 当前 follow-up 解析逻辑是：如果 payload 缺字段，就从可见文本里按标题抓；如果还抓不到，`direct_explanation` 会退化成整段 visible text，`evidence_lines` 会退化成第一行。

这会造成两个问题：

1. **状态以为有 evidence，实际只是第一句话。**
2. **状态以为 direct_explanation 是整段话，实际里面可能大部分是证据、不确定项、下一步。**

这会让后续的 `record_explained_items()`、`update_teaching_state_after_answer()` 得到很弱的信号。它不知道“讲过 FastAPI app 初始化”、“讲过 SSE 事件流”、“讲过 tool loop 的控制结构”，只知道“某个 learning goal 下回答过”。于是反重复能力天然弱。

### 根因 D：初始 teaching plan 太轻，只来自文件树

`backend/m5_session/teaching_state.py` 的 `build_initial_teaching_plan()` 当前只生成 3 个泛化步骤：

1. 建立仓库整体地图。
2. 核实第一个源码起点。
3. 沿用户关心的问题继续深挖。

并且 `generated_from_skeleton_id="m2_file_tree_only"`。

这不是 PRD v5 需要的“教学骨架”。它没有：

- 入口候选集合
- 候选主流程
- 教学式分层
- 模块关系
- 依赖来源
- 3–6 步阅读路径
- topic index
- 每个候选结论的 evidence/confidence/unknown

所以 Agent 每一轮都像临时翻书回答，而不是老师按课程地图带你走。

### 根因 E：TeachingDirective 只给“少量点 + 证据锚定”，没有“讲课结构”

`build_teaching_directive()` 当前默认：

- `allowed_new_points = 2`，阶段总结为 1。
- `must_anchor_to_evidence = True`。
- 不要重复。
- 先回答问题，然后最多加一句 bridge。

这适合“保守回答”，不适合“教学”。因为一轮真正像老师讲东西，通常至少需要：

- 先解释概念。
- 再映射到仓库。
- 再走一小段代码。
- 再解释为什么这么设计。
- 再指出一个常见误区或下一步拓展。

`allowed_new_points=2` 会让模型主动压缩教学内容。证据又被强调，最后就变成“2 个短教学点 + 很多证明/限制”。

### 根因 F：OutputContract 把“证据”当成和“讲解”同级大段落，但没有比例控制

`TeachingService.output_contract()` 当前 required sections 是：

- FOCUS
- DIRECT_EXPLANATION
- RELATION_TO_OVERALL
- EVIDENCE
- UNCERTAINTY
- NEXT_STEPS

问题不是有证据，而是没有控制证据体积。模型看到 `EVIDENCE` 是 required section，很容易把证据写成一个大区块。更糟糕的是，没有任何规则说：

- 证据最多 3 条。
- 证据只做压缩摘要。
- 不要在证据区重复讲解。
- 教学解释必须占主体。

于是 evidence section 会变成“看起来严谨，其实对初学者没有教学价值”的垃圾桶。

### 根因 G：工具层没有“教学材料工具”

`backend/agent_runtime/tool_selection.py` 只给模型选这些工具：

- `m2.list_relevant_files`
- `search_text`
- `read_file_excerpt`

`context_budget.py` seed 的也是 repo context、file tree summary、relevant files、teaching state snapshot，必要时只塞 1 个 starter excerpt。

这能帮模型找证据，但不能帮模型组织课程。模型拿到的是“可验证材料”，不是“讲课材料”。

### 根因 H：Deep Research 初报有材料，但没有进入 follow-up 教学骨架

`backend/deep_research/pipeline.py` 其实已经做了一些有用的事情：

- 选择 relevant source/config/doc files。
- 按 group 生成 notes。
- 合成 repository verdict、reading framework、module map、entry/startup、core flows、dependencies 等 synthesis notes。
- 构造 `InitialReportAnswer`。

但它现在主要服务于 initial report，并且 raw_text 是英文 deep research report 风格，不是持续中文教学风格。follow-up 仍回到保守工具循环，没有把这些 notes 持久化为 `TeachingSkeleton` / topic index / lesson memory。

这很可惜，因为这里已经有“候选教学骨架”的雏形。

### 根因 I：流式输出发生在质量校验之前

`backend/m5_session/chat_workflow.py` 当前逻辑是：

1. 开始 answer stream。
2. 每收到一个 visible chunk 就通过 SSE 发给前端。
3. stream 完成后再 `parse_answer()`。
4. 再 `record_explained_items()`、`update_teaching_state_after_answer()`。

所以如果模型前半段已经输出了一堆证据废话，后端没有机会拦住它。除非改成“先缓存/评分/必要时重写，再流式发送最终答案”。

---

## 3. 目标形态：什么才叫“像老师在讲”

建议把每轮回答拆成 7 个教学块，但不要机械套模板；结构可以自然，但内部必须满足这些功能。

| 块 | 作用 | 用户感受 |
|---|---|---|
| 本轮重点 | 明确这轮要学会什么 | “我知道这轮不是泛泛而谈” |
| 概念解释 | 先把陌生工程概念讲清楚 | “我懂这个词/机制是什么了” |
| 仓库映射 | 把概念放到当前仓库路径/模块里 | “我知道它在这个仓库哪儿体现” |
| 代码走读 | 带读 1 段关键代码或调用关系 | “我真的读进源码了” |
| 为什么这样设计 | 解释设计动机、工程取舍、常见模式 | “我知道为什么不是只知道是什么” |
| 自主拓展 | 主动补一个有价值的相关点 | “老师顺手告诉我下一层知识” |
| 压缩证据与不确定项 | 只列必要依据，不抢戏 | “可信，但不烦” |

推荐比例：

```text
教学讲解 >= 65%
仓库/代码映射 >= 20%
证据 <= 20%
不确定项 <= 10%
下一步 <= 5%
```

这里的“教学讲解”不是泛泛总结，而是：解释概念、拆流程、讲为什么、指出误区、用代码路径串起来。

---

## 4. 总体架构改造

建议新增/改造这 5 层：

```text
M1 仓库访问
  ↓
M2 文件树扫描
  ↓
M3 Teaching Skeleton Builder          ← 新增/恢复：候选教学骨架，不是确定事实
  ↓
M5 Teaching State + Turn Planner      ← 增强：每轮生成 TeachingTurnPlan
  ↓
M6 Teacher Answer Generator           ← 增强：教学块输出 + 证据压缩 + 质量闸门
  ↓
Frontend raw_text                     ← 最终只展示过闸门的教学回答
```

关键原则：

> 后端可以产出“候选教学骨架”，但必须标注 confidence、evidence_refs、unknown_items，不能把静态推断伪装成真实运行事实。

这既满足 PRD v5 的教学骨架要求，又不会违背“只读、证据标注、不硬猜”的安全原则。

如果 README 仍然作为 live runtime 的 source of truth，那就需要修改 README 的策略表述：

```text
旧：backend should not expose tools that return inferred entry points, module maps, reading paths, or teaching skeleton facts.

新：backend may expose candidate teaching skeleton tools when every item carries confidence, evidence_refs, unknowns, and candidate wording. They are teaching scaffolds, not verified runtime facts.
```

---

## 5. 具体改造一：补上 RepositoryTeachingSkeleton

### 5.1 复用已有 contract，不要从零造

`backend/contracts/domain.py` 已经有很接近 PRD 的模型：

- `AnalysisBundle`
- `TeachingSkeleton`
- `OverviewSection`
- `EntrySection`
- `FlowSection`
- `LayerSection`
- `DependencySection`
- `TopicIndex`

但当前 live runtime 没有真正把它们作为 follow-up 教学依据。

建议新增模块：

```text
backend/m3_teaching_skeleton/
  __init__.py
  builder.py
  heuristics.py
  evidence_compactor.py
  topic_indexer.py
  models.py        # 如不想改 contracts，可先内部模型
```

### 5.2 Skeleton 最低字段

`RepositoryTeachingSkeleton` 至少包含：

```python
class RepositoryTeachingSkeleton(ContractModel):
    skeleton_id: str
    repo_id: str
    generated_at: datetime
    mode: Literal["quick", "deep", "degraded"]

    overview: OverviewSection
    key_directories: list[KeyDirectoryItem]
    entry_section: EntrySection
    flow_section: FlowSection
    layer_section: LayerSection
    dependency_section: DependencySection
    reading_path_preview: list[ReadingStep]
    module_cards: list[ModuleTeachingCard]
    topic_index: TopicIndex
    evidence_catalog: list[EvidenceRef]
    unknown_items: list[UnknownItem]
```

新增 `ModuleTeachingCard`：

```python
class ModuleTeachingCard(ContractModel):
    module_id: str
    title: str
    paths: list[str]
    likely_role: str
    layer_hint: str | None = None
    main_path_role: MainPathRole
    upstream_refs: list[str] = []
    downstream_refs: list[str] = []
    teach_first_reason: str | None = None
    evidence_refs: list[str] = []
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    unknowns: list[str] = []
```

### 5.3 Skeleton 怎么生成

第一版不需要完整符号级调用图，可以用启发式 + 证据标注：

1. **从文件树识别 key directories**
   - `backend/`, `web/`, `routes/`, `contracts/`, `m*_xxx/`, `tests/`, `docs/` 等。
   - 根据路径命名、文件数量、源码密度、README 提及情况打分。

2. **从入口候选识别 start files**
   - Python：`main.py`, `app.py`, `__main__.py`, `manage.py`, `pyproject.toml` scripts。
   - Web：`index.html`, `main.js`, `app.js`, package scripts。
   - 只输出“候选入口”，不说“真实运行入口”。

3. **从 import 关系粗分 internal / stdlib / third-party / unknown**
   - 不做完整依赖解析也可以。
   - 先取 top-level imports，结合本仓库顶层包名判断 internal。

4. **生成教学式分层**
   - 入口层：`main.py`, API bootstrap, web index。
   - 路由/控制层：`routes/`。
   - 会话/编排层：`m5_session/`, `agent_runtime/`。
   - 响应生成层：`m6_response/`。
   - 工具/源码读取层：`agent_tools/`, `m1_repo_access/`, `m2_file_tree/`。
   - 契约层：`contracts/`。
   - 安全层：`security/`。

5. **候选主流程**
   - 从 README 当前 flow 和路径命名生成：`POST /api/repo -> M1 -> M2 -> M5 -> M6 -> tools -> SSE/message`。
   - 每个节点挂 evidence_refs。

6. **阅读路径**
   - 3–6 步：先 README/current runtime，再 `backend/main.py`，再 routes，再 m5 session，再 m6 response/tool loop，再 contracts。

### 5.4 Deep Research 要沉淀成 skeleton，不只写初报

当前 `deep_research/pipeline.py` 的 `SynthesisNote` 已经包含：

- repository_verdict
- reading_framework
- module_map
- entry_and_startup
- core_flows
- key_abstractions
- dependencies_and_config
- open_questions

建议新增：

```python
def build_teaching_skeleton_from_research(...):
    return RepositoryTeachingSkeleton(...)
```

然后把 skeleton 存入 session：

```python
session.analysis_bundle = analysis_bundle
session.teaching_skeleton = skeleton
session.conversation.teaching_plan_state = build_teaching_plan_from_skeleton(skeleton)
```

这样 follow-up 才能延续首轮理解，而不是每轮重新靠文件树和 search_text 拼。

---

## 6. 具体改造二：每轮先生成 TeachingTurnPlan

新增 `TeachingTurnPlanner`，放在 `backend/m5_session/turn_planner.py`。

### 6.1 输入

```python
class TeachingTurnPlannerInput(ContractModel):
    user_text: str
    scenario: PromptScenario
    learning_goal: LearningGoal
    depth_level: DepthLevel
    skeleton: RepositoryTeachingSkeleton | None
    conversation_state: ConversationState
    coverage_ledger: LessonCoverageLedger
    recent_messages_summary: SemanticHistorySummary
```

### 6.2 输出

```python
class TeachingTurnPlan(ContractModel):
    plan_id: str
    turn_goal: str
    user_intent: Literal["ask_entry", "ask_flow", "ask_module", "ask_why", "ask_deeper", "recap", "other"]
    answer_mode: Literal["teach", "walkthrough", "compare", "recap", "debug_reading"]

    must_teach_points: list[str]
    code_walkthrough_targets: list[str]
    repo_paths_to_anchor: list[str]
    autonomous_expansion: str | None
    avoid_repeating: list[str]
    new_angle_if_repeated: str | None

    evidence_refs_to_use: list[str]
    max_evidence_items: int = 3
    min_teaching_blocks: int = 3
    target_teaching_ratio: float = 0.65
    max_evidence_ratio: float = 0.20

    required_visible_sections: list[str]
```

### 6.3 计划器要解决的问题

用户问“入口在哪”时，plan 不是只说“入口候选是 X”，而是规定：

```text
本轮要教会：什么叫工程入口；为什么 backend/main.py 像入口；入口如何连接 routes/app；为什么仍叫候选；下一步读哪里。
代码走读目标：backend/main.py, backend/routes/...
自主拓展：入口不等于所有业务逻辑，入口通常只是装配层。
证据最多：3 条。
避免重复：不要重复上轮已经讲过的 README 当前 flow。
```

用户问“讲深一点”时，plan 应该识别这是重复/加深意图：

```text
不要重讲仓库概览。
换成代码走读角度：从请求进入 /api/chat 到 tool loop 和 SSE 输出。
新增一个工程概念：编排层和生成层分离。
```

### 6.4 TeachingService 接入点

在 `TeachingService.build_prompt_input()` 中，在 `prepare_teaching_decision()` 后、构造 `PromptBuildInput` 前加：

```python
turn_plan = self.turn_planner.build(
    session=session,
    user_text=user_text,
    scenario=scenario,
    goal=goal,
    depth=depth,
)

session.conversation.current_teaching_turn_plan = turn_plan
```

然后把 `turn_plan` 放进 prompt payload，而不是只放 `teaching_directive`。

---

## 7. 具体改造三：扩展结构化内容 schema

### 7.1 新增 TeachingBlock

在 `backend/contracts/domain.py` 里给 follow-up answer 加教学块。

```python
class TeachingBlock(ContractModel):
    block_id: str
    block_type: Literal[
        "concept_explanation",
        "repo_mapping",
        "code_walkthrough",
        "design_reason",
        "common_misunderstanding",
        "autonomous_expansion",
        "mini_exercise",
    ]
    title: str
    content: str
    repo_paths: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel | None = None
```

改造 `StructuredMessageContent`：

```python
class StructuredMessageContent(ContractModel):
    focus: str | None = None
    direct_explanation: str | None = None
    teaching_blocks: list[TeachingBlock] = Field(default_factory=list)
    relation_to_overall: str | None = None
    evidence_summary: list[EvidenceLine] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    autonomous_expansion: TeachingBlock | None = None
    coverage_updates: list[TeachingAtomRef] = Field(default_factory=list)
    next_steps: list[Suggestion] = Field(default_factory=list)
```

### 7.2 Follow-up JSON schema 必须完整

把 `prompt_builder.py` 的 follow-up schema 从“只要 next_steps”改成下面这种：

```python
def _json_schema_for_scenario(scenario: PromptScenario) -> str:
    if scenario == PromptScenario.INITIAL_REPORT:
        # 顺便修复 status：confirmed -> formed
        return """
        {
          "initial_report_content": {
            "overview": {"summary": "一句话概览", "confidence": "high|medium|low|unknown", "evidence_refs": []},
            "focus_points": [],
            "repo_mapping": [],
            "language_and_type": {"primary_language": "Python", "project_types": [], "degradation_notice": null},
            "key_directories": [],
            "entry_section": {"status": "formed|heuristic|unknown", "entries": [], "fallback_advice": null},
            "flow_section": {"status": "formed|heuristic|unknown", "flows": [], "fallback_advice": null},
            "layer_section": {"status": "formed|heuristic|unknown", "layers": [], "fallback_advice": null},
            "dependency_section": {"items": [], "unknown_count": 0, "summary": null},
            "recommended_first_step": {"target": "先看哪里", "reason": "为什么", "learning_gain": "学到什么", "evidence_refs": []},
            "reading_path_preview": [],
            "unknown_section": [],
            "suggested_next_questions": []
          },
          "used_evidence_refs": [],
          "warnings": [],
          "suggestions": []
        }
        """

    return """
    {
      "focus": "本轮真正要教会用户的点",
      "direct_explanation": "先直接回答用户问题，不能只给一句结论",
      "teaching_blocks": [
        {
          "block_id": "tb_1",
          "block_type": "concept_explanation|repo_mapping|code_walkthrough|design_reason|common_misunderstanding|autonomous_expansion|mini_exercise",
          "title": "教学块标题",
          "content": "教学内容，必须是解释，不是证据堆砌",
          "repo_paths": [],
          "evidence_refs": [],
          "confidence": "high|medium|low|unknown"
        }
      ],
      "relation_to_overall": "这件事放回整个仓库/主流程中是什么位置",
      "evidence_summary": [
        {"text": "最多 3 条压缩依据", "evidence_refs": [], "confidence": "high|medium|low|unknown"}
      ],
      "uncertainties": [],
      "autonomous_expansion": {
        "block_id": "tb_expansion",
        "block_type": "autonomous_expansion",
        "title": "顺手拓展",
        "content": "一个和当前问题强相关的扩展点",
        "repo_paths": [],
        "evidence_refs": [],
        "confidence": "medium"
      },
      "coverage_updates": [
        {"concept_id": "entry.fastapi_app", "repo_anchor": "backend/main.py", "depth": "shallow|normal|deep", "angle": "concept|walkthrough|design"}
      ],
      "used_evidence_refs": [],
      "related_topic_refs": [],
      "next_steps": []
    }
    """
```

注意：当前 initial report schema 里的 `entry_section.status` 使用了 `confirmed|heuristic|unknown`，但 `DerivedStatus` 里是 `formed|heuristic|unknown`。建议修掉，否则 parser/model_validate 容易把 confirmed 降级或解析异常。

---

## 8. 具体改造四：把 prompt 改成“教学优先”

### 8.1 替换系统规则重点

当前规则强调 evidence-first。建议改成：

```text
你是 Repo Tutor，一个带初学者读源码的老师。

最高优先级：让用户真的学会，而不是展示你查了多少证据。

每轮回答必须遵守：
1. 先直接回答用户问题，但不能只给一句结论。
2. 主体必须是教学讲解：解释概念、映射到当前仓库、走读关键代码、说明为什么这样设计。
3. 证据只用于支撑教学，不允许成为主体。证据区最多 3 条，每条只写“路径/线索 -> 支持什么判断”。
4. 如果信息不足，明确候选/不确定，但仍要给用户一个可学习的观察框架和下一步验证方法。
5. 每轮必须自主拓展 1 个和当前问题强相关的知识点；不能泛泛说“你可以继续看”。
6. 不要重复上一轮已讲过的角度；如果用户追问同一主题，换成更深的代码走读、设计原因、对比或常见误区。
7. 可见回答中不要展示内部教学状态、turn_plan 或 JSON。
```

### 8.2 增加比例约束

在 `_strict_output_requirements()` 里加入：

```text
Visible answer quality budget:
- Teaching explanation must be at least 65% of the visible answer.
- Evidence / 判断依据 must be at most 20% unless the user explicitly asks for evidence only.
- Uncertainty must be concise and actionable, at most 10%.
- Do not put most content into evidence, caveats, or next steps.
- At least one teaching block must map an abstract idea to concrete repo paths.
- If the user asks about source/flow/module/entry, include a small code walkthrough.
```

### 8.3 推荐可见回答模板

不要用“证据”当大标题放前面。建议默认结构：

```markdown
## 本轮重点
这轮我们要搞清楚：……

## 先把概念讲清楚
……

## 放到这个仓库里看
……

## 顺着代码走一小段
……

## 为什么这样设计
……

## 顺手拓展一个关键点
……

## 证据与不确定项
- `path/to/file`: 支持……
- `path/to/file`: 支持……
- 还不能确定：……

## 下一步
1. ……
```

如果用户问得很短，也可以缩短，但不能压缩成“结论 + 证据”。

---

## 9. 具体改造五：证据压缩器

新增 `backend/m6_response/evidence_compactor.py`。

目的：把 tool results、skeleton evidence、read_file_excerpt 压成“可教学的依据”，而不是把原始证据塞给模型后任由它大段复述。

```python
class CompactEvidence(ContractModel):
    evidence_id: str
    path: str
    signal_type: Literal["readme_flow", "entry_file", "import", "route", "class", "function", "config", "tree"]
    supports: str
    confidence: ConfidenceLevel
    quote_or_excerpt: str | None = None  # 最多 1-2 行
```

压缩规则：

```python
MAX_EVIDENCE_ITEMS = 3
MAX_EVIDENCE_TEXT_CHARS = 500
```

给模型的不是大段文件内容，而是：

```json
{
  "compact_evidence": [
    {
      "path": "backend/main.py",
      "signal_type": "entry_file",
      "supports": "它创建 FastAPI app 并挂载 routes，因此可作为后端入口候选。",
      "confidence": "medium"
    }
  ]
}
```

这样模型会把证据当材料，而不是把证据本身当回答。

---

## 10. 具体改造六：反重复账本 LessonCoverageLedger

当前 `explained_items` 太粗，建议新增语义级账本。

```python
class LessonCoverageItem(ContractModel):
    concept_id: str                 # entry.fastapi_app / flow.chat_sse / module.m5_session
    title: str
    repo_anchor: str | None         # backend/main.py
    angle: Literal["concept", "repo_mapping", "walkthrough", "design", "pitfall", "recap"]
    depth: DepthLevel
    message_id: str
    explanation_hash: str
    taught_at: datetime
```

```python
class LessonCoverageLedger(ContractModel):
    items: list[LessonCoverageItem] = []

    def has_recently_taught(self, concept_id: str, angle: str | None = None) -> bool: ...
    def suggest_new_angle(self, concept_id: str) -> str: ...
```

### 10.1 如何识别重复

模型每轮 sidecar 必须给：

```json
"coverage_updates": [
  {
    "concept_id": "flow.chat_sse",
    "repo_anchor": "backend/m5_session/chat_workflow.py",
    "depth": "normal",
    "angle": "walkthrough"
  }
]
```

如果用户下轮又问“那 chat 是怎么返回的”，planner 看到 `flow.chat_sse` 已经以 `walkthrough` 讲过，就换角度：

```text
上次讲过“从 workflow 到 SSE 的走法”。
这次不要重讲路径，改讲“为什么解析/状态更新放在流结束后，以及这对质量闸门的影响”。
```

### 10.2 Prompt 中明确禁止重复

`turn_plan.avoid_repeating` 进入 prompt：

```text
Do not repeat these already-taught angles:
- concept_id=flow.chat_sse, angle=walkthrough, anchor=backend/m5_session/chat_workflow.py

If the user asks about the same concept again, use this new angle:
- design_reason: explain why current streaming makes post-hoc repair impossible, then propose buffered streaming.
```

---

## 11. 具体改造七：质量闸门 QualityGate

### 11.1 为什么必须改 streaming

当前回答边生成边发给前端，后端没有机会在用户看到前修正。要做质量闸门，有两个方案：

**方案 A：缓存最终回答，再流式发送最终版。**

- 工具调用活动照常流式显示。
- 模型正文先缓存。
- 跑 parser + quality gate。
- 不合格就让模型重写或用 deterministic rewrite prompt 修复。
- 最后把合格正文按 chunk 发给前端。

优点：质量最好。缺点：首字等待时间变长。

**方案 B：两阶段流式。**

- 第一阶段只显示活动状态：正在定位源码、正在组织讲解。
- 第二阶段输出过闸门的最终教学回答。

不建议继续“边生成正文边发”，否则无法保证教学质量。

### 11.2 评分指标

新增 `backend/m6_response/quality_gate.py`：

```python
class AnswerQualityScore(ContractModel):
    teaching_sentence_ratio: float
    evidence_sentence_ratio: float
    uncertainty_sentence_ratio: float
    repo_anchor_count: int
    teaching_block_count: int
    autonomous_expansion_present: bool
    repeated_similarity: float
    next_steps_count: int
    passed: bool
    reasons: list[str]
```

基本阈值：

```python
MIN_TEACHING_RATIO = 0.65
MAX_EVIDENCE_RATIO = 0.20
MAX_UNCERTAINTY_RATIO = 0.10
MIN_TEACHING_BLOCKS = 3
MAX_EVIDENCE_ITEMS = 3
MAX_REPEAT_SIMILARITY = 0.35
```

### 11.3 简化 scoring 逻辑

```python
def score_answer(visible_text: str, structured: StructuredMessageContent, ledger: LessonCoverageLedger) -> AnswerQualityScore:
    sections = split_visible_sections(visible_text)
    sentences = split_cn_sentences(visible_text)

    evidence_sentences = sentences_in_sections(sections, names=["证据", "依据", "不确定项"])
    next_step_sentences = sentences_in_sections(sections, names=["下一步"])
    teaching_sentences = [
        s for s in sentences
        if s not in evidence_sentences
        and s not in next_step_sentences
        and not looks_like_disclaimer(s)
    ]

    return AnswerQualityScore(
        teaching_sentence_ratio=len(teaching_sentences) / max(len(sentences), 1),
        evidence_sentence_ratio=len(evidence_sentences) / max(len(sentences), 1),
        uncertainty_sentence_ratio=count_uncertainty(sentences) / max(len(sentences), 1),
        repo_anchor_count=count_repo_paths(visible_text),
        teaching_block_count=len(structured.teaching_blocks),
        autonomous_expansion_present=structured.autonomous_expansion is not None,
        repeated_similarity=max_similarity_against_recent(visible_text, ledger),
        next_steps_count=len(structured.next_steps),
        passed=..., 
        reasons=[]
    )
```

### 11.4 自动修复 prompt

如果失败，不直接返回，而是用 repair prompt：

```text
你的初稿没有通过 Repo Tutor 教学质量闸门。
失败原因：
- 教学讲解比例太低：{teaching_ratio}
- 证据比例太高：{evidence_ratio}
- 缺少代码走读 / 自主拓展 / 与整体关系

请保留事实结论和 evidence_refs，但重写可见回答：
1. 教学讲解 >= 65%。
2. 证据最多 3 条，合并到“证据与不确定项”。
3. 增加一个“顺着代码走一小段”块。
4. 增加一个强相关自主拓展。
5. 不要重复这些已讲角度：{avoid_repeating}。
6. 输出同样的 JSON sidecar。
```

最多 repair 1 次，避免成本爆炸。

---

## 12. 具体改造八：让 OutputContract 真正约束教学

当前 `OutputContract` 只有 required sections、max_core_points、must_include_next_steps、must_mark_uncertainty、must_use_candidate_wording。

建议扩展：

```python
class OutputContract(ContractModel):
    required_sections: list[MessageSection]
    max_core_points: int
    must_include_next_steps: bool
    must_mark_uncertainty: bool
    must_use_candidate_wording: bool

    min_teaching_blocks: int = 3
    must_include_code_walkthrough: bool = False
    must_include_autonomous_expansion: bool = True
    max_evidence_items: int = 3
    target_teaching_ratio: float = 0.65
    max_evidence_ratio: float = 0.20
    max_uncertainty_ratio: float = 0.10
```

`TeachingService.output_contract()` 改成：

```python
def output_contract(self, depth: DepthLevel, goal: LearningGoal | None = None) -> OutputContract:
    source_or_flow_goal = goal in {
        LearningGoal.ENTRY,
        LearningGoal.FLOW,
        LearningGoal.MODULE,
        LearningGoal.DEPENDENCY,
        LearningGoal.LAYER,
    }
    return OutputContract(
        required_sections=[...],
        max_core_points=4 if depth == DepthLevel.SHALLOW else 6,
        must_include_next_steps=True,
        must_mark_uncertainty=True,
        must_use_candidate_wording=True,
        min_teaching_blocks=3 if depth == DepthLevel.SHALLOW else 4,
        must_include_code_walkthrough=source_or_flow_goal,
        must_include_autonomous_expansion=True,
        max_evidence_items=3,
        target_teaching_ratio=0.65,
        max_evidence_ratio=0.20,
    )
```

`allowed_new_points` 不建议继续默认为 2。可以改成：

```python
allowed_new_points = 3 if conversation.depth_level == DepthLevel.SHALLOW else 4
```

注意：`allowed_new_points` 控制“新知识点”，不应该控制“教学句子数”。一个知识点可以讲 4–6 句。

---

## 13. 具体改造九：语义历史摘要，不要只截最近文本

当前 `TeachingService.summarize_recent_messages()` 是把最近 10 条消息 raw_text 截断拼接。这种摘要对反重复帮助很小。

建议改成结构化语义摘要：

```python
class SemanticHistorySummary(ContractModel):
    current_repo: str
    current_goal: LearningGoal
    concepts_taught: list[LessonCoverageItem]
    files_walked: list[str]
    flows_touched: list[str]
    unresolved_unknowns: list[str]
    last_user_intent: str | None
    last_suggestions: list[str]
    avoid_repeating_now: list[str]
```

可见 prompt 中传给模型的是：

```text
已讲过：
- backend/main.py 作为候选入口：讲过概念角度，未做逐行走读。
- /api/chat -> ChatWorkflow -> stream_answer_text_with_tools：讲过路径角度。

本轮不要重复：
- 不要再次从“这个仓库是 backend + web”开始。
- 不要再次解释什么是只读 Agent。

可以加深：
- 解释为什么 parse_answer 在 stream 后会影响质量控制。
```

这样模型才知道怎样“换角度讲深”。

---

## 14. 具体改造十：自主拓展策略

“自主拓展”不是让模型随便发散。建议规则是：

```text
每轮必须拓展 1 个点，但只能从下面选一个：
1. 工程概念：解释一个初学者很容易错过的概念。
2. 当前仓库下一层：指出一个与当前问题直接相连的源码点。
3. 常见误区：说明读这种代码时容易误判什么。
4. 对比理解：把当前模块和相邻模块的职责区分开。

禁止：
- 泛泛说“你可以继续阅读更多文件”。
- 引入和当前仓库无关的大知识。
- 一次拓展多个点。
```

例子：

用户问：“入口在哪里？”

不好的拓展：

```text
你还可以继续学习 FastAPI、Python、后端架构等知识。
```

好的拓展：

```text
顺手补一个读工程时很重要的点：入口文件通常不是“业务最多的文件”，而是“把应用对象、路由、配置装配起来的文件”。所以读入口时不要期待它解释所有业务，应该看它把请求转交给了哪些 routes / services。
```

---

## 15. 关键文件级修改建议

### 15.1 `backend/m6_response/prompt_builder.py`

要改：

1. `_SYSTEM_RULES`：从 evidence-first 改为 teaching-first with evidence cap。
2. `_strict_output_requirements()`：加入比例约束、教学块、证据上限、自主拓展。
3. `_json_schema_for_scenario()`：follow-up 返回完整 schema。
4. initial report schema 修正：`confirmed` -> `formed`。
5. `_build_payload()`：加入 `turn_plan`、`teaching_skeleton_summary`、`coverage_ledger_summary`、`compact_evidence`。

### 15.2 `backend/contracts/domain.py`

要加：

- `TeachingBlock`
- `TeachingTurnPlan`
- `TeachingAtomRef`
- `LessonCoverageItem`
- `LessonCoverageLedger`
- `SemanticHistorySummary`
- 扩展 `StructuredMessageContent`
- 扩展 `OutputContract`
- 最好让 `InitialReportContent` 补上 `flow_section`、`layer_section`、`dependency_section`，否则它不满足 PRD v5 P0。

### 15.3 `backend/m5_session/teaching_state.py`

要改：

1. `build_initial_teaching_plan()` 从 skeleton 生成 3–6 步阅读路径，不要只基于 file tree。
2. `build_teaching_directive()` 的 `allowed_new_points` 改为 3–4。
3. 新增 `coverage_ledger` 更新逻辑。
4. `record_explained_items()` 不只记录 topic，也记录 concept_id、repo_anchor、angle、depth。
5. `_answer_is_too_uncertain()` 不要只看 evidence refs，要结合质量分数。

### 15.4 `backend/m5_session/teaching_service.py`

要改：

1. `build_prompt_input()` 里生成 `TeachingTurnPlan`。
2. `history_summary()` 改成语义历史摘要。
3. `output_contract()` 接收 `goal`，动态判断是否必须 code walkthrough。
4. `ensure_answer_suggestions()` 继续限制 1–3 条，但建议下一步必须“可执行/可追问/非泛泛”。

### 15.5 `backend/agent_runtime/context_budget.py`

要改：

1. Seed 不只放 file tree 和 relevant files，还要放 `teaching_skeleton_summary`。
2. 对 follow-up，根据 `turn_plan.repo_paths_to_anchor` 优先放相关 excerpts。
3. 对证据使用 `compact_evidence`，不要把大段原始 tool result 原封不动塞进 prompt。

### 15.6 `backend/agent_runtime/tool_selection.py`

当前最多暴露 5 个工具没问题，但工具类型需要扩展：

```text
teaching.get_skeleton
teaching.get_topic_index
analysis.get_candidate_flow
analysis.get_layer_view
analysis.get_dependency_summary
analysis.get_reading_path
```

这些工具返回的是候选教学材料，不是 verified runtime truth。每个 item 必须有：

```text
confidence
candidate_wording
evidence_refs
unknowns
```

### 15.7 `backend/m6_response/response_parser.py`

要改：

1. 解析 `teaching_blocks`、`evidence_summary`、`autonomous_expansion`、`coverage_updates`。
2. fallback 不要再把第一行当 evidence。
3. 如果 sidecar 缺失关键教学字段，标记 quality failure，而不是默默 fallback。
4. 解析标题时支持新的可见结构：`先把概念讲清楚`、`放到这个仓库里看`、`顺着代码走一小段`、`顺手拓展`。

### 15.8 `backend/m5_session/chat_workflow.py` 和 `analysis_workflow.py`

要改 streaming：

1. Tool activity 继续流式输出。
2. 正文先缓存。
3. parse + quality gate。
4. repair 一次。
5. 再发送最终 visible chunks。

否则质量闸门永远只能“事后记录”，不能改变用户看到的答案。

### 15.9 `backend/deep_research/pipeline.py`

要改：

1. 新增 `build_teaching_skeleton_from_research()`。
2. synthesis notes 不只渲染成英文 report，还要变成 session 可复用的 skeleton。
3. raw_text 改成中文教学报告，或者至少经过 TeacherAnswerComposer 重写。
4. follow-up 能访问 deep research 的 group_notes / synthesis_notes。

---

## 16. 建议的回答生成链路

改造后的 follow-up 链路：

```text
用户问题
  ↓
TeachingService.infer_goal/depth/scenario
  ↓
TeachingTurnPlanner.build()
  ↓
ContextBudget 根据 turn_plan 取 skeleton + compact evidence + excerpts
  ↓
PromptBuilder 构造 teaching-first prompt
  ↓
LLM 生成 draft + sidecar
  ↓
ResponseParser 结构化解析
  ↓
QualityGate 评分
  ↓
不合格：RepairPrompt 重写一次
  ↓
合格：流式发送最终 raw_text
  ↓
CoverageLedger 更新“讲过什么、什么角度、什么深度”
```

这条链路的核心是：**让模型先拿到“我要怎么教”的 plan，再开始说话。**

---

## 17. 最小可行改法：一天内能先救效果

如果你想先快速看到效果，不想马上大改架构，可以按这个顺序改。

### Step 1：改 prompt 和 schema

改 `prompt_builder.py`：

- follow-up schema 补完整。
- 加教学比例约束。
- 证据最多 3 条。
- 必须自主拓展 1 个点。
- 必须有代码走读块。
- 修正 `confirmed` -> `formed`。

这一步会立刻减少“证据区巨大、教学区很短”。

### Step 2：改 OutputContract

把 `max_core_points` 从“压缩教学”改成“控制主题数量，不限制解释句子”。

```python
max_core_points=4
min_teaching_blocks=3
max_evidence_items=3
must_include_autonomous_expansion=True
```

### Step 3：改 parser fallback

`_fallback_evidence_lines()` 不要用第一行当 evidence：

```python
def _fallback_evidence_lines(text: str) -> list[EvidenceLine]:
    return []
```

如果需要 evidence，但没有 evidence，让 quality gate fail，而不是伪造 evidence。

### Step 4：先做轻量 QualityGate，不改 skeleton

即使没有 M3 skeleton，也能先做一个文本质量检查：

- 教学句子少于 60% -> repair。
- 证据 bullets 超过 3 -> repair。
- 没有仓库路径 -> repair。
- 没有自主拓展 -> repair。

### Step 5：暂时缓存正文再发

先牺牲一点首字速度，换明显质量提升。

---

## 18. 中期改法：真正符合 PRD v5

中期必须补 skeleton，否则只是 prompt 急救。

### 阶段 1：Skeleton Builder

从 file tree + README + config + imports + deep_research notes 生成：

- overview
- key directories
- entry candidates
- import classification summary
- module cards
- layer view
- candidate flow
- reading path
- topic index
- unknowns

### 阶段 2：Skeleton Tools

暴露只读候选工具：

- `teaching.get_skeleton`
- `analysis.get_candidate_flow`
- `analysis.get_layer_view`
- `analysis.get_reading_path`

### 阶段 3：Turn Planner

每轮生成 `TeachingTurnPlan`。

### 阶段 4：Quality Gate + Repair

上线真实拦截。

### 阶段 5：Golden Tests

用真实仓库跑固定问题集，比较教学质量指标。

---

## 19. 验收标准

建议新增 `backend/tests/test_teaching_answer_quality.py`。

### 19.1 指标验收

每个 follow-up 答案必须满足：

```text
teaching_sentence_ratio >= 0.65
evidence_sentence_ratio <= 0.20
uncertainty_sentence_ratio <= 0.10
teaching_block_count >= 3
evidence_items <= 3
autonomous_expansion_present == True
next_steps_count between 1 and 3
repo_anchor_count >= 1 when asking source/entry/flow/module
repeat_similarity <= 0.35 for repeated topic follow-up
```

### 19.2 Golden Prompts

用这些问题测：

```text
1. 这个仓库后端入口在哪里？像老师一样讲。
2. /api/chat 的回答是怎么从用户输入一路变成前端看到的流式文本的？
3. m5_session 和 m6_response 分别负责什么？为什么要拆开？
4. 讲深一点，不要重复刚才的话，带我走一段代码。
5. 只看证据，哪些地方说明 backend 不再做 m3/m4 skeleton？
6. 这个工具调用循环为什么可能导致回答偏证据而不是教学？
7. 总结一下目前我们学到了什么，下一步该读哪个文件？
```

### 19.3 人工验收问题

人工看答案时只问 5 件事：

1. 初学者读完能不能复述一个工程概念？
2. 有没有把概念映射到具体仓库路径？
3. 有没有走读至少一段代码/流程？
4. 证据有没有变成辅助，而不是主体？
5. 同主题追问时有没有换角度加深，而不是重讲？

---

## 20. 最重要的产品取舍

### 20.1 不要走极端：不是不要证据

Repo Tutor 仍然必须证据驱动，不能胡说。但证据应该像老师讲课时的板书依据，而不是把讲义全文贴出来。

正确形态：

```text
讲解：入口文件通常负责装配 app、路由、配置。
仓库映射：在这个仓库里，backend/main.py 更像后端入口候选，因为它承担应用启动装配角色。
证据：backend/main.py 创建 app；README 当前 flow 说明后端 + web 是 live stack。
不确定：静态阅读不能证明真实部署命令，需要看启动脚本或运行配置。
```

错误形态：

```text
结论：backend/main.py 可能是入口。
证据 1：……
证据 2：……
证据 3：……
证据 4：……
不确定项：……
下一步：……
```

### 20.2 也不要把 skeleton 当事实

Skeleton 是教学脚手架，不是“真实运行结论”。所有 skeleton item 都要带：

```text
status: formed / heuristic / unknown
confidence: high / medium / low / unknown
evidence_refs: []
unknowns: []
candidate_wording: true
```

### 20.3 自主拓展必须克制

每轮 1 个拓展就够。多了会又变废话。

---

## 21. 推荐优先级

### P0：马上改

1. `prompt_builder.py` follow-up schema 补全。
2. `prompt_builder.py` 教学比例 + 证据上限。
3. `response_parser.py` 解析 teaching_blocks / coverage_updates。
4. `OutputContract` 增加教学质量字段。
5. 修复 `entry_section.status` 的 `confirmed` -> `formed`。
6. 先做轻量 quality gate。

### P1：一两天内改

1. `LessonCoverageLedger`。
2. `SemanticHistorySummary`。
3. `TeachingTurnPlanner`。
4. 缓存后过闸门再 stream。
5. Deep research notes 进入 session memory。

### P2：完整 PRD 版本

1. `m3_teaching_skeleton`。
2. skeleton tools。
3. candidate flow / layer / dependency summary。
4. golden tests + metrics dashboard。

---

## 22. 最终效果预期

改完后，同样问“入口在哪里”，回答应该从：

```text
入口候选是 backend/main.py。证据如下……不确定项如下……下一步如下……
```

变成：

```text
这轮我们先学会“怎么判断一个后端仓库的入口”。入口不一定是业务最多的文件，而是把 app、路由、配置装配起来的地方。

放到这个仓库里看，backend/main.py 像后端入口候选，因为它处在后端 live stack 的装配位置；但我会把它叫候选入口，因为静态阅读还不能证明真实部署命令。

顺着代码读时，你应该先看它创建了什么应用对象，再看它把哪些 routes 或服务挂进去。这样你就能从“入口”自然走到“请求怎么进入系统”。

顺手拓展：读工程入口时，不要期待入口解释所有业务。入口的价值是告诉你“系统把控制权交给谁”。下一步就该沿着这个交接点进入 routes/session/response 层。

证据与不确定项：
- ... 最多三条
```

这才是老师，不是证据复读机。

