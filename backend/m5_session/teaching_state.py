from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from backend.contracts.domain import (
    ConversationState,
    InitialReportAnswer,
    StudentLearningState,
    StudentLearningTopicState,
    StructuredAnswer,
    Suggestion,
    TeachingDebugEvent,
    TeachingDecisionSnapshot,
    TeacherWorkingLog,
    TeachingPlanState,
    TeachingPlanStep,
    TeachingSkeleton,
    TopicRef,
)
from backend.contracts.enums import (
    ConfidenceLevel,
    LearningGoal,
    PromptScenario,
    ReadingTargetType,
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
    "why",
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
    skeleton: TeachingSkeleton,
    *,
    now: datetime,
) -> TeachingPlanState:
    steps: list[TeachingPlanStep] = []
    seen: set[tuple[str, str]] = set()

    def add_step(
        *,
        title: str,
        goal: LearningGoal,
        target_scope: str,
        reason: str,
        expected_learning_gain: str,
        source_topic_refs: list[TopicRef],
        depends_on: list[str] | None = None,
        adaptation_note: str | None = None,
    ) -> None:
        key = (goal, target_scope)
        if key in seen:
            return
        seen.add(key)
        step_id = f"plan_step_{len(steps) + 1}"
        steps.append(
            TeachingPlanStep(
                step_id=step_id,
                title=title,
                goal=goal,
                target_scope=target_scope,
                reason=reason,
                expected_learning_gain=expected_learning_gain,
                status=TeachingPlanStepStatus.ACTIVE
                if not steps
                else TeachingPlanStepStatus.PLANNED,
                priority=len(steps) + 1,
                depends_on=depends_on or [],
                source_topic_refs=source_topic_refs,
                adaptation_note=adaptation_note,
            )
        )

    first_goal = LearningGoal.ENTRY if skeleton.entry_section.entries else LearningGoal.STRUCTURE
    add_step(
        title="确定第一阅读起点",
        goal=first_goal,
        target_scope=skeleton.recommended_first_step.target,
        reason=skeleton.recommended_first_step.reason,
        expected_learning_gain=skeleton.recommended_first_step.learning_gain,
        source_topic_refs=_refs_for_goal(skeleton, first_goal)[:4],
        adaptation_note="由 M4 recommended_first_step 转成教学动作。",
    )

    for focus in skeleton.focus_points[:4]:
        add_step(
            title=focus.title,
            goal=focus.topic,
            target_scope=_scope_from_refs(focus.related_refs) or focus.topic,
            reason=focus.reason,
            expected_learning_gain=f"建立对“{focus.title}”的工程认知。",
            source_topic_refs=focus.related_refs[:6],
            adaptation_note="由 M4 focus_points 转成课堂推进点。",
        )

    previous_step_id = steps[-1].step_id if steps else None
    for reading_step in skeleton.reading_path_preview[:6]:
        goal = _goal_for_reading_step(reading_step.target_type, reading_step.step_no)
        depends_on = [previous_step_id] if previous_step_id else []
        add_step(
            title=f"阅读步骤 {reading_step.step_no}: {reading_step.target}",
            goal=goal,
            target_scope=reading_step.target,
            reason=reading_step.reason,
            expected_learning_gain=reading_step.learning_gain,
            source_topic_refs=_refs_for_goal(skeleton, goal)[:4],
            depends_on=depends_on,
            adaptation_note="由 M4 reading_path_preview 转成可更新教学计划。",
        )
        previous_step_id = steps[-1].step_id if steps else previous_step_id

    current_step_id = steps[0].step_id if steps else None
    return TeachingPlanState(
        plan_id=_new_id("teach_plan"),
        generated_from_skeleton_id=skeleton.skeleton_id,
        current_step_id=current_step_id,
        steps=steps,
        update_notes=["基于教学骨架初始化教学计划表。"],
        updated_at=now,
    )


