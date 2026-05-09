"""Data resolver — resolves input_mapping references to actual values.

Supports:
- "$input.<field>" — resolves from workflow input data
- "<node_id>.output.<field>" — resolves from predecessor node outputs
- Nested field access via dot notation (e.g. "$input.user.name")
"""

from __future__ import annotations

import structlog

from agent_orchestrator.models.execution import NodeResult
from agent_orchestrator.models.workflow import NodeDefinition

logger = structlog.get_logger(__name__)


class DataResolverError(Exception):
    """Raised when input_mapping resolution fails."""


class DataResolver:
    """Resolves declarative input_mapping into concrete values."""

    def resolve(
        self,
        node: NodeDefinition,
        workflow_input: dict,
        node_results: dict[str, NodeResult],
    ) -> dict:
        """Resolve all input mappings for a node.

        Args:
            node: The node definition with input_mapping.
            workflow_input: The workflow's initial input data.
            node_results: Completed results from predecessor nodes.

        Returns:
            Dict of resolved parameter name → value.

        Raises:
            DataResolverError: If a mapping cannot be resolved.
        """
        resolved: dict = {}

        for param_name, source_path in node.input_mapping.items():
            try:
                value = self._resolve_path(source_path, workflow_input, node_results)
                resolved[param_name] = value
            except (KeyError, TypeError, IndexError) as exc:
                raise DataResolverError(
                    f"Failed to resolve '{source_path}' for parameter '{param_name}' "
                    f"in node '{node.node_id}': {exc}"
                ) from exc

        return resolved

    def _resolve_path(
        self,
        path: str,
        workflow_input: dict,
        node_results: dict[str, NodeResult],
    ) -> object:
        """Resolve a single path expression.

        Patterns:
            "$input.field.subfield" → workflow_input["field"]["subfield"]
            "node_a.output.field" → node_results["node_a"].output["field"]
        """
        parts = path.split(".")

        if parts[0] == "$input":
            # Workflow input reference
            return self._traverse(workflow_input, parts[1:])

        # Node output reference: "<node_id>.output.<field>..."
        node_id = parts[0]
        if len(parts) < 3 or parts[1] != "output":
            raise DataResolverError(
                f"Invalid path format: '{path}'. "
                "Expected '$input.<field>' or '<node_id>.output.<field>'"
            )

        if node_id not in node_results:
            raise DataResolverError(
                f"Node '{node_id}' not found in completed results"
            )

        node_result = node_results[node_id]
        if node_result.output is None:
            raise DataResolverError(
                f"Node '{node_id}' has no output data"
            )

        return self._traverse(node_result.output, parts[2:])

    def _traverse(self, data: object, keys: list[str]) -> object:
        """Traverse nested dict/list using dot-notation keys."""
        current = data
        for key in keys:
            if isinstance(current, dict):
                current = current[key]
            elif isinstance(current, list):
                current = current[int(key)]
            else:
                raise TypeError(
                    f"Cannot traverse into {type(current).__name__} with key '{key}'"
                )
        return current
