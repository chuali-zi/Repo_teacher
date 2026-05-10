"""deep_research module: dedicated repository onboarding loop (mode=deep).

Phases live in submodules; this package re-exports the orchestrator
``DeepResearchLoop`` (SA-07) along with the pure data layers so callers can
construct and inject the loop without reaching through internal paths.
"""

from .deep_research_loop import DeepResearchLoop
from .investigation_policy import InvestigationPolicy
from .research_scratchpad import ResearchScratchpad, SubtopicMeta, SubtopicNote
from .triage import EmptyRepositoryError, TriageDecision, triage

__all__ = [
    "DeepResearchLoop",
    "EmptyRepositoryError",
    "InvestigationPolicy",
    "ResearchScratchpad",
    "SubtopicMeta",
    "SubtopicNote",
    "TriageDecision",
    "triage",
]
