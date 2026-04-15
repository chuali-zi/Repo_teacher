from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.contracts.domain import (
    ConfidenceLevel,
    ConversationState,
    DependencySection,
    EntrySection,
    ExplainedItemRef,
    FlowSection,
    InitialReportContent,
    KeyDirectoryItem,
    LanguageTypeSection,
    LayerSection,
    MessageRecord,
    OutputContract,
    OverviewSection,
    PromptBuildInput,
    RecommendedStep,
    TeachingSkeleton,
    TopicIndex,
    TopicRef,
)
from backend.contracts.enums import (
    ConversationSubStatus,
    DerivedStatus,
    DepthLevel,
    LearningGoal,
    MainPathRole,
    MessageSection,
    MessageRole,
    MessageType,
    PromptScenario,
    ReadingTargetType,
    SkeletonMode,
    StudentCoverageLevel,
    TeachingStage,
    TeachingDecisionAction,
    TeachingPlanStepStatus,
    TopicRefType,
)
from backend.m6_response.llm_caller import load_llm_config
from backend.m6_response.prompt_builder import build_messages
from backend.m6_response.response_parser import parse_final_answer
from backend.m6_response.suggestion_generator import generate_next_step_suggestions


def test_build_messages_for_follow_up_includes_context_and_history() -> None:
    messages = build_messages(
        PromptBuildInput(
            scenario=PromptScenario.FOLLOW_UP,
            user_message="启动流程怎么走？",
            teaching_skeleton=_teaching_skeleton(),
            topic_slice=[_topic_ref("ref_flow", LearningGoal.FLOW, "主流程")],
            conversation_state=ConversationState(
                current_repo_id="repo_1",
                current_learning_goal=LearningGoal.FLOW,
                current_stage=TeachingStage.INITIAL_REPORT,
                sub_status=ConversationSubStatus.AGENT_THINKING,
                messages=[
                    MessageRecord(
                        message_id="msg_user_1",
                        role=MessageRole.USER,
                        message_type=MessageType.USER_QUESTION,
                        created_at=datetime.now(UTC),
                        raw_text="先看 backend/main.py",
                        streaming_complete=True,
                    ),
                    MessageRecord(
                        message_id="msg_agent_1",
                        role=MessageRole.AGENT,
                        message_type=MessageType.AGENT_ANSWER,
                        created_at=datetime.now(UTC),
                        raw_text=(
                            "可以先看 backend/main.py。"
                            '\n<json_output>{"focus":"entry"}</json_output>'
                        ),
                        structured_content={
                            "focus": "入口",
                            "direct_explanation": "先看入口。",
                            "relation_to_overall": "入口帮助建立整体认知。",
                            "evidence_lines": [],
                            "uncertainties": [],
                            "next_steps": [],
                        },
                        streaming_complete=True,
                    ),
                ],
            ),
            history_summary="用户刚看完首轮报告，想继续看启动流程。",
            depth_level=DepthLevel.DEFAULT,
            output_contract=_output_contract(),
        )
    )

    assert isinstance(messages, list)
    assert len(messages) >= 4
    assert messages[0]["role"] == "system"
    assert "Repo Tutor" in messages[0]["content"]
    assert "topic_slice" in messages[0]["content"]
    assert "backend/main.py" in messages[0]["content"]
    assert "<path_omitted>" not in messages[0]["content"]
    assert messages[-1]["role"] == "user"
    assert "启动流程怎么走？" in messages[-1]["content"]
    assistant_history = [item for item in messages if item["role"] == "assistant"]
    assert assistant_history
    assert "<json_output>" not in assistant_history[-1]["content"]


