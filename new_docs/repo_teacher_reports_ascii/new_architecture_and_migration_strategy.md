# Repo_teacher 更改方案：全新架构和更改策略

分析时间：2026-04-22  
目标：按 `new_docs/PRD_v6_teaching_first.md` 将后端从“带教学包装的仓库分析器”改造成“以真实源码为素材的持续教学系统”。  
核心原则：**teaching-first with evidence boundaries**，即教学正文优先，所有事实由源码证据、候选置信度和未知边界约束。

## 1. 总体改造目标

当前系统最大的问题不是工具不够多，而是缺少“教学中间层”。改造后，后端不应该只把文件树和源码片段交给 LLM，而应该先把仓库转成“可教学材料”，再把每一轮变成“一个可讲透的教学单元”。

目标行为如下：

```text
用户进入仓库
  -> Agent 不 dump 文件树
  -> 先给轻地图
  -> 主动选择一个最值得先懂的点
  -> 像老师一样讲这个点为什么重要、承担什么职责、如何在源码中体现
  -> 只用少量源码锚点支撑
  -> 最后自然推进一个下一个教学子点
```

跟当前相比，最大变化是：

```text
从：LLM 根据文件树/片段自己组织答案
到：后端生成 TeachingTurnPlan，LLM 按计划讲课，质量门检查后再输出
```

## 2. 新架构总览

建议新后端架构如下：

```text
M1 RepoAccess
  负责仓库访问、安全边界、仓库基本信息
        │
        ▼
M2 FileTree + SourceCatalog
  负责文件树、语言/目录识别、可读源码目录、候选文件索引
        │
        ▼
M3 RepoTeachingSkeletonBuilder        ← 新增/恢复
  把仓库转换成候选教学骨架：入口、模块、流程、import、层次、未知边界
        │
        ▼
M4 TeachingTopicGraph / CurriculumBuilder   ← 新增/恢复
  把骨架转换成可讲的教学点卡片和推荐教学路线
        │
        ▼
M5 TeachingState + TeachingTurnPlanner      ← 升级
  维护已讲内容，选择本轮唯一教学点，生成 TeachingTurnPlan
        │
        ▼
M6 TeacherAnswerGenerator + QualityGate     ← 升级
  读取最少锚点，生成教学正文，压缩证据，质量检查，不合格重写
        │
        ▼
Frontend SSE / Chat UI
  展示最终教学答案和一个下一教学子点
```

## 3. 核心思想：候选教学骨架不是幻觉

当前 README 中排除了 m3/m4/repo_kb/likely architecture payload，这是造成“不敢讲”的核心之一。新方案不是让后端硬编码结论，而是让后端生成**候选教学骨架**。

候选教学骨架的每个结论都必须带：

```text
claim_type: entry_candidate | module_role | candidate_flow | layer_hint | import_source
claim_text: 候选结论
confidence: high | medium | low
evidence_refs: 指向文件路径、行号、工具结果 ID 或摘要来源
unknowns: 哪些部分还没核实
teaching_value: 这个结论为什么值得教
```

这样可以同时满足：

- 不胡说：所有结论都知道证据和边界；
- 能讲课：老师有结构化课程材料，不需要从文件树临场猜。

## 4. 新增数据结构

### 4.1 EvidenceRef

```python
class EvidenceRef(BaseModel):
    id: str
    source_type: Literal["file_tree", "readme", "source_excerpt", "search_result", "import_scan", "heuristic"]
    path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    summary: str
    confidence: Literal["high", "medium", "low"]
```

说明：所有教学骨架里的事实都通过 EvidenceRef 追踪来源。`heuristic` 可以存在，但必须低/中置信，并标注 unknown。

### 4.2 UnknownItem

```python
class UnknownItem(BaseModel):
    id: str
    description: str
    impact: Literal["blocks_claim", "narrows_claim", "minor"]
    suggested_verification: str | None = None
```

说明：不要把未知变成大段免责声明。未知应该是结构化边界，只在影响教学结论时可见。

### 4.3 RepoTeachingSkeleton

