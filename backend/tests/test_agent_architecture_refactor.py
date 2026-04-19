from __future__ import annotations

import asyncio
import json
from pathlib import Path

from backend.contracts.domain import (
    ConversationState,
    RepositoryContext,
    SessionContext,
)
from backend.contracts.enums import (
    ConversationSubStatus,
    MessageSection,
    ProgressStepKey,
    ProgressStepState,
    PromptScenario,
    SessionStatus,
)
from backend.llm_tools import build_llm_tool_context
from backend.m2_file_tree.tree_scanner import scan_repository_tree
from backend.m5_session.common import utc_now
from backend.m5_session.session_service import SessionService
from backend.m5_session.teaching_service import TeachingService
from backend.m6_response.llm_caller import StreamResult
from backend.m6_response.prompt_builder import build_messages
from backend.m6_response.tool_executor import TOOL_SCHEMAS
from backend.security.safety import build_default_read_policy


def _repository(root: Path) -> RepositoryContext:
    return RepositoryContext(
        repo_id="repo_refactor_test",
        source_type="local_path",
        display_name=root.name,
        input_value=str(root),
        root_path=str(root),
        is_temp_dir=False,
        access_verified=True,
        read_policy=build_default_read_policy(),
    )


def _fixture_repo(name: str) -> Path:
    return Path(__file__).resolve().parent / "fixtures" / name


def _prompt_payload(messages: list[dict[str, str]]) -> dict:
    system_message = messages[0]["content"]
    payload_start = system_message.find('{"scenario"')
    if payload_start < 0:
        raise AssertionError("missing prompt payload")
    return json.loads(system_message[payload_start:])


def _output_contract():
    from backend.contracts.domain import OutputContract

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


def test_chatting_session_no_longer_requires_analysis_or_teaching_skeleton() -> None:
    root = _fixture_repo("source_repo")
    repo = _repository(root)
    file_tree = scan_repository_tree(repo)
    now = utc_now()

    session = SessionContext(
        session_id="sess_refactor",
        status=SessionStatus.CHATTING,
        created_at=now,
        updated_at=now,
        repository=repo,
        file_tree=file_tree,
        conversation=ConversationState(
            current_repo_id=repo.repo_id,
            sub_status=ConversationSubStatus.WAITING_USER,
        ),
        progress_steps=[
            {
                "step_key": ProgressStepKey.REPO_ACCESS,
                "step_state": ProgressStepState.DONE,
            },
            {
                "step_key": ProgressStepKey.FILE_TREE_SCAN,
                "step_state": ProgressStepState.DONE,
            },
        ],
    )

    assert session.status == SessionStatus.CHATTING


def test_llm_tool_context_for_initial_report_uses_only_m1_m2_and_source_tools(
) -> None:
    root = _fixture_repo("source_repo")
    repo = _repository(root)
    file_tree = scan_repository_tree(repo)

    context = build_llm_tool_context(
        repository=repo,
        file_tree=file_tree,
        conversation=ConversationState(current_repo_id=repo.repo_id),
        scenario=PromptScenario.INITIAL_REPORT,
    )

    tool_names = {tool.tool_name for tool in context.tools}
    result_names = {result.tool_name for result in context.tool_results}

    assert "m1.get_repository_context" in result_names
    assert "m2.get_file_tree_summary" in result_names
    assert "m2.list_relevant_files" in result_names
    assert "search_text" not in result_names
    assert "read_file_excerpt" not in result_names
    assert all(not name.startswith("m3.") for name in result_names)
    assert all(not name.startswith("m4.") for name in result_names)
    assert "m2.list_relevant_files" in tool_names
    assert "search_text" in tool_names
    assert "read_file_excerpt" in tool_names
    assert all(not name.startswith("m3.") for name in tool_names)
    assert all(not name.startswith("m4.") for name in tool_names)


