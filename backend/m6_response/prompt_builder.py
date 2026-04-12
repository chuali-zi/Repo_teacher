from __future__ import annotations

import json
import re
from typing import Any

from backend.contracts.domain import PromptBuildInput
from backend.contracts.enums import PromptScenario

_WINDOWS_PATH_RE = re.compile(r"(?<![A-Za-z0-9_./-])(?:[A-Za-z]:\\[^\s\"']+)")
_UNIX_PATH_RE = re.compile(r"(?<![A-Za-z0-9_.-])/(?:[^\s\"']+)")
_SECRET_RE = re.compile(
    r"(?:sk-[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9]{16,}|AIza[0-9A-Za-z\-_]{20,})"
)

_SYSTEM_RULES = """
你是 Repo Tutor 的教学回答 Agent。

必须严格遵守：
1. 只能基于提供的教学骨架、主题切片、会话状态回答，不得发明新结论。
2. 对入口、流程、分层、依赖等不确定结论，使用“候选 / 可能 / 目前证据更支持”之类措辞。
3. 不得输出敏感文件正文、绝对真实路径、内部错误堆栈、疑似密钥。
4. 每轮只讲 2-4 个核心点；浅层时更少，深层时可补更多证据，但仍要标注不确定项。
5. 如果证据不足，要明确说明“不确定”或“暂时无法确认”，不要强行补全。
6. 最终必须输出给用户看的 Markdown 正文，然后单独输出一个 <json_output>...</json_output> 结构化 JSON。
""".strip()


def build_prompt(input_data: PromptBuildInput) -> str:
    payload = _build_payload(input_data)
    json_schema = _json_schema_for_scenario(input_data.scenario)
    sections = [
        _SYSTEM_RULES,
        f"场景: {input_data.scenario}",
        f"讲解深度: {input_data.depth_level}",
        _scenario_guidance(input_data.scenario),
        "输出要求:",
        _output_requirements(input_data),
        "JSON 结构要求:",
        json_schema,
        "可用上下文(JSON):",
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
    ]
    return "\n\n".join(section for section in sections if section)


def _build_payload(input_data: PromptBuildInput) -> dict[str, Any]:
    return {
        "scenario": input_data.scenario,
        "user_message": _sanitize_value(input_data.user_message),
        "depth_level": input_data.depth_level,
        "history_summary": _sanitize_value(input_data.history_summary),
        "output_contract": _sanitize_value(input_data.output_contract.model_dump(mode="json")),
        "conversation_state": _sanitize_conversation(input_data),
        "topic_slice": _sanitize_value([item.model_dump(mode="json") for item in input_data.topic_slice]),
        "teaching_skeleton": _sanitize_value(input_data.teaching_skeleton.model_dump(mode="json")),
    }


def _sanitize_conversation(input_data: PromptBuildInput) -> dict[str, Any]:
    conversation = input_data.conversation_state.model_dump(mode="json")
    conversation["messages"] = [
        {
            "message_id": item.message_id,
            "role": item.role,
            "message_type": item.message_type,
            "raw_text": _sanitize_value(item.raw_text),
            "related_goal": item.related_goal,
            "streaming_complete": item.streaming_complete,
        }
        for item in input_data.conversation_state.messages[-6:]
    ]
    return _sanitize_value(conversation)


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"root_path", "real_path", "internal_detail"}:
                continue
            sanitized[key] = _sanitize_value(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str):
        redacted = _WINDOWS_PATH_RE.sub("<path_omitted>", value)
        redacted = _UNIX_PATH_RE.sub("<path_omitted>", redacted)
        return _SECRET_RE.sub("[redacted_secret]", redacted)
    return value


