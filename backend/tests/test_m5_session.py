from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from backend.contracts.domain import (
    ConversationState,
    RepositoryContext,
    StructuredAnswer,
    StructuredMessageContent,
)
from backend.contracts.enums import (
    AgentActivityPhase,
    ConversationSubStatus,
    ConfidenceLevel,
    LearningGoal,
    MessageRole,
    MessageType,
    PromptScenario,
    MessageType,
    RuntimeEventType,
    SessionStatus,
    StudentCoverageLevel,
    TeachingDecisionAction,
    TeachingDebugEventType,
    TeachingPlanStepStatus,
)
from backend.m2_file_tree.tree_scanner import scan_repository_tree
from backend.m5_session.chat_workflow import (
    DEFAULT_CHAT_TURN_TIMEOUT_SECONDS,
    ENV_CHAT_TURN_TIMEOUT_SECONDS,
    load_chat_turn_timeouts,
)
from backend.m5_session.common import utc_now
from backend.m5_session.session_service import SessionService
from backend.m5_session.teaching_state import (
    build_initial_student_learning_state,
    build_initial_teacher_working_log,
    build_initial_teaching_plan,
    update_after_structured_answer,
)
from backend.m6_response.llm_caller import StreamResult, ToolCallRequest
from backend.security.safety import build_default_read_policy


def _fixture_repo(name: str) -> Path:
    return Path(__file__).resolve().parent / "fixtures" / name


def _repository(root: Path, repo_id: str = "repo_state_test") -> RepositoryContext:
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


def _prompt_payload(messages: list[dict[str, str]]) -> dict:
    system_message = messages[0]["content"]
    payload_start = system_message.find('{"scenario"')
    if payload_start < 0:
        raise AssertionError("missing prompt payload")
    return json.loads(system_message[payload_start:])


def _initial_report_text() -> str:
    payload = {
        "initial_report_content": {
            "overview": {"summary": "Small Python repo.", "confidence": "medium", "evidence_refs": []},
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
                "fallback_advice": "Verify source files before teaching the entry path.",
                "unknown_items": [],
            },
            "recommended_first_step": {
                "target": "README.md",
                "reason": "Build a quick map first.",
                "learning_gain": "Understand the repo surface.",
                "evidence_refs": [],
            },
            "reading_path_preview": [],
            "unknown_section": [],
            "suggested_next_questions": [],
        },
        "suggestions": [],
        "used_evidence_refs": [],
    }
    return (
        "## Initial report\n"
        "Start from the repository map, then verify one source file.\n"
        f"<json_output>{json.dumps(payload)}</json_output>"
    )


def _followup_answer_text(label: str = "main.py") -> str:
    payload = {
        "focus": f"Explain {label}.",
        "direct_explanation": f"{label} is a verified source location from the current repo.",
        "relation_to_overall": "The answer stays grounded in source evidence instead of static summaries.",
        "evidence_lines": [
            {
                "text": f"Verified by reading {label}.",
                "evidence_refs": ["ev_source"],
                "confidence": "high",
            }
        ],
        "uncertainties": ["The broader runtime path may still need more source verification."],
        "next_steps": [
            {
                "suggestion_id": "s1",
                "text": "Open app.py next.",
                "target_goal": "flow",
                "related_topic_refs": [],
            }
        ],
        "related_topic_refs": [],
        "used_evidence_refs": ["ev_source"],
    }
    return (
        "## Focus\n"
        f"Explain {label}.\n"
        f"<json_output>{json.dumps(payload)}</json_output>"
    )


def _followup_answer_without_next_steps_text(label: str = "main.py") -> str:
    payload = {
        "focus": f"Explain {label}.",
        "direct_explanation": f"{label} is a verified source location from the current repo.",
        "relation_to_overall": "The answer stays grounded in source evidence instead of static summaries.",
        "evidence_lines": [
            {
                "text": f"Verified by reading {label}.",
                "evidence_refs": ["ev_source"],
                "confidence": "high",
            }
        ],
        "uncertainties": ["The broader runtime path may still need more source verification."],
        "related_topic_refs": [],
        "used_evidence_refs": ["ev_source"],
    }
    return (
        "## Focus\n"
        f"Explain {label}.\n"
        "- It initializes configuration.\n"
        "- It wires the app together.\n"
        f"<json_output>{json.dumps(payload)}</json_output>"
    )


async def _collect(iterator) -> list:
    return [item async for item in iterator]


