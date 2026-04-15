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
- 记住自己已经讲过什么、下一步准备带学生看什么，保持连续的老师视角。
- 主动带路：每轮结束时告诉学生下一步该看什么、为什么。
- 先讲观察框架，再映射到当前仓库，最后再进入局部实现细节。
- 每轮围绕 2-5 个核心认知点展开；浅层回答少讲术语，深层回答补证据和实现线索。
- 如果已经有教学计划，优先沿计划推进；如果用户临时切换目标，再自然改道，不要僵硬复述旧提纲。
- 根据学生学习状态调节讲法：未见过的主题先补框架，需要强化的主题换一种说法，不要直接跳到细节。
- 教师工作日志是内部备课板，只用于决定本轮怎么教，不要把日志字段逐项暴露给用户。

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
- JSON 是机器侧车，不给用户看；除首轮报告外，JSON 只保留短字段和下一步建议，不要重复整段正文。
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
    messages.append(
        {"role": "system", "content": "\n\n".join(part for part in system_parts if part)}
    )

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
        "teacher_memory": _sanitize_value(_teacher_memory(input_data)),
        "teaching_plan": _sanitize_value(_teaching_plan(input_data)),
        "student_learning_state": _sanitize_value(_student_learning_state(input_data)),
        "teacher_working_log": _sanitize_value(_teacher_working_log(input_data)),
        "teaching_decision": _sanitize_value(_teaching_decision(input_data)),
        "output_contract": _sanitize_value(input_data.output_contract.model_dump(mode="json")),
        "conversation_state": _sanitize_conversation(input_data),
        "topic_slice": _sanitize_value(
            [item.model_dump(mode="json") for item in input_data.topic_slice]
        ),
        "teaching_skeleton": _sanitize_value(input_data.teaching_skeleton.model_dump(mode="json")),
    }


def _sanitize_conversation(input_data: PromptBuildInput) -> dict[str, Any]:
    conversation = input_data.conversation_state.model_dump(mode="json")
    conversation.pop("messages", None)
    conversation.pop("teaching_plan_state", None)
    conversation.pop("student_learning_state", None)
    conversation.pop("teacher_working_log", None)
    conversation.pop("current_teaching_decision", None)
    conversation.pop("teaching_debug_events", None)
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
            "- 你要像第一次带学生读这个仓库的老师，先帮学生建立观察框架，再给一条可执行的教学路线。\n"
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
        "正文要像老师在带学生阅读仓库，而不是在逐项填写结构化表单。\n"
        "先阅读 teaching_decision，它是本轮回答前的教学决策摘要；正文应体现这个决策，但不要机械复述字段名。\n"
        "先看 teacher_working_log 和 teaching_plan 的 active/completed/planned 状态，再决定本轮是推进、回扣还是改道。\n"
        "如果 student_learning_state 标记 needs_reinforcement，先补概念和当前仓库落点，再继续推进。\n"
        "每轮结尾给出 1-3 条下一步建议，语气像在带学生继续读仓库。\n"
        "不确定的结论必须标注；静态证据不足时不要伪造确定流程。"
    )


def _teacher_memory(input_data: PromptBuildInput) -> dict[str, Any]:
    conversation = input_data.conversation_state
    explained_items = [
        {
            "topic": item.topic,
            "item_type": item.item_type,
            "item_id": item.item_id,
            "explained_at_message_id": item.explained_at_message_id,
        }
        for item in conversation.explained_items[-8:]
    ]
    return {
        "current_learning_goal": conversation.current_learning_goal,
        "current_stage": conversation.current_stage,
        "depth_level": input_data.depth_level,
        "already_explained": explained_items,
        "recent_suggestions": [
            item.model_dump(mode="json") for item in conversation.last_suggestions[:3]
        ],
        "history_summary_available": bool(input_data.history_summary),
        "teacher_objective": (
            conversation.teacher_working_log.current_teaching_objective
            if conversation.teacher_working_log
            else None
        ),
    }


