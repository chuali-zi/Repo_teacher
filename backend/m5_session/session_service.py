from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from pathlib import PureWindowsPath

from backend.contracts.domain import (
    AgentActivity,
    ConversationState,
    MessageRecord,
    ReadPolicySnapshot,
    RepositoryContext,
    RuntimeEvent,
    SessionContext,
    SessionStore,
    TempResourceSet,
    UserFacingError,
    UserFacingErrorException,
)
from backend.contracts.dto import (
    AgentActivityDto,
    ClearSessionData,
    MessageDto,
    MessageErrorStateDto,
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
    ErrorCode,
    MessageRole,
    MessageType,
    RepoSourceType,
    RuntimeEventType,
    SessionStatus,
)
from backend.m1_repo_access.input_validator import classify_repo_input
from backend.m5_session.analysis_workflow import AnalysisWorkflow
from backend.m5_session.chat_workflow import ChatWorkflow
from backend.m5_session.common import initial_progress_steps, new_id, utc_now
from backend.m5_session.errors import analysis_failed_error, invalid_request_error, llm_failed_error
from backend.m5_session.reconnect_queries import ReconnectQueryService
from backend.m5_session.repository import SessionRepository
from backend.m5_session.runtime_events import RuntimeEventService
from backend.m5_session.teaching_service import TeachingService
from backend.m5_session.state_machine import assert_sub_status_allowed, view_for_status
from backend.m6_response.answer_generator import LlmStreamer, ToolAwareLlmStreamer
from backend.m6_response.llm_caller import stream_llm_response, stream_llm_response_with_tools
from backend.security.safety import build_default_read_policy


class SessionService:
    def __init__(self) -> None:
        self.store = SessionStore(active_session=None)
        self.llm_streamer: LlmStreamer = stream_llm_response
        self.tool_streamer: ToolAwareLlmStreamer = stream_llm_response_with_tools
        self.repository = SessionRepository(
            store=self.store,
            cleanup_temp_resources=self._cleanup_temp_resources,
        )
        self.events = RuntimeEventService(llm_error_builder=llm_failed_error)
        self.teaching = TeachingService()
        self.analysis_workflow = AnalysisWorkflow(
            repository=self.repository,
            events=self.events,
            teaching=self.teaching,
        )
        self.chat_workflow = ChatWorkflow(
            repository=self.repository,
            events=self.events,
            teaching=self.teaching,
        )
        self.reconnect_queries = ReconnectQueryService(
            repository=self.repository,
            events=self.events,
        )

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
        self.repository.set_active(context)
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
                {
                    "degradation_id": item.degradation_id,
                    "type": item.type,
                    "reason": item.reason,
                    "user_notice": item.user_notice,
                    "related_paths": item.related_paths,
                }
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
                    message="当前状态不允许发送消息。",
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
        self.events.append_runtime_event(
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
        return self.repository.require(session_id, allow_missing=allow_missing)

    def clear_active_session(self) -> None:
        self.repository.clear_active()

    async def run_initial_analysis(self, session_id: str) -> AsyncIterator[RuntimeEvent]:
        async for event in self.analysis_workflow.run(
            session_id,
            llm_streamer=self.llm_streamer,
            tool_streamer=self.tool_streamer,
        ):
            yield event

    async def run_chat_turn(self, session_id: str) -> AsyncIterator[RuntimeEvent]:
        async for event in self.chat_workflow.run(
            session_id,
            llm_streamer=self.llm_streamer,
            tool_streamer=self.tool_streamer,
        ):
            yield event

    def build_status_snapshot_event(self, session: SessionContext) -> RuntimeEvent:
        return self.events.build_status_snapshot_event(session)

    def latest_runtime_event(
        self,
        session_id: str,
        event_type: RuntimeEventType,
    ) -> RuntimeEvent | None:
        return self.repository.latest_runtime_event(session_id, event_type)

    def latest_initial_report_completed_event(self, session_id: str) -> RuntimeEvent | None:
        return self.repository.latest_initial_report_completed_event(session_id)

    def latest_chat_terminal_event(self, session_id: str) -> RuntimeEvent | None:
        return self.repository.latest_chat_terminal_event(session_id)

    def analysis_reconnect_events(self, session_id: str) -> list:
        return self.reconnect_queries.analysis_events(session_id)

    def chat_reconnect_events(self, session_id: str) -> list:
        return self.reconnect_queries.chat_events(session_id)

    def invalid_request_error(self, message: str) -> UserFacingError:
        return invalid_request_error(self.store.active_session, message)

    def analysis_failed_error(self, exc: Exception, *, stage: SessionStatus) -> UserFacingError:
        return analysis_failed_error(exc, stage=stage)

    def llm_failed_error(self, exc: Exception) -> UserFacingError:
        return llm_failed_error(exc)

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
