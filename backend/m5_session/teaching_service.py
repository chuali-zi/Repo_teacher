from __future__ import annotations

from backend.contracts.domain import (
    ExplainedItemRef,
    InitialReportAnswer,
    MessageRecord,
    OutputContract,
    PromptBuildInput,
    SessionContext,
    StructuredAnswer,
    TopicRef,
)
from backend.contracts.enums import (
    DepthLevel,
    LearningGoal,
    MessageRole,
    MessageSection,
    MessageType,
    PromptScenario,
    TeachingDebugEventType,
    TeachingStage,
)
from backend.llm_tools import build_llm_tool_context
from backend.m5_session.common import GOAL_KEYWORDS, TOPIC_ATTRS_BY_GOAL, utc_now
from backend.m5_session.teaching_state import (
    append_teaching_debug_event,
    build_initial_student_learning_state,
    build_initial_teacher_working_log,
    build_initial_teaching_plan,
    build_teaching_decision,
    plan_based_suggestions,
    update_after_initial_report,
    update_after_structured_answer,
)
from backend.m6_response.suggestion_generator import generate_next_step_suggestions


class TeachingService:
    def build_initial_report_prompt_input(self, session: SessionContext) -> PromptBuildInput:
        topic_slice = self.topic_slice_for_goal(session.teaching_skeleton, LearningGoal.OVERVIEW)
        user_text = "请先帮我建立这个仓库的整体理解，并给出一条主动引导的阅读计划。"
        self.prepare_teaching_decision(
            session,
            user_text=user_text,
            scenario=PromptScenario.INITIAL_REPORT,
            topic_slice=topic_slice,
        )
        return PromptBuildInput(
            scenario=PromptScenario.INITIAL_REPORT,
            user_message=user_text,
            teaching_skeleton=session.teaching_skeleton,
            topic_slice=topic_slice,
            tool_context=self.build_tool_context(
                session,
                topic_slice,
                scenario=PromptScenario.INITIAL_REPORT,
            ),
            conversation_state=session.conversation.model_copy(deep=True),
            history_summary=None,
            depth_level=session.conversation.depth_level,
            output_contract=self.output_contract(session.conversation.depth_level),
        )

    def build_prompt_input(self, session: SessionContext) -> PromptBuildInput:
        last_user_message = self.last_user_message(session)
        user_text = last_user_message.raw_text.strip()
        previous_goal = session.conversation.current_learning_goal
        previous_depth = session.conversation.depth_level
        goal = self.infer_learning_goal(session, user_text)
        depth = self.infer_depth_level(session.conversation.depth_level, user_text)
        scenario = self.infer_prompt_scenario(user_text)
        if scenario == PromptScenario.FOLLOW_UP:
            if goal != previous_goal and self.looks_like_goal_switch(user_text):
                scenario = PromptScenario.GOAL_SWITCH
            elif depth != previous_depth and self.looks_like_depth_adjustment(user_text):
                scenario = PromptScenario.DEPTH_ADJUSTMENT

        session.conversation.current_learning_goal = goal
        session.conversation.depth_level = depth
        topic_slice = self.topic_slice_for_goal(session.teaching_skeleton, goal)
        self.prepare_teaching_decision(
            session,
            user_text=user_text,
            scenario=scenario,
            topic_slice=topic_slice,
            message_id=last_user_message.message_id,
        )
        return PromptBuildInput(
            scenario=scenario,
            user_message=user_text,
            teaching_skeleton=session.teaching_skeleton,
            topic_slice=topic_slice,
            tool_context=self.build_tool_context(session, topic_slice, scenario=scenario),
            conversation_state=session.conversation.model_copy(deep=True),
            history_summary=self.history_summary(session),
            depth_level=depth,
            output_contract=self.output_contract(depth),
            enable_tool_calls=scenario
            in (
                PromptScenario.FOLLOW_UP,
                PromptScenario.GOAL_SWITCH,
                PromptScenario.DEPTH_ADJUSTMENT,
            ),
        )

    def build_tool_context(
        self,
        session: SessionContext,
        topic_slice: list[TopicRef],
        *,
        scenario: PromptScenario | None = None,
    ):
        if not (
            session.repository
            and session.file_tree
            and session.analysis
            and session.teaching_skeleton
        ):
            raise RuntimeError("Cannot build LLM tool context before analysis completes")
        return build_llm_tool_context(
            repository=session.repository,
            file_tree=session.file_tree,
            analysis=session.analysis,
            teaching_skeleton=session.teaching_skeleton,
            conversation=session.conversation,
            topic_slice=topic_slice,
            scenario=scenario,
        )

    def topic_slice_for_goal(self, skeleton, goal: LearningGoal) -> list[TopicRef]:
        topic_index = skeleton.topic_index
        refs: list[TopicRef] = []
        for attr in TOPIC_ATTRS_BY_GOAL.get(goal, ("structure_refs",)):
            refs.extend(getattr(topic_index, attr))
        if not refs:
            refs = self.all_topic_refs(skeleton)
        return self.dedupe_topic_refs(refs)[:20]

    def all_topic_refs(self, skeleton) -> list[TopicRef]:
        topic_index = skeleton.topic_index
        refs: list[TopicRef] = []
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
            refs.extend(getattr(topic_index, attr))
        return self.dedupe_topic_refs(refs)

    def dedupe_topic_refs(self, refs: list[TopicRef]) -> list[TopicRef]:
        deduped: list[TopicRef] = []
        seen: set[str] = set()
        for ref in refs:
            if ref.ref_id in seen:
                continue
            deduped.append(ref)
            seen.add(ref.ref_id)
        return deduped

    def history_summary(self, session: SessionContext) -> str | None:
        if session.conversation.history_summary:
            return session.conversation.history_summary
        return self.summarize_recent_messages(session.conversation.messages[:-1])

    def update_history_summary(self, session: SessionContext) -> None:
        session.conversation.history_summary = self.summarize_recent_messages(
            session.conversation.messages
        )

    def summarize_recent_messages(self, messages: list[MessageRecord]) -> str | None:
        if not messages:
            return None
        lines: list[str] = []
        for message in messages[-10:]:
            if message.role == MessageRole.USER:
                role = "用户"
            elif message.role == MessageRole.AGENT:
                role = "助手"
            else:
                role = "系统"
            text = " ".join(message.raw_text.split())
            if len(text) > 180:
                text = f"{text[:177]}..."
            lines.append(f"{role}: {text}")
        summary = "\n".join(lines)
        return summary[-2000:] if summary else None

    def ensure_answer_suggestions(
        self,
        session: SessionContext,
        answer: StructuredAnswer,
    ) -> None:
        suggestions = self.merge_teacher_suggestions(
            answer.suggestions,
            plan_based_suggestions(session.conversation),
        )
        if not suggestions:
            suggestions = generate_next_step_suggestions(
                session.conversation,
                self.all_topic_refs(session.teaching_skeleton),
            )
        answer.suggestions = suggestions
        answer.structured_content.next_steps = suggestions

    def ensure_initial_report_suggestions(
        self,
        session: SessionContext,
        answer: InitialReportAnswer,
    ) -> None:
        suggestions = self.merge_teacher_suggestions(
            answer.suggestions,
            plan_based_suggestions(session.conversation),
        )
        if not suggestions:
            suggestions = session.teaching_skeleton.suggested_next_questions[:3]
        answer.suggestions = suggestions
        answer.initial_report_content.suggested_next_questions = suggestions

    def merge_teacher_suggestions(self, primary: list, secondary: list) -> list:
        merged = []
        seen_texts: set[str] = set()
        for suggestion in [*primary, *secondary]:
            if len(merged) >= 3:
                break
            text = suggestion.text.strip()
            if not text or text in seen_texts:
                continue
            merged.append(suggestion)
            seen_texts.add(text)
        return merged

    def prepare_teaching_decision(
        self,
        session: SessionContext,
        *,
        user_text: str,
        scenario: PromptScenario,
        topic_slice: list[TopicRef],
        message_id: str | None = None,
    ) -> None:
        now = utc_now()
        active_step = None
        if session.conversation.teaching_plan_state:
            active_step = next(
                (
                    step
                    for step in session.conversation.teaching_plan_state.steps
                    if step.status == "active"
                ),
                None,
            )
        append_teaching_debug_event(
            session.conversation,
            TeachingDebugEventType.TEACHER_TURN_STARTED,
            summary="老师开始本轮教学决策。",
            now=now,
            message_id=message_id,
            plan_step_id=active_step.step_id if active_step else None,
            details={
                "scenario": scenario,
                "current_learning_goal": session.conversation.current_learning_goal,
                "topic_ref_count": len(topic_slice),
            },
        )
        if active_step:
            append_teaching_debug_event(
                session.conversation,
                TeachingDebugEventType.TEACHING_PLAN_SELECTED,
                summary=f"选中教学计划步骤：{active_step.title}",
                now=now,
                message_id=message_id,
                plan_step_id=active_step.step_id,
                details={
                    "goal": active_step.goal,
                    "target_scope": active_step.target_scope,
                    "status": active_step.status,
                },
            )
        decision = build_teaching_decision(
            session.conversation,
            user_text=user_text,
            scenario=scenario,
            topic_slice=topic_slice,
            now=now,
        )
        session.conversation.current_teaching_decision = decision
        append_teaching_debug_event(
            session.conversation,
            TeachingDebugEventType.TEACHING_DECISION_BUILT,
            summary=decision.decision_reason,
            now=now,
            message_id=message_id,
            plan_step_id=decision.selected_plan_step_id,
            details={
                "decision_id": decision.decision_id,
                "selected_action": decision.selected_action,
                "teaching_objective": decision.teaching_objective,
                "student_state_notes": decision.student_state_notes,
            },
        )

    def initialize_teaching_state(self, session: SessionContext) -> None:
        now = utc_now()
        plan = build_initial_teaching_plan(session.teaching_skeleton, now=now)
        student_state = build_initial_student_learning_state(session.teaching_skeleton, now=now)
        teacher_log = build_initial_teacher_working_log(
            session.teaching_skeleton,
            plan,
            student_state,
            now=now,
        )
        session.conversation.teaching_plan_state = plan
        session.conversation.student_learning_state = student_state
        session.conversation.teacher_working_log = teacher_log
        append_teaching_debug_event(
            session.conversation,
            TeachingDebugEventType.TEACHING_STATE_INITIALIZED,
            summary="已初始化教学计划、学生学习状态和教师工作日志。",
            now=now,
            plan_step_id=plan.current_step_id,
            details={
                "plan_step_count": len(plan.steps),
                "student_topic_count": len(student_state.topics),
            },
        )
        append_teaching_debug_event(
            session.conversation,
            TeachingDebugEventType.TEACHING_PLAN_SELECTED,
            summary="初始教学计划已选中第一步。",
            now=now,
            plan_step_id=plan.current_step_id,
            details={"current_step_id": plan.current_step_id},
        )

    def update_teaching_state_after_initial_report(
        self,
        session: SessionContext,
        answer: InitialReportAnswer,
        message_id: str,
    ) -> None:
        update = update_after_initial_report(
            session.conversation,
            answer,
            message_id=message_id,
            now=utc_now(),
        )
        session.conversation.teaching_plan_state = update.teaching_plan_state
        session.conversation.student_learning_state = update.student_learning_state
        session.conversation.teacher_working_log = update.teacher_working_log
        self.record_teaching_state_update_events(session, message_id=message_id)

    def update_teaching_state_after_answer(
        self,
        session: SessionContext,
        answer: StructuredAnswer,
        *,
        user_text: str,
        message_id: str,
        scenario: PromptScenario,
    ) -> None:
        update = update_after_structured_answer(
            session.conversation,
            answer,
            user_text=user_text,
            message_id=message_id,
            scenario=scenario,
            now=utc_now(),
        )
        session.conversation.teaching_plan_state = update.teaching_plan_state
        session.conversation.student_learning_state = update.student_learning_state
        session.conversation.teacher_working_log = update.teacher_working_log
        self.record_teaching_state_update_events(session, message_id=message_id)

    def record_teaching_state_update_events(
        self,
        session: SessionContext,
        *,
        message_id: str,
    ) -> None:
        now = utc_now()
        plan = session.conversation.teaching_plan_state
        student_state = session.conversation.student_learning_state
        teacher_log = session.conversation.teacher_working_log
        active_step_id = plan.current_step_id if plan else None
        append_teaching_debug_event(
            session.conversation,
            TeachingDebugEventType.TEACHING_PLAN_UPDATED,
            summary="教学计划已根据本轮结果更新。",
            now=now,
            message_id=message_id,
            plan_step_id=active_step_id,
            details={
                "current_step_id": active_step_id,
                "update_notes": plan.update_notes[-3:] if plan else [],
            },
        )
        append_teaching_debug_event(
            session.conversation,
            TeachingDebugEventType.STUDENT_STATE_UPDATED,
            summary="学生学习状态表已根据本轮信号更新。",
            now=now,
            message_id=message_id,
            plan_step_id=active_step_id,
            details={
                "update_notes": student_state.update_notes[-3:] if student_state else [],
                "topic_count": len(student_state.topics) if student_state else 0,
            },
        )
        append_teaching_debug_event(
            session.conversation,
            TeachingDebugEventType.WORKING_LOG_UPDATED,
            summary="教师工作日志已更新。",
            now=now,
            message_id=message_id,
            plan_step_id=active_step_id,
            details={
                "objective": teacher_log.current_teaching_objective if teacher_log else None,
                "recent_decisions": teacher_log.recent_decisions[-3:] if teacher_log else [],
            },
        )
        append_teaching_debug_event(
            session.conversation,
            TeachingDebugEventType.NEXT_TRANSITION_SELECTED,
            summary=teacher_log.planned_transition if teacher_log else "暂无下一步过渡。",
            now=now,
            message_id=message_id,
            plan_step_id=active_step_id,
            details={"planned_transition": teacher_log.planned_transition if teacher_log else None},
        )

    def record_explained_items(
        self,
        session: SessionContext,
        answer: StructuredAnswer,
        message_id: str,
    ) -> None:
        seen = {(item.item_type, item.item_id) for item in session.conversation.explained_items}
        for ref in answer.related_topic_refs[:6]:
            key = (ref.ref_type, ref.target_id)
            if key in seen:
                continue
            session.conversation.explained_items.append(
                ExplainedItemRef(
                    item_type=ref.ref_type,
                    item_id=ref.target_id,
                    topic=ref.topic,
                    explained_at_message_id=message_id,
                )
            )
            seen.add(key)

    def stage_for_goal(
        self,
        goal: LearningGoal,
        message_type: MessageType,
    ) -> TeachingStage:
        if message_type == MessageType.STAGE_SUMMARY or goal == LearningGoal.SUMMARY:
            return TeachingStage.SUMMARY
        return {
            LearningGoal.OVERVIEW: TeachingStage.STRUCTURE_OVERVIEW,
            LearningGoal.STRUCTURE: TeachingStage.STRUCTURE_OVERVIEW,
            LearningGoal.ENTRY: TeachingStage.ENTRY_EXPLAINED,
            LearningGoal.FLOW: TeachingStage.FLOW_EXPLAINED,
            LearningGoal.LAYER: TeachingStage.LAYER_EXPLAINED,
            LearningGoal.DEPENDENCY: TeachingStage.DEPENDENCY_EXPLAINED,
            LearningGoal.MODULE: TeachingStage.MODULE_DEEP_DIVE,
        }.get(goal, TeachingStage.STRUCTURE_OVERVIEW)

    def message_type_for_prompt(self, scenario: PromptScenario) -> MessageType:
        if scenario == PromptScenario.GOAL_SWITCH:
            return MessageType.GOAL_SWITCH_CONFIRMATION
        if scenario == PromptScenario.STAGE_SUMMARY:
            return MessageType.STAGE_SUMMARY
        return MessageType.AGENT_ANSWER

    def last_user_message(self, session: SessionContext) -> MessageRecord:
        return next(
            item for item in reversed(session.conversation.messages) if item.role == MessageRole.USER
        )

    def infer_prompt_scenario(self, user_text: str) -> PromptScenario:
        normalized = user_text.casefold()
        if any(token in normalized for token in ("总结", "小结", "回顾", "summary")):
            return PromptScenario.STAGE_SUMMARY
        return PromptScenario.FOLLOW_UP

    def looks_like_goal_switch(self, user_text: str) -> bool:
        normalized = user_text.casefold()
        return any(
            token in normalized for token in ("只看", "只讲", "聚焦", "切换", "先别", "focus", "only")
        )

    def looks_like_depth_adjustment(self, user_text: str) -> bool:
        normalized = user_text.casefold()
        return any(
            token in normalized
            for token in ("深入", "详细", "展开", "讲深", "简单", "概括", "浅", "brief", "short", "deep")
        )

    def infer_learning_goal(self, session: SessionContext, user_text: str) -> LearningGoal:
        normalized = user_text.casefold()
        for suggestion in reversed(session.conversation.last_suggestions):
            if suggestion.target_goal and suggestion.text.strip().casefold() == normalized:
                return suggestion.target_goal
        for goal, keywords in GOAL_KEYWORDS:
            if any(keyword.casefold() in normalized for keyword in keywords):
                return goal
        return session.conversation.current_learning_goal

    def infer_depth_level(self, current_depth: DepthLevel, user_text: str) -> DepthLevel:
        normalized = user_text.casefold()
        if any(token in normalized for token in ("深入", "详细", "展开", "源码", "代码", "deep")):
            return DepthLevel.DEEP
        if any(token in normalized for token in ("简单", "概括", "浅", "brief", "short")):
            return DepthLevel.SHALLOW
        return current_depth

    def output_contract(self, depth: DepthLevel) -> OutputContract:
        return OutputContract(
            required_sections=[
                MessageSection.FOCUS,
                MessageSection.DIRECT_EXPLANATION,
                MessageSection.RELATION_TO_OVERALL,
                MessageSection.EVIDENCE,
                MessageSection.UNCERTAINTY,
                MessageSection.NEXT_STEPS,
            ],
            max_core_points=3 if depth == DepthLevel.SHALLOW else 5,
            must_include_next_steps=True,
            must_mark_uncertainty=True,
            must_use_candidate_wording=True,
        )
