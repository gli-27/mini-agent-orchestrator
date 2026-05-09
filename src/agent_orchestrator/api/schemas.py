"""API request/response schemas (separate from domain models)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent_orchestrator.models.workflow import WorkflowEdge


class RegisterAgentRequest(BaseModel):
    """Request body for registering a new agent."""

    agent_id: str = Field(..., description="Unique agent identifier")
    name: str = Field(..., description="Human-readable agent name")
    endpoint: str = Field(..., description="HTTP endpoint URL for invoking the agent")
    description: str = Field(default="")
    capabilities: list[str] = Field(default_factory=list)
    timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    max_retries: int = Field(default=3, ge=0, le=10)


class UpdateAgentRequest(BaseModel):
    """Request body for updating an agent."""

    name: str | None = None
    endpoint: str | None = None
    description: str | None = None
    capabilities: list[str] | None = None
    timeout_seconds: float | None = Field(default=None, ge=1.0, le=300.0)
    max_retries: int | None = Field(default=None, ge=0, le=10)
    status: str | None = None


class NodeDefinitionRequest(BaseModel):
    """Node definition within a create workflow request."""

    node_id: str
    agent_id: str
    input_mapping: dict[str, str] = Field(default_factory=dict)
    timeout_override: float | None = Field(default=None, ge=1.0, le=300.0)
    retry_override: int | None = Field(default=None, ge=0, le=10)


class CreateWorkflowRequest(BaseModel):
    """Request body for creating a workflow."""

    workflow_id: str = Field(..., description="Unique workflow identifier")
    name: str = Field(..., description="Workflow name")
    description: str = Field(default="")
    nodes: list[NodeDefinitionRequest] = Field(..., min_length=1)
    edges: list[WorkflowEdge] = Field(default_factory=list)


class StartExecutionRequest(BaseModel):
    """Request body for starting a workflow execution."""

    workflow_id: str = Field(..., description="ID of workflow to execute")
    input_data: dict = Field(default_factory=dict, description="Input data for the workflow")


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str
    error_code: str | None = None
