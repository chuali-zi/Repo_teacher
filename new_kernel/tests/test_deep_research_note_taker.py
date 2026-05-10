"""SA-05 NoteTaker tests — AGENTS.md §3.3 (Phase 2 second LLM call).

Validates: anchor inference for ``read_file_range`` / ``list_dir`` /
``summarize_file``, JSON-leak sanitization, the 600-char hard cap, and the
empty-output success / failure fallbacks.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from new_kernel.deep_research import SubtopicMeta, SubtopicNote
from new_kernel.deep_research.agents.note_taker import NoteTaker
from new_kernel.deep_research.prompts import PROMPTS_ROOT
from new_kernel.prompts.prompt_manager import PromptManager


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


def _make_note_taker(response: str) -> tuple[NoteTaker, _FakeLLMClient]:
    client = _FakeLLMClient(response)
    agent = NoteTaker(
        llm_client=client,
        prompt_manager=PromptManager(prompts_root=PROMPTS_ROOT),
    )
    return agent, client


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _basic_subtopic(sid: str = "what", title: str = "这个仓库在干什么") -> SubtopicMeta:
    return SubtopicMeta(id=sid, title=title, anchors=("README.md",))


def test_note_taker_returns_subtopic_note_with_anchor_lines_for_read_range() -> None:
    """``read_file_range`` with start_line+end_line → anchor_path + anchor_lines tuple."""

    response = "这块代码读起来像一份请求路由表，主入口在 routes.py。"
    note_taker, _client = _make_note_taker(response)

    note = _run(
        note_taker.process(
            subtopic=_basic_subtopic(),
            intent="确认入口在哪里",
            tool_action="read_file_range",
            tool_input={"path": "src/main.py", "start_line": 1, "end_line": 40},
            observation="def main(): ...",
            success=True,
        )
    )

    assert isinstance(note, SubtopicNote)
    assert note.text == response
    assert note.success is True
    assert note.anchor_path == "src/main.py"
    assert note.anchor_lines == (1, 40)


def test_note_taker_anchor_path_only_for_list_dir() -> None:
    """``list_dir`` carries only ``path`` → anchor_lines must stay None."""

    response = "我们扫了一眼 src/ 目录，里面看起来按层切了几个子包。"
    note_taker, _client = _make_note_taker(response)

    note = _run(
        note_taker.process(
            subtopic=_basic_subtopic(sid="arch", title="整体架构"),
            intent="先把目录骨架摸清",
            tool_action="list_dir",
            tool_input={"path": "src/"},
            observation="api/\nrepo/\ntools/\n",
            success=True,
        )
    )

    assert note.anchor_path == "src/"
    assert note.anchor_lines is None
    assert note.success is True


def test_note_taker_strips_json_response() -> None:
    """A pure-JSON envelope is replaced by the polite fallback note."""

    note_taker, _client = _make_note_taker('{"text":"abc"}')

    note = _run(
        note_taker.process(
            subtopic=_basic_subtopic(),
            intent="探索入口",
            tool_action="read_file_range",
            tool_input={"path": "README.md", "start_line": 1, "end_line": 20},
            observation="# Repo",
            success=True,
        )
    )

    # JSON blob → forced fallback (NOT the empty-success fallback).
    assert "笔记" in note.text or "支点" in note.text
    assert note.text.startswith("这一轮素材")
    # Anchor inference still runs on success path.
    assert note.anchor_path == "README.md"
    assert note.anchor_lines == (1, 20)


def test_note_taker_caps_long_response_at_600_chars() -> None:
    """Hard cap: anything past 600 characters is truncated; never raises."""

    long_text = "这是一段很长的笔记，" * 200  # well over 600 chars
    assert len(long_text) > 600  # sanity: input is over budget
    note_taker, _client = _make_note_taker(long_text)

    note = _run(
        note_taker.process(
            subtopic=_basic_subtopic(),
            intent="探索",
            tool_action="summarize_file",
            tool_input={"path": "README.md"},
            observation="…",
            success=True,
        )
    )

    assert len(note.text) <= 600
    assert note.text  # non-empty after the cap


def test_note_taker_failure_path_uses_failure_fallback_when_empty() -> None:
    """Empty LLM output + failure path → fallback that names the target path."""

    note_taker, _client = _make_note_taker("")

    note = _run(
        note_taker.process(
            subtopic=_basic_subtopic(sid="flow", title="主流程怎么跑通"),
            intent="找入口",
            tool_action="read_file_range",
            tool_input={"path": "X.py", "start_line": 1, "end_line": 10},
            observation="",
            success=False,
        )
    )

    assert "X.py" in note.text
    assert "没拿到东西" in note.text
    assert note.success is False
    # Anchor inference runs regardless of success flag.
    assert note.anchor_path == "X.py"
    assert note.anchor_lines == (1, 10)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
