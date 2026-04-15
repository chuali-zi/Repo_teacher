from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.contracts.domain import RuntimeEvent
from backend.contracts.enums import (
    ConversationSubStatus,
    ErrorCode,
    LearningGoal,
    MessageRole,
    MessageType,
    RuntimeEventType,
    SessionStatus,
    StudentCoverageLevel,
    TeachingDebugEventType,
    TeachingDecisionAction,
    TeachingPlanStepStatus,
)
from backend.m5_session import session_service
from backend.m5_session.event_mapper import runtime_event_to_sse
from backend.m5_session.event_streams import iter_analysis_events, iter_chat_events


@pytest.fixture(autouse=True)
def fake_llm_streamer():
    captured: list[list[dict[str, str]]] = []
    previous_streamer = session_service.llm_streamer

    async def stream(messages: list[dict[str, str]]):
        captured.append(messages)
        prompt = _message_text(messages)
        if "当前场景: initial_report" in prompt:
            prompt_payload = _prompt_payload(messages)
            skeleton = _tool_payload(prompt_payload, "m4.get_initial_report_skeleton")
            payload = {
                "initial_report_content": {
                    "overview": skeleton["overview"],
                    "focus_points": skeleton["focus_points"],
                    "repo_mapping": skeleton["repo_mapping"],
                    "language_and_type": skeleton["language_and_type"],
                    "key_directories": skeleton["key_directories"],
                    "entry_section": skeleton["entry_section"],
                    "recommended_first_step": skeleton["recommended_first_step"],
                    "reading_path_preview": skeleton["reading_path_preview"],
                    "unknown_section": skeleton["unknown_section"],
                    "suggested_next_questions": skeleton["suggested_next_questions"],
                },
                "suggestions": skeleton["suggested_next_questions"],
                "used_evidence_refs": [],
            }
            first_target = skeleton["recommended_first_step"]["target"]
            text = (
                "## 仓库概览\n"
                f"这个仓库我会先带你抓整体结构，再落到 {first_target} 这个起点。\n\n"
                "## 推荐阅读计划\n"
                f"1. 先看 {first_target}。\n"
                "2. 再回头看关键目录和模块关系。\n"
                f"\n<json_output>{json.dumps(payload, ensure_ascii=False)}</json_output>"
            )
            midpoint = len(text) // 2
            yield text[:midpoint]
            yield text[midpoint:]
            return
        label = _prompt_label(_message_text(messages))
        payload = {
            "focus": f"LLM focus: {label}",
            "direct_explanation": f"LLM direct answer for {label}.",
            "relation_to_overall": "This answer is generated from the M6 prompt context.",
            "evidence_lines": [
                {
                    "text": "M6 received the controlled teaching skeleton and topic slice.",
                    "evidence_refs": [],
                    "confidence": "medium",
                }
            ],
            "uncertainties": ["当前没有额外不确定项。"],
            "next_steps": [
                {
                    "suggestion_id": "s_next",
                    "text": "继续看入口候选。",
                    "target_goal": "entry",
                    "related_topic_refs": [],
                }
            ],
            "related_topic_refs": [],
            "used_evidence_refs": [],
        }
        text = (
            f"## 本轮重点\nLLM answer for {label}."
            f"\n<json_output>{json.dumps(payload)}</json_output>"
        )
        midpoint = len(text) // 2
        yield text[:midpoint]
        yield text[midpoint:]

    session_service.llm_streamer = stream
    yield captured
    session_service.llm_streamer = previous_streamer
    session_service.clear_active_session()


def _message_text(messages: list[dict[str, str]]) -> str:
    return " ".join(message.get("content", "") for message in messages)


def _prompt_label(prompt: str) -> str:
    for candidate in (
        "second question",
        "first question",
        "question for reconnect",
        "这个仓库先看哪里？",
        "q3",
        "q2",
        "q1",
    ):
        if candidate in prompt:
            return candidate
    return "follow-up question"


