"""deep_research-local prompt root.

Construct a ``PromptManager(prompts_root=Path(__file__).parent)`` to use these
YAML files instead of the kernel-wide ``prompts/`` directory.
"""

from pathlib import Path

PROMPTS_ROOT = Path(__file__).resolve().parent

__all__ = ["PROMPTS_ROOT"]
