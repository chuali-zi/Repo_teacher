"""deep_research dedicated agents (Decomposer / Investigator / NoteTaker / Composer).

Each agent inherits ``BaseResearchAgent`` and is wired by ``DeepResearchLoop``.
This package does NOT import or reuse ``agents.teacher`` / ``agents.reading_agent`` /
``agents.orient_planner`` (forbidden by AGENTS.md §0.2 / §11.1).
"""

from __future__ import annotations

from .base_research_agent import BaseResearchAgent

__all__ = ["BaseResearchAgent"]

# Optional re-exports populated as Wave 3 lands the four agents.
try:
    from .decomposer import Decomposer  # noqa: F401
    __all__.append("Decomposer")
except ImportError:
    pass

try:
    from .investigator import Investigator  # noqa: F401
    __all__.append("Investigator")
except ImportError:
    pass

try:
    from .note_taker import NoteTaker  # noqa: F401
    __all__.append("NoteTaker")
except ImportError:
    pass

try:
    from .composer import Composer  # noqa: F401
    __all__.append("Composer")
except ImportError:
    pass
