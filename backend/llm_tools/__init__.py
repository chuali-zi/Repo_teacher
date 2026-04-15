"""LLM-facing read-only tool layer for repository tutoring.

The tools in this package wrap deterministic M1-M4 outputs and a small set of
safe repository readers. They do not call an LLM and they do not mutate session
or repository state.
"""

from backend.llm_tools.context_builder import (
    build_llm_tool_context,
    read_file_excerpt,
    search_text,
    tool_definitions,
)

__all__ = [
    "build_llm_tool_context",
    "read_file_excerpt",
    "search_text",
    "tool_definitions",
]
