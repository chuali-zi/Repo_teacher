"""Phase 2 NoteTaker: turn one tool round's observation into a teaching note.

This agent runs as the second LLM call inside each ReAct round (AGENTS.md §3.3).
It does NOT output JSON, does NOT pick the next tool, and does NOT touch the
scratchpad — the orchestrator (SA-07 ``DeepResearchLoop``) is responsible for
persistence. Output is a short natural-language ``SubtopicNote`` written in the
teacher voice from §7.2; the sanitizer here strips any leaked JSON / tool jargon
(``tool_call``, ``ToolResult``, ``action_input`` …) before returning, and
hard-caps the text at 600 characters per §3.3 so a runaway LLM cannot blow past
the per-sub-topic budget defined in §12.3.
"""

from __future__ import annotations

import json
from typing import Any

from ..research_scratchpad import SubtopicMeta, SubtopicNote
from .base_research_agent import BaseResearchAgent


_MAX_NOTE_CHARS = 600
_MAX_TOOL_INPUT_REPR = 200
_JARGON_TOKENS = ("tool_call", "ToolResult", "action_input", '"action"', "json", "JSON")
_JSON_FALLBACK_NOTE = "这一轮素材没产出可读的笔记，可能需要换个支点再看一次。"


class NoteTaker(BaseResearchAgent):
    """Compose one round's teaching note; never raises on bad LLM output."""

    def __init__(self, *, llm_client: Any, prompt_manager: Any, agent_name: str = "note") -> None:
        super().__init__(agent_name=agent_name, llm_client=llm_client, prompt_manager=prompt_manager)

    async def process(
        self,
        *,
        subtopic: SubtopicMeta,
        intent: str,
        tool_action: str,
        tool_input: dict,
        observation: str,
        success: bool,
    ) -> SubtopicNote:
        """Render one teaching note + anchor metadata for a single ReAct round."""

        anchor_path, anchor_lines = _infer_anchor(tool_action, tool_input)
        template = self.get_prompt("user_template")
        user_prompt = template.format(
            subtopic_id=subtopic.id,
            subtopic_title=subtopic.title,
            intent=intent or "（未填写）",
            tool_action=tool_action,
            tool_input=_render_tool_input(tool_input),
            observation=observation,
            success="成功" if success else "失败",
        )
        raw = await self.call_llm(
            user_prompt,
            system_prompt=self.get_prompt("system"),
            temperature=0.4,
            # FIX-08: 2.5× of 500 per user request to avoid mid-output truncation.
            max_tokens=1250,
        )
        text = _sanitize_note(raw, success=success, subtopic=subtopic, tool_input=tool_input)
        return SubtopicNote(text=text, success=success, anchor_path=anchor_path, anchor_lines=anchor_lines)


def _infer_anchor(
    tool_action: str,
    tool_input: dict,
) -> tuple[str | None, tuple[int, int] | None]:
    if not isinstance(tool_input, dict):
        return None, None
    raw_path = tool_input.get("path")
    path = raw_path if isinstance(raw_path, str) else None
    if tool_action == "read_file_range" and path:
        start = tool_input.get("start_line")
        end = tool_input.get("end_line")
        if isinstance(start, int) and isinstance(end, int):
            return path, (start, end)
        return path, None
    if tool_action in {"summarize_file", "list_dir"} and path:
        return path, None
    return None, None


def _render_tool_input(tool_input: dict) -> str:
    try:
        rendered = json.dumps(tool_input, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        rendered = str(tool_input)
    if len(rendered) > _MAX_TOOL_INPUT_REPR:
        rendered = rendered[: _MAX_TOOL_INPUT_REPR - 1] + "…"
    return rendered


def _looks_like_json_blob(text: str) -> bool:
    """JSON envelope OR fenced block that mentions tool jargon."""

    if text.startswith("{") and text.endswith("}"):
        return True
    if text.startswith("```") and any(token in text for token in _JARGON_TOKENS):
        return True
    return False


def _sanitize_note(
    raw: str,
    *,
    success: bool,
    subtopic: SubtopicMeta,
    tool_input: dict,
) -> str:
    candidate = (raw or "").strip()
    if candidate and _looks_like_json_blob(candidate):
        candidate = _JSON_FALLBACK_NOTE
    if len(candidate) > _MAX_NOTE_CHARS:
        candidate = candidate[:_MAX_NOTE_CHARS]
    if candidate:
        return candidate
    if success:
        return f"读了下{subtopic.title}相关的位置，没看到特别突出的细节，先走下一步。"
    path = tool_input.get("path") if isinstance(tool_input, dict) else None
    target = path if isinstance(path, str) and path else "相关位置"
    return f"这次读{target}没拿到东西，可能要换个入口。"


__all__ = ["NoteTaker"]