```python
class RepoTeachingSkeleton(BaseModel):
    skeleton_id: str
    repo_id: str
    generated_at: datetime
    project_profile: ProjectProfile
    entry_candidates: list[EntryCandidate]
    import_source_summary: ImportSourceSummary
    module_cards: list[ModuleTeachingCard]
    candidate_flows: list[CandidateFlow]
    layer_hints: list[LayerHint]
    topic_cards: list[TeachingPointCard]
    global_unknowns: list[UnknownItem]
    evidence_index: dict[str, EvidenceRef]
```

### 4.4 ProjectProfile

```python
class ProjectProfile(BaseModel):
    primary_languages: list[str]
    detected_frameworks: list[str]
    app_shape: Literal["backend", "frontend", "fullstack", "library", "unknown"]
    likely_runtime_roles: list[str]
    beginner_summary: str
    evidence_refs: list[str]
```

### 4.5 EntryCandidate

```python
class EntryCandidate(BaseModel):
    path: str
    entry_kind: Literal["api_app", "cli", "script", "test", "frontend_app", "unknown"]
    why_candidate: str
    confidence: Literal["high", "medium", "low"]
    evidence_refs: list[str]
    unknowns: list[str]
    teaching_value: str
```

### 4.6 ModuleTeachingCard

```python
class ModuleTeachingCard(BaseModel):
    module_id: str
    path_prefix: str
    observed_responsibility: str
    not_responsible_for: list[str]
    interacts_with: list[str]
    beginner_metaphor: str | None = None
    key_files: list[str]
    evidence_refs: list[str]
    confidence: Literal["high", "medium", "low"]
```

### 4.7 CandidateFlow

```python
class CandidateFlow(BaseModel):
    flow_id: str
    title: str
    steps: list[CandidateFlowStep]
    confidence: Literal["high", "medium", "low"]
    unknowns: list[str]
    teaching_value: str
```

### 4.8 TeachingPointCard

```python
class TeachingPointCard(BaseModel):
    point_id: str
    title: str
    why_worth_teaching: str
    prerequisite_points: list[str]
    related_modules: list[str]
    source_anchor_candidates: list[SourceAnchorCandidate]
    preferred_depth: Literal["intro", "normal", "deep"]
    common_student_confusion: list[str]
    next_point_candidates: list[str]
```

### 4.9 TeachingTurnPlan

这是 v6 最关键的数据结构。

```python
class TeachingTurnPlan(BaseModel):
    turn_id: str
    point_id: str
    point_title: str
    why_now: str
    user_question_relevance: str
    target_depth: Literal["shallow", "normal", "deep"]
    teaching_moves: list[Literal[
        "concept_explain",
        "repo_mapping",
        "code_walkthrough",
        "design_reasoning",
        "responsibility_split",
        "compare_alternatives"
    ]]
    source_anchors: list[SourceAnchorPlan]
    must_explain: list[str]
    avoid: list[str]
    evidence_budget: EvidenceBudget
    next_teaching_point: NextTeachingPoint
```

示例：

```json
{
  "point_title": "为什么 TeachingState 是这个系统的课堂记忆中枢",
  "why_now": "用户已经看到 Agent 会重复结构，但还没理解多轮教学为什么需要状态。先讲这个点能解释很多后端行为。",
  "target_depth": "normal",
  "teaching_moves": ["concept_explain", "repo_mapping", "responsibility_split"],
  "source_anchors": [
    {"path": "backend/m5_session/teaching_state.py", "reason": "看教学计划和状态如何被维护", "max_lines": 80},
    {"path": "backend/m5_session/teaching_service.py", "reason": "看状态如何进入 prompt", "max_lines": 60}
  ],
  "must_explain": [
    "它不是业务代码，而是老师的记忆系统",
    "它如何影响下一轮讲什么",
    "为什么 parser fallback 会污染记忆"
  ],
  "avoid": ["不要列完整文件树", "不要把证据写成主体"],
  "evidence_budget": {"max_visible_items": 2, "max_visible_ratio": 0.25},
  "next_teaching_point": {
    "title": "Prompt 和 output contract 如何把老师变成分析器",
    "why_after_this": "理解了状态后，下一步自然要看状态如何驱动 LLM 输出。"
  }
}
```

## 5. M3：RepoTeachingSkeletonBuilder

### 5.1 输入

```text
RepositoryContext
FileTreeSnapshot
README / docs 摘要
语言与框架检测结果
可选：有限源码扫描 / import scan / route scan
可选：deep_research notes
```

### 5.2 输出

```text
RepoTeachingSkeleton
```

