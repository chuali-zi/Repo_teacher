"""Phase 2 single-round ReAct investigator for deep_research onboarding.

Decides one tool action per ReAct round for a given sub-topic by calling the LLM
once with the ``investigate`` prompt and parsing a strict JSON envelope into an
``InvestigationDecision``. This module does NOT execute tools, NOT touch the
scratchpad, and NOT emit events — the orchestrator (SA-07 ``DeepResearchLoop``)
performs the tool dispatch, persistence, and SSE plumbing. On any parse or
validation failure, the agent silently falls back to ``done`` rather than
raising, per AGENTS.md §3.3 / §12.2.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..research_scratchpad import SubtopicMeta, SubtopicNote
from .base_research_agent import BaseResearchAgent


@dataclass(frozen=True)
class InvestigationDecision:
    """One round's resolved decision: action + input + intent + continuation flag."""

    action: str
    action_input: dict = field(default_factory=dict)
    intent: str = ""
    want_more: bool = False


class Investigator(BaseResearchAgent):
    """Phase 2 single-round decision agent — one LLM call, one tool action max."""

    def __init__(
        self,
        *,
        llm_client: Any,
        prompt_manager: Any,
        agent_name: str = "investigate",
    ) -> None:
        super().__init__(
            agent_name=agent_name,
            llm_client=llm_client,
            prompt_manager=prompt_manager,
        )

    async def process(
        self,
        *,
        subtopic: SubtopicMeta,
        notes_history: tuple[SubtopicNote, ...],
        failure_streak: int,
        valid_actions: tuple[str, ...],
        tools_description: str,
        repo_overview_text: str,
    ) -> InvestigationDecision:
        """Run one ReAct round for ``subtopic``; never raise on parse/validation."""

        user_prompt = self._render_user_prompt(
            subtopic=subtopic,
            notes_history=notes_history,
            failure_streak=failure_streak,
            valid_actions=valid_actions,
            tools_description=tools_description,
            repo_overview_text=repo_overview_text,
        )

        try:
            text = await self.call_llm(
                user_prompt,
                system_prompt=self.get_prompt("system"),
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=600,
            )
        except Exception:
            return _fallback_parse_failure()

        payload = self.parse_strict_json(text, fallback={})
        if not isinstance(payload, dict) or not payload:
            return _fallback_parse_failure()

        return _coerce_decision(
            payload,
            valid_actions=valid_actions,
            subtopic_title=subtopic.title,
        )

    def _render_user_prompt(
        self,
        *,
        subtopic: SubtopicMeta,
        notes_history: tuple[SubtopicNote, ...],
        failure_streak: int,
        valid_actions: tuple[str, ...],
        tools_description: str,
        repo_overview_text: str,
    ) -> str:
        template = self.get_prompt("user_template")
        notes_block = _render_notes_history(notes_history)
        anchors_json = json.dumps(list(subtopic.anchors), ensure_ascii=False)
        actions_csv = ", ".join(valid_actions)
        return template.format(
            subtopic_id=subtopic.id,
            subtopic_title=subtopic.title,
            subtopic_anchors=anchors_json,
            notes_history=notes_block,
            failure_streak=failure_streak,
            valid_actions=actions_csv,
            tools_description=tools_description,
            repo_overview_text=repo_overview_text,
        )


def _render_notes_history(notes_history: tuple[SubtopicNote, ...]) -> str:
    if not notes_history:
        return "（首轮）"
    rendered = [f"轮{i + 1}:\n{note.text}" for i, note in enumerate(notes_history)]
    return "\n\n".join(rendered)


def _fallback_parse_failure() -> InvestigationDecision:
    return InvestigationDecision(
        action="done",
        action_input={},
        intent="(解析失败，结束本支柱)",
        want_more=False,
    )


def _coerce_decision(
    payload: dict,
    *,
    valid_actions: tuple[str, ...],
    subtopic_title: str,
) -> InvestigationDecision:
    """Validate / coerce raw JSON payload into a stable ``InvestigationDecision``."""

    raw_action = payload.get("action")
    action = str(raw_action).strip() if isinstance(raw_action, str) else ""

    raw_input = payload.get("action_input")
    action_input: dict = raw_input if isinstance(raw_input, dict) else {}

    raw_intent = payload.get("intent")
    intent = str(raw_intent).strip() if raw_intent is not None else ""
    if not intent:
        intent = f"探索 {subtopic_title}"

    raw_want_more = payload.get("want_more")
    want_more = raw_want_more if isinstance(raw_want_more, bool) else False

    if action not in set(valid_actions):
        return InvestigationDecision(
            action="done",
            action_input={},
            intent="(降级 done)",
            want_more=False,
        )

    if action == "done":
        return InvestigationDecision(
            action="done",
            action_input={},
            intent=intent,
            want_more=False,
        )

    return InvestigationDecision(
        action=action,
        action_input=action_input,
        intent=intent,
        want_more=want_more,
    )


__all__ = ["InvestigationDecision", "Investigator"]
