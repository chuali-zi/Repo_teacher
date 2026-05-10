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
from types import SimpleNamespace
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
from .research_scratchpad import SubtopicMeta, SubtopicNote
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
    """Parse the structured fields ``triage()`` / Decomposer read from overview text.

    Beyond ``primary_language`` / ``file_count``, this also parses the YAML-style
    sub-blocks emitted by ``repo/overview_builder.py`` (``- top_level_paths:`` and
    ``- entry_candidates:``) so the Decomposer's anchor reachability check has
    real data to work with. Missing sub-blocks leave the fields as empty lists
    (RECON-D §A1 / RECON-B Severity-3).
    """

    text = repo_overview or ""
    primary: str | None = None
    file_count = 0
    top_level_paths: list[str] = []
    entry_candidates: list[Any] = []
    current_block: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.lstrip()
        # Sub-block headers — note these themselves start with "- " at the
        # top-level indent; check for them before treating "- " as a generic
        # block terminator.
        if stripped.startswith("- top_level_paths:"):
            current_block = "paths"
            continue
        if stripped.startswith("- entry_candidates:"):
            current_block = "entries"
            continue
        # 2-space indented "  - <value>" rows belong to the current sub-block.
        if current_block == "paths" and line.startswith("  - "):
            value = line[4:].strip()
            if value and len(top_level_paths) < 60:
                top_level_paths.append(value)
            continue
        if current_block == "entries" and line.startswith("  - "):
            value = line[4:].strip()
            if value and len(entry_candidates) < 12:
                path, lang, reason = _parse_entry_candidate_line(value)
                entry_candidates.append(
                    SimpleNamespace(path=path, language=lang, reason=reason)
                )
            continue
        # A new top-level "- " line (or a blank line) closes any open sub-block.
        if line.startswith("- ") or not line.strip():
            current_block = None
        # Top-level scalar fields.
        if line.startswith("- "):
            scalar = line[2:].strip()
            if scalar.startswith("primary_language:"):
                value = scalar.split(":", 1)[1].strip()
                if value and value.lower() not in {"none", "null", "unknown"}:
                    primary = value
            elif scalar.startswith("file_count:"):
                value = scalar.split(":", 1)[1].strip()
                try:
                    file_count = int(value)
                except ValueError:
                    file_count = 0
    if file_count <= 0:
        # Keep file_count >= 1 so triage doesn't raise EmptyRepositoryError for
        # repos that just lack the field; an empty repo would have already been
        # rejected upstream by the parse pipeline.
        file_count = 1
    proxy = _StringOverview(text=text, primary_language=primary, file_count=file_count)
    proxy.top_level_paths = top_level_paths
    proxy.entry_candidates = entry_candidates
    return proxy


def _parse_entry_candidate_line(value: str) -> tuple[str, str | None, str | None]:
    """Parse "<path> (<lang>): <reason>" → (path, lang, reason); tolerant of variants."""

    if "(" in value and "):" in value:
        head, _, tail = value.partition(" (")
        lang_part, _, reason_part = tail.partition("): ")
        path = head.strip() or value
        lang = lang_part.strip() or None
        reason = reason_part.strip() or None
        return path, lang, reason
    return value, None, None


def _pick_arch_drill_target(overview: Any) -> str | None:
    """Pick the most representative source file for the arch ReAct round to read.

    Priority (RECON-E §D3, FIX-05):
      1. First entry_candidate whose language is not markdown/plaintext.
      2. First entry_candidate of any language.
      3. First reachable top_level path that is file-like (not endswith('/')).
      4. None — caller skips the nudge.
    """

    entries = list(getattr(overview, "entry_candidates", ()) or ())
    for entry in entries:
        path = getattr(entry, "path", None)
        lang = getattr(entry, "language", None)
        if not isinstance(path, str) or not path:
            continue
        if lang and str(lang).lower() in {"markdown", "plaintext", "text"}:
            continue
        return path
    for entry in entries:
        path = getattr(entry, "path", None)
        if isinstance(path, str) and path:
            return path
    paths = list(getattr(overview, "top_level_paths", ()) or ())
    for path in paths:
        if isinstance(path, str) and path and not path.endswith("/"):
            return path
    return None


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
            repo_overview_obj=overview_obj,
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
        repo_overview_obj: Any = None,
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

            # RECON-D Option B: for the arch sub-topic specifically, run one
            # deterministic ``list_dir(".")`` and persist it as the round-1
            # ``raw_observation`` plus a prefab teacher-tone note. This guarantees
            # the Composer always sees the top-level directory listing without
            # touching any LLM prompt; ReAct rounds 2+ proceed normally on top of
            # the seeded scratchpad. Cost actually drops vs the old path because
            # we skip one NoteTaker LLM call.
            arch_pre_seeded = False
            if subtopic.id == "arch":
                pre_result = await self._tool_runtime.execute(
                    "list_dir", {"path": "."}, ctx=ctx
                )
                await _add_metrics(status_tracker, tool_call=1)
                if getattr(pre_result, "success", False):
                    raw_text = (getattr(pre_result, "content", None) or "")[:1800]
                    # RECON-E §D3 / FIX-05: pick a concrete file path to point
                    # the round-2 Investigator toward source reading. We reserve
                    # ~180 chars at the tail for the nudge so the listing portion
                    # is capped at 420 chars BEFORE the nudge gets appended;
                    # whole prefab still fits the existing 600-char hard cap.
                    nudge_target = _pick_arch_drill_target(repo_overview_obj)
                    listing_cap = 420 if nudge_target else 600
                    head = "我们先扫了一眼仓库的顶层布局，看看一共分了几大块：\n"
                    listing_room = max(0, listing_cap - len(head))
                    prefab_text = head + raw_text[:listing_room]
                    if nudge_target:
                        nudge = (
                            f"\n\n挑一个具体地方往里走一步：我们先打开 `{nudge_target}` "
                            f"看一段，把这块代码长什么样、关键 symbol 是啥、和上下游怎么连，"
                            f"摆到学生面前。"
                        )
                        prefab_text += nudge[:180]
                    prefab_note = SubtopicNote(
                        text=prefab_text[:600],
                        success=True,
                        anchor_path=".",
                        anchor_lines=None,
                    )
                    scratchpad.add_note(
                        subtopic.id,
                        1,
                        prefab_note,
                        raw_observation=getattr(pre_result, "content", None),
                    )
                    arch_pre_seeded = True

            policy.reset_failure()
            start_round = 2 if arch_pre_seeded else 1
            for round_idx in range(start_round, policy.round_quota() + 1):
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
