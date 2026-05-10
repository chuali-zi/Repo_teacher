"""Tests for FIX-09 (G1) — answer style hint inside TeacherAgent's user_template.

Covers:
- the small Chinese-keyword classifier `_classify_question_intent`
- the intent → Chinese suggestion mapper `_answer_style_hint`
- end-to-end wiring: a question with detail keywords causes the captured
  user_prompt to contain the detail-flavored suggestion sentence.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from new_kernel.agents.teacher import (
    TeacherAgent,
    _answer_style_hint,
    _classify_question_intent,
)
from new_kernel.memory.scratchpad import Scratchpad


# -- classifier --------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "这个仓库的整体架构是什么",
        "都有哪些模块",
        "顶层目录怎么分",
    ],
)
def test_classify_question_macro_keywords(question: str) -> None:
    assert _classify_question_intent(question) == "macro"


@pytest.mark.parametrize(
    "question",
    [
        "DeepResearchLoop.run 怎么实现",
        "Phase 2 里面具体细节是什么",
        "这段代码的字段含义",
    ],
)
def test_classify_question_detail_keywords(question: str) -> None:
    assert _classify_question_intent(question) == "detail"


@pytest.mark.parametrize(
    "question",
    [
        "你好",
        "继续",
        "",
        "deepresearch",
    ],
)
def test_classify_question_mixed_or_unclear(question: str) -> None:
    assert _classify_question_intent(question) == "mixed"


def test_classify_tie_falls_back_to_mixed() -> None:
    # "模块" → macro=1; "具体" → detail=1; equal → mixed.
    assert _classify_question_intent("模块的具体") == "mixed"


# -- hint mapper -------------------------------------------------------------


def test_answer_style_hint_macro_returns_chinese_suggestion() -> None:
    hint = _answer_style_hint("macro")
    assert hint
    assert "目录" in hint
    assert "模块" in hint


def test_answer_style_hint_detail_returns_chinese_suggestion() -> None:
    hint = _answer_style_hint("detail")
    assert hint
    assert "源码" in hint
    assert "引用" in hint


def test_answer_style_hint_mixed_returns_empty() -> None:
    assert _answer_style_hint("mixed") == ""


# -- end-to-end wiring -------------------------------------------------------


class _RecordingLLM:
    """Tiny fake LLM that records the last user_prompt instead of calling out."""

    def __init__(self) -> None:
        self.last_user_prompt: str | None = None
        self.last_system_prompt: str | None = None

    async def call_llm(
        self,
        user_prompt: str,
        *,
        system_prompt: str | None = None,
        response_format: Any | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **_kwargs: Any,
    ) -> str:
        self.last_user_prompt = user_prompt
        self.last_system_prompt = system_prompt
        return "回答正文。下一个教学点：继续读入口。"


def test_teacher_user_prompt_inserts_style_hint_for_detail_question() -> None:
    fake_llm = _RecordingLLM()
    teacher = TeacherAgent(llm_client=fake_llm)
    scratchpad = Scratchpad()
    scratchpad.reset_for_turn("这块代码的具体实现怎么写")

    asyncio.run(
        teacher.process(
            question="这块代码的具体实现怎么写",
            scratchpad=scratchpad,
            previous_covered={},
            next_anchor_hint=None,
        )
    )

    assert fake_llm.last_user_prompt is not None
    assert "学生这次问的是具体实现层面" in fake_llm.last_user_prompt


def test_teacher_user_prompt_inserts_style_hint_for_macro_question() -> None:
    fake_llm = _RecordingLLM()
    teacher = TeacherAgent(llm_client=fake_llm)
    scratchpad = Scratchpad()
    scratchpad.reset_for_turn("这个仓库的整体架构有哪些模块")

    asyncio.run(
        teacher.process(
            question="这个仓库的整体架构有哪些模块",
            scratchpad=scratchpad,
            previous_covered={},
            next_anchor_hint=None,
        )
    )

    assert fake_llm.last_user_prompt is not None
    assert "学生这次问的是宏观层面" in fake_llm.last_user_prompt
