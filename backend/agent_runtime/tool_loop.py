from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from time import monotonic
from typing import Any

from backend.agent_runtime.tool_selection import select_tools_for_prompt_input
from backend.contracts.domain import FileTreeSnapshot, PromptBuildInput, RepositoryContext
from backend.m6_response.budgets import output_token_budget_for_scenario
from backend.m6_response.llm_caller import (
    StreamResult,
    ToolCallRequest,
    stream_llm_response_with_tools,
)
from backend.m6_response.prompt_builder import build_messages
from backend.m6_response.tool_executor import api_tool_name, execute_tool_call, normalize_tool_name

ToolAwareLlmStreamer = Any
ActivityEmitter = Any


@dataclass(frozen=True)
class ToolStreamTextDelta:
    text: str


@dataclass(frozen=True)
class ToolStreamActivity:
    payload: dict[str, Any]
    recorded_event: Any | None = None


ToolStreamItem = ToolStreamTextDelta | ToolStreamActivity


@dataclass(frozen=True)
class ToolLoopTimeouts:
    thinking_notice_seconds: float = 1.5
    code_search_notice_seconds: float = 4.0
    tool_soft_timeout_seconds: float = 12.0
    tool_hard_timeout_seconds: float = 20.0


DEFAULT_TOOL_LOOP_TIMEOUTS = ToolLoopTimeouts()


@dataclass(frozen=True)
class _ToolExecution:
    tool_call: ToolCallRequest
    tool_output: str
    degraded: bool


