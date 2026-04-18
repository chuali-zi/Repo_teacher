from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from time import monotonic
from typing import Any

from backend.contracts.domain import (
    AnalysisBundle,
    FileTreeSnapshot,
    PromptBuildInput,
    RepositoryContext,
    TeachingSkeleton,
)
from backend.m6_response.llm_caller import StreamResult, ToolCallRequest, stream_llm_response_with_tools
from backend.m6_response.prompt_builder import build_messages
from backend.m6_response.tool_executor import TOOL_SCHEMAS, execute_tool_call, normalize_tool_name

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
    analysis: AnalysisBundle | None = None,
    teaching_skeleton: TeachingSkeleton | None = None,
    tool_streamer: ToolAwareLlmStreamer = stream_llm_response_with_tools,
    on_activity: ActivityEmitter | None = None,
    timeouts: ToolLoopTimeouts = DEFAULT_TOOL_LOOP_TIMEOUTS,
) -> AsyncIterator[ToolStreamItem]:
    messages: list[dict[str, Any]] = build_messages(input_data)
    max_rounds = input_data.max_tool_rounds

    for round_index in range(max_rounds + 1):
        queue: asyncio.Queue[ToolStreamItem | None] = asyncio.Queue()
        round_started_at = monotonic()
        saw_visible_content = False
        emitted_text_chunks: list[str] = []

        async def _emit_activity(
            phase: str,
            summary: str,
            **extra: Any,
        ) -> ToolStreamActivity:
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
                "正在梳理你的问题与已有上下文",
            )
        )
        search_task = asyncio.create_task(
            _emit_after(
                timeouts.code_search_notice_seconds,
                _emit_activity,
                "slow_warning",
                "正在定位相关代码与证据",
            )
        )

        async def _on_delta(chunk: str) -> None:
            emitted_text_chunks.append(chunk)
            await queue.put(ToolStreamTextDelta(chunk))

        async def _runner() -> StreamResult:
            try:
                return await tool_streamer(
                    messages,
                    tools=TOOL_SCHEMAS,
                    on_content_delta=_on_delta,
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
                    saw_visible_content = True
                yield item
            result: StreamResult = await runner_task
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

        if not emitted_text_chunks and result.content_chunks:
            for chunk in result.content_chunks:
                saw_visible_content = True
                yield ToolStreamTextDelta(chunk)

        if not result.tool_calls:
            return

        tool_calls = _normalize_tool_calls(result.tool_calls, round_index)
        if not saw_visible_content:
            yield await _make_activity_item(
                on_activity,
                round_started_at,
                round_index,
                "planning_tool_call",
                "正在决定要查看哪些代码证据",
            )

        full_content = "".join(result.content_chunks)
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": tc.call_id,
                    "type": "function",
                    "function": {
                        "name": tc.function_name,
                        "arguments": tc.arguments_json,
                    },
                }
                for tc in tool_calls
            ],
        }
        if full_content:
            assistant_msg["content"] = full_content
        messages.append(assistant_msg)

        async for activity in _execute_tool_batch(
            tool_calls,
            round_started_at=round_started_at,
            round_index=round_index,
            repository=repository,
            file_tree=file_tree,
            analysis=analysis,
            teaching_skeleton=teaching_skeleton,
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
                            "刚才的工具调用失败或超时。请不要继续等待该工具；"
                            "改用已有工具结果和上下文保守回答，并明确标注不确定性。"
                        ),
                    }
                )
                yield await _make_activity_item(
                    on_activity,
                    round_started_at,
                    round_index,
                    "degraded_continue",
                    "工具不可用，改为基于已有证据继续回答",
                )
            else:
                arguments = _safe_json_loads(activity.tool_call.arguments_json)
                yield await _make_activity_item(
                    on_activity,
                    round_started_at,
                    round_index,
                    "tool_succeeded",
                    f"{activity.tool_call.function_name} 已返回，继续组织回答",
                    tool_name=activity.tool_call.function_name,
                    tool_arguments=arguments,
                )

        if round_index < max_rounds:
            yield await _make_activity_item(
                on_activity,
                round_started_at,
                round_index,
                "waiting_llm_after_tool",
                "已拿到工具结果，正在组织回答",
            )
            continue

        messages.append(
            {
                "role": "system",
                "content": "工具调用轮次已达上限。接下来直接完成回答，不要再调用工具。",
            }
        )
        yield await _make_activity_item(
            on_activity,
            round_started_at,
            round_index,
            "degraded_continue",
            "已达到工具轮次上限，直接完成回答",
        )
        async for item in _stream_final_answer_without_tools(
            messages,
            tool_streamer=tool_streamer,
            on_activity=on_activity,
            round_index=round_index + 1,
        ):
            yield item
        return


