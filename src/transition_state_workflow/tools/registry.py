"""Capability-indexed registry for ChemTool implementations."""

from __future__ import annotations

from dataclasses import dataclass, field

from transition_state_workflow.tools.contracts import ChemTool, ToolCapability


@dataclass
class ChemToolRegistry:
    """Register tools by capability without coupling callers to implementations."""

    _tools_by_name: dict[str, ChemTool] = field(default_factory=dict)

    def register(self, tool: ChemTool) -> None:
        """Register one tool, replacing an existing tool with the same name."""

        if not tool.name:
            raise ValueError("tool name must be nonempty")
        if not tool.capabilities:
            raise ValueError(f"tool {tool.name} must declare at least one capability")
        self._tools_by_name[tool.name] = tool

    def get(self, name: str) -> ChemTool:
        """Return one registered tool by name."""

        try:
            return self._tools_by_name[name]
        except KeyError as exc:
            raise KeyError(f"unknown ChemTool: {name}") from exc

    def by_capability(self, capability: ToolCapability) -> tuple[ChemTool, ...]:
        """Return all tools that can provide a capability, sorted by name."""

        return tuple(
            self._tools_by_name[name]
            for name in sorted(self._tools_by_name)
            if capability in self._tools_by_name[name].capabilities
        )

    def names(self) -> tuple[str, ...]:
        """Return registered tool names in stable order."""

        return tuple(sorted(self._tools_by_name))