async def stream_answer_text_with_tools(
    input_data: PromptBuildInput,
    *,
    repository: RepositoryContext,
    file_tree: FileTreeSnapshot,
    tool_streamer: ToolAwareLlmStreamer = stream_llm_response_with_tools,
    on_activity: ActivityEmitter | None = None,
    timeouts: ToolLoopTimeouts = DEFAULT_TOOL_LOOP_TIMEOUTS,
) -> AsyncIterator[ToolStreamItem]:
    messages: list[dict[str, Any]] = build_messages(input_data)
    selected_tool_schemas = list(select_tools_for_prompt_input(input_data).openai_schemas)
    max_tool_rounds = max(input_data.max_tool_rounds, 0)
    max_tokens = output_token_budget_for_scenario(input_data.scenario)
    tool_rounds_used = 0
    round_index = 0

    while True:
        queue: asyncio.Queue[ToolStreamItem | None] = asyncio.Queue()
        round_started_at = monotonic()
        emitted_visible_text = False
        emitted_chunks: list[str] = []
        allow_tools = tool_rounds_used < max_tool_rounds
        active_tool_schemas = selected_tool_schemas if allow_tools else []

        async def _emit_activity(phase: str, summary: str, **extra: Any) -> ToolStreamActivity:
            item = await _make_activity_item(
                on_activity,
                round_started_at,
                round_index,
                phase,
                summary,
                **extra,
            )
            await queue.put(item)
            return item

        thinking_task = asyncio.create_task(
            _emit_after(
                timeouts.thinking_notice_seconds,
                _emit_activity,
                "thinking",
                "Thinking through the question and current evidence.",
            )
        )
        search_task = asyncio.create_task(
            _emit_after(
                timeouts.code_search_notice_seconds,
                _emit_activity,
                "slow_warning",
                "Still locating relevant source evidence.",
            )
        )

        async def _on_delta(chunk: str) -> None:
            emitted_chunks.append(chunk)
            await queue.put(ToolStreamTextDelta(chunk))

        async def _runner() -> StreamResult:
            try:
                return await _call_tool_streamer(
                    tool_streamer,
                    messages,
                    tools=active_tool_schemas,
                    on_content_delta=_on_delta,
                    max_tokens=max_tokens,
                )
            finally:
                await queue.put(None)

        runner_task = asyncio.create_task(_runner())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, ToolStreamTextDelta):
                    emitted_visible_text = True
                yield item
            result = await runner_task
        except BaseException:
            thinking_task.cancel()
            search_task.cancel()
            runner_task.cancel()
            try:
                await runner_task
            except BaseException:
                pass
            raise
        finally:
            thinking_task.cancel()
            search_task.cancel()

        if not emitted_chunks and result.content_chunks:
            for chunk in result.content_chunks:
                emitted_visible_text = True
                yield ToolStreamTextDelta(chunk)

        if not result.tool_calls:
            return

        if not allow_tools:
            yield await _make_activity_item(
                on_activity,
                round_started_at,
                round_index,
                "degraded_continue",
                "The model asked for more tools after the tool limit was reached.",
            )
            return

        tool_calls = _normalize_tool_calls(result.tool_calls, round_index)
        if not emitted_visible_text:
            yield await _make_activity_item(
                on_activity,
                round_started_at,
                round_index,
                "planning_tool_call",
                "Choosing which repository evidence to verify next.",
            )

        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": tool_call.call_id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function_name,
                        "arguments": tool_call.arguments_json,
                    },
                }
                for tool_call in tool_calls
            ],
        }
        full_content = "".join(result.content_chunks)
        if full_content:
            assistant_message["content"] = full_content
        messages.append(assistant_message)

        async for activity in _execute_tool_batch(
            tool_calls,
            round_started_at=round_started_at,
            round_index=round_index,
            repository=repository,
            file_tree=file_tree,
            on_activity=on_activity,
            timeouts=timeouts,
        ):
            if isinstance(activity, ToolStreamActivity):
                yield activity
                continue

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": activity.tool_call.call_id,
                    "content": activity.tool_output,
                }
            )
            if activity.degraded:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "The previous tool call failed or timed out. Continue with the existing"
                            " evidence, stay conservative, and mark uncertainty clearly."
                        ),
                    }
                )
                yield await _make_activity_item(
                    on_activity,
                    round_started_at,
                    round_index,
                    "degraded_continue",
                    "A tool failed, so the answer is continuing from existing evidence only.",
                )
                continue

            yield await _make_activity_item(
                on_activity,
                round_started_at,
                round_index,
                "tool_succeeded",
                f"{activity.tool_call.function_name} returned successfully.",
                tool_name=activity.tool_call.function_name,
                tool_arguments=_safe_json_loads(activity.tool_call.arguments_json),
            )

        tool_rounds_used += 1
        if tool_rounds_used >= max_tool_rounds:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "The tool round limit has been reached. Finish the answer directly without"
                        " asking for more tools."
                    ),
                }
            )
            yield await _make_activity_item(
                on_activity,
                round_started_at,
                round_index,
                "degraded_continue",
                "Tool round limit reached; finishing without more tool calls.",
            )
            async for item in _stream_final_answer_without_tools(
                messages,
                tool_streamer=tool_streamer,
                on_activity=on_activity,
                round_index=round_index + 1,
                max_tokens=max_tokens,
            ):
                yield item
            return

        yield await _make_activity_item(
            on_activity,
            round_started_at,
            round_index,
            "waiting_llm_after_tool",
            "Tool results are ready; asking the model to continue.",
        )
        round_index += 1


async def _execute_tool_batch(
    tool_calls: list[ToolCallRequest],
    *,
    round_started_at: float,
    round_index: int,
    repository: RepositoryContext,
    file_tree: FileTreeSnapshot,
    on_activity: ActivityEmitter | None,
    timeouts: ToolLoopTimeouts,
) -> AsyncIterator[ToolStreamActivity | _ToolExecution]:
    activity_queue: asyncio.Queue[ToolStreamActivity] = asyncio.Queue()
    task_order: list[str] = []
    tasks: list[asyncio.Task[_ToolExecution]] = []

    async def _tool_activity(phase: str, summary: str, **extra: Any) -> None:
        item = await _make_activity_item(
            on_activity,
            round_started_at,
            round_index,
            phase,
            summary,
            **extra,
        )
        await activity_queue.put(item)

    for tool_call in tool_calls:
        arguments = _safe_json_loads(tool_call.arguments_json)
        yield await _make_activity_item(
            on_activity,
            round_started_at,
            round_index,
            "tool_running",
            _tool_summary(tool_call.function_name, tool_call.arguments_json),
            tool_name=tool_call.function_name,
            tool_arguments=arguments,
        )
        task_order.append(tool_call.call_id)
        tasks.append(
            asyncio.create_task(
                _execute_tool_call_with_timeout(
                    tool_call,
                    repository=repository,
                    file_tree=file_tree,
                    on_activity=_tool_activity,
                    timeouts=timeouts,
                )
            )
        )

    pending = list(tasks)
    while pending:
        done, pending_set = await asyncio.wait(
            pending,
            timeout=0.05,
            return_when=asyncio.FIRST_COMPLETED,
        )
        while not activity_queue.empty():
            yield activity_queue.get_nowait()
        pending = list(pending_set)
        if not done:
            continue

    while not activity_queue.empty():
        yield activity_queue.get_nowait()

    results = await asyncio.gather(*tasks)
    ordered = sorted(results, key=lambda item: task_order.index(item.tool_call.call_id))
    for result in ordered:
        yield result