def _prompt_payload(messages: list[dict[str, str]]) -> dict:
    system_message = messages[0]["content"]
    marker = "以下是当前仓库的 LLM 工具目录、工具结果、教学状态和历史摘要。工具结果均为只读参考，请基于这些素材回答："
    payload_text = system_message.split(marker, 1)[1].strip()
    return json.loads(payload_text)


def _tool_payload(prompt_payload: dict, tool_name: str) -> dict:
    for result in prompt_payload["tool_context"]["tool_results"]:
        if result["tool_name"] == tool_name:
            return result["payload"]
    raise AssertionError(f"missing tool result: {tool_name}")


def test_analysis_stream_completes_initial_report_for_local_repo(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")

    submit = session_service.create_repo_session(str(tmp_path))
    session_id = session_service.store.active_session.session_id
    events = asyncio.run(_collect(iter_analysis_events(session_id)))

    assert submit.status == SessionStatus.ACCESSING
    assert events[0].event_type == RuntimeEventType.STATUS_CHANGED
    assert any(event.event_type == RuntimeEventType.ANALYSIS_PROGRESS for event in events)
    event_types = [event.event_type for event in events]
    assert event_types.index(RuntimeEventType.ANSWER_STREAM_START) < event_types.index(
        RuntimeEventType.MESSAGE_COMPLETED
    )
    assert any(
        event.event_type == RuntimeEventType.ANALYSIS_PROGRESS
        and event.step_key == "initial_report_generation"
        and event.step_state == "running"
        for event in events
    )
    assert events[-1].event_type == RuntimeEventType.MESSAGE_COMPLETED
    assert events[-1].message.message_type == MessageType.INITIAL_REPORT
    assert events[-1].message.raw_text.startswith("## 仓库概览")

    snapshot = session_service.get_snapshot(session_service.store.active_session.session_id)
    assert snapshot.status == SessionStatus.CHATTING
    assert snapshot.sub_status == ConversationSubStatus.WAITING_USER
    assert snapshot.messages[-1].message_type == MessageType.INITIAL_REPORT
    assert all(item.step_state == "done" for item in snapshot.progress_steps)

    conversation = session_service.store.active_session.conversation
    assert conversation.teaching_plan_state is not None
    assert conversation.student_learning_state is not None
    assert conversation.teacher_working_log is not None
    assert conversation.teaching_plan_state.steps[0].status == TeachingPlanStepStatus.ACTIVE
    overview_state = _topic_state(conversation.student_learning_state, LearningGoal.OVERVIEW)
    assert overview_state.coverage_level == StudentCoverageLevel.INTRODUCED
    assert (
        conversation.teacher_working_log.current_plan_step_id
        == conversation.teaching_plan_state.current_step_id
    )
    assert conversation.current_teaching_decision is not None
    assert conversation.current_teaching_decision.selected_action in {
        TeachingDecisionAction.PROCEED_WITH_PLAN,
        TeachingDecisionAction.ANSWER_LOCAL_QUESTION,
    }
    assert _debug_event_types(conversation)[:2] == [
        TeachingDebugEventType.TEACHING_STATE_INITIALIZED,
        TeachingDebugEventType.TEACHING_PLAN_SELECTED,
    ]
    assert TeachingDebugEventType.TEACHING_DECISION_BUILT in _debug_event_types(conversation)

    session_service.clear_active_session()


def test_analysis_pipeline_uses_m2_m3_m4_outputs(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n",
        encoding="utf-8",
    )
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "service.py").write_text("def run():\n    return 1\n", encoding="utf-8")

    session_service.create_repo_session(str(tmp_path))
    session_id = session_service.store.active_session.session_id
    asyncio.run(_collect(iter_analysis_events(session_id)))

    snapshot = session_service.get_snapshot(session_id)
    initial_report = snapshot.messages[-1].initial_report_content

    assert snapshot.repository.primary_language == "Python"
    assert any(entry.target_value == "app.py" for entry in initial_report.entry_section.entries)
    assert any(item.path == "pkg" for item in initial_report.key_directories)
    assert all(item.path != ".env" for item in initial_report.key_directories)

    session_service.clear_active_session()