### 5.3 生成策略

第一步，项目画像：识别语言、框架、应用类型、主要目录。

第二步，入口候选：Python 项目优先查 `main.py`、`app.py`、FastAPI/Flask app、CLI、`if __name__ == "__main__"`、路由注册、测试入口。非 Python 降级为文件树和 README 解释。

第三步，import 来源：区分标准库、第三方、本地模块；把本地 import 聚合成模块关系。

第四步，模块卡片：按路径前缀、import、命名、README 描述生成候选职责，但必须携带 confidence 和 evidence。

第五步，候选流程：从入口、路由、服务函数、工具调用链中生成 1-3 条候选流程骨架。低证据时只说“候选流程”，不说“真实运行链路”。

第六步，教学点卡片：把模块和流程转成“值得讲的点”。例如：

```text
- 为什么把 repo access 和 file tree 分开
- 为什么教学状态不应该靠 LLM 自己记
- 为什么 tool loop 会把回答带向证据分析
- 为什么 output contract 会塑造 Agent 口吻
```

### 5.4 关键要求

M3 不能输出“事实结论裸奔”。所有候选都必须有：

```text
evidence_refs
confidence
unknowns
teaching_value
```

## 6. M4：TeachingTopicGraph / CurriculumBuilder

M4 负责把 skeleton 变成可讲课程。

### 6.1 职责

```text
输入：RepoTeachingSkeleton + 用户画像/目标
输出：TeachingTopicGraph + 推荐 first point
```

### 6.2 TopicGraph 字段

```python
class TeachingTopicGraph(BaseModel):
    graph_id: str
    first_point_id: str
    points: list[TeachingPointCard]
    edges: list[TeachingEdge]
    beginner_path: list[str]
    architecture_path: list[str]
    code_walkthrough_path: list[str]
```

### 6.3 路径示例

对 Repo_teacher 自身，可能的 beginner path 是：

```text
1. 这个系统为什么需要“教学状态”
2. 状态如何进入 prompt
3. prompt/output contract 如何塑造老师口吻
4. 工具读取为什么只是证据层
5. 如何用质量门保证回答像老师
```

这条路径不是固定事实，而是课程组织方式。它可以根据用户问题切换，但每轮仍只讲一个点。

## 7. M5 升级：TeachingState + TeachingTurnPlanner

### 7.1 现有问题

当前 M5 有 teaching state，但它更像学习 goal/stage 管理，不是课程覆盖管理。

### 7.2 新状态结构

```python
class TeachingPointCoverage(BaseModel):
    point_id: str
    title: str
    status: Literal["not_started", "introduced", "explained", "practiced", "needs_reinforcement"]
    depth_reached: Literal["none", "intro", "normal", "deep"]
    anchor_paths_used: list[str]
    explanation_summary: str
    remaining_gaps: list[str]
    last_taught_message_id: str | None
```

```python
class TeachingSessionState(BaseModel):
    current_goal: LearningGoal
    current_topic_graph_id: str | None
    current_point_id: str | None
    covered_points: dict[str, TeachingPointCoverage]
    last_next_teaching_point: NextTeachingPoint | None
    user_profile_notes: list[str]
    goal_switch_history: list[GoalSwitchRecord]
```

### 7.3 TeachingTurnPlanner 决策流程

```text
输入：用户消息 + TeachingSessionState + TopicGraph + Skeleton
  1. 判断用户是否显式切换目标
  2. 如果未切换，优先继续上轮 next_teaching_point
  3. 如果用户问局部问题，把局部问题映射到一个 point card
  4. 如果上轮点未讲透，继续同点但换角度
  5. 生成 TeachingTurnPlan
```

### 7.4 决策原则

- 每轮只有一个 `point_id`；
- 允许 answer user first，但必须回到教学点；
- 如果用户问多个问题，选最能解开当前认知障碍的一个；
- 不再使用 `allowed_new_points=2` 控制教学，而使用 `current_point` 控制；
- “讲透”由质量门和 structured payload 决定，不由 visible_text fallback 决定。

## 8. M6 升级：TeacherAnswerGenerator

### 8.1 新的生成链路