def _teaching_plan(input_data: PromptBuildInput) -> dict[str, Any]:
    plan = input_data.conversation_state.teaching_plan_state
    if plan:
        return {
            "plan_id": plan.plan_id,
            "current_step_id": plan.current_step_id,
            "steps": [
                {
                    "step_id": step.step_id,
                    "title": step.title,
                    "goal": step.goal,
                    "target_scope": step.target_scope,
                    "reason": step.reason,
                    "expected_learning_gain": step.expected_learning_gain,
                    "status": step.status,
                    "priority": step.priority,
                    "depends_on": step.depends_on,
                    "source_topic_refs": [
                        item.model_dump(mode="json") for item in step.source_topic_refs[:4]
                    ],
                    "adaptation_note": step.adaptation_note,
                }
                for step in plan.steps[:8]
            ],
            "update_notes": plan.update_notes[-5:],
        }

    skeleton = input_data.teaching_skeleton
    reading_path = [
        {
            "step_no": step.step_no,
            "target": step.target,
            "reason": step.reason,
            "learning_gain": step.learning_gain,
        }
        for step in skeleton.reading_path_preview[:6]
    ]
    return {
        "opening_focus": [item.model_dump(mode="json") for item in skeleton.focus_points[:4]],
        "recommended_first_step": skeleton.recommended_first_step.model_dump(mode="json"),
        "reading_path": reading_path,
        "suggested_next_questions": [
            item.model_dump(mode="json") for item in skeleton.suggested_next_questions[:3]
        ],
    }


def _student_learning_state(input_data: PromptBuildInput) -> dict[str, Any] | None:
    student_state = input_data.conversation_state.student_learning_state
    if not student_state:
        return None
    return {
        "state_id": student_state.state_id,
        "topics": [
            {
                "topic": item.topic,
                "coverage_level": item.coverage_level,
                "confidence_of_estimate": item.confidence_of_estimate,
                "last_explained_at_message_id": item.last_explained_at_message_id,
                "student_signal": item.student_signal,
                "likely_gap": item.likely_gap,
                "recommended_intervention": item.recommended_intervention,
                "supporting_evidence": item.supporting_evidence[-8:],
            }
            for item in student_state.topics[:10]
        ],
        "update_notes": student_state.update_notes[-5:],
    }


def _teacher_working_log(input_data: PromptBuildInput) -> dict[str, Any] | None:
    log = input_data.conversation_state.teacher_working_log
    if not log:
        return None
    return {
        "current_teaching_objective": log.current_teaching_objective,
        "why_now": log.why_now,
        "active_topic_refs": [item.model_dump(mode="json") for item in log.active_topic_refs[:6]],
        "current_plan_step_id": log.current_plan_step_id,
        "planned_transition": log.planned_transition,
        "student_risk_notes": log.student_risk_notes[:5],
        "recent_decisions": log.recent_decisions[-6:],
        "open_questions": log.open_questions[-5:],
    }


def _teaching_decision(input_data: PromptBuildInput) -> dict[str, Any] | None:
    decision = input_data.conversation_state.current_teaching_decision
    if not decision:
        return None
    return {
        "decision_id": decision.decision_id,
        "scenario": decision.scenario,
        "user_message_summary": decision.user_message_summary,
        "selected_action": decision.selected_action,
        "selected_plan_step_id": decision.selected_plan_step_id,
        "selected_plan_step_title": decision.selected_plan_step_title,
        "teaching_objective": decision.teaching_objective,
        "decision_reason": decision.decision_reason,
        "student_state_notes": decision.student_state_notes[:5],
        "planned_transition": decision.planned_transition,
        "topic_refs": [item.model_dump(mode="json") for item in decision.topic_refs[:6]],
    }


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
        '  "focus": "用一句短语概括本轮重点，不要复述全文",\n'
        '  "relation_to_overall": "用一句短句说明和整体的关系",\n'
        '  "next_steps": [{"suggestion_id": "...", "text": "...", "target_goal": "overview|structure|entry|flow|module|dependency|layer|summary|null", "related_topic_refs": []}],\n'
        '  "related_topic_refs": [],\n'
        '  "used_evidence_refs": ["..."]\n'
        "}"
    )
