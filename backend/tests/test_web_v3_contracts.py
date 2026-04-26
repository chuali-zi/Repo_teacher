from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_web_v3_static_entry_exists() -> None:
    index_html = (ROOT / "web_v3" / "index.html").read_text(encoding="utf-8")

    assert 'id="root"' in index_html
    assert 'name="rt-api-base"' in index_html
    assert './js/services/api.js' in index_html
    assert './js/main.js' in index_html


def test_web_v3_client_exposes_rest_and_sse_api() -> None:
    api_source = (ROOT / "web_v3" / "js" / "services" / "api.js").read_text(
        encoding="utf-8"
    )

    assert 'apiRequest("POST", "/api/repo"' in api_source
    assert 'apiRequest("POST", "/api/repo/validate"' in api_source
    assert 'apiRequest("GET", "/api/session"' in api_source
    assert 'apiRequest("DELETE", "/api/session"' in api_source
    assert 'apiRequest("POST", "/api/chat"' in api_source
    assert 'apiRequest("POST", "/api/sidecar/explain"' in api_source
    assert "new EventSource(url)" in api_source
    assert '"message_completed"' in api_source
    assert '"error"' in api_source


def test_web_v3_main_thread_uses_raw_text_and_stream_deltas() -> None:
    app_source = (ROOT / "web_v3" / "js" / "app.js").read_text(encoding="utf-8")
    components_source = (ROOT / "web_v3" / "js" / "components.js").read_text(
        encoding="utf-8"
    )

    chat_view = components_source[
        components_source.index("// Chat view") : components_source.index("const PxBtn")
    ]
    right_panel = components_source[
        components_source.index("const RightPanel")
        : components_source.index("const DebugOverlay")
    ]

    assert "event.delta_text" in app_source
    assert '(x.raw_text || "") + delta' in app_source
    assert "msg.raw_text || msg.content || \"\"" in chat_view
    assert "structured_content" not in chat_view
    assert "initial_report_content" not in chat_view
    assert "lastAgent.structured_content" in right_panel
    assert "lastAgent.initial_report_content" in right_panel


def test_default_and_legacy_scripts_point_to_expected_frontends() -> None:
    default_all = (ROOT / "scripts" / "dev_all.ps1").read_text(encoding="utf-8")
    default_web = (ROOT / "scripts" / "dev_web.ps1").read_text(encoding="utf-8")
    default_v3 = (ROOT / "scripts" / "dev_v3.ps1").read_text(encoding="utf-8")
    legacy_all = (ROOT / "scripts" / "dev_all_legacy.ps1").read_text(encoding="utf-8")
    legacy_web = (ROOT / "scripts" / "dev_web_legacy.ps1").read_text(encoding="utf-8")

    assert "'web_v3'" in default_all
    assert "'web_v3'" in default_web
    assert "'web_v3'" in default_v3
    assert "5181" in default_all
    assert "5181" in default_web
    assert "5181" in default_v3
    assert "'web'" in legacy_all
    assert "'web'" in legacy_web
    assert "5180" in legacy_all
    assert "5180" in legacy_web


def test_startup_scripts_guard_against_port_conflicts() -> None:
    default_all = (ROOT / "scripts" / "dev_all.ps1").read_text(encoding="utf-8")
    default_web = (ROOT / "scripts" / "dev_web.ps1").read_text(encoding="utf-8")
    legacy_all = (ROOT / "scripts" / "dev_all_legacy.ps1").read_text(encoding="utf-8")
    legacy_web = (ROOT / "scripts" / "dev_web_legacy.ps1").read_text(encoding="utf-8")

    assert "Get-NetTCPConnection" in default_all
    assert "Get-NetTCPConnection" in default_web
    assert "Get-NetTCPConnection" in legacy_all
    assert "Get-NetTCPConnection" in legacy_web
    assert "Assert-PortFree -Port $FrontendPort" in default_all
    assert "Assert-PortFree -Port $FrontendPort" in default_web
    assert "Assert-PortFree -Port 5180" in legacy_all
    assert "Assert-PortFree -Port 5180" in legacy_web
    assert "Assert-PortFree -Port 8000" in default_all
    assert "Assert-PortFree -Port 8000" in legacy_all
