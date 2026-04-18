from __future__ import annotations

import json
from typing import Any

from backend.contracts.domain import LlmToolResult


def _truncate_value(
    value: Any,
    *,
    max_string_chars: int,
    max_list_items: int,
    max_dict_items: int,
    max_depth: int,
    _depth: int = 0,
) -> Any:
    if _depth >= max_depth:
        if isinstance(value, (dict, list)):
            return "[truncated_depth]"
        if isinstance(value, str) and len(value) > max_string_chars:
            return value[:max_string_chars] + "...[truncated]"
        return value
    if isinstance(value, dict):
        items = list(value.items())[:max_dict_items]
        clipped = {
            key: _truncate_value(
                item,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
                max_dict_items=max_dict_items,
                max_depth=max_depth,
                _depth=_depth + 1,
            )
            for key, item in items
        }
        if len(value) > max_dict_items:
            clipped["_truncated_dict_items"] = len(value) - max_dict_items
        return clipped
    if isinstance(value, list):
        items = [
            _truncate_value(
                item,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
                max_dict_items=max_dict_items,
                max_depth=max_depth,
                _depth=_depth + 1,
            )
            for item in value[:max_list_items]
        ]
        if len(value) > max_list_items:
            items.append({"_truncated_list_items": len(value) - max_list_items})
        return items
    if isinstance(value, str) and len(value) > max_string_chars:
        return value[:max_string_chars] + "...[truncated]"
    return value


def truncate_tool_result(
    result: LlmToolResult,
    *,
    max_chars: int = 9000,
) -> tuple[LlmToolResult, bool]:
    base_payload = {
        "tool_name": result.tool_name,
        "summary": result.summary,
        **result.payload,
    }
    raw = json.dumps(base_payload, ensure_ascii=False, default=str)
    if len(raw) <= max_chars:
        return result, False

    presets = (
        (480, 16, 24, 6),
        (320, 12, 18, 5),
        (240, 8, 14, 4),
        (160, 6, 10, 3),
    )
    for max_string_chars, max_list_items, max_dict_items, max_depth in presets:
        candidate = _truncate_value(
            result.payload,
            max_string_chars=max_string_chars,
            max_list_items=max_list_items,
            max_dict_items=max_dict_items,
            max_depth=max_depth,
        )
        candidate_result = result.model_copy(
            update={
                "payload": {
                    **candidate,
                    "truncated": True,
                    "truncation_notice": "tool payload was clipped to fit the LLM context budget",
                }
            }
        )
        candidate_raw = json.dumps(
            {
                "tool_name": candidate_result.tool_name,
                "summary": candidate_result.summary,
                **candidate_result.payload,
            },
            ensure_ascii=False,
            default=str,
        )
        if len(candidate_raw) <= max_chars:
            return candidate_result, True

    minimal = result.model_copy(
        update={
            "payload": {
                "truncated": True,
                "payload_keys": list(result.payload.keys())[:12],
                "payload_summary": json.dumps(
                    _truncate_value(
                        result.payload,
                        max_string_chars=120,
                        max_list_items=4,
                        max_dict_items=8,
                        max_depth=3,
                    ),
                    ensure_ascii=False,
                    default=str,
                )[: max_chars // 2],
            }
        }
    )
    return minimal, True


def serialize_tool_result(result: LlmToolResult, *, max_chars: int = 9000) -> str:
    clipped, was_truncated = truncate_tool_result(result, max_chars=max_chars)
    payload = {
        "tool_name": clipped.tool_name,
        "summary": clipped.summary,
        **clipped.payload,
    }
    if was_truncated and "truncated" not in payload:
        payload["truncated"] = True
    return json.dumps(payload, ensure_ascii=False, default=str)
