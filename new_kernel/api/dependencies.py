"""Runtime dependency container and small route helpers.

The API layer is a composition root. It stores already-built facades here and
passes requests to them without constructing business objects inside routes.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from fastapi import Request

from ..contracts import ErrorCode, ErrorStage
from .errors import ApiModuleError, api_error


T = TypeVar("T")


@dataclass(slots=True)
class ApiRuntime:
    session_store: Any | None = None
    github_resolver: Any | None = None
    repo_pipeline: Any | None = None
    turn_runtime: Any | None = None
    sidecar_explainer: Any | None = None
    event_factory: Any | None = None
    prompt_manager: Any | None = None
    llm_client: Any | None = None
    tool_runtime: Any | None = None
    clone_parent: Path | None = None
    auto_first_turn: bool = True
    background_tasks: set[Any] = field(default_factory=set)


def get_runtime(request: Request) -> ApiRuntime:
    runtime = getattr(request.app.state, "api_runtime", None)
    if not isinstance(runtime, ApiRuntime):
        raise ApiModuleError(
            api_error(
                error_code=ErrorCode.INVALID_STATE,
                message="API 运行时尚未初始化。",
                retryable=False,
                stage=ErrorStage.IDLE,
                internal_detail="app.state.api_runtime is missing",
            ),
            status_code=500,
        )
    return runtime


def require_dependency(runtime: ApiRuntime, name: str, *, stage: ErrorStage) -> Any:
    dependency = getattr(runtime, name)
    if dependency is None:
        raise ApiModuleError(
            api_error(
                error_code=ErrorCode.INVALID_STATE,
                message="当前后端能力尚未装配完成，请稍后重试。",
                retryable=True,
                stage=stage,
                internal_detail=f"missing api runtime dependency: {name}",
            ),
            status_code=503,
        )
    return dependency


async def maybe_await(value: T | Awaitable[T]) -> T:
    if inspect.isawaitable(value):
        return await value
    return value


async def call_maybe_async(func: Callable[..., T | Awaitable[T]], *args: Any, **kwargs: Any) -> T:
    return await maybe_await(func(*args, **kwargs))


def get_session_id_header(request: Request) -> str:
    session_id = request.headers.get("X-Session-Id")
    if not session_id:
        raise ApiModuleError(
            api_error(
                error_code=ErrorCode.INVALID_REQUEST,
                message="缺少 X-Session-Id 请求头。",
                retryable=False,
                stage=ErrorStage.CHAT,
            ),
            status_code=400,
        )
    return session_id


async def get_session(runtime: ApiRuntime, session_id: str, *, stage: ErrorStage) -> Any:
    store = require_dependency(runtime, "session_store", stage=stage)
    getter = getattr(store, "get", None) or getattr(store, "get_session", None)
    if getter is None:
        raise ApiModuleError(
            api_error(
                error_code=ErrorCode.INVALID_STATE,
                message="SessionStore 未提供 get 接口。",
                retryable=False,
                stage=stage,
                internal_detail="session store missing get/get_session",
            ),
            status_code=500,
            session_id=session_id,
        )
    try:
        session = await call_maybe_async(getter, session_id)
    except KeyError:
        session = None
    if session is None:
        raise ApiModuleError(
            api_error(
                error_code=ErrorCode.SESSION_NOT_FOUND,
                message="找不到这个会话，请重新连接仓库。",
                retryable=False,
                stage=stage,
            ),
            status_code=404,
            session_id=session_id,
        )
    return session


def get_session_id(session: Any) -> str:
    session_id = getattr(session, "session_id", None)
    if not isinstance(session_id, str) or not session_id:
        raise ApiModuleError(
            api_error(
                error_code=ErrorCode.INVALID_STATE,
                message="会话状态缺少 session_id。",
                retryable=False,
                stage=ErrorStage.IDLE,
                internal_detail="session.session_id is missing",
            ),
            status_code=500,
        )
    return session_id


__all__ = [
    "ApiRuntime",
    "call_maybe_async",
    "get_runtime",
    "get_session",
    "get_session_id",
    "get_session_id_header",
    "maybe_await",
    "require_dependency",
]
