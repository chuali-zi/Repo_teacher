"""TeacherAgent is the only visible answer writer for normal teaching turns."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..memory.scratchpad import Anchor, Scratchpad
from .base_agent import BaseAgent


ContentChunkCallback = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class TeacherOutput:
    """Final visible answer and one optional follow-up teaching point."""

    full_text: str
    suggestions: list[str] = field(default_factory=list)
    next_anchor: Anchor | None = None


class TeacherAgent(BaseAgent):
    """Write natural Chinese teaching text from scratchpad evidence."""

    def __init__(self, *, llm_client: Any | None = None, prompt_manager: Any | None = None) -> None:
        super().__init__(agent_name="teach", llm_client=llm_client, prompt_manager=prompt_manager)

    async def process(
        self,
        *,
        question: str,
        scratchpad: Scratchpad,
        previous_covered: dict[str, str],
        next_anchor_hint: Anchor | None = None,
        on_chunk: ContentChunkCallback | None = None,
    ) -> TeacherOutput:
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            question=question,
            scratchpad=scratchpad,
            previous_covered=previous_covered,
            next_anchor_hint=next_anchor_hint,
        )

        chunks: list[str] = []
        if on_chunk is None:
            text = await self.call_llm(
                user_prompt,
                system_prompt=system_prompt,
                temperature=0.5,
                max_tokens=5000,
            )
            chunks.append(text)
        else:
            async for chunk in self.stream_llm(
                user_prompt,
                system_prompt=system_prompt,
                temperature=0.5,
                max_tokens=5000,
            ):
                chunks.append(chunk)
                await on_chunk(chunk)

        full_text = "".join(chunks).strip()
        if not full_text:
            full_text = _empty_answer()
            if on_chunk is not None:
                await on_chunk(full_text)
        suggestions = _extract_suggestion(full_text)
        return TeacherOutput(
            full_text=full_text,
            suggestions=suggestions,
            next_anchor=next_anchor_hint,
        )

    def _build_system_prompt(self) -> str:
        return self.get_prompt("system", fallback=_DEFAULT_SYSTEM_PROMPT)

    def _build_user_prompt(
        self,
        *,
        question: str,
        scratchpad: Scratchpad,
        previous_covered: Mapping[str, str],
        next_anchor_hint: Anchor | None,
    ) -> str:
        template = self.get_prompt("user_template", fallback=_DEFAULT_USER_TEMPLATE)
        return _safe_format(
            template,
            question=question,
            scratchpad_evidence=scratchpad.build_teacher_context(),
            previous_covered=_format_covered(previous_covered),
            next_anchor_hint=_format_anchor(next_anchor_hint),
        )


def _extract_suggestion(text: str) -> list[str]:
    marker = "下一个教学点："
    index = text.rfind(marker)
    if index < 0:
        return []
    suggestion = text[index + len(marker) :].strip()
    if not suggestion:
        return []
    first_line = suggestion.splitlines()[0].strip()
    return [first_line[:200]] if first_line else []


def _empty_answer() -> str:
    return "当前证据不足，我不能可靠展开这个点。下一个教学点：先定位相关入口文件。"


def _format_anchor(anchor: Anchor | None) -> str:
    if anchor is None:
        return "(none)"
    if anchor.why:
        return f"{anchor.path} - {anchor.why}"
    return anchor.path


def _format_covered(covered: Mapping[str, str]) -> str:
    if not covered:
        return "(none)"
    return "\n".join(f"- {key}: {value}" for key, value in covered.items())


def _safe_format(template: str, **values: str) -> str:
    try:
        return template.format(**values)
    except KeyError:
        return _DEFAULT_USER_TEMPLATE.format(**values)


_DEFAULT_SYSTEM_PROMPT = (
    "你是仓库老师。只能基于 scratchpad 证据回答；一次只讲一个核心点；"
    "最多引用 3 个 source anchors；最终教学正文不少于 2000 中文字，不包含代码块和结尾的"
    "“下一个教学点：...”。必须围绕证据充实展开背景、调用链、关键 symbol、上下游协作、"
    "边界情况、设计原因和学习提示，不能空泛重复或堆砌废话；证据不足时明确缩小说法，"
    "不能编造。结尾必须恰好一个“下一个教学点：...”。"
)

_DEFAULT_USER_TEMPLATE = (
    "用户问题：\n{question}\n\n"
    "可用证据：\n{scratchpad_evidence}\n\n"
    "已讲过的点：\n{previous_covered}\n\n"
    "下一个教学点提示：\n{next_anchor_hint}\n\n"
    "请输出自然中文教学正文。"
)


__all__ = ["ContentChunkCallback", "TeacherAgent", "TeacherOutput"]