def _seed_conversation(*, learning_goal: LearningGoal = LearningGoal.OVERVIEW) -> ConversationState:
    repo = _repository(_fixture_repo("source_repo"))
    file_tree = scan_repository_tree(repo)
    now = utc_now()
    plan = build_initial_teaching_plan(file_tree, now=now)
    student_state = build_initial_student_learning_state(now=now)
    teacher_log = build_initial_teacher_working_log(plan, student_state, now=now)
    return ConversationState(
        current_repo_id=repo.repo_id,
        current_learning_goal=learning_goal,
        teaching_plan_state=plan,
        student_learning_state=student_state,
        teacher_working_log=teacher_log,
    )


def _structured_answer() -> StructuredAnswer:
    return StructuredAnswer(
        answer_id="ans_state_1",
        message_type=MessageType.AGENT_ANSWER,
        raw_text="Visible answer.",
        structured_content=StructuredMessageContent(
            focus="Explain the next file.",
            direct_explanation="This answer explains a verified source location.",
            relation_to_overall="It stays grounded in the source tree.",
            evidence_lines=[],
            uncertainties=[],
            next_steps=[],
        ),
        suggestions=[],
        related_topic_refs=[],
        used_evidence_refs=[],
        warnings=[],
    )


def test_analysis_stream_completes_initial_report_for_local_repo() -> None:
    service = SessionService()
    captured_messages: list[list[dict[str, str]]] = []

    async def failing_llm_streamer(messages: list[dict[str, str]], **_: object):
        raise AssertionError("initial analysis should use tool-aware streaming")
        yield ""

    async def tool_streamer(messages, *, tools=None, on_content_delta=None, max_tokens=None):
        captured_messages.append(messages)
        text = _initial_report_text()
        if on_content_delta is not None:
            await on_content_delta(text)
        return StreamResult(content_chunks=[text], finish_reason="stop")

    service.llm_streamer = failing_llm_streamer
    service.tool_streamer = tool_streamer
    service.create_repo_session(str(_fixture_repo("source_repo")))
    session_id = service.store.active_session.session_id
    events = asyncio.run(_collect(service.run_initial_analysis(session_id)))
    snapshot = service.get_snapshot(session_id)
    conversation = service.store.active_session.conversation

    assert captured_messages
    assert events[-1].event_type == RuntimeEventType.MESSAGE_COMPLETED
    assert snapshot.status == SessionStatus.CHATTING
    assert snapshot.sub_status == ConversationSubStatus.WAITING_USER
    assert snapshot.messages[-1].message_type == MessageType.INITIAL_REPORT
    assert snapshot.messages[-1].suggestions == []
    assert conversation.teaching_plan_state is not None
    assert conversation.student_learning_state is not None
    assert conversation.teacher_working_log is not None
    assert conversation.last_suggestions == []
    assert conversation.teaching_plan_state.steps[0].status == TeachingPlanStepStatus.COMPLETED
    assert any(
        step.status == TeachingPlanStepStatus.ACTIVE
        for step in conversation.teaching_plan_state.steps
    )
    overview = next(item for item in conversation.student_learning_state.topics if item.topic == "overview")
    assert overview.coverage_level == StudentCoverageLevel.INTRODUCED
    assert conversation.current_teaching_decision is not None
    assert conversation.current_teaching_decision.selected_action in {
        TeachingDecisionAction.PROCEED_WITH_PLAN,
        TeachingDecisionAction.ANSWER_LOCAL_QUESTION,
    }
    assert TeachingDebugEventType.TEACHING_STATE_INITIALIZED in {
        item.event_type for item in conversation.teaching_debug_events
    }


def test_followup_chat_prompt_payload_has_no_static_analysis_contracts() -> None:
    service = SessionService()
    captured_messages: list[list[dict[str, str]]] = []
    phase = {"value": "initial"}

    async def tool_streamer(messages, *, tools=None, on_content_delta=None, max_tokens=None):
        captured_messages.append(messages)
        if phase["value"] == "initial":
            text = _initial_report_text()
            phase["value"] = "chat"
        else:
            text = _followup_answer_text()
        if on_content_delta is not None:
            await on_content_delta(text)
        return StreamResult(content_chunks=[text], finish_reason="stop")

    service.tool_streamer = tool_streamer
    service.create_repo_session(str(_fixture_repo("source_repo")))
    session_id = service.store.active_session.session_id
    asyncio.run(_collect(service.run_initial_analysis(session_id)))

    service.accept_chat_message(session_id, "How does main.py work?")
    events = asyncio.run(_collect(service.run_chat_turn(session_id)))
    snapshot = service.get_snapshot(session_id)
    payload = _prompt_payload(captured_messages[-1])
    tool_names = {item["tool_name"] for item in payload["tool_context"]["tool_results"]}

    assert events[-1].event_type == RuntimeEventType.MESSAGE_COMPLETED
    assert snapshot.sub_status == ConversationSubStatus.WAITING_USER
    assert snapshot.messages[-2].role == MessageRole.USER
    assert snapshot.messages[-1].message_type == MessageType.AGENT_ANSWER
    assert "teaching_skeleton" not in payload
    assert "topic_slice" not in payload
    assert all(not name.startswith("m3.") for name in tool_names)
    assert all(not name.startswith("m4.") for name in tool_names)
    assert "m1.get_repository_context" in tool_names
    assert "m2.list_relevant_files" in tool_names
    assert payload["tool_context"]["available_tool_names"]


