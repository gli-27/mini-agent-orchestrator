"""In-memory agent registry implementation."""

from __future__ import annotations

from datetime import UTC, datetime

from agent_orchestrator.models.agent import Agent, AgentStatus
from agent_orchestrator.registry.base import AgentRegistry


class InMemoryAgentRegistry(AgentRegistry):
    """In-memory implementation of the agent registry.

    Suitable for development, testing, and single-instance deployments.
    For production multi-instance setups, use a DynamoDB-backed implementation.
    """

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    async def register(self, agent: Agent) -> Agent:
        """Register a new agent.

        Raises:
            ValueError: If agent_id already exists.
        """
        if agent.agent_id in self._agents:
            raise ValueError(f"Agent '{agent.agent_id}' already exists")
        self._agents[agent.agent_id] = agent
        return agent

    async def get(self, agent_id: str) -> Agent | None:
        """Get agent by ID, or None if not found."""
        return self._agents.get(agent_id)

    async def list_agents(self) -> list[Agent]:
        """List all registered agents."""
        return list(self._agents.values())

    async def update(self, agent_id: str, **kwargs: object) -> Agent:
        """Update agent fields.

        Raises:
            KeyError: If agent_id not found.
        """
        if agent_id not in self._agents:
            raise KeyError(f"Agent '{agent_id}' not found")

        agent = self._agents[agent_id]
        update_data = {k: v for k, v in kwargs.items() if v is not None}
        update_data["updated_at"] = datetime.now(UTC)

        updated = agent.model_copy(update=update_data)
        self._agents[agent_id] = updated
        return updated

    async def delete(self, agent_id: str) -> None:
        """Delete agent by ID.

        Raises:
            KeyError: If agent_id not found.
        """
        if agent_id not in self._agents:
            raise KeyError(f"Agent '{agent_id}' not found")
        del self._agents[agent_id]

    async def heartbeat(self, agent_id: str, timestamp: datetime) -> Agent:
        """Record a heartbeat from an agent.

        Also transitions agent back to ACTIVE if it was UNHEALTHY.

        Raises:
            KeyError: If agent_id not found.
        """
        if agent_id not in self._agents:
            raise KeyError(f"Agent '{agent_id}' not found")

        agent = self._agents[agent_id]
        update_data: dict[str, object] = {
            "last_heartbeat": timestamp,
            "updated_at": datetime.now(UTC),
        }

        # Auto-recover from unhealthy on heartbeat
        if agent.status == AgentStatus.UNHEALTHY:
            update_data["status"] = AgentStatus.ACTIVE

        updated = agent.model_copy(update=update_data)
        self._agents[agent_id] = updated
        return updated
