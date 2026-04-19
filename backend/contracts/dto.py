from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import Field, model_validator

from backend.contracts.domain import ContractModel, ProgressStepStateItem, UserFacingError
from backend.contracts.enums import (
    AgentActivityPhase,
    AnalysisMode,
    ClientView,
    ConfidenceLevel,
    ConversationSubStatus,
    DegradationType,
    DerivedStatus,
    EntryTargetType,
    ErrorCode,
    LearningGoal,
    MainPathRole,
    MessageRole,
    MessageType,
    ProgressStepKey,
    ProgressStepState,
    ProjectType,
    ReadingTargetType,
    RepoSizeLevel,
    RepoSourceType,
    RuntimeEventType,
    SessionStatus,
    UnknownTopic,
)

T = TypeVar("T")


class ApiEnvelope(ContractModel, Generic[T]):
    ok: bool
    session_id: str | None
    data: T | None = None
    error: UserFacingErrorDto | None = None

    @model_validator(mode="after")
    def validate_envelope_shape(self) -> ApiEnvelope[T]:
        if self.ok:
            if self.data is None or self.error is not None:
                raise ValueError("successful API envelopes must include data and omit error")
            return self
        if self.error is None or self.data is not None:
            raise ValueError("failed API envelopes must include error and omit data")
        return self


class ValidateRepoRequest(ContractModel):
    input_value: str


class SubmitRepoRequest(ContractModel):
    input_value: str
    analysis_mode: AnalysisMode = AnalysisMode.QUICK_GUIDE


class SendMessageRequest(ContractModel):
    message: str


class ExplainSidecarRequest(ContractModel):
    question: str


class RepositorySummaryDto(ContractModel):
    display_name: str
    source_type: RepoSourceType
    input_value: str
    primary_language: str | None = None
    repo_size_level: RepoSizeLevel | None = None
    source_code_file_count: int | None = None


class SuggestionDto(ContractModel):
    suggestion_id: str
    text: str
    target_goal: LearningGoal | None = None


class EvidenceLineDto(ContractModel):
    text: str
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel | None = None


class EntryCandidateDto(ContractModel):
    entry_id: str
    target_type: EntryTargetType
    target_value: str
    reason: str
    confidence: ConfidenceLevel
    rank: int
    evidence_refs: list[str] = Field(default_factory=list)


class ReadingStepDto(ContractModel):
    step_no: int
    target: str
    target_type: ReadingTargetType
    reason: str
    learning_gain: str
    skippable: str | None = None
    next_step_hint: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class UnknownItemDto(ContractModel):
    unknown_id: str
    topic: UnknownTopic
    description: str
    related_paths: list[str] = Field(default_factory=list)
    reason: str | None = None


class ProjectTypeCandidateDto(ContractModel):
    type: ProjectType
    reason: str
    confidence: ConfidenceLevel
    evidence_refs: list[str] = Field(default_factory=list)


class InitialReportContentDto(ContractModel):
    overview: InitialOverviewDto
    focus_points: list[InitialFocusPointDto] = Field(default_factory=list)
    repo_mapping: list[InitialRepoMappingDto] = Field(default_factory=list)
    language_and_type: InitialLanguageTypeDto
    key_directories: list[InitialKeyDirectoryDto] = Field(default_factory=list)
    entry_section: InitialEntrySectionDto
    recommended_first_step: InitialRecommendedStepDto
    reading_path_preview: list[ReadingStepDto] = Field(default_factory=list)
    unknown_section: list[UnknownItemDto] = Field(default_factory=list)
    suggested_next_questions: list[SuggestionDto] = Field(default_factory=list)


class InitialOverviewDto(ContractModel):
    summary: str
    confidence: ConfidenceLevel
    evidence_refs: list[str] = Field(default_factory=list)


class InitialFocusPointDto(ContractModel):
    title: str
    reason: str
    topic: LearningGoal


class InitialRepoMappingDto(ContractModel):
    concept: LearningGoal
    explanation: str
    mapped_paths: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel
    evidence_refs: list[str] = Field(default_factory=list)


class InitialLanguageTypeDto(ContractModel):
    primary_language: str
    project_types: list[ProjectTypeCandidateDto] = Field(default_factory=list)
    degradation_notice: str | None = None


