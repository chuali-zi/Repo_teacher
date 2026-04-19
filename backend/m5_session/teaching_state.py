from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from backend.contracts.domain import (
    ConversationState,
    FileTreeSnapshot,
    InitialReportAnswer,
    StudentLearningState,
    StudentLearningTopicState,
    StructuredAnswer,
    Suggestion,
    TeachingDebugEvent,
    TeachingDirective,
    TeachingDecisionSnapshot,
    TeacherWorkingLog,
    TeachingPlanState,
    TeachingPlanStep,
)
from backend.contracts.enums import (
    ConfidenceLevel,
    LearningGoal,
    PromptScenario,
    StudentCoverageLevel,
    TeachingDebugEventType,
    TeachingDecisionAction,
    TeachingPlanStepStatus,
)

_TEACHING_GOAL_ORDER: tuple[LearningGoal, ...] = (
    LearningGoal.OVERVIEW,
    LearningGoal.STRUCTURE,
    LearningGoal.ENTRY,
    LearningGoal.FLOW,
    LearningGoal.MODULE,
    LearningGoal.LAYER,
    LearningGoal.DEPENDENCY,
    LearningGoal.SUMMARY,
)

_CONFUSION_SIGNALS = (
    "没懂",
    "不懂",
    "看不懂",
    " confused",
    "confusing",
    "为什么",
    "再讲",
    "讲清楚",
    "重新",
)


@dataclass(frozen=True)
class TeachingStateUpdate:
    teaching_plan_state: TeachingPlanState
    student_learning_state: StudentLearningState
    teacher_working_log: TeacherWorkingLog


def build_initial_teaching_plan(
    file_tree: FileTreeSnapshot,
    *,
    now: datetime,
) -> TeachingPlanState:
    candidate_files = _initial_candidate_files(file_tree)
    first_target = candidate_files[0] if candidate_files else "README.md"
    steps = [
        TeachingPlanStep(
            step_id="plan_step_1",
            title="建立仓库整体地图",
            goal=LearningGoal.STRUCTURE,
            target_scope="repository root",
            reason="先建立目录和关键文件的整体认知，再决定具体从哪里深挖。",
            expected_learning_gain="知道仓库大致由哪些目录和入口样文件组成。",
            status=TeachingPlanStepStatus.ACTIVE,
            priority=1,
            depends_on=[],
            source_topic_refs=[],
            adaptation_note="轻计划，仅作为当前带读节奏，不代表静态事实。",
        ),
        TeachingPlanStep(
            step_id="plan_step_2",
            title=f"核实第一个源码起点: {first_target}",
            goal=LearningGoal.ENTRY,
            target_scope=first_target,
            reason="从一个具体文件开始核实入口或装配方式，避免只停留在目录猜测。",
            expected_learning_gain="把整体地图和具体源码位置连接起来。",
            status=TeachingPlanStepStatus.PLANNED,
            priority=2,
            depends_on=["plan_step_1"],
            source_topic_refs=[],
            adaptation_note="这只是当前建议的起点，后续可按证据调整。",
        ),
        TeachingPlanStep(
            step_id="plan_step_3",
            title="沿用户关心的问题继续深挖",
            goal=LearningGoal.FLOW,
            target_scope="user-driven exploration",
            reason="后续讲解以用户问题和已核实证据为主，不预设固定主流程。",
            expected_learning_gain="围绕真实证据建立更可靠的阅读路径。",
            status=TeachingPlanStepStatus.PLANNED,
            priority=3,
            depends_on=["plan_step_2"],
            source_topic_refs=[],
            adaptation_note="可根据用户问题切换到模块、依赖、分层等目标。",
        ),
    ]
    return TeachingPlanState(
        plan_id=_new_id("teach_plan"),
        generated_from_skeleton_id="m2_file_tree_only",
        current_step_id=steps[0].step_id,
        steps=steps,
        update_notes=["基于文件树初始化轻量教学计划。"],
        updated_at=now,
    )