async def _execute_tool_batch(
    tool_calls: list[ToolCallRequest],
    *,
    round_started_at: float,
    round_index: int,
    repository: RepositoryContext,
    file_tree: FileTreeSnapshot,
    analysis: AnalysisBundle | None,
    teaching_skeleton: TeachingSkeleton | None,
    on_activity: ActivityEmitter | None,
    timeouts: ToolLoopTimeouts,
) -> AsyncIterator[ToolStreamActivity | _ToolExecution]:
    activity_queue: asyncio.Queue[ToolStreamActivity] = asyncio.Queue()
    task_order: list[str] = []
    tasks: list[asyncio.Task[_ToolExecution]] = []

    async def _tool_activity(
        phase: str,
        summary: str,
        **extra: Any,
    ) -> None:
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
                    analysis=analysis,
                    teaching_skeleton=teaching_skeleton,
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
    ordered = sorted(
        results,
        key=lambda item: task_order.index(item.tool_call.call_id),
    )
    for result in ordered:
        yield result


async def _stream_final_answer_without_tools(
    messages: list[dict[str, Any]],
    *,
    tool_streamer: ToolAwareLlmStreamer,
    on_activity: ActivityEmitter | None,
    round_index: int,
) -> AsyncIterator[ToolStreamItem]:
    queue: asyncio.Queue[ToolStreamItem | None] = asyncio.Queue()
    round_started_at = monotonic()
    emitted_text_chunks: list[str] = []

    async def _on_delta(chunk: str) -> None:
        emitted_text_chunks.append(chunk)
        await queue.put(ToolStreamTextDelta(chunk))

    async def _runner() -> StreamResult:
        try:
            return await tool_streamer(
                messages,
                tools=[],
                on_content_delta=_on_delta,
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

    if not emitted_text_chunks and result.content_chunks:
        for chunk in result.content_chunks:
            yield ToolStreamTextDelta(chunk)

    if result.tool_calls:
        yield await _make_activity_item(
            on_activity,
            round_started_at,
            round_index,
            "degraded_continue",
            "模型在最终轮仍请求工具，已忽略并结束本轮工具循环",
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


def _normalize_tool_calls(
    tool_calls: list[ToolCallRequest],
    round_index: int,
) -> list[ToolCallRequest]:
    normalized: list[ToolCallRequest] = []
    for index, tc in enumerate(tool_calls, start=1):
        normalized.append(
            ToolCallRequest(
                call_id=tc.call_id or f"call_local_{round_index + 1}_{index}",
                function_name=normalize_tool_name(tc.function_name or "__missing_tool_name"),
                arguments_json=tc.arguments_json or "{}",
            )
        )
    return normalized


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
    analysis: AnalysisBundle | None,
    teaching_skeleton: TeachingSkeleton | None,
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
            analysis=analysis,
            teaching_skeleton=teaching_skeleton,
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
                    f"{tool_call.function_name} 用时较久，继续等待一小段时间",
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
                        f"{tool_call.function_name} 超时，改用已有证据继续回答",
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
                        detail="工具调用超时",
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
                f"{tool_call.function_name} 失败，改用已有证据继续回答",
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
    arguments = _safe_json_loads(arguments_json)
    if tool_name == "get_repo_surfaces":
        return f"正在查看仓库分区（{arguments.get('mode', 'teaching')} 模式）"
    if tool_name == "get_entry_candidates":
        return f"正在核对入口候选（{arguments.get('mode', 'teaching')} 模式）"
    if tool_name == "get_module_map":
        return f"正在整理模块地图（{arguments.get('mode', 'teaching')} 模式）"
    if tool_name == "get_reading_path":
        goal = str(arguments.get("goal") or "当前目标").strip()
        return f"正在生成 {goal} 的阅读路径"
    if tool_name == "get_evidence":
        target = str(arguments.get("target") or "当前结论").strip()
        return f"正在收集 {target} 的证据"
    if tool_name == "search_text":
        query = str(arguments.get("query") or "").strip()
        return f"正在搜索 {query!r} 相关代码" if query else "正在搜索相关代码"
    if tool_name == "read_file_excerpt":
        path = str(arguments.get("relative_path") or "").strip()
        return f"正在读取 {path} 的代码摘录" if path else "正在读取代码摘录"
    return f"正在执行 {tool_name}"
