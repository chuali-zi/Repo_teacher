"""FIX-01 integration: SessionStore -> TurnRuntime.start_turn(mode=DEEP) -> DeepResearchLoop -> ChatMessage.

This test was missing in SA-07 / SA-08. The production path used the kernel
default ``memory.Scratchpad`` factory wired into ``SessionState.scratchpad``,
which has none of the methods ``DeepResearchLoop`` calls (``set_subtopics``,
``add_note``, ``build_compose_context``, etc). The fix splits
``SessionState`` into ``teaching_scratchpad`` (kept as the legacy default) and
``research_scratchpad`` (lazy-created by ``TurnRuntime`` when ``mode=DEEP``).
This test pins that wiring end-to-end through the real ``SessionStore`` +
``TurnRuntime`` + ``DeepResearchLoop``, with stubbed LLM and tool runtime.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from new_kernel.contracts import (
    AgentPetState,
    AgentPhase,
    AgentStatus,
    AgentMetrics,
    ChatMessage,
    ChatMode,
    GithubRepositoryRef,
    ReportKind,
    RepoSource,
    RepositoryStatus,
    RepositorySummary,
    SendTeachingMessageRequest,
)
from new_kernel.deep_research.agents.composer import Composer
from new_kernel.deep_research.agents.decomposer import Decomposer
from new_kernel.deep_research.agents.investigator import Investigator
from new_kernel.deep_research.agents.note_taker import NoteTaker
from new_kernel.deep_research.deep_research_loop import DeepResearchLoop
from new_kernel.deep_research.prompts import PROMPTS_ROOT
from new_kernel.deep_research.research_scratchpad import ResearchScratchpad
from new_kernel.events.event_bus import EventBus
from new_kernel.memory.scratchpad import Scratchpad
from new_kernel.prompts.prompt_manager import PromptManager
from new_kernel.session.session_store import SessionStore
from new_kernel.tools.tool_protocol import ToolResult
from new_kernel.turn.turn_runtime import TurnRuntime


# --------------------------------------------------------------------------- #
# Stubs
# --------------------------------------------------------------------------- #


@dataclass
class _FakeLLMResponse:
    content: str


class _StubLLMClient:
    """Routes ``call_llm`` / ``stream_llm`` by inspecting the rendered prompt.

    Mirrors the pattern in ``test_deep_research_loop._StubLLMClient`` so the
    decomposer / investigator / note_taker / composer all get the right canned
    payload from a single client.
    """

    def __init__(
        self,
        *,
        decompose_response: str,
        investigate_response: str,
        note_response: str,
        compose_chunks: list[str],
    ) -> None:
        self._decompose_response = decompose_response
        self._investigate_response = investigate_response
        self._note_response = note_response
        self._compose_chunks = list(compose_chunks)
        self.call_log: list[dict[str, Any]] = []
        self.stream_log: list[dict[str, Any]] = []

    async def call_llm(
        self,
        user_prompt: str,
        *,
        system_prompt: str | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **request_kwargs: Any,
    ) -> _FakeLLMResponse:
        kind = _identify_agent(system_prompt, user_prompt)
        self.call_log.append({"kind": kind, "user_prompt": user_prompt})
        if kind == "decompose":
            payload = self._decompose_response
        elif kind == "investigate":
            payload = self._investigate_response
        elif kind == "note":
            payload = self._note_response
        else:  # pragma: no cover - defensive
            payload = ""
        return _FakeLLMResponse(content=payload)

    def stream_llm(
        self,
        user_prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **request_kwargs: Any,
    ) -> AsyncIterator[str]:
        self.stream_log.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        return self._compose_iter()

    async def _compose_iter(self) -> AsyncIterator[str]:
        for chunk in self._compose_chunks:
            yield chunk


def _identify_agent(system_prompt: str | None, user_prompt: str) -> str:
    """Pick a canned response by which YAML the prompt manager loaded."""

    text = (system_prompt or "") + "\n" + (user_prompt or "")
    if "Decomposer" in text or "decompose" in text or "subtopics" in text.lower() or "支柱" in text:
        return "decompose"
    if "Investigator" in text or "want_more" in text or "action_input" in text:
        return "investigate"
    if "NoteTaker" in text or "note" in text.lower() or "笔记" in text:
        return "note"
    return "compose"


class _StubToolRuntime:
    """Tiny ``ToolRuntime`` clone used by ``DeepResearchLoop``."""

    def __init__(self) -> None:
        self.execute_calls: list[dict[str, Any]] = []
        self._actions = frozenset(("read_file_range", "done"))

    @property
    def valid_actions(self) -> frozenset[str]:
        return self._actions

    async def execute(self, action: str, action_input: dict, *, ctx: Any) -> ToolResult:
        self.execute_calls.append({"action": action, "action_input": action_input})
        if action == "read_file_range":
            return ToolResult.ok("# README\nfake body\n", metadata={})
        return ToolResult.fail("unknown action", error_code="invalid_action")

    def build_reader_description(self) -> str:
        return (
            "| Action | Input | When to use |\n"
            "| --- | --- | --- |\n"
            "| read_file_range | path | read README |"
        )


class _ExplodingTeachingLoop:
    """Fail-fast teaching loop; deep-mode tests must never invoke it."""

    async def run(self, **_kwargs: Any) -> ChatMessage:
        raise AssertionError("teaching loop must not run during a deep-mode turn")


class _NoOpTeachingLoop:
    """Returns a fixed assistant message; used by the chat-mode test."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run(self, **kwargs: Any) -> ChatMessage:
        self.calls.append(kwargs)
        return ChatMessage(
            message_id="msg_assistant_chat_test",
            role="assistant",
            mode=ChatMode.CHAT,
            content="hello from teaching loop",
            created_at=datetime.now(UTC),
            streaming_complete=True,
        )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _idle_status(session_id: str) -> AgentStatus:
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


