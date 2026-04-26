from __future__ import annotations

import asyncio
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Sequence
from uuid import uuid4

import pytest

from new_kernel.contracts import ErrorCode, GithubRepositoryRef, ParseStage, RepositoryStatus
from new_kernel.repo import GithubResolver, OverviewBuilder, RepoModuleError, TeachingSlicePicker
from new_kernel.repo.git_cloner import CloneResult, GitCloner
from new_kernel.repo.parse_pipeline import RepoParsePipeline
from new_kernel.repo.tree_scanner import TreeScanner


TEMP_ROOT = Path(__file__).resolve().parents[2] / "new_kernel" / ".test_tmp"


@contextmanager
def workspace_temp_dir():
    path = TEMP_ROOT / f"repo_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_github_resolver_normalizes_and_reads_default_branch() -> None:
    calls: list[Sequence[str]] = []

    def runner(
        args: Sequence[str],
        *,
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(
            args,
            0,
            stdout="ref: refs/heads/main\tHEAD\nabc123\tHEAD\n",
            stderr="",
        )

    resolver = GithubResolver(runner=runner)

    data = resolver.resolve("https://github.com/openai/example.git/")

    assert data.is_valid is True
    assert data.normalized_url == "https://github.com/openai/example"
    assert data.owner == "openai"
    assert data.repo == "example"
    assert data.default_branch == "main"
    assert calls == [["git", "ls-remote", "--symref", "https://github.com/openai/example", "HEAD"]]

    ref = resolver.resolve_ref("openai/example", branch="dev", verify=False)
    assert ref.normalized_url == "https://github.com/openai/example"
    assert ref.resolved_branch == "dev"


def test_github_resolver_rejects_non_repo_input_without_network() -> None:
    def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("invalid input should not invoke git")

    data = GithubResolver(runner=runner).resolve("https://github.com/openai")

    assert data.is_valid is False
    assert data.input_kind == "unknown"
    assert data.normalized_url is None


def test_tree_scanner_skips_sensitive_ignored_binary_and_large_files() -> None:
    with workspace_temp_dir() as repo_root:
        (repo_root / "src").mkdir()
        (repo_root / "src" / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
        (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")
        (repo_root / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
        (repo_root / ".git").mkdir()
        (repo_root / ".git" / "config").write_text("[remote]\n", encoding="utf-8")
        (repo_root / "node_modules").mkdir()
        (repo_root / "node_modules" / "pkg.js").write_text("ignored()", encoding="utf-8")
        (repo_root / "logo.png").write_bytes(b"\x89PNG\r\n")
        (repo_root / "large.txt").write_text("x" * 128, encoding="utf-8")

        scan = TreeScanner(max_file_size_bytes=64).scan(repo_root)
    paths = {file.path for file in scan.files}
    skipped = {(item.path, item.reason) for item in scan.skipped}

    assert paths == {"README.md", "src/app.py"}
    assert scan.primary_language == "Python"
    assert (".env", "sensitive_path") in skipped
    assert (".git", "ignored_directory") in skipped
    assert ("node_modules", "ignored_directory") in skipped
    assert ("logo.png", "binary_file") in skipped
    assert ("large.txt", "large_file") in skipped


def test_overview_builder_and_slice_picker_choose_entrypoint() -> None:
    with workspace_temp_dir() as repo_root:
        (repo_root / "src").mkdir()
        (repo_root / "src" / "app.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")
        (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")

        scan = TreeScanner().scan(repo_root)
        overview = OverviewBuilder().build(scan)
        snippet = TeachingSlicePicker(max_lines=1).pick(overview, scan)

    assert len(overview.text.splitlines()) <= 50
    assert overview.entry_candidates[0].path == "src/app.py"
    assert snippet is not None
    assert snippet.path == "src/app.py"
    assert snippet.start_line == 1
    assert snippet.end_line == 1
    assert "def main" in snippet.code


def test_parse_pipeline_returns_result_and_emits_structured_callbacks() -> None:
    order: list[tuple[str, str]] = []
    connected = []

    with workspace_temp_dir() as temp:
        repo_root = temp / "repo"
        (repo_root / "src").mkdir(parents=True)
        (repo_root / "src" / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")

        def status_sink(status: object) -> None:
            order.append(("status", getattr(status, "phase")))

        def log_sink(log: object) -> None:
            order.append(("log", getattr(log, "stage")))

        def connected_sink(data: object) -> None:
            connected.append(data)
            order.append(("connected", getattr(data, "repository").repo_id))

        pipeline = RepoParsePipeline(
            resolver=FakeResolver(),
            cloner=FakeCloner(repo_root),
            repo_id_factory=lambda: "repo_test",
        )

        result = asyncio.run(
            pipeline.run(
                session_id="sess_test",
                input_value="https://github.com/acme/demo",
                status_sink=status_sink,
                log_sink=log_sink,
                connected_sink=connected_sink,
            )
        )

    assert result.repository.repo_id == "repo_test"
    assert result.repository.status == RepositoryStatus.READY
    assert result.repository.github.commit_sha == "abc123"
    assert result.current_code is not None
    assert result.current_code.path == "src/app.py"
    assert [log.stage for log in result.parse_log] == [
        ParseStage.VALIDATING_URL,
        ParseStage.RESOLVING_METADATA,
        ParseStage.CLONING,
        ParseStage.SCANNING_TREE,
        ParseStage.BUILDING_OVERVIEW,
        ParseStage.SELECTING_TEACHING_SLICE,
        ParseStage.COMPLETED,
    ]
    assert connected and connected[0].repository.repo_id == "repo_test"
    assert order[-1] == ("connected", "repo_test")
    for index in range(0, len(order) - 1, 2):
        assert order[index][0] == "status"
        assert order[index + 1][0] == "log"


def test_git_cloner_maps_inaccessible_repository() -> None:
    def runner(
        args: Sequence[str],
        *,
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(128, args, stderr="Repository not found")

    ref = GithubRepositoryRef(
        owner="acme",
        repo="missing",
        normalized_url="https://github.com/acme/missing",
        default_branch="main",
        resolved_branch="main",
    )

    with workspace_temp_dir() as temp:
        with pytest.raises(RepoModuleError) as exc_info:
            GitCloner(runner=runner).clone(ref, destination_root=temp)

    assert exc_info.value.error.error_code == ErrorCode.GITHUB_REPO_INACCESSIBLE


class FakeResolver:
    def resolve_ref(
        self,
        input_value: str,
        *,
        branch: str | None = None,
        verify: bool = True,
    ) -> GithubRepositoryRef:
        assert input_value == "https://github.com/acme/demo"
        assert verify is True
        return GithubRepositoryRef(
            owner="acme",
            repo="demo",
            normalized_url="https://github.com/acme/demo",
            default_branch="main",
            resolved_branch=branch or "main",
        )


class FakeCloner:
    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def clone(
        self,
        ref: GithubRepositoryRef,
        *,
        branch: str | None = None,
        destination_root: Path | None = None,
    ) -> CloneResult:
        assert ref.owner == "acme"
        assert destination_root is None
        return CloneResult(
            repo_root=self._repo_root,
            commit_sha="abc123",
            branch=branch or ref.resolved_branch,
            is_temp_dir=False,
        )