def build_initial_student_learning_state(*, now: datetime) -> StudentLearningState:
    return StudentLearningState(
        state_id=_new_id("student_state"),
        topics=[
            StudentLearningTopicState(
                topic=goal,
                coverage_level=StudentCoverageLevel.UNSEEN,
                confidence_of_estimate=ConfidenceLevel.LOW,
                likely_gap="新会话尚未确认学生对该主题的理解。",
                recommended_intervention=_default_intervention(goal),
                supporting_evidence=[],
            )
            for goal in _TEACHING_GOAL_ORDER
        ],
        update_notes=["新会话初始化：所有主题按未讲解处理。"],
        updated_at=now,
    )


def build_initial_teacher_working_log(
    plan: TeachingPlanState,
    student_state: StudentLearningState,
    *,
    now: datetime,
) -> TeacherWorkingLog:
    active_step = _active_plan_step(plan)
    return TeacherWorkingLog(
        log_id=_new_id("teacher_log"),
        current_teaching_objective=active_step.title if active_step else "建立仓库整体地图",
        why_now=active_step.reason if active_step else "先建立整体地图，再按证据深入。",
        active_topic_refs=[],
        current_plan_step_id=active_step.step_id if active_step else None,
        planned_transition=_next_transition(plan),
        student_risk_notes=[
            "学生刚进入仓库，默认没有当前仓库的工程地图。",
            "入口、流程、分层都必须通过源码核实，不能把轻提示当事实。",
        ],
        recent_decisions=["生成初始轻量教学计划、学生状态和教师工作日志。"],
        open_questions=[],
        updated_at=now,
    )


def update_after_initial_report(
    conversation: ConversationState,
    answer: InitialReportAnswer,
    *,
    message_id: str,
    now: datetime,
) -> TeachingStateUpdate:
    plan = _copy_plan(conversation.teaching_plan_state, now)
    student_state = _copy_student_state(conversation.student_learning_state, now)
    student_state = _mark_topics(
        student_state,
        topics={LearningGoal.OVERVIEW, LearningGoal.STRUCTURE},
        message_id=message_id,
        student_signal="首轮报告已建立仓库地图和阅读起点。",
        default_level=StudentCoverageLevel.INTRODUCED,
        evidence_refs=answer.used_evidence_refs,
        now=now,
    )
    _complete_active_step(plan, note="首轮报告已建立整体地图。", now=now)
    log = _build_log_from_states(
        conversation,
        plan,
        student_state,
        decision="首轮报告完成：已建立仓库地图并保留未知项。",
        now=now,
    )
    return TeachingStateUpdate(plan, student_state, log)


def update_after_structured_answer(
    conversation: ConversationState,
    answer: StructuredAnswer,
    *,
    user_text: str,
    message_id: str,
    scenario: PromptScenario,
    now: datetime,
) -> TeachingStateUpdate:
    topics = _topics_from_answer(answer) or {conversation.current_learning_goal}
    plan = _copy_plan(conversation.teaching_plan_state, now)
    plan = _update_plan_after_answer(
        plan,
        topics=topics,
        scenario=scenario,
        answer=answer,
        now=now,
    )
    student_state = _copy_student_state(conversation.student_learning_state, now)
    student_state = _mark_topics(
        student_state,
        topics=topics,
        message_id=message_id,
        student_signal=_student_signal(user_text, answer, scenario),
        default_level=_coverage_level_for_turn(user_text, scenario),
        evidence_refs=answer.used_evidence_refs,
        now=now,
    )
    log = _build_log_from_states(
        conversation,
        plan,
        student_state,
        decision=_decision_note(topics, scenario),
        now=now,
    )
    return TeachingStateUpdate(plan, student_state, log)


def plan_based_suggestions(conversation: ConversationState) -> list[Suggestion]:
    plan = conversation.teaching_plan_state
    if not plan:
        return []
    suggestions: list[Suggestion] = []
    seen: set[str] = set()
    for step in plan.steps:
        if step.status not in {TeachingPlanStepStatus.ACTIVE, TeachingPlanStepStatus.PLANNED}:
            continue
        text = _suggestion_text_for_step(step)
        if text in seen:
            continue
        suggestions.append(
            Suggestion(
                suggestion_id=f"sug_{step.step_id}",
                text=text,
                target_goal=step.goal,
                related_topic_refs=[],
            )
        )
        seen.add(text)
        if len(suggestions) >= 3:
            break
    return suggestions