def _ready_repository() -> RepositorySummary:
    return RepositorySummary(
        repo_id="r1",
        display_name="acme/demo",
        source=RepoSource.GITHUB_URL,
        github=GithubRepositoryRef(
            owner="acme",
            repo="demo",
            normalized_url="https://github.com/acme/demo",
        ),
        primary_language="Python",
        file_count=10,
        status=RepositoryStatus.READY,
    )


def _five_pillar_decompose_payload() -> str:
    return json.dumps(
        {
            "subtopics": [
                {"id": "what", "title": "做了什么", "anchors": []},
                {"id": "stack", "title": "技术栈", "anchors": []},
                {"id": "why", "title": "选型", "anchors": []},
                {"id": "arch", "title": "整体架构", "anchors": []},
                {"id": "flow", "title": "主流程", "anchors": []},
            ]
        }
    )


def _done_investigate_payload() -> str:
    return json.dumps(
        {
            "action": "done",
            "action_input": {},
            "intent": "够了",
            "want_more": False,
        }
    )


def _standard_compose_chunks() -> list[str]:
    return ["前言", "正文", "\n\n<<SUGGESTIONS>>\n", "- 接下来读 README\n"]


def _build_deep_loop() -> tuple[DeepResearchLoop, _StubLLMClient, _StubToolRuntime]:
    llm_client = _StubLLMClient(
        decompose_response=_five_pillar_decompose_payload(),
        investigate_response=_done_investigate_payload(),
        note_response="not used",
        compose_chunks=_standard_compose_chunks(),
    )
    pm = PromptManager(prompts_root=PROMPTS_ROOT)
    tool_runtime = _StubToolRuntime()
    loop = DeepResearchLoop(
        decomposer=Decomposer(llm_client=llm_client, prompt_manager=pm),
        investigator=Investigator(llm_client=llm_client, prompt_manager=pm),
        note_taker=NoteTaker(llm_client=llm_client, prompt_manager=pm),
        composer=Composer(llm_client=llm_client, prompt_manager=pm),
        tool_runtime=tool_runtime,
    )
    return loop, llm_client, tool_runtime


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_session_store_creates_state_with_teaching_and_research_scratchpads() -> None:
    """The default session has a teaching scratchpad and no research scratchpad yet."""

    store = SessionStore(
        event_bus_factory=EventBus,
        idle_status_factory=_idle_status,
    )
    state = store.create(session_id="sess_split_default")

    # teaching slot is the kernel default Scratchpad.
    assert isinstance(state.teaching_scratchpad, Scratchpad)
    # research slot is lazy — only created on first deep-mode turn.
    assert state.research_scratchpad is None
    # legacy alias still works and points at the same teaching object.
    assert state.scratchpad is state.teaching_scratchpad


