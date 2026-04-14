from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from backend.contracts.domain import InitialReportAnswer, PromptBuildInput, StructuredAnswer
from backend.m6_response.llm_caller import stream_llm_response
from backend.m6_response.prompt_builder import build_messages
from backend.m6_response.response_parser import parse_final_answer

LlmStreamer = Callable[[list[dict[str, str]]], AsyncIterator[str]]


async def stream_answer_text(
    input_data: PromptBuildInput,
    *,
    llm_streamer: LlmStreamer = stream_llm_response,
) -> AsyncIterator[str]:
    messages = build_messages(input_data)
    async for chunk in llm_streamer(messages):
        yield chunk


def parse_answer(
    input_data: PromptBuildInput,
    raw_text: str,
) -> StructuredAnswer | InitialReportAnswer:
    return parse_final_answer(input_data.scenario, raw_text)
