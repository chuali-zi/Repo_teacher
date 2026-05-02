"""Teaching agents for the new repository tutor kernel."""

from .base_agent import BaseAgent
from .orient_planner import OrientPlan, OrientPlanner
from .reading_agent import ReadingAgent, ReadingDecision
from .sidecar_explainer import SidecarExplainer
from .teacher import TeacherAgent, TeacherOutput
from .teaching_loop import TeachingLoop


__all__ = [
    "BaseAgent",
    "OrientPlan",
    "OrientPlanner",
    "ReadingAgent",
    "ReadingDecision",
    "SidecarExplainer",
    "TeacherAgent",
    "TeacherOutput",
    "TeachingLoop",
]
