"""Sub-topic-aware research scratchpad for the deep research onboarding loop.

Owns the per-turn evidence ledger consumed by the Composer phase. Distinct from
``memory.Scratchpad`` (the teaching loop's ledger) and intentionally lives in
``deep_research/`` because its read/write semantics are scoped to the dedicated
sub-topic ReAct rounds described in AGENTS.md §3.3 / §3.4. No LLM and no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_RAW_BUDGET = 2048
_RAW_HEAD = 1024
_RAW_TAIL = 1024
_RAW_MARKER = "\n…\n[truncated]\n…\n"


@dataclass(frozen=True)
class SubtopicNote:
    """One round's NoteTaker output; ``success`` mirrors ``ToolResult.success``."""

    text: str
    success: bool = True
    anchor_path: str | None = None
    anchor_lines: tuple[int, int] | None = None  # (start, end) inclusive


@dataclass(frozen=True)
class SubtopicMeta:
    """Sub-topic header: id is one of ``{what, stack, why, arch, flow, polyglot}``."""

    id: str
    title: str
    anchors: tuple[str, ...] = ()


class ResearchScratchpad:
    """Per-turn, sub-topic-keyed evidence ledger feeding the Composer."""

    def __init__(self) -> None:
        self._subtopics: list[SubtopicMeta] = []
        self._notes: dict[str, list[SubtopicNote]] = {}
        self._raw_first_round: dict[str, str] = {}
        self._skip_reasons: dict[str, str] = {}
        self._covered_points: list[str] = []

    @property
    def subtopics(self) -> tuple[SubtopicMeta, ...]:
        return tuple(self._subtopics)

    def set_subtopics(self, items: list[SubtopicMeta]) -> None:
        """Replace the sub-topic list and reset every per-id slot."""

        self._subtopics = list(items)
        self._notes = {meta.id: [] for meta in self._subtopics}
        self._raw_first_round = {}
        self._skip_reasons = {}

    def add_note(
        self,
        subtopic_id: str,
        round_index: int,
        note: SubtopicNote,
        *,
        raw_observation: str | None = None,
    ) -> None:
        """Append a round note. Only round 1 ``raw_observation`` is persisted."""

        if subtopic_id not in self._notes:
            raise KeyError(f"unknown subtopic_id: {subtopic_id!r}")
        self._notes[subtopic_id].append(note)
        if round_index == 1 and raw_observation is not None:
            self._raw_first_round[subtopic_id] = _truncate_raw(raw_observation)

    def add_skip_reason(self, subtopic_id: str, reason: str) -> None:
        self._skip_reasons[subtopic_id] = reason

    def notes_for(self, subtopic_id: str) -> tuple[SubtopicNote, ...]:
        return tuple(self._notes.get(subtopic_id, ()))

    def first_round_raw(self, subtopic_id: str) -> str | None:
        return self._raw_first_round.get(subtopic_id)

    def skip_reason(self, subtopic_id: str) -> str | None:
        return self._skip_reasons.get(subtopic_id)

    def add_covered_point(self, point: str) -> None:
        if point:
            self._covered_points.append(point)

    @property
    def covered_points(self) -> tuple[str, ...]:
        return tuple(self._covered_points)

    def build_compose_context(self, *, max_total_bytes: int = 30000) -> dict:
        """Serialize state for Composer; trim to fit ``max_total_bytes``.

        Trim order: longest ``raw_first_round`` strings first, then the tails
        of ``notes`` lists. Always keep ≥1 note per non-skipped sub-topic
        when notes exist.
        """

        subtopics_payload: list[dict[str, Any]] = [
            {
                "id": meta.id,
                "title": meta.title,
                "anchors": list(meta.anchors),
                "skip_reason": self._skip_reasons.get(meta.id),
            }
            for meta in self._subtopics
        ]
        notes_by_id: dict[str, list[dict[str, Any]]] = {
            meta.id: [
                {
                    "text": note.text,
                    "success": note.success,
                    "anchor_path": note.anchor_path,
                    "anchor_lines": (
                        list(note.anchor_lines) if note.anchor_lines is not None else None
                    ),
                }
                for note in self._notes.get(meta.id, [])
            ]
            for meta in self._subtopics
        }
        raw_first_round_by_id: dict[str, str | None] = {
            meta.id: self._raw_first_round.get(meta.id) for meta in self._subtopics
        }
        context = {
            "subtopics": subtopics_payload,
            "notes_by_id": notes_by_id,
            "raw_first_round_by_id": raw_first_round_by_id,
            "covered_points": list(self._covered_points),
        }
        _enforce_budget(context, max_total_bytes=max_total_bytes)
        return context


def _truncate_raw(raw: str) -> str:
    """Hard-cap a raw observation to ~2KB while keeping head + tail (UTF-8 safe)."""

    encoded = raw.encode("utf-8")
    if len(encoded) <= _RAW_BUDGET:
        return raw
    head = encoded[:_RAW_HEAD].decode("utf-8", errors="ignore")
    tail = encoded[-_RAW_TAIL:].decode("utf-8", errors="ignore")
    return head + _RAW_MARKER + tail


def _byte_len(value: str | None) -> int:
    return len(value.encode("utf-8")) if value else 0


def _context_byte_size(context: dict) -> int:
    """Sum byte length of user-visible strings in the context payload."""

    total = 0
    for raw in context["raw_first_round_by_id"].values():
        total += _byte_len(raw)
    for notes in context["notes_by_id"].values():
        for note in notes:
            total += _byte_len(note.get("text"))
            total += _byte_len(note.get("anchor_path"))
    for sub in context["subtopics"]:
        total += _byte_len(sub.get("title"))
        total += _byte_len(sub.get("skip_reason"))
        for anchor in sub.get("anchors", []):
            total += _byte_len(anchor)
    for point in context["covered_points"]:
        total += _byte_len(point)
    return total


def _enforce_budget(context: dict, *, max_total_bytes: int) -> None:
    """Trim raws first, then note tails. Mutates ``context`` in place."""

    if max_total_bytes <= 0:
        return
    skipped_ids = {
        sub["id"] for sub in context["subtopics"] if sub.get("skip_reason") is not None
    }

    # Pass 1: drop the longest raw_first_round entries first.
    while _context_byte_size(context) > max_total_bytes:
        raws = context["raw_first_round_by_id"]
        candidates = [(sid, _byte_len(raw)) for sid, raw in raws.items() if raw]
        if not candidates:
            break
        candidates.sort(key=lambda item: item[1], reverse=True)
        raws[candidates[0][0]] = None

    # Pass 2: drop note tails, preserving 1 per non-skipped sub-topic.
    while _context_byte_size(context) > max_total_bytes:
        notes_by_id = context["notes_by_id"]
        victim_id: str | None = None
        victim_len = 0
        for sid, notes in notes_by_id.items():
            min_keep = 0 if sid in skipped_ids else 1
            if len(notes) > min_keep and len(notes) > victim_len:
                victim_id = sid
                victim_len = len(notes)
        if victim_id is None:
            break
        notes_by_id[victim_id].pop()


__all__ = [
    "ResearchScratchpad",
    "SubtopicMeta",
    "SubtopicNote",
]