def test_chat_stream_emits_tool_activity_in_same_turn() -> None:
    service = SessionService()
    call_count = 0

    async def tool_streamer(messages, *, tools=None, on_content_delta=None, max_tokens=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            text = _initial_report_text()
            if on_content_delta is not None:
                await on_content_delta(text)
            return StreamResult(content_chunks=[text], finish_reason="stop")
        if call_count == 2:
            return StreamResult(
                tool_calls=[
                    ToolCallRequest(
                        call_id="call_main",
                        function_name="read_file_excerpt",
                        arguments_json=json.dumps({"relative_path": "main.py"}),
                    )
                ],
                finish_reason="tool_calls",
            )
        text = _followup_answer_text()
        if on_content_delta is not None:
            await on_content_delta(text)
        return StreamResult(content_chunks=[text], finish_reason="stop")

    service.tool_streamer = tool_streamer
    service.create_repo_session(str(_fixture_repo("source_repo")))
    session_id = service.store.active_session.session_id
    asyncio.run(_collect(service.run_initial_analysis(session_id)))

    service.accept_chat_message(session_id, "Explain main.py.")
    events = asyncio.run(_collect(service.run_chat_turn(session_id)))
    phases = [
        event.activity.phase
        for event in events
        if event.event_type == RuntimeEventType.AGENT_ACTIVITY
    ]

    assert AgentActivityPhase.PLANNING_TOOL_CALL in phases
    assert AgentActivityPhase.TOOL_RUNNING in phases
    assert AgentActivityPhase.TOOL_SUCCEEDED in phases
    assert events[-1].event_type == RuntimeEventType.MESSAGE_COMPLETED


def test_chat_turn_without_structured_suggestions_keeps_suggestions_empty() -> None:
    service = SessionService()
    phase = {"value": "initial"}

    async def tool_streamer(messages, *, tools=None, on_content_delta=None, max_tokens=None):
        if phase["value"] == "initial":
            text = _initial_report_text()
            phase["value"] = "chat"
        else:
            text = _followup_answer_without_next_steps_text()
        if on_content_delta is not None:
            await on_content_delta(text)
        return StreamResult(content_chunks=[text], finish_reason="stop")

    service.tool_streamer = tool_streamer
    service.create_repo_session(str(_fixture_repo("source_repo")))
    session_id = service.store.active_session.session_id
    asyncio.run(_collect(service.run_initial_analysis(session_id)))

    service.accept_chat_message(session_id, "How does main.py work?")
    events = asyncio.run(_collect(service.run_chat_turn(session_id)))
    snapshot = service.get_snapshot(session_id)
    conversation = service.store.active_session.conversation

    assert events[-1].event_type == RuntimeEventType.MESSAGE_COMPLETED
    assert snapshot.messages[-1].message_type == MessageType.AGENT_ANSWER
    assert snapshot.messages[-1].suggestions == []
    assert conversation.last_suggestions == []


def test_chat_turn_keeps_only_structured_llm_suggestions() -> None:
    service = SessionService()
    phase = {"value": "initial"}

    async def tool_streamer(messages, *, tools=None, on_content_delta=None, max_tokens=None):
        if phase["value"] == "initial":
            text = _initial_report_text()
            phase["value"] = "chat"
        else:
            text = _followup_answer_text()
        if on_content_delta is not None:
            await on_content_delta(text)
        return StreamResult(content_chunks=[text], finish_reason="stop")

    service.tool_streamer = tool_streamer
    service.create_repo_session(str(_fixture_repo("source_repo")))
    session_id = service.store.active_session.session_id
    asyncio.run(_collect(service.run_initial_analysis(session_id)))

    service.accept_chat_message(session_id, "How does main.py work?")
    events = asyncio.run(_collect(service.run_chat_turn(session_id)))
    snapshot = service.get_snapshot(session_id)
    conversation = service.store.active_session.conversation

    assert events[-1].event_type == RuntimeEventType.MESSAGE_COMPLETED
    assert [item.text for item in snapshot.messages[-1].suggestions] == ["Open app.py next."]
    assert [item.text for item in conversation.last_suggestions] == ["Open app.py next."]


def test_followup_answer_does_not_upgrade_student_understanding_without_user_signal() -> None:
    conversation = _seed_conversation()
    overview = next(item for item in conversation.student_learning_state.topics if item.topic == LearningGoal.OVERVIEW)
    overview.coverage_level = StudentCoverageLevel.INTRODUCED
    overview.confidence_of_estimate = ConfidenceLevel.MEDIUM

    update = update_after_structured_answer(
        conversation,
        _structured_answer(),
        user_text="What file should I read next?",
        message_id="msg_agent_followup",
        scenario=PromptScenario.FOLLOW_UP,
        now=utc_now(),
    )

    updated_overview = next(
        item for item in update.student_learning_state.topics if item.topic == LearningGoal.OVERVIEW
    )
    assert updated_overview.coverage_level == StudentCoverageLevel.INTRODUCED


def test_why_question_is_not_treated_as_confusion_signal() -> None:
    conversation = _seed_conversation(learning_goal=LearningGoal.ENTRY)

    update = update_after_structured_answer(
        conversation,
        _structured_answer(),
        user_text="Why does main.py import app.py?",
        message_id="msg_agent_why",
        scenario=PromptScenario.FOLLOW_UP,
        now=utc_now(),
    )

    entry_topic = next(
        item for item in update.student_learning_state.topics if item.topic == LearningGoal.ENTRY
    )
    assert entry_topic.coverage_level == StudentCoverageLevel.INTRODUCED


def test_load_chat_turn_timeouts_defaults_to_six_hundred_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENV_CHAT_TURN_TIMEOUT_SECONDS, raising=False)

    assert load_chat_turn_timeouts().total_seconds == DEFAULT_CHAT_TURN_TIMEOUT_SECONDS == 600.0


