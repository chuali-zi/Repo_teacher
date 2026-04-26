from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


T = TypeVar("T")


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class ErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    GITHUB_URL_INVALID = "github_url_invalid"
    GITHUB_REPO_INACCESSIBLE = "github_repo_inaccessible"
    GIT_CLONE_TIMEOUT = "git_clone_timeout"
    GIT_CLONE_FAILED = "git_clone_failed"
    REPO_SCAN_FAILED = "repo_scan_failed"
    SESSION_NOT_FOUND = "session_not_found"
    INVALID_STATE = "invalid_state"
    LLM_API_FAILED = "llm_api_failed"
    LLM_API_TIMEOUT = "llm_api_timeout"
    RUN_CANCELLED = "run_cancelled"


class ErrorStage(StrEnum):
    IDLE = "idle"
    REPO_PARSE = "repo_parse"
    CHAT = "chat"
    DEEP_RESEARCH = "deep_research"
    SIDECAR = "sidecar"


class ApiError(ContractModel):
    error_code: ErrorCode
    message: str
    retryable: bool
    stage: ErrorStage
    input_preserved: bool = True
    internal_detail: str | None = None


class ApiEnvelope(ContractModel, Generic[T]):
    ok: bool
    session_id: str | None = None
    data: T | None = None
    error: ApiError | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "ApiEnvelope[T]":
        if self.ok:
            if self.data is None or self.error is not None:
                raise ValueError("successful envelope must include data and omit error")
        elif self.error is None or self.data is not None:
            raise ValueError("failed envelope must include error and omit data")
        return self


class ChatMode(StrEnum):
    CHAT = "chat"
    DEEP = "deep"


class RepoSource(StrEnum):
    GITHUB_URL = "github_url"


class RepositoryStatus(StrEnum):
    CONNECTING = "connecting"
    SCANNING = "scanning"
    READY = "ready"
    ERROR = "error"


class AgentPetState(StrEnum):
    IDLE = "idle"
    THINKING = "thinking"
    ACTING = "acting"
    SCANNING = "scanning"
    TEACHING = "teaching"
    RESEARCHING = "researching"
    ERROR = "error"


class AgentPhase(StrEnum):
    IDLE = "idle"
    RESOLVING_GITHUB = "resolving_github"
    CLONING_REPO = "cloning_repo"
    SCANNING_TREE = "scanning_tree"
    BUILDING_OVERVIEW = "building_overview"
    SELECTING_TEACHING_SLICE = "selecting_teaching_slice"
    PLANNING = "planning"
    READING_CODE = "reading_code"
    TEACHING = "teaching"
    RESEARCHING = "researching"
    STREAMING = "streaming"
    IDLE_AFTER_TEACH = "idle_after_teach"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ParseStage(StrEnum):
    VALIDATING_URL = "validating_url"
    RESOLVING_METADATA = "resolving_metadata"
    CLONING = "cloning"
    SCANNING_TREE = "scanning_tree"
    BUILDING_OVERVIEW = "building_overview"
    SELECTING_TEACHING_SLICE = "selecting_teaching_slice"
    COMPLETED = "completed"


class LogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class SseEventType(StrEnum):
    AGENT_STATUS = "agent_status"
    REPO_PARSE_LOG = "repo_parse_log"
    REPO_CONNECTED = "repo_connected"
    TEACHING_CODE = "teaching_code"
    ANSWER_STREAM_START = "answer_stream_start"
    ANSWER_STREAM_DELTA = "answer_stream_delta"
    ANSWER_STREAM_END = "answer_stream_end"
    MESSAGE_COMPLETED = "message_completed"
    DEEP_RESEARCH_PROGRESS = "deep_research_progress"
    RUN_CANCELLED = "run_cancelled"
    ERROR = "error"


class ResolveGithubUrlRequest(ContractModel):
    input_value: str = Field(min_length=1)


class CreateRepositorySessionRequest(ContractModel):
    input_value: str = Field(min_length=1)
    branch: str | None = None
    mode: ChatMode = ChatMode.CHAT


class SendTeachingMessageRequest(ContractModel):
    message: str = Field(min_length=1)
    mode: ChatMode = ChatMode.CHAT
    client_message_id: str | None = None


class SidecarExplainRequest(ContractModel):
    term: str = Field(min_length=1)
    session_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class CancelRunRequest(ContractModel):
    reason: Literal["user_escape", "new_repo", "manual"] = "manual"


class GithubRepositoryRef(ContractModel):
    owner: str
    repo: str
    normalized_url: str
    default_branch: str | None = None
    resolved_branch: str | None = None
    commit_sha: str | None = None


class ResolveGithubUrlData(ContractModel):
    input_kind: Literal["github_url", "unknown"]
    is_valid: bool
    normalized_url: str | None = None
    owner: str | None = None
    repo: str | None = None
    default_branch: str | None = None
    display_name: str | None = None
    message: str | None = None


class RepositorySummary(ContractModel):
    repo_id: str
    display_name: str
    source: RepoSource
    github: GithubRepositoryRef
    primary_language: str | None = None
    file_count: int = 0
    status: RepositoryStatus


class AgentMetrics(ContractModel):
    llm_call_count: int = 0
    tool_call_count: int = 0
    token_count: int = 0
    elapsed_ms: int = 0


class AgentStatus(ContractModel):
    session_id: str
    state: AgentPetState
    phase: AgentPhase
    label: str
    pet_mood: Literal["idle", "think", "act", "scan", "teach", "research", "error"]
    pet_message: str
    current_action: str | None = None
    current_target: str | None = None
    metrics: AgentMetrics = Field(default_factory=AgentMetrics)
    updated_at: datetime


