from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from openai import APITimeoutError, AuthenticationError, RateLimitError

from new_kernel.agents.teacher import TeacherOutput
from new_kernel.agents.teaching_loop import TeachingLoop
from new_kernel.api.dependencies import ApiRuntime
from new_kernel.api.routes.repositories import _kickoff_initial_turn
from new_kernel.contracts import (
    AgentMetrics,
    AgentPetState,
    AgentPhase,
    AgentStatus,
    ChatMessage,
    ChatMode,
    RepoConnectedData,
    RepositoryStatus,
    RepositorySummary,
    RepoSource,
    GithubRepositoryRef,
    SendTeachingMessageRequest,
)
from new_kernel.events.event_factory import EventFactory
from new_kernel.llm.client import LLMAuthenticationError, LLMClient, LLMRateLimitError
from new_kernel.memory.scratchpad import Anchor, ReadingStep, Scratchpad, _fit_text
from new_kernel.tools.tool_protocol import ToolContext, ToolResult
from new_kernel.turn.turn_runtime import TurnRuntime


def test_llm_client_retries_timeout_once_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("POST", "https://example.test/chat")
    calls = 0

    async def fake_sleep(delay: float) -> None:
        assert delay == 0.5

    class FakeCompletions:
        async def create(self, **_kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise APITimeoutError(request)
            return _completion_response("ok")

    monkeypatch.setattr("new_kernel.llm.client.asyncio.sleep", fake_sleep)
    client = LLMClient(api_key=None, model_id="demo", client=_fake_chat_client(FakeCompletions()))

    result = asyncio.run(client.call_llm("hello"))

    assert result == "ok"
    assert calls == 2


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (
            AuthenticationError(
                "bad key",
                response=httpx.Response(
                    401,
                    request=httpx.Request("POST", "https://example.test/chat"),
                ),
                body=None,
            ),
            LLMAuthenticationError,
        ),
        (
            RateLimitError(
                "too many",
                response=httpx.Response(
                    429,
                    request=httpx.Request("POST", "https://example.test/chat"),
                ),
                body=None,
            ),
            LLMRateLimitError,
        ),
    ],
)
def test_llm_client_does_not_retry_auth_or_rate_limit(exc: Exception, expected: type[Exception]) -> None:
    calls = 0

    class FakeCompletions:
        async def create(self, **_kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            raise exc

    client = LLMClient(api_key=None, model_id="demo", client=_fake_chat_client(FakeCompletions()))

    with pytest.raises(expected):
        asyncio.run(client.call_llm("hello"))

    assert calls == 1


def test_teaching_loop_reads_steps_in_parallel() -> None:
    loop = TeachingLoop(
        orient=_OrientStub(
            (
                ReadingStep("s1", "read first", anchors=(Anchor("a.py"),)),
                ReadingStep("s2", "read second", anchors=(Anchor("b.py"),)),
            )
        ),
        reader=_SlowDoneReader(),
        teacher=_TeacherStub(),
        tool_runtime=_ToolRuntimeStub(),
    )
    scratchpad = Scratchpad()
    status = _StatusTracker("sess_test")
    sink = _Sink()
    start = time.perf_counter()

    message = asyncio.run(
        loop.run(
            session_id="sess_test",
            turn_id="turn_test",
            user_message="teach me",
            scratchpad=scratchpad,
            repo_overview="repo_overview",
            repo_root=Path.cwd(),
            sink=sink,
            status_tracker=status,
            cancellation_token=_CancellationToken(),
        )
    )

    assert time.perf_counter() - start < 1.5
    assert message.role == "assistant"
    assert status.metrics.llm_call_count == 4


def test_fit_text_keeps_head_middle_and_tail() -> None:
    text = "".join(f"[chunk-{index:02d}]" + ("x" * 1000) for index in range(30))

    fitted = _fit_text(text, max_tokens=2000)

    assert len(fitted) <= 8000
    assert "[chunk-00]" in fitted
    assert "[chunk-29]" in fitted
    assert "[chunk-14]" in fitted or "[chunk-15]" in fitted


def test_turn_runtime_records_system_initiator_message() -> None:
    state = _TurnState()
    runtime = TurnRuntime(
        teaching_loop=_TurnLoopStub(),
        deep_loop=_TurnLoopStub(),
        task_factory=asyncio.create_task,
    )

    async def run() -> None:
        data = await runtime.start_turn(
            state=state,
            request=SendTeachingMessageRequest(message="initial guide", mode=ChatMode.CHAT),
            initiator="system",
        )
        task = runtime.active_task(state.session_id)
        assert task is not None
        await task
        assert data.user_message_id.startswith("msg_system_")

    asyncio.run(run())

    assert state.messages[0].role == "system"
    assert state.messages[0].message_id.startswith("msg_system_")
    assert state.messages[1].role == "assistant"


def test_auto_first_turn_uses_system_initiator() -> None:
    turn_runtime = _RecordingTurnRuntime()
    runtime = ApiRuntime(
        turn_runtime=turn_runtime,
        event_factory=EventFactory(),
    )
    session = _TurnState()
    connected = _repo_connected()

    asyncio.run(
        _kickoff_initial_turn(
            runtime=runtime,
            session=session,
            connected_data=connected,
        )
    )

    assert turn_runtime.calls == [("system", connected.initial_message)]


def test_auto_first_turn_failure_emits_error_event() -> None:
    runtime = ApiRuntime(
        turn_runtime=_FailingTurnRuntime(),
        event_factory=EventFactory(),
    )
    session = _TurnState()

    asyncio.run(
        _kickoff_initial_turn(
            runtime=runtime,
            session=session,
            connected_data=_repo_connected(),
        )
    )

    assert session.event_bus.events
    assert session.event_bus.events[-1].event_type == "error"


def _fake_chat_client(completions: Any) -> Any:
    return type("Client", (), {"chat": type("Chat", (), {"completions": completions})()})()


def _completion_response(text: str) -> Any:
    message = type("Message", (), {"content": text})()
    choice = type("Choice", (), {"message": message, "finish_reason": "stop"})()
    return type("Response", (), {"choices": [choice], "model": "demo", "usage": None})()


class _OrientStub:
    def __init__(self, steps: tuple[ReadingStep, ...]) -> None:
        self._steps = steps

    async def process(self, **_kwargs: Any) -> Any:
        return type("Plan", (), {"steps": self._steps})()


class _SlowDoneReader:
    async def process(self, **_kwargs: Any) -> Any:
        await asyncio.sleep(1)
        return type(
            "Decision",
            (),
            {"thought": "done", "action": "done", "action_input": {}, "self_note": "done"},
        )()


class _TeacherStub:
    async def process(self, *, on_chunk: Any, **_kwargs: Any) -> TeacherOutput:
        await on_chunk("visible answer")
        return TeacherOutput(full_text="visible answer\n下一个教学点：继续读入口。")


class _ToolRuntimeStub:
    valid_actions = frozenset({"done", "read_file_range"})

    def build_planner_description(self) -> str:
        return "read_file_range"

    def build_reader_description(self) -> str:
        return "read_file_range"

    async def execute(self, _action: str, _input: dict[str, Any], *, ctx: ToolContext) -> ToolResult:
        return ToolResult(content="", metadata={}, success=True)


class _CancellationToken:
    def raise_if_cancelled(self) -> None:
        return None


class _Sink:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)

    async def publish(self, event: Any) -> None:
        self.events.append(event)


