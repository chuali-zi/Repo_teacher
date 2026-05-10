"""SA-06 Composer tests — AGENTS.md §3.4 (Phase 3 streaming + suggestion parsing).

Validates the marker-aware splitter: visible chunks must never include the
``<<SUGGESTIONS>>`` line nor any text after it (even when the marker is split
across chunk boundaries), and the post-marker block must be parsed into 1..3
short Chinese suggestion strings on ``last_output.suggestions``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from new_kernel.deep_research.agents.composer import Composer, ComposeOutput
from new_kernel.deep_research.prompts import PROMPTS_ROOT
from new_kernel.prompts.prompt_manager import PromptManager


class _FakeLLMClient:
    """Deterministic stub: ``stream_llm`` is an async generator yielding canned chunks."""

    def __init__(self, chunks: list[str]) -> None:
        self._chunks = list(chunks)
        self.calls: list[dict[str, Any]] = []

    def stream_llm(
        self,
        user_prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **request_kwargs: Any,
    ) -> AsyncIterator[str]:
        self.calls.append(
            {
                "user_prompt": user_prompt,
                "system_prompt": system_prompt,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "request_kwargs": request_kwargs,
            }
        )
        return self._async_iter()

    async def _async_iter(self) -> AsyncIterator[str]:
        for chunk in self._chunks:
            yield chunk


def _make_composer(chunks: list[str]) -> Composer:
    return Composer(
        llm_client=_FakeLLMClient(chunks),
        prompt_manager=PromptManager(prompts_root=PROMPTS_ROOT),
    )


def _empty_context() -> dict:
    return {
        "subtopics": [
            {"id": "what", "title": "做了什么", "anchors": [], "skip_reason": None},
        ],
        "notes_by_id": {"what": []},
        "raw_first_round_by_id": {"what": None},
        "covered_points": [],
    }


def _drain(composer: Composer, chunks_payload: dict) -> list[str]:
    """Drain ``composer.stream(...)`` synchronously; return the visible chunks."""

    async def _run() -> list[str]:
        out: list[str] = []
        async for chunk in composer.stream(**chunks_payload):
            out.append(chunk)
        return out

    return asyncio.run(_run())


def _payload() -> dict:
    return {
        "report_shape": "standard",
        "repo_overview_text": "(overview)",
        "scratchpad_context": _empty_context(),
    }


def test_composer_streams_visible_chunks_and_strips_suggestions_marker() -> None:
    """The marker line and bullet block must never reach the visible stream."""

    chunks = ["前言…", "正文一段", "\n\n<<SUGGESTIONS>>\n", "- 第一条\n- 第二条\n"]
    composer = _make_composer(chunks)

    visible = _drain(composer, _payload())

    assert "".join(visible) == "前言…正文一段", (
        f"visible concatenation must equal 前言…正文一段; got {visible!r}"
    )
    for chunk in visible:
        assert "<<SUGGESTIONS>>" not in chunk, "marker must never appear in visible chunks"
        assert "第一条" not in chunk and "第二条" not in chunk

    assert isinstance(composer.last_output, ComposeOutput)
    assert composer.last_output.markdown == "前言…正文一段"
    assert composer.last_output.suggestions == ("第一条", "第二条")


def test_composer_handles_marker_split_across_chunks() -> None:
    """A marker fragmented across chunk boundaries must still be detected and stripped."""

    chunks = ["开头", "<<SUG", "GESTIONS>>", "\n- 仅一条\n"]
    composer = _make_composer(chunks)

    visible = _drain(composer, _payload())

    assert "".join(visible) == "开头", (
        f"visible chunks must equal 开头 only; got {visible!r}"
    )
    for chunk in visible:
        assert "<<" not in chunk and "SUG" not in chunk
    assert composer.last_output is not None
    assert composer.last_output.markdown == "开头"
    assert composer.last_output.suggestions == ("仅一条",)


def test_composer_no_suggestions_marker_keeps_full_text() -> None:
    """If the model never emits the marker, the entire body must reach the client."""

    chunks = ["全部正文"]
    composer = _make_composer(chunks)

    visible = _drain(composer, _payload())

    assert "".join(visible) == "全部正文"
    assert composer.last_output is not None
    assert composer.last_output.markdown == "全部正文"
    assert composer.last_output.suggestions == ()


def test_composer_caps_suggestions_at_three() -> None:
    """Suggestions parsing must hard-cap at 3 entries, even with 5 bullets."""

    chunks = [
        "正文",
        "\n<<SUGGESTIONS>>\n",
        "- 一\n- 二\n- 三\n- 四\n- 五\n",
    ]
    composer = _make_composer(chunks)

    visible = _drain(composer, _payload())

    assert "".join(visible) == "正文"
    assert composer.last_output is not None
    assert len(composer.last_output.suggestions) == 3
    assert composer.last_output.suggestions == ("一", "二", "三")


def test_composer_empty_stream_returns_placeholder() -> None:
    """Empty model output must yield exactly the placeholder chunk and record it."""

    composer = _make_composer([])

    visible = _drain(composer, _payload())

    assert visible, "empty stream must still produce at least one visible chunk"
    assert "".join(visible).startswith("(本次未产出导读")
    assert composer.last_output is not None
    assert composer.last_output.markdown.startswith("(本次未产出导读")
    assert composer.last_output.suggestions == ()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
