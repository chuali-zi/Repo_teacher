from __future__ import annotations

import asyncio
import shutil
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import PureWindowsPath
from uuid import uuid4

from backend.contracts.domain import (
    AgentActivity,
    ConversationState,
    DegradationFlag,
    ExplainedItemRef,
    InitialReportAnswer,
    MessageRecord,
    OutputContract,
    ProgressStepStateItem,
    PromptBuildInput,
    ReadPolicySnapshot,
    RepositoryContext,
    RuntimeEvent,
    SessionContext,
    SessionStore,
    StructuredAnswer,
    TempResourceSet,
    TopicRef,
    UserFacingError,
    UserFacingErrorException,
)
from backend.contracts.dto import (
    AgentActivityDto,
    ClearSessionData,
    DegradationFlagDto,
    MessageErrorStateDto,
    MessageDto,
    RepositorySummaryDto,
    SendMessageData,
    SessionSnapshotDto,
    StructuredMessageContentDto,
    SuggestionDto,
    SubmitRepoData,
    UserFacingErrorDto,
    ValidateRepoData,
)
from backend.contracts.enums import (
    AgentActivityPhase,
    CleanupStatus,
    ClientView,
    ConversationSubStatus,
    DegradationType,
    DepthLevel,
    ErrorCode,
    LearningGoal,
    MessageSection,
    MessageRole,
    MessageType,
    ProgressStepKey,
    ProgressStepState,
    PromptScenario,
    RepoSourceType,
    RuntimeEventType,
    SessionStatus,
    TeachingDebugEventType,
    TeachingStage,
)
from backend.llm_tools import build_llm_tool_context
from backend.m1_repo_access import access_repository
from backend.m1_repo_access.input_validator import classify_repo_input
from backend.m2_file_tree.tree_scanner import scan_repository_tree
from backend.m3_analysis import run_static_analysis
from backend.m4_skeleton import assemble_teaching_skeleton
from backend.m5_session.state_machine import (
    assert_sub_status_allowed,
    assert_transition_allowed,
    view_for_status,
)
from backend.m5_session.teaching_state import (
    append_teaching_debug_event,
    build_teaching_decision,
    build_initial_student_learning_state,
    build_initial_teacher_working_log,
    build_initial_teaching_plan,
    plan_based_suggestions,
    update_after_initial_report,
    update_after_structured_answer,
)
from backend.m6_response.answer_generator import (
    LlmStreamer,
    ToolStreamActivity,
    ToolStreamTextDelta,
    ToolAwareLlmStreamer,
    parse_answer,
    stream_answer_text,
    stream_answer_text_with_tools,
)
from backend.m6_response.llm_caller import stream_llm_response, stream_llm_response_with_tools
from backend.m6_response.suggestion_generator import generate_next_step_suggestions
from backend.security.safety import build_default_read_policy


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def initial_progress_steps() -> list[ProgressStepStateItem]:
    return [
        ProgressStepStateItem(step_key=key, step_state=ProgressStepState.PENDING)
        for key in (
            ProgressStepKey.REPO_ACCESS,
            ProgressStepKey.FILE_TREE_SCAN,
            ProgressStepKey.ENTRY_AND_MODULE_ANALYSIS,
            ProgressStepKey.DEPENDENCY_ANALYSIS,
            ProgressStepKey.SKELETON_ASSEMBLY,
            ProgressStepKey.INITIAL_REPORT_GENERATION,
        )
    ]


_GOAL_KEYWORDS: tuple[tuple[LearningGoal, tuple[str, ...]], ...] = (
    (LearningGoal.ENTRY, ("入口", "启动", "main", "app", "route", "路由")),
    (LearningGoal.FLOW, ("流程", "调用链", "怎么走", "请求", "数据流", "flow")),
    (LearningGoal.MODULE, ("模块", "文件", "类", "函数", "module")),
    (LearningGoal.DEPENDENCY, ("依赖", "import", "包", "第三方")),
    (LearningGoal.LAYER, ("分层", "架构", "层", "layer")),
    (LearningGoal.STRUCTURE, ("结构", "目录", "先看哪里", "阅读顺序")),
    (LearningGoal.SUMMARY, ("总结", "小结", "回顾")),
)

_TOPIC_ATTRS_BY_GOAL: dict[LearningGoal, tuple[str, ...]] = {
    LearningGoal.OVERVIEW: (
        "structure_refs",
        "entry_refs",
        "flow_refs",
        "module_refs",
        "reading_path_refs",
    ),
    LearningGoal.STRUCTURE: ("structure_refs", "reading_path_refs", "module_refs"),
    LearningGoal.ENTRY: ("entry_refs", "reading_path_refs", "module_refs"),
    LearningGoal.FLOW: ("flow_refs", "entry_refs", "module_refs"),
    LearningGoal.MODULE: ("module_refs", "structure_refs", "reading_path_refs"),
    LearningGoal.DEPENDENCY: ("dependency_refs", "module_refs", "structure_refs"),
    LearningGoal.LAYER: ("layer_refs", "module_refs", "structure_refs"),
    LearningGoal.SUMMARY: ("unknown_refs", "reading_path_refs", "structure_refs"),
}


