from __future__ import annotations

from backend.contracts.domain import AnalysisBundle, ReadingStep
from backend.contracts.enums import MainPathRole, ReadingTargetType


def build_reading_path(analysis: AnalysisBundle) -> list[ReadingStep]:
    steps: list[ReadingStep] = []
    next_step_no = 1

    for entry in analysis.entry_candidates[:1]:
        if entry.target_value == "unknown":
            continue
        steps.append(
            ReadingStep(
                step_no=next_step_no,
                target=entry.target_value,
                target_type=ReadingTargetType.FILE,
                reason="Start from the most likely entry to understand how the project boots.",
                learning_gain="You will see the first executable boundary and initial wiring.",
                skippable=None,
                next_step_hint="Then inspect the main package or module it reaches next.",
                evidence_refs=entry.evidence_refs,
            )
        )
        next_step_no += 1

    for module in analysis.module_summaries[:3]:
        if next_step_no > 5:
            break
        target_type = ReadingTargetType.DIRECTORY if "/" not in module.path and not module.path.endswith(".py") else ReadingTargetType.MODULE
        steps.append(
            ReadingStep(
                step_no=next_step_no,
                target=module.path,
                target_type=target_type,
                reason=module.responsibility or "Key module from static analysis.",
                learning_gain="You will build a clearer map of the project's main responsibilities.",
                skippable="Lower-ranked support modules can wait until the main path is clear." if module.main_path_role != MainPathRole.MAIN_PATH else None,
                next_step_hint="Use the inferred layers and flow as a cross-check while reading.",
                evidence_refs=module.evidence_refs,
            )
        )
        next_step_no += 1

    if analysis.flow_summaries and next_step_no <= 6:
        flow = analysis.flow_summaries[0]
        steps.append(
            ReadingStep(
                step_no=next_step_no,
                target=flow.flow_id,
                target_type=ReadingTargetType.FLOW,
                reason="Review the inferred teaching flow after reading the entry and main modules.",
                learning_gain="You can connect individual files into a repository-level execution story.",
                skippable=None,
                next_step_hint="Return to unknown items if the inferred flow still leaves gaps.",
                evidence_refs=flow.evidence_refs,
            )
        )

    return steps[:6]
