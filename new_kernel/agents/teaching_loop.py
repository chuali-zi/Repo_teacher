"""TeachingLoop orchestrates orient, read, and teach for one normal turn."""

from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import uuid4

from ..contracts import (
    AgentPetState,
    AgentPhase,
    AgentStatus,
    ChatMessage,
    ChatMode,
    RepoTutorSseEvent,
    TeachingCodeSnippet,
)
from ..events.event_factory import EventFactory
from ..memory.scratchpad import Anchor, ReadEntry, ReadingStep, Scratchpad
from ..tools.tool_protocol import ToolContext, ToolRuntimeProtocol
from .orient_planner import OrientPlanner
from .reading_agent import ReadingAgent, ReadingDecision
from .teacher import TeacherAgent, TeacherOutput


PetMood = Literal["idle", "think", "act", "scan", "teach", "research", "error"]


class EventSink(Protocol):
    async def emit(self, event: RepoTutorSseEvent) -> None:
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


class CancellationToken(Protocol):
    def raise_if_cancelled(self) -> None:
        ...


class TeachingLoop:
    """Run one bounded repository teaching turn."""

    def __init__(
        self,
        *,
        orient: OrientPlanner | None = None,
        reader: ReadingAgent | None = None,
        teacher: TeacherAgent | None = None,
        tool_runtime: ToolRuntimeProtocol,
        llm_client: Any | None = None,
        prompt_manager: Any | None = None,
        max_steps: int = 2,
        max_react_iterations: int = 2,
        event_factory: Any | None = None,
    ) -> None:
        if tool_runtime is None:
            raise ValueError("tool_runtime is required")
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        if max_react_iterations < 1:
            raise ValueError("max_react_iterations must be positive")
        self._orient = orient or OrientPlanner(
            llm_client=llm_client,
            prompt_manager=prompt_manager,
        )
        self._reader = reader or ReadingAgent(
            llm_client=llm_client,
            prompt_manager=prompt_manager,
        )
        self._teacher = teacher or TeacherAgent(
            llm_client=llm_client,
            prompt_manager=prompt_manager,
        )
        self._tool_runtime = tool_runtime
        self._max_steps = max_steps
        self._max_react_iterations = max_react_iterations
        self._event_factory = event_factory or EventFactory()

    async def run(
        self,
        *,
        session_id: str,
        turn_id: str,
        user_message: str,
        scratchpad: Scratchpad,
        repo_overview: str,
        repo_root: Path,
        sink: EventSink,
        status_tracker: StatusTracker,
        cancellation_token: CancellationToken,
    ) -> ChatMessage:
        cancellation_token.raise_if_cancelled()
        scratchpad.reset_for_turn(user_message)

        await status_tracker.update_phase(
            state=AgentPetState.THINKING,
            phase=AgentPhase.PLANNING,
            label="规划中",
            pet_mood="think",
            pet_message="正在规划本轮要读的代码",
            current_action="生成阅读计划",
        )
        plan = await self._orient.process(
            question=user_message,
            repo_overview=repo_overview,
            previous_covered=scratchpad.covered_points,
            tool_descriptions=self._tool_runtime.build_planner_description(),
        )
        await _add_metrics(status_tracker, llm_call=1)
        steps = tuple(plan.steps[: self._max_steps])
        scratchpad.set_plan(steps)

        ctx = ToolContext(repo_root=str(repo_root))
        await status_tracker.update_phase(
            state=AgentPetState.ACTING,
            phase=AgentPhase.READING_CODE,
            label="读码中",
            pet_mood="act",
            pet_message="正在读取最少必要的源码证据",
            current_action="读取代码",
            current_target=_format_step_targets(steps),
        )

        async def _run_one(step: ReadingStep) -> None:
            cancellation_token.raise_if_cancelled()
            await self._run_read_step(
                step=step,
                question=user_message,
                scratchpad=scratchpad,
                ctx=ctx,
                sink=sink,
                session_id=session_id,
                status_tracker=status_tracker,
                cancellation_token=cancellation_token,
            )

        await asyncio.gather(*(_run_one(step) for step in steps))

        cancellation_token.raise_if_cancelled()
        await status_tracker.update_phase(
            state=AgentPetState.TEACHING,
            phase=AgentPhase.TEACHING,
            label="教学中",
            pet_mood="teach",
            pet_message="正在把源码证据整理成回答",
            current_action="生成教学回答",
        )

        message_id = _new_message_id("msg_assistant")
        await _emit(
            sink,
            self._event_factory.answer_stream_start_event(
                session_id=session_id,
                turn_id=turn_id,
                message_id=message_id,
                mode=ChatMode.CHAT,
            ),
        )
        stream_counter = 0

        async def on_chunk(chunk: str) -> None:
            nonlocal stream_counter
            stream_counter += 1
            if stream_counter % 8 == 0:
                cancellation_token.raise_if_cancelled()
            await _emit(
                sink,
                self._event_factory.answer_stream_delta_event(
                    session_id=session_id,
                    turn_id=turn_id,
                    message_id=message_id,
                    delta_text=chunk,
                ),
            )

        output = await self._teacher.process(
            question=user_message,
            scratchpad=scratchpad,
            previous_covered=scratchpad.covered_points,
            next_anchor_hint=_next_anchor_hint(steps),
            on_chunk=on_chunk,
        )
        await _add_metrics(status_tracker, llm_call=1)
        cancellation_token.raise_if_cancelled()
        await _emit(
            sink,
            self._event_factory.answer_stream_end_event(
                session_id=session_id,
                turn_id=turn_id,
                message_id=message_id,
            ),
        )

        _record_covered_point(scratchpad, steps=steps, output=output)
        return ChatMessage(
            message_id=message_id,
            role="assistant",
            mode=ChatMode.CHAT,
            content=output.full_text,
            created_at=_now_utc(),
            streaming_complete=True,
            suggestions=output.suggestions[:1],
        )

    async def _run_read_step(
        self,
        *,
        step: ReadingStep,
        question: str,
        scratchpad: Scratchpad,
        ctx: ToolContext,
        sink: EventSink,
        session_id: str,
        status_tracker: StatusTracker,
        cancellation_token: CancellationToken,
    ) -> None:
        for round_index in range(self._max_react_iterations):
            cancellation_token.raise_if_cancelled()
            decision = await self._reader.process(
                question=question,
                current_step=step,
                step_history=scratchpad.get_entries_for_step(step.step_id),
                previous_steps_summary=_previous_steps_summary(scratchpad, step.step_id),
                valid_actions=self._tool_runtime.valid_actions,
                tool_descriptions=self._tool_runtime.build_reader_description(),
            )
            await _add_metrics(status_tracker, llm_call=1)

            decision = _fail_closed_decision(decision, self._tool_runtime.valid_actions)
            if decision.action == "done":
                return

            await status_tracker.update_phase(
                state=AgentPetState.ACTING,
                phase=AgentPhase.READING_CODE,
                label="读码中",
                pet_mood="act",
                pet_message="正在调用只读仓库工具",
                current_action=decision.action,
                current_target=step.goal,
            )
            result = await self._tool_runtime.execute(
                decision.action,
                decision.action_input,
                ctx=ctx,
            )
            await _add_metrics(status_tracker, tool_call=1)
            observation = result.content
            if not result.success and result.error_code:
                observation = observation or f"Tool error ({result.error_code})"

            scratchpad.add_entry(
                ReadEntry(
                    step_id=step.step_id,
                    round_index=round_index,
                    thought=decision.thought,
                    action=decision.action,
                    action_input=decision.action_input,
                    observation=observation,
                    self_note=decision.self_note,
                    tool_success=result.success,
                )
            )
            snippet = _snippet_from_tool_result(step=step, result_content=observation, metadata=result.metadata)
            if snippet is not None:
                await _emit(
                    sink,
                    self._event_factory.teaching_code_event(
                        session_id=session_id,
                        snippet=snippet,
                    ),
                )


