from __future__ import annotations

import json
import re
from typing import Any

from backend.contracts.domain import PromptBuildInput
from backend.contracts.enums import PromptScenario
from backend.m6_response.tool_executor import api_tool_name

_SECRET_RE = re.compile(
    r"(?:sk-[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9]{16,}|AIza[0-9A-Za-z\-_]{20,})"
)

_SYSTEM_RULES = """
你是 Repo Tutor，负责带用户阅读仓库源码。
原则：
- 优先基于文件树、源码工具结果、当前教学状态和用户问题回答。
- 入口、流程、分层、依赖来源如果没有源码证据，只能写成候选、推测或不确定。
- 可以给很轻的阅读建议，但要明确“这只是建议，不是事实，也不是必须遵循的固定顺序”。
- 回答像老师讲解，不要机械复述字段名。
- 每轮只展开少量核心点，并给出自然的下一步建议。
安全与输出：
- 不输出密钥、token、凭据或内部堆栈。
- 正文用 Markdown。
- 正文结束后，单独输出 `<json_output>{...}</json_output>` 作为机器侧补充。
- 正文必须完整，JSON 只是补充。
""".strip()


def build_messages(input_data: PromptBuildInput) -> list[dict[str, str]]:
    payload = _build_payload(input_data)
    system_parts = [
        _SYSTEM_RULES,
        f"当前场景: {input_data.scenario}",
        f"讲解深度: {input_data.depth_level}",
        _scenario_guidance(input_data.scenario),
        (
            "Use teaching_directive as the only teaching control object. "
            "Do not expose teaching_plan, student_learning_state, teacher_working_log, "
            "or teaching_decision in the visible answer."
        ),
        _tool_calling_guidance(input_data),
        _strict_output_requirements(input_data),
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
        "teaching_directive": _sanitize_value(_teaching_directive(input_data)),
        "output_contract": _sanitize_value(input_data.output_contract.model_dump(mode="json")),
        "conversation_state": _sanitize_conversation(input_data),
        "tool_context": _sanitize_value(_tool_context(input_data)),
    }


def _tool_context(input_data: PromptBuildInput) -> dict[str, Any]:
    if input_data.tool_context is not None:
        context = input_data.tool_context.model_dump(mode="json")
        tools = context.pop("tools", [])
        visible_tools = tools if input_data.enable_tool_calls else []
        context["available_tool_names"] = [
            api_tool_name(str(item.get("tool_name") or ""))
            for item in visible_tools
            if item.get("tool_name")
        ]
        context["tool_name_note"] = (
            "Use available_tool_names exactly when calling tools. Seeded tool_results may use"
            " internal dotted names for traceability."
        )
        context["tool_schema_transport"] = (
            "Function schemas are passed through the API tools parameter, not repeated here."
            if input_data.enable_tool_calls
            else "No function schemas are passed for this turn; rely on seeded tool results."
        )
        return context
    return {
        "policy": "No formal tool context was provided for this turn.",
        "available_tool_names": [],
        "tool_results": [],
        "tool_schema_transport": "No function schemas are passed for this turn.",
    }


def _sanitize_conversation(input_data: PromptBuildInput) -> dict[str, Any]:
    conversation = input_data.conversation_state.model_dump(mode="json")
    for key in (
        "messages",
        "teaching_plan_state",
        "student_learning_state",
        "teacher_working_log",
        "current_teaching_decision",
        "current_teaching_directive",
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
            "- 这是首轮报告，先帮助用户建立仓库地图，再用少量源码核实关键起点。\n"
            "- 你可以轻提示 README、main.py、app.py、配置文件等可能值得先看，但必须明确这只是建议，不是事实。"
        )
    if scenario == PromptScenario.GOAL_SWITCH:
        return "场景说明:\n- 用户正在切换学习目标，先确认新的讲解焦点。"
    if scenario == PromptScenario.DEPTH_ADJUSTMENT:
        return "场景说明:\n- 用户正在调整讲解深浅，保持目标不变，只调整表达粒度。"
    if scenario == PromptScenario.STAGE_SUMMARY:
        return "场景说明:\n- 用户需要阶段总结，回顾已讲内容、未展开内容和自然下一步。"
    return "场景说明:\n- 这是 follow-up 回合，优先围绕用户问题和已验证证据继续推进。"


def _tool_calling_guidance(input_data: PromptBuildInput) -> str:
    if not input_data.enable_tool_calls:
        return ""
    return (
        "工具调用说明:\n"
        "- 先用文件树与相关文件列表缩小范围，再按需搜索或读取源码。\n"
        "- 没有源码证据时，不要把推测写成确定事实。\n"
        "- 轻建议不是固定顺序；如果证据指向别处，应立即调整探索路径。"
    )


def _output_requirements(input_data: PromptBuildInput) -> str:
    required_sections = ", ".join(input_data.output_contract.required_sections)
    return (
        f"回答建议自然覆盖这些部分: {required_sections}\n"
        f"核心点控制在 {input_data.output_contract.max_core_points} 个以内。\n"
        "明确标注不确定性，不伪造运行时细节。"
    )


def _strict_output_requirements(input_data: PromptBuildInput) -> str:
    required_sections = ", ".join(input_data.output_contract.required_sections)
    return (
        f"Cover these parts naturally in the visible answer: {required_sections}\n"
        f"Keep the number of core points within {input_data.output_contract.max_core_points}.\n"
        "Mark uncertainty explicitly and do not invent runtime details.\n"
        "For next_steps / suggested_next_questions, output 1-3 clickable next-step questions or learning actions only.\n"
        "Do not use module responsibility lists, paragraph summaries, caveats, disclaimers, or generic filler as suggestions.\n"
        "If you are not confident about a good next step, return [] for those fields instead of guessing."
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


def _teaching_directive(input_data: PromptBuildInput) -> dict[str, Any]:
    directive = input_data.conversation_state.current_teaching_directive
    if directive is None:
        return {
            "turn_goal": "Answer the current question with source-grounded repository evidence.",
            "mode": "answer",
            "focus_topics": [str(input_data.conversation_state.current_learning_goal)],
            "answer_user_question_first": True,
            "allowed_new_points": 2,
            "must_anchor_to_evidence": True,
            "avoid_repeating_message_ids": [],
            "transition_hint": None,
            "forbidden_behaviors": [
                "Do not mention teaching state, student state, or teaching plan explicitly.",
                "Do not repeat prior explanations unless the user explicitly asks for a recap.",
            ],
        }
    return directive.model_dump(mode="json")


def _teaching_plan(input_data: PromptBuildInput) -> dict[str, Any]:
    plan = input_data.conversation_state.teaching_plan_state
    if plan is None:
        return {
            "opening_focus": [
                "build a repository map",
                "verify one or two likely starting files",
                "keep unknowns explicit",
            ],
            "recommended_first_step": {
                "target": "README.md or a likely entry file",
                "reason": "Start from the repository map, then verify a concrete source location.",
                "learning_gain": "Build a first mental model before diving deeper.",
                "evidence_refs": [],
            },
            "steps": [],
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
