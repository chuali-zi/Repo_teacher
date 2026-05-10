"""SA-03 Decomposer tests — AGENTS.md §3.2 (Phase 1 planning).

Validates: id whitelist, anchor reachability filtering, short-branch capping,
JSON-failure fallback to canonical 5 pillars, and the polyglot trigger
(secondary language ≥ 25% share).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from new_kernel.deep_research import SubtopicMeta
from new_kernel.deep_research.agents.decomposer import Decomposer
from new_kernel.deep_research.prompts import PROMPTS_ROOT
from new_kernel.prompts.prompt_manager import PromptManager


@dataclass
class _FakeOverview:
    """In-memory ``RepoOverview``-like object for the Decomposer tests."""

    text: str = "repo_overview:\n- primary_language: Python\n- file_count: 42"
    primary_language: str | None = "Python"
    file_count: int = 42
    language_counts: dict[str, int] = field(default_factory=lambda: {"Python": 100})
    top_level_paths: list[str] = field(
        default_factory=lambda: ["README.md", "src/", "tests/", "package.json"]
    )
    entry_candidates: list[Any] = field(default_factory=list)


@dataclass
class _FakeLLMResponse:
    content: str


class _FakeLLMClient:
    """Deterministic LLM stub: returns the configured payload, records the call."""

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


def _make_decomposer(response: str) -> Decomposer:
    return Decomposer(
        llm_client=_FakeLLMClient(response),
        prompt_manager=PromptManager(prompts_root=PROMPTS_ROOT),
    )


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_decomposer_happy_path_standard() -> None:
    """Standard branch: 5-pillar valid JSON → 5 SubtopicMeta in canonical order."""

    response = json.dumps(
        {
            "subtopics": [
                {"id": "what", "title": "做了什么", "anchors": ["README.md"]},
                {"id": "stack", "title": "技术栈与角色", "anchors": ["package.json"]},
                {"id": "why", "title": "选型动机", "anchors": ["README.md"]},
                {"id": "arch", "title": "整体架构", "anchors": ["src/"]},
                {"id": "flow", "title": "主流程", "anchors": ["src/"]},
            ]
        }
    )
    decomposer = _make_decomposer(response)

    result = _run(
        decomposer.process(report_shape="standard", repo_overview=_FakeOverview())
    )

    assert [meta.id for meta in result] == ["what", "stack", "why", "arch", "flow"]
    titles = [meta.title for meta in result]
    assert titles == ["做了什么", "技术栈与角色", "选型动机", "整体架构", "主流程"]
    assert result[0].anchors == ("README.md",)
    assert result[1].anchors == ("package.json",)
    assert result[3].anchors == ("src/",)
    assert all(isinstance(meta, SubtopicMeta) for meta in result)


def test_decomposer_drops_unreachable_anchor_keeps_subtopic() -> None:
    """Bogus anchors are filtered out; the sub-topic itself remains in the list."""

    response = json.dumps(
        {
            "subtopics": [
                {"id": "what", "title": "做了什么", "anchors": ["README.md", "non/existent/path"]},
                {"id": "stack", "title": "技术栈", "anchors": ["totally_fake.lock"]},
                {"id": "why", "title": "选型", "anchors": ["README.md"]},
                {"id": "arch", "title": "架构", "anchors": ["src/"]},
                {"id": "flow", "title": "主流程", "anchors": ["src/"]},
            ]
        }
    )
    decomposer = _make_decomposer(response)

    result = _run(
        decomposer.process(report_shape="standard", repo_overview=_FakeOverview())
    )

    by_id = {meta.id: meta for meta in result}
    assert "stack" in by_id, "sub-topic must survive even when every anchor is unreachable"
    assert by_id["stack"].anchors == (), "all bogus anchors must be filtered out"
    # what's good anchor stays, fake one is dropped.
    assert by_id["what"].anchors == ("README.md",)
    assert [meta.id for meta in result] == ["what", "stack", "why", "arch", "flow"]


def test_decomposer_short_branch_caps_to_what_or_what_stack() -> None:
    """Short branch: 5-pillar JSON must be trimmed to [what] or [what, stack] only."""

    response = json.dumps(
        {
            "subtopics": [
                {"id": "what", "title": "做了什么", "anchors": ["README.md"]},
                {"id": "stack", "title": "技术栈", "anchors": ["package.json"]},
                {"id": "why", "title": "选型", "anchors": ["README.md"]},
                {"id": "arch", "title": "架构", "anchors": ["src/"]},
                {"id": "flow", "title": "主流程", "anchors": ["src/"]},
            ]
        }
    )
    decomposer = _make_decomposer(response)

    result = _run(
        decomposer.process(report_shape="short", repo_overview=_FakeOverview())
    )

    ids = [meta.id for meta in result]
    assert ids in (["what"], ["what", "stack"]), f"unexpected ids on short branch: {ids}"
    # Verify the explicit 5-pillar input gave us [what, stack].
    assert ids == ["what", "stack"], "LLM returned both → keep both in canonical order"


def test_decomposer_invalid_json_falls_back_to_defaults_standard() -> None:
    """Unparseable LLM output → deterministic 5-pillar fallback with default titles."""

    decomposer = _make_decomposer("not json at all, sorry")

    result = _run(
        decomposer.process(report_shape="standard", repo_overview=_FakeOverview())
    )

    assert [meta.id for meta in result] == ["what", "stack", "why", "arch", "flow"]
    assert [meta.title for meta in result] == [
        "这个仓库在干什么",
        "用了哪些技术栈与各自作用",
        "为什么挑这套技术栈",
        "整体架构（重点）",
        "主流程怎么跑通",
    ]
    anchor_map = {meta.id: meta.anchors for meta in result}
    assert anchor_map["what"] == ("README.md",)
    assert anchor_map["stack"] == ("README.md",)
    assert anchor_map["why"] == ("README.md",)
    assert anchor_map["arch"] == ()
    assert anchor_map["flow"] == ()


def test_decomposer_polyglot_appended_when_multilingual() -> None:
    """Polyglot is kept iff secondary language share ≥ 25% of the primary's count."""

    response = json.dumps(
        {
            "subtopics": [
                {"id": "what", "title": "做了什么", "anchors": ["README.md"]},
                {"id": "stack", "title": "技术栈", "anchors": ["package.json"]},
                {"id": "why", "title": "选型", "anchors": ["README.md"]},
                {"id": "arch", "title": "架构", "anchors": ["src/"]},
                {"id": "flow", "title": "主流程", "anchors": ["src/"]},
                {"id": "polyglot", "title": "多语言分工", "anchors": []},
            ]
        }
    )

    # 30 / 100 = 0.30 ≥ 0.25 → keep polyglot.
    decomposer_keep = _make_decomposer(response)
    overview_keep = _FakeOverview(language_counts={"Python": 100, "JavaScript": 30})
    kept = _run(
        decomposer_keep.process(report_shape="standard", repo_overview=overview_keep)
    )
    assert [meta.id for meta in kept] == ["what", "stack", "why", "arch", "flow", "polyglot"]
    polyglot = next(meta for meta in kept if meta.id == "polyglot")
    assert polyglot.title == "多语言分工"
    assert polyglot.anchors == ()

    # 5 / 100 = 0.05 < 0.25 → drop polyglot even though the model returned it.
    decomposer_drop = _make_decomposer(response)
    overview_drop = _FakeOverview(language_counts={"Python": 100, "JavaScript": 5})
    dropped = _run(
        decomposer_drop.process(report_shape="standard", repo_overview=overview_drop)
    )
    assert [meta.id for meta in dropped] == ["what", "stack", "why", "arch", "flow"]