class ParseLogLine(ContractModel):
    line_id: str
    stage: ParseStage
    level: LogLevel = LogLevel.INFO
    text: str
    path: str | None = None
    progress: float | None = Field(default=None, ge=0.0, le=1.0)


class TeachingCodeSnippet(ContractModel):
    snippet_id: str
    path: str
    language: str | None = None
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    title: str | None = None
    reason: str | None = None
    code: str

    @model_validator(mode="after")
    def validate_line_range(self) -> "TeachingCodeSnippet":
        if self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
        return self


class ChatMessage(ContractModel):
    message_id: str
    role: Literal["system", "user", "assistant"]
    mode: ChatMode = ChatMode.CHAT
    content: str
    created_at: datetime
    streaming_complete: bool = True
    suggestions: list[str] = Field(default_factory=list)


class CreateRepositorySessionData(ContractModel):
    accepted: Literal[True]
    session_id: str
    repository: RepositorySummary
    agent_status: AgentStatus
    repo_stream_url: str
    status_url: str


class RepoConnectedData(ContractModel):
    repository: RepositorySummary
    initial_message: str
    current_code: TeachingCodeSnippet | None = None


class SendTeachingMessageData(ContractModel):
    accepted: Literal[True]
    session_id: str
    turn_id: str
    user_message_id: str
    chat_stream_url: str
    agent_status: AgentStatus


class SidecarExplainData(ContractModel):
    term: str
    explanation: str
    short_label: str | None = None
    related_paths: list[str] = Field(default_factory=list)


class CancelRunData(ContractModel):
    cancelled: bool
    session_id: str
    agent_status: AgentStatus


class SessionSnapshotData(ContractModel):
    session_id: str | None
    repository: RepositorySummary | None = None
    agent_status: AgentStatus | None = None
    parse_log: list[ParseLogLine] = Field(default_factory=list)
    messages: list[ChatMessage] = Field(default_factory=list)
    current_code: TeachingCodeSnippet | None = None
    mode: ChatMode = ChatMode.CHAT


class SseEvent(ContractModel):
    event_id: str
    event_type: SseEventType
    session_id: str
    occurred_at: datetime


class AgentStatusEvent(SseEvent):
    event_type: Literal[SseEventType.AGENT_STATUS]
    status: AgentStatus


class RepoParseLogEvent(SseEvent):
    event_type: Literal[SseEventType.REPO_PARSE_LOG]
    log: ParseLogLine


class RepoConnectedEvent(SseEvent):
    event_type: Literal[SseEventType.REPO_CONNECTED]
    repository: RepositorySummary
    initial_message: str
    current_code: TeachingCodeSnippet | None = None


class TeachingCodeEvent(SseEvent):
    event_type: Literal[SseEventType.TEACHING_CODE]
    snippet: TeachingCodeSnippet


class AnswerStreamStartEvent(SseEvent):
    event_type: Literal[SseEventType.ANSWER_STREAM_START]
    turn_id: str
    message_id: str
    mode: ChatMode


class AnswerStreamDeltaEvent(SseEvent):
    event_type: Literal[SseEventType.ANSWER_STREAM_DELTA]
    turn_id: str
    message_id: str
    delta_text: str


class AnswerStreamEndEvent(SseEvent):
    event_type: Literal[SseEventType.ANSWER_STREAM_END]
    turn_id: str
    message_id: str


class MessageCompletedEvent(SseEvent):
    event_type: Literal[SseEventType.MESSAGE_COMPLETED]
    message: ChatMessage
    agent_status: AgentStatus | None = None
    current_code: TeachingCodeSnippet | None = None


class DeepResearchProgressEvent(SseEvent):
    event_type: Literal[SseEventType.DEEP_RESEARCH_PROGRESS]
    turn_id: str
    phase: str
    summary: str
    completed_units: int = 0
    total_units: int = 0
    current_target: str | None = None


class RunCancelledEvent(SseEvent):
    event_type: Literal[SseEventType.RUN_CANCELLED]
    turn_id: str | None = None
    agent_status: AgentStatus


class ErrorEvent(SseEvent):
    event_type: Literal[SseEventType.ERROR]
    error: ApiError
    agent_status: AgentStatus | None = None


RepoTutorSseEvent = (
    AgentStatusEvent
    | RepoParseLogEvent
    | RepoConnectedEvent
    | TeachingCodeEvent
    | AnswerStreamStartEvent
    | AnswerStreamDeltaEvent
    | AnswerStreamEndEvent
    | MessageCompletedEvent
    | DeepResearchProgressEvent
    | RunCancelledEvent
    | ErrorEvent
)


STREAM_EVENT_NAMES = tuple(item.value for item in SseEventType)


HTTP_ENDPOINTS = {
    "resolve_github": "POST /api/v4/github/resolve",
    "create_repository_session": "POST /api/v4/repositories",
    "repository_stream": "GET /api/v4/repositories/stream?session_id={session_id}",
    "agent_status": "GET /api/v4/agent/status?session_id={session_id}",
    "send_chat_message": "POST /api/v4/chat/messages",
    "chat_stream": "GET /api/v4/chat/stream?session_id={session_id}&turn_id={turn_id}",
    "sidecar_explain": "POST /api/v4/sidecar/explain",
    "session_snapshot": "GET /api/v4/session?session_id={session_id}",
    "cancel": "POST /api/v4/control/cancel",
}
