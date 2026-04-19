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
    AnalysisMode,
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
from backend.deep_research import (
    build_group_notes,
    build_initial_report_answer_from_research,
    build_research_packets,
    build_research_run_state,
    build_synthesis_notes,
)
from backend.m1_repo_access import access_repository
from backend.m2_file_tree.tree_scanner import scan_repository_tree
from backend.m5_session.common import initial_progress_steps, utc_now
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
                "Validating repository access.",
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
                "Repository access verified.",
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
                "File tree scan completed.",
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

            initial_answer: InitialReportAnswer | None = None
            if (
                session.analysis_mode == AnalysisMode.DEEP_RESEARCH
                and file_tree.primary_language == "Python"
            ):
                async for item in self._build_deep_research_initial_report(session):
                    if isinstance(item, RuntimeEvent):
                        yield item
                    else:
                        initial_answer = item
            else:
                if session.analysis_mode == AnalysisMode.DEEP_RESEARCH and session.deep_research_state:
                    session.deep_research_state.phase = "degraded_to_quick_guide"
                    session.deep_research_state.current_target = None
                    session.progress_steps = initial_progress_steps(AnalysisMode.QUICK_GUIDE)
                yield self.events.set_progress_step(
                    session,
                    ProgressStepKey.INITIAL_REPORT_GENERATION,
                    ProgressStepState.RUNNING,
                    "Generating the initial report.",
                )
                async for item in self._stream_initial_report_answer(
                    session,
                    llm_streamer=llm_streamer,
                    tool_streamer=tool_streamer,
                ):
                    if isinstance(item, RuntimeEvent):
                        yield item
                    else:
                        initial_answer = item
                yield self.events.set_progress_step(
                    session,
                    ProgressStepKey.INITIAL_REPORT_GENERATION,
                    ProgressStepState.DONE,
                    "Initial report generation completed.",
                )

            if initial_answer is None:
                raise RuntimeError("Initial report generation did not produce an answer")

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

    async def _build_deep_research_initial_report(
        self,
        session: SessionContext,
    ) -> AsyncIterator[RuntimeEvent | InitialReportAnswer]:
        run_state = build_research_run_state(session.repository, session.file_tree)
        session.deep_research_state = run_state
        yield self.events.set_progress_step(
            session,
            ProgressStepKey.RESEARCH_PLANNING,
            ProgressStepState.RUNNING,
            "Planning the deep research pass.",
            payload=self._research_state_payload(session),
        )
        run_state.phase = "research_planning"
        if run_state.total_files:
            run_state.current_target = next(
                item.relative_path for item in run_state.relevant_files if item.selected
            )
        yield self.events.set_progress_step(
            session,
            ProgressStepKey.RESEARCH_PLANNING,
            ProgressStepState.DONE,
            "Relevant source files selected for deep research.",
            payload=self._research_state_payload(session),
        )

        run_state.phase = "source_sweep"
        yield self.events.set_progress_step(
            session,
            ProgressStepKey.SOURCE_SWEEP,
            ProgressStepState.RUNNING,
            "Sweeping selected source files.",
            payload=self._research_state_payload(session),
        )
        packets = build_research_packets(session.repository, run_state)
        for packet in packets:
            run_state.current_target = packet.relative_path
            run_state.completed_files += 1
            run_state.last_completed_target = packet.relative_path
            run_state.coverage_ratio = (
                run_state.completed_files / run_state.total_files
                if run_state.total_files
                else 0.0
            )
            yield self.events.set_progress_step(
                session,
                ProgressStepKey.SOURCE_SWEEP,
                ProgressStepState.RUNNING,
                f"Researched {packet.relative_path}.",
                payload=self._research_state_payload(session),
            )
        run_state.current_target = None
        yield self.events.set_progress_step(
            session,
            ProgressStepKey.SOURCE_SWEEP,
            ProgressStepState.DONE,
            "Source sweep completed.",
            payload=self._research_state_payload(session),
        )

        run_state.phase = "chapter_synthesis"
        yield self.events.set_progress_step(
            session,
            ProgressStepKey.CHAPTER_SYNTHESIS,
            ProgressStepState.RUNNING,
            "Synthesizing chapter notes.",
            payload=self._research_state_payload(session),
        )
        group_notes = build_group_notes(packets)
        synthesis_notes = build_synthesis_notes(
            session.repository,
            session.file_tree,
            run_state,
            group_notes,
            packets,
        )
        run_state.research_notes = group_notes
        run_state.synthesis_notes = synthesis_notes
        yield self.events.set_progress_step(
            session,
            ProgressStepKey.CHAPTER_SYNTHESIS,
            ProgressStepState.DONE,
            "Chapter synthesis completed.",
            payload=self._research_state_payload(session),
        )

        run_state.phase = "final_report_write"
        yield self.events.set_progress_step(
            session,
            ProgressStepKey.FINAL_REPORT_WRITE,
            ProgressStepState.RUNNING,
            "Writing the deep research report.",
            payload=self._research_state_payload(session),
        )
        answer = build_initial_report_answer_from_research(
            session.repository,
            session.file_tree,
            run_state,
            group_notes,
            synthesis_notes,
        )
        self.teaching.ensure_initial_report_suggestions(session, answer)
        run_state.phase = "completed"
        run_state.current_target = answer.initial_report_content.recommended_first_step.target
        yield self.events.set_progress_step(
            session,
            ProgressStepKey.FINAL_REPORT_WRITE,
            ProgressStepState.DONE,
            "Deep research report completed.",
            payload=self._research_state_payload(session),
        )
        run_state.current_target = None
        yield answer

    async def _stream_initial_report_answer(
        self,
        session: SessionContext,
        *,
        llm_streamer: LlmStreamer,
        tool_streamer: ToolAwareLlmStreamer,
    ) -> AsyncIterator[RuntimeEvent | InitialReportAnswer]:
        prompt_input = self.teaching.build_initial_report_prompt_input(session)
        answer_id = self._new_answer_id()
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

    def _research_state_payload(self, session: SessionContext) -> dict[str, dict]:
        state = session.deep_research_state
        if state is None:
            return {}
        return {
            "research_state": {
                "phase": state.phase,
                "total_files": state.total_files,
                "completed_files": state.completed_files,
                "skipped_files": state.skipped_files,
                "coverage_ratio": state.coverage_ratio,
                "current_target": state.current_target,
                "last_completed_target": state.last_completed_target,
            }
        }

    def _new_answer_id(self) -> str:
        return f"msg_agent_init_{utc_now().timestamp():.0f}"