def build_teaching_decision(
    conversation: ConversationState,
    *,
    user_text: str,
    scenario: PromptScenario,
    now: datetime,
) -> TeachingDecisionSnapshot:
    plan = conversation.teaching_plan_state
    active_step = _active_plan_step(plan) if plan else None
    topic_refs = []
    topic_goals = {conversation.current_learning_goal}
    reinforcement_notes = _reinforcement_notes(conversation.student_learning_state, topic_goals)

    if scenario == PromptScenario.STAGE_SUMMARY:
        action = TeachingDecisionAction.SUMMARIZE_PROGRESS
        reason = "用户要求阶段总结，本轮优先回顾已讲内容和未展开内容。"
    elif reinforcement_notes:
        action = TeachingDecisionAction.REINFORCE_STUDENT_GAP
        reason = "学生状态显示当前主题需要补强，本轮先补框架与证据。"
    elif scenario == PromptScenario.GOAL_SWITCH:
        action = TeachingDecisionAction.ADAPT_TO_USER_GOAL
        reason = "用户显式切换学习目标，本轮先顺应新的讲解焦点。"
    elif active_step and active_step.goal in topic_goals:
        action = TeachingDecisionAction.PROCEED_WITH_PLAN
        reason = "用户问题与当前 active 教学计划一致，本轮继续沿计划推进。"
    else:
        action = TeachingDecisionAction.ANSWER_LOCAL_QUESTION
        reason = "用户问题偏向局部源码核实，本轮先回答局部问题，再回扣主线。"

    return TeachingDecisionSnapshot(
        decision_id=_new_id("teach_decision"),
        scenario=scenario,
        user_message_summary=_summarize_user_text(user_text),
        selected_action=action,
        selected_plan_step_id=active_step.step_id if active_step else None,
        selected_plan_step_title=active_step.title if active_step else None,
        teaching_objective=_decision_objective(conversation, active_step, action),
        decision_reason=reason,
        student_state_notes=reinforcement_notes
        or (conversation.teacher_working_log.student_risk_notes[:3] if conversation.teacher_working_log else []),
        planned_transition=conversation.teacher_working_log.planned_transition
        if conversation.teacher_working_log
        else _next_transition(plan) if plan else None,
        topic_refs=topic_refs,
        created_at=now,
    )


def build_teaching_directive(
    conversation: ConversationState,
    *,
    user_text: str,
    scenario: PromptScenario,
    decision: TeachingDecisionSnapshot | None = None,
) -> TeachingDirective:
    active_step = _active_plan_step(conversation.teaching_plan_state)
    directive_decision = decision or conversation.current_teaching_decision
    mode = _directive_mode(directive_decision.selected_action if directive_decision else None, scenario)
    focus_topics = _directive_focus_topics(conversation, active_step)
    return TeachingDirective(
        turn_goal=_directive_turn_goal(conversation, active_step, mode),
        mode=mode,
        focus_topics=focus_topics,
        answer_user_question_first=True,
        allowed_new_points=1 if scenario == PromptScenario.STAGE_SUMMARY else 2,
        must_anchor_to_evidence=True,
        avoid_repeating_message_ids=_recently_explained_message_ids(conversation),
        transition_hint=_directive_transition_hint(conversation, active_step, mode, user_text),
        forbidden_behaviors=[
            "Do not mention teaching state, student state, or teaching plan explicitly.",
            "Do not repeat prior explanations unless the user explicitly asks for a recap.",
            "Do not let plan progression override the current user question.",
        ],
    )


def append_teaching_debug_event(
    conversation: ConversationState,
    event_type: TeachingDebugEventType,
    *,
    summary: str,
    now: datetime,
    message_id: str | None = None,
    plan_step_id: str | None = None,
    details: dict | None = None,
) -> TeachingDebugEvent:
    event = TeachingDebugEvent(
        debug_event_id=_new_id("teach_evt"),
        event_type=event_type,
        occurred_at=now,
        message_id=message_id,
        plan_step_id=plan_step_id,
        summary=summary,
        details=details or {},
    )
    conversation.teaching_debug_events.append(event)
    conversation.teaching_debug_events = conversation.teaching_debug_events[-80:]
    return event


