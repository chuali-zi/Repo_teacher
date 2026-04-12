from __future__ import annotations

from backend.contracts.domain import EntryCandidate, LayerAssignment, LayerViewResult, ModuleSummary
from backend.contracts.enums import ConfidenceLevel, DerivedStatus, LayerType, MainPathRole
from backend.m3_analysis._helpers import stable_id


def infer_layers(
    entries: list[EntryCandidate],
    modules: list[ModuleSummary],
) -> LayerViewResult:
    buckets: dict[LayerType, list[ModuleSummary]] = {
        LayerType.ENTRY: [],
        LayerType.ROUTE_OR_CONTROLLER: [],
        LayerType.BUSINESS_LOGIC: [],
        LayerType.DATA_ACCESS: [],
        LayerType.UTILITY_OR_CONFIG: [],
        LayerType.UNKNOWN: [],
    }

    entry_targets = {entry.target_value for entry in entries if entry.target_value != "unknown"}
    for module in modules:
        path = module.path.lower()
        if module.path in entry_targets or path.endswith("main.py") or path.endswith("app.py") or path.endswith("manage.py"):
            buckets[LayerType.ENTRY].append(module)
        elif any(token in path for token in ["route", "controller", "view", "api"]):
            buckets[LayerType.ROUTE_OR_CONTROLLER].append(module)
        elif any(token in path for token in ["repo", "dao", "db", "store", "model"]):
            buckets[LayerType.DATA_ACCESS].append(module)
        elif any(token in path for token in ["util", "helper", "config", "setting"]):
            buckets[LayerType.UTILITY_OR_CONFIG].append(module)
        elif any(token in path for token in ["service", "logic", "core", "domain"]):
            buckets[LayerType.BUSINESS_LOGIC].append(module)
        else:
            buckets[LayerType.UNKNOWN].append(module)

    assignments: list[LayerAssignment] = []
    for layer_type, layer_modules in buckets.items():
        if not layer_modules:
            continue
        assignments.append(
            LayerAssignment(
                layer_type=layer_type,
                module_ids=[module.module_id for module in layer_modules],
                paths=[module.path for module in layer_modules],
                role_description=f"Modules heuristically grouped into `{layer_type}`.",
                main_path_role=MainPathRole.MAIN_PATH if any(module.main_path_role == MainPathRole.MAIN_PATH for module in layer_modules) else MainPathRole.SUPPORTING,
                confidence=ConfidenceLevel.MEDIUM if layer_type != LayerType.UNKNOWN else ConfidenceLevel.LOW,
                evidence_refs=[stable_id("evidence", "layer", str(layer_type))],
            )
        )

    status = DerivedStatus.FORMED if assignments and len(assignments) >= 2 else DerivedStatus.HEURISTIC
    uncertainty_note = None
    if not assignments:
        status = DerivedStatus.UNKNOWN
        uncertainty_note = "Not enough module signals to form a stable teaching layer view."
    elif LayerType.UNKNOWN in {assignment.layer_type for assignment in assignments}:
        uncertainty_note = "Some modules could only be placed heuristically or remained unknown."

    return LayerViewResult(
        layer_view_id=stable_id("layer-view", len(assignments), *(str(assignment.layer_type) for assignment in assignments)),
        status=status,
        layers=assignments,
        uncertainty_note=uncertainty_note,
        evidence_refs=[ref for assignment in assignments for ref in assignment.evidence_refs],
    )
