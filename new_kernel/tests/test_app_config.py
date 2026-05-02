from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from new_kernel.api.app import _load_root_llm_config_json, create_app


def test_load_root_llm_config_json_accepts_utf8_bom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "api_key": "sk-test",
        "model": "demo-model",
        "base_url": "https://example.test/v1",
        "timeout_seconds": 12.5,
    }
    raw_payload = b"\xef\xbb\xbf" + json.dumps(payload).encode("utf-8")
    seen_encoding: dict[str, str | None] = {}

    def fake_is_file(self: Path) -> bool:
        return True

    def fake_read_text(self: Path, encoding: str | None = None) -> str:
        seen_encoding["value"] = encoding
        return raw_payload.decode(encoding or "utf-8")

    monkeypatch.setattr(Path, "is_file", fake_is_file)
    monkeypatch.setattr(Path, "read_text", fake_read_text)

    config = _load_root_llm_config_json("llm_config.json")

    assert config is not None
    assert config["model"] == "demo-model"
    assert config["base_url"] == "https://example.test/v1"
    assert config["timeout_seconds"] == 12.5
    assert seen_encoding["value"] == "utf-8-sig"


def test_create_app_wires_llm_client_and_turn_runtime_from_valid_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_valid_llm_config(monkeypatch)

    app = create_app(llm_config_path="llm_config.json")
    runtime = app.state.api_runtime

    assert runtime.llm_client is not None
    assert runtime.turn_runtime is not None


def test_chat_message_with_valid_config_does_not_fail_missing_turn_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_valid_llm_config(monkeypatch)
    app = create_app(llm_config_path="llm_config.json")
    session = app.state.api_runtime.session_store.create_session(session_id="sess_config")

    with TestClient(app) as client:
        response = client.post(
            "/api/v4/chat/messages",
            headers={"X-Session-Id": session.session_id},
            json={"message": "请讲一下这个仓库", "mode": "chat"},
        )

    body = response.json()

    assert response.status_code == 409
    assert body["ok"] is False
    assert body["error"]["internal_detail"] != "missing api runtime dependency: turn_runtime"


def _patch_valid_llm_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "new_kernel.api.app._load_root_llm_config_json",
        lambda _explicit_path=None: {
            "api_key": "sk-test",
            "model": "demo-model",
            "base_url": "https://example.test/v1",
            "timeout_seconds": 1,
        },
    )
