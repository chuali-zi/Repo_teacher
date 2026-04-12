from __future__ import annotations

import json
import re
from uuid import uuid4

from backend.contracts.domain import (
    AnalysisWarning,
    EvidenceLine,
    InitialReportAnswer,
    InitialReportContent,
    LanguageTypeSection,
    OverviewSection,
    RecommendedStep,
    StructuredAnswer,
    StructuredMessageContent,
    Suggestion,
    TopicRef,
)
from backend.contracts.enums import (
    ConfidenceLevel,
    DerivedStatus,
    LearningGoal,
    MessageType,
    PromptScenario,
    WarningType,
)

_JSON_BLOCK_RE = re.compile(r"<json_output>\s*(\{.*\})\s*</json_output>", re.DOTALL)
_JSON_FENCE_RE = re.compile(r"```json\s*(\{.*\})\s*```", re.DOTALL)

_SECTION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("focus", r"(?:^|\n)#{1,6}\s*本轮重点\s*\n"),
    ("direct_explanation", r"(?:^|\n)#{1,6}\s*直接解释\s*\n"),
    ("relation_to_overall", r"(?:^|\n)#{1,6}\s*与整体的关系\s*\n"),
    ("evidence", r"(?:^|\n)#{1,6}\s*证据\s*\n"),
    ("uncertainty", r"(?:^|\n)#{1,6}\s*不确定项\s*\n"),
    ("next_steps", r"(?:^|\n)#{1,6}\s*下一步建议\s*\n"),
)


def parse_final_answer(
    scenario: PromptScenario,
    raw_text: str,
) -> StructuredAnswer | InitialReportAnswer:
    visible_text, payload = _extract_payload(raw_text)
    if scenario == PromptScenario.INITIAL_REPORT:
        return InitialReportAnswer(
            answer_id=_new_answer_id(),
            message_type=MessageType.INITIAL_REPORT,
            raw_text=visible_text,
            initial_report_content=_parse_initial_report_content(payload, visible_text),
            suggestions=_parse_suggestions(
                payload.get("suggestions") or payload.get("initial_report_content", {}).get("suggested_next_questions")
            ),
            used_evidence_refs=_string_list(payload.get("used_evidence_refs")),
            warnings=_parse_warnings(payload.get("warnings")),
        )
    structured_content = _parse_structured_content(payload, visible_text)
    suggestions = structured_content.next_steps[:3] or _fallback_suggestions(visible_text)
    structured_content.next_steps = suggestions
    return StructuredAnswer(
        answer_id=_new_answer_id(),
        message_type=_message_type_for_scenario(scenario),
        raw_text=visible_text,
        structured_content=structured_content,
        suggestions=suggestions,
        related_topic_refs=_parse_topic_refs(payload.get("related_topic_refs")),
        used_evidence_refs=_string_list(payload.get("used_evidence_refs")),
        warnings=_parse_warnings(payload.get("warnings")),
    )


def _extract_payload(raw_text: str) -> tuple[str, dict]:
    for pattern in (_JSON_BLOCK_RE, _JSON_FENCE_RE):
        match = pattern.search(raw_text)
        if not match:
            continue
        payload_text = match.group(1)
        visible_text = pattern.sub("", raw_text).strip()
        try:
            return visible_text, json.loads(payload_text)
        except json.JSONDecodeError:
            break
    return raw_text.strip(), {}


def _parse_initial_report_content(payload: dict, visible_text: str) -> InitialReportContent:
    content = payload.get("initial_report_content")
    if isinstance(content, dict):
        return InitialReportContent.model_validate(content)
    summary = _first_non_empty_line(visible_text) or "已生成首轮报告，但结构化区块缺失。"
    return InitialReportContent(
        overview=OverviewSection(summary=summary, confidence=ConfidenceLevel.UNKNOWN, evidence_refs=[]),
        focus_points=[],
        repo_mapping=[],
        language_and_type=LanguageTypeSection(primary_language="unknown", project_types=[], degradation_notice=None),
        key_directories=[],
        entry_section={"status": DerivedStatus.UNKNOWN, "entries": [], "fallback_advice": None, "unknown_items": []},
        recommended_first_step=RecommendedStep(
            target="先查看 README 或主入口文件",
            reason="结构化首轮报告缺失时，先从仓库说明和主入口建立上下文。",
            learning_gain="先建立整体认知，再决定后续深入方向。",
            evidence_refs=[],
        ),
        reading_path_preview=[],
        unknown_section=[],
        suggested_next_questions=_fallback_suggestions(visible_text),
    )


