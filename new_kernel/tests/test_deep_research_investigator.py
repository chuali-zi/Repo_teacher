"""SA-04 Investigator tests — AGENTS.md §3.3 (Phase 2 single-round ReAct).

Covers: happy-path JSON parsing, action whitelist enforcement, parse-failure
fallback to ``done``, ``done`` enforcement (clears input + want_more), and
notes_history rendering into the user prompt.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import pytest

from new_kernel.deep_research import SubtopicMeta, SubtopicNote
from new_kernel.deep_research.agents.investigator import (
    InvestigationDecision,
    Investigator,
)
from new_kernel.deep_research.prompts import PROMPTS_ROOT
from new_kernel.prompts.prompt_manager import PromptManager


_VALID_ACTIONS: tuple[str, ...] = (
    "read_file_range",
    "list_dir",
    "search_in_repo",
    "done",
)
_TOOLS_DESC = "| Action | Input | When to use |\n| --- | --- | --- |\n| read_file_range | ... | ... |"
_REPO_OVERVIEW = "primary_language: Python\nfile_count: 42"


@dataclass
class _FakeLLMResponse:
    content: str


class _FakeLLMClient:
    """Deterministic LLM stub returning the configured payload, capturing calls."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    async def call_llm(
        self,
        user_prompt: str,
        *,
        system_prompt: str | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **request_kwargs: Any,
    ) -> _FakeLLMResponse:
        self.calls.append(
            {
                "user_prompt": user_prompt,
                "system_prompt": system_prompt,
                "response_format": response_format,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "request_kwargs": request_kwargs,
            }
        )
        return _FakeLLMResponse(content=self._response)


def _make_investigator(response: str) -> tuple[Investigator, _FakeLLMClient]:
    fake = _FakeLLMClient(response)
    investigator = Investigator(
        llm_client=fake,
        prompt_manager=PromptManager(prompts_root=PROMPTS_ROOT),
    )
    return investigator, fake


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _subtopic(id_: str = "what", title: str = "这个仓库在干什么") -> SubtopicMeta:
    return SubtopicMeta(id=id_, title=title, anchors=("README.md",))


def test_investigator_returns_valid_decision_when_llm_returns_json() -> None:
    """Happy path: well-formed JSON → all four fields propagate correctly."""

    response = json.dumps(
        {
            "action": "read_file_range",
            "action_input": {"path": "README.md", "start_line": 1, "end_line": 40},
            "intent": "看 README",
            "want_more": True,
        }
    )
    investigator, _ = _make_investigator(response)

    decision = _run(
        investigator.process(
            subtopic=_subtopic(),
            notes_history=(),
            failure_streak=0,
            valid_actions=_VALID_ACTIONS,
            tools_description=_TOOLS_DESC,
            repo_overview_text=_REPO_OVERVIEW,
        )
    )

    assert isinstance(decision, InvestigationDecision)
    assert decision.action == "read_file_range"
    assert decision.action_input == {
        "path": "README.md",
        "start_line": 1,
        "end_line": 40,
    }
    assert decision.intent == "看 README"
    assert decision.want_more is True


def test_investigator_action_not_in_valid_actions_falls_back_to_done() -> None:
    """Unknown action → coerce to ``done`` with cleared input and want_more=False."""

    response = json.dumps(
        {
            "action": "shell_exec",
            "action_input": {"cmd": "ls"},
            "intent": "想跑命令",
            "want_more": True,
        }
    )
    investigator, _ = _make_investigator(response)

    decision = _run(
        investigator.process(
            subtopic=_subtopic(),
            notes_history=(),
            failure_streak=0,
            valid_actions=_VALID_ACTIONS,  # shell_exec is NOT here
            tools_description=_TOOLS_DESC,
            repo_overview_text=_REPO_OVERVIEW,
        )
    )

    assert decision.action == "done"
    assert decision.action_input == {}
    assert decision.want_more is False
    assert decision.intent == "(降级 done)"


def test_investigator_returns_done_on_parse_failure() -> None:
    """Garbage LLM output → canonical parse-failure fallback decision."""

    investigator, _ = _make_investigator("not json")

    decision = _run(
        investigator.process(
            subtopic=_subtopic(),
            notes_history=(),
            failure_streak=0,
            valid_actions=_VALID_ACTIONS,
            tools_description=_TOOLS_DESC,
            repo_overview_text=_REPO_OVERVIEW,
        )
    )

    assert decision == InvestigationDecision(
        action="done",
        action_input={},
        intent="(解析失败，结束本支柱)",
        want_more=False,
    )


def test_investigator_done_action_clears_input_and_want_more() -> None:
    """``done`` always wipes ``action_input`` and forces ``want_more=False``."""

    response = json.dumps(
        {
            "action": "done",
            "action_input": {"foo": 1},
            "intent": "看够了",
            "want_more": True,
        }
    )
    investigator, _ = _make_investigator(response)

    decision = _run(
        investigator.process(
            subtopic=_subtopic(),
            notes_history=(),
            failure_streak=0,
            valid_actions=_VALID_ACTIONS,
            tools_description=_TOOLS_DESC,
            repo_overview_text=_REPO_OVERVIEW,
        )
    )

    assert decision.action == "done"
    assert decision.action_input == {}
    assert decision.want_more is False
    # intent flows through since the LLM gave a real one.
    assert decision.intent == "看够了"


def test_investigator_passes_notes_history_to_prompt() -> None:
    """notes_history is rendered as ``轮{i+1}:\\n{text}`` joined and sent to the LLM."""

    response = json.dumps(
        {
            "action": "done",
            "action_input": {},
            "intent": "看够了",
            "want_more": False,
        }
    )
    investigator, fake = _make_investigator(response)

    history = (
        SubtopicNote(text="第一轮我们看到了 README 顶部 ASCII logo"),
        SubtopicNote(text="第二轮发现 src/ 下分了 api/ 和 core/"),
    )

    _run(
        investigator.process(
            subtopic=_subtopic(),
            notes_history=history,
            failure_streak=1,
            valid_actions=_VALID_ACTIONS,
            tools_description=_TOOLS_DESC,
            repo_overview_text=_REPO_OVERVIEW,
        )
    )

    assert len(fake.calls) == 1
    user_prompt = fake.calls[0]["user_prompt"]
    assert "轮1:" in user_prompt
    assert "轮2:" in user_prompt
    assert "第一轮我们看到了 README 顶部 ASCII logo" in user_prompt
    assert "第二轮发现 src/ 下分了 api/ 和 core/" in user_prompt


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