async def _stream_final_answer_without_tools(
    messages: list[dict[str, Any]],
    *,
    tool_streamer: ToolAwareLlmStreamer,
    on_activity: ActivityEmitter | None,
    round_index: int,
    max_tokens: int,
) -> AsyncIterator[ToolStreamItem]:
    queue: asyncio.Queue[ToolStreamItem | None] = asyncio.Queue()
    round_started_at = monotonic()
    emitted_chunks: list[str] = []

    async def _on_delta(chunk: str) -> None:
        emitted_chunks.append(chunk)
        await queue.put(ToolStreamTextDelta(chunk))

    async def _runner() -> StreamResult:
        try:
            return await _call_tool_streamer(
                tool_streamer,
                messages,
                tools=[],
                on_content_delta=_on_delta,
                max_tokens=max_tokens,
            )
        finally:
            await queue.put(None)

    runner_task = asyncio.create_task(_runner())
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
        result = await runner_task
    except BaseException:
        runner_task.cancel()
        try:
            await runner_task
        except BaseException:
            pass
        raise

    if not emitted_chunks and result.content_chunks:
        for chunk in result.content_chunks:
            yield ToolStreamTextDelta(chunk)

    if result.tool_calls:
        yield await _make_activity_item(
            on_activity,
            round_started_at,
            round_index,
            "degraded_continue",
            "The model still requested tools during the final no-tool round.",
        )


async def _make_activity_item(
    on_activity: ActivityEmitter | None,
    round_started_at: float,
    round_index: int,
    phase: str,
    summary: str,
    **extra: Any,
) -> ToolStreamActivity:
    payload = {
        "phase": phase,
        "summary": summary,
        "round_index": round_index + 1,
        "elapsed_ms": int((monotonic() - round_started_at) * 1000),
    }
    payload.update(extra)
    recorded_event = None
    if on_activity is not None:
        recorded_event = await _maybe_await(on_activity(**payload))
    return ToolStreamActivity(payload=payload, recorded_event=recorded_event)


def _normalize_tool_calls(tool_calls: list[ToolCallRequest], round_index: int) -> list[ToolCallRequest]:
    normalized: list[ToolCallRequest] = []
    for index, tool_call in enumerate(tool_calls, start=1):
        normalized.append(
            ToolCallRequest(
                call_id=tool_call.call_id or f"call_local_{round_index + 1}_{index}",
                function_name=api_tool_name(tool_call.function_name or "__missing_tool_name"),
                arguments_json=tool_call.arguments_json or "{}",
            )
        )
    return normalized


async def _call_tool_streamer(
    tool_streamer: ToolAwareLlmStreamer,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]],
    on_content_delta: Any,
    max_tokens: int,
) -> StreamResult:
    kwargs: dict[str, Any] = {"tools": tools, "on_content_delta": on_content_delta}
    if _accepts_kwarg(tool_streamer, "max_tokens"):
        kwargs["max_tokens"] = max_tokens
    return await tool_streamer(messages, **kwargs)


def _accepts_kwarg(func: Any, name: str) -> bool:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return True
    return any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD or parameter.name == name
        for parameter in signature.parameters.values()
    )


async def _emit_after(
    delay_seconds: float,
    emitter: ActivityEmitter,
    phase: str,
    summary: str,
) -> None:
    try:
        await asyncio.sleep(delay_seconds)
        await _maybe_await(emitter(phase, summary))
    except asyncio.CancelledError:
        raise


async def _maybe_await(result: Any) -> Any:
    if asyncio.iscoroutine(result):
        return await result
    return result


