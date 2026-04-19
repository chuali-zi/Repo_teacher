from __future__ import annotations

from pathlib import Path


def test_web_render_message_prefers_structured_contracts() -> None:
    source = (Path(__file__).resolve().parents[2] / "web/js/views.js").read_text(
        encoding="utf-8"
    )
    render_message = source[
        source.index("function renderMessage")
        : source.index("function renderActivityBanner")
    ]

    initial_index = render_message.index("renderInitialReport(msg)")
    structured_index = render_message.index("renderStructuredAnswer(msg)")
    raw_index = render_message.index("renderRawMessage(msg)")

    assert initial_index < raw_index
    assert structured_index < raw_index
