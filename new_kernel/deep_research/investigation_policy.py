"""Phase 2 Investigation policy: pure state machine for round/skip decisions.

No LLM, no I/O. Caller passes in current state; receives next decision. The
``DeepResearchLoop`` owns one ``InvestigationPolicy`` per turn and consults it
between ReAct rounds. Behaviour is fully described by AGENTS.md §3.3.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InvestigationPolicy:
    """Per-turn policy: round budget + consecutive-failure tracking + skip set."""

    # FIX-10 (user override): bump from 2 to 4 — sub-topic ReAct 配额翻倍.
    max_rounds: int = 4
    # FIX-10 (user override): bump from 2 to 4 — 工具偶发失败时不要太快放弃 sub-topic.
    max_consecutive_failures: int = 4
    failure_streak: int = 0
    skip_subtopic_ids: set[str] = field(default_factory=set)

    def reset_failure(self) -> None:
        """Zero the consecutive-failure counter (call after a tool succeeds)."""

        self.failure_streak = 0

    def bump_failure(self) -> None:
        """Increment the consecutive-failure counter (call after a tool fails)."""

        self.failure_streak += 1

    def mark_skipped(self, subtopic_id: str) -> None:
        """Mark a sub-topic as skipped and reset the failure streak.

        Caller decides when to call this (typically once
        ``failure_streak >= max_consecutive_failures``). We reset the streak
        here so the next sub-topic starts clean.
        """

        self.skip_subtopic_ids.add(subtopic_id)
        self.failure_streak = 0

    def should_skip(self, subtopic_id: str) -> bool:
        """Whether this sub-topic was previously marked skipped."""

        return subtopic_id in self.skip_subtopic_ids

    def round_quota(self) -> int:
        """Maximum rounds allowed per sub-topic for the current turn."""

        return self.max_rounds

    def can_continue(
        self,
        *,
        current_round: int,
        want_more: bool,
        last_action_done: bool,
    ) -> bool:
        """Whether the loop should run another ReAct round.

        Returns ``False`` if any of:

        - ``current_round >= max_rounds`` (budget exhausted), OR
        - ``last_action_done is True`` (Investigator declared done), OR
        - ``want_more is False`` (Investigator said no more rounds needed).

        Otherwise ``True``.
        """

        if current_round >= self.max_rounds:
            return False
        if last_action_done:
            return False
        if not want_more:
            return False
        return True


__all__ = ["InvestigationPolicy"]
