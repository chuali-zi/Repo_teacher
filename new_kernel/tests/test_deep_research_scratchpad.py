"""ResearchScratchpad behaviour tests — AGENTS.md §3.3 / §3.4."""

from __future__ import annotations

import pytest

from new_kernel.deep_research import (
    ResearchScratchpad,
    SubtopicMeta,
    SubtopicNote,
)


def _basic_subtopics() -> list[SubtopicMeta]:
    return [
        SubtopicMeta(id="what", title="这个仓库在干什么", anchors=("README.md",)),
        SubtopicMeta(id="stack", title="技术栈", anchors=("package.json",)),
        SubtopicMeta(id="arch", title="整体架构", anchors=("src/",)),
    ]


def test_set_subtopics_resets_prior_state() -> None:
    """Re-calling set_subtopics wipes notes / raw / skip slots."""

    pad = ResearchScratchpad()
    pad.set_subtopics(_basic_subtopics())
    pad.add_note("what", 1, SubtopicNote(text="first pass"), raw_observation="raw 1")
    pad.add_skip_reason("arch", "工具连续失败")
    assert pad.notes_for("what")
    assert pad.first_round_raw("what") == "raw 1"
    assert pad.skip_reason("arch") == "工具连续失败"

    # Reset with a new sub-topic list — old state must be gone.
    pad.set_subtopics([SubtopicMeta(id="what", title="新版本", anchors=())])
    assert pad.notes_for("what") == ()
    assert pad.first_round_raw("what") is None
    assert pad.skip_reason("arch") is None


def test_add_note_for_unknown_id_raises() -> None:
    """Defensive: writing to a sub-topic the decomposer never produced is a bug."""

    pad = ResearchScratchpad()
    pad.set_subtopics(_basic_subtopics())
    with pytest.raises(KeyError):
        pad.add_note("polyglot", 1, SubtopicNote(text="ghost note"))


def test_raw_observation_only_persists_on_round_one() -> None:
    """Round 1 raw goes into the ledger; round 2 raw is silently dropped."""

    pad = ResearchScratchpad()
    pad.set_subtopics(_basic_subtopics())
    pad.add_note("what", 1, SubtopicNote(text="r1"), raw_observation="ROUND1")
    pad.add_note("what", 2, SubtopicNote(text="r2"), raw_observation="ROUND2_IGNORED")
    assert pad.first_round_raw("what") == "ROUND1"


def test_raw_observation_truncation_marker_present() -> None:
    """Oversized raw observation is truncated head + marker + tail."""

    pad = ResearchScratchpad()
    pad.set_subtopics(_basic_subtopics())
    big = ("A" * 5000) + ("Z" * 5000)
    pad.add_note("what", 1, SubtopicNote(text="r1"), raw_observation=big)

    stored = pad.first_round_raw("what")
    assert stored is not None
    assert "[truncated]" in stored
    # head + marker + tail should be much smaller than the original.
    assert len(stored.encode("utf-8")) < len(big.encode("utf-8"))
    assert stored.startswith("A")
    assert stored.endswith("Z")


def test_build_compose_context_shape() -> None:
    """Returned dict has the four documented top-level keys with expected types."""

    pad = ResearchScratchpad()
    pad.set_subtopics(_basic_subtopics())
    pad.add_note(
        "what",
        1,
        SubtopicNote(
            text="教学要点：仓库在做 X",
            success=True,
            anchor_path="README.md",
            anchor_lines=(1, 20),
        ),
        raw_observation="raw what",
    )
    pad.add_skip_reason("arch", "工具连续失败")

    ctx = pad.build_compose_context()
    assert set(ctx) == {
        "subtopics",
        "notes_by_id",
        "raw_first_round_by_id",
        "covered_points",
    }
    assert isinstance(ctx["subtopics"], list)
    assert ctx["subtopics"][0]["id"] == "what"
    assert ctx["subtopics"][2]["skip_reason"] == "工具连续失败"

    note_dict = ctx["notes_by_id"]["what"][0]
    assert note_dict["text"] == "教学要点：仓库在做 X"
    assert note_dict["anchor_path"] == "README.md"
    assert note_dict["anchor_lines"] == [1, 20]

    assert ctx["raw_first_round_by_id"]["what"] == "raw what"
    assert ctx["raw_first_round_by_id"]["arch"] is None


def test_build_compose_context_enforces_byte_budget() -> None:
    """Budget trims raw observations first; non-skipped sub-topics keep ≥1 note."""

    pad = ResearchScratchpad()
    pad.set_subtopics(_basic_subtopics())
    big_raw = "X" * 8000  # under the 2KB raw cap-after-truncation but still hefty
    big_note = "N" * 4000

    for sid in ("what", "stack", "arch"):
        pad.add_note(sid, 1, SubtopicNote(text=big_note), raw_observation=big_raw)
        pad.add_note(sid, 2, SubtopicNote(text="round 2 note"))

    ctx = pad.build_compose_context(max_total_bytes=1500)

    # Each non-skipped sub-topic must keep at least one note.
    for sid in ("what", "stack", "arch"):
        assert len(ctx["notes_by_id"][sid]) >= 1, f"{sid} lost all notes under budget"


def test_add_covered_point_accumulates() -> None:
    """covered_points appends in call order and exposes via the property."""

    pad = ResearchScratchpad()
    pad.set_subtopics(_basic_subtopics())
    pad.add_covered_point("what:仓库做 X")
    pad.add_covered_point("arch:三层切分")
    pad.add_covered_point("")  # empty no-op

    assert pad.covered_points == ("what:仓库做 X", "arch:三层切分")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
