from __future__ import annotations

from datetime import UTC, datetime

from backend.contracts.domain import (
    AnalysisBundle,
    EntryCandidate,
    EvidenceRef,
    FlowSummary,
    FlowStep,
    ImportClassification,
    LayerAssignment,
    LayerViewResult,
    ModuleSummary,
    ProjectProfileResult,
    ReadingStep,
    UnknownItem,
)
from backend.contracts.enums import (
    AnalysisMode,
    ConfidenceLevel,
    DerivedStatus,
    EntryTargetType,
    EvidenceType,
    FlowKind,
    ImportSourceType,
    LayerType,
    MainPathRole,
    ModuleKind,
    ProjectType,
    ReadingTargetType,
    TopicRefType,
    UnknownTopic,
)
from backend.m4_skeleton import assemble_teaching_skeleton
from backend.m4_skeleton.skeleton_assembler import INITIAL_REPORT_FIELD_ORDER


def build_analysis_bundle(*, mode: AnalysisMode = AnalysisMode.FULL_PYTHON) -> AnalysisBundle:
    return AnalysisBundle(
        bundle_id="bundle_1",
        repo_id="repo_1",
        file_tree_snapshot_id="tree_1",
        generated_at=datetime(2026, 4, 12, tzinfo=UTC),
        analysis_mode=mode,
        project_profile=ProjectProfileResult(
            project_types=[
                {
                    "type": ProjectType.WEB_APP,
                    "reason": "Contains FastAPI routes.",
                    "confidence": ConfidenceLevel.HIGH,
                    "evidence_refs": ["ev_profile"],
                }
            ],
            primary_language="Python" if mode != AnalysisMode.DEGRADED_NON_PYTHON else "TypeScript",
            summary_text="A web application with API routes and a service layer.",
            confidence=ConfidenceLevel.HIGH,
            evidence_refs=["ev_profile"],
        ),
        entry_candidates=[]
        if mode == AnalysisMode.DEGRADED_NON_PYTHON
        else [
            EntryCandidate(
                entry_id="entry_main",
                target_type=EntryTargetType.FILE,
                target_value="backend/main.py",
                reason="Defines the FastAPI application startup.",
                confidence=ConfidenceLevel.HIGH,
                rank=1,
                evidence_refs=["ev_entry"],
                unknown_items=[
                    UnknownItem(
                        unknown_id="unk_entry_secondary",
                        topic=UnknownTopic.ENTRY,
                        description="A secondary startup script may exist outside the scanned path.",
                        related_paths=["scripts/dev_backend.cmd"],
                        reason="No direct execution trace.",
                        user_visible=True,
                    )
                ],
            )
        ],
        import_classifications=[]
        if mode == AnalysisMode.DEGRADED_NON_PYTHON
        else [
            ImportClassification(
                import_id="imp_fastapi",
                import_name="fastapi",
                source_type=ImportSourceType.THIRD_PARTY,
                used_by_files=["backend/main.py"],
                declared_in=["pyproject.toml"],
                basis="Declared in pyproject and imported by backend/main.py.",
                worth_expanding_now=True,
                confidence=ConfidenceLevel.HIGH,
                evidence_refs=["ev_dep"],
            )
        ],
        module_summaries=[
            ModuleSummary(
                module_id="mod_backend",
                path="backend",
                module_kind=ModuleKind.DIRECTORY,
                responsibility="API layer and orchestration code.",
                importance_rank=1,
                likely_layer=LayerType.ROUTE_OR_CONTROLLER,
                main_path_role=MainPathRole.MAIN_PATH,
                upstream_modules=[],
                downstream_modules=["mod_service"],
                related_entry_ids=["entry_main"],
                related_flow_ids=["flow_request"],
                worth_reading_now=True,
                confidence=ConfidenceLevel.HIGH,
                evidence_refs=["ev_mod_backend"],
            ),
            ModuleSummary(
                module_id="mod_service",
                path="backend/m5_session",
                module_kind=ModuleKind.PACKAGE,
                responsibility="Session service and state transitions.",
                importance_rank=2,
                likely_layer=LayerType.BUSINESS_LOGIC,
                main_path_role=MainPathRole.SUPPORTING,
                upstream_modules=["mod_backend"],
                downstream_modules=[],
                related_entry_ids=[],
                related_flow_ids=["flow_request"],
                worth_reading_now=True,
                confidence=ConfidenceLevel.MEDIUM,
                evidence_refs=["ev_mod_service"],
            ),
        ],
        layer_view=LayerViewResult(
            layer_view_id="layer_1",
            status=DerivedStatus.UNKNOWN if mode == AnalysisMode.DEGRADED_NON_PYTHON else DerivedStatus.FORMED,
            layers=[]
            if mode == AnalysisMode.DEGRADED_NON_PYTHON
            else [
                LayerAssignment(
                    layer_type=LayerType.ROUTE_OR_CONTROLLER,
                    module_ids=["mod_backend"],
                    paths=["backend"],
                    role_description="Accepts requests and dispatches work.",
                    main_path_role=MainPathRole.MAIN_PATH,
                    confidence=ConfidenceLevel.HIGH,
                    evidence_refs=["ev_layer"],
                )
            ],
            uncertainty_note="Non-Python repository cannot form a Python layer view."
            if mode == AnalysisMode.DEGRADED_NON_PYTHON
            else None,
            evidence_refs=["ev_layer"],
        ),
        flow_summaries=[]
        if mode == AnalysisMode.DEGRADED_NON_PYTHON
        else [
            FlowSummary(
                flow_id="flow_request",
                entry_candidate_id="entry_main",
                flow_kind=FlowKind.TEACHING_DATA_FLOW,
                input_source="HTTP request",
                steps=[
                    FlowStep(
                        step_no=1,
                        description="Route receives a request.",
                        module_id="mod_backend",
                        path="backend/main.py",
                        layer_type=LayerType.ROUTE_OR_CONTROLLER,
                        evidence_refs=["ev_flow"],
                        confidence=ConfidenceLevel.HIGH,
                    )
                ],
                module_path=["mod_backend", "mod_service"],
                layer_path=[LayerType.ROUTE_OR_CONTROLLER, LayerType.BUSINESS_LOGIC],
                output_target="response payload",
                fallback_reading_advice=None,
                confidence=ConfidenceLevel.MEDIUM,
                uncertainty_note=None,
                evidence_refs=["ev_flow"],
            )
        ],
        reading_path=[
            ReadingStep(
                step_no=1,
                target="backend/main.py",
                target_type=ReadingTargetType.FILE,
                reason="Start at the application bootstrap.",
                learning_gain="You will see how the app is wired together.",
                skippable=None,
                next_step_hint="Then inspect the session service.",
                evidence_refs=["ev_read_1"],
            ),
            ReadingStep(
                step_no=2,
                target="backend/m5_session",
                target_type=ReadingTargetType.DIRECTORY,
                reason="Continue into the session service package.",
                learning_gain="You will understand how requests become state transitions.",
                skippable=None,
                next_step_hint=None,
                evidence_refs=["ev_read_2"],
            ),
        ],
        evidence_catalog=[
            EvidenceRef(
                evidence_id="ev_profile",
                type=EvidenceType.FILE_PATH,
                source_path="backend/routes",
                source_location=None,
                content_excerpt=None,
                is_sensitive_source=False,
                note=None,
            )
        ],
        unknown_items=[
            UnknownItem(
                unknown_id="unk_dep_1",
                topic=UnknownTopic.DEPENDENCY,
                description="One dependency source could not be classified from the scanned files.",
                related_paths=["backend/main.py"],
                reason="Limited declaration evidence.",
                user_visible=True,
            ),
            UnknownItem(
                unknown_id="unk_hidden",
                topic=UnknownTopic.OTHER,
                description="Internal-only note",
                related_paths=[],
                reason=None,
                user_visible=False,
            ),
        ],
        warnings=[],
    )