def test_turn_runtime_start_turn_deep_lazy_inits_research_scratchpad_and_completes() -> None:
    """End-to-end: deep-mode turn must lazy-init ``research_scratchpad`` and finish cleanly.

    Failure mode this test guards against: production previously sent the
    legacy ``memory.Scratchpad`` to ``DeepResearchLoop`` which then crashed on
    ``scratchpad.set_subtopics(...)`` after the first decomposer LLM round.
    """

    deep_loop, llm_client, tool_runtime = _build_deep_loop()

    store = SessionStore(
        event_bus_factory=EventBus,
        idle_status_factory=_idle_status,
    )
    teaching_loop = _ExplodingTeachingLoop()
    turn_runtime = TurnRuntime(
        teaching_loop=teaching_loop,
        deep_loop=deep_loop,
        idle_status_factory=_idle_status,
    )

    state = store.create(session_id="sess_split_deep")
    state.repository = _ready_repository()
    state.repo_root = Path(".")
    state.current_code = None

    async def _runner() -> None:
        await turn_runtime.start_turn(
            state=state,
            request=SendTeachingMessageRequest(
                message="请基于刚刚接入的仓库生成一份面向新手的入门导读。",
                mode=ChatMode.DEEP,
                report_kind=ReportKind.REPO_ONBOARDING,
            ),
            initiator="system",
        )
        task = turn_runtime.active_task(state.session_id)
        assert task is not None, "TurnRuntime must register an active task"
        await asyncio.wait_for(task, timeout=5.0)

    asyncio.run(_runner())

    # The research scratchpad must have been created and populated by the loop.
    assert state.research_scratchpad is not None
    assert isinstance(state.research_scratchpad, ResearchScratchpad)
    assert len(state.research_scratchpad.subtopics) == 5

    # Teaching scratchpad: the SAME object (FIX-01 split is preserved), but
    # since FIX-06 it now carries bridged onboarding evidence — the legacy
    # "must NOT have been touched" claim no longer applies. The detailed
    # bridge contract is exercised in
    # ``test_after_deep_turn_teaching_scratchpad_has_covered_points`` below.
    assert isinstance(state.teaching_scratchpad, Scratchpad)
    assert state.scratchpad is state.teaching_scratchpad

    # Final assistant message lands in state.messages with the right metadata.
    assert state.messages, "expected at least one assistant message"
    assistant = state.messages[-1]
    assert assistant.role == "assistant"
    assert ChatMode(assistant.mode) == ChatMode.DEEP
    assert ReportKind(assistant.kind) == ReportKind.REPO_ONBOARDING
    assert assistant.streaming_complete is True

    # active_turn_id cleared by TurnRuntime.finally.
    assert state.active_turn_id is None

    # Decomposer / composer were invoked at least once.
    assert any(call["kind"] == "decompose" for call in llm_client.call_log)
    assert llm_client.stream_log, "Composer.stream_llm must have been called"
    # Investigator returned 'done' immediately, but the arch pre-seed still
    # invokes ``list_dir`` once (RECON-D Option B). The stub runtime only knows
    # ``read_file_range``, so the seed call returns a failure ToolResult and no
    # prefab note lands in the scratchpad.
    assert [call["action"] for call in tool_runtime.execute_calls] == ["list_dir"]


