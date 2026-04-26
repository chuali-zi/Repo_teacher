# OverviewBuilder：把 TreeScanResult 压成 ≤ 50 行的 RepoOverview 文本（primary_language / file_count / top_level_paths / entry_candidates），喂给 OrientPlanner 的 user_template。
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from .tree_scanner import ScannedFile, TreeScanResult


MAX_OVERVIEW_LINES = 50


@dataclass(frozen=True)
class OverviewEntryCandidate:
    path: str
    language: str | None
    reason: str
    score: int


@dataclass(frozen=True)
class RepoOverview:
    text: str
    entry_candidates: tuple[OverviewEntryCandidate, ...]
    top_level_paths: tuple[str, ...]
    primary_language: str | None
    file_count: int


class OverviewBuilder:
    def __init__(self, *, max_lines: int = MAX_OVERVIEW_LINES) -> None:
        self._max_lines = max_lines

    def build(self, scan: TreeScanResult) -> RepoOverview:
        top_level_paths = _top_level_paths(scan)
        candidates = tuple(_rank_entry_candidates(scan.files))
        lines = self._build_lines(scan, top_level_paths, candidates)
        return RepoOverview(
            text="\n".join(lines[: self._max_lines]),
            entry_candidates=candidates,
            top_level_paths=top_level_paths,
            primary_language=scan.primary_language,
            file_count=scan.file_count,
        )

    def _build_lines(
        self,
        scan: TreeScanResult,
        top_level_paths: tuple[str, ...],
        candidates: tuple[OverviewEntryCandidate, ...],
    ) -> list[str]:
        lines = [
            "repo_overview:",
            f"- primary_language: {scan.primary_language or 'unknown'}",
            f"- file_count: {scan.file_count}",
        ]
        if scan.language_counts:
            language_summary = ", ".join(
                f"{language}={count}"
                for language, count in sorted(
                    scan.language_counts.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            )
            lines.append(f"- language_counts: {language_summary}")
        if top_level_paths:
            lines.append("- top_level_paths:")
            lines.extend(f"  - {path}" for path in top_level_paths[:20])
        if candidates:
            lines.append("- entry_candidates:")
            lines.extend(
                f"  - {candidate.path}"
                f" ({candidate.language or 'text'}): {candidate.reason}"
                for candidate in candidates[:12]
            )
        return lines


def _rank_entry_candidates(files: tuple[ScannedFile, ...]) -> list[OverviewEntryCandidate]:
    candidates: list[OverviewEntryCandidate] = []
    for scanned_file in files:
        score, reason = _entry_score(scanned_file)
        if score <= 0:
            continue
        candidates.append(
            OverviewEntryCandidate(
                path=scanned_file.path,
                language=scanned_file.language,
                reason=reason,
                score=score,
            )
        )
    return sorted(candidates, key=lambda item: (-item.score, item.path))[:20]


def _entry_score(scanned_file: ScannedFile) -> tuple[int, str]:
    path = scanned_file.path
    lower_path = path.lower()
    name = PurePosixPath(path).name.lower()
    score = 0
    reason = ""

    if name in {"main.py", "app.py", "server.py", "cli.py", "index.js", "index.ts"}:
        score = 120
        reason = "likely runtime entrypoint"
    elif lower_path in {"src/main.py", "src/app.py", "backend/main.py", "backend/app.py"}:
        score = 115
        reason = "common application entrypoint"
    elif name in {"package.json", "pyproject.toml", "go.mod", "cargo.toml", "pom.xml"}:
        score = 105
        reason = "project metadata and scripts"
    elif name.startswith("readme."):
        score = 90
        reason = "project overview"
    elif scanned_file.is_source and scanned_file.depth <= 3:
        score = 70 - scanned_file.depth
        reason = "near-root source file"
    elif name in {"dockerfile", "makefile", "justfile"}:
        score = 65
        reason = "developer workflow file"

    if scanned_file.size_bytes > 80_000:
        score -= 25
    if "/test" in lower_path or lower_path.startswith("test"):
        score -= 20

    return max(score, 0), reason


def _top_level_paths(scan: TreeScanResult) -> tuple[str, ...]:
    directories = [f"{directory.path}/" for directory in scan.directories if directory.depth == 1]
    files = [file.path for file in scan.files if file.depth == 1]
    return tuple(sorted(directories)[:12] + sorted(files)[:12])
