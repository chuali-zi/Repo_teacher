from __future__ import annotations

from backend.contracts.enums import PromptScenario

OUTPUT_TOKEN_BUDGETS: dict[PromptScenario, int] = {
    PromptScenario.INITIAL_REPORT: 2400,
    PromptScenario.FOLLOW_UP: 1400,
    PromptScenario.GOAL_SWITCH: 1400,
    PromptScenario.DEPTH_ADJUSTMENT: 1000,
    PromptScenario.STAGE_SUMMARY: 1200,
}

DEFAULT_OUTPUT_TOKEN_BUDGET = 1400
INITIAL_TOOL_CONTEXT_BUDGET_CHARS = 24_000
FOLLOWUP_TOOL_CONTEXT_BUDGET_CHARS = 12_000


def output_token_budget_for_scenario(scenario: PromptScenario) -> int:
    return OUTPUT_TOKEN_BUDGETS.get(scenario, DEFAULT_OUTPUT_TOKEN_BUDGET)


def tool_context_budget_for_scenario(scenario: PromptScenario | None) -> int:
    if scenario == PromptScenario.INITIAL_REPORT:
        return INITIAL_TOOL_CONTEXT_BUDGET_CHARS
    return FOLLOWUP_TOOL_CONTEXT_BUDGET_CHARS
