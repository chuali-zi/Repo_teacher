from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from backend.contracts.domain import (
    FileTreeSnapshot,
    InitialReportAnswer,
    PromptBuildInput,
    RepositoryContext,
    StructuredAnswer,
)
from backend.m6_response.llm_caller import (
    StreamResult,
    stream_llm_response,
    stream_llm_response_with_tools,
)
from backend.m6_response.prompt_builder import build_messages
from backend.m6_response.response_parser import parse_final_answer
from backend.m6_response.tool_executor import TOOL_SCHEMAS, execute_tool_call

LlmStreamer = Callable[[list[dict[str, str]]], AsyncIterator[str]]

ToolAwareLlmStreamer = Callable[
    ...,
    Any,
]


async def stream_answer_text(
    input_data: PromptBuildInput,
    *,
    llm_streamer: LlmStreamer = stream_llm_response,
) -> AsyncIterator[str]:
    """Original one-shot streaming path (no function calling)."""
    messages = build_messages(input_data)
    async for chunk in llm_streamer(messages):
        yield chunk


async def stream_answer_text_with_tools(
    input_data: PromptBuildInput,
    *,
    repository: RepositoryContext,
    file_tree: FileTreeSnapshot,
    tool_streamer: ToolAwareLlmStreamer = stream_llm_response_with_tools,
) -> AsyncIterator[str]:
    """Streaming path with tool-calling loop.

    Yields visible text chunks to the caller in real-time. When the LLM
    requests tool calls, executes them locally and feeds results back,
    continuing for up to *input_data.max_tool_rounds* iterations.
    """
    messages: list[dict[str, Any]] = build_messages(input_data)
    max_rounds = input_data.max_tool_rounds

    for _round in range(max_rounds + 1):
        collected_chunks: list[str] = []

        async def _on_delta(chunk: str) -> None:
            collected_chunks.append(chunk)

        result: StreamResult = await tool_streamer(
            messages,
            tools=TOOL_SCHEMAS,
            on_content_delta=_on_delta,
        )

        for chunk in result.content_chunks:
            yield chunk

        if not result.tool_calls or result.finish_reason != "tool_calls":
            return

        assistant_msg: dict[str, Any] = {"role": "assistant"}
        full_content = "".join(result.content_chunks)
        if full_content:
            assistant_msg["content"] = full_content
        assistant_msg["tool_calls"] = [
            {
                "id": tc.call_id,
                "type": "function",
                "function": {
                    "name": tc.function_name,
                    "arguments": tc.arguments_json,
                },
            }
            for tc in result.tool_calls
        ]
        messages.append(assistant_msg)

        for tc in result.tool_calls:
            try:
                arguments = json.loads(tc.arguments_json)
            except json.JSONDecodeError:
                arguments = {}

            tool_output = execute_tool_call(
                tc.function_name,
                arguments,
                repository=repository,
                file_tree=file_tree,
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.call_id,
                    "content": tool_output,
                }
            )


def parse_answer(
    input_data: PromptBuildInput,
    raw_text: str,
) -> StructuredAnswer | InitialReportAnswer:
    return parse_final_answer(input_data.scenario, raw_text)