class SessionService:
    def __init__(self) -> None:
        self.store = SessionStore(active_session=None)
        self.llm_streamer: LlmStreamer = stream_llm_response
        self.tool_streamer: ToolAwareLlmStreamer = stream_llm_response_with_tools

    def validate_repo_input(self, input_value: str) -> ValidateRepoData:
        return classify_repo_input(input_value)

    def create_repo_session(self, input_value: str) -> SubmitRepoData:
        validation = self.validate_repo_input(input_value)
        if not validation.is_valid or validation.normalized_input is None:
            raise UserFacingErrorException(
                self.invalid_request_error("请输入本地仓库绝对路径或 GitHub 公开仓库 URL")
            )

        self.clear_active_session()
        now = utc_now()
        session_id = new_id("sess")
        repository = self._bootstrap_repository(validation, input_value)
        context = SessionContext(
            session_id=session_id,
            status=SessionStatus.ACCESSING,
            created_at=now,
            updated_at=now,
            repository=repository,
            conversation=ConversationState(current_repo_id=repository.repo_id),
            progress_steps=initial_progress_steps(),
            temp_resources=TempResourceSet(
                clone_dir=None,
                cleanup_required=repository.source_type == RepoSourceType.GITHUB_URL,
                cleanup_status=CleanupStatus.PENDING
                if repository.source_type == RepoSourceType.GITHUB_URL
                else CleanupStatus.NOT_NEEDED,
            ),
        )
        assert_sub_status_allowed(context.status, context.conversation.sub_status)
        self.store.active_session = context
        return SubmitRepoData(
            accepted=True,
            status=context.status,
            sub_status=context.conversation.sub_status,
            view=view_for_status(context.status, context.conversation.sub_status),
            repository=self._repository_summary(repository),
            analysis_stream_url=f"/api/analysis/stream?session_id={session_id}",
        )

    def get_snapshot(self, session_id: str | None = None) -> SessionSnapshotDto:
        session = self.store.active_session
        if session is None:
            return SessionSnapshotDto(
                session_id=None,
                status=SessionStatus.IDLE,
                sub_status=None,
                view=ClientView.INPUT,
            )
        self.assert_session_matches(session_id, allow_missing=True)
        sub_status = session.conversation.sub_status
        return SessionSnapshotDto(
            session_id=session.session_id,
            status=session.status,
            sub_status=sub_status,
            view=view_for_status(session.status, sub_status),
            repository=self._repository_summary(session.repository) if session.repository else None,
            progress_steps=session.progress_steps,
            degradation_notices=[
                DegradationFlagDto(
                    degradation_id=item.degradation_id,
                    type=item.type,
                    reason=item.reason,
                    user_notice=item.user_notice,
                    related_paths=item.related_paths,
                )
                for item in session.active_degradations
            ],
            messages=[self._message_dto(item) for item in session.conversation.messages],
            active_agent_activity=(
                AgentActivityDto.model_validate(
                    session.active_agent_activity.model_dump(mode="python")
                )
                if session.active_agent_activity
                else None
            ),
            active_error=UserFacingErrorDto.from_domain(session.last_error)
            if session.last_error
            else None,
        )

    def accept_chat_message(self, session_id: str, message: str) -> SendMessageData:
        session = self.assert_session_matches(session_id)
        if not message.strip():
            raise UserFacingErrorException(self.invalid_request_error("消息不能为空"))
        if (
            session.status != SessionStatus.CHATTING
            or session.conversation.sub_status != ConversationSubStatus.WAITING_USER
        ):
            raise UserFacingErrorException(
                UserFacingError(
                    error_code=ErrorCode.INVALID_STATE,
                    message="当前状态不允许发送消息",
                    retryable=True,
                    stage=session.status,
                    input_preserved=True,
                )
            )
        user_message_id = new_id("msg_user")
        session.conversation.messages.append(
            MessageRecord(
                message_id=user_message_id,
                role=MessageRole.USER,
                message_type=MessageType.USER_QUESTION,
                created_at=utc_now(),
                raw_text=message,
                streaming_complete=True,
            )
        )
        session.last_error = None
        session.conversation.sub_status = ConversationSubStatus.AGENT_THINKING
        session.active_agent_activity = AgentActivity(
            activity_id=new_id("act"),
            phase=AgentActivityPhase.THINKING,
            summary="正在理解你的问题",
        )
        session.updated_at = utc_now()
        self._append_runtime_event(
            session,
            RuntimeEventType.AGENT_ACTIVITY,
            activity=session.active_agent_activity,
        )
        return SendMessageData(
            accepted=True,
            status="chatting",
            sub_status="agent_thinking",
            user_message_id=user_message_id,
            chat_stream_url=f"/api/chat/stream?session_id={session_id}",
        )

    def clear_session(self, session_id: str) -> ClearSessionData:
        self.assert_session_matches(session_id)
        self.clear_active_session()
        return ClearSessionData(
            status="idle",
            sub_status=None,
            view="input",
            cleanup_completed=True,
        )

    def assert_session_matches(
        self,
        session_id: str | None,
        *,
        allow_missing: bool = False,
    ) -> SessionContext:
        session = self.store.active_session
        if session is None:
            raise UserFacingErrorException(
                UserFacingError(
                    error_code=ErrorCode.INVALID_STATE,
                    message="当前没有活跃会话",
                    retryable=True,
                    stage=SessionStatus.IDLE,
                    input_preserved=True,
                )
            )
        if session_id is None and allow_missing:
            return session
        if session_id != session.session_id:
            raise UserFacingErrorException(
                UserFacingError(
                    error_code=ErrorCode.INVALID_STATE,
                    message="会话已失效，请刷新后重试",
                    retryable=True,
                    stage=session.status,
                    input_preserved=True,
                )
            )
        return session

    def clear_active_session(self) -> None:
        active = self.store.active_session
        if active and active.temp_resources and active.temp_resources.cleanup_required:
            self._cleanup_temp_resources(active.temp_resources)
        self.store.active_session = None

    async def run_initial_analysis(self, session_id: str) -> AsyncIterator[RuntimeEvent]:
        session = self.assert_session_matches(session_id)
        if session.status == SessionStatus.CHATTING and self.latest_initial_report_completed_event(
            session_id
        ):
            return

        try:
            yield self._set_progress_step(
                session,
                ProgressStepKey.REPO_ACCESS,
                ProgressStepState.RUNNING,
                "正在验证仓库访问...",
            )
            repository, temp_resources = access_repository(
                session.repository.input_value,
                session.repository.read_policy,
            )
            repository.repo_id = session.repository.repo_id
            session.repository = repository
            session.temp_resources = temp_resources
            yield self._set_progress_step(
                session,
                ProgressStepKey.REPO_ACCESS,
                ProgressStepState.DONE,
                "仓库访问验证完成",
            )

            status_start_index = len(session.runtime_events)
            self._transition_status(session, SessionStatus.ANALYZING)
            for event in session.runtime_events[status_start_index:]:
                yield event

            file_tree = scan_repository_tree(repository)
            session.file_tree = file_tree
            session.repository.primary_language = file_tree.primary_language
            session.repository.repo_size_level = file_tree.repo_size_level
            session.repository.source_code_file_count = file_tree.source_code_file_count
            yield self._set_progress_step(
                session,
                ProgressStepKey.FILE_TREE_SCAN,
                ProgressStepState.DONE,
                "文件树扫描完成",
            )

            degradation = self._maybe_create_degradation(file_tree)
            if degradation is not None:
                session.active_degradations = [degradation]
                yield self._append_runtime_event(
                    session,
                    RuntimeEventType.DEGRADATION_NOTICE,
                    degradation=degradation,
                )

            analysis = run_static_analysis(repository, file_tree)
            session.analysis = analysis
            yield self._set_progress_step(
                session,
                ProgressStepKey.ENTRY_AND_MODULE_ANALYSIS,
                ProgressStepState.DONE,
                "入口与模块分析完成",
            )
            yield self._set_progress_step(
                session,
                ProgressStepKey.DEPENDENCY_ANALYSIS,
                ProgressStepState.DONE,
                "依赖来源分析完成",
            )

            skeleton = assemble_teaching_skeleton(analysis)
            session.teaching_skeleton = skeleton
            self._initialize_teaching_state(session)
            yield self._set_progress_step(
                session,
                ProgressStepKey.SKELETON_ASSEMBLY,
                ProgressStepState.DONE,
                "教学骨架组装完成",
            )

            yield self._set_progress_step(
                session,
                ProgressStepKey.INITIAL_REPORT_GENERATION,
                ProgressStepState.RUNNING,
                "正在生成首轮教学报告...",
            )
            initial_answer: InitialReportAnswer | None = None
            async for item in self._stream_initial_report_answer(session):
                if isinstance(item, RuntimeEvent):
                    yield item
                else:
                    initial_answer = item
            if initial_answer is None:
                raise RuntimeError("Initial report generation did not produce an answer")

            yield self._set_progress_step(
                session,
                ProgressStepKey.INITIAL_REPORT_GENERATION,
                ProgressStepState.DONE,
                "首轮报告生成完成",
            )
            completion_start_index = len(session.runtime_events)
            self._transition_status(
                session,
                SessionStatus.CHATTING,
                ConversationSubStatus.WAITING_USER,
            )
            for event in session.runtime_events[completion_start_index:]:
                yield event
            self._complete_initial_report(session, initial_answer)
            yield session.runtime_events[-1]
        except UserFacingErrorException as exc:
            error_status = (
                SessionStatus.ACCESS_ERROR
                if session.status == SessionStatus.ACCESSING
                else SessionStatus.ANALYSIS_ERROR
            )
            session.last_error = exc.error
            error_start_index = len(session.runtime_events)
            self._transition_status(session, error_status)
            for event in session.runtime_events[error_start_index:]:
                yield event
            yield self._append_runtime_event(
                session,
                RuntimeEventType.ERROR,
                error=exc.error,
            )
        except Exception as exc:
            error = self.analysis_failed_error(exc, stage=session.status)
            error_status = (
                SessionStatus.ACCESS_ERROR
                if session.status == SessionStatus.ACCESSING
                else SessionStatus.ANALYSIS_ERROR
            )
            session.last_error = error
            error_start_index = len(session.runtime_events)
            self._transition_status(session, error_status)
            for event in session.runtime_events[error_start_index:]:
                yield event
            yield self._append_runtime_event(
                session,
                RuntimeEventType.ERROR,
                error=error,
            )

    async def run_chat_turn(self, session_id: str) -> AsyncIterator[RuntimeEvent]:
        session = self.assert_session_matches(session_id)
        if (
            session.status != SessionStatus.CHATTING
            or session.conversation.sub_status != ConversationSubStatus.AGENT_THINKING
        ):
            return

        prompt_input = self._build_prompt_input(session)
        answer_id = new_id("msg_agent")
        status_start_index = len(session.runtime_events)
        self._transition_status(
            session,
            SessionStatus.CHATTING,
            ConversationSubStatus.AGENT_STREAMING,
        )
        for event in session.runtime_events[status_start_index:]:
            yield event

        yield self._append_runtime_event(
            session,
            RuntimeEventType.ANSWER_STREAM_START,
            message_id=answer_id,
            payload={"message_type": self._message_type_for_prompt(prompt_input.scenario)},
        )

        use_tool_calls = prompt_input.enable_tool_calls and session.repository and session.file_tree
        if use_tool_calls:
            answer_stream = stream_answer_text_with_tools(
                prompt_input,
                repository=session.repository,
                file_tree=session.file_tree,
                analysis=session.analysis,
                teaching_skeleton=session.teaching_skeleton,
                tool_streamer=self.tool_streamer,
                on_activity=lambda **payload: self._record_agent_activity(session, **payload),
            )
        else:
            answer_stream = stream_answer_text(prompt_input, llm_streamer=self.llm_streamer)

        raw_chunks: list[str] = []
        visible_chunks: list[str] = []
        visible_buffer = ""
        json_output_started = False
        answer_stream_ended = False
        json_marker = "<json_output>"
        marker_tail_size = len(json_marker) - 1
        try:
            async with asyncio.timeout(45):
                async for item in answer_stream:
                    if isinstance(item, ToolStreamActivity):
                        event = (
                            item.recorded_event
                            if isinstance(item.recorded_event, RuntimeEvent)
                            else self._record_agent_activity(session, **item.payload)
                        )
                        yield event
                        continue
                    chunk = item.text if isinstance(item, ToolStreamTextDelta) else item
                    raw_chunks.append(chunk)
                    if json_output_started:
                        continue
                    visible_buffer += chunk
                    marker_index = visible_buffer.find(json_marker)
                    if marker_index >= 0:
                        visible_chunk = visible_buffer[:marker_index]
                        visible_buffer = ""
                        json_output_started = True
                    elif len(visible_buffer) > marker_tail_size:
                        visible_chunk = visible_buffer[:-marker_tail_size]
                        visible_buffer = visible_buffer[-marker_tail_size:]
                    else:
                        visible_chunk = ""
                    if visible_chunk:
                        visible_chunks.append(visible_chunk)
                        yield self._append_runtime_event(
                            session,
                            RuntimeEventType.ANSWER_STREAM_DELTA,
                            message_id=answer_id,
                            message_chunk=visible_chunk,
                        )
                    if json_output_started and not answer_stream_ended:
                        yield self._append_runtime_event(
                            session,
                            RuntimeEventType.ANSWER_STREAM_END,
                            message_id=answer_id,
                        )
                        answer_stream_ended = True
        except asyncio.CancelledError as exc:
            self._cancel_chat_turn(session, exc)
            raise
        except Exception as exc:
            for event in self._fail_chat_turn(session, exc):
                yield event
            return

        if visible_buffer and not json_output_started:
            visible_chunks.append(visible_buffer)
            yield self._append_runtime_event(
                session,
                RuntimeEventType.ANSWER_STREAM_DELTA,
                message_id=answer_id,
                message_chunk=visible_buffer,
            )

        raw_text = "".join(raw_chunks).strip()
        if not raw_text:
            error = RuntimeError("LLM returned an empty response")
            for event in self._fail_chat_turn(session, error):
                yield event
            return

        if not answer_stream_ended:
            yield self._append_runtime_event(
                session,
                RuntimeEventType.ANSWER_STREAM_END,
                message_id=answer_id,
            )

        try:
            parsed_answer = parse_answer(prompt_input, raw_text)
            if not isinstance(parsed_answer, StructuredAnswer):
                raise RuntimeError("M6 returned an initial-report answer for a chat turn")
            answer = parsed_answer.model_copy(update={"answer_id": answer_id})
            self._ensure_answer_suggestions(session, answer)
        except Exception as exc:
            for event in self._fail_chat_turn(session, exc):
                yield event
            return

        visible_text = "".join(visible_chunks)
        message = MessageRecord(
            message_id=answer.answer_id,
            role=MessageRole.AGENT,
            message_type=answer.message_type,
            created_at=utc_now(),
            raw_text=visible_text,
            structured_content=answer.structured_content,
            related_goal=session.conversation.current_learning_goal,
            suggestions=answer.suggestions,
            streaming_complete=True,
        )
        session.conversation.messages.append(message)
        session.conversation.last_suggestions = answer.suggestions
        session.conversation.current_stage = self._stage_for_goal(
            session.conversation.current_learning_goal,
            answer.message_type,
        )
        session.active_agent_activity = None
        session.last_error = None
        self._record_explained_items(session, answer, message.message_id)
        self._update_teaching_state_after_answer(
            session,
            answer,
            user_text=prompt_input.user_message or "",
            message_id=message.message_id,
            scenario=prompt_input.scenario,
        )
        self._update_history_summary(session)
        completion_start_index = len(session.runtime_events)
        self._transition_status(session, SessionStatus.CHATTING, ConversationSubStatus.WAITING_USER)
        for event in session.runtime_events[completion_start_index:]:
            yield event
        yield self._append_runtime_event(
            session,
            RuntimeEventType.MESSAGE_COMPLETED,
            message_id=message.message_id,
            payload={"message": message.model_dump(mode="python")},
        )

    async def _stream_initial_report_answer(
        self,
        session: SessionContext,
    ) -> AsyncIterator[RuntimeEvent | InitialReportAnswer]:
        prompt_input = self._build_initial_report_prompt_input(session)
        answer_id = new_id("msg_agent_init")
        raw_chunks: list[str] = []
        visible_chunks: list[str] = []
        visible_buffer = ""
        json_output_started = False
        answer_stream_ended = False
        json_marker = "<json_output>"
        marker_tail_size = len(json_marker) - 1

        yield self._append_runtime_event(
            session,
            RuntimeEventType.ANSWER_STREAM_START,
            message_id=answer_id,
            payload={"message_type": MessageType.INITIAL_REPORT},
        )

        async for chunk in stream_answer_text(prompt_input, llm_streamer=self.llm_streamer):
            raw_chunks.append(chunk)
            if json_output_started:
                continue
            visible_buffer += chunk
            marker_index = visible_buffer.find(json_marker)
            if marker_index >= 0:
                visible_chunk = visible_buffer[:marker_index]
                visible_buffer = ""
                json_output_started = True
            elif len(visible_buffer) > marker_tail_size:
                visible_chunk = visible_buffer[:-marker_tail_size]
                visible_buffer = visible_buffer[-marker_tail_size:]
            else:
                visible_chunk = ""
            if visible_chunk:
                visible_chunks.append(visible_chunk)
                yield self._append_runtime_event(
                    session,
                    RuntimeEventType.ANSWER_STREAM_DELTA,
                    message_id=answer_id,
                    message_chunk=visible_chunk,
                )
            if json_output_started and not answer_stream_ended:
                yield self._append_runtime_event(
                    session,
                    RuntimeEventType.ANSWER_STREAM_END,
                    message_id=answer_id,
                )
                answer_stream_ended = True

        if visible_buffer and not json_output_started:
            visible_chunks.append(visible_buffer)
            yield self._append_runtime_event(
                session,
                RuntimeEventType.ANSWER_STREAM_DELTA,
                message_id=answer_id,
                message_chunk=visible_buffer,
            )

        raw_text = "".join(raw_chunks).strip()
        if not raw_text:
            raise RuntimeError("LLM returned an empty initial report")

        if not answer_stream_ended:
            yield self._append_runtime_event(
                session,
                RuntimeEventType.ANSWER_STREAM_END,
                message_id=answer_id,
            )

        parsed_answer = parse_answer(prompt_input, raw_text)
        if not isinstance(parsed_answer, InitialReportAnswer):
            raise RuntimeError("M6 returned a non-initial-report answer for initial analysis")

        visible_text = "".join(visible_chunks)
        if not visible_text.strip():
            raise RuntimeError("LLM returned an initial report without user-visible text")
        answer = parsed_answer.model_copy(update={"answer_id": answer_id, "raw_text": visible_text})
        self._ensure_initial_report_suggestions(session, answer)
        yield answer

    def _build_initial_report_prompt_input(self, session: SessionContext) -> PromptBuildInput:
        topic_slice = self._topic_slice_for_goal(session.teaching_skeleton, LearningGoal.OVERVIEW)
        self._prepare_teaching_decision(
            session,
            user_text="请先带我建立这个仓库的整体理解，并给出一条主动引导的阅读计划。",
            scenario=PromptScenario.INITIAL_REPORT,
            topic_slice=topic_slice,
        )
        return PromptBuildInput(
            scenario=PromptScenario.INITIAL_REPORT,
            user_message="请先带我建立这个仓库的整体理解，并给出一条主动引导的阅读计划。",
            teaching_skeleton=session.teaching_skeleton,
            topic_slice=topic_slice,
            tool_context=self._build_tool_context(session, topic_slice),
            conversation_state=session.conversation.model_copy(deep=True),
            history_summary=None,
            depth_level=session.conversation.depth_level,
            output_contract=self._output_contract(session.conversation.depth_level),
        )

    def _build_prompt_input(self, session: SessionContext) -> PromptBuildInput:
        last_user_message = self._last_user_message(session)
        user_text = last_user_message.raw_text.strip()
        previous_goal = session.conversation.current_learning_goal
        previous_depth = session.conversation.depth_level
        goal = self._infer_learning_goal(session, user_text)
        depth = self._infer_depth_level(session.conversation.depth_level, user_text)
        scenario = self._infer_prompt_scenario(user_text)
        if scenario == PromptScenario.FOLLOW_UP:
            if goal != previous_goal and self._looks_like_goal_switch(user_text):
                scenario = PromptScenario.GOAL_SWITCH
            elif depth != previous_depth and self._looks_like_depth_adjustment(user_text):
                scenario = PromptScenario.DEPTH_ADJUSTMENT

        session.conversation.current_learning_goal = goal
        session.conversation.depth_level = depth
        topic_slice = self._topic_slice_for_goal(session.teaching_skeleton, goal)
        self._prepare_teaching_decision(
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
            tool_context=self._build_tool_context(session, topic_slice),
            conversation_state=session.conversation.model_copy(deep=True),
            history_summary=self._history_summary(session),
            depth_level=depth,
            output_contract=self._output_contract(depth),
            enable_tool_calls=scenario
            in (
                PromptScenario.FOLLOW_UP,
                PromptScenario.GOAL_SWITCH,
                PromptScenario.DEPTH_ADJUSTMENT,
            ),
        )

    def _build_tool_context(
        self,
        session: SessionContext,
        topic_slice: list[TopicRef],
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
        )

    def _last_user_message(self, session: SessionContext) -> MessageRecord:
        return next(
            item
            for item in reversed(session.conversation.messages)
            if item.role == MessageRole.USER
        )

    def _infer_prompt_scenario(self, user_text: str) -> PromptScenario:
        normalized = user_text.casefold()
        if any(token in normalized for token in ("总结", "小结", "回顾", "summary")):
            return PromptScenario.STAGE_SUMMARY
        return PromptScenario.FOLLOW_UP

    def _looks_like_goal_switch(self, user_text: str) -> bool:
        normalized = user_text.casefold()
        return any(
            token in normalized
            for token in ("只看", "只讲", "聚焦", "切换", "先别", "focus", "only")
        )

    def _looks_like_depth_adjustment(self, user_text: str) -> bool:
        normalized = user_text.casefold()
        return any(
            token in normalized
            for token in (
                "深入",
                "详细",
                "展开",
                "讲深",
                "简单",
                "概括",
                "浅",
                "brief",
                "short",
                "deep",
            )
        )

    def _infer_learning_goal(self, session: SessionContext, user_text: str) -> LearningGoal:
        normalized = user_text.casefold()
        for suggestion in reversed(session.conversation.last_suggestions):
            if suggestion.target_goal and suggestion.text.strip().casefold() == normalized:
                return suggestion.target_goal
        for goal, keywords in _GOAL_KEYWORDS:
            if any(keyword.casefold() in normalized for keyword in keywords):
                return goal
        return session.conversation.current_learning_goal

    def _infer_depth_level(self, current_depth: DepthLevel, user_text: str) -> DepthLevel:
        normalized = user_text.casefold()
        if any(token in normalized for token in ("深入", "详细", "展开", "源码", "代码", "deep")):
            return DepthLevel.DEEP
        if any(token in normalized for token in ("简单", "概括", "浅", "brief", "short")):
            return DepthLevel.SHALLOW
        return current_depth

    def _output_contract(self, depth: DepthLevel) -> OutputContract:
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

    def _topic_slice_for_goal(self, skeleton, goal: LearningGoal) -> list[TopicRef]:
        topic_index = skeleton.topic_index
        refs: list[TopicRef] = []
        for attr in _TOPIC_ATTRS_BY_GOAL.get(goal, ("structure_refs",)):
            refs.extend(getattr(topic_index, attr))
        if not refs:
            refs = self._all_topic_refs(skeleton)
        return self._dedupe_topic_refs(refs)[:20]

    def _all_topic_refs(self, skeleton) -> list[TopicRef]:
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
        return self._dedupe_topic_refs(refs)

    def _dedupe_topic_refs(self, refs: list[TopicRef]) -> list[TopicRef]:
        deduped: list[TopicRef] = []
        seen: set[str] = set()
        for ref in refs:
            if ref.ref_id in seen:
                continue
            deduped.append(ref)
            seen.add(ref.ref_id)
        return deduped

    def _history_summary(self, session: SessionContext) -> str | None:
        if session.conversation.history_summary:
            return session.conversation.history_summary
        return self._summarize_recent_messages(session.conversation.messages[:-1])

    def _update_history_summary(self, session: SessionContext) -> None:
        session.conversation.history_summary = self._summarize_recent_messages(
            session.conversation.messages
        )

    def _summarize_recent_messages(self, messages: list[MessageRecord]) -> str | None:
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

    def _ensure_answer_suggestions(
        self,
        session: SessionContext,
        answer: StructuredAnswer,
    ) -> None:
        suggestions = self._merge_teacher_suggestions(
            answer.suggestions,
            plan_based_suggestions(session.conversation),
        )
        if not suggestions:
            suggestions = generate_next_step_suggestions(
                session.conversation,
                self._all_topic_refs(session.teaching_skeleton),
            )
        answer.suggestions = suggestions
        answer.structured_content.next_steps = suggestions

    def _ensure_initial_report_suggestions(
        self,
        session: SessionContext,
        answer: InitialReportAnswer,
    ) -> None:
        suggestions = self._merge_teacher_suggestions(
            answer.suggestions,
            plan_based_suggestions(session.conversation),
        )
        if not suggestions:
            suggestions = session.teaching_skeleton.suggested_next_questions[:3]
        answer.suggestions = suggestions
        answer.initial_report_content.suggested_next_questions = suggestions

    def _merge_teacher_suggestions(self, primary: list, secondary: list) -> list:
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

    def _prepare_teaching_decision(
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

    def _initialize_teaching_state(self, session: SessionContext) -> None:
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

    def _update_teaching_state_after_initial_report(
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
        self._record_teaching_state_update_events(session, message_id=message_id)

    def _update_teaching_state_after_answer(
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
        self._record_teaching_state_update_events(session, message_id=message_id)

    def _record_teaching_state_update_events(
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
            summary="学生学习状态表已根据本轮教学信号更新。",
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

    def _record_explained_items(
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

    def _stage_for_goal(
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

    def _message_type_for_prompt(self, scenario: PromptScenario) -> MessageType:
        if scenario == PromptScenario.GOAL_SWITCH:
            return MessageType.GOAL_SWITCH_CONFIRMATION
        if scenario == PromptScenario.STAGE_SUMMARY:
            return MessageType.STAGE_SUMMARY
        return MessageType.AGENT_ANSWER

    def _fail_chat_turn(self, session: SessionContext, exc: Exception) -> list[RuntimeEvent]:
        start_index = len(session.runtime_events)
        error = self.llm_failed_error(exc)
        session.last_error = error
        session.active_agent_activity = None
        self._transition_status(
            session,
            SessionStatus.CHATTING,
            ConversationSubStatus.WAITING_USER,
        )
        self._append_runtime_event(
            session,
            RuntimeEventType.ERROR,
            error=error,
        )
        return session.runtime_events[start_index:]

    def _cancel_chat_turn(
        self,
        session: SessionContext,
        exc: asyncio.CancelledError,
    ) -> list[RuntimeEvent]:
        start_index = len(session.runtime_events)
        error = UserFacingError(
            error_code=ErrorCode.LLM_API_FAILED,
            message="本轮输出连接已中断，请重试。",
            retryable=True,
            stage=SessionStatus.CHATTING,
            input_preserved=True,
            internal_detail=str(exc) or "chat stream cancelled",
        )
        session.last_error = error
        session.active_agent_activity = None
        self._transition_status(
            session,
            SessionStatus.CHATTING,
            ConversationSubStatus.WAITING_USER,
        )
        self._append_runtime_event(
            session,
            RuntimeEventType.ERROR,
            error=error,
        )
        return session.runtime_events[start_index:]

    def build_status_snapshot_event(self, session: SessionContext) -> RuntimeEvent:
        return RuntimeEvent(
            event_id=new_id("evt"),
            session_id=session.session_id,
            event_type=RuntimeEventType.STATUS_CHANGED,
            occurred_at=session.updated_at,
            status_snapshot=session.status,
            sub_status_snapshot=session.conversation.sub_status,
        )

    def latest_runtime_event(
        self,
        session_id: str,
        event_type: RuntimeEventType,
    ) -> RuntimeEvent | None:
        session = self.assert_session_matches(session_id)
        for event in reversed(session.runtime_events):
            if event.event_type == event_type:
                return event
        return None

    def latest_initial_report_completed_event(self, session_id: str) -> RuntimeEvent | None:
        session = self.assert_session_matches(session_id)
        for event in reversed(session.runtime_events):
            if event.event_type != RuntimeEventType.MESSAGE_COMPLETED or not event.payload:
                continue
            payload = event.payload.get("message")
            if payload and payload.get("message_type") == MessageType.INITIAL_REPORT:
                return event
        return None

    def latest_chat_terminal_event(self, session_id: str) -> RuntimeEvent | None:
        session = self.assert_session_matches(session_id)
        for event in reversed(session.runtime_events):
            if event.event_type == RuntimeEventType.ERROR:
                return event
            if event.event_type != RuntimeEventType.MESSAGE_COMPLETED or not event.payload:
                continue
            payload = event.payload.get("message")
            if payload and payload.get("message_type") in {
                MessageType.AGENT_ANSWER,
                MessageType.GOAL_SWITCH_CONFIRMATION,
                MessageType.STAGE_SUMMARY,
                MessageType.ERROR,
            }:
                return event
        return None

    def invalid_request_error(self, message: str) -> UserFacingError:
        active = self.store.active_session
        return UserFacingError(
            error_code=ErrorCode.INVALID_REQUEST,
            message=message,
            retryable=True,
            stage=active.status if active else SessionStatus.IDLE,
            input_preserved=True,
        )

    def analysis_failed_error(self, exc: Exception, *, stage: SessionStatus) -> UserFacingError:
        return UserFacingError(
            error_code=ErrorCode.ANALYSIS_FAILED,
            message="分析过程出错，请重试或尝试其他仓库",
            retryable=True,
            stage=stage,
            input_preserved=True,
            internal_detail=str(exc),
        )

    def llm_failed_error(self, exc: Exception) -> UserFacingError:
        is_timeout = isinstance(exc, TimeoutError)
        return UserFacingError(
            error_code=ErrorCode.LLM_API_TIMEOUT if is_timeout else ErrorCode.LLM_API_FAILED,
            message=(
                "LLM 调用超时，请稍后重试或缩小问题范围。"
                if is_timeout
                else "LLM 调用失败，请检查 llm_config.json 或稍后重试。"
            ),
            retryable=True,
            stage=SessionStatus.CHATTING,
            input_preserved=True,
            internal_detail=str(exc),
        )

    def _bootstrap_repository(
        self,
        validation: ValidateRepoData,
        raw_input: str,
    ) -> RepositoryContext:
        source_type = (
            RepoSourceType.GITHUB_URL
            if validation.input_kind == "github_url"
            else RepoSourceType.LOCAL_PATH
        )
        display_name, owner, name = self._display_name_parts(raw_input, source_type)
        read_policy: ReadPolicySnapshot = build_default_read_policy()
        return RepositoryContext(
            repo_id=new_id("repo"),
            source_type=source_type,
            display_name=display_name,
            input_value=raw_input,
            root_path=validation.normalized_input or raw_input,
            is_temp_dir=source_type == RepoSourceType.GITHUB_URL,
            owner=owner,
            name=name,
            access_verified=False,
            read_policy=read_policy,
        )

    def _display_name_parts(
        self,
        input_value: str,
        source_type: RepoSourceType,
    ) -> tuple[str, str | None, str | None]:
        if source_type == RepoSourceType.GITHUB_URL:
            parts = input_value.rstrip("/").removesuffix(".git").split("/")
            owner = parts[-2] if len(parts) >= 2 else None
            name = parts[-1] if parts else input_value
            display = f"{owner}/{name}" if owner else name
            return display, owner, name
        name = PureWindowsPath(input_value).name or input_value
        return name, None, name

    def _repository_summary(self, repository: RepositoryContext) -> RepositorySummaryDto:
        return RepositorySummaryDto(
            display_name=repository.display_name,
            source_type=repository.source_type,
            input_value=repository.input_value,
            primary_language=repository.primary_language,
            repo_size_level=repository.repo_size_level,
            source_code_file_count=repository.source_code_file_count,
        )

    def _message_dto(self, message: MessageRecord) -> MessageDto:
        return MessageDto(
            message_id=message.message_id,
            role=message.role,
            message_type=message.message_type,
            created_at=message.created_at,
            raw_text=message.raw_text,
            structured_content=(
                StructuredMessageContentDto.model_validate(
                    message.structured_content.model_dump(mode="python")
                )
                if message.structured_content
                else None
            ),
            initial_report_content=(
                message.initial_report_content.model_dump(mode="python")
                if message.initial_report_content
                else None
            ),
            related_goal=message.related_goal,
            suggestions=[
                SuggestionDto.model_validate(item.model_dump(mode="python"))
                for item in message.suggestions
            ],
            streaming_complete=message.streaming_complete,
            error_state=(
                MessageErrorStateDto(
                    error=UserFacingErrorDto.from_domain(message.error_state.error),
                    failed_during_stream=message.error_state.failed_during_stream,
                    partial_text_available=message.error_state.partial_text_available,
                )
                if message.error_state
                else None
            ),
        )

    def _transition_status(
        self,
        session: SessionContext,
        status: SessionStatus,
        sub_status: ConversationSubStatus | None = None,
    ) -> None:
        assert_transition_allowed(session.status, status)
        session.status = status
        session.conversation.sub_status = sub_status
        assert_sub_status_allowed(session.status, session.conversation.sub_status)
        session.updated_at = utc_now()
        self._append_runtime_event(session, RuntimeEventType.STATUS_CHANGED)

    def _set_progress_step(
        self,
        session: SessionContext,
        step_key: ProgressStepKey,
        step_state: ProgressStepState,
        user_notice: str,
    ) -> RuntimeEvent:
        for item in session.progress_steps:
            if item.step_key == step_key:
                item.step_state = step_state
                break
        session.updated_at = utc_now()
        return self._append_runtime_event(
            session,
            RuntimeEventType.ANALYSIS_PROGRESS,
            step_key=step_key,
            step_state=step_state,
            user_notice=user_notice,
            payload={
                "progress_steps": [
                    item.model_dump(mode="python") for item in session.progress_steps
                ]
            },
        )

    def _append_runtime_event(
        self,
        session: SessionContext,
        event_type: RuntimeEventType,
        *,
        step_key: ProgressStepKey | None = None,
        step_state: ProgressStepState | None = None,
        message_id: str | None = None,
        message_chunk: str | None = None,
        structured_delta: dict | None = None,
        user_notice: str | None = None,
        error: UserFacingError | None = None,
        degradation: DegradationFlag | None = None,
        activity: AgentActivity | None = None,
        payload: dict | None = None,
    ) -> RuntimeEvent:
        event = RuntimeEvent(
            event_id=new_id("evt"),
            session_id=session.session_id,
            event_type=event_type,
            occurred_at=utc_now(),
            status_snapshot=session.status,
            sub_status_snapshot=session.conversation.sub_status,
            step_key=step_key,
            step_state=step_state,
            message_id=message_id,
            message_chunk=message_chunk,
            structured_delta=structured_delta,
            user_notice=user_notice,
            error=error,
            degradation=degradation,
            activity=activity,
            payload=payload,
        )
        session.runtime_events.append(event)
        session.updated_at = event.occurred_at
        return event

    def _record_agent_activity(
        self,
        session: SessionContext,
        *,
        phase: str,
        summary: str,
        tool_name: str | None = None,
        tool_arguments: dict | None = None,
        round_index: int | None = None,
        elapsed_ms: int | None = None,
        soft_timed_out: bool = False,
        failed: bool = False,
        retryable: bool = False,
    ) -> RuntimeEvent:
        activity = AgentActivity(
            activity_id=new_id("act"),
            phase=AgentActivityPhase(phase),
            summary=summary,
            tool_name=tool_name,
            tool_arguments=tool_arguments or {},
            round_index=round_index,
            elapsed_ms=elapsed_ms,
            soft_timed_out=soft_timed_out,
            failed=failed,
            retryable=retryable,
        )
        session.active_agent_activity = activity
        return self._append_runtime_event(
            session,
            RuntimeEventType.AGENT_ACTIVITY,
            activity=activity,
        )

    def _emit_answer_events(
        self,
        session: SessionContext,
        message_id: str,
        message_type: MessageType,
        raw_text: str,
    ) -> None:
        self._append_runtime_event(
            session,
            RuntimeEventType.ANSWER_STREAM_START,
            message_id=message_id,
            payload={"message_type": message_type},
        )
        for chunk in self._chunk_text(raw_text):
            self._append_runtime_event(
                session,
                RuntimeEventType.ANSWER_STREAM_DELTA,
                message_id=message_id,
                message_chunk=chunk,
            )
        self._append_runtime_event(
            session,
            RuntimeEventType.ANSWER_STREAM_END,
            message_id=message_id,
        )

    def _chunk_text(self, text: str, size: int = 80) -> list[str]:
        return [text[index : index + size] for index in range(0, len(text), size)] or [""]

    def _maybe_create_degradation(self, file_tree) -> DegradationFlag | None:
        if file_tree.repo_size_level == "large":
            return DegradationFlag(
                degradation_id=new_id("deg"),
                type=DegradationType.LARGE_REPO,
                reason="source_code_file_count > 3000",
                user_notice="仓库较大，优先输出结构总览和阅读起点。",
                started_at=utc_now(),
            )
        if file_tree.primary_language != "Python":
            return DegradationFlag(
                degradation_id=new_id("deg"),
                type=DegradationType.NON_PYTHON_REPO,
                reason="primary_language != Python",
                user_notice="当前仓库不是 Python 主仓库，仅提供保守结构说明。",
                started_at=utc_now(),
            )
        return None

    def _complete_initial_report(
        self,
        session: SessionContext,
        answer: InitialReportAnswer,
    ) -> None:
        message = MessageRecord(
            message_id=answer.answer_id,
            role=MessageRole.AGENT,
            message_type=answer.message_type,
            created_at=utc_now(),
            raw_text=answer.raw_text,
            initial_report_content=answer.initial_report_content,
            related_goal=LearningGoal.OVERVIEW,
            suggestions=answer.suggestions,
            streaming_complete=True,
        )
        session.conversation.messages.append(message)
        session.conversation.last_suggestions = answer.suggestions
        session.conversation.current_stage = TeachingStage.INITIAL_REPORT
        self._update_teaching_state_after_initial_report(
            session,
            answer,
            message.message_id,
        )
        self._append_runtime_event(
            session,
            RuntimeEventType.MESSAGE_COMPLETED,
            message_id=message.message_id,
            payload={"message": message.model_dump(mode="python")},
        )

    def _cleanup_temp_resources(self, temp_resources: TempResourceSet) -> None:
        if not temp_resources.clone_dir:
            temp_resources.cleanup_status = CleanupStatus.COMPLETED
            return
        try:
            shutil.rmtree(temp_resources.clone_dir, ignore_errors=False)
            temp_resources.cleanup_status = CleanupStatus.COMPLETED
        except OSError as exc:
            temp_resources.cleanup_status = CleanupStatus.FAILED
            temp_resources.cleanup_error = str(exc)


session_service = SessionService()
