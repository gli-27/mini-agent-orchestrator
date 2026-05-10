"""Execution run and node result models."""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from pydantic import BaseModel, Field


class RunStatus(str, enum.Enum):
    """Status of a workflow execution run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIALLY_FAILED = "partially_failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class NodeResult(BaseModel):
    """Result of executing a single node in a workflow."""

    node_id: str = Field(..., description="The node that was executed")
    status: RunStatus = Field(..., description="Outcome status of the node execution")
    output: dict | None = Field(default=None, description="Output data from the agent")
    error: str | None = Field(default=None, description="Error message if execution failed")
    started_at: datetime | None = Field(default=None, description="When execution started")
    completed_at: datetime | None = Field(default=None, description="When execution finished")
    attempts: int = Field(default=0, description="Number of attempts made")
    duration_ms: float | None = Field(default=None, description="Total execution time in ms")


class ExecutionRun(BaseModel):
    """A single execution run of a workflow."""

    run_id: str = Field(..., description="Unique run identifier")
    workflow_id: str = Field(..., description="ID of the workflow being executed")
    status: RunStatus = Field(default=RunStatus.PENDING, description="Current run status")
    input_data: dict = Field(default_factory=dict, description="Input data for the workflow")
    node_results: dict[str, NodeResult] = Field(
        default_factory=dict, description="Results keyed by node_id"
    )
    output: dict | None = Field(default=None, description="Final aggregated workflow output")
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def compute_status(self) -> RunStatus:
        """Compute overall run status from node results."""
        if not self.node_results:
            return RunStatus.PENDING

        statuses = {r.status for r in self.node_results.values()}

        if statuses == {RunStatus.COMPLETED}:
            return RunStatus.COMPLETED
        if RunStatus.RUNNING in statuses:
            return RunStatus.RUNNING
        if RunStatus.FAILED in statuses and RunStatus.COMPLETED in statuses:
            return RunStatus.PARTIALLY_FAILED
        if statuses == {RunStatus.FAILED}:
            return RunStatus.FAILED
        return RunStatus.RUNNING
