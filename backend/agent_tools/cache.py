from __future__ import annotations

import json
from collections import OrderedDict

from backend.agent_tools.base import ToolContext
from backend.contracts.domain import LlmToolResult


def _scope_for_context(ctx: ToolContext) -> str:
    if ctx.analysis is not None:
        return ctx.analysis.bundle_id
    return ctx.file_tree.snapshot_id


class ToolResultCache:
    def __init__(self, *, max_entries: int = 512) -> None:
        self._max_entries = max_entries
        self._store: OrderedDict[str, LlmToolResult] = OrderedDict()

    def build_key(self, tool_name: str, arguments: dict, ctx: ToolContext) -> str:
        payload = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
        return f"{_scope_for_context(ctx)}::{tool_name}::{payload}"

    def get(self, tool_name: str, arguments: dict, ctx: ToolContext) -> LlmToolResult | None:
        key = self.build_key(tool_name, arguments, ctx)
        result = self._store.get(key)
        if result is None:
            return None
        self._store.move_to_end(key)
        return result

    def set(
        self,
        tool_name: str,
        arguments: dict,
        ctx: ToolContext,
        result: LlmToolResult,
    ) -> None:
        key = self.build_key(tool_name, arguments, ctx)
        self._store[key] = result
        self._store.move_to_end(key)
        while len(self._store) > self._max_entries:
            self._store.popitem(last=False)


GLOBAL_TOOL_RESULT_CACHE = ToolResultCache()
