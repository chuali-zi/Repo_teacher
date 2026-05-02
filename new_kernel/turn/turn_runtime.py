"""Turn lifecycle runtime.

This module owns one active turn per session, cancellation token registration,
user/assistant message commits, and terminal turn events. It deliberately does
not implement orient/read/teach logic; those loops are injected.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, TypeAlias
from uuid import uuid4

from ..contracts import (
    AgentMetrics,
    AgentPetState,
    AgentPhase,
    AgentStatus,
    AgentStatusEvent,
    ApiError,
    CancelRunData,
    ChatMessage,
    ChatMode,
    ErrorCode,
    ErrorEvent,
    ErrorStage,
    MessageCompletedEvent,
    RepoTutorSseEvent,
    RepositoryStatus,
    SendTeachingMessageData,
    SendTeachingMessageRequest,
    SseEventType,
    TeachingCodeSnippet,
    RunCancelledEvent,
)
from .cancellation import CancelledError, CancellationToken, CancelReason


PetMood: TypeAlias = Literal["idle", "think", "act", "scan", "teach", "research", "error"]
TaskFactory: TypeAlias = Callable[[Coroutine[Any, Any, None]], asyncio.Task[None]]


class EventSink(Protocol):
    async def emit(self, event: RepoTutorSseEvent) -> None:
        ...


class TurnEventFactory(Protocol):
    def agent_status_event(self, *, session_id: str, status: AgentStatus) -> AgentStatusEvent:
        ...

    def message_completed_event(
        self,
        *,
        session_id: str,
        message: ChatMessage,
        agent_status: AgentStatus | None = None,
        current_code: TeachingCodeSnippet | None = None,
    ) -> MessageCompletedEvent:
        ...

    def run_cancelled_event(
        self,
        *,
        session_id: str,
        agent_status: AgentStatus,
        turn_id: str | None = None,
    ) -> RunCancelledEvent:
        ...

    def error_event(
        self,
        *,
        session_id: str,
        error: ApiError,
        agent_status: AgentStatus | None = None,
    ) -> ErrorEvent:
        ...


class StatusTracker(Protocol):
    @property
    def current(self) -> AgentStatus:
        ...

    async def update_phase(
        self,
        *,
        state: AgentPetState,
        phase: AgentPhase,
        label: str,
        pet_mood: PetMood,
        pet_message: str,
        current_action: str | None = None,
        current_target: str | None = None,
        emit: bool = True,
    ) -> AgentStatus:
        ...

    async def add_metrics(
        self,
        *,
        llm_call: int = 0,
        tool_call: int = 0,
        tokens: int = 0,
        elapsed_ms: int = 0,
        emit: bool = False,
    ) -> AgentStatus:
        ...


class TurnLoop(Protocol):
    async def run(
        self,
        *,
        session_id: str,
        turn_id: str,
        user_message: str,
        scratchpad: Any,
        repo_overview: str,
        repo_root: Path,
        sink: EventSink,
        status_tracker: StatusTracker,
        cancellation_token: CancellationToken,
    ) -> ChatMessage:
        ...


class TurnSessionState(Protocol):
    session_id: str
    event_bus: EventSink
    agent_status: AgentStatus
    mode: ChatMode
    repository: Any | None
    repo_root: Path | str | None
    messages: list[ChatMessage]
    scratchpad: Any
    current_code: TeachingCodeSnippet | None
    active_turn_id: str | None


StatusTrackerFactory: TypeAlias = Callable[
    [TurnSessionState, EventSink, TurnEventFactory],
    StatusTracker,
]


class TurnRuntimeError(Exception):
    """Base runtime error that can be mapped to a public ApiError."""

    def __init__(
        self,
        message: str,
        *,
        error_code: ErrorCode = ErrorCode.INVALID_STATE,
        retryable: bool = False,
        internal_detail: str | None = None,
    ) -> None:
        self.message = message
        self.error_code = error_code
        self.retryable = retryable
        self.internal_detail = internal_detail
        super().__init__(message)

    def to_api_error(self, *, stage: ErrorStage) -> ApiError:
        return ApiError(
            error_code=self.error_code,
            message=self.message,
            retryable=self.retryable,
            stage=stage,
            input_preserved=True,
            internal_detail=self.internal_detail,
        )


class InvalidTurnStateError(TurnRuntimeError):
    """Raised when a turn cannot start from the current session state."""


class TurnDependencyError(TurnRuntimeError):
    """Raised when a required injected dependency is missing or malformed."""


class TurnRuntime:
    """Owns turn mutual exclusion, background execution, and cancellation."""

    def __init__(
        self,
        *,
        teaching_loop: TurnLoop,
        deep_loop: TurnLoop,
        idle_status_factory: Callable[[str], AgentStatus] | None = None,
        event_factory: TurnEventFactory | None = None,
        status_tracker_factory: StatusTrackerFactory | None = None,
        task_factory: TaskFactory | None = None,
        turn_id_factory: Callable[[], str] | None = None,
        message_id_factory: Callable[[str], str] | None = None,
        chat_stream_url_template: str = (
            "/api/v4/chat/stream?session_id={session_id}&turn_id={turn_id}"
        ),
    ) -> None:
        self._teaching_loop = teaching_loop
        self._deep_loop = deep_loop
        self._idle_status_factory = idle_status_factory or _default_idle_status
        self._event_factory = event_factory or _ContractTurnEventFactory()
        self._status_tracker_factory = status_tracker_factory or _make_status_tracker
        self._task_factory = task_factory or asyncio.create_task
        self._turn_id_factory = turn_id_factory or _new_turn_id
        self._message_id_factory = message_id_factory or _new_message_id
        self._chat_stream_url_template = chat_stream_url_template

        self._tokens: dict[str, CancellationToken] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._trackers: dict[str, StatusTracker] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def start_turn(
        self,
        *,
        state: TurnSessionState,
        request: SendTeachingMessageRequest,
        initiator: Literal["user", "system"] = "user",
    ) -> SendTeachingMessageData:
        session_id = _session_id(state)
        mode = _mode(request.mode)
        lock = self._lock_for(session_id)

        async with lock:
            if state.active_turn_id is not None:
                raise InvalidTurnStateError(
                    "当前会话已有正在运行的回答，请先等待完成或取消后再发送。",
                    internal_detail=f"active_turn_id={state.active_turn_id}",
                )

            sink = _event_sink(state)
            repo_root = _repo_root_or_error(state)
            _ensure_repository_ready(state)
            _ensure_messages_owner_shape(state)

            turn_id = self._turn_id_factory()
            user_message_id = self._message_id_factory(
                "msg_system" if initiator == "system" else "msg_user"
            )
            token = CancellationToken(session_id=session_id, turn_id=turn_id)
            user_message = ChatMessage(
                message_id=user_message_id,
                role=initiator,
                mode=mode,
                content=request.message,
                created_at=_now_utc(),
                streaming_complete=True,
            )
            tracker = self._status_tracker_factory(state, sink, self._event_factory)

            state.active_turn_id = turn_id
            state.mode = mode
            state.messages.append(user_message)
            self._tokens[session_id] = token
            self._trackers[session_id] = tracker

            agent_status = await self._mark_started(tracker, mode)
            task = self._task_factory(
                self._run_turn(
                    state=state,
                    request=request,
                    mode=mode,
                    turn_id=turn_id,
                    repo_root=repo_root,
                    sink=sink,
                    status_tracker=tracker,
                    cancellation_token=token,
                )
            )
            task.add_done_callback(_observe_task_result)
            self._tasks[session_id] = task

            return SendTeachingMessageData(
                accepted=True,
                session_id=session_id,
                turn_id=turn_id,
                user_message_id=user_message_id,
                chat_stream_url=self._chat_stream_url_template.format(
                    session_id=session_id,
                    turn_id=turn_id,
                ),
                agent_status=agent_status,
            )

    async def cancel(
        self,
        *,
        state: TurnSessionState,
        reason: CancelReason,
    ) -> CancelRunData:
        session_id = _session_id(state)
        lock = self._lock_for(session_id)

        async with lock:
            token = self._tokens.get(session_id)
            if token is None or state.active_turn_id is None:
                return CancelRunData(
                    cancelled=False,
                    session_id=session_id,
                    agent_status=getattr(
                        state,
                        "agent_status",
                        self._idle_status_factory(session_id),
                    ),
                )
            token.cancel(reason)
            tracker = self._trackers.get(session_id)

        if tracker is None:
            sink = _event_sink(state)
            tracker = self._status_tracker_factory(state, sink, self._event_factory)
            self._trackers[session_id] = tracker

        status = await self._mark_cancelled(tracker)
        return CancelRunData(cancelled=True, session_id=session_id, agent_status=status)

    def active_token(self, session_id: str) -> CancellationToken | None:
        return self._tokens.get(session_id)

    def active_task(self, session_id: str) -> asyncio.Task[None] | None:
        return self._tasks.get(session_id)

    def _lock_for(self, session_id: str) -> asyncio.Lock:
        lock = self._locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        return lock

    async def _run_turn(
        self,
        *,
        state: TurnSessionState,
        request: SendTeachingMessageRequest,
        mode: ChatMode,
        turn_id: str,
        repo_root: Path,
        sink: EventSink,
        status_tracker: StatusTracker,
        cancellation_token: CancellationToken,
    ) -> None:
        session_id = _session_id(state)
        try:
            cancellation_token.raise_if_cancelled()
            loop = self._deep_loop if mode == ChatMode.DEEP else self._teaching_loop
            assistant_message = await loop.run(
                session_id=session_id,
                turn_id=turn_id,
                user_message=request.message,
                scratchpad=state.scratchpad,
                repo_overview=_repo_overview(state),
                repo_root=repo_root,
                sink=sink,
                status_tracker=status_tracker,
                cancellation_token=cancellation_token,
            )
            cancellation_token.raise_if_cancelled()
            assistant_message = _normalize_assistant_message(assistant_message, mode)
            completed_status = await self._mark_completed(status_tracker)
            cancellation_token.raise_if_cancelled()

            state.messages.append(assistant_message)
            await _emit_to_sink(
                sink,
                self._event_factory.message_completed_event(
                    session_id=session_id,
                    message=assistant_message,
                    agent_status=completed_status,
                    current_code=getattr(state, "current_code", None),
                ),
            )
        except CancelledError:
            status = await self._mark_cancelled(status_tracker)
            await _emit_to_sink(
                sink,
                self._event_factory.run_cancelled_event(
                    session_id=session_id,
                    turn_id=turn_id,
                    agent_status=status,
                ),
            )
        except Exception as exc:
            error = _exception_to_api_error(exc, mode=mode)
            status = await self._mark_failed(status_tracker, error.message)
            await _emit_to_sink(
                sink,
                self._event_factory.error_event(
                    session_id=session_id,
                    error=error,
                    agent_status=status,
                ),
            )
        finally:
            await self._clear_active_turn(state=state, turn_id=turn_id)

    async def _clear_active_turn(self, *, state: TurnSessionState, turn_id: str) -> None:
        session_id = _session_id(state)
        lock = self._lock_for(session_id)
        async with lock:
            if state.active_turn_id == turn_id:
                state.active_turn_id = None
            token = self._tokens.get(session_id)
            if token is not None and token.turn_id == turn_id:
                self._tokens.pop(session_id, None)
            task = asyncio.current_task()
            if task is not None and self._tasks.get(session_id) is task:
                self._tasks.pop(session_id, None)
            self._trackers.pop(session_id, None)

    async def _mark_started(self, tracker: StatusTracker, mode: ChatMode) -> AgentStatus:
        if mode == ChatMode.DEEP:
            return await tracker.update_phase(
                state=AgentPetState.RESEARCHING,
                phase=AgentPhase.RESEARCHING,
                label="深度研究中",
                pet_mood="research",
                pet_message="正在规划研究路径",
                current_action="规划深度研究",
            )
        return await tracker.update_phase(
            state=AgentPetState.THINKING,
            phase=AgentPhase.PLANNING,
            label="思考中",
            pet_mood="think",
            pet_message="正在理解问题并规划阅读路径",
            current_action="规划阅读路径",
        )

    async def _mark_completed(self, tracker: StatusTracker) -> AgentStatus:
        return await tracker.update_phase(
            state=AgentPetState.TEACHING,
            phase=AgentPhase.IDLE_AFTER_TEACH,
            label="教学中",
            pet_mood="teach",
            pet_message="等待你的下一个问题",
            current_action="等待追问",
        )

    async def _mark_cancelled(self, tracker: StatusTracker) -> AgentStatus:
        return await tracker.update_phase(
            state=AgentPetState.IDLE,
            phase=AgentPhase.CANCELLED,
            label="待机中",
            pet_mood="idle",
            pet_message="已中断",
            current_action=None,
            current_target=None,
        )

    async def _mark_failed(self, tracker: StatusTracker, message: str) -> AgentStatus:
        return await tracker.update_phase(
            state=AgentPetState.ERROR,
            phase=AgentPhase.FAILED,
            label="回答失败",
            pet_mood="error",
            pet_message=message,
            current_action=None,
            current_target=None,
        )


class _ContractTurnEventFactory:
    def agent_status_event(self, *, session_id: str, status: AgentStatus) -> AgentStatusEvent:
        return AgentStatusEvent(
            **_event_base(session_id=session_id, event_type=SseEventType.AGENT_STATUS),
            status=status,
        )

    def message_completed_event(
        self,
        *,
        session_id: str,
        message: ChatMessage,
        agent_status: AgentStatus | None = None,
        current_code: TeachingCodeSnippet | None = None,
    ) -> MessageCompletedEvent:
        return MessageCompletedEvent(
            **_event_base(session_id=session_id, event_type=SseEventType.MESSAGE_COMPLETED),
            message=message,
            agent_status=agent_status,
            current_code=current_code,
        )

    def run_cancelled_event(
        self,
        *,
        session_id: str,
        agent_status: AgentStatus,
        turn_id: str | None = None,
    ) -> RunCancelledEvent:
        return RunCancelledEvent(
            **_event_base(session_id=session_id, event_type=SseEventType.RUN_CANCELLED),
            turn_id=turn_id,
            agent_status=agent_status,
        )

    def error_event(
        self,
        *,
        session_id: str,
        error: ApiError,
        agent_status: AgentStatus | None = None,
    ) -> ErrorEvent:
        return ErrorEvent(
            **_event_base(session_id=session_id, event_type=SseEventType.ERROR),
            error=error,
            agent_status=agent_status,
        )


class _TurnStatusTracker:
    def __init__(
        self,
        *,
        state: TurnSessionState,
        sink: EventSink,
        event_factory: TurnEventFactory,
    ) -> None:
        self._state = state
        self._sink = sink
        self._event_factory = event_factory
        self._current = getattr(state, "agent_status", _default_idle_status(state.session_id))

    @property
    def current(self) -> AgentStatus:
        return self._current

    async def update_phase(
        self,
        *,
        state: AgentPetState,
        phase: AgentPhase,
        label: str,
        pet_mood: PetMood,
        pet_message: str,
        current_action: str | None = None,
        current_target: str | None = None,
        emit: bool = True,
    ) -> AgentStatus:
        status = AgentStatus(
            session_id=self._current.session_id,
            state=state,
            phase=phase,
            label=label,
            pet_mood=pet_mood,
            pet_message=pet_message,
            current_action=current_action,
            current_target=current_target,
            metrics=self._current.metrics,
            updated_at=_now_utc(),
        )
        self._set_current(status)
        if emit:
            await _emit_to_sink(
                self._sink,
                self._event_factory.agent_status_event(
                    session_id=status.session_id,
                    status=status,
                ),
            )
        return status

    async def add_metrics(
        self,
        *,
        llm_call: int = 0,
        tool_call: int = 0,
        tokens: int = 0,
        elapsed_ms: int = 0,
        emit: bool = False,
    ) -> AgentStatus:
        current = self._current
        metrics = AgentMetrics(
            llm_call_count=current.metrics.llm_call_count + llm_call,
            tool_call_count=current.metrics.tool_call_count + tool_call,
            token_count=current.metrics.token_count + tokens,
            elapsed_ms=current.metrics.elapsed_ms + elapsed_ms,
        )
        status = current.model_copy(update={"metrics": metrics, "updated_at": _now_utc()})
        self._set_current(status)
        if emit:
            await _emit_to_sink(
                self._sink,
                self._event_factory.agent_status_event(
                    session_id=status.session_id,
                    status=status,
                ),
            )
        return status

    def _set_current(self, status: AgentStatus) -> None:
        self._current = status
        self._state.agent_status = status


def _make_status_tracker(
    state: TurnSessionState,
    sink: EventSink,
    event_factory: TurnEventFactory,
) -> StatusTracker:
    return _TurnStatusTracker(state=state, sink=sink, event_factory=event_factory)


async def _emit_to_sink(sink: EventSink, event: RepoTutorSseEvent) -> None:
    emit = getattr(sink, "emit", None)
    if emit is None:
        emit = getattr(sink, "publish", None)
    if emit is None:
        raise TurnDependencyError(
            "当前会话缺少可用的事件通道，无法推送运行状态。",
            internal_detail="event sink must expose emit(event)",
        )
    result = emit(event)
    if inspect.isawaitable(result):
        await result


def _event_sink(state: TurnSessionState) -> EventSink:
    sink = getattr(state, "event_bus", None)
    if sink is None:
        raise TurnDependencyError(
            "当前会话缺少事件通道，无法开始回答。",
            internal_detail="SessionState.event_bus is missing",
        )
    return sink


def _session_id(state: TurnSessionState) -> str:
    session_id = getattr(state, "session_id", None)
    if not session_id:
        raise TurnDependencyError(
            "当前会话状态不完整，无法开始回答。",
            internal_detail="SessionState.session_id is missing",
        )
    return str(session_id)


def _mode(value: ChatMode | str) -> ChatMode:
    return ChatMode(value)


def _repo_root_or_error(state: TurnSessionState) -> Path:
    repo_root = getattr(state, "repo_root", None)
    if repo_root is None:
        raise InvalidTurnStateError(
            "仓库尚未准备好，请等待仓库接入完成后再提问。",
            internal_detail="SessionState.repo_root is missing",
        )
    return repo_root if isinstance(repo_root, Path) else Path(repo_root)


def _ensure_repository_ready(state: TurnSessionState) -> None:
    repository = getattr(state, "repository", None)
    if repository is None:
        raise InvalidTurnStateError(
            "仓库尚未准备好，请等待仓库接入完成后再提问。",
            internal_detail="SessionState.repository is missing",
        )
    status = getattr(repository, "status", None)
    if status is not None and status != RepositoryStatus.READY and status != "ready":
        raise InvalidTurnStateError(
            "仓库仍在接入中，请等待完成后再提问。",
            internal_detail=f"repository.status={status}",
        )


def _ensure_messages_owner_shape(state: TurnSessionState) -> None:
    messages = getattr(state, "messages", None)
    if not isinstance(messages, list):
        raise TurnDependencyError(
            "当前会话消息容器不可用，无法开始回答。",
            internal_detail="SessionState.messages must be a list",
        )
    if not hasattr(state, "scratchpad"):
        raise TurnDependencyError(
            "当前会话缺少 scratchpad，无法开始回答。",
            internal_detail="SessionState.scratchpad is missing",
        )


def _repo_overview(state: TurnSessionState) -> str:
    overview = getattr(state, "repo_overview", None)
    if overview is None:
        overview = getattr(state, "overview", None)
    text = getattr(overview, "text", None)
    if text:
        return str(text)

    repository = getattr(state, "repository", None)
    lines = ["repo_overview:"]
    if repository is not None:
        lines.append(f"- display_name: {getattr(repository, 'display_name', 'unknown')}")
        lines.append(f"- primary_language: {getattr(repository, 'primary_language', None) or 'unknown'}")
        lines.append(f"- file_count: {getattr(repository, 'file_count', 0)}")
    current_code = getattr(state, "current_code", None)
    if current_code is not None:
        lines.append("- current_code:")
        lines.append(f"  - path: {current_code.path}")
        lines.append(f"  - lines: {current_code.start_line}-{current_code.end_line}")
    return "\n".join(lines)


def _normalize_assistant_message(message: ChatMessage, mode: ChatMode) -> ChatMessage:
    if not isinstance(message, ChatMessage):
        raise TurnDependencyError(
            "教学循环没有返回合法的 assistant 消息。",
            internal_detail=f"loop returned {type(message).__name__}",
        )
    if message.role != "assistant":
        raise TurnDependencyError(
            "教学循环返回了非 assistant 消息。",
            internal_detail=f"role={message.role}",
        )
    updates: dict[str, Any] = {}
    if _mode(message.mode) != mode:
        updates["mode"] = mode
    if not message.streaming_complete:
        updates["streaming_complete"] = True
    return message.model_copy(update=updates) if updates else message


def _exception_to_api_error(exc: Exception, *, mode: ChatMode) -> ApiError:
    stage = ErrorStage.DEEP_RESEARCH if mode == ChatMode.DEEP else ErrorStage.CHAT
    if isinstance(exc, TurnRuntimeError):
        return exc.to_api_error(stage=stage)
    return ApiError(
        error_code=ErrorCode.LLM_API_FAILED,
        message="回答生成失败，请稍后重试。",
        retryable=True,
        stage=stage,
        input_preserved=True,
        internal_detail=str(exc) or type(exc).__name__,
    )


def _observe_task_result(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception:
        return


def _event_base(*, session_id: str, event_type: SseEventType) -> dict[str, Any]:
    return {
        "event_id": f"evt_{uuid4().hex[:12]}",
        "event_type": event_type,
        "session_id": session_id,
        "occurred_at": _now_utc(),
    }


def _default_idle_status(session_id: str) -> AgentStatus:
    return AgentStatus(
        session_id=session_id,
        state=AgentPetState.IDLE,
        phase=AgentPhase.IDLE,
        label="待机中",
        pet_mood="idle",
        pet_message="等待你的问题",
        current_action=None,
        current_target=None,
        metrics=AgentMetrics(),
        updated_at=_now_utc(),
    )


def _new_turn_id() -> str:
    return f"turn_{uuid4().hex[:12]}"


def _new_message_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _now_utc() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "EventSink",
    "InvalidTurnStateError",
    "StatusTracker",
    "TurnDependencyError",
    "TurnEventFactory",
    "TurnLoop",
    "TurnRuntime",
    "TurnRuntimeError",
    "TurnSessionState",
]
