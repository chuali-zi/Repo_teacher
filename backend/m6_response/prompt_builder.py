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
你是 Repo Tutor，负责带用户阅读仓库源码。

原则：
- 先解释框架，再落到当前仓库证据，最后进入局部实现。
- 优先使用工具结果、教学状态和历史摘要；证据不足时明确标注“根据推断”或“不确定”。
- 回答自然连贯，像老师讲解，不机械复述字段名。
- 每轮只展开少量核心点，并给出自然的下一步建议。

安全与输出：
- 不输出密钥、token、凭据或内部堆栈。
- 正文用 Markdown。
- 正文结束后，单独输出 `<json_output>{...}</json_output>` 作为机器侧车。
- 正文必须完整，JSON 只是补充。
""".strip()


def build_messages(input_data: PromptBuildInput) -> list[dict[str, str]]:
    payload = _build_payload(input_data)
    system_parts = [
        _SYSTEM_RULES,
        f"当前场景: {input_data.scenario}",
        f"讲解深度: {input_data.depth_level}",
        _scenario_guidance(input_data.scenario),
        _tool_calling_guidance(input_data),
        _output_requirements(input_data),
        "JSON 侧车结构:\n" + _json_schema_for_scenario(input_data.scenario),
        "以下是当前仓库的 LLM 工具目录、工具结果、教学状态和历史摘要。工具结果均为只读参考，请基于这些素材回答：",
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    ]
    messages: list[dict[str, str]] = [
        {"role": "system", "content": "\n\n".join(part for part in system_parts if part)}
    ]

    for message in input_data.conversation_state.messages[-6:]:
        if message.role == "user":
            messages.append({"role": "user", "content": _sanitize_value(message.raw_text)})
        elif message.role == "agent":
            visible = _strip_json_output(message.raw_text)
            if len(visible) > 1000:
                visible = visible[:997] + "..."
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
        "selected_topic_refs": _sanitize_value(
            [item.model_dump(mode="json") for item in input_data.topic_slice]
        ),
        "tool_context": _sanitize_value(_tool_context(input_data)),
    }


def _tool_context(input_data: PromptBuildInput) -> dict[str, Any]:
    if input_data.tool_context is not None:
        context = input_data.tool_context.model_dump(mode="json")
        tools = context.pop("tools", [])
        visible_tools = tools if input_data.enable_tool_calls else []
        context["available_tool_names"] = [
            str(item.get("tool_name") or "") for item in visible_tools if item.get("tool_name")
        ]
        context["tool_schema_transport"] = (
            "Function schemas are passed through the API tools parameter, not repeated here."
            if input_data.enable_tool_calls
            else "No function schemas are passed for this turn; rely on seeded tool results."
        )
        return context
    skeleton = input_data.teaching_skeleton
    return {
        "policy": "兼容模式：未传入正式工具上下文，以下仅提供最小教学骨架投影。",
        "tools": [],
        "tool_results": [
            {
                "tool_name": "m4.get_initial_report_skeleton",
                "source_module": "m4_skeleton.skeleton_assembler",
                "summary": "兼容模式下的最小教学骨架投影。",
                "reference_only": True,
                "payload": {
                    "overview": skeleton.overview.model_dump(mode="json"),
                    "focus_points": [
                        item.model_dump(mode="json") for item in skeleton.focus_points[:4]
                    ],
                    "repo_mapping": [
                        item.model_dump(mode="json") for item in skeleton.repo_mapping[:4]
                    ],
                    "language_and_type": skeleton.language_and_type.model_dump(mode="json"),
                    "key_directories": [
                        item.model_dump(mode="json") for item in skeleton.key_directories[:6]
                    ],
                    "entry_section": skeleton.entry_section.model_dump(mode="json"),
                    "recommended_first_step": skeleton.recommended_first_step.model_dump(
                        mode="json"
                    ),
                    "reading_path_preview": [
                        item.model_dump(mode="json")
                        for item in skeleton.reading_path_preview[:4]
                    ],
                    "unknown_section": [
                        item.model_dump(mode="json") for item in skeleton.unknown_section[:4]
                    ],
                    "suggested_next_questions": [
                        item.model_dump(mode="json")
                        for item in skeleton.suggested_next_questions[:3]
                    ],
                },
            },
            {
                "tool_name": "m4.get_topic_slice",
                "source_module": "m4_skeleton.topic_indexer",
                "summary": "兼容模式下的主题切片。",
                "reference_only": True,
                "payload": {
                    "topic_slice": [item.model_dump(mode="json") for item in input_data.topic_slice]
                },
            },
        ],
    }


def _sanitize_conversation(input_data: PromptBuildInput) -> dict[str, Any]:
    conversation = input_data.conversation_state.model_dump(mode="json")
    for key in (
        "messages",
        "teaching_plan_state",
        "student_learning_state",
        "teacher_working_log",
        "current_teaching_decision",
        "teaching_debug_events",
    ):
        conversation.pop(key, None)
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
            "- 这是首轮报告，先帮助用户建立整体仓库地图。\n"
            "- 优先借助教学骨架、入口候选、模块地图和阅读路径组织讲解。"
        )
    if scenario == PromptScenario.GOAL_SWITCH:
        return "场景说明:\n- 用户正在切换学习目标，先确认新的讲解焦点。"
    if scenario == PromptScenario.DEPTH_ADJUSTMENT:
        return "场景说明:\n- 用户正在调整讲解深浅，保持目标不变，只调整表达粒度。"
    if scenario == PromptScenario.STAGE_SUMMARY:
        return "场景说明:\n- 用户需要阶段总结，回顾已讲内容、未展开内容和自然下一步。"
    return "场景说明:\n- 这是 follow-up 回合，优先围绕当前 topic slice 和教学计划继续推进。"


def _tool_calling_guidance(input_data: PromptBuildInput) -> str:
    if not input_data.enable_tool_calls:
        return ""
    return (
        "工具调用说明:\n"
        "- 先用静态分析类工具理解结构，再按需读取源码。\n"
        "- 只有已有证据不足时才调用工具，不要为调用而调用。\n"
        "- 优先高层工具，必要时再用 read_file_excerpt 或 search_text 补代码证据。"
    )


def _output_requirements(input_data: PromptBuildInput) -> str:
    required_sections = ", ".join(input_data.output_contract.required_sections)
    return (
        f"回答建议自然覆盖这些部分: {required_sections}\n"
        f"核心点控制在 {input_data.output_contract.max_core_points} 个以内。\n"
        "明确标注不确定性，不伪造运行时细节。"
    )


def _teacher_memory(input_data: PromptBuildInput) -> dict[str, Any]:
    conversation = input_data.conversation_state
    return {
        "current_learning_goal": conversation.current_learning_goal,
        "current_stage": conversation.current_stage,
        "depth_level": input_data.depth_level,
        "already_explained": [
            {
                "topic": item.topic,
                "item_type": item.item_type,
                "item_id": item.item_id,
                "explained_at_message_id": item.explained_at_message_id,
            }
            for item in conversation.explained_items[-8:]
        ],
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
    if plan is None:
        skeleton = input_data.teaching_skeleton
        return {
            "opening_focus": [
                item.model_dump(mode="json") for item in skeleton.focus_points[:4]
            ],
            "recommended_first_step": skeleton.recommended_first_step.model_dump(mode="json"),
            "reading_path": [
                {
                    "step_no": step.step_no,
                    "target": step.target,
                    "reason": step.reason,
                    "learning_gain": step.learning_gain,
                }
                for step in skeleton.reading_path_preview[:6]
            ],
            "suggested_next_questions": [
                item.model_dump(mode="json") for item in skeleton.suggested_next_questions[:3]
            ],
        }
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


def _student_learning_state(input_data: PromptBuildInput) -> dict[str, Any] | None:
    student_state = input_data.conversation_state.student_learning_state
    if student_state is None:
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
    if log is None:
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
    if decision is None:
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
            "{"
            '"initial_report_content":{"overview":{"summary":"一句话概览","confidence":"high|medium|low|unknown","evidence_refs":[]},'
            '"focus_points":[],"repo_mapping":[],"language_and_type":{"primary_language":"Python","project_types":[],"degradation_notice":null},'
            '"key_directories":[],"entry_section":{"status":"confirmed|heuristic|unknown","entries":[],"fallback_advice":null},'
            '"recommended_first_step":{"target":"先看哪里","reason":"为什么","learning_gain":"学到什么","evidence_refs":[]},'
            '"reading_path_preview":[],"unknown_section":[],"suggested_next_questions":[]},'
            '"suggestions":[{"suggestion_id":"sug_1","text":"下一步建议","target_goal":"overview|structure|entry|flow|module|dependency|layer|summary|null"}]}'
        )
    return (
        "{"
        '"next_steps":[{"suggestion_id":"sug_1","text":"下一步建议","target_goal":"overview|structure|entry|flow|module|dependency|layer|summary|null"}]'
        "}"
    )
