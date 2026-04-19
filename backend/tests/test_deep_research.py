from __future__ import annotations

import asyncio
import json
from pathlib import Path

from backend.contracts.domain import RepositoryContext
from backend.contracts.enums import ProgressStepKey, RuntimeEventType, SessionStatus
from backend.m6_response.llm_caller import StreamResult
from backend.m2_file_tree.tree_scanner import scan_repository_tree
from backend.m5_session.session_service import SessionService
from backend.security.safety import build_default_read_policy


def _fixture_repo(name: str) -> Path:
    return Path(__file__).resolve().parent / "fixtures" / name


def _repository(root: Path, repo_id: str = "repo_deep_test") -> RepositoryContext:
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


async def _collect(iterator) -> list:
    return [item async for item in iterator]


def test_select_relevant_source_files_excludes_noise_and_tracks_skip_reasons(
    tmp_path: Path,
) -> None:
    from backend.deep_research.source_selection import select_relevant_source_files

    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "architecture.md").write_text("Architecture notes\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("from src.service import run\n", encoding="utf-8")
    (tmp_path / "src" / "service.py").write_text("def run():\n    return 'ok'\n", encoding="utf-8")
    (tmp_path / "test_service.py").write_text("def test_run():\n    assert True\n", encoding="utf-8")
    (tmp_path / "generated_bundle.py").write_text("GENERATED = True\n", encoding="utf-8")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "lib.py").write_text("def vendored():\n    return True\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=top-secret\n", encoding="utf-8")

    repo = _repository(tmp_path)
    file_tree = scan_repository_tree(repo)

    relevant_files = select_relevant_source_files(file_tree)
    selected_paths = {item.relative_path for item in relevant_files if item.selected}
    skipped = {
        item.relative_path: item.skip_reason for item in relevant_files if not item.selected
    }

    assert {
        "README.md",
        "pyproject.toml",
        "docs/architecture.md",
        "src/app.py",
        "src/service.py",
    }.issubset(selected_paths)
    assert skipped["test_service.py"] == "test_or_fixture"
    assert skipped["generated_bundle.py"] == "build_or_generated"
    assert skipped["vendor/lib.py"] == "vendor_or_dependency"
    assert skipped[".env"] == "sensitive_or_unreadable"


def test_deep_research_analysis_stream_emits_research_progress_and_long_report() -> None:
    service = SessionService()
    service.create_repo_session(
        str(_fixture_repo("source_repo")),
        analysis_mode="deep_research",
    )
    session_id = service.store.active_session.session_id

    events = asyncio.run(_collect(service.run_initial_analysis(session_id)))
    snapshot = service.get_snapshot(session_id)

    progress_keys = {
        event.step_key
        for event in events
        if event.event_type == RuntimeEventType.ANALYSIS_PROGRESS
    }
    research_payloads = [
        event.payload.get("research_state")
        for event in events
        if event.event_type == RuntimeEventType.ANALYSIS_PROGRESS and event.payload
    ]

    assert snapshot.status == SessionStatus.CHATTING
    assert snapshot.analysis_mode == "deep_research"
    assert snapshot.deep_research_state is not None
    assert snapshot.deep_research_state.phase == "completed"
    assert snapshot.deep_research_state.completed_files == snapshot.deep_research_state.total_files
    assert snapshot.deep_research_state.total_files >= 2
    assert ProgressStepKey.RESEARCH_PLANNING in progress_keys
    assert ProgressStepKey.SOURCE_SWEEP in progress_keys
    assert ProgressStepKey.CHAPTER_SYNTHESIS in progress_keys
    assert ProgressStepKey.FINAL_REPORT_WRITE in progress_keys
    assert any(payload and payload.get("current_target") for payload in research_payloads)
    assert events[-1].event_type == RuntimeEventType.MESSAGE_COMPLETED
    assert "## Repository Verdict" in snapshot.messages[-1].raw_text
    assert "## File Coverage Appendix" in snapshot.messages[-1].raw_text
    assert snapshot.messages[-1].initial_report_content.overview.summary


def test_deep_research_non_python_repo_degrades_to_quick_guide_progress(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name":"demo"}\n', encoding="utf-8")
    (tmp_path / "index.js").write_text("export function main() { return 1; }\n", encoding="utf-8")

    service = SessionService()

    async def failing_llm_streamer(messages: list[dict[str, str]], **_: object):
        raise AssertionError("degraded initial analysis should still use tool-aware streaming")
        yield ""

    async def tool_streamer(messages, *, tools=None, on_content_delta=None, max_tokens=None):
        payload = {
            "initial_report_content": {
                "overview": {
                    "summary": "Non-Python repo degraded to quick guide mode.",
                    "confidence": "medium",
                    "evidence_refs": ["README.md"],
                },
                "focus_points": [],
                "repo_mapping": [],
                "language_and_type": {
                    "primary_language": "JavaScript",
                    "project_types": [],
                    "degradation_notice": None,
                },
                "key_directories": [],
                "entry_section": {
                    "status": "unknown",
                    "entries": [],
                    "fallback_advice": "Start from README.md.",
                    "unknown_items": [],
                },
                "recommended_first_step": {
                    "target": "README.md",
                    "reason": "Start from the repo map.",
                    "learning_gain": "Build a first mental model.",
                    "evidence_refs": ["README.md"],
                },
                "reading_path_preview": [],
                "unknown_section": [],
                "suggested_next_questions": [],
            },
            "suggestions": [],
            "used_evidence_refs": ["README.md"],
        }
        text = (
            "## Initial report\n"
            "Quick guide fallback.\n"
            f"<json_output>{json.dumps(payload)}</json_output>"
        )
        if on_content_delta is not None:
            await on_content_delta(text)
        return StreamResult(content_chunks=[text], finish_reason="stop")

    service.llm_streamer = failing_llm_streamer
    service.tool_streamer = tool_streamer
    service.create_repo_session(str(tmp_path), analysis_mode="deep_research")
    session_id = service.store.active_session.session_id

    events = asyncio.run(_collect(service.run_initial_analysis(session_id)))
    snapshot = service.get_snapshot(session_id)
    progress_keys = [
        step.step_key
        for step in snapshot.progress_steps
    ]

    assert snapshot.status == SessionStatus.CHATTING
    assert snapshot.analysis_mode == "deep_research"
    assert snapshot.repository.primary_language != "Python"
    assert snapshot.deep_research_state is not None
    assert snapshot.deep_research_state.phase == "degraded_to_quick_guide"
    assert progress_keys == [
        "repo_access",
        "file_tree_scan",
        "initial_report_generation",
    ]
    assert any(
        event.step_key == ProgressStepKey.INITIAL_REPORT_GENERATION
        for event in events
        if event.event_type == RuntimeEventType.ANALYSIS_PROGRESS
    )
    assert snapshot.messages[-1].message_type == "initial_report"
