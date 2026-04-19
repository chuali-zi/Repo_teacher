from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.contracts.domain import (
    ConversationState,
    MessageRecord,
    OutputContract,
    PromptBuildInput,
    RepositoryContext,
    SessionContext,
)
from backend.contracts.enums import (
    ConversationSubStatus,
    DepthLevel,
    MessageRole,
    MessageSection,
    MessageType,
    PromptScenario,
    SessionStatus,
)
from backend.llm_tools import build_llm_tool_context
from backend.m2_file_tree.tree_scanner import scan_repository_tree
from backend.m5_session.common import utc_now
from backend.m5_session.teaching_service import (
    DEFAULT_MAX_TOOL_ROUNDS,
    ENV_MAX_TOOL_ROUNDS,
    TeachingService,
    load_max_tool_rounds,
)
from backend.m6_response.answer_generator import output_token_budget
from backend.m6_response.llm_caller import load_llm_config
from backend.m6_response.prompt_builder import build_messages
from backend.m6_response.response_parser import parse_final_answer
from backend.m6_response.sidecar_stream import JsonOutputSidecarStripper
from backend.security.safety import build_default_read_policy


def _fixture_repo(name: str) -> Path:
    return Path(__file__).resolve().parent / "fixtures" / name


def _repository(root: Path, repo_id: str = "repo_prompt_test") -> RepositoryContext:
    return RepositoryContext(
        repo_id=repo_id,
        source_type="local_path",
        display_name=root.name,
        input_value=str(root),
        root_path=str(root),
        is_temp_dir=False,
        access_verified=True,
        read_policy=build_default_read_policy(),
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


def _prompt_payload(messages: list[dict[str, str]]) -> dict:
    system_message = messages[0]["content"]
    payload_start = system_message.find('{"scenario"')
    if payload_start < 0:
        raise AssertionError("missing prompt payload")
    return json.loads(system_message[payload_start:])


def test_build_messages_for_follow_up_excludes_static_analysis_contracts() -> None:
    repo = _repository(_fixture_repo("source_repo"))
    file_tree = scan_repository_tree(repo)
    conversation = ConversationState(
        current_repo_id=repo.repo_id,
        sub_status=ConversationSubStatus.AGENT_THINKING,
        messages=[
            MessageRecord(
                message_id="msg_user_1",
                role=MessageRole.USER,
                message_type=MessageType.USER_QUESTION,
                created_at=datetime.now(UTC),
                raw_text="Start with main.py.",
                streaming_complete=True,
            ),
            MessageRecord(
                message_id="msg_agent_1",
                role=MessageRole.AGENT,
                message_type=MessageType.AGENT_ANSWER,
                created_at=datetime.now(UTC),
                raw_text="Visible answer.\n<json_output>{\"focus\":\"entry\"}</json_output>",
                structured_content={
                    "focus": "entry",
                    "direct_explanation": "Read main.py first.",
                    "relation_to_overall": "It is a likely entry file.",
                    "evidence_lines": [],
                    "uncertainties": [],
                    "next_steps": [],
                },
                streaming_complete=True,
            ),
        ],
    )
    tool_context = build_llm_tool_context(
        repository=repo,
        file_tree=file_tree,
        conversation=conversation,
        scenario=PromptScenario.FOLLOW_UP,
    )

    messages = build_messages(
        PromptBuildInput(
            scenario=PromptScenario.FOLLOW_UP,
            user_message="How does main.py work?",
            tool_context=tool_context,
            conversation_state=conversation,
            history_summary="User wants to inspect the likely entry file.",
            depth_level=DepthLevel.DEFAULT,
            output_contract=_output_contract(),
            enable_tool_calls=True,
        )
    )

    system_text = messages[0]["content"]
    assistant_history = [item for item in messages if item["role"] == "assistant"]

    assert "tool_context" in system_text
    assert "available_tool_names" in system_text
    assert "teaching_skeleton" not in system_text
    assert "topic_slice" not in system_text
    assert "m4.get_topic_slice" not in system_text
    assert "return [] for those fields instead of guessing" in system_text
    assert "<json_output>" not in assistant_history[-1]["content"]


def test_build_messages_for_initial_report_uses_teaching_directive_without_verbose_state_sections() -> None:
    repo = _repository(_fixture_repo("source_repo"), repo_id="repo_initial_report")
    file_tree = scan_repository_tree(repo)
    now = utc_now()
    session = SessionContext(
        session_id="sess_initial_report",
        status=SessionStatus.ANALYZING,
        created_at=now,
        updated_at=now,
        repository=repo,
        file_tree=file_tree,
        conversation=ConversationState(current_repo_id=repo.repo_id),
    )
    teaching = TeachingService()
    teaching.initialize_teaching_state(session)

    prompt_input = teaching.build_initial_report_prompt_input(session)
    payload = _prompt_payload(build_messages(prompt_input))

    assert "teacher_memory" in payload
    assert "teaching_directive" in payload
    assert "teaching_plan" not in payload
    assert "student_learning_state" not in payload
    assert "teacher_working_log" not in payload
    assert "teaching_decision" not in payload
    assert payload["teaching_directive"]["answer_user_question_first"] is True
    assert payload["teaching_directive"]["must_anchor_to_evidence"] is True
    assert payload["teaching_directive"]["forbidden_behaviors"]


def test_build_messages_for_follow_up_uses_only_teaching_directive() -> None:
    repo = _repository(_fixture_repo("source_repo"), repo_id="repo_followup_directive")
    file_tree = scan_repository_tree(repo)
    now = utc_now()
    session = SessionContext(
        session_id="sess_followup_directive",
        status=SessionStatus.CHATTING,
        created_at=now,
        updated_at=now,
        repository=repo,
        file_tree=file_tree,
        conversation=ConversationState(
            current_repo_id=repo.repo_id,
            sub_status=ConversationSubStatus.AGENT_THINKING,
            messages=[
                MessageRecord(
                    message_id="msg_user_1",
                    role=MessageRole.USER,
                    message_type=MessageType.USER_QUESTION,
                    created_at=now,
                    raw_text="How does helper.py work?",
                    streaming_complete=True,
                )
            ],
        ),
    )
    teaching = TeachingService()
    teaching.initialize_teaching_state(session)

    prompt_input = teaching.build_prompt_input(session)
    payload = _prompt_payload(build_messages(prompt_input))

    assert "teaching_directive" in payload
    assert "teaching_plan" not in payload
    assert "student_learning_state" not in payload
    assert "teacher_working_log" not in payload
    assert "teaching_decision" not in payload
    assert payload["teaching_directive"]["mode"] == "answer"
    assert payload["teaching_directive"]["focus_topics"]


def test_prompt_build_input_defaults_to_fifty_tool_rounds() -> None:
    prompt_input = PromptBuildInput(
        scenario=PromptScenario.FOLLOW_UP,
        user_message="How does main.py work?",
        tool_context=None,
        conversation_state=ConversationState(current_repo_id="repo_test"),
        history_summary=None,
        depth_level=DepthLevel.DEFAULT,
        output_contract=_output_contract(),
        enable_tool_calls=True,
    )

    assert prompt_input.max_tool_rounds == 50


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("75", 75),
        ("", DEFAULT_MAX_TOOL_ROUNDS),
        ("0", DEFAULT_MAX_TOOL_ROUNDS),
        ("abc", DEFAULT_MAX_TOOL_ROUNDS),
    ],
)
def test_load_max_tool_rounds_respects_env_and_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
    expected: int,
) -> None:
    monkeypatch.setenv(ENV_MAX_TOOL_ROUNDS, raw)

    assert load_max_tool_rounds() == expected


