from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from backend.contracts.domain import FileNode, FileTreeSnapshot, RepositoryContext, SensitiveFileRef
from backend.contracts.enums import (
    AnalysisMode,
    FileNodeStatus,
    FileNodeType,
    ImportSourceType,
    UnknownTopic,
    WarningType,
)
from backend.m3_analysis import run_static_analysis
from backend.security.safety import build_default_read_policy


def _write(root: Path, relative_path: str, content: str) -> Path:
    file_path = root / relative_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    return file_path


def _file_node(
    root: Path,
    relative_path: str,
    *,
    is_python_source: bool,
    status: FileNodeStatus = FileNodeStatus.NORMAL,
) -> FileNode:
    path = root / relative_path
    return FileNode(
        node_id=f"node:{relative_path}",
        relative_path=relative_path.replace("\\", "/"),
        real_path=str(path.resolve()),
        node_type=FileNodeType.FILE,
        extension=path.suffix or None,
        status=status,
        is_source_file=is_python_source,
        is_python_source=is_python_source,
        size_bytes=path.stat().st_size if path.exists() else None,
        depth=len(Path(relative_path).parts),
        parent_path=str(Path(relative_path).parent).replace("\\", "/")
        if len(Path(relative_path).parts) > 1
        else None,
        matched_rule_ids=[],
    )


def _repository(
    root: Path, *, repo_id: str = "repo_test", max_source_files_full_analysis: int = 3000
) -> RepositoryContext:
    read_policy = build_default_read_policy().model_copy(
        update={"max_source_files_full_analysis": max_source_files_full_analysis}
    )
    return RepositoryContext(
        repo_id=repo_id,
        source_type="local_path",
        display_name=root.name,
        input_value=str(root),
        root_path=str(root),
        is_temp_dir=False,
        access_verified=True,
        read_policy=read_policy,
    )


def _file_tree(
    root: Path,
    *,
    repo_id: str,
    nodes: list[FileNode],
    primary_language: str,
    source_code_file_count: int,
    sensitive_matches: list[SensitiveFileRef] | None = None,
) -> FileTreeSnapshot:
    return FileTreeSnapshot(
        snapshot_id=f"snapshot:{repo_id}",
        repo_id=repo_id,
        generated_at=datetime.now(UTC),
        root_path=str(root),
        nodes=nodes,
        ignored_rules=[],
        sensitive_matches=sensitive_matches or [],
        language_stats=[],
        primary_language=primary_language,
        repo_size_level="small",
        source_code_file_count=source_code_file_count,
        degraded_scan_scope=None,
    )


def test_run_static_analysis_builds_python_analysis_bundle(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "app.py",
        "from fastapi import FastAPI\nfrom pkg.service import run\napp = FastAPI()\n\nif __name__ == '__main__':\n    run()\n",
    )
    _write(tmp_path, "pkg/__init__.py", "")
    _write(
        tmp_path,
        "pkg/service.py",
        "import os\nfrom pkg.repo import get_data\n\ndef run():\n    return get_data()\n",
    )
    _write(tmp_path, "pkg/repo.py", "def get_data():\n    return 1\n")
    _write(
        tmp_path,
        "pyproject.toml",
        "[project]\nname = 'demo'\ndependencies = ['fastapi']\n[project.scripts]\ndemo = 'app:app'\n",
    )
    _write(tmp_path, "README.md", "python app.py\n")

    repo = _repository(tmp_path)
    nodes = [
        _file_node(tmp_path, "app.py", is_python_source=True),
        _file_node(tmp_path, "pkg/__init__.py", is_python_source=True),
        _file_node(tmp_path, "pkg/service.py", is_python_source=True),
        _file_node(tmp_path, "pkg/repo.py", is_python_source=True),
        _file_node(tmp_path, "pyproject.toml", is_python_source=False),
        _file_node(tmp_path, "README.md", is_python_source=False),
    ]
    file_tree = _file_tree(
        tmp_path,
        repo_id=repo.repo_id,
        nodes=nodes,
        primary_language="Python",
        source_code_file_count=4,
    )

    analysis = run_static_analysis(repo, file_tree)

    assert analysis.analysis_mode == AnalysisMode.FULL_PYTHON
    assert any(entry.target_value == "app.py" for entry in analysis.entry_candidates)
    assert any(
        item.import_name == "pkg" and item.source_type == ImportSourceType.INTERNAL
        for item in analysis.import_classifications
    )
    assert any(
        item.import_name == "os" and item.source_type == ImportSourceType.STDLIB
        for item in analysis.import_classifications
    )
    assert any(
        item.import_name == "fastapi" and item.source_type == ImportSourceType.THIRD_PARTY
        for item in analysis.import_classifications
    )
    assert any(module.path == "pkg" for module in analysis.module_summaries)
    assert analysis.layer_view.status != "unknown"
    assert analysis.flow_summaries
    assert len(analysis.reading_path) >= 3
    assert analysis.project_profile.primary_language == "Python"


