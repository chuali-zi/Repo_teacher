"""SA-02 prompt tests — local PromptManager loads the four deep_research YAMLs.

Covers AGENTS.md §7 voice rules: the compose prompt must NOT carry §7.1 anti-patterns.
"""

from __future__ import annotations

import pytest

from new_kernel.deep_research.prompts import PROMPTS_ROOT
from new_kernel.prompts.prompt_manager import PromptManager


_FORBIDDEN_PHRASES = (
    "必须严格根据证据",
    "如果没有证据请保持沉默",
    "禁止推测",
    "只复述工具看到的内容",
)


def _make_local_manager() -> PromptManager:
    return PromptManager(prompts_root=PROMPTS_ROOT)


def test_local_prompt_manager_loads_decompose_yaml() -> None:
    """A PromptManager rooted at deep_research/prompts/ must resolve decompose.yaml."""

    pm = _make_local_manager()
    system = pm.get("decompose", "system")
    assert system, "decompose.yaml system block must be non-empty"

    needles = ("decompose", "deep", "导读")
    lowered = system.lower()
    assert any(needle.lower() in lowered for needle in needles), (
        f"decompose system prompt should mention an identifier in {needles}, "
        f"got first 200 chars: {system[:200]!r}"
    )


@pytest.mark.parametrize("agent_name", ["decompose", "investigate", "note", "compose"])
def test_local_prompt_manager_loads_all_four(agent_name: str) -> None:
    """Each YAML must have a non-empty system AND a non-empty user_template."""

    pm = _make_local_manager()
    system = pm.get(agent_name, "system")
    user_template = pm.get(agent_name, "user_template")
    assert system, f"{agent_name}.yaml is missing a non-empty system block"
    assert user_template, f"{agent_name}.yaml is missing a non-empty user_template block"


def test_compose_prompt_does_not_use_anti_pattern() -> None:
    """compose.yaml must avoid AGENTS.md §7.1 forbidden phrases verbatim."""

    pm = _make_local_manager()
    system = pm.get("compose", "system")
    assert system, "compose.yaml system block must be non-empty"

    for phrase in _FORBIDDEN_PHRASES:
        assert phrase not in system, (
            f"compose system prompt must NOT contain forbidden anti-pattern phrase {phrase!r}"
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
