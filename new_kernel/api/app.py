"""FastAPI application factory for the new kernel API."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..contracts import (
    AgentMetrics,
    AgentPetState,
    AgentPhase,
    AgentStatus,
    ApiError,
    ChatMessage,
    ErrorCode,
    ErrorStage,
)
from .dependencies import ApiRuntime
from .errors import ApiModuleError, api_error, install_exception_handlers
from .routes import agent, chat, control, github, repositories, session, sidecar


_LOGGER = logging.getLogger(__name__)
_PROJECT_ROOT_LLM_CONFIG = "llm_config.json"


def create_app(
    *,
    runtime: ApiRuntime | None = None,
    session_store: Any | None = None,
    github_resolver: Any | None = None,
    repo_pipeline: Any | None = None,
    turn_runtime: Any | None = None,
    sidecar_explainer: Any | None = None,
    event_factory: Any | None = None,
    prompt_manager: Any | None = None,
    llm_client: Any | None = None,
    tool_runtime: Any | None = None,
    clone_parent: str | Path | None = None,
    llm_api_key: str | None = None,
    llm_model_id: str | None = None,
    llm_base_url: str | None = None,
    llm_timeout_seconds: float | None = None,
    llm_config_path: str | Path | None = None,
    cors_allow_origins: list[str] | None = None,
) -> FastAPI:
    api_runtime = runtime or _build_default_runtime(
        llm_api_key=llm_api_key,
        llm_model_id=llm_model_id,
        llm_base_url=llm_base_url,
        llm_timeout_seconds=llm_timeout_seconds,
        llm_config_path=llm_config_path,
        clone_parent=clone_parent,
    )
    _apply_runtime_overrides(
        api_runtime,
        session_store=session_store,
        github_resolver=github_resolver,
        repo_pipeline=repo_pipeline,
        turn_runtime=turn_runtime,
        sidecar_explainer=sidecar_explainer,
        event_factory=event_factory,
        prompt_manager=prompt_manager,
        llm_client=llm_client,
        tool_runtime=tool_runtime,
        clone_parent=clone_parent,
    )

    app = FastAPI(title="Repo Tutor new_kernel API", version="0.1.0")
    app.state.api_runtime = api_runtime
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allow_origins or ["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_exception_handlers(app)
    _include_routers(app)

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await _close_runtime(api_runtime)

    return app


def _include_routers(app: FastAPI) -> None:
    for router in (
        github.router,
        repositories.router,
        chat.router,
        sidecar.router,
        agent.router,
        session.router,
        control.router,
    ):
        app.include_router(router)


def _build_default_runtime(
    *,
    llm_api_key: str | None,
    llm_model_id: str | None,
    llm_base_url: str | None = None,
    llm_timeout_seconds: float | None = None,
    llm_config_path: str | Path | None = None,
    clone_parent: str | Path | None,
) -> ApiRuntime:
    """Wire concrete business objects per spec §4 composition-root rules.

    Lazy imports keep the ``api`` package import-clean for tools that scan
    module surfaces (the heavy modules below pull in tools/agents/turn/etc.).
    """

    from ..agents import (
        OrientPlanner,
        ReadingAgent,
        SidecarExplainer,
        TeacherAgent,
        TeachingLoop,
    )
    from ..events import EventBus, EventFactory
    from ..prompts.prompt_manager import PromptManager
    from ..repo import GithubResolver, RepoParsePipeline
    from ..session import SessionStore
    from ..tools import ToolRuntime, build_default_tools
    from ..turn import TurnRuntime

    prompt_manager = PromptManager()
    llm_client = _build_llm_client(
        llm_api_key=llm_api_key,
        llm_model_id=llm_model_id,
        llm_base_url=llm_base_url,
        llm_timeout_seconds=llm_timeout_seconds,
        llm_config_path=llm_config_path,
    )

    summarizer = _make_summarizer(llm_client)
    tool_runtime = ToolRuntime(build_default_tools(summarizer=summarizer))

    session_store = SessionStore(
        event_bus_factory=EventBus,
        idle_status_factory=_idle_agent_status,
    )

    sidecar_explainer = SidecarExplainer(
        llm_client=llm_client,
        prompt_manager=prompt_manager,
    )

    turn_runtime: Any | None = None
    if llm_client is not None:
        teaching_loop = TeachingLoop(
            orient=OrientPlanner(llm_client=llm_client, prompt_manager=prompt_manager),
            reader=ReadingAgent(llm_client=llm_client, prompt_manager=prompt_manager),
            teacher=TeacherAgent(llm_client=llm_client, prompt_manager=prompt_manager),
            tool_runtime=tool_runtime,
        )
        turn_runtime = TurnRuntime(
            teaching_loop=teaching_loop,
            deep_loop=_DeepResearchPlaceholder(),
            idle_status_factory=_idle_agent_status,
        )

    return ApiRuntime(
        session_store=session_store,
        github_resolver=GithubResolver(),
        repo_pipeline=RepoParsePipeline(),
        turn_runtime=turn_runtime,
        sidecar_explainer=sidecar_explainer,
        event_factory=EventFactory(),
        prompt_manager=prompt_manager,
        llm_client=llm_client,
        tool_runtime=tool_runtime,
        clone_parent=Path(clone_parent) if clone_parent is not None else None,
    )


def _idle_agent_status(session_id: str) -> AgentStatus:
    """Default idle AgentStatus shared by SessionStore and TurnRuntime."""

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
        updated_at=datetime.now(UTC),
    )


def _make_summarizer(llm_client: Any | None):
    """Wrap LLMClient as the SummarizeFile-injected callable.

    Per spec §5 tools, summarize_file must receive an explicit summarizer
    callable (not via ToolContext) and never imports llm/. Composition root
    builds the wrapper and hands it to SummarizeFile constructor.
    """

    if llm_client is None:
        return None

    async def _summarize(excerpt: str) -> str:
        return await llm_client.call_llm(
            (
                "请用 3-5 句中文摘要下面这段代码：突出文件用途、关键 symbol、"
                "出入口；不要复制代码原文。\n\n"
                f"{excerpt}"
            ),
            system_prompt="你是只读代码摘要器，输出简洁中文摘要，不超过 200 字。",
            temperature=0.2,
            max_tokens=320,
        )

    return _summarize


class _DeepResearchPlaceholder:
    """Deep research stub: surfaced via TurnRuntime when ``mode=deep``.

    The deep_research package is not implemented yet (per Phase 3 backlog).
    This placeholder satisfies TurnRuntime's mandatory ``deep_loop`` argument
    and raises a clear ApiModuleError if ever invoked, so mode=chat traffic
    stays unaffected while mode=deep returns a friendly error envelope.
    """

    async def run(self, **_kwargs: Any) -> ChatMessage:
        raise ApiModuleError(
            api_error(
                error_code=ErrorCode.INVALID_STATE,
                message="深度研究模式（mode=deep）尚未在新内核启用，请使用 chat 模式。",
                retryable=False,
                stage=ErrorStage.DEEP_RESEARCH,
                internal_detail="DeepResearchLoop is not implemented in new_kernel",
            ),
            status_code=501,
        )


def _apply_runtime_overrides(runtime: ApiRuntime, **overrides: Any) -> None:
    for name, value in overrides.items():
        if value is None:
            continue
        if name == "clone_parent":
            value = Path(value)
        setattr(runtime, name, value)


def _optional_instance(module_name: str, class_name: str, **kwargs: Any) -> Any | None:
    try:
        module = importlib.import_module(f"..{module_name}", package=__package__)
        cls = getattr(module, class_name)
    except (AttributeError, ImportError):
        return None

    try:
        return _instantiate(cls, **kwargs)
    except TypeError:
        try:
            return cls()
        except TypeError:
            return None


def _instantiate(cls: type[Any], **kwargs: Any) -> Any:
    signature = inspect.signature(cls)
    accepted = {
        name: value
        for name, value in kwargs.items()
        if value is not None and name in signature.parameters
    }
    return cls(**accepted)


def _build_llm_client(
    *,
    llm_api_key: str | None,
    llm_model_id: str | None,
    llm_base_url: str | None = None,
    llm_timeout_seconds: float | None = None,
    llm_config_path: str | Path | None = None,
) -> Any | None:
    """Resolve LLM config and build a shared async client.

    Resolution order (composition root only — ``llm/`` never reads any of this):
    1. explicit kwargs from ``create_app(...)``;
    2. project-root JSON file at ``<repo>/llm_config.json`` (overridable via
       ``llm_config_path``); fields ``api_key`` / ``model`` / ``base_url`` /
       ``timeout_seconds``.
    Missing api_key or model after both steps disables the LLM client.
    """

    file_config = _load_root_llm_config_json(llm_config_path)
    api_key = llm_api_key or _config_text(file_config, "api_key")
    model_id = llm_model_id or _config_text(file_config, "model", "model_id")
    base_url = llm_base_url or _config_text(file_config, "base_url")
    timeout_seconds = (
        llm_timeout_seconds
        if llm_timeout_seconds is not None
        else _config_number(file_config, "timeout_seconds")
    )

    if not api_key or not model_id:
        return None

    try:
        module = importlib.import_module("..llm.client", package=__package__)
        make_client = getattr(module, "make_client")
    except (AttributeError, ImportError):
        return None

    factory_kwargs: dict[str, Any] = {}
    if base_url:
        factory_kwargs["base_url"] = base_url
    if timeout_seconds is not None and timeout_seconds > 0:
        factory_kwargs["timeout_seconds"] = float(timeout_seconds)

    return make_client(api_key, model_id, **factory_kwargs)


def _load_root_llm_config_json(
    explicit_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Read project-root ``llm_config.json`` if available; return None on miss.

    Only the composition root may read filesystem config. ``llm/`` itself
    must continue to receive everything via explicit kwargs.
    """

    candidate = (
        Path(explicit_path).expanduser()
        if explicit_path is not None
        else _default_llm_config_path()
    )
    if candidate is None or not candidate.is_file():
        return None
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        _LOGGER.warning("failed to read llm config %s: %s", candidate, exc)
        return None
    if not isinstance(payload, dict):
        _LOGGER.warning("llm config %s does not contain a JSON object", candidate)
        return None
    return payload


def _default_llm_config_path() -> Path | None:
    """Return ``<project_root>/llm_config.json`` based on this file's location."""

    # api/app.py -> api/ -> new_kernel/ -> <project_root>
    project_root = Path(__file__).resolve().parents[2]
    return project_root / _PROJECT_ROOT_LLM_CONFIG


def _config_text(config: dict[str, Any] | None, *keys: str) -> str | None:
    if not config:
        return None
    for key in keys:
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _config_number(config: dict[str, Any] | None, key: str) -> float | None:
    if not config:
        return None
    value = config.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


async def _close_runtime(runtime: ApiRuntime) -> None:
    for task in list(runtime.background_tasks):
        if isinstance(task, asyncio.Task) and not task.done():
            task.cancel()
    if runtime.background_tasks:
        await asyncio.gather(*runtime.background_tasks, return_exceptions=True)

    closer = getattr(runtime.llm_client, "close", None)
    if callable(closer):
        result = closer()
        if inspect.isawaitable(result):
            await result


app = create_app()


__all__ = ["app", "create_app"]
