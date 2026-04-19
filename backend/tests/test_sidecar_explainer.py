from __future__ import annotations

import asyncio

import pytest

from backend.contracts.domain import UserFacingErrorException
from backend.sidecar import explainer


def test_build_sidecar_messages_constrains_context_and_answer_length() -> None:
    messages = explainer.build_sidecar_messages("什么是控制反转？")

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "只根据学生当前这句话作答" in messages[0]["content"]
    assert "目标 80-120 个中文字符" in messages[0]["content"]
    assert messages[1]["content"] == "学生问题：什么是控制反转？"


def test_explain_question_trims_long_model_output(monkeypatch: pytest.MonkeyPatch) -> None:
    long_answer = "老师换个白话说法：" + ("这是把复杂关系先拆开再约定如何配合。" * 20)

    async def fake_complete(messages, *, temperature, max_tokens):
        assert messages[1]["content"] == "学生问题：什么是控制反转？"
        assert temperature == 0.3
        assert max_tokens == 160
        return f"\n{long_answer}\n"

    monkeypatch.setattr(explainer, "complete_llm_text", fake_complete)

    data = asyncio.run(explainer.explain_question("什么是控制反转？"))

    assert data.answer.startswith("老师换个白话说法：")
    assert len(data.answer) <= explainer.SIDECAR_MAX_CHARS


def test_explain_question_rejects_blank_input() -> None:
    with pytest.raises(UserFacingErrorException) as exc_info:
        asyncio.run(explainer.explain_question("   "))

    assert exc_info.value.error.error_code == "invalid_request"


def test_explain_question_maps_llm_failures_to_user_facing_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_complete(messages, *, temperature, max_tokens):
        raise RuntimeError("boom")

    monkeypatch.setattr(explainer, "complete_llm_text", fake_complete)

    with pytest.raises(UserFacingErrorException) as exc_info:
        asyncio.run(explainer.explain_question("什么是控制反转？"))

    assert exc_info.value.error.error_code == "llm_api_failed"