def _fail_closed_decision(
    decision: ReadingDecision,
    valid_actions: frozenset[str],
) -> ReadingDecision:
    if decision.action in valid_actions:
        return decision
    return ReadingDecision(
        thought=decision.thought,
        action="done",
        action_input={},
        self_note="action 不在可用动作空间内，已安全结束当前 step。",
    )


def _previous_steps_summary(scratchpad: Scratchpad, current_step_id: str) -> str:
    lines: list[str] = []
    for step in scratchpad.reading_plan:
        if step.step_id == current_step_id:
            continue
        notes = [
            entry.self_note
            for entry in scratchpad.get_entries_for_step(step.step_id)
            if entry.self_note
        ]
        if notes:
            lines.append(f"{step.step_id}: " + " | ".join(notes))
    return "\n".join(lines) if lines else "(none)"


def _next_anchor_hint(steps: tuple[ReadingStep, ...]) -> Anchor | None:
    for step in steps:
        if step.anchors:
            return step.anchors[0]
    return None


def _format_step_targets(steps: tuple[ReadingStep, ...]) -> str | None:
    if not steps:
        return None
    return "；".join(step.goal for step in steps if step.goal)[:240] or None


def _record_covered_point(
    scratchpad: Scratchpad,
    *,
    steps: tuple[ReadingStep, ...],
    output: TeacherOutput,
) -> None:
    if not steps or not scratchpad.read_entries or not output.full_text.strip():
        return
    first_step = steps[0]
    summary = output.suggestions[0] if output.suggestions else _first_sentence(output.full_text)
    scratchpad.update_covered_points(first_step.step_id, summary[:300])


