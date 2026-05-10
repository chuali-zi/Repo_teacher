"""DeepResearchLoop: orchestrates Phase 0..3 of the repo onboarding research turn.

This module implements the ``TurnLoop`` Protocol declared in
``turn/turn_runtime.py`` (we conform to the protocol rather than importing it,
per AGENTS.md §11.1). It owns the four-phase pipeline — Phase 0 Triage, Phase 1
Decompose, Phase 2 Investigate (sequential ReAct rounds), Phase 3 Compose
(streaming) — and threads cancellation, metrics, and SSE progress through every
checkpoint required by AGENTS.md §0..§14.

It does NOT call other modules' loops, does NOT emit ``MessageCompletedEvent``
(``TurnRuntime`` does), does NOT swallow LLM errors, does NOT persist anything
beyond the scratchpad mutations triggered by its sub-agents. Cancellation
checkpoints fire at: turn entry, Phase 1 entry, every sub-topic, every ReAct
round, Phase 3 entry, and every 8 streaming chunks (AGENTS.md §5 / §12.1).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..contracts import (
    AgentPetState,
    AgentPhase,
    AnswerStreamDeltaEvent,
    AnswerStreamEndEvent,
    AnswerStreamStartEvent,
    ChatMessage,
    ChatMode,
    DeepResearchProgressEvent,
    ReportKind,
    SseEventType,
)
from ..tools.tool_protocol import ToolContext
from .agents.composer import Composer
from .agents.decomposer import Decomposer
from .agents.investigator import Investigator
from .agents.note_taker import NoteTaker
from .investigation_policy import InvestigationPolicy
from .research_scratchpad import SubtopicMeta
from .triage import TriageDecision, triage


_OBSERVATION_NOTE_LIMIT = 2048


def _new_message_id() -> str:
    return f"msg_assistant_{uuid4().hex[:12]}"


def _new_event_id() -> str:
    return f"evt_{uuid4().hex[:12]}"


def _now_utc() -> datetime:
    return datetime.now(UTC)


class _StringOverview:
    """Best-effort proxy that exposes the fields ``triage()`` reads from a string.

    ``TurnRuntime._repo_overview()`` produces a plain string; ``triage()`` and
    the Decomposer want object attributes (``primary_language``, ``file_count``,
    ``language_counts``, ``top_level_paths``, ``entry_candidates``, ``text``).
    Per AGENTS.md §3.1's parser-style note we parse two known lines out of the
    overview text and leave the rest empty — safe for triage's decision matrix
    and the decomposer's anchor reachability check (unknown anchors are dropped
    while the sub-topic itself is kept).
    """

    __slots__ = (
        "text",
        "primary_language",
        "file_count",
        "language_counts",
        "top_level_paths",
        "entry_candidates",
    )

    def __init__(self, *, text: str, primary_language: str | None, file_count: int) -> None:
        self.text = text or ""
        self.primary_language = primary_language
        self.file_count = file_count
        self.language_counts: dict[str, int] = {}
        self.top_level_paths: list[str] = []
        self.entry_candidates: list[Any] = []


def _make_overview_proxy(repo_overview: str) -> _StringOverview:
    """Parse ``primary_language`` / ``file_count`` lines out of the overview text."""

    text = repo_overview or ""
    primary: str | None = None
    file_count = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("- "):
            line = line[2:].strip()
        if line.startswith("primary_language:"):
            value = line.split(":", 1)[1].strip()
            if value and value.lower() not in {"none", "null", "unknown"}:
                primary = value
        elif line.startswith("file_count:"):
            value = line.split(":", 1)[1].strip()
            try:
                file_count = int(value)
            except ValueError:
                file_count = 0
    if file_count <= 0:
        # Keep file_count >= 1 so triage doesn't raise EmptyRepositoryError for
        # repos that just lack the field; an empty repo would have already been
        # rejected upstream by the parse pipeline.
        file_count = 1
    return _StringOverview(text=text, primary_language=primary, file_count=file_count)


class DeepResearchLoop:
    """Run one onboarding turn through the four-phase research pipeline.

    Conforms to ``turn.turn_runtime.TurnLoop`` Protocol (we don't import it to
    keep the dependency arrow turn -> deep_research one-way per AGENTS.md
    §11.1). The constructor takes the four sub-agents and a tool runtime; the
    ``run`` method drives them through Triage -> Decompose -> Investigate ->
    Compose, emitting progress and answer-stream events along the way.
    """

    def __init__(
        self,
        *,
        decomposer: Decomposer,
        investigator: Investigator,
        note_taker: NoteTaker,
        composer: Composer,
        tool_runtime: Any,
        max_rounds_per_subtopic: int = 2,
        max_parallel_subtopics: int = 1,
        event_factory: Any | None = None,
        message_id_factory: Callable[[], str] = _new_message_id,
    ) -> None:
        if max_rounds_per_subtopic < 1:
            raise ValueError("max_rounds_per_subtopic must be positive")
        self._decomposer = decomposer
        self._investigator = investigator
        self._note_taker = note_taker
        self._composer = composer
        self._tool_runtime = tool_runtime
        self._max_rounds_per_subtopic = max_rounds_per_subtopic
        # v1 only supports parallel=1; we record the value but always run sequential.
        self._max_parallel_subtopics = max_parallel_subtopics
        self._event_factory = event_factory
        self._message_id_factory = message_id_factory

    async def run(
        self,
        *,
        session_id: str,
        turn_id: str,
        user_message: str,
        scratchpad: Any,
        repo_overview: str,
        repo_root: Path,
        sink: Any,
        status_tracker: Any,
        cancellation_token: Any,
    ) -> ChatMessage:
        """Drive the four-phase onboarding pipeline; return the assistant ``ChatMessage``."""

        # Phase 0 — Triage (pure, no LLM).
        cancellation_token.raise_if_cancelled()
        overview_obj = _make_overview_proxy(repo_overview)
        decision = triage(overview_obj)
        await self._emit_progress(
            sink,
            session_id=session_id,
            turn_id=turn_id,
            phase="triage",
            summary=decision.reason,
            completed_units=0,
            total_units=0,
            current_target=None,
        )

        # Phase 1 — Decompose (1 LLM call).
        cancellation_token.raise_if_cancelled()
        subtopics = await self._decomposer.process(
            report_shape=decision.report_shape,
            repo_overview=overview_obj,
        )
        scratchpad.set_subtopics(list(subtopics))
        await _add_metrics(status_tracker, llm_call=1)
        await self._emit_progress(
            sink,
            session_id=session_id,
            turn_id=turn_id,
            phase="decompose",
            summary=f"切成 {len(subtopics)} 个支柱",
            completed_units=0,
            total_units=len(subtopics),
            current_target=None,
        )

        # Phase 2 — Investigate (sequential per AGENTS.md §3.3 / v1 max_parallel=1).
        await self._run_investigate_phase(
            subtopics=subtopics,
            scratchpad=scratchpad,
            repo_overview_text=overview_obj.text,
            repo_root=repo_root,
            session_id=session_id,
            turn_id=turn_id,
            sink=sink,
            status_tracker=status_tracker,
            cancellation_token=cancellation_token,
        )

        # Phase 3 — Compose (1 streaming LLM call).
        cancellation_token.raise_if_cancelled()
        return await self._run_compose_phase(
            decision=decision,
            scratchpad=scratchpad,
            repo_overview_text=overview_obj.text,
            session_id=session_id,
            turn_id=turn_id,
            sink=sink,
            status_tracker=status_tracker,
            cancellation_token=cancellation_token,
        )

    async def _run_investigate_phase(
        self,
        *,
        subtopics: list[SubtopicMeta],
        scratchpad: Any,
        repo_overview_text: str,
        repo_root: Path,
        session_id: str,
        turn_id: str,
        sink: Any,
        status_tracker: Any,
        cancellation_token: Any,
    ) -> None:
        """Sequentially run ReAct rounds for each sub-topic."""

        policy = InvestigationPolicy(max_rounds=self._max_rounds_per_subtopic)
        valid_actions = tuple(self._tool_runtime.valid_actions)
        tools_description = self._tool_runtime.build_reader_description()
        ctx = ToolContext(repo_root=str(repo_root))
        total = len(subtopics)

        for index, subtopic in enumerate(subtopics, start=1):
            cancellation_token.raise_if_cancelled()
            await self._emit_progress(
                sink,
                session_id=session_id,
                turn_id=turn_id,
                phase="investigate",
                summary=subtopic.title,
                completed_units=index - 1,
                total_units=total,
                current_target=subtopic.title,
            )

            policy.reset_failure()
            for round_idx in range(1, policy.round_quota() + 1):
                cancellation_token.raise_if_cancelled()
                decision_io = await self._investigator.process(
                    subtopic=subtopic,
                    notes_history=scratchpad.notes_for(subtopic.id),
                    failure_streak=policy.failure_streak,
                    valid_actions=valid_actions,
                    tools_description=tools_description,
                    repo_overview_text=repo_overview_text,
                )
                await _add_metrics(status_tracker, llm_call=1)

                if decision_io.action == "done":
                    break

                tool_result = await self._tool_runtime.execute(
                    decision_io.action,
                    decision_io.action_input,
                    ctx=ctx,
                )
                await _add_metrics(status_tracker, tool_call=1)

                observation_text = _format_observation(tool_result)
                tool_success = bool(getattr(tool_result, "success", True))

                note = await self._note_taker.process(
                    subtopic=subtopic,
                    intent=decision_io.intent,
                    tool_action=decision_io.action,
                    tool_input=decision_io.action_input,
                    observation=observation_text[:_OBSERVATION_NOTE_LIMIT],
                    success=tool_success,
                )
                await _add_metrics(status_tracker, llm_call=1)

                scratchpad.add_note(
                    subtopic.id,
                    round_idx,
                    note,
                    raw_observation=observation_text if round_idx == 1 else None,
                )

                if not tool_success:
                    policy.bump_failure()
                    if policy.failure_streak >= policy.max_consecutive_failures:
                        policy.mark_skipped(subtopic.id)
                        scratchpad.add_skip_reason(subtopic.id, "工具连续失败")
                        break
                else:
                    policy.reset_failure()

                if not policy.can_continue(
                    current_round=round_idx,
                    want_more=bool(decision_io.want_more),
                    last_action_done=False,
                ):
                    break

    async def _run_compose_phase(
        self,
        *,
        decision: TriageDecision,
        scratchpad: Any,
        repo_overview_text: str,
        session_id: str,
        turn_id: str,
        sink: Any,
        status_tracker: Any,
        cancellation_token: Any,
    ) -> ChatMessage:
        """Stream the long-form report; return the terminal ``ChatMessage``."""

        await status_tracker.update_phase(
            state=AgentPetState.RESEARCHING,
            phase=AgentPhase.STREAMING,
            label="正在撰写导读",
            pet_mood="research",
            pet_message="正在把笔记串成正文",
            current_action="撰写导读",
        )

        message_id = self._message_id_factory()
        await self._emit_event(
            sink,
            self._build_event(
                "answer_stream_start_event",
                AnswerStreamStartEvent,
                SseEventType.ANSWER_STREAM_START,
                session_id=session_id,
                turn_id=turn_id,
                message_id=message_id,
                mode=ChatMode.DEEP,
            ),
        )

        chunk_count = 0
        async for delta in self._composer.stream(
            report_shape=decision.report_shape,
            repo_overview_text=repo_overview_text,
            scratchpad_context=scratchpad.build_compose_context(),
        ):
            if not delta:
                continue
            chunk_count += 1
            if chunk_count % 8 == 0:
                cancellation_token.raise_if_cancelled()
            await self._emit_event(
                sink,
                self._build_event(
                    "answer_stream_delta_event",
                    AnswerStreamDeltaEvent,
                    SseEventType.ANSWER_STREAM_DELTA,
                    session_id=session_id,
                    turn_id=turn_id,
                    message_id=message_id,
                    delta_text=delta,
                ),
            )

        await _add_metrics(status_tracker, llm_call=1)
        await self._emit_event(
            sink,
            self._build_event(
                "answer_stream_end_event",
                AnswerStreamEndEvent,
                SseEventType.ANSWER_STREAM_END,
                session_id=session_id,
                turn_id=turn_id,
                message_id=message_id,
            ),
        )

        composed = self._composer.last_output
        markdown = composed.markdown if composed and composed.markdown else "(本次未产出导读)"
        suggestions = list(composed.suggestions) if composed else []
        return ChatMessage(
            message_id=message_id,
            role="assistant",
            mode=ChatMode.DEEP,
            kind=ReportKind.REPO_ONBOARDING,
            content=markdown,
            created_at=_now_utc(),
            streaming_complete=True,
            suggestions=suggestions,
        )

    async def _emit_progress(
        self,
        sink: Any,
        *,
        session_id: str,
        turn_id: str,
        phase: str,
        summary: str,
        completed_units: int,
        total_units: int,
        current_target: str | None,
    ) -> None:
        event = self._build_event(
            "deep_research_progress_event",
            DeepResearchProgressEvent,
            SseEventType.DEEP_RESEARCH_PROGRESS,
            session_id=session_id,
            turn_id=turn_id,
            phase=phase,
            summary=summary,
            completed_units=completed_units,
            total_units=total_units,
            current_target=current_target,
        )
        await self._emit_event(sink, event)

    def _build_event(
        self,
        factory_method_name: str,
        event_class: type,
        event_type: SseEventType,
        *,
        session_id: str,
        **fields: Any,
    ) -> Any:
        """Build an SSE event via the injected factory or by direct contract construction.

        When ``self._event_factory`` exposes ``factory_method_name``, we delegate
        to it (passing ``session_id`` plus the remaining ``fields``); otherwise
        we instantiate ``event_class`` directly with a fresh ``event_id`` /
        ``occurred_at`` envelope and the same fields.
        """

        method = _factory_method(self._event_factory, factory_method_name)
        if method is not None:
            return method(session_id=session_id, **fields)
        return event_class(
            event_id=_new_event_id(),
            event_type=event_type,
            session_id=session_id,
            occurred_at=_now_utc(),
            **fields,
        )

    async def _emit_event(self, sink: Any, event: Any) -> None:
        emit = getattr(sink, "emit", None) or getattr(sink, "publish", None)
        if emit is None:
            raise RuntimeError("event sink must expose emit(event)")
        result = emit(event)
        if inspect.isawaitable(result):
            await result


def _factory_method(factory: Any, method_name: str) -> Callable[..., Any] | None:
    """Return a callable for the named factory method, or ``None``."""

    if factory is None:
        return None
    method = getattr(factory, method_name, None)
    return method if callable(method) else None


async def _add_metrics(
    status_tracker: Any,
    *,
    llm_call: int = 0,
    tool_call: int = 0,
) -> None:
    """Mirror the ``teaching_loop`` pattern: tolerate sync or async ``add_metrics``."""

    method = getattr(status_tracker, "add_metrics", None)
    if method is None:
        return
    result = method(llm_call=llm_call, tool_call=tool_call, emit=False)
    if inspect.isawaitable(result):
        await result


def _format_observation(tool_result: Any) -> str:
    """Resolve a ``ToolResult``-like into the string we feed to NoteTaker / scratchpad."""

    content = getattr(tool_result, "content", None)
    if content is None:
        return ""
    return content if isinstance(content, str) else str(content)


__all__ = ["DeepResearchLoop"]
