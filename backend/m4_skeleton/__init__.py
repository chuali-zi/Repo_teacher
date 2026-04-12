"""M4 teaching skeleton assembler.

Maps AnalysisBundle to TeachingSkeleton in OUT-1 order, builds topic_index for
controlled M6 slices, and aggregates user-visible unknowns.
"""

from backend.contracts.domain import AnalysisBundle, TeachingSkeleton
from backend.m4_skeleton.skeleton_assembler import assemble_skeleton

MODULE_DESCRIPTION = __doc__ or "M4 teaching skeleton assembler"


def assemble_teaching_skeleton(analysis: AnalysisBundle) -> TeachingSkeleton:
    return assemble_skeleton(analysis)
