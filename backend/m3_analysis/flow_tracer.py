from __future__ import annotations

from backend.contracts.domain import EntryCandidate, FlowStep, FlowSummary, ImportClassification, ModuleSummary
from backend.contracts.enums import ConfidenceLevel, FlowKind, ImportSourceType, LayerType
from backend.m3_analysis._helpers import stable_id


def trace_candidate_flows(
    entries: list[EntryCandidate],
    modules: list[ModuleSummary],
    imports: list[ImportClassification],
) -> list[FlowSummary]:
    usable_entries = [entry for entry in entries if entry.target_value != "unknown"]
    if not usable_entries:
        return [
            FlowSummary(
                flow_id=stable_id("flow", "none"),
                entry_candidate_id=None,
                flow_kind=FlowKind.NO_RELIABLE_FLOW,
                input_source=None,
                steps=[],
                module_path=[],
                layer_path=[],
                output_target=None,
                fallback_reading_advice="Start from the top-level package or README because no reliable entry candidate was found.",
                confidence=ConfidenceLevel.UNKNOWN,
                uncertainty_note="Evidence was insufficient to form a reliable module-level flow.",
                evidence_refs=[],
            )
        ]

    internal_imports = [item for item in imports if item.source_type == ImportSourceType.INTERNAL]
    module_by_path = {module.path: module for module in modules}
    flows: list[FlowSummary] = []
    for entry in usable_entries[:3]:
        steps: list[FlowStep] = [
            FlowStep(
                step_no=1,
                description=f"Begin at entry candidate `{entry.target_value}`.",
                module_id=module_by_path.get(entry.target_value).module_id if entry.target_value in module_by_path else None,
                path=entry.target_value,
                layer_type=LayerType.ENTRY,
                evidence_refs=entry.evidence_refs,
                confidence=entry.confidence,
            )
        ]
        module_path = [entry.target_value]
        layer_path = [LayerType.ENTRY]
        next_imports = [item for item in internal_imports if entry.target_value in item.used_by_files][:2]
        step_no = 2
        for item in next_imports:
            candidate_module = next((module for module in modules if module.path == item.import_name or module.path.endswith(f"/{item.import_name}")), None)
            steps.append(
                FlowStep(
                    step_no=step_no,
                    description=f"Entry imports internal module `{item.import_name}`.",
                    module_id=candidate_module.module_id if candidate_module else None,
                    path=candidate_module.path if candidate_module else item.import_name,
                    layer_type=candidate_module.likely_layer if candidate_module else LayerType.UNKNOWN,
                    evidence_refs=item.evidence_refs,
                    confidence=item.confidence,
                )
            )
            module_path.append(candidate_module.path if candidate_module else item.import_name)
            if candidate_module and candidate_module.likely_layer:
                layer_path.append(candidate_module.likely_layer)
            step_no += 1

        flows.append(
            FlowSummary(
                flow_id=stable_id("flow", entry.entry_id),
                entry_candidate_id=entry.entry_id,
                flow_kind=FlowKind.MODULE_LEVEL_PATH if len(steps) > 1 else FlowKind.ENTRY_NEIGHBORHOOD,
                input_source="Process start or framework entry",
                steps=steps,
                module_path=module_path,
                layer_path=layer_path,
                output_target="Internal modules or side effects inferred from imports",
                fallback_reading_advice=None,
                confidence=ConfidenceLevel.MEDIUM if len(steps) > 1 else ConfidenceLevel.LOW,
                uncertainty_note="This is a teaching-oriented static path, not a proven runtime call chain.",
                evidence_refs=[ref for step in steps for ref in step.evidence_refs],
            )
        )

    return flows