def _initial_candidate_files(file_tree: FileTreeSnapshot) -> list[str]:
    preferred = ("README.md", "main.py", "app.py", "__main__.py", "pyproject.toml")
    readable_files = {
        node.relative_path
        for node in file_tree.nodes
        if node.node_type == "file" and node.status == "normal"
    }
    ordered = [path for path in preferred if path in readable_files]
    if ordered:
        return ordered
    return sorted(readable_files)[:5]


def _copy_plan(plan: TeachingPlanState | None, now: datetime) -> TeachingPlanState:
    if plan is not None:
        return plan.model_copy(deep=True, update={"updated_at": now})
    return TeachingPlanState(
        plan_id=_new_id("teach_plan"),
        generated_from_skeleton_id="m2_file_tree_only",
        current_step_id=None,
        steps=[],
        update_notes=["缺少教学计划，保守跳过计划更新。"],
        updated_at=now,
    )


def _copy_student_state(
    student_state: StudentLearningState | None,
    now: datetime,
) -> StudentLearningState:
    if student_state is not None:
        return student_state.model_copy(deep=True, update={"updated_at": now})
    return build_initial_student_learning_state(now=now)


def _update_plan_after_answer(
    plan: TeachingPlanState,
    *,
    topics: set[LearningGoal],
    scenario: PromptScenario,
    answer: StructuredAnswer,
    now: datetime,
) -> TeachingPlanState:
    if not plan.steps:
        return plan
    target = _first_step_for_topics(plan, topics)
    if target is None:
        return plan

    if _answer_is_too_uncertain(answer):
        target.status = TeachingPlanStepStatus.DEFERRED
        target.adaptation_note = "本轮证据不足，先标记为 deferred，后续补证据再继续。"
    elif scenario == PromptScenario.GOAL_SWITCH:
        _set_active_step(plan, target.step_id)
        target.adaptation_note = "用户显式切换学习目标，本步骤被提前激活。"
    else:
        if target.status == TeachingPlanStepStatus.ACTIVE:
            target.status = TeachingPlanStepStatus.COMPLETED
            target.adaptation_note = "本轮回答已覆盖该教学动作。"
        else:
            _set_active_step(plan, target.step_id)
            target.adaptation_note = "用户追问触达该主题，本步骤提前进入 active。"
        _promote_next_planned_step(plan)

    active_after = _active_plan_step(plan)
    plan.current_step_id = active_after.step_id if active_after else None
    plan.update_notes = [
        *plan.update_notes[-4:],
        f"根据本轮回答更新计划: topics={','.join(sorted(topics)) or 'unknown'}。",
    ]
    plan.updated_at = now
    return plan


def _complete_active_step(plan: TeachingPlanState, *, note: str, now: datetime) -> None:
    active = _active_plan_step(plan)
    if active is not None:
        active.status = TeachingPlanStepStatus.COMPLETED
        active.adaptation_note = note
    _promote_next_planned_step(plan)
    active_after = _active_plan_step(plan)
    plan.current_step_id = active_after.step_id if active_after else None
    plan.updated_at = now
    plan.update_notes = [*plan.update_notes[-4:], note]


def _promote_next_planned_step(plan: TeachingPlanState) -> None:
    if _active_plan_step(plan) is not None:
        return
    next_step = _next_planned_step(plan)
    if next_step is not None:
        next_step.status = TeachingPlanStepStatus.ACTIVE
        next_step.adaptation_note = "上一步完成后自然推进到这里。"


def _set_active_step(plan: TeachingPlanState, step_id: str) -> None:
    for step in plan.steps:
        if step.step_id == step_id:
            step.status = TeachingPlanStepStatus.ACTIVE
        elif step.status == TeachingPlanStepStatus.ACTIVE:
            step.status = TeachingPlanStepStatus.PLANNED