async def _execute_tool_call_with_timeout(
    tool_call: ToolCallRequest,
    *,
    repository: RepositoryContext,
    file_tree: FileTreeSnapshot,
    on_activity: ActivityEmitter,
    timeouts: ToolLoopTimeouts,
) -> _ToolExecution:
    arguments = _safe_json_loads(tool_call.arguments_json)
    started_at = monotonic()
    tool_task = asyncio.create_task(
        asyncio.to_thread(
            execute_tool_call,
            tool_call.function_name,
            arguments,
            repository=repository,
            file_tree=file_tree,
        )
    )
    soft_timeout_fired = False

    try:
        done, _ = await asyncio.wait({tool_task}, timeout=timeouts.tool_soft_timeout_seconds)
        if not done:
            soft_timeout_fired = True
            await _maybe_await(
                on_activity(
                    "slow_warning",
                    f"{tool_call.function_name} is taking longer than expected.",
                    tool_name=tool_call.function_name,
                    tool_arguments=arguments,
                    soft_timed_out=True,
                    elapsed_ms=int((monotonic() - started_at) * 1000),
                )
            )
            done, _ = await asyncio.wait(
                {tool_task},
                timeout=max(
                    0.0,
                    timeouts.tool_hard_timeout_seconds - timeouts.tool_soft_timeout_seconds,
                ),
            )
            if not done:
                tool_task.cancel()
                await _maybe_await(
                    on_activity(
                        "tool_failed",
                        f"{tool_call.function_name} timed out.",
                        tool_name=tool_call.function_name,
                        tool_arguments=arguments,
                        failed=True,
                        soft_timed_out=soft_timeout_fired,
                        elapsed_ms=int((monotonic() - started_at) * 1000),
                    )
                )
                return _ToolExecution(
                    tool_call=tool_call,
                    tool_output=_tool_failure_payload(
                        tool_call.function_name,
                        arguments,
                        reason="tool_timeout",
                        detail="Tool call timed out.",
                        elapsed_ms=int((monotonic() - started_at) * 1000),
                        soft_timed_out=soft_timeout_fired,
                    ),
                    degraded=True,
                )
        return _ToolExecution(
            tool_call=tool_call,
            tool_output=await tool_task,
            degraded=False,
        )
    except Exception as exc:
        await _maybe_await(
            on_activity(
                "tool_failed",
                f"{tool_call.function_name} failed.",
                tool_name=tool_call.function_name,
                tool_arguments=arguments,
                failed=True,
                soft_timed_out=soft_timeout_fired,
                elapsed_ms=int((monotonic() - started_at) * 1000),
            )
        )
        return _ToolExecution(
            tool_call=tool_call,
            tool_output=_tool_failure_payload(
                tool_call.function_name,
                arguments,
                reason="tool_execution_failed",
                detail=str(exc),
                elapsed_ms=int((monotonic() - started_at) * 1000),
                soft_timed_out=soft_timeout_fired,
            ),
            degraded=True,
        )


def _tool_failure_payload(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    reason: str,
    detail: str,
    elapsed_ms: int,
    soft_timed_out: bool,
) -> str:
    return json.dumps(
        {
            "tool_name": tool_name,
            "available": False,
            "degraded": True,
            "reason": reason,
            "detail": detail,
            "arguments": arguments,
            "elapsed_ms": elapsed_ms,
            "soft_timed_out": soft_timed_out,
        },
        ensure_ascii=False,
    )


def _safe_json_loads(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _tool_summary(tool_name: str, arguments_json: str) -> str:
    normalized_name = normalize_tool_name(tool_name)
    arguments = _safe_json_loads(arguments_json)
    if normalized_name == "search_text":
        query = str(arguments.get("query") or "").strip()
        return f"Searching source files for {query!r}" if query else "Searching source files"
    if normalized_name == "read_file_excerpt":
        path = str(arguments.get("relative_path") or "").strip()
        return f"Reading {path}" if path else "Reading a source excerpt"
    if normalized_name == "m2.list_relevant_files":
        return "Listing relevant repository files"
    if normalized_name == "m2.get_file_tree_summary":
        return "Reviewing the file-tree summary"
    if normalized_name == "m1.get_repository_context":
        return "Reviewing repository context"
    return f"Running {normalized_name}"
