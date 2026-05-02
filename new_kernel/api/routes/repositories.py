"""Repository session creation and repository SSE endpoints."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Query, Request, status

from ...contracts import (
    AgentMetrics,
    AgentPetState,
    AgentPhase,
    AgentStatus,
    ApiEnvelope,
    ChatMode,
    CreateRepositorySessionData,
    CreateRepositorySessionRequest,
    ErrorCode,
    ErrorStage,
    GithubRepositoryRef,
    ParseLogLine,
    RepoConnectedData,
    RepoSource,
    RepositoryStatus,
    RepositorySummary,
    SendTeachingMessageRequest,
)
from ..dependencies import (
    ApiRuntime,
    call_maybe_async,
    get_runtime,
    get_session,
    get_session_id,
    maybe_await,
    require_dependency,
)
from ..envelope import success
from ..errors import ApiModuleError, api_error
from ..sse import sse_response


router = APIRouter(prefix="/api/v4/repositories", tags=["repositories"])


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ApiEnvelope[CreateRepositorySessionData],
    response_model_exclude_none=True,
)
async def create_repository_session(
    payload: CreateRepositorySessionRequest,
    request: Request,
) -> ApiEnvelope[CreateRepositorySessionData]:
    runtime = get_runtime(request)
    store = require_dependency(runtime, "session_store", stage=ErrorStage.REPO_PARSE)
    resolver = require_dependency(runtime, "github_resolver", stage=ErrorStage.REPO_PARSE)
    pipeline = require_dependency(runtime, "repo_pipeline", stage=ErrorStage.REPO_PARSE)

    resolved = await _resolve_without_remote_check(resolver, payload.input_value)
    if (
        not resolved.is_valid
        or resolved.normalized_url is None
        or resolved.owner is None
        or resolved.repo is None
    ):
        raise ApiModuleError(
            api_error(
                error_code=ErrorCode.GITHUB_URL_INVALID,
                message=resolved.message or "GitHub 仓库地址格式不正确。",
                retryable=False,
                stage=ErrorStage.REPO_PARSE,
            ),
            status_code=400,
        )

    session = await _create_session(store, mode=payload.mode)
    session_id = get_session_id(session)
    repository = _pending_repository(
        session_id=session_id,
        owner=resolved.owner,
        repo=resolved.repo,
        normalized_url=resolved.normalized_url,
        branch=payload.branch or resolved.default_branch,
        default_branch=resolved.default_branch,
    )
    agent_status = _status(
        session_id=session_id,
        phase=AgentPhase.RESOLVING_GITHUB,
        label="正在校验 GitHub 仓库地址",
        current_target=repository.display_name,
    )
    _set_if_possible(session, "mode", payload.mode)
    _set_if_possible(session, "repository", repository)
    _set_if_possible(session, "agent_status", agent_status)

    task = asyncio.create_task(
        _run_parse_pipeline(
            runtime=runtime,
            pipeline=pipeline,
            session=session,
            payload=payload,
        )
    )
    runtime.background_tasks.add(task)
    task.add_done_callback(runtime.background_tasks.discard)

    data = CreateRepositorySessionData(
        accepted=True,
        session_id=session_id,
        repository=repository,
        agent_status=agent_status,
        repo_stream_url=f"/api/v4/repositories/stream?session_id={session_id}",
        status_url=f"/api/v4/agent/status?session_id={session_id}",
    )
    return success(data, session_id=session_id)


@router.get("/stream")
async def repository_stream(
    request: Request,
    session_id: str = Query(min_length=1),
):
    runtime = get_runtime(request)
    session = await get_session(runtime, session_id, stage=ErrorStage.REPO_PARSE)
    event_bus = _require_event_bus(session)
    return sse_response(event_bus, request)


async def _resolve_without_remote_check(resolver: Any, input_value: str) -> Any:
    try:
        return await call_maybe_async(resolver.resolve, input_value, verify=False)
    except TypeError:
        return await call_maybe_async(resolver.resolve, input_value)


async def _create_session(store: Any, *, mode: ChatMode) -> Any:
    create = getattr(store, "create_session", None)
    if create is None:
        raise ApiModuleError(
            api_error(
                error_code=ErrorCode.INVALID_STATE,
                message="SessionStore 未提供 create_session 接口。",
                retryable=False,
                stage=ErrorStage.REPO_PARSE,
                internal_detail="session store missing create_session",
            ),
            status_code=500,
        )
    try:
        session = await call_maybe_async(create, mode=mode)
    except TypeError:
        session = await call_maybe_async(create)
        _set_if_possible(session, "mode", mode)
    if isinstance(session, str):
        getter = getattr(store, "get", None) or getattr(store, "get_session", None)
        session = await call_maybe_async(getter, session) if getter else None
    if session is None:
        raise ApiModuleError(
            api_error(
                error_code=ErrorCode.INVALID_STATE,
                message="创建会话失败。",
                retryable=True,
                stage=ErrorStage.REPO_PARSE,
                internal_detail="create_session returned None",
            ),
            status_code=500,
        )
    return session


async def _run_parse_pipeline(
    *,
    runtime: ApiRuntime,
    pipeline: Any,
    session: Any,
    payload: CreateRepositorySessionRequest,
) -> None:
    session_id = get_session_id(session)
    connected_data: RepoConnectedData | None = None

    async def status_sink(status_value: AgentStatus) -> None:
        _set_if_possible(session, "agent_status", status_value)
        await _publish(runtime, session, ("agent_status_event",), status=status_value)

    async def log_sink(log: ParseLogLine) -> None:
        _append_to_list_field(session, "parse_log", log)
        await _publish(runtime, session, ("repo_parse_log_event",), log=log)

    async def connected_sink(data: RepoConnectedData) -> None:
        nonlocal connected_data
        connected_data = data
        _set_if_possible(session, "repository", data.repository)
        _set_if_possible(session, "current_code", data.current_code)

    runner = getattr(pipeline, "run", pipeline)
    kwargs = {
        "session_id": session_id,
        "input_value": payload.input_value,
        "branch": payload.branch,
        "mode": payload.mode,
        "clone_parent": runtime.clone_parent,
        "status_sink": status_sink,
        "log_sink": log_sink,
        "connected_sink": connected_sink,
    }
    try:
        result = await _call_with_supported_kwargs(runner, **kwargs)
    except Exception as exc:
        error = getattr(exc, "error", None)
        if error is None:
            error = api_error(
                error_code=ErrorCode.REPO_SCAN_FAILED,
                message="仓库接入失败，请稍后重试。",
                retryable=True,
                stage=ErrorStage.REPO_PARSE,
                internal_detail=f"{exc.__class__.__name__}: {exc}",
            )
        await _publish(runtime, session, ("error_event",), error=error)
        return

    if result is None:
        return
    _set_if_possible(session, "repository", getattr(result, "repository", None))
    _set_if_possible(session, "repo_root", getattr(result, "repo_root", None))
    _set_if_possible(session, "repo_overview", getattr(result, "overview", None))
    _set_if_possible(session, "current_code", getattr(result, "current_code", None))
    parse_log = getattr(result, "parse_log", None)
    if parse_log is not None:
        _set_if_possible(session, "parse_log", list(parse_log))
    if connected_data is not None:
        await _publish_repo_connected(runtime, session, connected_data)
        if getattr(runtime, "auto_first_turn", True):
            await _kickoff_initial_turn(
                runtime=runtime,
                session=session,
                connected_data=connected_data,
            )


async def _call_with_supported_kwargs(func: Callable[..., Any], **kwargs: Any) -> Any:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return await call_maybe_async(func, **kwargs)

    if any(param.kind is inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()):
        accepted = kwargs
    else:
        accepted = {key: value for key, value in kwargs.items() if key in signature.parameters}
    return await call_maybe_async(func, **accepted)


async def _publish_repo_connected(
    runtime: ApiRuntime,
    session: Any,
    data: RepoConnectedData,
) -> None:
    await _publish(
        runtime,
        session,
        ("repo_connected_event",),
        repository=data.repository,
        initial_message=data.initial_message,
        current_code=data.current_code,
    )


async def _kickoff_initial_turn(
    *,
    runtime: ApiRuntime,
    session: Any,
    connected_data: RepoConnectedData,
) -> None:
    """Start the automatic first teaching turn without breaking repo connection."""

    turn_runtime = runtime.turn_runtime
    if turn_runtime is None:
        return

    initial_text = (connected_data.initial_message or "").strip()
    if not initial_text:
        initial_text = (
            "请先用 3-5 句概览这个仓库的整体架构、核心模块和入口文件，"
            "然后挑 1 个最重要的入口点带我读一下。"
        )

    request = SendTeachingMessageRequest(message=initial_text, mode=ChatMode.CHAT)
    try:
        await call_maybe_async(
            turn_runtime.start_turn,
            state=session,
            request=request,
            initiator="system",
        )
    except Exception as exc:
        error = api_error(
            error_code=ErrorCode.INVALID_STATE,
            message="自动首轮讲解未能启动，请直接发送你的第一个问题。",
            retryable=False,
            stage=ErrorStage.CHAT,
            internal_detail=f"{exc.__class__.__name__}: {exc}",
        )
        await _publish(runtime, session, ("error_event",), error=error)


async def _publish(runtime: ApiRuntime, session: Any, method_names: tuple[str, ...], **payload: Any) -> None:
    event_bus = getattr(session, "event_bus", None)
    factory = runtime.event_factory
    if event_bus is None or factory is None:
        return

    event = None
    session_id = get_session_id(session)
    for method_name in method_names:
        method = getattr(factory, method_name, None)
        if not callable(method):
            continue
        for args, kwargs in (
            ((), {"session_id": session_id, **payload}),
            ((session_id,), payload),
            ((), payload),
        ):
            try:
                event = await call_maybe_async(method, *args, **kwargs)
            except TypeError:
                continue
            break
        if event is not None:
            break
    if event is None:
        return

    publisher = getattr(event_bus, "publish", None)
    if callable(publisher):
        await maybe_await(publisher(event))


def _pending_repository(
    *,
    session_id: str,
    owner: str,
    repo: str,
    normalized_url: str,
    branch: str | None,
    default_branch: str | None,
) -> RepositorySummary:
    return RepositorySummary(
        repo_id=f"repo_{session_id.removeprefix('sess_')[:12] or uuid4().hex[:12]}",
        display_name=f"{owner}/{repo}",
        source=RepoSource.GITHUB_URL,
        github=GithubRepositoryRef(
            owner=owner,
            repo=repo,
            normalized_url=normalized_url,
            default_branch=default_branch,
            resolved_branch=branch,
            commit_sha=None,
        ),
        primary_language=None,
        file_count=0,
        status=RepositoryStatus.CONNECTING,
    )


def _status(
    *,
    session_id: str,
    phase: AgentPhase,
    label: str,
    current_target: str | None = None,
) -> AgentStatus:
    return AgentStatus(
        session_id=session_id,
        state=AgentPetState.SCANNING,
        phase=phase,
        label=label,
        pet_mood="scan",
        pet_message=label,
        current_action="接入仓库",
        current_target=current_target,
        metrics=AgentMetrics(),
        updated_at=datetime.now(UTC),
    )


def _append_to_list_field(target: Any, field_name: str, value: Any) -> None:
    current = getattr(target, field_name, None)
    if current is None:
        current = []
        _set_if_possible(target, field_name, current)
    if hasattr(current, "append"):
        current.append(value)


def _set_if_possible(target: Any, field_name: str, value: Any) -> None:
    if value is not None:
        try:
            setattr(target, field_name, value)
        except (AttributeError, TypeError):
            return


def _require_event_bus(session: Any) -> Any:
    event_bus = getattr(session, "event_bus", None)
    if event_bus is None or not callable(getattr(event_bus, "subscribe", None)):
        raise ApiModuleError(
            api_error(
                error_code=ErrorCode.INVALID_STATE,
                message="当前会话没有可订阅的事件流。",
                retryable=True,
                stage=ErrorStage.REPO_PARSE,
                internal_detail="session.event_bus missing subscribe",
            ),
            status_code=503,
            session_id=get_session_id(session),
        )
    return event_bus