def test_load_max_tool_rounds_defaults_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_MAX_TOOL_ROUNDS, raising=False)

    assert load_max_tool_rounds() == DEFAULT_MAX_TOOL_ROUNDS


def test_output_token_budget_is_raised_for_all_active_scenarios() -> None:
    scenarios = (
        PromptScenario.INITIAL_REPORT,
        PromptScenario.FOLLOW_UP,
        PromptScenario.GOAL_SWITCH,
        PromptScenario.DEPTH_ADJUSTMENT,
        PromptScenario.STAGE_SUMMARY,
    )

    for scenario in scenarios:
        prompt_input = PromptBuildInput(
            scenario=scenario,
            user_message="How does main.py work?",
            tool_context=None,
            conversation_state=ConversationState(current_repo_id="repo_test"),
            history_summary=None,
            depth_level=DepthLevel.DEFAULT,
            output_contract=_output_contract(),
            enable_tool_calls=True,
        )
        assert output_token_budget(prompt_input) == 2400


def test_json_output_sidecar_stripper_handles_chunked_sidecars_and_visible_suffix() -> None:
    stripper = JsonOutputSidecarStripper()

    visible = [
        *stripper.feed("Visible before <jso"),
        *stripper.feed('n_output>{"focus":"x"}'),
        *stripper.feed("</json_output> visible after"),
        *stripper.finish(),
    ]

    assert "".join(visible) == "Visible before  visible after"