```text
build_messages_v6(turn_plan, skeleton, state, tool_context)
  -> LLM 工具读取最少源码锚点
  -> draft answer + structured payload
  -> quality gate
  -> fail: rewrite once or twice with precise reasons
  -> pass: stream final visible answer
  -> parse structured payload
  -> update TeachingPointCoverage
```

### 8.2 新 system prompt 核心规则

建议替换为以下语义，不必逐字照搬：

```text
你是 Repo Teacher。你的主产品是教学，不是证据报告。
每轮必须完成一个教学单元：说明本轮讲什么、为什么现在讲、它在系统里承担什么角色、用少量源码锚点带用户理解、最后给出一个自然的下一教学子点。
证据用于约束事实，不能成为主体。除非用户要求审计，否则不要把回答写成“证据分析报告”。
读完源码后，不能只复述文件内容；必须解释它为什么存在、解决什么问题、为什么这样拆职责、和当前教学点的关系。
如果证据不足，缩小说法并标注边界，而不是停止讲课。
下一步只能给一个具体教学子点，不给菜单。
```

### 8.3 新输出 contract

废弃当前固定可见 sections。改成内部 contract：

```python
class TeacherVisibleAnswerContract(BaseModel):
    must_be_natural_teaching: bool = True
    exactly_one_teaching_point: bool = True
    must_include_why_now: bool = True
    must_include_system_role: bool = True
    max_source_anchors_visible: int = 3
    max_evidence_visible_ratio: float = 0.25
    exactly_one_next_teaching_point: bool = True
    avoid_fixed_analysis_template: bool = True
```

可见输出不强制标题，但机器 schema 强制字段。

### 8.4 新 follow-up JSON schema

替换当前主要只有 `next_steps` 的 schema：

```json
{
  "answer_kind": "teaching_turn",
  "current_teaching_point": {
    "point_id": "string",
    "title": "string",
    "why_now": "string",
    "depth_reached": "intro|normal|deep"
  },
  "source_anchors_used": [
    {
      "path": "string",
      "line_start": 0,
      "line_end": 0,
      "role_in_teaching": "string",
      "evidence_ref_id": "string"
    }
  ],
  "teaching_claims": [
    {
      "claim": "string",
      "confidence": "high|medium|low",
      "evidence_ref_ids": ["string"],
      "unknown_boundaries": ["string"]
    }
  ],
  "covered_point_update": {
    "point_id": "string",
    "status": "introduced|explained|needs_reinforcement",
    "summary": "string",
    "remaining_gaps": ["string"]
  },
  "next_teaching_point": {
    "title": "string",
    "why_after_this": "string",
    "point_id": "string|null"
  },
  "quality_self_check": {
    "one_point": true,
    "why_now_present": true,
    "system_role_present": true,
    "evidence_not_dominant": true,
    "not_readme_dump": true,
    "single_next_point": true
  }
}
```

说明：这些字段不是为了让用户看到，而是为了让状态可靠更新。

## 9. 质量门 QualityGate

### 9.1 为什么必须有质量门

当前架构先 stream 再 parse，所以无法拦住低质量回答。v6 必须先生成草稿再检查。

### 9.2 P0 检查项

质量门至少检查：

```text
1. 是否只有一个明确 current teaching point
2. 是否说明 why now
3. 是否说明该点在系统中的角色
4. 是否有足够教学正文，而不是列表/证据堆叠
5. 是否使用 1-3 个源码锚点
6. 证据可见比例是否 <= 25%
7. 不确定性是否没有压倒正文
8. 是否没有 README/file-tree dump
9. 是否没有 1-3 个菜单式 next steps
10. 是否给出唯一 next_teaching_point
11. 是否读完源码后解释了“为什么/职责/设计意图”
12. structured payload 是否可用于状态更新
```

### 9.3 简单实现

第一版可以不用模型评审，先用规则打分：

```python
class TeachingQualityGate:
    def evaluate(self, visible_text: str, payload: TeacherPayload, plan: TeachingTurnPlan) -> QualityReport:
        failures = []
        if not payload.current_teaching_point.title:
            failures.append("missing_current_teaching_point")
        if len(payload.source_anchors_used) > 3:
            failures.append("too_many_anchors")
        if len(payload.next_teaching_point.title.split("；")) > 1:
            failures.append("next_point_not_single")
        if self._looks_like_file_tree_dump(visible_text):
            failures.append("file_tree_dump")
        if self._evidence_ratio(visible_text) > 0.25:
            failures.append("evidence_dominates")
        if not self._has_why_design_or_role(visible_text):
            failures.append("missing_design_or_role_explanation")
        return QualityReport(pass_=not failures, failures=failures)
```

