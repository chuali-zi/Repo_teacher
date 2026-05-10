"""Phase 0 Triage decision matrix — covers all four branches in AGENTS.md §3.1."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from new_kernel.deep_research import EmptyRepositoryError, triage
from new_kernel.deep_research.triage import TriageDecision


def _overview(
    *,
    file_count: int = 1,
    primary_language: str | None = "Python",
) -> SimpleNamespace:
    """Build a minimal RepoOverview-like stub with all attrs the Protocol names."""

    return SimpleNamespace(
        text="",
        file_count=file_count,
        primary_language=primary_language,
        language_counts={},
        top_level_paths=[],
        entry_candidates=[],
    )


def test_empty_repository_raises() -> None:
    """file_count == 0 must raise EmptyRepositoryError before any branch logic."""

    with pytest.raises(EmptyRepositoryError):
        triage(_overview(file_count=0, primary_language=None))


def test_few_files_no_primary_language_is_short() -> None:
    """file_count <= 5 AND primary_language is None -> short."""

    decision = triage(_overview(file_count=3, primary_language=None))
    assert isinstance(decision, TriageDecision)
    assert decision.report_shape == "short"
    assert decision.is_short is True


@pytest.mark.parametrize("primary", [None, "Markdown", "plaintext"])
def test_marker_languages_force_short(primary: str | None) -> None:
    """primary_language in {None, "Markdown", "plaintext"} -> short, even on big repos."""

    decision = triage(_overview(file_count=200, primary_language=primary))
    assert decision.report_shape == "short"


def test_typical_python_repo_is_standard() -> None:
    """A sufficiently sized repo with a real source primary language goes standard."""

    decision = triage(_overview(file_count=42, primary_language="Python"))
    assert decision.report_shape == "standard"
    assert decision.is_short is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
