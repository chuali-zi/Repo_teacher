from __future__ import annotations

import asyncio
import json
from pathlib import Path

from backend.m5_session import session_service
from backend.routes.analysis import analysis_stream
from backend.routes.chat import chat_stream
from backend.routes.repo import submit_repo
from backend.routes.session import get_session


def _decode_json_response(response_body: bytes) -> dict:
    return json.loads(response_body.decode("utf-8"))


async def _read_streaming_response_body(response) -> str:
    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    return "".join(chunks)


def test_get_session_without_active_session_returns_idle_snapshot() -> None:
    session_service.clear_active_session()

    response = asyncio.run(get_session())

    assert response.status_code == 200
    assert _decode_json_response(response.body) == {
        "ok": True,
        "session_id": None,
        "data": {
            "session_id": None,
            "status": "idle",
            "sub_status": None,
            "view": "input",
            "repository": None,
            "progress_steps": [],
            "degradation_notices": [],
            "messages": [],
            "active_agent_activity": None,
            "active_error": None,
        },
    }


def test_submit_repo_returns_invalid_request_envelope_for_bad_input() -> None:
    session_service.clear_active_session()

    response = asyncio.run(submit_repo(type("Request", (), {"input_value": "not-a-repo"})()))

    payload = _decode_json_response(response.body)
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["session_id"] is None
    assert payload["error"]["error_code"] == "invalid_request"
    assert payload["error"]["stage"] == "idle"


def test_analysis_stream_returns_error_event_for_stale_session() -> None:
    session_service.clear_active_session()

    response = asyncio.run(analysis_stream("sess_stale"))
    body = asyncio.run(_read_streaming_response_body(response))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: error" in body
    assert '"error_code": "invalid_state"' in body


def test_chat_stream_returns_error_event_for_stale_session() -> None:
    session_service.clear_active_session()

    response = asyncio.run(chat_stream("sess_stale"))
    body = asyncio.run(_read_streaming_response_body(response))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: error" in body
    assert '"error_code": "invalid_state"' in body


def test_analysis_stream_stale_session_error_keeps_requested_session_id(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    session_service.create_repo_session(str(tmp_path))

    response = asyncio.run(analysis_stream("sess_stale"))
    body = asyncio.run(_read_streaming_response_body(response))

    assert '"session_id": "sess_stale"' in body

    session_service.clear_active_session()
