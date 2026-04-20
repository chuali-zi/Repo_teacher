from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_web_v2_static_entry_exists() -> None:
    index_html = (ROOT / "web_v2" / "index.html").read_text(encoding="utf-8")

    assert 'src="./js/main.js"' in index_html
    assert 'data-role="app-root"' in index_html
    assert 'name="rt-api-base"' in index_html


def test_web_v2_client_uses_raw_text_and_sidecar_api() -> None:
    api_source = (ROOT / "web_v2" / "js" / "api.js").read_text(encoding="utf-8")
    view_source = (ROOT / "web_v2" / "js" / "views.js").read_text(encoding="utf-8")

    assert "/api/sidecar/explain" in api_source
    assert 'request("POST", "/api/sidecar/explain"' in api_source
    assert "raw_text" in view_source
    assert "structured_content" not in view_source
    assert "initial_report_content" not in view_source


def test_default_and_legacy_scripts_point_to_expected_frontends() -> None:
    default_all = (ROOT / "scripts" / "dev_all.ps1").read_text(encoding="utf-8")
    default_web = (ROOT / "scripts" / "dev_web.ps1").read_text(encoding="utf-8")
    legacy_all = (ROOT / "scripts" / "dev_all_legacy.ps1").read_text(encoding="utf-8")
    legacy_web = (ROOT / "scripts" / "dev_web_legacy.ps1").read_text(encoding="utf-8")

    assert "'web_v2'" in default_all
    assert "'web_v2'" in default_web
    assert "'web'" in legacy_all
    assert "'web'" in legacy_web
