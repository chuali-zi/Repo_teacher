from __future__ import annotations

from collections.abc import AsyncIterator

from backend.contracts.domain import (
    InitialReportAnswer,
    MessageRecord,
    RuntimeEvent,
    SessionContext,
    UserFacingErrorException,
)
from backend.contracts.enums import (
    ConversationSubStatus,
    LearningGoal,
    MessageRole,
    MessageType,
    ProgressStepKey,
    ProgressStepState,
    RuntimeEventType,
    SessionStatus,
    TeachingStage,
)
from backend.m1_repo_access import access_repository
from backend.m2_file_tree.tree_scanner import scan_repository_tree
from backend.m5_session.common import new_id, utc_now
from backend.m5_session.errors import analysis_failed_error
from backend.m6_response.answer_generator import (
    LlmStreamer,
    ToolAwareLlmStreamer,
    ToolStreamActivity,
    ToolStreamTextDelta,
    parse_answer,
    stream_answer_text,
    stream_answer_text_with_tools,
)
from backend.m6_response.sidecar_stream import JsonOutputSidecarStripper


class AnalysisWorkflow:
    def __init__(self, *, repository, events, teaching) -> None:
        self.repository = repository
        self.events = events
        self.teaching = teaching

    async def run(
        self,
        session_id: str,
        *,
        llm_streamer: LlmStreamer,
        tool_streamer: ToolAwareLlmStreamer,
    ) -> AsyncIterator[RuntimeEvent]:
        session = self.repository.require(session_id)
        if session.status == SessionStatus.CHATTING and self.repository.latest_initial_report_completed_event(
            session_id
        ):
            return

        try:
            yield self.events.set_progress_step(
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
            yield self.events.set_progress_step(
                session,
                ProgressStepKey.REPO_ACCESS,
                ProgressStepState.DONE,
                "仓库访问验证完成",
            )

            status_start_index = len(session.runtime_events)
            self.events.transition_status(session, SessionStatus.ANALYZING)
            for event in session.runtime_events[status_start_index:]:
                yield event

            file_tree = scan_repository_tree(repository)
            session.file_tree = file_tree
            session.repository.primary_language = file_tree.primary_language
            session.repository.repo_size_level = file_tree.repo_size_level
            session.repository.source_code_file_count = file_tree.source_code_file_count
            yield self.events.set_progress_step(
                session,
                ProgressStepKey.FILE_TREE_SCAN,
                ProgressStepState.DONE,
                "文件树扫描完成",
            )

            degradation = self.events.maybe_create_degradation(file_tree)
            if degradation is not None:
                session.active_degradations = [degradation]
                yield self.events.append_runtime_event(
                    session,
                    RuntimeEventType.DEGRADATION_NOTICE,
                    degradation=degradation,
                )

            self.teaching.initialize_teaching_state(session)

            yield self.events.set_progress_step(
                session,
                ProgressStepKey.INITIAL_REPORT_GENERATION,
                ProgressStepState.RUNNING,
                "正在生成首轮教学报告...",
            )
            initial_answer: InitialReportAnswer | None = None
            async for item in self._stream_initial_report_answer(
                session,
                llm_streamer=llm_streamer,
                tool_streamer=tool_streamer,
            ):
                if isinstance(item, RuntimeEvent):
                    yield item
                else:
                    initial_answer = item
            if initial_answer is None:
                raise RuntimeError("Initial report generation did not produce an answer")

            yield self.events.set_progress_step(
                session,
                ProgressStepKey.INITIAL_REPORT_GENERATION,
                ProgressStepState.DONE,
                "首轮报告生成完成",
            )
            completion_start_index = len(session.runtime_events)
            self.events.transition_status(
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
            self.events.transition_status(session, error_status)
            for event in session.runtime_events[error_start_index:]:
                yield event
            yield self.events.append_runtime_event(
                session,
                RuntimeEventType.ERROR,
                error=exc.error,
            )
        except Exception as exc:
            error = analysis_failed_error(exc, stage=session.status)
            error_status = (
                SessionStatus.ACCESS_ERROR
                if session.status == SessionStatus.ACCESSING
                else SessionStatus.ANALYSIS_ERROR
            )
            session.last_error = error
            error_start_index = len(session.runtime_events)
            self.events.transition_status(session, error_status)
            for event in session.runtime_events[error_start_index:]:
                yield event
            yield self.events.append_runtime_event(
                session,
                RuntimeEventType.ERROR,
                error=error,
            )

    async def _stream_initial_report_answer(
        self,
        session: SessionContext,
        *,
        llm_streamer: LlmStreamer,
        tool_streamer: ToolAwareLlmStreamer,
    ) -> AsyncIterator[RuntimeEvent | InitialReportAnswer]:
        prompt_input = self.teaching.build_initial_report_prompt_input(session)
        answer_id = new_id("msg_agent_init")
        raw_chunks: list[str] = []
        visible_chunks: list[str] = []
        sidecar_stripper = JsonOutputSidecarStripper()

        yield self.events.append_runtime_event(
            session,
            RuntimeEventType.ANSWER_STREAM_START,
            message_id=answer_id,
            payload={"message_type": MessageType.INITIAL_REPORT},
        )

        if prompt_input.enable_tool_calls and session.repository and session.file_tree:
            answer_stream = stream_answer_text_with_tools(
                prompt_input,
                repository=session.repository,
                file_tree=session.file_tree,
                tool_streamer=tool_streamer,
                on_activity=lambda **payload: self.events.record_agent_activity(
                    session,
                    **payload,
                ),
            )
        else:
            answer_stream = stream_answer_text(prompt_input, llm_streamer=llm_streamer)

        async for item in answer_stream:
            if isinstance(item, ToolStreamActivity):
                event = (
                    item.recorded_event
                    if isinstance(item.recorded_event, RuntimeEvent)
                    else self.events.record_agent_activity(session, **item.payload)
                )
                yield event
                continue
            chunk = item.text if isinstance(item, ToolStreamTextDelta) else item
            raw_chunks.append(chunk)
            for visible_chunk in sidecar_stripper.feed(chunk):
                visible_chunks.append(visible_chunk)
                yield self.events.append_runtime_event(
                    session,
                    RuntimeEventType.ANSWER_STREAM_DELTA,
                    message_id=answer_id,
                    message_chunk=visible_chunk,
                )

        for visible_chunk in sidecar_stripper.finish():
            visible_chunks.append(visible_chunk)
            yield self.events.append_runtime_event(
                session,
                RuntimeEventType.ANSWER_STREAM_DELTA,
                message_id=answer_id,
                message_chunk=visible_chunk,
            )

        raw_text = "".join(raw_chunks).strip()
        if not raw_text:
            raise RuntimeError("LLM returned an empty initial report")

        yield self.events.append_runtime_event(
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
        self.teaching.ensure_initial_report_suggestions(session, answer)
        yield answer

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
        self.teaching.update_teaching_state_after_initial_report(session, answer, message.message_id)
        self.events.append_runtime_event(
            session,
            RuntimeEventType.MESSAGE_COMPLETED,
            message_id=message.message_id,
            payload={"message": message.model_dump(mode="python")},
        )