class InitialKeyDirectoryDto(ContractModel):
    path: str
    role: str
    main_path_role: MainPathRole
    confidence: ConfidenceLevel
    evidence_refs: list[str] = Field(default_factory=list)


class InitialEntrySectionDto(ContractModel):
    status: DerivedStatus
    entries: list[EntryCandidateDto] = Field(default_factory=list)
    fallback_advice: str | None = None


class InitialRecommendedStepDto(ContractModel):
    target: str
    reason: str
    learning_gain: str
    evidence_refs: list[str] = Field(default_factory=list)


class StructuredMessageContentDto(ContractModel):
    focus: str
    direct_explanation: str
    relation_to_overall: str
    evidence_lines: list[EvidenceLineDto] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    next_steps: list[SuggestionDto] = Field(default_factory=list)


class UserFacingErrorDto(ContractModel):
    error_code: ErrorCode
    message: str
    retryable: bool
    stage: SessionStatus
    input_preserved: bool
    internal_detail: str | None = None

    @classmethod
    def from_domain(cls, error: UserFacingError) -> UserFacingErrorDto:
        return cls(
            error_code=error.error_code,
            message=error.message,
            retryable=error.retryable,
            stage=error.stage,
            input_preserved=error.input_preserved,
            internal_detail=error.internal_detail,
        )


class MessageErrorStateDto(ContractModel):
    error: UserFacingErrorDto
    failed_during_stream: bool
    partial_text_available: bool


class MessageDto(ContractModel):
    message_id: str
    role: MessageRole
    message_type: MessageType
    created_at: datetime
    raw_text: str
    structured_content: StructuredMessageContentDto | None = None
    initial_report_content: InitialReportContentDto | None = None
    related_goal: LearningGoal | None = None
    suggestions: list[SuggestionDto] = Field(default_factory=list)
    streaming_complete: bool
    error_state: MessageErrorStateDto | None = None

    @model_validator(mode="after")
    def validate_message_shape(self) -> MessageDto:
        if self.message_type == MessageType.INITIAL_REPORT:
            if self.initial_report_content is None or self.structured_content is not None:
                raise ValueError(
                    "initial_report messages must include initial_report_content and omit structured_content"
                )
        else:
            if self.initial_report_content is not None:
                raise ValueError("non-initial-report messages must omit initial_report_content")
            if (
                self.message_type
                in {
                    MessageType.AGENT_ANSWER,
                    MessageType.GOAL_SWITCH_CONFIRMATION,
                    MessageType.STAGE_SUMMARY,
                }
                and self.structured_content is None
            ):
                raise ValueError("structured agent messages must include structured_content")
        if self.role == MessageRole.USER:
            if self.structured_content is not None or self.initial_report_content is not None:
                raise ValueError("user messages must not include structured payloads")
        return self


class DegradationFlagDto(ContractModel):
    degradation_id: str
    type: DegradationType
    reason: str
    user_notice: str
    related_paths: list[str] = Field(default_factory=list)


class RelevantSourceFileDto(ContractModel):
    relative_path: str
    selected: bool
    source_kind: str
    group_key: str
    include_reason: str | None = None
    skip_reason: str | None = None
    size_bytes: int | None = None
    is_python_source: bool = False


class DeepResearchStateDto(ContractModel):
    phase: str
    total_files: int = 0
    completed_files: int = 0
    skipped_files: int = 0
    coverage_ratio: float = 0.0
    current_target: str | None = None
    last_completed_target: str | None = None
    relevant_files: list[RelevantSourceFileDto] = Field(default_factory=list)


class SessionSnapshotDto(ContractModel):
    session_id: str | None
    status: SessionStatus
    sub_status: ConversationSubStatus | None
    view: ClientView
    analysis_mode: AnalysisMode | None = None
    repository: RepositorySummaryDto | None = None
    progress_steps: list[ProgressStepStateItem] = Field(default_factory=list)
    degradation_notices: list[DegradationFlagDto] = Field(default_factory=list)
    messages: list[MessageDto] = Field(default_factory=list)
    active_agent_activity: AgentActivityDto | None = None
    active_error: UserFacingErrorDto | None = None
    deep_research_state: DeepResearchStateDto | None = None


class ValidateRepoData(ContractModel):
    input_kind: Literal["local_path", "github_url", "unknown"]
    is_valid: bool
    normalized_input: str | None = None
    message: str | None = None