def test_chat_stream_completes_followup_answer(tmp_path: Path, fake_llm_streamer) -> None:
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('hi')\n", encoding="utf-8")

    session_service.create_repo_session(str(tmp_path))
    session_id = session_service.store.active_session.session_id
    asyncio.run(_collect(iter_analysis_events(session_id)))

    session_service.accept_chat_message(session_id, "这个仓库先看哪里？")
    events = asyncio.run(_collect(iter_chat_events(session_id)))

    assert events[0].event_type == RuntimeEventType.STATUS_CHANGED
    assert any(event.event_type == RuntimeEventType.ANSWER_STREAM_START for event in events)
    assert events[-1].event_type == RuntimeEventType.MESSAGE_COMPLETED
    assert events[-1].message.message_type == MessageType.AGENT_ANSWER

    snapshot = session_service.get_snapshot(session_id)
    assert snapshot.sub_status == ConversationSubStatus.WAITING_USER
    assert snapshot.messages[-2].role == MessageRole.USER
    assert snapshot.messages[-1].message_type == MessageType.AGENT_ANSWER
    assert fake_llm_streamer
    assert fake_llm_streamer[-1][0]["role"] == "system"
    assert "topic_slice" in _message_text(fake_llm_streamer[-1])
    assert fake_llm_streamer[-1][-1]["role"] == "user"
    assert snapshot.messages[-1].raw_text.startswith("## 本轮重点")
    direct_explanation = snapshot.messages[-1].structured_content.direct_explanation
    assert direct_explanation.startswith("LLM direct answer")
    assert "后续 M2-M4/M6 实现补齐" not in snapshot.messages[-1].raw_text
    assert any("当前场景: initial_report" in _message_text(item) for item in fake_llm_streamer)

    prompt_payload = _prompt_payload(fake_llm_streamer[-1])
    assert "teaching_skeleton" not in prompt_payload
    tool_names = {
        result["tool_name"] for result in prompt_payload["tool_context"]["tool_results"]
    }
    assert "m4.get_topic_slice" in tool_names
    assert "m3.get_entry_candidates" in tool_names
    assert "repo.read_file_excerpt" in tool_names
    assert prompt_payload["teaching_plan"]["steps"]
    assert prompt_payload["student_learning_state"]["topics"]
    assert prompt_payload["teacher_working_log"]["current_teaching_objective"]
    assert prompt_payload["teaching_decision"]["teaching_objective"]
    assert prompt_payload["teaching_decision"]["selected_action"]

    conversation = session_service.store.active_session.conversation
    assert any(
        step.status == TeachingPlanStepStatus.ACTIVE
        for step in conversation.teaching_plan_state.steps
    )
    structure_state = _topic_state(conversation.student_learning_state, LearningGoal.STRUCTURE)
    assert structure_state.coverage_level in {
        StudentCoverageLevel.INTRODUCED,
        StudentCoverageLevel.PARTIALLY_GRASPED,
    }
    assert structure_state.last_explained_at_message_id == snapshot.messages[-1].message_id
    assert conversation.teacher_working_log.recent_decisions
    debug_event_types = _debug_event_types(conversation)
    assert TeachingDebugEventType.TEACHER_TURN_STARTED in debug_event_types
    assert TeachingDebugEventType.TEACHING_PLAN_UPDATED in debug_event_types
    assert TeachingDebugEventType.STUDENT_STATE_UPDATED in debug_event_types
    assert TeachingDebugEventType.WORKING_LOG_UPDATED in debug_event_types
    assert TeachingDebugEventType.NEXT_TRANSITION_SELECTED in debug_event_types

    session_service.clear_active_session()


