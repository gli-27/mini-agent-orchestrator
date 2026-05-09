"""Agent domain model."""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from pydantic import BaseModel, Field


class AgentStatus(str, enum.Enum):
    """Lifecycle status of a registered agent."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    UNHEALTHY = "unhealthy"


class Agent(BaseModel):
    """A registered agent capable of processing tasks."""

    agent_id: str = Field(..., description="Unique identifier for the agent")
    name: str = Field(..., description="Human-readable agent name")
    endpoint: str = Field(..., description="HTTP endpoint URL for invoking the agent")
    description: str = Field(default="", description="Optional description of agent capabilities")
    status: AgentStatus = Field(default=AgentStatus.ACTIVE, description="Current agent status")
    capabilities: list[str] = Field(
        default_factory=list,
        description="List of capability tags (e.g. 'summarize', 'translate')",
    )
    timeout_seconds: float = Field(
        default=30.0, ge=1.0, le=300.0, description="Per-request timeout in seconds"
    )
    max_retries: int = Field(default=3, ge=0, le=10, description="Max retry attempts on failure")
    last_heartbeat: datetime | None = Field(
        default=None, description="Timestamp of last successful heartbeat"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def is_healthy(self) -> bool:
        """Check if agent is considered healthy and available for tasks."""
        return self.status == AgentStatus.ACTIVE
