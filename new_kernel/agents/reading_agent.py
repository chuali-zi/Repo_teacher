"""ReadingAgent produces one ReAct read decision without executing tools."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..memory.scratchpad import ReadEntry, ReadingStep
from .base_agent import BaseAgent


@dataclass(frozen=True)
class ReadingDecision:
    """A single read-stage action decision."""

    thought: str
    action: str
    action_input: dict[str, Any] = field(default_factory=dict)
    self_note: str = ""


class ReadingAgent(BaseAgent):
    """Choose the next read-only tool action for a current ReadingStep."""

    def __init__(self, *, llm_client: Any | None = None, prompt_manager: Any | None = None) -> None:
        super().__init__(agent_name="read", llm_client=llm_client, prompt_manager=prompt_manager)

    async def process(
        self,
        *,
        question: str,
        current_step: ReadingStep,
        step_history: list[ReadEntry],
        previous_steps_summary: str,
        valid_actions: frozenset[str],
        tool_descriptions: str,
    ) -> ReadingDecision:
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            question=question,
            current_step=current_step,
            step_history=step_history,
            previous_steps_summary=previous_steps_summary,
            tool_descriptions=tool_descriptions,
        )
        response = await self.call_llm(
            user_prompt,
            system_prompt=system_prompt,
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=900,
        )
        return self._parse_decision(response, valid_actions=valid_actions)

    def _build_system_prompt(self) -> str:
        return self.get_prompt("system", fallback=_DEFAULT_SYSTEM_PROMPT)

    def _build_user_prompt(
        self,
        *,
        question: str,
        current_step: ReadingStep,
        step_history: list[ReadEntry],
        previous_steps_summary: str,
        tool_descriptions: str,
    ) -> str:
        template = self.get_prompt("user_template", fallback=_DEFAULT_USER_TEMPLATE)
        return _safe_format(
            template,
            question=question,
            current_step=_format_step(current_step),
            step_history=_format_history(step_history),
            previous_steps=previous_steps_summary or "(none)",
            tools_description=tool_descriptions or "(no tools available)",
        )

    def _parse_decision(
        self,
        response: str,
        *,
        valid_actions: frozenset[str],
    ) -> ReadingDecision:
        payload = _extract_json_object(response)
        if not payload:
            return _done("无法解析 ReadingAgent 输出，安全结束当前 step。")

        raw_action = _clean_text(payload.get("action") or "done")
        action = raw_action if raw_action in valid_actions else raw_action.lower()
        if action not in valid_actions:
            return ReadingDecision(
                thought=_clean_text(payload.get("thought")),
                action="done",
                action_input={},
                self_note="模型选择了不可用 action，已降级为 done。",
            )

        action_input = _coerce_action_input(payload.get("action_input"))
        if action == "done":
            action_input = {}

        return ReadingDecision(
            thought=_clean_text(payload.get("thought")),
            action=action,
            action_input=action_input,
            self_note=_clean_text(payload.get("self_note")),
        )


def _done(note: str) -> ReadingDecision:
    return ReadingDecision(thought=note, action="done", action_input={}, self_note=note)


def _coerce_action_input(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return {}
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, Mapping):
            return {str(key): _plain_value(item) for key, item in parsed.items()}
    return {}


def _plain_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain_value(item) for item in value]
    if isinstance(value, tuple):
        return [_plain_value(item) for item in value]
    return value


def _extract_json_object(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    for candidate in (cleaned, _between_braces(cleaned)):
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _between_braces(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return ""
    return text[start : end + 1]


def _format_step(step: ReadingStep) -> str:
    lines = [f"step_id: {step.step_id}", f"goal: {step.goal}"]
    if step.anchors:
        lines.append("anchors:")
        for anchor in step.anchors:
            why = f" - {anchor.why}" if anchor.why else ""
            lines.append(f"- {anchor.path}{why}")
    return "\n".join(lines)


def _format_history(entries: list[ReadEntry]) -> str:
    if not entries:
        return "(none)"
    parts: list[str] = []
    for entry in entries:
        lines = [
            f"round: {entry.round_index}",
            f"action: {entry.action}",
            f"tool_success: {entry.tool_success}",
        ]
        if entry.action_input:
            lines.append(f"action_input: {entry.action_input}")
        if entry.self_note:
            lines.append(f"self_note: {entry.self_note}")
        if entry.observation:
            lines.append(f"observation:\n{entry.observation}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _safe_format(template: str, **values: str) -> str:
    try:
        return template.format(**values)
    except KeyError:
        return _DEFAULT_USER_TEMPLATE.format(**values)


def _clean_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


_DEFAULT_SYSTEM_PROMPT = (
    "你是仓库读码 agent。只输出严格 JSON："
    '{"thought":"...","action":"工具名或done","action_input":{},"self_note":"..."}。'
    "每轮最多一个只读动作，证据足够时 action=done。"
)

_DEFAULT_USER_TEMPLATE = (
    "用户问题：\n{question}\n\n"
    "当前 reading step：\n{current_step}\n\n"
    "当前 step 已有历史：\n{step_history}\n\n"
    "之前 step 摘要：\n{previous_steps}\n\n"
    "可用只读工具：\n{tools_description}\n\n"
    "请选择下一步动作。只输出严格 JSON。"
)


__all__ = ["ReadingAgent", "ReadingDecision"]
