"""Agent registry — in-memory store with DynamoDB-ready interface."""

from agent_orchestrator.registry.base import AgentRegistry
from agent_orchestrator.registry.memory import InMemoryAgentRegistry

__all__ = ["AgentRegistry", "InMemoryAgentRegistry"]