def test_run_static_analysis_ignores_test_entry_candidates(tmp_path: Path) -> None:
    _write(tmp_path, "app.py", "from fastapi import FastAPI\napp = FastAPI()\n")
    _write(tmp_path, "tests/main.py", "if __name__ == '__main__':\n    raise SystemExit(0)\n")
    _write(tmp_path, "test_runner.py", "if __name__ == '__main__':\n    raise SystemExit(0)\n")

    repo = _repository(tmp_path, repo_id="repo_ignore_tests")
    nodes = [
        _file_node(tmp_path, "app.py", is_python_source=True),
        _file_node(tmp_path, "tests/main.py", is_python_source=True, status=FileNodeStatus.IGNORED),
        _file_node(
            tmp_path, "test_runner.py", is_python_source=True, status=FileNodeStatus.IGNORED
        ),
    ]
    file_tree = _file_tree(
        tmp_path,
        repo_id=repo.repo_id,
        nodes=nodes,
        primary_language="Python",
        source_code_file_count=1,
    )

    analysis = run_static_analysis(repo, file_tree)

    assert any(entry.target_value == "app.py" for entry in analysis.entry_candidates)
    assert all(entry.target_value != "tests/main.py" for entry in analysis.entry_candidates)
    assert all(entry.target_value != "test_runner.py" for entry in analysis.entry_candidates)


def test_run_static_analysis_degrades_for_non_python_repository(tmp_path: Path) -> None:
    _write(tmp_path, "src/index.ts", "export const boot = () => 1\n")
    _write(tmp_path, "package.json", '{"name": "demo"}')

    repo = _repository(tmp_path, repo_id="repo_ts")
    nodes = [
        _file_node(tmp_path, "src/index.ts", is_python_source=False),
        _file_node(tmp_path, "package.json", is_python_source=False),
    ]
    file_tree = _file_tree(
        tmp_path,
        repo_id=repo.repo_id,
        nodes=nodes,
        primary_language="TypeScript",
        source_code_file_count=1,
    )

    analysis = run_static_analysis(repo, file_tree)

    assert analysis.analysis_mode == AnalysisMode.DEGRADED_NON_PYTHON
    assert analysis.entry_candidates == []
    assert analysis.import_classifications == []
    assert analysis.flow_summaries == []
    assert analysis.layer_view.status == "unknown"
    assert any(item.topic == UnknownTopic.FLOW for item in analysis.unknown_items)
    assert analysis.reading_path


def test_run_static_analysis_marks_large_repo_mode(tmp_path: Path) -> None:
    _write(tmp_path, "main.py", "if __name__ == '__main__':\n    pass\n")
    _write(tmp_path, "worker.py", "import main\n")

    repo = _repository(tmp_path, repo_id="repo_large", max_source_files_full_analysis=1)
    nodes = [
        _file_node(tmp_path, "main.py", is_python_source=True),
        _file_node(tmp_path, "worker.py", is_python_source=True),
    ]
    file_tree = _file_tree(
        tmp_path,
        repo_id=repo.repo_id,
        nodes=nodes,
        primary_language="Python",
        source_code_file_count=2,
    )

    analysis = run_static_analysis(repo, file_tree)

    assert analysis.analysis_mode == AnalysisMode.DEGRADED_LARGE_REPO
    assert any(warning.type == WarningType.LARGE_REPO_LIMITED for warning in analysis.warnings)


def test_run_static_analysis_reports_sensitive_files_without_reading_content(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "main.py", "if __name__ == '__main__':\n    pass\n")
    secret_path = _write(tmp_path, ".env", "SECRET_KEY=value\n")

    repo = _repository(tmp_path, repo_id="repo_sensitive")
    nodes = [
        _file_node(tmp_path, "main.py", is_python_source=True),
        _file_node(
            tmp_path, ".env", is_python_source=False, status=FileNodeStatus.SENSITIVE_SKIPPED
        ),
    ]
    file_tree = _file_tree(
        tmp_path,
        repo_id=repo.repo_id,
        nodes=nodes,
        primary_language="Python",
        source_code_file_count=1,
        sensitive_matches=[
            SensitiveFileRef(
                relative_path=".env",
                matched_pattern=".env",
                content_read=False,
                user_notice="Sensitive file content was intentionally skipped.",
            )
        ],
    )

    analysis = run_static_analysis(repo, file_tree)

    assert any(warning.type == WarningType.SENSITIVE_FILE_SKIPPED for warning in analysis.warnings)
    assert any(item.topic == UnknownTopic.SECURITY_SKIPPED for item in analysis.unknown_items)
    sensitive_evidence = next(
        item for item in analysis.evidence_catalog if item.source_path == ".env"
    )
    assert sensitive_evidence.is_sensitive_source is True
    assert sensitive_evidence.content_excerpt is None
    assert secret_path.read_text(encoding="utf-8") == "SECRET_KEY=value\n"
