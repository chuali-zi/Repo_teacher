from __future__ import annotations

import re

from backend.contracts.domain import UserFacingError, UserFacingErrorException
from backend.contracts.dto import ExplainSidecarData
from backend.contracts.enums import ErrorCode, SessionStatus
from backend.m5_session.errors import invalid_request_error
from backend.m6_response.llm_caller import complete_llm_text

SIDECAR_MAX_CHARS = 120
SIDECAR_MAX_TOKENS = 160

_WHITESPACE_RE = re.compile(r"\s+")


def build_sidecar_messages(question: str) -> list[dict[str, str]]:
    trimmed = question.strip()
    return [
        {
            "role": "system",
            "content": (
                "你是代码带读课里的老师助教。"
                "你的唯一任务是把学生当前这句困惑讲成能听懂的白话。"
                "只根据学生当前这句话作答，不要假装看过仓库、代码、上下文或上一轮消息。"
                "保持老师口吻，直接回答，不寒暄，不分点，不加多余铺垫。"
                "优先解释术语、概念和因果，不要编造具体代码细节。"
                "如果问题缺上下文，就直接说明还缺哪一句背景，再给出最小补充方向。"
                "目标 80-120 个中文字符，必要时可略短，但不要超过 120 个中文字符。"
            ),
        },
        {"role": "user", "content": f"学生问题：{trimmed}"},
    ]


async def explain_question(question: str) -> ExplainSidecarData:
    trimmed = question.strip()
    if not trimmed:
        raise UserFacingErrorException(invalid_request_error(None, "问题不能为空"))

    try:
        raw_answer = await complete_llm_text(
            build_sidecar_messages(trimmed),
            temperature=0.3,
            max_tokens=SIDECAR_MAX_TOKENS,
        )
    except Exception as exc:
        raise UserFacingErrorException(_sidecar_llm_error(exc)) from exc

    answer = normalize_sidecar_answer(raw_answer)
    if not answer:
        raise UserFacingErrorException(_sidecar_llm_error(RuntimeError("empty sidecar answer")))
    return ExplainSidecarData(answer=answer)


def normalize_sidecar_answer(text: str) -> str:
    collapsed = _WHITESPACE_RE.sub(" ", text).strip()
    if len(collapsed) <= SIDECAR_MAX_CHARS:
        return collapsed
    clipped = collapsed[:SIDECAR_MAX_CHARS].rstrip()
    if clipped.endswith(("。", "！", "？", "…")):
        return clipped
    if len(clipped) == SIDECAR_MAX_CHARS:
        return f"{clipped[:-1].rstrip()}…"
    return clipped


def _sidecar_llm_error(exc: Exception) -> UserFacingError:
    is_timeout = isinstance(exc, TimeoutError)
    return UserFacingError(
        error_code=ErrorCode.LLM_API_TIMEOUT if is_timeout else ErrorCode.LLM_API_FAILED,
        message=(
            "小回答器请求超时，请稍后重试。"
            if is_timeout
            else "小回答器暂时不可用，请稍后重试。"
        ),
        retryable=True,
        stage=SessionStatus.CHATTING,
        input_preserved=True,
        internal_detail=str(exc),
    )
