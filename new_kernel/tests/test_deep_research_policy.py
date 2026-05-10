"""InvestigationPolicy state-machine tests — AGENTS.md §3.3."""

from __future__ import annotations

import pytest

from new_kernel.deep_research import InvestigationPolicy


def test_bump_failure_streak_then_mark_skipped_resets() -> None:
    """Reaching max_consecutive_failures, then mark_skipped: id in set, streak=0."""

    policy = InvestigationPolicy()
    policy.bump_failure()
    policy.bump_failure()
    assert policy.failure_streak == 2
    assert policy.failure_streak >= policy.max_consecutive_failures

    policy.mark_skipped("arch")
    assert policy.should_skip("arch") is True
    assert policy.failure_streak == 0


def test_reset_failure_zeroes_streak() -> None:
    """A successful tool call clears the streak so the next sub-topic starts clean."""

    policy = InvestigationPolicy()
    policy.bump_failure()
    assert policy.failure_streak == 1

    policy.reset_failure()
    assert policy.failure_streak == 0


def test_can_continue_blocks_when_round_budget_hit() -> None:
    """current_round >= max_rounds short-circuits to False."""

    policy = InvestigationPolicy(max_rounds=2)
    assert (
        policy.can_continue(current_round=2, want_more=True, last_action_done=False)
        is False
    )


def test_can_continue_blocks_when_action_done() -> None:
    """Investigator declared done -> we never run another round."""

    policy = InvestigationPolicy()
    assert (
        policy.can_continue(current_round=1, want_more=True, last_action_done=True)
        is False
    )


def test_can_continue_blocks_when_want_more_is_false() -> None:
    """Investigator wants no more rounds -> stop."""

    policy = InvestigationPolicy()
    assert (
        policy.can_continue(current_round=1, want_more=False, last_action_done=False)
        is False
    )


def test_can_continue_allows_progress_when_all_clear() -> None:
    """Below budget, action not done, want_more True -> continue."""

    policy = InvestigationPolicy()
    assert (
        policy.can_continue(current_round=1, want_more=True, last_action_done=False)
        is True
    )


def test_should_skip_reflects_manual_mark() -> None:
    """mark_skipped(id) is the only entry point; should_skip mirrors the set."""

    policy = InvestigationPolicy()
    assert policy.should_skip("flow") is False
    policy.mark_skipped("flow")
    assert policy.should_skip("flow") is True
    assert policy.should_skip("arch") is False


def test_round_quota_returns_max_rounds() -> None:
    """round_quota is the published quota for callers' for-loops."""

    policy = InvestigationPolicy(max_rounds=3)
    assert policy.round_quota() == 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