def test_chat_stream_ends_visible_answer_before_hidden_json_finishes(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('hi')\n", encoding="utf-8")

    session_service.create_repo_session(str(tmp_path))
    session_id = session_service.store.active_session.session_id
    asyncio.run(_collect(iter_analysis_events(session_id)))

    async def stream_with_slow_hidden_json(messages: list[dict[str, str]]):
        payload = {
            "focus": "先看入口",
            "relation_to_overall": "入口是继续阅读主流程的起点。",
            "next_steps": [
                {
                    "suggestion_id": "s1",
                    "text": "继续看入口候选吗？",
                    "target_goal": "entry",
                    "related_topic_refs": [],
                }
            ],
            "related_topic_refs": [],
            "used_evidence_refs": [],
        }
        yield "## 本轮重点\n先看入口。\n\n## 下一步建议\n- 继续看入口候选吗？\n<json_output>"
        await asyncio.sleep(0)
        yield json.dumps(payload, ensure_ascii=False)
        yield "</json_output>"

    async def read_stream() -> tuple[list[RuntimeEvent], list[RuntimeEvent]]:
        iterator = iter_chat_events(session_id)
        early_events: list[RuntimeEvent] = []
        while True:
            event = await iterator.__anext__()
            early_events.append(event)
            if event.event_type == RuntimeEventType.ANSWER_STREAM_END:
                break
        remaining_events = [event async for event in iterator]
        return early_events, remaining_events

    session_service.llm_streamer = stream_with_slow_hidden_json
    session_service.accept_chat_message(session_id, "入口在哪里？")

    early_events, remaining_events = asyncio.run(read_stream())

    assert early_events[-1].event_type == RuntimeEventType.ANSWER_STREAM_END
    assert all(event.event_type != RuntimeEventType.MESSAGE_COMPLETED for event in early_events)
    assert remaining_events[-1].event_type == RuntimeEventType.MESSAGE_COMPLETED

    session_service.clear_active_session()


def test_chat_stream_completes_consecutive_followup_answers(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('hi')\n", encoding="utf-8")

    session_service.create_repo_session(str(tmp_path))
    session_id = session_service.store.active_session.session_id
    asyncio.run(_collect(iter_analysis_events(session_id)))

    for index in range(1, 4):
        session_service.accept_chat_message(session_id, f"q{index}")
        events = asyncio.run(_collect(iter_chat_events(session_id)))
        snapshot = session_service.get_snapshot(session_id)

        assert any(event.event_type == RuntimeEventType.ANSWER_STREAM_START for event in events)
        assert events[-1].event_type == RuntimeEventType.MESSAGE_COMPLETED
        assert events[-1].message.message_type == MessageType.AGENT_ANSWER
        assert snapshot.sub_status == ConversationSubStatus.WAITING_USER

    snapshot = session_service.get_snapshot(session_id)
    agent_answers = [
        message for message in snapshot.messages if message.message_type == MessageType.AGENT_ANSWER
    ]
    assert len(agent_answers) == 3

    session_service.clear_active_session()


def test_chat_stream_reports_llm_failure_without_fallback_answer(tmp_path: Path) -> None:
    async def failing_streamer(messages: list[dict[str, str]]):
        raise RuntimeError("provider unavailable")
        yield ""

    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('hi')\n", encoding="utf-8")

    session_service.create_repo_session(str(tmp_path))
    session_id = session_service.store.active_session.session_id
    asyncio.run(_collect(iter_analysis_events(session_id)))

    session_service.llm_streamer = failing_streamer
    session_service.accept_chat_message(session_id, "first question")
    events = asyncio.run(_collect(iter_chat_events(session_id)))

    assert events[-1].event_type == RuntimeEventType.ERROR
    assert events[-1].error.error_code == ErrorCode.LLM_API_FAILED

    snapshot = session_service.get_snapshot(session_id)
    assert snapshot.sub_status == ConversationSubStatus.WAITING_USER
    assert snapshot.active_error.error_code == ErrorCode.LLM_API_FAILED
    assert snapshot.messages[-1].role == MessageRole.USER

    session_service.clear_active_session()


def test_pending_chat_turn_does_not_replay_previous_completion(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('hi')\n", encoding="utf-8")

    session_service.create_repo_session(str(tmp_path))
    session_id = session_service.store.active_session.session_id
    asyncio.run(_collect(iter_analysis_events(session_id)))

    session_service.accept_chat_message(session_id, "first question")
    first_events = asyncio.run(_collect(iter_chat_events(session_id)))
    first_answer_id = first_events[-1].message.message_id

    session_service.accept_chat_message(session_id, "second question")
    second_events = asyncio.run(_collect(iter_chat_events(session_id)))
    first_non_status = next(
        event for event in second_events if event.event_type != RuntimeEventType.STATUS_CHANGED
    )

    assert first_non_status.event_type == RuntimeEventType.ANSWER_STREAM_START
    assert second_events[-1].event_type == RuntimeEventType.MESSAGE_COMPLETED
    assert second_events[-1].message.message_id != first_answer_id
    assert "second question" in second_events[-1].message.raw_text

    snapshot = session_service.get_snapshot(session_id)
    assert snapshot.sub_status == ConversationSubStatus.WAITING_USER

    session_service.clear_active_session()


def test_completed_chat_turn_reconnect_replays_latest_completion(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('hi')\n", encoding="utf-8")

    session_service.create_repo_session(str(tmp_path))
    session_id = session_service.store.active_session.session_id
    asyncio.run(_collect(iter_analysis_events(session_id)))

    session_service.accept_chat_message(session_id, "question for reconnect")
    events = asyncio.run(_collect(iter_chat_events(session_id)))
    completed_message = events[-1].message
    message_count = len(session_service.get_snapshot(session_id).messages)

    reconnect_events = asyncio.run(_collect(iter_chat_events(session_id)))

    assert [event.event_type for event in reconnect_events] == [
        RuntimeEventType.STATUS_CHANGED,
        RuntimeEventType.MESSAGE_COMPLETED,
    ]
    assert reconnect_events[-1].message.message_id == completed_message.message_id
    assert len(session_service.get_snapshot(session_id).messages) == message_count

    session_service.clear_active_session()


def test_analysis_stream_reconnect_returns_final_message_then_closes(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    session_service.create_repo_session(str(tmp_path))
    session_id = session_service.store.active_session.session_id

    asyncio.run(_collect(iter_analysis_events(session_id)))
    reconnect_events = asyncio.run(_collect(iter_analysis_events(session_id)))

    assert reconnect_events[0].event_type == RuntimeEventType.STATUS_CHANGED
    assert reconnect_events[-1].event_type == RuntimeEventType.MESSAGE_COMPLETED
    assert len(reconnect_events) <= 3

    session_service.clear_active_session()


def test_runtime_event_to_sse_maps_message_completed_payload() -> None:
    event = RuntimeEvent(
        event_id="evt_1",
        session_id="sess_1",
        event_type=RuntimeEventType.MESSAGE_COMPLETED,
        occurred_at=datetime.now(UTC),
        status_snapshot=SessionStatus.CHATTING,
        sub_status_snapshot=ConversationSubStatus.WAITING_USER,
        payload={
            "message": {
                "message_id": "msg_1",
                "role": MessageRole.AGENT,
                "message_type": MessageType.AGENT_ANSWER,
                "created_at": "2026-04-12T00:00:00Z",
                "raw_text": "hello",
                "structured_content": {
                    "focus": "f",
                    "direct_explanation": "d",
                    "relation_to_overall": "r",
                    "evidence_lines": [],
                    "uncertainties": [],
                    "next_steps": [],
                },
                "related_goal": None,
                "related_topic_refs": [],
                "suggestions": [],
                "streaming_complete": True,
                "error_state": None,
            }
        },
    )

    sse = runtime_event_to_sse(event)

    assert sse.event_type == RuntimeEventType.MESSAGE_COMPLETED
    assert sse.message.message_type == MessageType.AGENT_ANSWER


async def _collect(iterator) -> list:
    return [item async for item in iterator]


def _topic_state(student_learning_state, goal: LearningGoal):
    return next(item for item in student_learning_state.topics if item.topic == goal)


def _debug_event_types(conversation):
    return [item.event_type for item in conversation.teaching_debug_events]