def test_build_messages_for_initial_report_includes_teacher_memory_and_teaching_plan() -> None:
    now = datetime.now(UTC)
    messages = build_messages(
        PromptBuildInput(
            scenario=PromptScenario.INITIAL_REPORT,
            user_message="请先带我建立这个仓库的整体理解，并给出一条主动引导的阅读计划。",
            teaching_skeleton=_teaching_skeleton(),
            topic_slice=[_topic_ref("ref_structure", LearningGoal.STRUCTURE, "仓库结构")],
            conversation_state=ConversationState(
                current_repo_id="repo_1",
                current_learning_goal=LearningGoal.OVERVIEW,
                current_stage=TeachingStage.NOT_STARTED,
                teaching_plan_state={
                    "plan_id": "plan_1",
                    "generated_from_skeleton_id": "sk_1",
                    "current_step_id": "plan_step_1",
                    "steps": [
                        {
                            "step_id": "plan_step_1",
                            "title": "先定位入口",
                            "goal": LearningGoal.ENTRY,
                            "target_scope": "backend/main.py",
                            "reason": "入口能帮学生建立第一条主线。",
                            "expected_learning_gain": "知道系统从哪里开始看。",
                            "status": TeachingPlanStepStatus.ACTIVE,
                            "priority": 1,
                            "depends_on": [],
                            "source_topic_refs": [],
                            "adaptation_note": None,
                        }
                    ],
                    "update_notes": ["初始化教学计划。"],
                    "updated_at": now,
                },
                student_learning_state={
                    "state_id": "student_1",
                    "topics": [
                        {
                            "topic": LearningGoal.ENTRY,
                            "coverage_level": StudentCoverageLevel.NEEDS_REINFORCEMENT,
                            "confidence_of_estimate": ConfidenceLevel.MEDIUM,
                            "last_explained_at_message_id": "msg_1",
                            "student_signal": "用户说入口没懂。",
                            "likely_gap": "入口概念还没有和仓库文件连起来。",
                            "recommended_intervention": "先换一种说法补框架。",
                            "supporting_evidence": [],
                        }
                    ],
                    "update_notes": ["入口需要强化。"],
                    "updated_at": now,
                },
                teacher_working_log={
                    "log_id": "log_1",
                    "current_teaching_objective": "补清楚入口和仓库起点",
                    "why_now": "学生还没有把入口和文件位置连起来。",
                    "active_topic_refs": [],
                    "current_plan_step_id": "plan_step_1",
                    "planned_transition": "补完入口后再进入主流程。",
                    "student_risk_notes": ["entry: 入口需要强化。"],
                    "recent_decisions": ["根据学生信号先补入口。"],
                    "open_questions": [],
                    "updated_at": now,
                },
                current_teaching_decision={
                    "decision_id": "decision_1",
                    "scenario": PromptScenario.INITIAL_REPORT,
                    "user_message_summary": "请先带我建立这个仓库的整体理解",
                    "selected_action": TeachingDecisionAction.REINFORCE_STUDENT_GAP,
                    "selected_plan_step_id": "plan_step_1",
                    "selected_plan_step_title": "先定位入口",
                    "teaching_objective": "先补清楚入口",
                    "decision_reason": "学生状态表显示入口需要强化。",
                    "student_state_notes": ["entry: 先换一种说法补框架。"],
                    "planned_transition": "补完入口后再进入主流程。",
                    "topic_refs": [],
                    "created_at": now,
                },
            ),
            history_summary=None,
            depth_level=DepthLevel.DEFAULT,
            output_contract=_output_contract(),
        )
    )

    assert messages[0]["role"] == "system"
    assert "teacher_memory" in messages[0]["content"]
    assert "teaching_plan" in messages[0]["content"]
    assert "student_learning_state" in messages[0]["content"]
    assert "teacher_working_log" in messages[0]["content"]
    assert "teaching_decision" in messages[0]["content"]
    assert "reinforce_student_gap" in messages[0]["content"]
    assert "needs_reinforcement" in messages[0]["content"]
    assert "backend/main.py" in messages[0]["content"]


def test_parse_final_answer_reads_structured_follow_up_payload() -> None:
    raw_text = """
## 本轮重点
先解释启动流程。

<json_output>
{
  "focus": "先解释启动流程。",
  "direct_explanation": "当前证据更支持从 main.py 进入路由注册。",
  "relation_to_overall": "这是用户进入业务逻辑前的第一跳。",
  "evidence_lines": [
    {"text": "backend/main.py 注册了全部路由", "evidence_refs": ["ev_main"], "confidence": "high"}
  ],
  "uncertainties": ["具体运行时参数仍需结合部署方式确认。"],
  "next_steps": [
    {"suggestion_id": "s1", "text": "想继续看某条路由怎么进入服务层吗？", "target_goal": "flow", "related_topic_refs": []}
  ],
  "related_topic_refs": [
    {"ref_id": "ref_flow", "ref_type": "flow_summary", "target_id": "flow_1", "topic": "flow", "summary": "主流程"}
  ],
  "used_evidence_refs": ["ev_main"]
}
</json_output>
""".strip()

    answer = parse_final_answer(PromptScenario.FOLLOW_UP, raw_text)

    assert answer.message_type == "agent_answer"
    assert answer.structured_content.focus == "先解释启动流程。"
    assert answer.structured_content.evidence_lines[0].evidence_refs == ["ev_main"]
    assert len(answer.suggestions) == 1
    assert answer.related_topic_refs[0].target_id == "flow_1"