def _first_sentence(text: str) -> str:
    cleaned = " ".join(text.split())
    for marker in ("。", "！", "？", ".", "!", "?"):
        index = cleaned.find(marker)
        if index >= 0:
            return cleaned[: index + 1]
    return cleaned[:180]


def _snippet_from_tool_result(
    *,
    step: ReadingStep,
    result_content: str,
    metadata: dict[str, Any],
) -> TeachingCodeSnippet | None:
    path = metadata.get("path")
    start_line = metadata.get("start_line")
    end_line = metadata.get("end_line")
    if not isinstance(path, str) or not isinstance(start_line, int) or not isinstance(end_line, int):
        return None
    if start_line < 1 or end_line < start_line:
        return None
    return TeachingCodeSnippet(
        snippet_id=f"snip_{uuid4().hex[:12]}",
        path=path,
        language=_language_from_path(path),
        start_line=start_line,
        end_line=end_line,
        title=step.goal[:80] or None,
        reason=step.goal,
        code=result_content,
    )


def _language_from_path(path: str) -> str | None:
    suffix = Path(path).suffix.lower().lstrip(".")
    return {
        "py": "python",
        "ts": "typescript",
        "tsx": "tsx",
        "js": "javascript",
        "jsx": "jsx",
        "md": "markdown",
        "json": "json",
        "yaml": "yaml",
        "yml": "yaml",
    }.get(suffix, suffix or None)


async def _add_metrics(
    status_tracker: StatusTracker,
    *,
    llm_call: int = 0,
    tool_call: int = 0,
) -> None:
    result = status_tracker.add_metrics(llm_call=llm_call, tool_call=tool_call, emit=False)
    if inspect.isawaitable(result):
        await result


async def _emit(sink: EventSink, event: RepoTutorSseEvent) -> None:
    emit = getattr(sink, "emit", None) or getattr(sink, "publish", None)
    if emit is None:
        raise RuntimeError("event sink must expose emit(event)")
    result = emit(event)
    if inspect.isawaitable(result):
        await result


def _new_message_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _now_utc() -> datetime:
    return datetime.now(UTC)


__all__ = ["EventSink", "StatusTracker", "TeachingLoop"]
