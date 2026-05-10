"""BaseAgent extension for deep_research's four agents.

Adds two utilities the kernel ``BaseAgent`` does not need:
  - ``parse_strict_json``: tolerant JSON extraction (strips Markdown fences, retries
    with the first balanced ``{...}`` slice) so Decomposer / Investigator can safely
    fall back when the LLM wraps its output in fences or stray prose.
  - ``aggregate_chunks``: regroups an LLM stream into batches of ~N tokens so the
    orchestrator can perform cancellation checks on a stable cadence
    (see AGENTS.md §5 cancellation list).

This file does NOT touch tools, scratchpad, or events; it only widens BaseAgent.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from ...agents.base_agent import BaseAgent


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]+?)\s*```", re.IGNORECASE)


class BaseResearchAgent(BaseAgent):
    """BaseAgent extension shared by Decomposer / Investigator / NoteTaker / Composer."""

    def parse_strict_json(self, text: str, fallback: Any) -> Any:
        if not text:
            return fallback
        candidate = text.strip()
        match = _JSON_FENCE_RE.search(candidate)
        if match:
            candidate = match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        # Last-resort: take the first balanced {...} slice.
        opener = candidate.find("{")
        closer = candidate.rfind("}")
        if 0 <= opener < closer:
            try:
                return json.loads(candidate[opener:closer + 1])
            except json.JSONDecodeError:
                return fallback
        return fallback

    @staticmethod
    async def aggregate_chunks(
        stream: AsyncIterator[str],
        *,
        group_size: int = 6,
    ) -> AsyncIterator[str]:
        buffer: list[str] = []
        size = 0
        async for chunk in stream:
            if not chunk:
                continue
            buffer.append(chunk)
            size += 1
            if size >= group_size:
                yield "".join(buffer)
                buffer.clear()
                size = 0
        if buffer:
            yield "".join(buffer)


__all__ = ["BaseResearchAgent"]