def test_parse_final_answer_accepts_compact_follow_up_payload() -> None:
    raw_text = """
## 本轮重点
先看入口位置。
## 直接解释
当前可以先从 backend/main.py 开始读。
## 下一步建议
- 继续看入口候选吗？
<json_output>
{
  "focus": "先看入口",
  "next_steps": [
    {"suggestion_id": "s1", "text": "继续看入口候选吗？", "target_goal": "entry", "related_topic_refs": []}
  ],
  "related_topic_refs": [],
  "used_evidence_refs": []
}
</json_output>
""".strip()

    answer = parse_final_answer(PromptScenario.FOLLOW_UP, raw_text)

    assert answer.structured_content.focus == "先看入口"
    assert answer.structured_content.direct_explanation == "当前可以先从 backend/main.py 开始读。"
    assert answer.structured_content.relation_to_overall
    assert answer.suggestions[0].text == "继续看入口候选吗？"


def test_parse_final_answer_falls_back_to_minimum_valid_structure() -> None:
    raw_text = """
## 本轮重点
先看入口位置。

## 直接解释
当前可以先从 backend/main.py 开始读。

## 下一步建议
- 想继续看路由如何挂载吗？
""".strip()

    answer = parse_final_answer(PromptScenario.FOLLOW_UP, raw_text)

    assert answer.message_type == "agent_answer"
    assert answer.structured_content.focus == "先看入口位置。"
    assert answer.structured_content.direct_explanation == "当前可以先从 backend/main.py 开始读。"
    assert answer.structured_content.relation_to_overall is not None
    assert len(answer.suggestions) >= 1
    assert len(answer.structured_content.next_steps) >= 1


def test_parse_initial_report_uses_controlled_payload() -> None:
    content = InitialReportContent(
        overview=OverviewSection(
            summary="这是一个后端 API 服务。", confidence=ConfidenceLevel.HIGH, evidence_refs=[]
        ),
        focus_points=[],
        repo_mapping=[],
        language_and_type=LanguageTypeSection(
            primary_language="Python", project_types=[], degradation_notice=None
        ),
        key_directories=[
            KeyDirectoryItem(
                path="backend/",
                role="主要后端代码",
                main_path_role=MainPathRole.MAIN_PATH,
                confidence=ConfidenceLevel.HIGH,
                evidence_refs=[],
            )
        ],
        entry_section=EntrySection(
            status=DerivedStatus.HEURISTIC, entries=[], fallback_advice=None, unknown_items=[]
        ),
        recommended_first_step=RecommendedStep(
            target="backend/main.py",
            reason="这里负责应用装配。",
            learning_gain="先建立入口认知。",
            evidence_refs=[],
        ),
        reading_path_preview=[],
        unknown_section=[],
        suggested_next_questions=[],
    )
    raw_text = (
        "这是首轮报告。\n\n<json_output>{"
        f'"initial_report_content": {content.model_dump_json()}, '
        '"suggestions": [], "used_evidence_refs": []}</json_output>'
    )

    answer = parse_final_answer(PromptScenario.INITIAL_REPORT, raw_text)

    assert answer.message_type == "initial_report"
    assert answer.initial_report_content.overview.summary == "这是一个后端 API 服务。"
    assert answer.initial_report_content.recommended_first_step.target == "backend/main.py"


def test_parse_initial_report_falls_back_when_payload_shape_is_invalid() -> None:
    raw_text = """
这是首轮报告正文。

<json_output>
{
  "initial_report_content": {
    "overview": {"summary": "缺少其他必填字段"}
  },
  "suggestions": []
}
</json_output>
""".strip()

    answer = parse_final_answer(PromptScenario.INITIAL_REPORT, raw_text)

    assert answer.message_type == "initial_report"
    assert answer.raw_text == "这是首轮报告正文。"
    assert answer.initial_report_content.overview.summary == "这是首轮报告正文。"
    assert (
        answer.initial_report_content.recommended_first_step.target == "先查看 README 或主入口文件"
    )


def test_load_llm_config_reads_visible_json_file(tmp_path: Path) -> None:
    config_path = tmp_path / "llm_config.json"
    config_path.write_text(
        '{"api_key":"demo-key","base_url":"https://example.com","model":"demo-model","timeout_seconds":12}',
        encoding="utf-8",
    )

    config = load_llm_config(config_path)

    assert config.api_key == "demo-key"
    assert config.base_url == "https://example.com"
    assert config.model == "demo-model"
    assert config.timeout_seconds == 12.0


