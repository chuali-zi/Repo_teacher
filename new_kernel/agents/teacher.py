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
                # FIX-08 (user override): request 2.5× of 5000 = 12500 without
                # client-side clamping; let the provider clamp/reject if needed.
                max_tokens=12500,
            )
            chunks.append(text)
        else:
            async for chunk in self.stream_llm(
                user_prompt,
                system_prompt=system_prompt,
                temperature=0.5,
                # FIX-08 (user override): request 2.5× of 5000 = 12500 without
                # client-side clamping; let the provider clamp/reject if needed.
                max_tokens=12500,
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
        style_hint = _answer_style_hint(_classify_question_intent(question))
        return _safe_format(
            template,
            question=question,
            scratchpad_evidence=scratchpad.build_teacher_context(),
            previous_covered=_format_covered(previous_covered),
            next_anchor_hint=_format_anchor(next_anchor_hint),
            answer_style_hint=style_hint,
        )


_MACRO_KEYWORDS: tuple[str, ...] = (
    "架构", "整体", "模块", "分工", "概览", "关系", "顶层",
    "都有什么", "哪些模块", "怎么分", "组织结构", "划分", "边界",
)
_DETAIL_KEYWORDS: tuple[str, ...] = (
    "怎么实现", "具体", "细节", "这段代码", "这块代码", "函数",
    "方法", "流程", "字段", "参数", "实现", "为什么这么写",
    "里面", "内部",
)


def _classify_question_intent(question: str) -> str:
    """Soft classifier: returns 'macro' / 'detail' / 'mixed'.

    Counts substring hits in a tiny Chinese keyword set. Ties or zero hits
    yield 'mixed' so the user_template hint stays empty.
    """

    if not question:
        return "mixed"
    macro_hits = sum(1 for kw in _MACRO_KEYWORDS if kw in question)
    detail_hits = sum(1 for kw in _DETAIL_KEYWORDS if kw in question)
    if macro_hits > detail_hits and macro_hits > 0:
        return "macro"
    if detail_hits > macro_hits and detail_hits > 0:
        return "detail"
    return "mixed"


def _answer_style_hint(intent: str) -> str:
    """Map classified intent to a Chinese soft suggestion (or empty for mixed)."""

    if intent == "macro":
        return (
            "学生这次问的是宏观层面的问题，"
            "你这次回答更偏向把仓库的目录结构、模块分工、"
            "依赖关系画清楚，少粘整段代码原文；"
            "代码引用控制在 1-2 处即可。"
        )
    if intent == "detail":
        return (
            "学生这次问的是具体实现层面的问题，"
            "你这次回答更偏向把实际源码片段（带 path:line）"
            "和关键 symbol 摆出来，多引用代码，"
            "目录抽象只在最后一句简短交代。"
        )
    return ""  # mixed → empty, model uses its default voice


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
    "本轮回答风格倾向（软建议）：\n{answer_style_hint}\n\n"
    "请输出自然中文教学正文。"
)


__all__ = ["ContentChunkCallback", "TeacherAgent", "TeacherOutput"]