def test_assemble_teaching_skeleton_builds_ordered_initial_report_fields() -> None:
    skeleton = assemble_teaching_skeleton(build_analysis_bundle())

    initial_report_projection = {field: getattr(skeleton, field) for field in INITIAL_REPORT_FIELD_ORDER}

    assert tuple(initial_report_projection.keys()) == INITIAL_REPORT_FIELD_ORDER
    assert skeleton.skeleton_mode == "full"
    assert skeleton.recommended_first_step.target == "backend/main.py"
    assert skeleton.topic_index.entry_refs[0].ref_type == TopicRefType.ENTRY_CANDIDATE


def test_assemble_teaching_skeleton_aggregates_user_visible_unknowns_only_once() -> None:
    skeleton = assemble_teaching_skeleton(build_analysis_bundle())

    assert [item.unknown_id for item in skeleton.unknown_section] == [
        "unk_dep_1",
        "unk_entry_secondary",
    ]
    assert [item.unknown_id for item in skeleton.entry_section.unknown_items] == ["unk_entry_secondary"]
    assert skeleton.dependency_section.unknown_count == 1


def test_assemble_teaching_skeleton_handles_non_python_degraded_mode() -> None:
    skeleton = assemble_teaching_skeleton(build_analysis_bundle(mode=AnalysisMode.DEGRADED_NON_PYTHON))

    assert skeleton.skeleton_mode == "degraded_non_python"
    assert skeleton.entry_section.status == "unknown"
    assert skeleton.flow_section.status == "unknown"
    assert skeleton.layer_section.status == "unknown"
    assert skeleton.language_and_type.degradation_notice is not None
    assert skeleton.topic_index.reading_path_refs
