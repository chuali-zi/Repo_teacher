# TeachingSlicePicker：从 RepoOverview.entry_candidates 选首个安全文件，读最多 max_lines 行作为 RepoConnectedData.current_code 推送。
from __future__ import annotations

from hashlib import sha1
from pathlib import Path

from ..contracts import TeachingCodeSnippet
from .overview_builder import OverviewEntryCandidate, RepoOverview
from .tree_scanner import ScannedFile, TreeScanResult, is_sensitive_path, resolve_repo_path


class TeachingSlicePicker:
    def __init__(self, *, max_lines: int = 80, max_chars: int = 20_000) -> None:
        self._max_lines = max_lines
        self._max_chars = max_chars

    def pick(self, overview: RepoOverview, scan: TreeScanResult) -> TeachingCodeSnippet | None:
        files_by_path = {file.path: file for file in scan.files}
        for candidate in _candidate_paths(overview, scan):
            scanned_file = files_by_path.get(candidate.path)
            if scanned_file is None or is_sensitive_path(scanned_file.path):
                continue
            snippet = self._read_snippet(scan.repo_root, scanned_file, candidate)
            if snippet is not None:
                return snippet
        return None

    def _read_snippet(
        self,
        repo_root: Path,
        scanned_file: ScannedFile,
        candidate: OverviewEntryCandidate,
    ) -> TeachingCodeSnippet | None:
        file_path = resolve_repo_path(repo_root, scanned_file.path)
        if not file_path.is_file():
            return None

        lines: list[str] = []
        chars_read = 0
        try:
            with file_path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if len(lines) >= self._max_lines or chars_read >= self._max_chars:
                        break
                    lines.append(line.rstrip("\n"))
                    chars_read += len(line)
        except OSError:
            return None

        if not lines:
            return None

        return TeachingCodeSnippet(
            snippet_id=_snippet_id(scanned_file.path),
            path=scanned_file.path,
            language=scanned_file.language,
            start_line=1,
            end_line=len(lines),
            title=Path(scanned_file.path).name,
            reason=candidate.reason,
            code="\n".join(lines),
        )


def _candidate_paths(
    overview: RepoOverview,
    scan: TreeScanResult,
) -> tuple[OverviewEntryCandidate, ...]:
    candidates = list(overview.entry_candidates)
    seen = {candidate.path for candidate in candidates}
    for scanned_file in sorted(
        scan.source_files,
        key=lambda item: (item.depth, item.path.lower()),
    ):
        if scanned_file.path in seen:
            continue
        candidates.append(
            OverviewEntryCandidate(
                path=scanned_file.path,
                language=scanned_file.language,
                reason="source file selected from scan fallback",
                score=1,
            )
        )
        seen.add(scanned_file.path)
    return tuple(candidates)


def _snippet_id(path: str) -> str:
    return f"snippet_{sha1(path.encode('utf-8')).hexdigest()[:12]}"
