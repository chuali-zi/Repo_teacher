from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from backend.contracts.domain import RuntimeEvent
from backend.contracts.enums import (
    ConversationSubStatus,
    MessageRole,
    MessageType,
    RuntimeEventType,
    SessionStatus,
)
from backend.m5_session import session_service
from backend.m5_session.event_mapper import runtime_event_to_sse
from backend.m5_session.event_streams import iter_analysis_events, iter_chat_events


def test_analysis_stream_completes_initial_report_for_local_repo(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")

    submit = session_service.create_repo_session(str(tmp_path))
    session_id = session_service.store.active_session.session_id
    events = asyncio.run(_collect(iter_analysis_events(session_id)))

    assert submit.status == SessionStatus.ACCESSING
    assert events[0].event_type == RuntimeEventType.STATUS_CHANGED
    assert any(event.event_type == RuntimeEventType.ANALYSIS_PROGRESS for event in events)
    assert events[-1].event_type == RuntimeEventType.MESSAGE_COMPLETED
    assert events[-1].message.message_type == MessageType.INITIAL_REPORT

    snapshot = session_service.get_snapshot(session_service.store.active_session.session_id)
    assert snapshot.status == SessionStatus.CHATTING
    assert snapshot.sub_status == ConversationSubStatus.WAITING_USER
    assert snapshot.messages[-1].message_type == MessageType.INITIAL_REPORT
    assert all(item.step_state == "done" for item in snapshot.progress_steps)

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


def test_chat_stream_completes_followup_answer(tmp_path: Path) -> None:
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
