"""SA-07 DeepResearchLoop integration tests — AGENTS.md §3 / §5 / §9.

Exercises the four-phase orchestrator with stub LLM, tools, sink, and status
tracker. Asserts the SSE event sequence (triage -> decompose -> per-subtopic
investigate -> answer_stream_*), the terminal ``ChatMessage`` shape (DEEP /
REPO_ONBOARDING / streaming_complete / suggestions parsed from
``<<SUGGESTIONS>>``), the cancellation propagation via ``CancelledError``, and
the short-branch path for tiny repos.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from new_kernel.contracts import (
    AgentMetrics,
    AgentPetState,
    AgentPhase,
    AgentStatus,
    AnswerStreamDeltaEvent,
    AnswerStreamEndEvent,
    AnswerStreamStartEvent,
    ChatMessage,
    ChatMode,
    DeepResearchProgressEvent,
    ReportKind,
)
from new_kernel.deep_research import DeepResearchLoop, ResearchScratchpad
from new_kernel.deep_research.agents.composer import Composer
from new_kernel.deep_research.agents.decomposer import Decomposer
from new_kernel.deep_research.agents.investigator import Investigator
from new_kernel.deep_research.agents.note_taker import NoteTaker
from new_kernel.deep_research.prompts import PROMPTS_ROOT
from new_kernel.prompts.prompt_manager import PromptManager
from new_kernel.tools.tool_protocol import ToolResult
from new_kernel.turn.cancellation import CancellationToken, CancelledError


_STANDARD_OVERVIEW = (
    "repo_overview:\n"
    "- display_name: demo\n"
    "- primary_language: Python\n"
    "- file_count: 42\n"
)
_SHORT_OVERVIEW = (
    "repo_overview:\n"
    "- display_name: tiny\n"
    "- file_count: 3\n"
)


# --------------------------------------------------------------------------- #
# Stubs
# --------------------------------------------------------------------------- #


@dataclass
class _FakeLLMResponse:
    content: str


class _StubLLMClient:
    """Routes ``call_llm`` and ``stream_llm`` by ``agent_name`` heuristics.

    The base agent calls each method with a ``user_prompt`` that contains the
    rendered template; we discriminate by inspecting the system prompt header
    YAML (``decompose`` / ``investigate`` / ``note`` / ``compose``).
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
    """Pick the right canned response by which YAML the prompt manager loaded."""

    text = (system_prompt or "") + "\n" + (user_prompt or "")
    if "Decomposer" in text or "decompose" in text or "subtopics" in text.lower() or "支柱" in text:
        return "decompose"
    if "Investigator" in text or "want_more" in text or "action_input" in text:
        return "investigate"
    if "NoteTaker" in text or "note" in text.lower() or "笔记" in text:
        return "note"
    return "compose"


class _StubTool:
    """Minimal ``BaseTool``-shaped stub with a ``read_file_range`` action."""

    def get_definition(self) -> Any:
        from new_kernel.tools.tool_protocol import (
            ToolDefinition,
            ToolParameter,
        )

        return ToolDefinition(
            name="read_file_range",
            description="Read a slice of a file.",
            parameters=[
                ToolParameter(name="path", type="string"),
                ToolParameter(name="start_line", type="integer"),
                ToolParameter(name="end_line", type="integer"),
            ],
        )

    def get_prompt_hints(self, language: str = "zh") -> Any:
        from new_kernel.tools.tool_protocol import ToolPromptHints

        return ToolPromptHints(short_description="Read file slice.")

    @property
    def name(self) -> str:
        return "read_file_range"

    async def execute(self, *, ctx: Any, **kwargs: Any) -> ToolResult:
        return ToolResult.ok("# README\nfake body\n", metadata={})


class _StubToolRuntime:
    """Tiny ``ToolRuntime`` clone: records executes; never actually reads files."""

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
        return "| Action | Input | When to use |\n| --- | --- | --- |\n| read_file_range | ... | ... |"