如果失败，执行一次重写：

```text
你的草稿没有通过 Repo Teacher v6 质量检查。
失败原因：evidence_dominates, missing_design_or_role_explanation, next_point_not_single。
请保留事实边界，重写为一个自然教学单元：只讲当前点，证据最多两条，结尾一个下一教学子点。
```

### 9.4 Streaming 改法

推荐方案：

```text
后端内部非流式/缓冲生成草稿
  -> 质量门
  -> 最终答案再流式给前端
```

如果担心用户等待，可以在生成草稿期间只发 activity event，例如：

```text
正在确定本轮最值得讲的点
正在核实两个源码锚点
正在整理成教学说明
```

不要先把未检查草稿发给用户。

## 10. 工具层改造

### 10.1 保留工具

保留：

```text
m1.get_repository_context
m2.get_file_tree_summary
m2.list_relevant_files
search_text
read_file_excerpt
teaching.get_state_snapshot
```

### 10.2 新增教学工具

新增：

```text
teaching.get_repo_skeleton
teaching.get_topic_graph
teaching.get_current_turn_plan
teaching.get_anchor_pack
teaching.get_covered_points
```

如果希望模块化更清楚，也可以拆成：

```text
m3.get_project_profile
m3.get_entry_candidates
m3.get_import_source_summary
m3.get_module_cards
m3.get_candidate_flows
m4.get_teaching_point_cards
m4.get_recommended_path
```

### 10.3 AnchorPack

`get_anchor_pack` 不应返回一堆文件，而应返回“当前教学点需要的最小源码锚点”：

```python
class AnchorPack(BaseModel):
    point_id: str
    anchors: list[SourceAnchor]
    why_these_anchors: str
    omitted_but_related: list[str]
```

### 10.4 工具选择策略

当前 `tool_selection.py` 按用户文本决定是否加 `read_file_excerpt`。新策略应按 `TeachingTurnPlan` 决定：

```text
如果本轮 plan 已有 anchors：优先 get_anchor_pack/read_file_excerpt 指定路径
如果用户问 entry：优先 m3.get_entry_candidates + anchor pack
如果用户问 flow：优先 m3.get_candidate_flows + 1-2 个关键源码锚点
如果用户问 architecture：优先 module_cards/layer_hints/topic_graph
```

不要每轮默认给 `list_relevant_files(limit=60)`，这会诱导路径列表化。

## 11. Prompt 改造细节

### 11.1 删除/弱化的规则

应删除或降级为内部要求：

```text
- 可见回答必须覆盖 Evidence / Uncertainty 固定部分
- 输出 1-3 个下一步问题/动作
- 给轻量阅读建议而不提供教学顺序
- 每轮只讲 small core points 但没有讲透标准
```

### 11.2 新增强规则

加入：

```text
- 可见回答必须是一个教学单元，不是仓库报告
- 本轮只讲 current_teaching_point
- 讲完要让初学者知道它为什么重要、在系统中做什么、读源码时抓什么
- 源码锚点最多 3 个，证据不要单独堆叠
- 不要复述 README 或文件树，除非它直接服务本轮教学点
- 不要把工具调用过程讲给用户，讲源码含义
- 如果证据不足，缩小 claim，不要停止教学
- 结尾只给一个 next_teaching_point
```

### 11.3 新 Prompt 输入结构

```json
{
  "teacher_role": "Repo Teacher v6",
  "student_context": {
    "level": "beginner_cs_student",
    "known_points": [],
    "recent_confusions": []
  },
  "repo_teaching_skeleton": "compressed skeleton or tool reference",
  "turn_plan": "TeachingTurnPlan",
  "evidence_policy": {
    "must_ground_factual_claims": true,
    "visible_evidence_max_items": 2,
    "unknowns_visible_only_if_material": true
  },
  "output_contract": "TeacherVisibleAnswerContract",
  "machine_payload_schema": "TeacherPayload"
}
```

## 12. Parser 改造

### 12.1 当前 parser 的问题

当前 parser 太宽容，会从 visible_text fallback 出 direct explanation 和 evidence，进而污染状态。

