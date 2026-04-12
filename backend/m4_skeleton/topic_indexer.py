from __future__ import annotations

from backend.contracts.domain import AnalysisBundle, TopicIndex, TopicRef
from backend.contracts.enums import LearningGoal, TopicRefType


def _trim_summary(text: str | None, *, default: str) -> str:
    candidate = (text or "").strip()
    if not candidate:
        return default
    return candidate[:160]


def _topic_ref(ref_id: str, ref_type: TopicRefType, target_id: str, topic: LearningGoal, summary: str) -> TopicRef:
    return TopicRef(
        ref_id=ref_id,
        ref_type=ref_type,
        target_id=target_id,
        topic=topic,
        summary=summary,
    )


def build_topic_index(analysis: AnalysisBundle) -> TopicIndex:
    structure_refs: list[TopicRef] = []
    entry_refs: list[TopicRef] = []
    flow_refs: list[TopicRef] = []
    layer_refs: list[TopicRef] = []
    dependency_refs: list[TopicRef] = []
    module_refs: list[TopicRef] = []
    reading_path_refs: list[TopicRef] = []
    unknown_refs: list[TopicRef] = []

    structure_refs.append(
        _topic_ref(
            ref_id="topic_structure_overview",
            ref_type=TopicRefType.OVERVIEW,
            target_id=analysis.bundle_id,
            topic=LearningGoal.STRUCTURE,
            summary=_trim_summary(
                analysis.project_profile.summary_text,
                default="Project structure overview from analysis bundle.",
            ),
        )
    )

    for module in analysis.module_summaries:
        summary = _trim_summary(
            module.responsibility,
            default=f"{module.path} is a {module.module_kind} in the repository structure.",
        )
        ref = _topic_ref(
            ref_id=f"topic_module_{module.module_id}",
            ref_type=TopicRefType.MODULE_SUMMARY,
            target_id=module.module_id,
            topic=LearningGoal.MODULE,
            summary=summary,
        )
        module_refs.append(ref)
        structure_refs.append(
            _topic_ref(
                ref_id=f"topic_structure_module_{module.module_id}",
                ref_type=TopicRefType.MODULE_SUMMARY,
                target_id=module.module_id,
                topic=LearningGoal.STRUCTURE,
                summary=summary,
            )
        )

    for entry in analysis.entry_candidates:
        entry_refs.append(
            _topic_ref(
                ref_id=f"topic_entry_{entry.entry_id}",
                ref_type=TopicRefType.ENTRY_CANDIDATE,
                target_id=entry.entry_id,
                topic=LearningGoal.ENTRY,
                summary=_trim_summary(entry.reason, default=f"Entry candidate at {entry.target_value}."),
            )
        )

    for flow in analysis.flow_summaries:
        flow_refs.append(
            _topic_ref(
                ref_id=f"topic_flow_{flow.flow_id}",
                ref_type=TopicRefType.FLOW_SUMMARY,
                target_id=flow.flow_id,
                topic=LearningGoal.FLOW,
                summary=_trim_summary(
                    flow.uncertainty_note or flow.fallback_reading_advice,
                    default=f"Flow candidate with {len(flow.steps)} traced steps.",
                ),
            )
        )

    for layer in analysis.layer_view.layers:
        layer_refs.append(
            _topic_ref(
                ref_id=f"topic_layer_{layer.layer_type}",
                ref_type=TopicRefType.LAYER_ASSIGNMENT,
                target_id=analysis.layer_view.layer_view_id,
                topic=LearningGoal.LAYER,
                summary=_trim_summary(layer.role_description, default=f"Layer {layer.layer_type} view."),
            )
        )
    if not layer_refs:
        layer_refs.append(
            _topic_ref(
                ref_id="topic_layer_overview",
                ref_type=TopicRefType.OVERVIEW,
                target_id=analysis.layer_view.layer_view_id,
                topic=LearningGoal.LAYER,
                summary=_trim_summary(
                    analysis.layer_view.uncertainty_note,
                    default="Layering could not be derived reliably.",
                ),
            )
        )

    for item in analysis.import_classifications:
        dependency_refs.append(
            _topic_ref(
                ref_id=f"topic_dependency_{item.import_id}",
                ref_type=TopicRefType.IMPORT_CLASSIFICATION,
                target_id=item.import_id,
                topic=LearningGoal.DEPENDENCY,
                summary=_trim_summary(item.basis, default=f"Dependency {item.import_name} classification."),
            )
        )

    for step in analysis.reading_path:
        reading_path_refs.append(
            _topic_ref(
                ref_id=f"topic_reading_{step.step_no}",
                ref_type=TopicRefType.READING_STEP,
                target_id=f"reading_step_{step.step_no}",
                topic=LearningGoal.STRUCTURE,
                summary=_trim_summary(step.reason, default=f"Read {step.target} at step {step.step_no}."),
            )
        )

    for item in analysis.unknown_items:
        if not item.user_visible:
            continue
        unknown_refs.append(
            _topic_ref(
                ref_id=f"topic_unknown_{item.unknown_id}",
                ref_type=TopicRefType.UNKNOWN_ITEM,
                target_id=item.unknown_id,
                topic=LearningGoal.SUMMARY,
                summary=_trim_summary(item.description, default="Unknown analysis item."),
            )
        )
    for entry in analysis.entry_candidates:
        for item in entry.unknown_items:
            if not item.user_visible:
                continue
            unknown_refs.append(
                _topic_ref(
                    ref_id=f"topic_unknown_{item.unknown_id}",
                    ref_type=TopicRefType.UNKNOWN_ITEM,
                    target_id=item.unknown_id,
                    topic=LearningGoal.SUMMARY,
                    summary=_trim_summary(item.description, default="Unknown analysis item."),
                )
            )

    deduped_unknown_refs: list[TopicRef] = []
    seen_unknown_targets: set[str] = set()
    for ref in unknown_refs:
        if ref.target_id in seen_unknown_targets:
            continue
        deduped_unknown_refs.append(ref)
        seen_unknown_targets.add(ref.target_id)

    return TopicIndex(
        structure_refs=structure_refs,
        entry_refs=entry_refs,
        flow_refs=flow_refs,
        layer_refs=layer_refs,
        dependency_refs=dependency_refs,
        module_refs=module_refs,
        reading_path_refs=reading_path_refs,
        unknown_refs=deduped_unknown_refs,
    )
