"""Scratchpad value objects and context compression helpers.

The memory module is intentionally runtime-free. It owns the in-memory evidence
ledger used by teaching/deep loops, but it does not call LLMs, tools, events,
API, or session services.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any


DEFAULT_READING_CONTEXT_TOKENS = 4000
DEFAULT_TEACHER_CONTEXT_TOKENS = 12000
_CHARS_PER_TOKEN = 4
_OMITTED_TEXT = "[omitted to fit context budget]"
_NO_PLAN_TEXT = "(no reading plan yet)"
_NO_EVIDENCE_TEXT = "(no evidence gathered yet)"


@dataclass(frozen=True)
class Anchor:
    """A source location the planner thinks may be useful to read."""

    path: str
    why: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _clean_text(self.path))
        object.__setattr__(self, "why", _clean_text(self.why))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Anchor":
        return cls(
            path=_clean_text(payload.get("path", "")),
            why=_clean_text(payload.get("why", "")),
        )


@dataclass(frozen=True)
class ReadingStep:
    """One planned reading step for the current turn."""

    step_id: str
    goal: str
    anchors: tuple[Anchor, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        anchors = () if self.anchors is None else self.anchors
        object.__setattr__(self, "step_id", _clean_text(self.step_id))
        object.__setattr__(self, "goal", _clean_text(self.goal))
        object.__setattr__(self, "anchors", tuple(_coerce_anchor(item) for item in anchors))
        if not self.step_id:
            raise ValueError("step_id must be a non-empty string")

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "goal": self.goal,
            "anchors": [anchor.to_dict() for anchor in self.anchors],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReadingStep":
        anchors = payload.get("anchors", ())
        if anchors is None:
            anchors = ()
        if not isinstance(anchors, Iterable) or isinstance(anchors, (str, bytes)):
            raise TypeError("anchors must be an iterable of Anchor values")
        return cls(
            step_id=_clean_text(payload.get("step_id", "")),
            goal=_clean_text(payload.get("goal", "")),
            anchors=tuple(_coerce_anchor(item) for item in anchors),
        )


@dataclass(frozen=True)
class ReadEntry:
    """One read-stage observation captured after a ReAct tool decision."""

    step_id: str
    round_index: int
    thought: str = ""
    action: str = ""
    action_input: dict[str, Any] = field(default_factory=dict)
    observation: str = ""
    self_note: str = ""
    tool_success: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_id", _clean_text(self.step_id))
        object.__setattr__(self, "round_index", int(self.round_index))
        object.__setattr__(self, "thought", _clean_text(self.thought))
        object.__setattr__(self, "action", _clean_text(self.action))
        object.__setattr__(self, "action_input", _copy_mapping(self.action_input))
        object.__setattr__(self, "observation", _clean_text(self.observation))
        object.__setattr__(self, "self_note", _clean_text(self.self_note))
        object.__setattr__(self, "tool_success", bool(self.tool_success))
        if not self.step_id:
            raise ValueError("step_id must be a non-empty string")
        if self.round_index < 0:
            raise ValueError("round_index must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReadEntry":
        normalized = _normalize_entry_payload(payload)
        return cls(
            step_id=_clean_text(normalized.get("step_id", "")),
            round_index=int(normalized.get("round_index", 0)),
            thought=_clean_text(normalized.get("thought", "")),
            action=_clean_text(normalized.get("action", "")),
            action_input=_copy_mapping(normalized.get("action_input", {})),
            observation=_clean_text(normalized.get("observation", "")),
            self_note=_clean_text(normalized.get("self_note", "")),
            tool_success=bool(normalized.get("tool_success", True)),
        )


@dataclass
class Scratchpad:
    """Turn-local evidence ledger plus cross-turn covered point memory."""

    question: str = ""
    reading_plan: list[ReadingStep] = field(default_factory=list)
    read_entries: list[ReadEntry] = field(default_factory=list)
    covered_points: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.question = _clean_text(self.question)
        self.reading_plan = [_coerce_reading_step(item) for item in self.reading_plan]
        self.read_entries = [_coerce_read_entry(item) for item in self.read_entries]
        self.covered_points = {
            _clean_text(key): _clean_text(value)
            for key, value in self.covered_points.items()
            if _clean_text(key) and _clean_text(value)
        }
        self.metadata = _copy_mapping(self.metadata)

    def reset_for_turn(self, question: str) -> None:
        """Clear turn-local plan/evidence while preserving covered_points."""

        self.question = _clean_text(question)
        self.reading_plan.clear()
        self.read_entries.clear()

    def set_plan(self, plan: Iterable[ReadingStep]) -> None:
        """Replace the current turn reading plan with modeled steps."""

        if isinstance(plan, (str, bytes)):
            raise TypeError("plan must be an iterable of ReadingStep values")
        self.reading_plan = [_coerce_reading_step(item) for item in plan]

    def add_entry(self, entry: ReadEntry | None = None, **kwargs: Any) -> ReadEntry:
        """Append one read-stage observation and return the stored entry.

        Callers should usually pass a ReadEntry. Keyword construction is kept as
        a convenience for loop code that already has the individual fields.
        """

        if entry is not None and kwargs:
            raise ValueError("pass either entry or keyword fields, not both")
        stored = _coerce_read_entry(entry if entry is not None else kwargs)
        self.read_entries.append(stored)
        return stored

    def update_covered_points(self, point_id: str, summary: str) -> None:
        """Record a completed teaching point when both id and summary are known."""

        cleaned_id = _clean_text(point_id)
        cleaned_summary = _clean_text(summary)
        if cleaned_id and cleaned_summary:
            self.covered_points[cleaned_id] = cleaned_summary

    def get_entries_for_step(self, step_id: str) -> list[ReadEntry]:
        cleaned_step_id = _clean_text(step_id)
        return [entry for entry in self.read_entries if entry.step_id == cleaned_step_id]

    def build_reading_context(
        self,
        *,
        current_step_id: str | None = None,
        max_tokens: int = DEFAULT_READING_CONTEXT_TOKENS,
    ) -> str:
        """Build compact context for ReadingAgent.

        The current step keeps observations. Other steps are summarized through
        self_note so earlier tool output does not flood the next read decision.
        """

        current_id = _clean_text(current_step_id or "")
        if not current_id and self.reading_plan:
            current_id = self.reading_plan[0].step_id

        parts = [
            "Question:\n" + (self.question or "(empty)"),
            "Covered points:\n" + self._format_covered_points(),
            "Reading plan:\n" + self._format_plan(current_step_id=current_id),
        ]

        current_step = self._find_step(current_id)
        if current_step is not None:
            parts.append("Current step:\n" + self._format_step(current_step, current=True))

        step_history = self._format_step_history(current_id)
        if step_history:
            parts.append("Current step history:\n" + step_history)

        previous_notes = self._format_previous_step_notes(current_id)
        if previous_notes:
            parts.append("Previous step notes:\n" + previous_notes)

        return _fit_text("\n\n".join(parts), max_tokens=max_tokens)

    def build_teacher_context(self, *, max_tokens: int = DEFAULT_TEACHER_CONTEXT_TOKENS) -> str:
        """Build evidence context for TeacherAgent.

        Full observations are preserved first. If the budget is exceeded, earlier
        steps collapse to self_note while recent steps keep observations.
        """

        full = self._format_teacher_context(include_full_observations=True)
        if _estimate_tokens(full) <= max_tokens:
            return full
        compressed = self._format_teacher_context(include_full_observations=False)
        return _fit_text(compressed, max_tokens=max_tokens)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "reading_plan": [step.to_dict() for step in self.reading_plan],
            "read_entries": [entry.to_dict() for entry in self.read_entries],
            "covered_points": dict(self.covered_points),
            "metadata": _copy_mapping(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Scratchpad":
        return cls(
            question=_clean_text(payload.get("question", "")),
            reading_plan=[
                _coerce_reading_step(item) for item in payload.get("reading_plan", [])
            ],
            read_entries=[_coerce_read_entry(item) for item in payload.get("read_entries", [])],
            covered_points=_copy_mapping(payload.get("covered_points", {})),
            metadata=_copy_mapping(payload.get("metadata", {})),
        )

    def _find_step(self, step_id: str) -> ReadingStep | None:
        for step in self.reading_plan:
            if step.step_id == step_id:
                return step
        return None

    def _format_plan(self, *, current_step_id: str = "") -> str:
        if not self.reading_plan:
            return _NO_PLAN_TEXT

        lines: list[str] = []
        for index, step in enumerate(self.reading_plan, start=1):
            prefix = "->" if step.step_id == current_step_id else "  "
            lines.append(f"{prefix} {index}. {step.step_id}: {step.goal or '(no goal)'}")
            if step.anchors:
                lines.append("     anchors: " + _format_anchors(step.anchors))
        return "\n".join(lines)

    @staticmethod
    def _format_step(step: ReadingStep, *, current: bool = False) -> str:
        marker = "current " if current else ""
        lines = [f"{marker}step_id: {step.step_id}", f"goal: {step.goal or '(no goal)'}"]
        if step.anchors:
            lines.append("anchors:")
            for anchor in step.anchors:
                why = f" - {anchor.why}" if anchor.why else ""
                lines.append(f"- {anchor.path}{why}")
        return "\n".join(lines)

    def _format_step_history(self, step_id: str) -> str:
        entries = self.get_entries_for_step(step_id)
        if not entries:
            return ""
        return "\n\n".join(_format_entry(entry, include_observation=True) for entry in entries)

    def _format_previous_step_notes(self, current_step_id: str) -> str:
        grouped: list[str] = []
        for step in self.reading_plan:
            if step.step_id == current_step_id:
                continue
            notes = [
                entry.self_note
                for entry in self.get_entries_for_step(step.step_id)
                if entry.self_note
            ]
            if notes:
                grouped.append(f"{step.step_id}: " + " | ".join(notes))
        return "\n".join(grouped)

    def _format_teacher_context(self, *, include_full_observations: bool) -> str:
        parts = [
            "Question:\n" + (self.question or "(empty)"),
            "Covered points:\n" + self._format_covered_points(),
            "Reading plan:\n" + self._format_plan(),
        ]

        if not self.read_entries:
            parts.append("Evidence:\n" + _NO_EVIDENCE_TEXT)
            return "\n\n".join(parts)

        evidence_parts: list[str] = []
        step_ids = self._ordered_step_ids_with_entries()
        recent_full_ids = set(step_ids[-2:]) if not include_full_observations else set(step_ids)

        for step_id in step_ids:
            step = self._find_step(step_id)
            header = f"Step {step_id}"
            if step and step.goal:
                header += f": {step.goal}"

            entries = self.get_entries_for_step(step_id)
            include_observation = step_id in recent_full_ids
            body = "\n\n".join(
                _format_entry(entry, include_observation=include_observation) for entry in entries
            )
            evidence_parts.append(f"## {header}\n{body}")

        parts.append("Evidence:\n" + "\n\n".join(evidence_parts))
        return "\n\n".join(parts)

    def _ordered_step_ids_with_entries(self) -> list[str]:
        ordered = [step.step_id for step in self.reading_plan]
        extra = [entry.step_id for entry in self.read_entries if entry.step_id not in ordered]
        seen: set[str] = set()
        result: list[str] = []
        for step_id in [*ordered, *extra]:
            if step_id in seen or not self.get_entries_for_step(step_id):
                continue
            seen.add(step_id)
            result.append(step_id)
        return result

    def _format_covered_points(self) -> str:
        if not self.covered_points:
            return "(none)"
        return "\n".join(
            f"- {point_id}: {summary}" for point_id, summary in self.covered_points.items()
        )


def _coerce_anchor(value: Anchor | Mapping[str, Any]) -> Anchor:
    if isinstance(value, Anchor):
        return value
    if isinstance(value, Mapping):
        return Anchor.from_dict(value)
    raise TypeError("anchor must be an Anchor or mapping")


def _coerce_reading_step(value: ReadingStep | Mapping[str, Any]) -> ReadingStep:
    if isinstance(value, ReadingStep):
        return value
    if isinstance(value, Mapping):
        return ReadingStep.from_dict(value)
    raise TypeError("reading step must be a ReadingStep or mapping")


def _coerce_read_entry(value: ReadEntry | Mapping[str, Any] | None) -> ReadEntry:
    if isinstance(value, ReadEntry):
        return value
    if isinstance(value, Mapping):
        return ReadEntry.from_dict(_normalize_entry_payload(value))
    raise TypeError("read entry must be a ReadEntry or mapping")


def _normalize_entry_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    if "round_index" not in normalized and "round" in normalized:
        normalized["round_index"] = normalized["round"]
    return normalized


def _format_entry(entry: ReadEntry, *, include_observation: bool) -> str:
    lines = [
        f"Round {entry.round_index}",
        f"action: {entry.action or '(none)'}",
        f"tool_success: {entry.tool_success}",
    ]
    if entry.action_input:
        lines.append(f"action_input: {_stable_mapping_text(entry.action_input)}")
    if entry.thought:
        lines.append(f"thought: {entry.thought}")
    if entry.self_note:
        lines.append(f"self_note: {entry.self_note}")
    if include_observation:
        lines.append("observation:\n" + (entry.observation or "(empty)"))
    else:
        lines.append("observation:\n" + _OMITTED_TEXT)
    return "\n".join(lines)


def _format_anchors(anchors: Iterable[Anchor]) -> str:
    formatted: list[str] = []
    for anchor in anchors:
        if anchor.why:
            formatted.append(f"{anchor.path} ({anchor.why})")
        else:
            formatted.append(anchor.path)
    return "; ".join(formatted)


def _fit_text(text: str, *, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ""
    max_chars = max_tokens * _CHARS_PER_TOKEN
    if len(text) <= max_chars:
        return text
    marker_a = "\n\n[...head trimmed...]\n\n"
    marker_b = "\n\n[...tail trimmed...]\n\n"
    overhead = len(marker_a) + len(marker_b)
    keep_chars = max(max_chars - overhead, 0)
    if keep_chars <= 0:
        return (marker_a + marker_b).strip()
    head_chars = max(keep_chars // 4, 1)
    tail_chars = max(keep_chars // 4, 1)
    mid_chars = keep_chars - head_chars - tail_chars
    head = text[:head_chars]
    tail = text[-tail_chars:]
    mid_start = max((len(text) - mid_chars) // 2, head_chars)
    mid_end = min(mid_start + mid_chars, len(text) - tail_chars)
    mid = text[mid_start:mid_end]
    return head + marker_a + mid + marker_b + tail


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _copy_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("value must be a mapping")
    return {str(key): _plain_value(val) for key, val in value.items()}


def _plain_value(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return {str(key): _plain_value(val) for key, val in value.items()}
    if isinstance(value, tuple):
        return [_plain_value(item) for item in value]
    if isinstance(value, list):
        return [_plain_value(item) for item in value]
    return value


def _stable_mapping_text(mapping: Mapping[str, Any]) -> str:
    items = sorted(mapping.items(), key=lambda item: item[0])
    return ", ".join(f"{key}={value!r}" for key, value in items)


__all__ = [
    "Anchor",
    "DEFAULT_READING_CONTEXT_TOKENS",
    "DEFAULT_TEACHER_CONTEXT_TOKENS",
    "ReadEntry",
    "ReadingStep",
    "Scratchpad",
]