def build_initial_student_learning_state(
    skeleton: TeachingSkeleton,
    *,
    now: datetime,
) -> StudentLearningState:
    available_goals = _goals_with_skeleton_refs(skeleton)
    topics: list[StudentLearningTopicState] = []
    for goal in _TEACHING_GOAL_ORDER:
        likely_gap = (
            "该主题在当前骨架中证据较少，后续讲解需要更保守。"
            if goal not in available_goals and goal != LearningGoal.SUMMARY
            else "新会话尚未确认学生对该主题的理解。"
        )
        topics.append(
            StudentLearningTopicState(
                topic=goal,
                coverage_level=StudentCoverageLevel.UNSEEN,
                confidence_of_estimate=ConfidenceLevel.LOW,
                likely_gap=likely_gap,
                recommended_intervention=_default_intervention(goal),
                supporting_evidence=[],
            )
        )
    return StudentLearningState(
        state_id=_new_id("student_state"),
        topics=topics,
        update_notes=["新会话初始化：所有主题按未讲解处理，避免假装知道学生理解程度。"],
        updated_at=now,
    )


def build_initial_teacher_working_log(
    skeleton: TeachingSkeleton,
    plan: TeachingPlanState,
    student_state: StudentLearningState,
    *,
    now: datetime,
) -> TeacherWorkingLog:
    active_step = _active_plan_step(plan)
    risk_notes = [
        "学生刚进入仓库，默认没有当前仓库的工程地图。",
        "学生理解状态只能按教学信号保守估计，不做心理判断。",
    ]
    if any(item.coverage_level == StudentCoverageLevel.UNSEEN for item in student_state.topics):
        risk_notes.append("多数主题尚未覆盖，下一轮应先补框架再深入细节。")
    return TeacherWorkingLog(
        log_id=_new_id("teacher_log"),
        current_teaching_objective=(
            active_step.title if active_step else "先建立当前仓库的整体观察框架。"
        ),
        why_now=active_step.reason if active_step else skeleton.overview.summary,
        active_topic_refs=active_step.source_topic_refs if active_step else [],
        current_plan_step_id=active_step.step_id if active_step else None,
        planned_transition=_next_transition(plan),
        student_risk_notes=risk_notes,
        recent_decisions=["生成初始教学计划、学生状态表和教师工作日志。"],
        open_questions=[item.description for item in skeleton.unknown_section[:5]],
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
    topics = {LearningGoal.OVERVIEW, *(item.topic for item in answer.initial_report_content.focus_points)}
    student_state = _mark_topics(
        student_state,
        topics=topics,
        message_id=message_id,
        student_signal="首轮报告已覆盖观察框架和阅读路线。",
        default_level=StudentCoverageLevel.INTRODUCED,
        evidence_refs=answer.used_evidence_refs,
        now=now,
    )
    log = _build_log_from_states(
        conversation,
        plan,
        student_state,
        decision="首轮报告完成：已向学生交代仓库地图、第一阅读起点和后续路线。",
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
    candidates = [step for step in plan.steps if step.status == TeachingPlanStepStatus.ACTIVE]
    candidates.extend(step for step in plan.steps if step.status == TeachingPlanStepStatus.PLANNED)
    suggestions: list[Suggestion] = []
    seen: set[str] = set()
    for step in candidates:
        if len(suggestions) >= 3:
            break
        text = _suggestion_text_for_step(step)
        if text in seen:
            continue
        suggestions.append(
            Suggestion(
                suggestion_id=f"sug_{step.step_id}",
                text=text,
                target_goal=step.goal,
                related_topic_refs=step.source_topic_refs[:3],
            )
        )
        seen.add(text)
    return suggestions


def build_teaching_decision(
    conversation: ConversationState,
    *,
    user_text: str,
    scenario: PromptScenario,
    topic_slice: list[TopicRef],
    now: datetime,
) -> TeachingDecisionSnapshot:
    plan = conversation.teaching_plan_state
    student_state = conversation.student_learning_state
    active_step = _active_plan_step(plan) if plan else None
    topic_goals = {ref.topic for ref in topic_slice} or {conversation.current_learning_goal}
    reinforcement_notes = _reinforcement_notes(student_state, topic_goals)

    if scenario == PromptScenario.STAGE_SUMMARY:
        action = TeachingDecisionAction.SUMMARIZE_PROGRESS
        reason = "用户要求阶段性总结，本轮优先回顾已讲内容和未展开内容。"
    elif reinforcement_notes:
        action = TeachingDecisionAction.REINFORCE_STUDENT_GAP
        reason = "学生状态表显示当前主题需要强化，本轮先补框架和仓库落点。"
    elif scenario == PromptScenario.GOAL_SWITCH:
        action = TeachingDecisionAction.ADAPT_TO_USER_GOAL
        reason = "用户显式切换学习目标，本轮先顺应新目标并局部改道。"
    elif active_step and active_step.goal in topic_goals:
        action = TeachingDecisionAction.PROCEED_WITH_PLAN
        reason = "用户问题与当前 active 教学计划一致，本轮继续沿计划推进。"
    else:
        action = TeachingDecisionAction.ANSWER_LOCAL_QUESTION
        reason = "用户问题没有完全落在当前 active 计划上，本轮先回答局部问题，再回扣主线。"

    objective = _decision_objective(conversation, active_step, action)
    return TeachingDecisionSnapshot(
        decision_id=_new_id("teach_decision"),
        scenario=scenario,
        user_message_summary=_summarize_user_text(user_text),
        selected_action=action,
        selected_plan_step_id=active_step.step_id if active_step else None,
        selected_plan_step_title=active_step.title if active_step else None,
        teaching_objective=objective,
        decision_reason=reason,
        student_state_notes=reinforcement_notes
        or (conversation.teacher_working_log.student_risk_notes[:3] if conversation.teacher_working_log else []),
        planned_transition=conversation.teacher_working_log.planned_transition
        if conversation.teacher_working_log
        else _next_transition(plan) if plan else None,
        topic_refs=topic_slice[:8],
        created_at=now,
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


def _copy_plan(plan: TeachingPlanState | None, now: datetime) -> TeachingPlanState:
    if plan is not None:
        return plan.model_copy(deep=True, update={"updated_at": now})
    return TeachingPlanState(
        plan_id=_new_id("teach_plan"),
        generated_from_skeleton_id="unknown",
        current_step_id=None,
        steps=[],
        update_notes=["缺少教学骨架计划，保守跳过计划更新。"],
        updated_at=now,
    )


def _copy_student_state(
    student_state: StudentLearningState | None,
    now: datetime,
) -> StudentLearningState:
    if student_state is not None:
        return student_state.model_copy(deep=True, update={"updated_at": now})
    return StudentLearningState(
        state_id=_new_id("student_state"),
        topics=[],
        update_notes=["缺少学生状态表，保守跳过学生状态更新。"],
        updated_at=now,
    )


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
    active = _active_plan_step(plan)
    target = _first_step_for_topics(plan, topics) or active
    if target is None:
        return plan

    if active and active.step_id != target.step_id and active.status == TeachingPlanStepStatus.ACTIVE:
        active.status = TeachingPlanStepStatus.PLANNED
        active.adaptation_note = "用户问题临时切换了课堂焦点，先保留该步骤。"

    if _answer_is_too_uncertain(answer):
        target.status = TeachingPlanStepStatus.DEFERRED
        target.adaptation_note = "本轮证据不足，先标记为 deferred，后续补证据再继续。"
    elif scenario == PromptScenario.GOAL_SWITCH:
        target.status = TeachingPlanStepStatus.ACTIVE
        target.adaptation_note = "用户显式切换学习目标，本步骤被提前激活。"
    elif target.status == TeachingPlanStepStatus.ACTIVE:
        target.status = TeachingPlanStepStatus.COMPLETED
        target.adaptation_note = "本轮回答已覆盖该教学动作，后续进入下一步。"
    elif target.status == TeachingPlanStepStatus.PLANNED:
        target.status = TeachingPlanStepStatus.ACTIVE
        target.adaptation_note = "用户追问触达该主题，本步骤提前进入 active。"

    next_step = _next_planned_step(plan)
    if next_step and not _active_plan_step(plan):
        next_step.status = TeachingPlanStepStatus.ACTIVE
        next_step.adaptation_note = "上一教学动作结束后自然推进到这里。"

    active_after = _active_plan_step(plan)
    plan.current_step_id = active_after.step_id if active_after else None
    plan.update_notes = [
        *plan.update_notes[-4:],
        f"根据本轮回答更新计划：topics={','.join(sorted(topics)) or 'unknown'}。",
    ]
    plan.updated_at = now
    return plan


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
    if not student_state.topics:
        student_state.topics = [
            StudentLearningTopicState(
                topic=goal,
                coverage_level=StudentCoverageLevel.UNSEEN,
                confidence_of_estimate=ConfidenceLevel.LOW,
                likely_gap="此前缺少学生状态记录。",
                recommended_intervention=_default_intervention(goal),
            )
            for goal in _TEACHING_GOAL_ORDER
        ]

    seen_goals = {item.topic for item in student_state.topics}
    for goal in topics:
        if goal not in seen_goals:
            student_state.topics.append(
                StudentLearningTopicState(
                    topic=goal,
                    coverage_level=StudentCoverageLevel.UNSEEN,
                    confidence_of_estimate=ConfidenceLevel.LOW,
                    likely_gap="后续对话中新出现的主题。",
                    recommended_intervention=_default_intervention(goal),
                )
            )

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
        topic_state.supporting_evidence = _merge_evidence(
            topic_state.supporting_evidence,
            evidence_refs,
        )
        topic_state.likely_gap = _likely_gap(topic_state.topic, topic_state.coverage_level)
        topic_state.recommended_intervention = _intervention_for_state(topic_state)

    student_state.update_notes = [
        *student_state.update_notes[-4:],
        f"根据本轮教学结果更新学生主题覆盖：{','.join(sorted(topics)) or 'unknown'}。",
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
    ]
    if not risks:
        risks = [
            "继续保守估计学生理解：没有明确反馈前，不把“讲过”当成“已经掌握”。"
        ]
    previous_log = conversation.teacher_working_log
    open_questions = previous_log.open_questions[-5:] if previous_log else []
    recent_decisions = previous_log.recent_decisions[-5:] if previous_log else []
    return TeacherWorkingLog(
        log_id=previous_log.log_id if previous_log else _new_id("teacher_log"),
        current_teaching_objective=(
            active_step.title if active_step else f"围绕 {conversation.current_learning_goal} 回答。"
        ),
        why_now=active_step.reason if active_step else "用户当前问题决定了本轮焦点。",
        active_topic_refs=active_step.source_topic_refs if active_step else [],
        current_plan_step_id=active_step.step_id if active_step else None,
        planned_transition=_next_transition(plan),
        student_risk_notes=risks[:5],
        recent_decisions=[*recent_decisions, decision][-6:],
        open_questions=open_questions,
        updated_at=now,
    )


def _refs_for_goal(skeleton: TeachingSkeleton, goal: LearningGoal) -> list[TopicRef]:
    topic_index = skeleton.topic_index
    by_goal = {
        LearningGoal.OVERVIEW: [
            *topic_index.structure_refs,
            *topic_index.entry_refs,
            *topic_index.flow_refs,
        ],
        LearningGoal.STRUCTURE: topic_index.structure_refs,
        LearningGoal.ENTRY: topic_index.entry_refs,
        LearningGoal.FLOW: topic_index.flow_refs,
        LearningGoal.MODULE: topic_index.module_refs,
        LearningGoal.LAYER: topic_index.layer_refs,
        LearningGoal.DEPENDENCY: topic_index.dependency_refs,
        LearningGoal.SUMMARY: topic_index.reading_path_refs,
    }
    return list(by_goal.get(goal, []))


def _goals_with_skeleton_refs(skeleton: TeachingSkeleton) -> set[LearningGoal]:
    goals = {focus.topic for focus in skeleton.focus_points}
    for attr in (
        "structure_refs",
        "entry_refs",
        "flow_refs",
        "layer_refs",
        "dependency_refs",
        "module_refs",
        "reading_path_refs",
        "unknown_refs",
    ):
        goals.update(ref.topic for ref in getattr(skeleton.topic_index, attr))
    return goals


def _goal_for_reading_step(target_type: ReadingTargetType, step_no: int) -> LearningGoal:
    if step_no == 1:
        return LearningGoal.ENTRY
    if target_type == ReadingTargetType.FLOW:
        return LearningGoal.FLOW
    if target_type == ReadingTargetType.MODULE:
        return LearningGoal.MODULE
    if target_type == ReadingTargetType.DIRECTORY:
        return LearningGoal.STRUCTURE
    return LearningGoal.MODULE


def _scope_from_refs(refs: list[TopicRef]) -> str | None:
    parts = [ref.summary or ref.target_id for ref in refs[:3]]
    return ", ".join(part for part in parts if part) or None


def _active_plan_step(plan: TeachingPlanState) -> TeachingPlanStep | None:
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
    if default_level == StudentCoverageLevel.NEEDS_REINFORCEMENT:
        return default_level
    if default_level == StudentCoverageLevel.TEMPORARILY_STABLE:
        return default_level
    if current == StudentCoverageLevel.UNSEEN:
        return StudentCoverageLevel.INTRODUCED
    if current in {
        StudentCoverageLevel.INTRODUCED,
        StudentCoverageLevel.NEEDS_REINFORCEMENT,
    }:
        return StudentCoverageLevel.PARTIALLY_GRASPED
    return current


def _next_confidence(level: StudentCoverageLevel) -> ConfidenceLevel:
    if level == StudentCoverageLevel.TEMPORARILY_STABLE:
        return ConfidenceLevel.MEDIUM
    if level == StudentCoverageLevel.NEEDS_REINFORCEMENT:
        return ConfidenceLevel.MEDIUM
    if level == StudentCoverageLevel.PARTIALLY_GRASPED:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def _student_signal(
    user_text: str,
    answer: StructuredAnswer,
    scenario: PromptScenario,
) -> str:
    if _coverage_level_for_turn(user_text, scenario) == StudentCoverageLevel.NEEDS_REINFORCEMENT:
        return "用户表达了困惑或要求重新解释。"
    if answer.structured_content.direct_explanation:
        return "本轮回答已给出直接解释，可视为该主题被教学覆盖。"
    return "本轮回答触达该主题，但缺少更明确的理解反馈。"


def _likely_gap(topic: LearningGoal, level: StudentCoverageLevel) -> str:
    if level == StudentCoverageLevel.NEEDS_REINFORCEMENT:
        return "学生可能还没有把概念和当前仓库落点连接起来。"
    if level == StudentCoverageLevel.INTRODUCED:
        return "刚介绍过，尚不能假设学生已经能独立复述。"
    if topic == LearningGoal.FLOW:
        return "后续仍需确认学生是否能顺着入口、模块和去向复述主线。"
    return "暂无明确缺口；继续用下一轮问题观察。"


def _intervention_for_state(topic_state: StudentLearningTopicState) -> str:
    if topic_state.coverage_level == StudentCoverageLevel.NEEDS_REINFORCEMENT:
        return "下一轮先换一种说法补框架，再给仓库中的具体落点。"
    if topic_state.coverage_level == StudentCoverageLevel.INTRODUCED:
        return "下一轮用一个具体文件或模块帮助学生巩固。"
    if topic_state.coverage_level == StudentCoverageLevel.PARTIALLY_GRASPED:
        return "可以继续沿计划推进，但要保留一句回扣。"
    return _default_intervention(topic_state.topic)


def _default_intervention(goal: LearningGoal) -> str:
    return {
        LearningGoal.OVERVIEW: "先帮学生建立仓库整体地图。",
        LearningGoal.STRUCTURE: "先讲目录分工，再落到关键目录。",
        LearningGoal.ENTRY: "先定位入口候选，再说明为什么像入口。",
        LearningGoal.FLOW: "先给候选主线，再标注不确定处。",
        LearningGoal.MODULE: "先讲模块职责，再进入局部实现。",
        LearningGoal.DEPENDENCY: "先区分内部、标准库、第三方和未知。",
        LearningGoal.LAYER: "先强调启发式分层，不做强断言。",
        LearningGoal.SUMMARY: "先总结已讲内容和未展开内容。",
    }.get(goal, "继续沿当前主题保守推进。")


def _risk_note(topic_state: StudentLearningTopicState) -> str:
    return f"{topic_state.topic}: {topic_state.likely_gap or '需要补强。'}"


def _answer_is_too_uncertain(answer: StructuredAnswer) -> bool:
    uncertainties = " ".join(answer.structured_content.uncertainties).casefold()
    if any(token in uncertainties for token in ("没有额外不确定", "暂无", "无额外不确定")):
        return False
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


def _next_transition(plan: TeachingPlanState) -> str | None:
    active = _active_plan_step(plan)
    next_step = _next_planned_step(plan)
    if active and next_step:
        return f"完成“{active.title}”后，转入“{next_step.title}”。"
    if next_step:
        return f"下一轮可推进到“{next_step.title}”。"
    return "当前计划已无明确待推进步骤，适合做阶段性总结或按用户问题改道。"


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


def _summarize_user_text(user_text: str) -> str | None:
    text = " ".join(user_text.split())
    if not text:
        return None
    return text[:180] + "..." if len(text) > 180 else text


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def utc_now() -> datetime:
    return datetime.now(UTC)
