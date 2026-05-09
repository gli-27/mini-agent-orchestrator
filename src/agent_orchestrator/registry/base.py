"""Abstract base for agent registry — DynamoDB-ready interface."""

from __future__ import annotations

import abc
from datetime import datetime

from agent_orchestrator.models.agent import Agent


class AgentRegistry(abc.ABC):
    """Abstract agent registry interface.

    Implementations can back this with in-memory storage, DynamoDB,
    or any other persistence layer.
    """

    @abc.abstractmethod
    async def register(self, agent: Agent) -> Agent:
        """Register a new agent.

        Raises:
            ValueError: If agent_id already exists.
        """

    @abc.abstractmethod
    async def get(self, agent_id: str) -> Agent | None:
        """Get agent by ID, or None if not found."""

    @abc.abstractmethod
    async def list_agents(self) -> list[Agent]:
        """List all registered agents."""

    @abc.abstractmethod
    async def update(self, agent_id: str, **kwargs: object) -> Agent:
        """Update agent fields.

        Raises:
            KeyError: If agent_id not found.
        """

    @abc.abstractmethod
    async def delete(self, agent_id: str) -> None:
        """Delete agent by ID.

        Raises:
            KeyError: If agent_id not found.
        """

    @abc.abstractmethod
    async def heartbeat(self, agent_id: str, timestamp: datetime) -> Agent:
        """Record a heartbeat from an agent.

        Raises:
            KeyError: If agent_id not found.
        """
