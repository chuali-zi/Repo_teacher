"""M5 dialog/session manager.

Coordinates repository access, deterministic analysis, skeleton assembly,
runtime events, snapshots, chat turn lifecycle, and session cleanup.
"""

from backend.m5_session.session_service import session_service

__all__ = ["session_service"]
