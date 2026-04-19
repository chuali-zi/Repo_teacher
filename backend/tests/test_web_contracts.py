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

    assert (
        "renderRawMessage(msg)" in render_message
        or "renderVisibleAgentMessage(msg)" in render_message
    )
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
    path = (
        Path(__file__).resolve().parents[2]
        / "frontend/src/components/AgentMessage.tsx"
    )
    if not path.exists():
        return

    source = path.read_text(encoding="utf-8")

    assert "message.raw_text.trim()" in source
    assert "stripStructuredPayload" not in source
    assert "extractSuggestionHints" not in source
    assert "initial_report_content" not in source
    assert "structured_content" not in source


def test_web_client_exposes_sidecar_explain_api() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "web/js/api.js"
    ).read_text(encoding="utf-8")

    assert "explainSidecar" in source
    assert "/api/sidecar/explain" in source
    assert 'request("POST", "/api/sidecar/explain"' in source


def test_web_sidebar_plugin_renders_small_sidecar_explainer() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "web/js/views.js"
    ).read_text(encoding="utf-8")
    plugins = (
        Path(__file__).resolve().parents[2]
        / "web/js/plugins.js"
    ).read_text(encoding="utf-8")
    sidecar_plugin = (
        Path(__file__).resolve().parents[2]
        / "web/plugins/sidecar_explainer.js"
    ).read_text(encoding="utf-8")
    styles = (
        Path(__file__).resolve().parents[2]
        / "web/css/main.css"
    ).read_text(encoding="utf-8")
    html = (
        Path(__file__).resolve().parents[2]
        / "web/index.html"
    ).read_text(encoding="utf-8")

    assert "renderSidecarPanel" not in source
    assert "submitSidecarQuestion" not in source
    assert "chat-shell" not in html
    assert "chat-sidecar" not in html
    assert 'data-host="sidebar"' in html
    assert './plugins/sidecar_explainer.js' in html
    assert html.index('id="plugin-slot-sidebar"') < html.index('class="sidebar__spacer"')
    assert "export default" in sidecar_plugin
    assert 'api.explainSidecar(question)' in sidecar_plugin
    assert 'ctx.slots?.sidebar' in sidecar_plugin
    assert "plugin-tag" in plugins
    assert ".sidecar-card" in styles
    assert ".plugin-host" in styles
    assert ".plugins-panel .plugin-host" in styles
    assert "overflow-y: auto" in styles
