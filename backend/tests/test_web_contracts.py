from __future__ import annotations

from pathlib import Path


def test_web_render_message_uses_raw_agent_output() -> None:
    source = (Path(__file__).resolve().parents[2] / "web/js/views.js").read_text(
        encoding="utf-8"
    )
    render_message = source[
        source.index("function renderMessage")
        : source.index("function renderActivityBanner")
    ]

    assert "renderRawMessage(msg)" in render_message
    assert "renderInitialReport(msg)" not in render_message
    assert "renderStructuredAnswer(msg)" not in render_message
    assert "initial_report_content" not in render_message
    assert "structured_content" not in render_message


def test_web_suggestions_do_not_read_structured_contracts() -> None:
    source = (Path(__file__).resolve().parents[2] / "web/js/views.js").read_text(
        encoding="utf-8"
    )
    collect_suggestions = source[
        source.index("function collectMessageSuggestions")
        : source.index("function renderMessageHead")
    ]

    assert "msg.suggestions" in collect_suggestions
    assert "initial_report_content" not in collect_suggestions
    assert "structured_content" not in collect_suggestions


def test_legacy_react_agent_message_uses_raw_agent_output() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "frontend/src/components/AgentMessage.tsx"
    ).read_text(encoding="utf-8")

    assert "message.raw_text.trim()" in source
    assert "stripStructuredPayload" not in source
    assert "extractSuggestionHints" not in source
    assert "initial_report_content" not in source
    assert "structured_content" not in source