def test_decomposer_falls_back_to_default_pillars_on_llm_exception() -> None:
    """When call_llm raises (e.g., DeepSeek 401/402/limit), Decomposer must
    return the same default 5 pillars as for JSON parse failure (AGENTS.md §3.2,
    extended to HTTP errors per FIX-02). It must NOT raise."""

    class _RaisingLLMClient:
        calls = 0

        async def call_llm(self, *args: Any, **kwargs: Any) -> Any:
            type(self).calls += 1
            raise RuntimeError("simulated DeepSeek 401")

    decomposer = Decomposer(
        llm_client=_RaisingLLMClient(),
        prompt_manager=PromptManager(prompts_root=PROMPTS_ROOT),
    )

    result = _run(
        decomposer.process(report_shape="standard", repo_overview=_FakeOverview())
    )

    # Five default pillars in canonical order, with default titles & anchors.
    assert [meta.id for meta in result] == ["what", "stack", "why", "arch", "flow"]
    assert [meta.title for meta in result] == [
        "这个仓库在干什么",
        "用了哪些技术栈与各自作用",
        "为什么挑这套技术栈",
        "整体架构（重点）",
        "主流程怎么跑通",
    ]
    anchor_map = {meta.id: meta.anchors for meta in result}
    assert anchor_map["what"] == ("README.md",)
    assert anchor_map["arch"] == ()
    # And we did call the LLM exactly once (then the fallback fired, no retry loop).
    assert _RaisingLLMClient.calls == 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