def _mark_topics(
    student_state: StudentLearningState,
    *,
    topics: set[LearningGoal],
    message_id: str,
    student_signal: str,
    default_level: StudentCoverageLevel,
    evidence_refs: list[str],
    now: datetime,
) -> StudentLearningState:
    topic_map = {item.topic: item for item in student_state.topics}
    for goal in topics:
        if goal not in topic_map:
            topic_map[goal] = StudentLearningTopicState(
                topic=goal,
                coverage_level=StudentCoverageLevel.UNSEEN,
                confidence_of_estimate=ConfidenceLevel.LOW,
                likely_gap="后续对话中新出现的主题。",
                recommended_intervention=_default_intervention(goal),
            )
            student_state.topics.append(topic_map[goal])

    for topic_state in student_state.topics:
        if topic_state.topic not in topics:
            continue
        topic_state.coverage_level = _next_coverage_level(
            topic_state.coverage_level,
            default_level,
        )
        topic_state.confidence_of_estimate = _next_confidence(topic_state.coverage_level)
        topic_state.last_explained_at_message_id = message_id
        topic_state.student_signal = student_signal
        topic_state.supporting_evidence = _merge_evidence(topic_state.supporting_evidence, evidence_refs)
        topic_state.likely_gap = _likely_gap(topic_state.topic, topic_state.coverage_level)
        topic_state.recommended_intervention = _intervention_for_state(topic_state)

    student_state.update_notes = [
        *student_state.update_notes[-4:],
        f"根据本轮教学结果更新学生主题覆盖: {','.join(sorted(topics)) or 'unknown'}。",
    ]
    student_state.updated_at = now
    return student_state


def _build_log_from_states(
    conversation: ConversationState,
    plan: TeachingPlanState,
    student_state: StudentLearningState,
    *,
    decision: str,
    now: datetime,
) -> TeacherWorkingLog:
    active_step = _active_plan_step(plan)
    risks = [
        _risk_note(item)
        for item in student_state.topics
        if item.coverage_level == StudentCoverageLevel.NEEDS_REINFORCEMENT
    ] or ["继续保守估计学生理解：不要把“讲过”当作“已经掌握”。"]
    previous_log = conversation.teacher_working_log
    recent_decisions = previous_log.recent_decisions[-5:] if previous_log else []
    open_questions = previous_log.open_questions[-5:] if previous_log else []
    return TeacherWorkingLog(
        log_id=previous_log.log_id if previous_log else _new_id("teacher_log"),
        current_teaching_objective=active_step.title if active_step else f"围绕 {conversation.current_learning_goal} 回答",
        why_now=active_step.reason if active_step else "用户当前问题决定了本轮焦点。",
        active_topic_refs=[],
        current_plan_step_id=active_step.step_id if active_step else None,
        planned_transition=_next_transition(plan),
        student_risk_notes=risks[:5],
        recent_decisions=[*recent_decisions, decision][-6:],
        open_questions=open_questions,
        updated_at=now,
    )


def _active_plan_step(plan: TeachingPlanState | None) -> TeachingPlanStep | None:
    if plan is None:
        return None
    for step in plan.steps:
        if step.status == TeachingPlanStepStatus.ACTIVE:
            return step
    return None


def _next_planned_step(plan: TeachingPlanState) -> TeachingPlanStep | None:
    for step in sorted(plan.steps, key=lambda item: item.priority):
        if step.status == TeachingPlanStepStatus.PLANNED:
            return step
    return None


def _first_step_for_topics(
    plan: TeachingPlanState,
    topics: set[LearningGoal],
) -> TeachingPlanStep | None:
    for step in sorted(plan.steps, key=lambda item: item.priority):
        if step.goal in topics and step.status in {
            TeachingPlanStepStatus.ACTIVE,
            TeachingPlanStepStatus.PLANNED,
        }:
            return step
    return None


def _topics_from_answer(answer: StructuredAnswer) -> set[LearningGoal]:
    return {ref.topic for ref in answer.related_topic_refs}


def _coverage_level_for_turn(
    user_text: str,
    scenario: PromptScenario,
) -> StudentCoverageLevel:
    normalized = f" {user_text.casefold()} "
    if any(signal in normalized for signal in _CONFUSION_SIGNALS):
        return StudentCoverageLevel.NEEDS_REINFORCEMENT
    if scenario == PromptScenario.STAGE_SUMMARY:
        return StudentCoverageLevel.TEMPORARILY_STABLE
    return StudentCoverageLevel.INTRODUCED


def _next_coverage_level(
    current: StudentCoverageLevel,
    default_level: StudentCoverageLevel,
) -> StudentCoverageLevel:
    if default_level in {
        StudentCoverageLevel.NEEDS_REINFORCEMENT,
        StudentCoverageLevel.TEMPORARILY_STABLE,
    }:
        return default_level
    if current == StudentCoverageLevel.UNSEEN:
        return StudentCoverageLevel.INTRODUCED
    return current