class _CapturingSink:
    """Records every emitted event into ``self.events`` for assertions."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)


@dataclass
class _StubStatusTracker:
    """No-op tracker that returns a stable ``AgentStatus`` and counts updates."""

    session_id: str = "sess_test"
    update_calls: list[dict[str, Any]] = field(default_factory=list)
    metric_calls: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        from datetime import UTC, datetime

        self._current = AgentStatus(
            session_id=self.session_id,
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

    @property
    def current(self) -> AgentStatus:
        return self._current

    async def update_phase(self, **kwargs: Any) -> AgentStatus:
        self.update_calls.append(dict(kwargs))
        return self._current

    async def add_metrics(self, **kwargs: Any) -> AgentStatus:
        self.metric_calls.append(dict(kwargs))
        return self._current


# --------------------------------------------------------------------------- #
# Fixtures helpers
# --------------------------------------------------------------------------- #


def _build_loop(
    *,
    decompose_response: str,
    investigate_response: str,
    note_response: str,
    compose_chunks: list[str],
) -> tuple[DeepResearchLoop, _StubLLMClient, _StubToolRuntime]:
    llm_client = _StubLLMClient(
        decompose_response=decompose_response,
        investigate_response=investigate_response,
        note_response=note_response,
        compose_chunks=compose_chunks,
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
    return ["第一段", "第二段", "\n\n<<SUGGESTIONS>>\n", "- 接下来读 README\n"]


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_loop_emits_expected_event_sequence() -> None:
    """Run the full loop end-to-end; assert sink saw the documented event order.

    With each Investigator returning ``done``, every sub-topic still emits
    exactly one ``DeepResearchProgressEvent(phase=investigate)`` (the one we
    fire BEFORE entering the round loop). That gives us 1 triage + 1 decompose
    + 5 investigate + answer_stream_start/delta+/end.
    """

    loop, llm_client, tool_runtime = _build_loop(
        decompose_response=_five_pillar_decompose_payload(),
        investigate_response=_done_investigate_payload(),
        note_response="not used",
        compose_chunks=_standard_compose_chunks(),
    )
    scratchpad = ResearchScratchpad()
    sink = _CapturingSink()
    tracker = _StubStatusTracker()
    token = CancellationToken(session_id="s1", turn_id="t1")

    asyncio.run(
        loop.run(
            session_id="s1",
            turn_id="t1",
            user_message="请基于刚刚接入的仓库生成一份面向新手的入门导读。",
            scratchpad=scratchpad,
            repo_overview=_STANDARD_OVERVIEW,
            repo_root=Path("."),
            sink=sink,
            status_tracker=tracker,
            cancellation_token=token,
        )
    )

    # Filter to only the event types we care about ordering for; allow other
    # events (status, etc.) to interleave. AGENTS.md §4.2 requires this order.
    progress_phases = [
        ev.phase for ev in sink.events if isinstance(ev, DeepResearchProgressEvent)
    ]
    assert progress_phases[:2] == ["triage", "decompose"]
    assert progress_phases.count("investigate") == 5

    # Stream events.
    starts = [ev for ev in sink.events if isinstance(ev, AnswerStreamStartEvent)]
    deltas = [ev for ev in sink.events if isinstance(ev, AnswerStreamDeltaEvent)]
    ends = [ev for ev in sink.events if isinstance(ev, AnswerStreamEndEvent)]
    assert len(starts) == 1
    assert len(deltas) >= 1
    assert len(ends) == 1

    # Investigator says done for every sub-topic. The tool runtime is still
    # invoked exactly once for the arch pre-seed (RECON-D Option B); since the
    # default ``_StubToolRuntime`` only knows ``read_file_range`` it returns
    # failure and the prefab seed is silently skipped.
    assert [call["action"] for call in tool_runtime.execute_calls] == ["list_dir"]
    assert tool_runtime.execute_calls[0]["action_input"] == {"path": "."}

    # Last DeepResearchProgressEvent must be an investigate event before stream_start.
    progress_indices = [
        i for i, ev in enumerate(sink.events) if isinstance(ev, DeepResearchProgressEvent)
    ]
    start_index = next(i for i, ev in enumerate(sink.events) if isinstance(ev, AnswerStreamStartEvent))
    assert all(i < start_index for i in progress_indices)


def test_loop_returns_chat_message_with_repo_onboarding_kind() -> None:
    """Returned message must be DEEP / repo_onboarding / streaming_complete / parsed suggestions."""

    loop, _, _ = _build_loop(
        decompose_response=_five_pillar_decompose_payload(),
        investigate_response=_done_investigate_payload(),
        note_response="not used",
        compose_chunks=_standard_compose_chunks(),
    )
    scratchpad = ResearchScratchpad()
    sink = _CapturingSink()
    tracker = _StubStatusTracker()
    token = CancellationToken(session_id="s1", turn_id="t1")

    message = asyncio.run(
        loop.run(
            session_id="s1",
            turn_id="t1",
            user_message="seed",
            scratchpad=scratchpad,
            repo_overview=_STANDARD_OVERVIEW,
            repo_root=Path("."),
            sink=sink,
            status_tracker=tracker,
            cancellation_token=token,
        )
    )

    assert isinstance(message, ChatMessage)
    assert message.role == "assistant"
    assert message.mode == ChatMode.DEEP
    assert message.kind == ReportKind.REPO_ONBOARDING
    assert message.streaming_complete is True
    assert message.suggestions == ["接下来读 README"]
    # Visible body equals concatenation of pre-marker chunks.
    assert message.content.startswith("第一段")
    assert "<<SUGGESTIONS>>" not in message.content


def test_loop_cancellation_during_investigate_propagates() -> None:
    """Cancel after Phase 1; ``CancelledError`` must propagate, scratchpad keeps half-state."""

    # We use a custom investigate response that asks for a tool call so the
    # round loop reaches the cancellation checkpoint AFTER an Investigator call.
    investigate_call = json.dumps(
        {
            "action": "read_file_range",
            "action_input": {"path": "README.md", "start_line": 1, "end_line": 40},
            "intent": "看 README",
            "want_more": False,
        }
    )
    loop, _, _ = _build_loop(
        decompose_response=_five_pillar_decompose_payload(),
        investigate_response=investigate_call,
        note_response="读了 README，看到入门段落。",
        compose_chunks=_standard_compose_chunks(),
    )
    scratchpad = ResearchScratchpad()
    sink = _CapturingSink()
    tracker = _StubStatusTracker()
    token = CancellationToken(session_id="s1", turn_id="t1")

    # Wrap the sink to cancel the token as soon as we see the first investigate
    # progress event. The very next checkpoint inside the ReAct round will then
    # raise.
    original_emit = sink.emit
    cancel_after_first_investigate = {"fired": False}

    async def _emit_and_maybe_cancel(event: Any) -> None:
        await original_emit(event)
        if (
            isinstance(event, DeepResearchProgressEvent)
            and event.phase == "investigate"
            and not cancel_after_first_investigate["fired"]
        ):
            cancel_after_first_investigate["fired"] = True
            token.cancel("user_escape")

    sink.emit = _emit_and_maybe_cancel  # type: ignore[assignment]

    with pytest.raises(CancelledError):
        asyncio.run(
            loop.run(
                session_id="s1",
                turn_id="t1",
                user_message="seed",
                scratchpad=scratchpad,
                repo_overview=_STANDARD_OVERVIEW,
                repo_root=Path("."),
                sink=sink,
                status_tracker=tracker,
                cancellation_token=token,
            )
        )

    # AGENTS.md §5: scratchpad keeps half-state on cancel.
    # Sub-topics were set before the cancel; scratchpad therefore exposes them.
    assert len(scratchpad.subtopics) == 5
    # No assertion on note count — partial state is whatever happened to land.


def test_loop_short_branch_with_two_files_repo() -> None:
    """``file_count: 3`` + no primary_language → triage 'short'; loop completes with 1 sub-topic."""

    short_decompose = json.dumps(
        {
            "subtopics": [
                {"id": "what", "title": "做了什么", "anchors": []},
            ]
        }
    )
    loop, _, _ = _build_loop(
        decompose_response=short_decompose,
        investigate_response=_done_investigate_payload(),
        note_response="not used",
        compose_chunks=["短报告正文"],
    )
    scratchpad = ResearchScratchpad()
    sink = _CapturingSink()
    tracker = _StubStatusTracker()
    token = CancellationToken(session_id="s1", turn_id="t1")

    message = asyncio.run(
        loop.run(
            session_id="s1",
            turn_id="t1",
            user_message="seed",
            scratchpad=scratchpad,
            repo_overview=_SHORT_OVERVIEW,
            repo_root=Path("."),
            sink=sink,
            status_tracker=tracker,
            cancellation_token=token,
        )
    )

    investigate_events = [
        ev
        for ev in sink.events
        if isinstance(ev, DeepResearchProgressEvent) and ev.phase == "investigate"
    ]
    assert len(investigate_events) == 1
    assert investigate_events[0].total_units == 1

    triage_events = [
        ev
        for ev in sink.events
        if isinstance(ev, DeepResearchProgressEvent) and ev.phase == "triage"
    ]
    assert len(triage_events) == 1
    assert "short" in triage_events[0].summary

    assert isinstance(message, ChatMessage)
    assert message.kind == ReportKind.REPO_ONBOARDING
    assert message.content.startswith("短报告正文")


def test_loop_satisfies_turnloop_protocol_signature() -> None:
    """``DeepResearchLoop.run`` must expose the keyword-only TurnLoop signature."""

    sig = inspect.signature(DeepResearchLoop.run)
    expected = {
        "session_id",
        "turn_id",
        "user_message",
        "scratchpad",
        "repo_overview",
        "repo_root",
        "sink",
        "status_tracker",
        "cancellation_token",
    }
    actual = set(sig.parameters.keys()) - {"self"}
    missing = expected - actual
    assert not missing, f"DeepResearchLoop.run missing parameters: {missing}"
    for name in expected:
        param = sig.parameters[name]
        assert param.kind is inspect.Parameter.KEYWORD_ONLY, (
            f"parameter {name!r} must be keyword-only; got {param.kind!r}"
        )
    # Return annotation must resolve to ChatMessage (or its forward-reference).
    return_anno = sig.return_annotation
    if isinstance(return_anno, str):
        assert "ChatMessage" in return_anno
    else:
        assert return_anno is ChatMessage


def test_arch_subtopic_pre_seeds_list_dir_into_scratchpad() -> None:
    """RECON-D Option B: arch sub-topic must always pre-seed ``list_dir(.)``.

    The deterministic pre-step persists the raw output as the round-1
    ``raw_observation`` and writes a teacher-tone prefab note in front of the
    LLM-driven ReAct loop, so the Composer always sees the top-level directory
    listing without depending on Investigator's choices.
    """

    fake_listing = (
        "[dir]  api/\n"
        "[dir]  deep_research/\n"
        "[dir]  tools/\n"
        "[file] README.md (123 bytes)"
    )

    class _StubRuntimeWithListDir:
        """Like ``_StubToolRuntime`` but also handles ``list_dir``."""

        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []
            self._actions = frozenset(("read_file_range", "list_dir", "done"))

        @property
        def valid_actions(self) -> frozenset[str]:
            return self._actions

        async def execute(self, action: str, action_input: dict, *, ctx: Any) -> ToolResult:
            self.calls.append((action, dict(action_input)))
            if action == "list_dir":
                return ToolResult.ok(fake_listing, metadata={"path": "."})
            if action == "read_file_range":
                return ToolResult.ok("# README\nfake body\n", metadata={})
            return ToolResult.fail("unknown action", error_code="invalid_action")

        def build_reader_description(self) -> str:
            return (
                "| Action | Input | When to use |\n"
                "| --- | --- | --- |\n"
                "| read_file_range | path | read source slice |\n"
                "| list_dir | path | inspect directory |"
            )

    llm_client = _StubLLMClient(
        decompose_response=_five_pillar_decompose_payload(),
        investigate_response=_done_investigate_payload(),
        note_response="not used",
        compose_chunks=_standard_compose_chunks(),
    )
    pm = PromptManager(prompts_root=PROMPTS_ROOT)
    runtime = _StubRuntimeWithListDir()
    loop = DeepResearchLoop(
        decomposer=Decomposer(llm_client=llm_client, prompt_manager=pm),
        investigator=Investigator(llm_client=llm_client, prompt_manager=pm),
        note_taker=NoteTaker(llm_client=llm_client, prompt_manager=pm),
        composer=Composer(llm_client=llm_client, prompt_manager=pm),
        tool_runtime=runtime,
    )

    scratchpad = ResearchScratchpad()
    sink = _CapturingSink()
    tracker = _StubStatusTracker()
    token = CancellationToken(session_id="s_arch", turn_id="t_arch")

    message = asyncio.run(
        loop.run(
            session_id="s_arch",
            turn_id="t_arch",
            user_message="seed",
            scratchpad=scratchpad,
            repo_overview=_STANDARD_OVERVIEW,
            repo_root=Path("."),
            sink=sink,
            status_tracker=tracker,
            cancellation_token=token,
        )
    )

    # Exactly one list_dir(".") was issued for the arch pre-seed; no other
    # tool calls happened (Investigator returned 'done' for every sub-topic).
    list_dir_calls = [call for call in runtime.calls if call[0] == "list_dir"]
    assert list_dir_calls == [("list_dir", {"path": "."})]
    assert all(action != "read_file_range" for action, _ in runtime.calls)

    # The raw listing was persisted as the arch's round-1 raw observation.
    raw = scratchpad.first_round_raw("arch")
    assert raw is not None
    assert "[dir]  api/" in raw

    # The prefab note opens with the teacher-tone preamble and contains the
    # listing snippet.
    arch_notes = scratchpad.notes_for("arch")
    assert arch_notes, "arch sub-topic must have at least the prefab note"
    assert arch_notes[0].text.startswith("我们先扫了一眼仓库的顶层布局")
    assert "api/" in arch_notes[0].text
    assert arch_notes[0].anchor_path == "."
    assert arch_notes[0].success is True

    # End-to-end behaviour preserved.
    assert isinstance(message, ChatMessage)
    assert message.kind == ReportKind.REPO_ONBOARDING


def test_arch_pre_seed_skipped_when_subtopic_absent_short_branch() -> None:
    """Short branch never has an ``arch`` sub-topic → no pre-seed, no list_dir."""

    short_decompose = json.dumps(
        {
            "subtopics": [
                {"id": "what", "title": "做了什么", "anchors": []},
            ]
        }
    )
    loop, _, runtime = _build_loop(
        decompose_response=short_decompose,
        investigate_response=_done_investigate_payload(),
        note_response="not used",
        compose_chunks=["短报告正文"],
    )
    scratchpad = ResearchScratchpad()
    sink = _CapturingSink()
    tracker = _StubStatusTracker()
    token = CancellationToken(session_id="s_short", turn_id="t_short")

    asyncio.run(
        loop.run(
            session_id="s_short",
            turn_id="t_short",
            user_message="seed",
            scratchpad=scratchpad,
            repo_overview=_SHORT_OVERVIEW,
            repo_root=Path("."),
            sink=sink,
            status_tracker=tracker,
            cancellation_token=token,
        )
    )

    # ``list_dir`` must never have been invoked because the only sub-topic is
    # ``what``; Investigator immediately returns done so no ReAct tool calls fire.
    assert runtime.execute_calls == []


def test_overview_proxy_parses_top_level_paths_from_text() -> None:
    """RECON-D Option A1: ``_make_overview_proxy`` must populate the structured
    fields from the YAML-style sub-blocks emitted by ``overview_builder``."""

    from new_kernel.deep_research.deep_research_loop import _make_overview_proxy

    overview_text = (
        "repo_overview:\n"
        "- primary_language: Python\n"
        "- file_count: 17\n"
        "- top_level_paths:\n"
        "  - api/\n"
        "  - deep_research/\n"
        "  - tools/\n"
        "  - README.md\n"
        "- entry_candidates:\n"
        "  - README.md (markdown): top-level readme\n"
        "  - src/main.py (python): primary entry\n"
    )

    proxy = _make_overview_proxy(overview_text)

    assert proxy.primary_language == "Python"
    assert proxy.file_count == 17
    assert proxy.top_level_paths == ["api/", "deep_research/", "tools/", "README.md"]
    assert len(proxy.entry_candidates) == 2
    paths = [entry.path for entry in proxy.entry_candidates]
    assert paths == ["README.md", "src/main.py"]
    languages = [entry.language for entry in proxy.entry_candidates]
    assert languages == ["markdown", "python"]
    reasons = [entry.reason for entry in proxy.entry_candidates]
    assert reasons == ["top-level readme", "primary entry"]


def test_overview_proxy_missing_sub_blocks_leaves_lists_empty() -> None:
    """When ``top_level_paths`` / ``entry_candidates`` blocks are absent the
    proxy must expose empty lists rather than raising. Also locks the original
    minimal-overview behaviour kept across the FIX-03 refactor."""

    from new_kernel.deep_research.deep_research_loop import _make_overview_proxy

    overview_text = (
        "repo_overview:\n"
        "- primary_language: Python\n"
        "- file_count: 42\n"
    )

    proxy = _make_overview_proxy(overview_text)

    assert proxy.primary_language == "Python"
    assert proxy.file_count == 42
    assert proxy.top_level_paths == []
    assert proxy.entry_candidates == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