def test_parse_final_answer_reads_structured_follow_up_payload() -> None:
    raw_text = """
## Focus
Explain the startup flow.
<json_output>
{
  "focus": "Explain the startup flow.",
  "direct_explanation": "main.py is the visible starting point in the current fixture.",
  "relation_to_overall": "It is the first file to verify before inferring a larger flow.",
  "evidence_lines": [
    {"text": "main.py prints a greeting.", "evidence_refs": ["ev_main"], "confidence": "high"}
  ],
  "uncertainties": ["The full runtime path still needs more source verification."],
  "next_steps": [
    {"suggestion_id": "s1", "text": "Open app.py next.", "target_goal": "flow", "related_topic_refs": []}
  ],
  "related_topic_refs": [],
  "used_evidence_refs": ["ev_main"]
}
</json_output>
""".strip()

    answer = parse_final_answer(PromptScenario.FOLLOW_UP, raw_text)

    assert answer.message_type == "agent_answer"
    assert answer.structured_content.focus == "Explain the startup flow."
    assert answer.structured_content.evidence_lines[0].evidence_refs == ["ev_main"]
    assert answer.suggestions[0].text == "Open app.py next."
    assert answer.structured_content.next_steps[0].text == "Open app.py next."


def test_parse_follow_up_without_structured_next_steps_ignores_visible_bullets() -> None:
    raw_text = """
## Focus
Explain the startup flow.

- It initializes config.
- It wires routes.
- It separates modules by responsibility.
<json_output>
{
  "focus": "Explain the startup flow.",
  "direct_explanation": "main.py is the visible starting point in the current fixture.",
  "relation_to_overall": "It is the first file to verify before inferring a larger flow.",
  "evidence_lines": [],
  "uncertainties": ["The full runtime path still needs more source verification."]
}
</json_output>
""".strip()

    answer = parse_final_answer(PromptScenario.FOLLOW_UP, raw_text)

    assert answer.suggestions == []
    assert answer.structured_content.next_steps == []


def test_parse_follow_up_with_invalid_sidecar_does_not_recover_suggestions_from_visible_bullets() -> None:
    raw_text = """
## Focus
Explain the startup flow.

- It initializes config.
- It wires routes.
<json_output>
{"focus":"Explain the startup flow.","next_steps":[
</json_output>
""".strip()

    answer = parse_final_answer(PromptScenario.FOLLOW_UP, raw_text)

    assert answer.suggestions == []
    assert answer.structured_content.next_steps == []


def test_parse_initial_report_keeps_visible_text_and_sidecar() -> None:
    raw_text = """
## Initial report
Start from the repository map, then verify one source file.
<json_output>
{
  "initial_report_content": {
    "overview": {"summary": "Small Python repo.", "confidence": "medium", "evidence_refs": []},
    "focus_points": [],
    "repo_mapping": [],
    "language_and_type": {"primary_language": "Python", "project_types": [], "degradation_notice": null},
    "key_directories": [],
    "entry_section": {"status": "unknown", "entries": [], "fallback_advice": "Verify source files.", "unknown_items": []},
    "recommended_first_step": {"target": "README.md", "reason": "Build a quick map first.", "learning_gain": "Understand the repo surface.", "evidence_refs": []},
    "reading_path_preview": [],
    "unknown_section": [],
    "suggested_next_questions": []
  },
  "suggestions": [],
  "used_evidence_refs": []
}
</json_output>
""".strip()

    answer = parse_final_answer(PromptScenario.INITIAL_REPORT, raw_text)

    assert answer.message_type == "initial_report"
    assert answer.raw_text == "## Initial report\nStart from the repository map, then verify one source file."
    assert answer.initial_report_content.overview.summary == "Small Python repo."
    assert answer.initial_report_content.recommended_first_step.target == "README.md"
    assert answer.initial_report_content.suggested_next_questions == []


def test_parse_initial_report_without_structured_suggestions_ignores_visible_bullets() -> None:
    raw_text = """
## Initial report
Start from the repository map.

- README.md explains the project.
- main.py looks like an entry file.
<json_output>
{
  "initial_report_content": {
    "overview": {"summary": "Small Python repo.", "confidence": "medium", "evidence_refs": []},
    "focus_points": [],
    "repo_mapping": [],
    "language_and_type": {"primary_language": "Python", "project_types": [], "degradation_notice": null},
    "key_directories": [],
    "entry_section": {"status": "unknown", "entries": [], "fallback_advice": "Verify source files.", "unknown_items": []},
    "recommended_first_step": {"target": "README.md", "reason": "Build a quick map first.", "learning_gain": "Understand the repo surface.", "evidence_refs": []},
    "reading_path_preview": [],
    "unknown_section": [],
    "suggested_next_questions": []
  },
  "used_evidence_refs": []
}
</json_output>
""".strip()

    answer = parse_final_answer(PromptScenario.INITIAL_REPORT, raw_text)

    assert answer.suggestions == []
    assert answer.initial_report_content.suggested_next_questions == []


def test_load_llm_config_reads_visible_json_file() -> None:
    config_path = _fixture_repo("llm_config_demo.json")

    config = load_llm_config(config_path)

    assert config.api_key == "demo-key"
    assert config.base_url == "https://example.com"
    assert config.model == "demo-model"
    assert config.timeout_seconds == 12.0
