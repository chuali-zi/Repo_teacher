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
    OutputContract,
    OverviewSection,
    ProgressStepStateItem,
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
    LayerType,
    LearningGoal,
    MainPathRole,
    MessageSection,
    PromptScenario,
    ProgressStepKey,
    ProgressStepState,
    SkeletonMode,
    TeachingStage,
    TopicRefType,
)
from backend.m6_response.llm_caller import load_llm_config
from backend.m6_response.prompt_builder import build_prompt
from backend.m6_response.response_parser import parse_final_answer
from backend.m6_response.suggestion_generator import generate_next_step_suggestions


def test_build_prompt_for_follow_up_includes_sanitized_context() -> None:
    prompt = build_prompt(
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
            ),
            history_summary="用户刚看完首轮报告，想继续看启动流程。",
            depth_level=DepthLevel.DEFAULT,
            output_contract=_output_contract(),
        )
    )

    assert "场景: follow_up" in prompt
    assert "启动流程怎么走？" in prompt
    assert "<json_output>" in prompt
    assert "[redacted_path]" not in prompt
    assert '"topic_slice"' in prompt


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
        overview=OverviewSection(summary="这是一个后端 API 服务。", confidence=ConfidenceLevel.HIGH, evidence_refs=[]),
        focus_points=[],
        repo_mapping=[],
        language_and_type=LanguageTypeSection(primary_language="Python", project_types=[], degradation_notice=None),
        key_directories=[
            KeyDirectoryItem(
                path="backend/",
                role="主要后端代码",
                main_path_role=MainPathRole.MAIN_PATH,
                confidence=ConfidenceLevel.HIGH,
                evidence_refs=[],
            )
        ],
        entry_section=EntrySection(status=DerivedStatus.HEURISTIC, entries=[], fallback_advice=None, unknown_items=[]),
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
        _topic_ref("ref_done", LearningGoal.FLOW, "已讲主流程", TopicRefType.FLOW_SUMMARY, "flow_done"),
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
        overview=OverviewSection(summary="仓库概览", confidence=ConfidenceLevel.HIGH, evidence_refs=[]),
        focus_points=[],
        repo_mapping=[],
        language_and_type=LanguageTypeSection(primary_language="Python", project_types=[], degradation_notice=None),
        key_directories=[],
        entry_section=EntrySection(status=DerivedStatus.HEURISTIC, entries=[], fallback_advice=None, unknown_items=[]),
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
        reading_path_preview=[],
        unknown_section=[],
        topic_index=TopicIndex(),
        suggested_next_questions=[],
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