def test_initial_report_prompt_input_enables_tool_calls_without_skeleton() -> None:
    root = _fixture_repo("source_repo")
    repo = _repository(root)
    file_tree = scan_repository_tree(repo)
    now = utc_now()
    session = SessionContext(
        session_id="sess_prompt_input",
        status=SessionStatus.ANALYZING,
        created_at=now,
        updated_at=now,
        repository=repo,
        file_tree=file_tree,
        conversation=ConversationState(current_repo_id=repo.repo_id),
    )

    prompt_input = TeachingService().build_initial_report_prompt_input(session)

    assert prompt_input.enable_tool_calls is True
    system_text = build_messages(prompt_input)[0]["content"]
    assert "m4.get_initial_report_skeleton" not in system_text
    assert "m4.get_topic_slice" not in system_text
    assert "teaching_skeleton" not in system_text
    assert "topic_slice" not in system_text


def test_tool_schemas_drop_m3_m4_and_static_repo_kb_tools() -> None:
    names = {schema["function"]["name"] for schema in TOOL_SCHEMAS}

    assert {"m1_get_repository_context", "m2_get_file_tree_summary", "m2_list_relevant_files"}.issubset(names)
    assert {"search_text", "read_file_excerpt"}.issubset(names)
    assert not any(name.startswith(("m3.", "m3_")) for name in names)
    assert not any(name.startswith(("m4.", "m4_")) for name in names)
    assert "get_entry_candidates" not in names
    assert "get_module_map" not in names
    assert "get_reading_path" not in names
    assert "get_evidence" not in names


def test_initial_analysis_uses_tool_streamer_and_prompt_has_no_skeleton_payload() -> None:
    root = _fixture_repo("source_repo")

    captured_messages: list[list[dict[str, str]]] = []
    service = SessionService()

    async def failing_llm_streamer(messages: list[dict[str, str]], **_: object):
        raise AssertionError("initial report should use tool-aware streaming")
        yield ""

    async def tool_streamer(
        messages, *, tools=None, on_content_delta=None, temperature=0.6, max_tokens=None
    ):
        captured_messages.append(messages)
        payload = {
            "initial_report_content": {
                "overview": {"summary": "Repo overview", "confidence": "medium", "evidence_refs": []},
                "focus_points": [],
                "repo_mapping": [],
                "language_and_type": {
                    "primary_language": "Python",
                    "project_types": [],
                    "degradation_notice": None,
                },
                "key_directories": [],
                "entry_section": {
                    "status": "unknown",
                    "entries": [],
                    "fallback_advice": "Need source verification.",
                    "unknown_items": [],
                },
                "recommended_first_step": {
                    "target": "README.md",
                    "reason": "Start from the repo map.",
                    "learning_gain": "Build a first mental model.",
                    "evidence_refs": [],
                },
                "reading_path_preview": [],
                "unknown_section": [],
                "suggested_next_questions": [],
            },
            "suggestions": [],
            "used_evidence_refs": [],
        }
        text = f"## Initial report\nSource-driven walkthrough.\n<json_output>{json.dumps(payload)}</json_output>"
        if on_content_delta is not None:
            await on_content_delta(text)
        return StreamResult(content_chunks=[text], finish_reason="stop")

    service.llm_streamer = failing_llm_streamer
    service.tool_streamer = tool_streamer
    service.create_repo_session(str(root))
    session_id = service.store.active_session.session_id

    async def _collect() -> list:
        return [item async for item in service.run_initial_analysis(session_id)]

    events = asyncio.run(_collect())

    assert captured_messages
    payload = _prompt_payload(captured_messages[0])
    tool_names = {item["tool_name"] for item in payload["tool_context"]["tool_results"]}

    assert events[-1].event_type == "message_completed"
    assert service.get_snapshot(session_id).status == SessionStatus.CHATTING
    assert "m4.get_initial_report_skeleton" not in tool_names
    assert "m4.get_topic_slice" not in tool_names
    assert "teaching_skeleton" not in payload
    assert "topic_slice" not in payload
    assert payload["tool_context"]["available_tool_names"]
    assert all(not name.startswith("m3.") for name in tool_names)
    assert all(not name.startswith("m4.") for name in tool_names)
