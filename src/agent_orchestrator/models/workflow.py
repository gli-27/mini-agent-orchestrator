"""Workflow and node definition models."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class WorkflowEdge(BaseModel):
    """A directed edge in the workflow DAG."""

    source: str = Field(..., description="Source node ID")
    target: str = Field(..., description="Target node ID")


class NodeDefinition(BaseModel):
    """Definition of a single node (task) in a workflow DAG.

    Each node maps to an agent and declares how its inputs are resolved
    from workflow input or predecessor outputs.
    """

    node_id: str = Field(..., description="Unique node identifier within the workflow")
    agent_id: str = Field(..., description="ID of the agent that executes this node")
    input_mapping: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Maps parameter names to data sources. "
            "Use '$input.<field>' for workflow input, "
            "'<node_id>.output.<field>' for predecessor outputs."
        ),
    )
    timeout_override: float | None = Field(
        default=None,
        ge=1.0,
        le=300.0,
        description="Override agent timeout for this specific node",
    )
    retry_override: int | None = Field(
        default=None,
        ge=0,
        le=10,
        description="Override agent max_retries for this specific node",
    )


class Workflow(BaseModel):
    """A workflow defined as a directed acyclic graph (DAG) of nodes."""

    workflow_id: str = Field(..., description="Unique workflow identifier")
    name: str = Field(..., description="Human-readable workflow name")
    description: str = Field(default="", description="Optional workflow description")
    nodes: list[NodeDefinition] = Field(..., min_length=1, description="List of node definitions")
    edges: list[WorkflowEdge] = Field(
        default_factory=list, description="Directed edges defining dependencies"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def get_node(self, node_id: str) -> NodeDefinition | None:
        """Look up a node by ID."""
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        return None