### 12.2 新原则

```text
可见文本可以宽容展示；教学状态必须严格更新。
```

### 12.3 新行为

- 如果缺少 `<json_output>`，可见回答仍可显示，但不更新 covered_points；
- 如果 payload 缺少 `current_teaching_point`，触发质量门重写；
- 如果 payload 缺少 `next_teaching_point`，触发重写或保留上轮 next；
- 不再从第一行 fallback evidence；
- 不再把整段 visible_text 当作 direct_explanation；
- `related_topic_refs` 改为 `covered_point_update.point_id`。

## 13. 状态更新改造

状态更新只接受结构化 payload：

```python
def update_after_teaching_turn(session, payload: TeacherPayload, plan: TeachingTurnPlan):
    point_id = payload.covered_point_update.point_id
    coverage = session.teaching_state.covered_points.get(point_id) or TeachingPointCoverage(...)
    coverage.status = payload.covered_point_update.status
    coverage.depth_reached = payload.current_teaching_point.depth_reached
    coverage.anchor_paths_used = [a.path for a in payload.source_anchors_used]
    coverage.explanation_summary = payload.covered_point_update.summary
    coverage.remaining_gaps = payload.covered_point_update.remaining_gaps
    session.teaching_state.current_point_id = payload.next_teaching_point.point_id
    session.teaching_state.last_next_teaching_point = payload.next_teaching_point
```

如果质量门认为本轮没有讲透：

```text
coverage.status = needs_reinforcement
下一轮继续同 point，但换 teaching_moves
```

## 14. Deep Research 的正确接入方式

当前 `deep_research` 不应该只用于生成一段初始报告。它更适合成为 M3 skeleton 的材料来源。

建议：

```text
deep_research notes
  -> normalize_to_evidence_refs
  -> feed RepoTeachingSkeletonBuilder
  -> skeleton.topic_cards / module_cards / candidate_flows
  -> TeachingTurnPlanner 使用
```

如果 deep_research 成本高，可以分阶段：

```text
Phase A: quick skeleton from file tree/import scan，立即可教
Phase B: background/enriched skeleton，后续轮次逐步替换低置信候选
```

在产品实现中可以异步；在一次请求内也可以先用 quick skeleton，不要为了完整分析阻塞首轮教学。

## 15. 前端/API 输出策略

### 15.1 API 层

新增或扩展返回字段：

```json
{
  "visible_answer": "string",
  "current_teaching_point": {...},
  "next_teaching_point": {...},
  "source_anchors": [...],
  "quality": {"passed": true, "warnings": []}
}
```

### 15.2 UI 层

主 UI 只显示教学回答和一个“继续讲下一点”的按钮。不要默认显示证据报告。源码锚点可以折叠显示，例如：

```text
本轮用到的源码锚点（2）
```

工具活动可以保留为状态提示，但不要和最终教学正文混在一起。

## 16. 分阶段更改策略

### Phase 0：立即止血，1-2 天内可做

目标：不用新增完整 M3/M4，也要立刻减少“复述 README + 证据分析”。

改动：

1. `TeachingService._build_output_contract` 去掉固定 `EVIDENCE/UNCERTAINTY/NEXT_STEPS` 可见栏目；
2. follow-up JSON schema 从 `next_steps` 扩展为 `current_teaching_point/source_anchors/next_teaching_point/quality_self_check`；
3. prompt 明确“教学正文优先，证据最多两条，下一步一个教学子点”；
4. `next_steps` UI 暂时只保留一个，内部命名改为 `next_teaching_point`；
5. `response_parser.py` 禁止从 visible_text fallback evidence/direct_explanation 来推进教学状态；
6. `ChatWorkflow` 至少对非工具 final answer 做缓冲质量检查，失败则重写一次；
7. 初始 prompt 改为“轻地图 + 选一个最值得讲的点讲透”，而不是“建立整体理解”。

预期效果：回答会明显更像老师，证据栏目减少，next step 不再像菜单。

### Phase 1：TeachingTurnPlan 落地，3-5 天

目标：每轮有明确教学计划。

改动：

1. 新增 `TeachingTurnPlan` contract；
2. 在 M5 中实现 `TeachingTurnPlanner`；
3. 将 `build_teaching_directive` 替换/升级为 `build_teaching_turn_plan`；
4. M6 prompt 必须围绕 turn_plan 输出；
5. 质量门检查 turn_plan 是否被满足；
6. tests 增加单轮教学质量快照测试。

