from __future__ import annotations

import json
import re
from typing import Any

from backend.contracts.domain import PromptBuildInput
from backend.contracts.enums import PromptScenario

_SECRET_RE = re.compile(
    r"(?:sk-[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9]{16,}|AIza[0-9A-Za-z\-_]{20,})"
)

_SYSTEM_RULES = """
你是 Repo Tutor，一位面向编程初学者的源码仓库教学老师。

你的教学风格：
- 用自然、耐心的语言带着学生理解陌生仓库，不要像在填表。
- 主动带路：每轮结束时告诉学生下一步该看什么、为什么。
- 先讲观察框架，再映射到当前仓库，最后再进入局部实现细节。
- 每轮围绕 2-5 个核心认知点展开；浅层回答少讲术语，深层回答补证据和实现线索。

你的知识来源：
- 优先基于提供的教学骨架、主题切片、会话状态和历史摘要回答。
- 当骨架没有直接覆盖用户问题时，可以基于编程常识和当前仓库上下文合理补充，但必须标注“根据推断”或“可能”。
- 对入口、流程、分层、依赖等不确定结论，使用“候选”“可能”“目前证据更支持”等措辞。
- 证据不足时明确说“目前不确定”，不要硬编运行时调用链、真实数据流或不存在的模块职责。

安全规则：
- 不得输出疑似密钥、token、凭据等敏感信息。
- 不得输出内部错误堆栈。

输出格式：
- 先输出给用户看的 Markdown 正文，保持教学语言自然可读。
- 正文结束后，另起一行输出 <json_output>...</json_output> 包裹的结构化 JSON，用于系统解析。
""".strip()


def build_messages(input_data: PromptBuildInput) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    system_parts = [
        _SYSTEM_RULES,
        f"当前场景: {input_data.scenario}",
        f"讲解深度: {input_data.depth_level}",
        _scenario_guidance(input_data.scenario),
        _output_requirements(input_data),
        "JSON 结构要求:\n" + _json_schema_for_scenario(input_data.scenario),
        "以下是当前仓库的教学参考素材（教学骨架、主题切片、会话状态和历史摘要），请基于这些素材回答：",
        json.dumps(_build_payload(input_data), ensure_ascii=False, indent=2, sort_keys=True),
    ]
    messages.append({"role": "system", "content": "\n\n".join(part for part in system_parts if part)})

    for msg in input_data.conversation_state.messages[-8:]:
        if msg.role == "user":
            messages.append({"role": "user", "content": _sanitize_value(msg.raw_text)})
        elif msg.role == "agent":
            visible = _strip_json_output(msg.raw_text)
            if len(visible) > 1500:
                visible = visible[:1500] + "\n...(已截断)"
            messages.append({"role": "assistant", "content": _sanitize_value(visible)})

    current_user_text = _sanitize_value(input_data.user_message or "")
    if current_user_text and (
        not messages
        or messages[-1].get("role") != "user"
        or messages[-1].get("content") != current_user_text
    ):
        messages.append({"role": "user", "content": current_user_text})

    return messages


def _strip_json_output(text: str) -> str:
    return re.sub(r"<json_output>.*?</json_output>", "", text, flags=re.DOTALL).strip()


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
    conversation.pop("messages", None)
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
        return _SECRET_RE.sub("[redacted_secret]", value)
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
        f"回答建议包含以下部分（自然衔接，不需要机械使用这些标题）：{required_sections}\n"
        f"核心认知点控制在 {input_data.output_contract.max_core_points} 个以内。\n"
        "每轮结尾给出 1-3 条下一步建议，语气像在带学生继续读仓库。\n"
        "不确定的结论必须标注；静态证据不足时不要伪造确定流程。"
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