def test_turn_runtime_start_turn_chat_uses_teaching_scratchpad() -> None:
    """Chat-mode turn must use ``teaching_scratchpad`` and never create a research one."""

    deep_loop = _ExplodingTeachingLoop()  # deep loop must not run in chat mode
    teaching_loop = _NoOpTeachingLoop()
    store = SessionStore(
        event_bus_factory=EventBus,
        idle_status_factory=_idle_status,
    )
    turn_runtime = TurnRuntime(
        teaching_loop=teaching_loop,
        deep_loop=deep_loop,  # type: ignore[arg-type]  # deliberately exploding stub
        idle_status_factory=_idle_status,
    )

    state = store.create(session_id="sess_split_chat")
    state.repository = _ready_repository()
    state.repo_root = Path(".")
    state.current_code = None
    teaching_pad_before = state.teaching_scratchpad

    async def _runner() -> None:
        await turn_runtime.start_turn(
            state=state,
            request=SendTeachingMessageRequest(
                message="hello",
                mode=ChatMode.CHAT,
                report_kind=ReportKind.ANSWER,
            ),
            initiator="user",
        )
        task = turn_runtime.active_task(state.session_id)
        assert task is not None
        await asyncio.wait_for(task, timeout=5.0)

    asyncio.run(_runner())

    # Teaching loop received the teaching scratchpad (the same object).
    assert teaching_loop.calls, "teaching loop must run in chat mode"
    assert teaching_loop.calls[-1]["scratchpad"] is teaching_pad_before

    # Research scratchpad must remain untouched.
    assert state.research_scratchpad is None

    # Teaching scratchpad reference is stable; the alias still resolves.
    assert state.teaching_scratchpad is teaching_pad_before
    assert state.scratchpad is teaching_pad_before

    # Assistant message arrived from the no-op teaching loop.
    assert state.messages
    assistant = state.messages[-1]
    assert assistant.role == "assistant"
    assert ChatMode(assistant.mode) == ChatMode.CHAT
    assert state.active_turn_id is None


def test_after_deep_turn_teaching_scratchpad_has_covered_points() -> None:
    """FIX-06: the bridge must promote onboarding evidence into the teaching pad.

    AGENTS.md §5 promises: "onboarding 完成后保留全部 sub-topic 笔记 +
    covered_points, 供后续 TeachingLoop 引用". With the standard 5-pillar
    branch, exactly 5 covered_points must land — one per sub-topic — each
    tagged with the ``[onboarding]`` prefix so the next chat turn's
    OrientPlanner can recognise them as onboarding-derived (vs. accumulated
    by the chat itself in later turns).
    """

    deep_loop, _llm_client, _tool_runtime = _build_deep_loop()

    store = SessionStore(
        event_bus_factory=EventBus,
        idle_status_factory=_idle_status,
    )
    teaching_loop = _ExplodingTeachingLoop()
    turn_runtime = TurnRuntime(
        teaching_loop=teaching_loop,
        deep_loop=deep_loop,
        idle_status_factory=_idle_status,
    )

    state = store.create(session_id="sess_bridge_after_deep")
    state.repository = _ready_repository()
    state.repo_root = Path(".")
    state.current_code = None

    async def _runner() -> None:
        await turn_runtime.start_turn(
            state=state,
            request=SendTeachingMessageRequest(
                message="请生成入门导读。",
                mode=ChatMode.DEEP,
                report_kind=ReportKind.REPO_ONBOARDING,
            ),
            initiator="system",
        )
        task = turn_runtime.active_task(state.session_id)
        assert task is not None
        await asyncio.wait_for(task, timeout=5.0)

    asyncio.run(_runner())

    # Research pad still holds the 5 pillars from the standard branch.
    assert state.research_scratchpad is not None
    assert len(state.research_scratchpad.subtopics) == 5

    # Bridge populated the teaching pad: 5 covered_points, one per sub-topic.
    teaching = state.teaching_scratchpad
    assert isinstance(teaching, Scratchpad)
    assert teaching.covered_points, "bridge must promote covered_points"
    assert len(teaching.covered_points) == 5, (
        f"expected 5 onboarding points (one per pillar), got {len(teaching.covered_points)}: "
        f"{list(teaching.covered_points)}"
    )
    for summary in teaching.covered_points.values():
        assert summary.startswith("[onboarding]"), (
            f"covered_point summary must be tagged: {summary!r}"
        )

    # Synthetic ReadEntry per pillar so TeacherAgent's evidence context can
    # reference the onboarding step ids next turn.
    onboarding_step_ids = {
        entry.step_id
        for entry in teaching.read_entries
        if entry.step_id.startswith("onboarding/")
    }
    assert onboarding_step_ids == {
        "onboarding/what",
        "onboarding/stack",
        "onboarding/why",
        "onboarding/arch",
        "onboarding/flow",
    }


