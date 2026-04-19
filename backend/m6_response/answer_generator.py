from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Callable
from typing import Any

from backend.agent_runtime.tool_loop import (
    DEFAULT_TOOL_LOOP_TIMEOUTS,
    ToolLoopTimeouts,
    ToolStreamActivity,
    ToolStreamItem,
    ToolStreamTextDelta,
    stream_answer_text_with_tools,
)
from backend.contracts.domain import InitialReportAnswer, PromptBuildInput, StructuredAnswer
from backend.contracts.enums import PromptScenario
from backend.m6_response.llm_caller import stream_llm_response
from backend.m6_response.prompt_builder import build_messages
from backend.m6_response.response_parser import parse_final_answer

LlmStreamer = Callable[..., AsyncIterator[str]]
ToolAwareLlmStreamer = Callable[..., object]

OUTPUT_TOKEN_BUDGETS: dict[PromptScenario, int] = {
    PromptScenario.INITIAL_REPORT: 2400,
    PromptScenario.FOLLOW_UP: 1400,
    PromptScenario.GOAL_SWITCH: 1400,
    PromptScenario.DEPTH_ADJUSTMENT: 1000,
    PromptScenario.STAGE_SUMMARY: 1200,
}


async def stream_answer_text(
    input_data: PromptBuildInput,
    *,
    llm_streamer: LlmStreamer = stream_llm_response,
) -> AsyncIterator[str]:
    messages = build_messages(input_data)
    max_tokens = output_token_budget(input_data)
    stream = _call_with_optional_max_tokens(llm_streamer, messages, max_tokens=max_tokens)
    async for chunk in stream:
        yield chunk


def parse_answer(
    input_data: PromptBuildInput,
    raw_text: str,
) -> StructuredAnswer | InitialReportAnswer:
    return parse_final_answer(input_data.scenario, raw_text)


def output_token_budget(input_data: PromptBuildInput) -> int:
    return OUTPUT_TOKEN_BUDGETS.get(input_data.scenario, 1400)


def _call_with_optional_max_tokens(
    streamer: LlmStreamer,
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
) -> AsyncIterator[str]:
    if _accepts_kwarg(streamer, "max_tokens"):
        return streamer(messages, max_tokens=max_tokens)
    return streamer(messages)


def _accepts_kwarg(func: Any, name: str) -> bool:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return True
    return any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD or parameter.name == name
        for parameter in signature.parameters.values()
    )


__all__ = [
    "DEFAULT_TOOL_LOOP_TIMEOUTS",
    "LlmStreamer",
    "ToolAwareLlmStreamer",
    "ToolLoopTimeouts",
    "ToolStreamActivity",
    "ToolStreamItem",
    "ToolStreamTextDelta",
    "parse_answer",
    "output_token_budget",
    "stream_answer_text",
    "stream_answer_text_with_tools",
]