预期效果：多轮不再随机跳点，每轮只讲一个点且能接续。

### Phase 2：RepoTeachingSkeletonBuilder，1-2 周

目标：后端提供可教学材料，而不是只提供文件树。

改动：

1. 新建 `backend/m3_teaching_skeleton/`；
2. 从 M2 file tree、README、Python AST/import scan、route scan 生成 skeleton；
3. 增加 `RepoTeachingSkeleton`、`EntryCandidate`、`ModuleTeachingCard`、`CandidateFlow`；
4. 将 skeleton 存入 session；
5. 新增工具 `teaching.get_repo_skeleton`、`m3.get_entry_candidates`、`m3.get_module_cards`；
6. 初始教学计划从 skeleton 生成，而不是 `m2_file_tree_only`。

预期效果：首轮不再靠文件树猜讲什么，而能主动选择有教学价值的点。

### Phase 3：TopicGraph 与教学记忆，1 周

目标：建立真正多轮课程。

改动：

1. 新建 `backend/m4_curriculum/`；
2. 根据 skeleton 生成 TeachingPointCard；
3. `TeachingState` 改为记录 `TeachingPointCoverage`；
4. 支持五轮以上上下文记忆；
5. goal switch 时保留旧路径并建立新路径；
6. 添加重复检测，避免上一轮讲过的内容重新复述。

预期效果：Agent 像持续上课，不像每轮重新分析。

### Phase 4：质量门与流式重构，3-7 天

目标：不合格回答不进入用户界面。

改动：

1. `stream_answer_text_with_tools` 增加 buffered mode；
2. `ChatWorkflow` 先收集 draft，再质量门，再发送最终 visible chunks；
3. 失败重写最多一次或两次；
4. 前端 activity event 显示“正在整理教学解释”，而非流出草稿；
5. tests 增加 quality gate failure/rewrite 场景。

预期效果：大幅降低坏回答外露。

### Phase 5：回归测试与评测集，持续

建立 fixtures：

```text
fixture_python_fastapi_repo
fixture_cli_repo
fixture_non_python_repo
fixture_large_mixed_repo
fixture_repo_teacher_self
```

每个 fixture 测试：

- 首轮是否一个点讲透；
- 是否不 dump 文件树；
- 是否 evidence ratio 合格；
- 是否一个 next teaching point；
- 五轮后是否不重复；
- 目标切换是否保留上下文；
- 不确定性是否边界化而非劝退；
- 非 Python 是否优雅降级。

## 17. 文件级修改建议

### 17.1 `backend/m6_response/prompt_builder.py`

改动：

- 新增 `_SYSTEM_RULES_V6_TEACHING_FIRST`；
- `_strict_output_requirements` 改为 teaching unit requirements；
- `_teaching_directive` 替换为 `_teaching_turn_plan_summary`；
- `_json_schema` 加入 `current_teaching_point/source_anchors/next_teaching_point/quality_self_check`；
- payload 加入 compressed skeleton / topic graph / turn plan。

### 17.2 `backend/m5_session/teaching_service.py`

改动：

- `_build_output_contract` 改成内部质量要求，不再要求固定可见 sections；
- `build_prompt_input` 调用 `TeachingTurnPlanner`；
- `ensure_answer_suggestions` 改成 `ensure_next_teaching_point`；
- 初始 user_text 改为“轻地图 + 讲透一个点”。

### 17.3 `backend/m5_session/teaching_state.py`

改动：

- `build_initial_teaching_plan` 从 skeleton 生成；
- 新增 `TeachingPointCoverage`；
- `update_after_structured_answer` 只根据 payload 更新；
- 删除或弱化基于 visible_text/direct_explanation 的完成判断；
- `build_teaching_decision` 输出 point-level decision。

### 17.4 `backend/m6_response/response_parser.py`

改动：

- 删除 first-line evidence fallback；
- 删除 visible_text direct_explanation fallback 对状态的影响；
- 对缺少关键 payload 的回答返回 `parse_quality_failed`；
- 支持 v6 payload schema；
- 保留 legacy parser 仅作兼容。

### 17.5 `backend/m6_response/answer_generator.py`

改动：

