"""OrientPlanner turns a user question into a bounded code-reading plan."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..memory.scratchpad import Anchor, ReadingStep
from .base_agent import BaseAgent


@dataclass(frozen=True)
class OrientPlan:
    """A small set of reading steps for one teaching turn."""

    steps: tuple[ReadingStep, ...]


class OrientPlanner(BaseAgent):
    """Plan 1-3 read-only steps without executing tools."""

    def __init__(self, *, llm_client: Any | None = None, prompt_manager: Any | None = None) -> None:
        super().__init__(agent_name="orient", llm_client=llm_client, prompt_manager=prompt_manager)

    async def process(
        self,
        *,
        question: str,
        repo_overview: str,
        previous_covered: dict[str, str],
        tool_descriptions: str,
    ) -> OrientPlan:
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            question=question,
            repo_overview=repo_overview,
            previous_covered=previous_covered,
            tool_descriptions=tool_descriptions,
        )
        response = await self.call_llm(
            user_prompt,
            system_prompt=system_prompt,
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=1200,
        )
        return self._parse_plan(response, question=question)

    def _build_system_prompt(self) -> str:
        return self.get_prompt("system", fallback=_DEFAULT_SYSTEM_PROMPT)

    def _build_user_prompt(
        self,
        *,
        question: str,
        repo_overview: str,
        previous_covered: Mapping[str, str],
        tool_descriptions: str,
    ) -> str:
        template = self.get_prompt("user_template", fallback=_DEFAULT_USER_TEMPLATE)
        return _safe_format(
            template,
            question=question,
            repo_overview=repo_overview or "(no repo overview)",
            previous_covered=_format_covered(previous_covered),
            tool_descriptions=tool_descriptions or "(no tools available)",
        )

    def _parse_plan(self, response: str, *, question: str) -> OrientPlan:
        payload = _extract_json_object(response)
        if not payload:
            return _fallback_plan(question)

        raw_steps = payload.get("reading_plan", payload.get("steps", payload.get("plan", [])))
        if not isinstance(raw_steps, list):
            return _fallback_plan(question)

        steps: list[ReadingStep] = []
        for index, item in enumerate(raw_steps[:3], start=1):
            if not isinstance(item, Mapping):
                continue
            step_id = _clean_text(item.get("step_id") or item.get("id") or f"s{index}")
            goal = _clean_text(item.get("goal")) or f"验证与问题相关的第 {index} 个代码点"
            anchors = _parse_anchors(item.get("anchors"))
            try:
                steps.append(ReadingStep(step_id=step_id, goal=goal, anchors=tuple(anchors)))
            except (TypeError, ValueError):
                continue

        return OrientPlan(steps=tuple(steps[:3])) if steps else _fallback_plan(question)


def _parse_anchors(raw: Any) -> list[Anchor]:
    if raw is None:
        return []
    if isinstance(raw, Mapping):
        raw = [raw]
    if not isinstance(raw, list):
        return []

    anchors: list[Anchor] = []
    for item in raw[:5]:
        if isinstance(item, str):
            path = item
            why = ""
        elif isinstance(item, Mapping):
            path = _clean_text(item.get("path"))
            why = _clean_text(item.get("why") or item.get("reason"))
        else:
            continue
        if path:
            anchors.append(Anchor(path=path, why=why))
    return anchors


def _fallback_plan(question: str) -> OrientPlan:
    goal = "先定位与问题最相关的入口和源码证据"
    if question.strip():
        goal = f"先定位能回答“{question.strip()[:80]}”的最小源码证据"
    return OrientPlan(
        steps=(
            ReadingStep(
                step_id="s1",
                goal=goal,
                anchors=(Anchor(path="src/", why="兜底探索入口；实际路径需通过只读工具确认"),),
            ),
        ),
    )


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


def _format_covered(covered: Mapping[str, str]) -> str:
    if not covered:
        return "(none)"
    return "\n".join(f"- {key}: {value}" for key, value in covered.items())


def _safe_format(template: str, **values: str) -> str:
    try:
        return template.format(**values)
    except KeyError:
        return _DEFAULT_USER_TEMPLATE.format(**values)


def _clean_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


_DEFAULT_SYSTEM_PROMPT = (
    "你是仓库教学规划者。根据用户问题输出严格 JSON："
    '{"reading_plan":[{"step_id":"s1","goal":"...","anchors":[{"path":"...","why":"..."}]}]}。'
    "reading_plan 必须有 1 到 3 步，只计划只读代码证据。"
)

_DEFAULT_USER_TEMPLATE = (
    "用户问题：\n{question}\n\n"
    "仓库概览：\n{repo_overview}\n\n"
    "已讲过的点：\n{previous_covered}\n\n"
    "可用只读工具：\n{tool_descriptions}\n\n"
    "请生成本轮 reading_plan。只输出严格 JSON。"
)


__all__ = ["OrientPlan", "OrientPlanner"]
