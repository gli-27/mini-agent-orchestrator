"""DAG engine using Kahn's algorithm for topological sort.

Produces parallelism levels: groups of nodes that can execute concurrently.
"""

from __future__ import annotations

from collections import defaultdict, deque

from agent_orchestrator.models.workflow import Workflow, WorkflowEdge


class DAGValidationError(Exception):
    """Raised when a workflow definition is not a valid DAG."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class DAGEngine:
    """Validates workflow DAGs and computes execution levels via Kahn's algorithm.

    Execution levels are groups of nodes with no interdependencies, meaning
    all nodes within a single level can execute in parallel.
    """

    def validate(self, workflow: Workflow) -> None:
        """Validate workflow DAG structure.

        Checks:
        - All edge endpoints reference existing nodes
        - No duplicate node IDs
        - No self-loops
        - No cycles (via Kahn's algorithm)

        Raises:
            DAGValidationError: If the workflow is not a valid DAG.
        """
        node_ids = {node.node_id for node in workflow.nodes}

        # Check for duplicate node IDs
        if len(node_ids) != len(workflow.nodes):
            seen: set[str] = set()
            duplicates: list[str] = []
            for node in workflow.nodes:
                if node.node_id in seen:
                    duplicates.append(node.node_id)
                seen.add(node.node_id)
            raise DAGValidationError(
                f"Duplicate node IDs: {duplicates}",
                details={"duplicates": duplicates},
            )

        # Check edge references
        for edge in workflow.edges:
            if edge.source not in node_ids:
                raise DAGValidationError(
                    f"Edge source '{edge.source}' not found in nodes",
                    details={"invalid_source": edge.source},
                )
            if edge.target not in node_ids:
                raise DAGValidationError(
                    f"Edge target '{edge.target}' not found in nodes",
                    details={"invalid_target": edge.target},
                )
            if edge.source == edge.target:
                raise DAGValidationError(
                    f"Self-loop detected on node '{edge.source}'",
                    details={"self_loop": edge.source},
                )

        # Check for cycles using Kahn's algorithm
        levels = self._topological_sort(node_ids, workflow.edges)
        sorted_count = sum(len(level) for level in levels)
        if sorted_count != len(node_ids):
            raise DAGValidationError(
                "Cycle detected in workflow DAG",
                details={"sorted_nodes": sorted_count, "total_nodes": len(node_ids)},
            )

    def compute_levels(self, workflow: Workflow) -> list[list[str]]:
        """Compute parallel execution levels using Kahn's algorithm (BFS topological sort).

        Returns:
            List of levels, where each level is a list of node IDs that can
            execute concurrently. Levels are ordered — level N+1 depends on level N.

        Raises:
            DAGValidationError: If the workflow contains cycles.
        """
        self.validate(workflow)
        node_ids = {node.node_id for node in workflow.nodes}
        return self._topological_sort(node_ids, workflow.edges)

    def get_predecessors(self, workflow: Workflow, node_id: str) -> list[str]:
        """Get all direct predecessors of a node."""
        return [edge.source for edge in workflow.edges if edge.target == node_id]

    def get_successors(self, workflow: Workflow, node_id: str) -> list[str]:
        """Get all direct successors of a node."""
        return [edge.target for edge in workflow.edges if edge.source == node_id]

    def _topological_sort(
        self, node_ids: set[str], edges: list[WorkflowEdge]
    ) -> list[list[str]]:
        """Kahn's algorithm producing parallelism levels.

        BFS-based topological sort that groups nodes into levels.
        Nodes in the same level have all their dependencies satisfied
        by prior levels.
        """
        # Build adjacency and in-degree
        in_degree: dict[str, int] = {nid: 0 for nid in node_ids}
        adjacency: dict[str, list[str]] = defaultdict(list)

        for edge in edges:
            in_degree[edge.target] += 1
            adjacency[edge.source].append(edge.target)

        # Start with nodes that have no incoming edges
        queue: deque[str] = deque(
            sorted(nid for nid, deg in in_degree.items() if deg == 0)
        )

        levels: list[list[str]] = []

        while queue:
            # All nodes currently in the queue form one parallel level
            current_level = sorted(queue)  # Sort for deterministic ordering
            queue.clear()

            for node_id in current_level:
                for successor in adjacency[node_id]:
                    in_degree[successor] -= 1
                    if in_degree[successor] == 0:
                        queue.append(successor)

            levels.append(current_level)

        return levels
