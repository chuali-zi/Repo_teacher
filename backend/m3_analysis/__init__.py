"""M3 static analysis engine.

Runs deterministic Python-first analysis for project profile, modules, entries,
dependencies, layers, flow summaries, reading path, evidence, unknowns, and
non-Python/large-repo degradation without calling an LLM.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.contracts.domain import (
    AnalysisBundle,
    AnalysisWarning,
    EvidenceRef,
    FileTreeSnapshot,
    LayerViewResult,
    ProjectProfileResult,
    RepositoryContext,
)
from backend.contracts.enums import (
    AnalysisMode,
    DerivedStatus,
    EvidenceType,
    ImportSourceType,
    LayerType,
    UnknownTopic,
    WarningType,
)
from backend.m3_analysis.entry_detector import detect_entry_candidates
from backend.m3_analysis.evidence_collector import EvidenceCollector
from backend.m3_analysis.flow_tracer import trace_candidate_flows
from backend.m3_analysis.import_analyzer import classify_imports
from backend.m3_analysis.layer_inferrer import infer_layers
from backend.m3_analysis.module_identifier import identify_modules
from backend.m3_analysis.project_profiler import profile_project
from backend.m3_analysis.reading_path_builder import build_reading_path
from backend.m3_analysis._helpers import (
    dedupe_by_id,
    extract_declared_dependencies,
    make_unknown,
    stable_id,
    unreadable_or_sensitive_warnings,
)

MODULE_DESCRIPTION = __doc__ or "M3 static analysis engine"


def run_static_analysis(
    repository: RepositoryContext,
    file_tree: FileTreeSnapshot,
) -> AnalysisBundle:
    collector = EvidenceCollector()
    warnings, unknowns, extra_evidence = unreadable_or_sensitive_warnings(file_tree)
    collector.extend(extra_evidence)

    analysis_mode = AnalysisMode.FULL_PYTHON
    if file_tree.primary_language.lower() != "python":
        analysis_mode = AnalysisMode.DEGRADED_NON_PYTHON
    elif file_tree.source_code_file_count > repository.read_policy.max_source_files_full_analysis:
        analysis_mode = AnalysisMode.DEGRADED_LARGE_REPO
        warnings.append(
            AnalysisWarning(
                warning_id=stable_id("warning", "large-repo", file_tree.repo_id),
                type=WarningType.LARGE_REPO_LIMITED,
                message="Large repository triggered limited analysis mode.",
                user_notice=(
                    "This repository is large, so the analysis only inspects "
                    "entry-adjacent and structural signals."
                ),
                related_paths=[],
            )
        )

    project_profile = profile_project(file_tree)
    _, dependency_evidence = extract_declared_dependencies(file_tree)
    collector.extend(dependency_evidence)

    if analysis_mode == AnalysisMode.DEGRADED_NON_PYTHON:
        modules = [
            module.model_copy(update={"likely_layer": LayerType.UNKNOWN})
            for module in identify_modules(file_tree)
        ]
        layer_view = LayerViewResult(
            layer_view_id=stable_id("layer-view", repository.repo_id, "non-python"),
            status=DerivedStatus.UNKNOWN,
            layers=[],
            uncertainty_note=(
                "Primary language is not Python, so Python-specific layer inference was skipped."
            ),
            evidence_refs=[],
        )
        unknowns.append(
            make_unknown(
                topic=UnknownTopic.FLOW,
                description="Python-specific entry and flow analysis was skipped.",
                related_paths=[],
                reason="Repository primary language is not Python.",
            )
        )
        analysis = AnalysisBundle(
            bundle_id=stable_id(
                "analysis",
                repository.repo_id,
                file_tree.snapshot_id,
                str(analysis_mode),
            ),
            repo_id=repository.repo_id,
            file_tree_snapshot_id=file_tree.snapshot_id,
            generated_at=datetime.now(UTC),
            analysis_mode=analysis_mode,
            project_profile=project_profile,
            entry_candidates=[],
            import_classifications=[],
            module_summaries=modules,
            layer_view=layer_view,
            flow_summaries=[],
            reading_path=[],
            evidence_catalog=collector.list(),
            unknown_items=dedupe_by_id(unknowns, "unknown_id"),
            warnings=warnings,
        )
        analysis.reading_path = build_reading_path(analysis)
        _backfill_referenced_evidence(analysis)
        return analysis

    entries = detect_entry_candidates(file_tree)
    imports = classify_imports(file_tree)
    modules = identify_modules(file_tree)
    layer_view = infer_layers(entries, modules)

    layer_lookup: dict[str, str] = {}
    for assignment in layer_view.layers:
        for path in assignment.paths:
            layer_lookup[path] = str(assignment.layer_type)
    for index, module in enumerate(modules):
        updated_layer = layer_lookup.get(module.path)
        if updated_layer is not None:
            modules[index] = module.model_copy(update={"likely_layer": updated_layer})

    flows = trace_candidate_flows(entries, modules, imports)
    for module_index, module in enumerate(modules):
        related_entry_ids = [
            entry.entry_id
            for entry in entries
            if entry.target_value == module.path
            or module.path.startswith(entry.target_value.split("/", 1)[0])
        ]
        related_flow_ids = [flow.flow_id for flow in flows if module.path in flow.module_path]
        modules[module_index] = module.model_copy(
            update={
                "related_entry_ids": related_entry_ids,
                "related_flow_ids": related_flow_ids,
            }
        )

    if entries and entries[0].target_value == "unknown":
        unknowns.extend(entries[0].unknown_items)
        warnings.append(
            AnalysisWarning(
                warning_id=stable_id("warning", "entry-not-found", repository.repo_id),
                type=WarningType.INSUFFICIENT_EVIDENCE,
                message="No reliable entry candidate found.",
                user_notice=(
                    "No reliable entry candidate was found, so the report will focus "
                    "on structure-first reading advice."
                ),
                related_paths=[],
            )
        )

    unknown_imports = [item for item in imports if item.source_type == ImportSourceType.UNKNOWN]
    if unknown_imports:
        unknowns.append(
            make_unknown(
                topic=UnknownTopic.DEPENDENCY,
                description=f"{len(unknown_imports)} imports could not be classified confidently.",
                related_paths=[
                    path
                    for item in unknown_imports[:3]
                    for path in item.used_by_files[:1]
                ],
                reason="Imports did not match internal modules, stdlib, or declared dependencies.",
            )
        )

    analysis = AnalysisBundle(
        bundle_id=stable_id(
            "analysis",
            repository.repo_id,
            file_tree.snapshot_id,
            str(analysis_mode),
        ),
        repo_id=repository.repo_id,
        file_tree_snapshot_id=file_tree.snapshot_id,
        generated_at=datetime.now(UTC),
        analysis_mode=analysis_mode,
        project_profile=ProjectProfileResult(
            project_types=project_profile.project_types,
            primary_language=project_profile.primary_language,
            summary_text=project_profile.summary_text,
            confidence=project_profile.confidence,
            evidence_refs=project_profile.evidence_refs,
        ),
        entry_candidates=entries,
        import_classifications=imports,
        module_summaries=modules,
        layer_view=layer_view,
        flow_summaries=flows,
        reading_path=[],
        evidence_catalog=collector.list(),
        unknown_items=dedupe_by_id(unknowns, "unknown_id"),
        warnings=warnings,
    )
    analysis.reading_path = build_reading_path(analysis)
    _backfill_referenced_evidence(analysis)
    return analysis


def _backfill_referenced_evidence(analysis: AnalysisBundle) -> None:
    existing_ids = {item.evidence_id for item in analysis.evidence_catalog}
    generated: list[EvidenceRef] = []

    def add(refs: list[str], *, source_path: str | None, note: str) -> None:
        for evidence_id in refs:
            if not evidence_id or evidence_id in existing_ids:
                continue
            generated.append(
                EvidenceRef(
                    evidence_id=evidence_id,
                    type=EvidenceType.FILE_PATH,
                    source_path=source_path,
                    source_location=None,
                    content_excerpt=None,
                    is_sensitive_source=False,
                    note=note,
                )
            )
            existing_ids.add(evidence_id)

    add(analysis.project_profile.evidence_refs, source_path=None, note="Project profile signal.")
    for entry in analysis.entry_candidates:
        source_path = entry.target_value if entry.target_value != "unknown" else None
        add(entry.evidence_refs, source_path=source_path, note="Entry candidate signal.")
    for item in analysis.import_classifications:
        source_path = item.used_by_files[0] if item.used_by_files else None
        add(
            item.evidence_refs,
            source_path=source_path,
            note=f"Import classification for {item.import_name}.",
        )
    for module in analysis.module_summaries:
        add(module.evidence_refs, source_path=module.path, note="Module structure signal.")
    for assignment in analysis.layer_view.layers:
        source_path = assignment.paths[0] if assignment.paths else None
        add(assignment.evidence_refs, source_path=source_path, note="Layer inference signal.")
    add(analysis.layer_view.evidence_refs, source_path=None, note="Layer view signal.")
    for flow in analysis.flow_summaries:
        source_path = next((step.path for step in flow.steps if step.path), None)
        add(flow.evidence_refs, source_path=source_path, note="Flow inference signal.")
        for step in flow.steps:
            add(step.evidence_refs, source_path=step.path, note="Flow step signal.")
    for step in analysis.reading_path:
        add(step.evidence_refs, source_path=step.target, note="Reading path signal.")

    if generated:
        analysis.evidence_catalog = [*analysis.evidence_catalog, *generated]