def test_bridge_is_idempotent_across_two_deep_turns() -> None:
    """A second successful deep turn must NOT double the bridged covered_points.

    The bridge keys covered_points by ``onboarding:<sub.id>`` and read_entries
    by ``onboarding/<sub.id>``; running it twice over the same research
    scratchpad must idempotently overwrite, not append. Both deep turns share
    a single asyncio.run/event-loop so TurnRuntime's per-session ``asyncio.Lock``
    in ``_locks`` stays valid for the second start_turn call.
    """

    deep_loop, _llm_client, _tool_runtime = _build_deep_loop()

    store = SessionStore(
        event_bus_factory=EventBus,
        idle_status_factory=_idle_status,
    )
    teaching_loop = _ExplodingTeachingLoop()
    turn_runtime = TurnRuntime(
        teaching_loop=teaching_loop,
        deep_loop=deep_loop,
        idle_status_factory=_idle_status,
    )

    state = store.create(session_id="sess_bridge_idempotent")
    state.repository = _ready_repository()
    state.repo_root = Path(".")
    state.current_code = None

    captured: dict[str, Any] = {}

    async def _run_one_deep_turn() -> None:
        await turn_runtime.start_turn(
            state=state,
            request=SendTeachingMessageRequest(
                message="请生成入门导读。",
                mode=ChatMode.DEEP,
                report_kind=ReportKind.REPO_ONBOARDING,
            ),
            initiator="system",
        )
        task = turn_runtime.active_task(state.session_id)
        assert task is not None
        await asyncio.wait_for(task, timeout=5.0)

    async def _runner() -> None:
        # Turn 1.
        await _run_one_deep_turn()
        teaching = state.teaching_scratchpad
        captured["first_count"] = len(teaching.covered_points)
        captured["first_keys"] = set(teaching.covered_points.keys())
        captured["first_step_ids"] = {
            entry.step_id
            for entry in teaching.read_entries
            if entry.step_id.startswith("onboarding/")
        }
        # Turn 2 in the SAME event loop so per-session asyncio.Lock stays valid.
        await _run_one_deep_turn()

    asyncio.run(_runner())

    teaching = state.teaching_scratchpad
    second_count = len(teaching.covered_points)
    second_keys = set(teaching.covered_points.keys())
    second_step_ids = {
        entry.step_id
        for entry in teaching.read_entries
        if entry.step_id.startswith("onboarding/")
    }
    assert captured["first_count"] == 5
    assert second_count == captured["first_count"], (
        f"bridge must be idempotent: 1st={captured['first_count']} 2nd={second_count}"
    )
    assert second_keys == captured["first_keys"]
    assert second_step_ids == captured["first_step_ids"]
    # Synthetic onboarding entries must not pile up.
    assert len(second_step_ids) == 5