def _parse_structured_content(payload: dict, visible_text: str) -> StructuredMessageContent:
    if payload:
        return StructuredMessageContent(
            focus=_clean_text(payload.get("focus")) or _section_map(visible_text).get("focus") or _first_non_empty_line(visible_text),
            direct_explanation=_clean_text(payload.get("direct_explanation")) or _section_map(visible_text).get("direct_explanation") or visible_text,
            relation_to_overall=_clean_text(payload.get("relation_to_overall")) or _section_map(visible_text).get("relation_to_overall"),
            evidence_lines=_parse_evidence_lines(payload.get("evidence_lines")) or _fallback_evidence_lines(visible_text),
            uncertainties=_string_list(payload.get("uncertainties")) or _fallback_uncertainties(),
            next_steps=_parse_suggestions(payload.get("next_steps")),
        )
    sections = _section_map(visible_text)
    return StructuredMessageContent(
        focus=sections.get("focus") or _first_non_empty_line(visible_text),
        direct_explanation=sections.get("direct_explanation") or visible_text,
        relation_to_overall=sections.get("relation_to_overall") or "这部分需要结合仓库整体结构继续确认。",
        evidence_lines=_fallback_evidence_lines(sections.get("evidence") or visible_text),
        uncertainties=_extract_bullets(sections.get("uncertainty")) or _fallback_uncertainties(),
        next_steps=_parse_suggestions(sections.get("next_steps")) or _fallback_suggestions(visible_text),
    )


def _section_map(raw_text: str) -> dict[str, str]:
    positions: list[tuple[str, int, int]] = []
    for key, pattern in _SECTION_PATTERNS:
        match = re.search(pattern, raw_text)
        if match:
            positions.append((key, match.start(), match.end()))
    sections: dict[str, str] = {}
    for index, (key, _start, end) in enumerate(positions):
        next_start = positions[index + 1][1] if index + 1 < len(positions) else len(raw_text)
        sections[key] = raw_text[end:next_start].strip()
    return sections


def _parse_evidence_lines(value: object) -> list[EvidenceLine]:
    if not isinstance(value, list):
        return []
    parsed: list[EvidenceLine] = []
    for item in value[:4]:
        try:
            parsed.append(EvidenceLine.model_validate(item))
        except Exception:
            continue
    return parsed


def _parse_suggestions(value: object) -> list[Suggestion]:
    if isinstance(value, str):
        return _suggestions_from_lines(_extract_bullets(value))
    if not isinstance(value, list):
        return []
    parsed: list[Suggestion] = []
    for item in value:
        if isinstance(item, dict):
            try:
                parsed.append(Suggestion.model_validate(item))
                continue
            except Exception:
                text = _clean_text(item.get("text"))
                if text:
                    parsed.append(_make_suggestion(text, item.get("target_goal")))
                continue
        if isinstance(item, str) and item.strip():
            parsed.append(_make_suggestion(item.strip()))
    return parsed[:3]


def _parse_topic_refs(value: object) -> list[TopicRef]:
    if not isinstance(value, list):
        return []
    parsed: list[TopicRef] = []
    for item in value:
        if isinstance(item, dict):
            try:
                parsed.append(TopicRef.model_validate(item))
            except Exception:
                continue
    return parsed


def _parse_warnings(value: object) -> list[AnalysisWarning]:
    if not isinstance(value, list):
        return []
    parsed: list[AnalysisWarning] = []
    for item in value:
        if isinstance(item, dict):
            try:
                parsed.append(AnalysisWarning.model_validate(item))
            except Exception:
                continue
    return parsed


def _fallback_evidence_lines(text: str) -> list[EvidenceLine]:
    line = _first_non_empty_line(text) or "当前回答未提供独立证据条目。"
    return [EvidenceLine(text=line, evidence_refs=[], confidence=ConfidenceLevel.UNKNOWN)]


def _fallback_uncertainties() -> list[str]:
    return ["当前结构化区块缺失，建议结合下一轮追问继续确认细节。"]


def _fallback_suggestions(text: str) -> list[Suggestion]:
    bullets = _extract_bullets(text)
    if bullets:
        suggestions = _suggestions_from_lines(bullets)
        if suggestions:
            return suggestions[:3]
    return [
        _make_suggestion("想继续看整体结构吗？", LearningGoal.STRUCTURE),
        _make_suggestion("想看看入口或启动点吗？", LearningGoal.ENTRY),
        _make_suggestion("想继续追问核心流程吗？", LearningGoal.FLOW),
    ]


def _suggestions_from_lines(lines: list[str]) -> list[Suggestion]:
    suggestions: list[Suggestion] = []
    for line in lines:
        if len(suggestions) >= 3:
            break
        suggestions.append(_make_suggestion(line))
    return suggestions


def _make_suggestion(text: str, target_goal: object = None) -> Suggestion:
    goal = target_goal if target_goal in set(LearningGoal) else None
    return Suggestion(
        suggestion_id=f"sug_{uuid4().hex[:10]}",
        text=text,
        target_goal=goal,
        related_topic_refs=[],
    )


def _message_type_for_scenario(scenario: PromptScenario) -> MessageType:
    if scenario == PromptScenario.GOAL_SWITCH:
        return MessageType.GOAL_SWITCH_CONFIRMATION
    if scenario == PromptScenario.STAGE_SUMMARY:
        return MessageType.STAGE_SUMMARY
    return MessageType.AGENT_ANSWER


def _extract_bullets(text: str | None) -> list[str]:
    if not text:
        return []
    items: list[str] = []
    for line in text.splitlines():
        candidate = re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", line).strip()
        if candidate and candidate != line.strip() or line.strip().startswith(("-", "*")):
            items.append(candidate)
    return items


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _first_non_empty_line(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip("# ")
        if stripped:
            return stripped
    return None


def _new_answer_id() -> str:
    return f"ans_{uuid4().hex[:12]}"