class _StatusTracker:
    def __init__(self, session_id: str) -> None:
        self.current = _status(session_id)

    @property
    def metrics(self) -> AgentMetrics:
        return self.current.metrics

    async def update_phase(self, **kwargs: Any) -> AgentStatus:
        self.current = AgentStatus(
            session_id=self.current.session_id,
            metrics=self.current.metrics,
            updated_at=datetime.now(UTC),
            **kwargs,
        )
        return self.current

    async def add_metrics(
        self,
        *,
        llm_call: int = 0,
        tool_call: int = 0,
        tokens: int = 0,
        elapsed_ms: int = 0,
        emit: bool = False,
    ) -> AgentStatus:
        del emit
        self.current = self.current.model_copy(
            update={
                "metrics": AgentMetrics(
                    llm_call_count=self.current.metrics.llm_call_count + llm_call,
                    tool_call_count=self.current.metrics.tool_call_count + tool_call,
                    token_count=self.current.metrics.token_count + tokens,
                    elapsed_ms=self.current.metrics.elapsed_ms + elapsed_ms,
                )
            }
        )
        return self.current


@dataclass
class _TurnState:
    session_id: str = "sess_test"
    event_bus: _Sink = field(default_factory=_Sink)
    agent_status: AgentStatus = field(default_factory=lambda: _status("sess_test"))
    mode: ChatMode = ChatMode.CHAT
    repository: RepositorySummary = field(default_factory=lambda: _repository("ready"))
    repo_root: Path = field(default_factory=lambda: Path.cwd())
    messages: list[ChatMessage] = field(default_factory=list)
    scratchpad: Scratchpad = field(default_factory=Scratchpad)
    current_code: Any | None = None
    active_turn_id: str | None = None


class _TurnLoopStub:
    async def run(self, **kwargs: Any) -> ChatMessage:
        return ChatMessage(
            message_id="msg_assistant_test",
            role="assistant",
            mode=kwargs["request"].mode if "request" in kwargs else ChatMode.CHAT,
            content="assistant answer",
            created_at=datetime.now(UTC),
            streaming_complete=True,
        )


class _RecordingTurnRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def start_turn(
        self,
        *,
        state: Any,
        request: SendTeachingMessageRequest,
        initiator: str,
    ) -> None:
        del state
        self.calls.append((initiator, request.message))


class _FailingTurnRuntime:
    async def start_turn(self, **_kwargs: Any) -> None:
        raise RuntimeError("already active")


def _repo_connected() -> RepoConnectedData:
    return RepoConnectedData(
        repository=_repository("ready"),
        initial_message="仓库已连接。请从入口开始讲解。",
        current_code=None,
    )


def _repository(status: str) -> RepositorySummary:
    return RepositorySummary(
        repo_id="repo_test",
        display_name="acme/demo",
        source=RepoSource.GITHUB_URL,
        github=GithubRepositoryRef(
            owner="acme",
            repo="demo",
            normalized_url="https://github.com/acme/demo",
            default_branch="main",
            resolved_branch="main",
            commit_sha="abc123",
        ),
        primary_language="Python",
        file_count=1,
        status=RepositoryStatus(status),
    )


def _status(session_id: str) -> AgentStatus:
    return AgentStatus(
        session_id=session_id,
        state=AgentPetState.IDLE,
        phase=AgentPhase.IDLE,
        label="idle",
        pet_mood="idle",
        pet_message="idle",
        metrics=AgentMetrics(),
        updated_at=datetime.now(UTC),
    )