class SubmitRepoData(ContractModel):
    accepted: Literal[True]
    status: SessionStatus
    sub_status: ConversationSubStatus | None
    view: ClientView
    analysis_mode: AnalysisMode
    repository: RepositorySummaryDto
    analysis_stream_url: str


class SendMessageData(ContractModel):
    accepted: Literal[True]
    status: Literal["chatting"]
    sub_status: Literal["agent_thinking"]
    user_message_id: str
    chat_stream_url: str


class ExplainSidecarData(ContractModel):
    answer: str


class ClearSessionData(ContractModel):
    status: Literal["idle"]
    sub_status: None
    view: Literal["input"]
    cleanup_completed: bool


class SseEventDto(ContractModel):
    event_id: str
    event_type: RuntimeEventType
    session_id: str
    occurred_at: datetime


class StatusChangedEvent(SseEventDto):
    event_type: Literal[RuntimeEventType.STATUS_CHANGED]
    status: SessionStatus
    sub_status: ConversationSubStatus | None
    view: ClientView


class AnalysisProgressEvent(SseEventDto):
    event_type: Literal[RuntimeEventType.ANALYSIS_PROGRESS]
    step_key: ProgressStepKey
    step_state: ProgressStepState
    user_notice: str
    progress_steps: list[ProgressStepStateItem] = Field(default_factory=list)
    deep_research_state: DeepResearchStateDto | None = None


class DegradationNoticeEvent(SseEventDto):
    event_type: Literal[RuntimeEventType.DEGRADATION_NOTICE]
    degradation: DegradationFlagDto


class AgentActivityDto(ContractModel):
    activity_id: str
    phase: AgentActivityPhase
    summary: str
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    round_index: int | None = None
    elapsed_ms: int | None = None
    soft_timed_out: bool = False
    failed: bool = False
    retryable: bool = False


class AgentActivityEvent(SseEventDto):
    event_type: Literal[RuntimeEventType.AGENT_ACTIVITY]
    activity: AgentActivityDto


class AnswerStreamStartEvent(SseEventDto):
    event_type: Literal[RuntimeEventType.ANSWER_STREAM_START]
    message_id: str
    message_type: MessageType


class AnswerStreamDeltaEvent(SseEventDto):
    event_type: Literal[RuntimeEventType.ANSWER_STREAM_DELTA]
    message_id: str
    delta_text: str
    structured_delta: dict[str, Any] | None = None


class AnswerStreamEndEvent(SseEventDto):
    event_type: Literal[RuntimeEventType.ANSWER_STREAM_END]
    message_id: str


class MessageCompletedEvent(SseEventDto):
    event_type: Literal[RuntimeEventType.MESSAGE_COMPLETED]
    message: MessageDto
    status: SessionStatus
    sub_status: ConversationSubStatus | None
    view: ClientView


class ErrorEvent(SseEventDto):
    event_type: Literal[RuntimeEventType.ERROR]
    error: UserFacingErrorDto
    status: SessionStatus
    sub_status: ConversationSubStatus | None
    view: ClientView


AnalysisSseEvent = (
    StatusChangedEvent
    | AnalysisProgressEvent
    | DegradationNoticeEvent
    | AgentActivityEvent
    | AnswerStreamStartEvent
    | AnswerStreamDeltaEvent
    | AnswerStreamEndEvent
    | MessageCompletedEvent
    | ErrorEvent
)

ChatSseEvent = (
    StatusChangedEvent
    | AgentActivityEvent
    | AnswerStreamStartEvent
    | AnswerStreamDeltaEvent
    | AnswerStreamEndEvent
    | MessageCompletedEvent
    | ErrorEvent
)


def success_envelope(
    session_id: str | None, data: ContractModel | dict[str, Any]
) -> dict[str, Any]:
    payload = data.model_dump(mode="json") if isinstance(data, ContractModel) else data
    return {"ok": True, "session_id": session_id, "data": payload}


def error_envelope(
    session_id: str | None, error: UserFacingError | UserFacingErrorDto
) -> dict[str, Any]:
    public_error = (
        error if isinstance(error, UserFacingErrorDto) else UserFacingErrorDto.from_domain(error)
    )
    return {"ok": False, "session_id": session_id, "error": public_error.model_dump(mode="json")}