def _next_confidence(level: StudentCoverageLevel) -> ConfidenceLevel:
    if level == StudentCoverageLevel.UNSEEN:
        return ConfidenceLevel.LOW
    return ConfidenceLevel.MEDIUM


def _student_signal(
    user_text: str,
    answer: StructuredAnswer,
    scenario: PromptScenario,
) -> str:
    if _coverage_level_for_turn(user_text, scenario) == StudentCoverageLevel.NEEDS_REINFORCEMENT:
        return "用户表达了困惑或要求重新解释。"
    if answer.structured_content.direct_explanation:
        return "本轮回答给出了直接解释，可视为该主题被覆盖。"
    return "本轮回答触达该主题，但缺少更明确的理解反馈。"


def _likely_gap(topic: LearningGoal, level: StudentCoverageLevel) -> str:
    if level == StudentCoverageLevel.NEEDS_REINFORCEMENT:
        return "学生可能还没有把概念和当前仓库的源码位置连接起来。"
    if level == StudentCoverageLevel.INTRODUCED:
        return "刚介绍过，尚不能假设学生已经能独立复述。"
    if topic == LearningGoal.FLOW:
        return "后续仍需确认学生是否能沿入口和主要调用关系复述主线。"
    return "暂无明确缺口，继续观察。"


def _intervention_for_state(topic_state: StudentLearningTopicState) -> str:
    if topic_state.coverage_level == StudentCoverageLevel.NEEDS_REINFORCEMENT:
        return "下一轮先换一种说法补框架，再给仓库中的具体落点。"
    if topic_state.coverage_level == StudentCoverageLevel.INTRODUCED:
        return "下一轮用一个具体文件或模块帮助学生巩固。"
    if topic_state.coverage_level == StudentCoverageLevel.PARTIALLY_GRASPED:
        return "可以继续沿计划推进，但保留一句回扣。"
    return _default_intervention(topic_state.topic)


def _default_intervention(goal: LearningGoal) -> str:
    return {
        LearningGoal.OVERVIEW: "先帮助学生建立仓库整体地图。",
        LearningGoal.STRUCTURE: "先讲目录分工，再落到关键目录。",
        LearningGoal.ENTRY: "先核实入口候选，再说明为什么它像入口。",
        LearningGoal.FLOW: "先给候选主线，再标注不确定处。",
        LearningGoal.MODULE: "先讲模块职责，再进入局部实现。",
        LearningGoal.DEPENDENCY: "先区分仓库内外来源，再解释关键依赖。",
        LearningGoal.LAYER: "先强调启发式分层，不做强断言。",
        LearningGoal.SUMMARY: "先总结已讲内容和未展开内容。",
    }.get(goal, "继续沿当前主题保守推进。")


def _risk_note(topic_state: StudentLearningTopicState) -> str:
    return f"{topic_state.topic}: {topic_state.likely_gap or '需要补强。'}"


def _answer_is_too_uncertain(answer: StructuredAnswer) -> bool:
    uncertainties = " ".join(answer.structured_content.uncertainties).casefold()
    evidence_count = sum(len(line.evidence_refs) for line in answer.structured_content.evidence_lines)
    return evidence_count == 0 and any(
        token in uncertainties for token in ("证据不足", "无法确认", "不确定", "unknown")
    )


def _merge_evidence(existing: list[str], new_items: list[str]) -> list[str]:
    merged = [*existing]
    for item in new_items:
        if item and item not in merged:
            merged.append(item)
    return merged[-12:]


def _next_transition(plan: TeachingPlanState | None) -> str | None:
    if plan is None:
        return None
    active = _active_plan_step(plan)
    next_step = _next_planned_step(plan)
    if active and next_step:
        return f"完成“{active.title}”后，转入“{next_step.title}”。"
    if next_step:
        return f"下一轮可推进到“{next_step.title}”。"
    return "当前计划暂无明确待推进步骤，适合做阶段总结或按用户问题改道。"


