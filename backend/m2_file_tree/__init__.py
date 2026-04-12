"""M2 file tree scanning and filtering.

Provides read-only recursive scan, ignore/sensitive filtering, language stats,
repo sizing, and large-repo degraded scan scope.
"""

from backend.m2_file_tree.tree_scanner import scan_repository_tree

MODULE_DESCRIPTION = __doc__ or "M2 file tree scanning and filtering"

__all__ = ["scan_repository_tree"]