def test_load_llm_config_requires_api_key(tmp_path: Path) -> None:
    config_path = tmp_path / "llm_config.json"
    config_path.write_text('{"api_key":""}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="api_key"):
        load_llm_config(config_path)


def test_load_llm_config_uses_defaults_for_optional_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "llm_config.json"
    config_path.write_text('{"api_key":"demo-key"}', encoding="utf-8")

    config = load_llm_config(config_path)

    assert config.base_url == "https://api.deepseek.com"
    assert config.model == "deepseek-chat"
    assert config.timeout_seconds == 60.0


def test_generate_next_step_suggestions_skips_explained_and_limits_to_three() -> None:
    conversation = ConversationState(
        current_repo_id="repo_1",
        current_learning_goal=LearningGoal.FLOW,
        current_stage=TeachingStage.FLOW_EXPLAINED,
        explained_items=[
            ExplainedItemRef(
                item_type=TopicRefType.FLOW_SUMMARY,
                item_id="flow_done",
                topic=LearningGoal.FLOW,
                explained_at_message_id="msg_1",
            )
        ],
    )
    topic_refs = [
        _topic_ref(
            "ref_done", LearningGoal.FLOW, "已讲主流程", TopicRefType.FLOW_SUMMARY, "flow_done"
        ),
        _topic_ref("ref_entry", LearningGoal.ENTRY, "入口候选"),
        _topic_ref("ref_module", LearningGoal.MODULE, "核心模块"),
        _topic_ref("ref_layer", LearningGoal.LAYER, "分层关系"),
        _topic_ref("ref_dep", LearningGoal.DEPENDENCY, "依赖来源"),
    ]

    suggestions = generate_next_step_suggestions(conversation, topic_refs)

    assert len(suggestions) == 3
    assert all(item.text for item in suggestions)
    assert all(item.related_topic_refs for item in suggestions)
    assert all(item.related_topic_refs[0].target_id != "flow_done" for item in suggestions)


def _teaching_skeleton() -> TeachingSkeleton:
    return TeachingSkeleton(
        skeleton_id="sk_1",
        repo_id="repo_1",
        analysis_bundle_id="bundle_1",
        generated_at=datetime.now(UTC),
        skeleton_mode=SkeletonMode.FULL,
        overview=OverviewSection(
            summary="仓库概览", confidence=ConfidenceLevel.HIGH, evidence_refs=[]
        ),
        focus_points=[
            {
                "focus_id": "focus_1",
                "topic": LearningGoal.STRUCTURE,
                "title": "先抓整体结构",
                "reason": "先建立仓库地图再钻进细节。",
                "related_refs": [],
            }
        ],
        repo_mapping=[],
        language_and_type=LanguageTypeSection(
            primary_language="Python", project_types=[], degradation_notice=None
        ),
        key_directories=[],
        entry_section=EntrySection(
            status=DerivedStatus.HEURISTIC, entries=[], fallback_advice=None, unknown_items=[]
        ),
        flow_section=FlowSection(status=DerivedStatus.HEURISTIC, flows=[], fallback_advice=None),
        layer_section=LayerSection(
            status=DerivedStatus.HEURISTIC,
            layer_view={
                "layer_view_id": "layer_1",
                "status": DerivedStatus.HEURISTIC,
                "layers": [],
                "uncertainty_note": None,
                "evidence_refs": [],
            },
            fallback_advice=None,
        ),
        dependency_section=DependencySection(items=[], unknown_count=0, summary=None),
        recommended_first_step=RecommendedStep(
            target="backend/main.py",
            reason="应用入口通常最适合建立整体认知。",
            learning_gain="能先看清应用装配方式。",
            evidence_refs=[],
        ),
        reading_path_preview=[
            {
                "step_no": 1,
                "target": "backend/main.py",
                "target_type": ReadingTargetType.FILE,
                "reason": "先定位应用入口与装配方式。",
                "learning_gain": "先建立入口与整体执行框架。",
                "evidence_refs": [],
            }
        ],
        unknown_section=[],
        topic_index=TopicIndex(),
        suggested_next_questions=[
            {
                "suggestion_id": "s1",
                "text": "想先看入口候选吗？",
                "target_goal": LearningGoal.ENTRY,
                "related_topic_refs": [],
            }
        ],
    )


def _topic_ref(
    ref_id: str,
    goal: LearningGoal,
    summary: str,
    ref_type: TopicRefType = TopicRefType.MODULE_SUMMARY,
    target_id: str | None = None,
) -> TopicRef:
    return TopicRef(
        ref_id=ref_id,
        ref_type=ref_type,
        target_id=target_id or ref_id,
        topic=goal,
        summary=summary,
    )


def _output_contract() -> OutputContract:
    return OutputContract(
        required_sections=[
            MessageSection.FOCUS,
            MessageSection.DIRECT_EXPLANATION,
            MessageSection.RELATION_TO_OVERALL,
            MessageSection.EVIDENCE,
            MessageSection.UNCERTAINTY,
            MessageSection.NEXT_STEPS,
        ],
        max_core_points=4,
        must_include_next_steps=True,
        must_mark_uncertainty=True,
        must_use_candidate_wording=True,
    )