def _decision_note(topics: set[LearningGoal], scenario: PromptScenario) -> str:
    ordered = ", ".join(sorted(topics)) or "unknown"
    return f"本轮场景 {scenario} 覆盖主题 {ordered}，已同步计划和学生状态。"


def _suggestion_text_for_step(step: TeachingPlanStep) -> str:
    if step.status == TeachingPlanStepStatus.ACTIVE:
        return f"继续看“{step.title}”吗？"
    return f"下一步要不要看“{step.title}”？"


def _reinforcement_notes(
    student_state: StudentLearningState | None,
    topic_goals: set[LearningGoal],
) -> list[str]:
    if not student_state:
        return []
    notes: list[str] = []
    for topic_state in student_state.topics:
        if topic_state.topic not in topic_goals:
            continue
        if topic_state.coverage_level == StudentCoverageLevel.NEEDS_REINFORCEMENT:
            notes.append(
                f"{topic_state.topic}: {topic_state.recommended_intervention or topic_state.likely_gap or '需要补强。'}"
            )
    return notes[:4]


def _decision_objective(
    conversation: ConversationState,
    active_step: TeachingPlanStep | None,
    action: TeachingDecisionAction,
) -> str:
    if action == TeachingDecisionAction.REINFORCE_STUDENT_GAP:
        return f"先补强 {conversation.current_learning_goal} 的理解缺口，再回到教学主线。"
    if action == TeachingDecisionAction.SUMMARIZE_PROGRESS:
        return "总结目前已经讲过的内容、仍不确定的部分和下一步路线。"
    if active_step:
        return active_step.title
    if conversation.teacher_working_log:
        return conversation.teacher_working_log.current_teaching_objective
    return f"围绕 {conversation.current_learning_goal} 回答，并保持主动带路。"


def _directive_mode(
    action: TeachingDecisionAction | None,
    scenario: PromptScenario,
) -> str:
    if scenario == PromptScenario.STAGE_SUMMARY:
        return "summarize"
    if scenario == PromptScenario.GOAL_SWITCH:
        return "goal_switch"
    if action == TeachingDecisionAction.REINFORCE_STUDENT_GAP:
        return "reinforce"
    return "answer"


def _directive_focus_topics(
    conversation: ConversationState,
    active_step: TeachingPlanStep | None,
) -> list[str]:
    topics: list[str] = [str(conversation.current_learning_goal)]
    if active_step is not None and str(active_step.goal) not in topics:
        topics.append(str(active_step.goal))
    return topics[:2]


def _directive_turn_goal(
    conversation: ConversationState,
    active_step: TeachingPlanStep | None,
    mode: str,
) -> str:
    if mode == "summarize":
        return "Summarize what is verified, what remains uncertain, and the next natural step."
    if mode == "goal_switch":
        return f"Adapt to the user's new focus on {conversation.current_learning_goal}."
    if mode == "reinforce":
        return f"Clarify the current {conversation.current_learning_goal} topic before moving on."
    if active_step is not None:
        return f"Answer the question while staying aligned with {active_step.title}."
    return f"Answer the current question about {conversation.current_learning_goal}."


def _recently_explained_message_ids(conversation: ConversationState) -> list[str]:
    message_ids: list[str] = []
    for item in conversation.explained_items[-6:]:
        if item.explained_at_message_id not in message_ids:
            message_ids.append(item.explained_at_message_id)
    return message_ids[-4:]


def _directive_transition_hint(
    conversation: ConversationState,
    active_step: TeachingPlanStep | None,
    mode: str,
    user_text: str,
) -> str | None:
    if mode == "answer" and active_step is None:
        return "If it helps, connect the local answer back to the broader repository map in one sentence."
    if mode == "answer" and user_text.strip():
        return "Answer the user's concrete question first, then add at most one short bridge to the teaching path."
    if conversation.teacher_working_log and conversation.teacher_working_log.planned_transition:
        return conversation.teacher_working_log.planned_transition
    if active_step is not None:
        return f"After this turn, the next natural step is {active_step.title}."
    return None


def _summarize_user_text(user_text: str) -> str | None:
    text = " ".join(user_text.split())
    if not text:
        return None
    return text[:180] + "..." if len(text) > 180 else text


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def utc_now() -> datetime:
    return datetime.now(UTC)