- 增加 `generate_answer_draft`；
- 增加 `generate_answer_with_quality_gate`；
- legacy `stream_answer_text` 可保留；
- v6 chat 默认走 buffered draft -> gate -> stream final。

### 17.6 `backend/agent_runtime/tool_selection.py`

改动：

- 选择工具时读取 `TeachingTurnPlan`；
- 优先教学工具和 anchor pack；
- 降低默认 `m2.list_relevant_files(limit=60)` 的使用；
- 对 flow/entry/module 走 M3 工具而不是纯搜索。

### 17.7 `backend/agent_runtime/context_budget.py`

改动：

- seed context 从 file tree summary 主导改成 turn_plan + skeleton summary 主导；
- 文件树只保留压缩摘要；
- 相关文件列表只作为 fallback，不作为主材料；
- starter excerpt 根据 source_anchors 选，不根据用户关键词粗触发。

### 17.8 README

改动当前保守说明：

旧：

```text
No m3 static entry inference, no m4 teaching skeleton/topic index, no repo_kb, no backend-authored likely architecture payload.
```

新：

```text
Runtime may build an evidence-bounded teaching skeleton. It must label candidates with evidence_refs, confidence, and unknowns. The skeleton is teaching material, not guaranteed runtime truth.
```

## 18. 验收标准

### 18.1 首轮验收

输入一个仓库后，首轮回答必须：

1. 先给轻量地图，不超过 20% 篇幅；
2. 明确“这一轮先讲 X”；
3. 说明为什么 X 值得先讲；
4. 解释 X 在系统中的角色；
5. 使用 1-3 个源码锚点；
6. 不列大文件树；
7. 不把证据/不确定性作为主要栏目；
8. 结尾给一个下一个教学子点。

### 18.2 Follow-up 验收

连续 5 轮必须：

1. 不重复 README；
2. 每轮一个点；
3. 能继承上一轮 next teaching point；
4. 用户切换问题时能把问题映射到当前课程；
5. 讲不透时继续同一点，而不是跳；
6. 状态记录具体 point coverage。

### 18.3 质量门验收

构造坏草稿：

```text
- 文件树 dump
- 证据超过 50%
- 给三个下一步选项
- 没有 why now
- 没有源码锚点
```

系统必须拒绝或重写。

## 19. 风险与对策

### 风险 1：候选 skeleton 引入幻觉

对策：所有 skeleton claim 带 `confidence/evidence_refs/unknowns`；低置信 claim 只能用于“候选教学”，不能当事实。

### 风险 2：质量门增加延迟

对策：只允许一次重写；activity event 先提示“正在组织教学点”；首轮 quick skeleton，后续懒加载 enrichment。

### 风险 3：回答过度模板化

对策：schema 是内部结构，可见答案不固定标题。质量门检查“自然教学”，不要求固定章节。

### 风险 4：大仓库 skeleton 成本高

对策：分层 skeleton。第一版只做目录/README/import scan；用户深入时再按 topic 读源码。

### 风险 5：用户问具体 bug/代码细节时教学拖沓

对策：TeachingTurnPlanner 支持 `answer_user_first`，先回答具体问题，再把它纳入一个教学点。不是每次都长篇上课，但每次都要有老师式解释。

## 20. 推荐优先级

最推荐的实现顺序：

```text
1. 改 prompt/output_contract/schema，马上止血
2. 改 parser fail-closed，防止状态污染
3. 加 TeachingTurnPlan，每轮一个点
4. 加 QualityGate，坏回答不外露
5. 加 M3 Skeleton，首轮和多轮真正变强
6. 加 M4 TopicGraph，形成持续课程
```

如果只做一件事，做 `TeachingTurnPlan + QualityGate`。如果做两件事，再加 `RepoTeachingSkeleton`。如果要彻底达到 PRD v6，三者都必须有。

## 21. 最终架构宣言

Repo_teacher 的后端不应该再把自己理解成“把仓库事实安全交给 LLM”。它应该理解成：

```text
把仓库加工成可验证的教学材料，
把每一轮对话规划成一个可讲透的教学单元，
让 LLM 像老师一样解释源码，
并用证据边界保证不胡说。
```

这就是 PRD v6 的核心，也是一条能解决当前“复述 README、只做证据分析、不像老师”问题的完整技术路线。