def _scenario_guidance(scenario: PromptScenario) -> str:
    if scenario == PromptScenario.INITIAL_REPORT:
        return (
            "场景说明:\n"
            "- 这是首轮报告。必须围绕教学骨架完整介绍仓库。\n"
            "- 用户可见 Markdown 的顺序必须贴合：概览、先抓什么、仓库映射、语言与类型、关键目录、入口候选、"
            "推荐第一步、阅读路径、不确定项、下一步建议。\n"
            "- initial_report_content 只能复述或重组现有教学骨架，不得新增没有证据的新结论。"
        )
    if scenario == PromptScenario.GOAL_SWITCH:
        return (
            "场景说明:\n"
            "- 这是目标切换确认。focus 先明确“接下来改为聚焦什么”。\n"
            "- message_type 对应 goal_switch_confirmation。"
        )
    if scenario == PromptScenario.DEPTH_ADJUSTMENT:
        return (
            "场景说明:\n"
            "- 这是深浅调整。focus 先明确“讲解深度已调整”。\n"
            "- 不改变学习目标，只改变表达粒度。"
        )
    if scenario == PromptScenario.STAGE_SUMMARY:
        return (
            "场景说明:\n"
            "- 这是阶段性总结。优先总结已讲内容、未展开内容和自然下一步。\n"
            "- 重点利用 explained_items 和 history_summary。"
        )
    return (
        "场景说明:\n"
        "- 这是多轮追问。优先使用 topic_slice 对应内容回答。\n"
        "- 如果用户问题超出 topic_slice，可基于 teaching_skeleton 的相关字段保守补充。"
    )


def _output_requirements(input_data: PromptBuildInput) -> str:
    required_sections = ", ".join(input_data.output_contract.required_sections)
    return (
        f"- 先输出用户可读 Markdown，再输出 <json_output>JSON</json_output>。\n"
        f"- required_sections 顺序: {required_sections}\n"
        f"- max_core_points: {input_data.output_contract.max_core_points}\n"
        f"- must_include_next_steps: {str(input_data.output_contract.must_include_next_steps).lower()}\n"
        f"- must_mark_uncertainty: {str(input_data.output_contract.must_mark_uncertainty).lower()}\n"
        f"- must_use_candidate_wording: {str(input_data.output_contract.must_use_candidate_wording).lower()}\n"
        f"- next_steps / suggested_next_questions 必须 1-3 条，短句、可点击、自然。"
    )


def _json_schema_for_scenario(scenario: PromptScenario) -> str:
    if scenario == PromptScenario.INITIAL_REPORT:
        return (
            "{\n"
            '  "initial_report_content": {\n'
            '    "overview": {"summary": "...", "confidence": "high|medium|low|unknown", "evidence_refs": ["..."]},\n'
            '    "focus_points": [{"focus_id": "...", "topic": "overview|structure|entry|flow|module|dependency|layer|summary", "title": "...", "reason": "...", "related_refs": []}],\n'
            '    "repo_mapping": [{"concept": "...", "mapped_paths": ["..."], "mapped_module_ids": ["..."], "explanation": "...", "confidence": "high|medium|low|unknown", "evidence_refs": ["..."]}],\n'
            '    "language_and_type": {"primary_language": "...", "project_types": [], "degradation_notice": null},\n'
            '    "key_directories": [{"path": "...", "role": "...", "main_path_role": "main_path|supporting|unknown", "confidence": "high|medium|low|unknown", "evidence_refs": ["..."]}],\n'
            '    "entry_section": {"status": "formed|heuristic|unknown", "entries": [], "fallback_advice": null, "unknown_items": []},\n'
            '    "recommended_first_step": {"target": "...", "reason": "...", "learning_gain": "...", "evidence_refs": ["..."]},\n'
            '    "reading_path_preview": [],\n'
            '    "unknown_section": [],\n'
            '    "suggested_next_questions": [{"suggestion_id": "...", "text": "...", "target_goal": "overview|structure|entry|flow|module|dependency|layer|summary|null", "related_topic_refs": []}]\n'
            "  },\n"
            '  "suggestions": [{"suggestion_id": "...", "text": "...", "target_goal": null, "related_topic_refs": []}],\n'
            '  "used_evidence_refs": ["..."]\n'
            "}"
        )
    return (
        "{\n"
        '  "focus": "...",\n'
        '  "direct_explanation": "...",\n'
        '  "relation_to_overall": "...",\n'
        '  "evidence_lines": [{"text": "...", "evidence_refs": ["..."], "confidence": "high|medium|low|unknown|null"}],\n'
        '  "uncertainties": ["..."],\n'
        '  "next_steps": [{"suggestion_id": "...", "text": "...", "target_goal": "overview|structure|entry|flow|module|dependency|layer|summary|null", "related_topic_refs": []}],\n'
        '  "related_topic_refs": [],\n'
        '  "used_evidence_refs": ["..."]\n'
        "}"
    )
