"""Runtime wrapper for read-only repository tools."""

from __future__ import annotations

from typing import Any

from .tool_protocol import BaseTool, ToolContext, ToolResult


class ToolRuntime:
    """
    Capability-scoped action router for read-only tools.

    The runtime owns only tool registration and action dispatch. It does not
    know about sessions, events, scratchpads, agents, or visible answers.
    """

    def __init__(
        self,
        tools: list[BaseTool],
        *,
        control_actions: tuple[str, ...] = ("done",),
    ) -> None:
        self._tools = tuple(tools)
        self._control_actions = frozenset(control_actions)
        self._tool_by_action: dict[str, BaseTool] = {}

        for tool in self._tools:
            definition = tool.get_definition()
            if not definition.name:
                raise ValueError("tool name must be non-empty")
            if definition.name in self._tool_by_action:
                raise ValueError(f"duplicate tool action: {definition.name}")
            if definition.name in self._control_actions:
                raise ValueError(f"tool action conflicts with control action: {definition.name}")

            self._tool_by_action[definition.name] = tool

            for alias in tool.get_prompt_hints().aliases:
                if not alias.name:
                    continue
                if alias.name in self._control_actions:
                    raise ValueError(f"tool alias conflicts with control action: {alias.name}")
                existing = self._tool_by_action.get(alias.name)
                if existing is not None and existing is not tool:
                    raise ValueError(f"duplicate tool alias: {alias.name}")
                self._tool_by_action[alias.name] = tool

    @property
    def valid_actions(self) -> frozenset[str]:
        return frozenset(self._tool_by_action) | self._control_actions

    @property
    def tools(self) -> tuple[BaseTool, ...]:
        return self._tools

    async def execute(
        self,
        action: str,
        action_input: dict[str, Any],
        *,
        ctx: ToolContext,
    ) -> ToolResult:
        if action in self._control_actions:
            raise ValueError(f"control action must be handled by the caller: {action}")

        tool = self._tool_by_action.get(action)
        if tool is None:
            return ToolResult.fail(
                f"Unknown tool action: {action}",
                error_code="invalid_action",
                metadata={"action": action},
            )
        if action_input is None:
            action_input = {}
        if not isinstance(action_input, dict):
            return ToolResult.fail(
                "Tool action_input must be an object.",
                error_code="invalid_input",
                metadata={"action": action, "input_type": type(action_input).__name__},
            )

        try:
            result = await tool.execute(ctx=ctx, **action_input)
        except TypeError as exc:
            return ToolResult.fail(
                f"Invalid input for tool '{tool.name}': {exc}",
                error_code="invalid_input",
                metadata={"action": action, "tool": tool.name},
            )
        except Exception as exc:  # pragma: no cover - defensive tool boundary
            return ToolResult.fail(
                f"Tool '{tool.name}' failed: {exc}",
                error_code="tool_error",
                metadata={
                    "action": action,
                    "tool": tool.name,
                    "exception_type": type(exc).__name__,
                },
            )

        if not isinstance(result, ToolResult):
            return ToolResult.fail(
                f"Tool '{tool.name}' returned an invalid result.",
                error_code="invalid_result",
                metadata={"action": action, "tool": tool.name},
            )
        return result

    def build_planner_description(self) -> str:
        lines = []
        for tool in self._tools:
            definition = tool.get_definition()
            signature = _format_signature(definition)
            lines.append(f"- `{signature}`: {definition.description}")
        return "\n".join(lines)

    def build_reader_description(self) -> str:
        lines = [
            "| Action | Input | When to use |",
            "| --- | --- | --- |",
        ]
        for tool in self._tools:
            definition = tool.get_definition()
            hints = tool.get_prompt_hints()
            input_format = hints.input_format or _format_input_object(definition)
            when = hints.when_to_use or definition.description
            lines.append(f"| `{definition.name}` | `{input_format}` | {when} |")
            for alias in hints.aliases:
                if alias.name:
                    alias_input = alias.input_format or input_format
                    alias_when = alias.description or when
                    lines.append(f"| `{alias.name}` | `{alias_input}` | {alias_when} |")

        if "done" in self._control_actions:
            lines.append(
                "| `done` | `{}` | Use when the current reading step has enough evidence. |"
            )
        return "\n".join(lines)


def _format_signature(definition: Any) -> str:
    params = ", ".join(param.name for param in definition.parameters)
    return f"{definition.name}({params})"


def _format_input_object(definition: Any) -> str:
    if not definition.parameters:
        return "{}"
    pairs = []
    for parameter in definition.parameters:
        if parameter.required:
            pairs.append(f'"{parameter.name}": ...')
        else:
            default = parameter.default if parameter.default is not None else None
            pairs.append(f'"{parameter.name}": {default!r}')
    return "{" + ", ".join(pairs) + "}"


__all__ = ["ToolRuntime"]
