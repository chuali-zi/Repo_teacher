"""Phase 0 Triage: pure-function decision (short vs standard onboarding).

This file holds zero LLM logic and zero I/O. It only inspects ``RepoOverview``
fields in memory and returns a ``TriageDecision``. Behaviour is fully described
by AGENTS.md §3.1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


ReportShape = Literal["short", "standard"]


class _RepoOverviewLike(Protocol):
    """Structural typing: anything overview-like with these read attributes works."""

    text: str
    primary_language: str | None
    file_count: int
    language_counts: dict[str, int]
    top_level_paths: list[str]
    entry_candidates: list  # 不强约束 entry_candidate 内部 shape


@dataclass(frozen=True)
class TriageDecision:
    """Result of Phase 0: which report shape to render and why."""

    report_shape: ReportShape
    reason: str

    @property
    def is_short(self) -> bool:
        return self.report_shape == "short"


class EmptyRepositoryError(Exception):
    """Raised when ``file_count == 0`` so onboarding should not run."""


def triage(overview: _RepoOverviewLike) -> TriageDecision:
    """Decide ``short`` vs ``standard`` onboarding shape; raise on empty repo.

    The four branches mirror AGENTS.md §3.1 verbatim:

    1. ``file_count == 0`` -> raise ``EmptyRepositoryError``.
    2. ``file_count <= 5`` AND ``primary_language is None`` -> short.
    3. ``primary_language in {None, "Markdown", "plaintext"}`` -> short.
    4. otherwise -> standard.
    """

    file_count = int(getattr(overview, "file_count", 0) or 0)
    primary = getattr(overview, "primary_language", None)
    if file_count == 0:
        raise EmptyRepositoryError("仓库无可分析文件，跳过 onboarding。")
    if file_count <= 5 and primary is None:
        return TriageDecision("short", "文件 ≤5 且无主语言，走 short 分支。")
    if primary in {None, "Markdown", "plaintext"}:
        return TriageDecision(
            "short",
            f"主语言为 {primary or 'unknown'}，走 short 分支。",
        )
    return TriageDecision("standard", "走 standard 5 支柱分支。")


__all__ = ["EmptyRepositoryError", "ReportShape", "TriageDecision", "triage"]