def test_load_chat_turn_timeouts_respects_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_CHAT_TURN_TIMEOUT_SECONDS, "420")

    assert load_chat_turn_timeouts().total_seconds == 420.0


def test_chat_stream_keeps_visible_text_after_complete_json_sidecar() -> None:
    service = SessionService()
    phase = {"value": "initial"}

    async def tool_streamer(messages, *, tools=None, on_content_delta=None, max_tokens=None):
        if phase["value"] == "initial":
            phase["value"] = "chat"
            text = _initial_report_text()
            chunks = [text]
        else:
            text = (
                'Visible before marker. <json_output>{"focus":"entry"}</json_output>'
                " Visible after marker."
            )
            chunks = [
                "Visible before marker. <jso",
                'n_output>{"focus":"entry"}',
                "</json_output> Visible after marker.",
            ]
        if on_content_delta is not None:
            for chunk in chunks:
                await on_content_delta(chunk)
        return StreamResult(content_chunks=[text], finish_reason="stop")

    service.tool_streamer = tool_streamer
    service.create_repo_session(str(_fixture_repo("source_repo")))
    session_id = service.store.active_session.session_id
    asyncio.run(_collect(service.run_initial_analysis(session_id)))

    service.accept_chat_message(session_id, "Explain main.py.")
    events = asyncio.run(_collect(service.run_chat_turn(session_id)))

    delta_text = "".join(
        event.message_chunk or ""
        for event in events
        if event.event_type == RuntimeEventType.ANSWER_STREAM_DELTA
    )
    stream_end_indexes = [
        index for index, event in enumerate(events) if event.event_type == RuntimeEventType.ANSWER_STREAM_END
    ]
    last_delta_index = max(
        index
        for index, event in enumerate(events)
        if event.event_type == RuntimeEventType.ANSWER_STREAM_DELTA
    )
    completed_message = next(
        event.payload["message"]["raw_text"]
        for event in reversed(events)
        if event.event_type == RuntimeEventType.MESSAGE_COMPLETED
    )

    assert delta_text == "Visible before marker.  Visible after marker."
    assert completed_message == delta_text
    assert len(stream_end_indexes) == 1
    assert stream_end_indexes[0] > last_delta_index
