"""Tests for the agent registry."""

from datetime import UTC, datetime

import pytest

from agent_orchestrator.models.agent import Agent, AgentStatus
from agent_orchestrator.registry.memory import InMemoryAgentRegistry


@pytest.fixture
def registry() -> InMemoryAgentRegistry:
    return InMemoryAgentRegistry()


@pytest.fixture
def agent() -> Agent:
    return Agent(
        agent_id="agent-1",
        name="Test Agent",
        endpoint="http://localhost:9000/invoke",
        capabilities=["test"],
    )


class TestInMemoryRegistry:
    """Test in-memory agent registry operations."""

    async def test_register_agent(self, registry: InMemoryAgentRegistry, agent: Agent):
        result = await registry.register(agent)
        assert result.agent_id == "agent-1"
        assert result.name == "Test Agent"

    async def test_register_duplicate_raises(
        self, registry: InMemoryAgentRegistry, agent: Agent
    ):
        await registry.register(agent)
        with pytest.raises(ValueError, match="already exists"):
            await registry.register(agent)

    async def test_get_existing(self, registry: InMemoryAgentRegistry, agent: Agent):
        await registry.register(agent)
        result = await registry.get("agent-1")
        assert result is not None
        assert result.agent_id == "agent-1"

    async def test_get_nonexistent_returns_none(self, registry: InMemoryAgentRegistry):
        result = await registry.get("nonexistent")
        assert result is None

    async def test_list_agents(self, registry: InMemoryAgentRegistry, agent: Agent):
        await registry.register(agent)
        agent2 = Agent(
            agent_id="agent-2",
            name="Agent 2",
            endpoint="http://localhost:9001/invoke",
        )
        await registry.register(agent2)
        agents = await registry.list_agents()
        assert len(agents) == 2

    async def test_update_agent(self, registry: InMemoryAgentRegistry, agent: Agent):
        await registry.register(agent)
        updated = await registry.update("agent-1", name="Updated Name")
        assert updated.name == "Updated Name"
        assert updated.agent_id == "agent-1"

    async def test_update_nonexistent_raises(self, registry: InMemoryAgentRegistry):
        with pytest.raises(KeyError, match="not found"):
            await registry.update("nonexistent", name="x")

    async def test_delete_agent(self, registry: InMemoryAgentRegistry, agent: Agent):
        await registry.register(agent)
        await registry.delete("agent-1")
        result = await registry.get("agent-1")
        assert result is None

    async def test_delete_nonexistent_raises(self, registry: InMemoryAgentRegistry):
        with pytest.raises(KeyError, match="not found"):
            await registry.delete("nonexistent")

    async def test_heartbeat(self, registry: InMemoryAgentRegistry, agent: Agent):
        await registry.register(agent)
        ts = datetime.now(UTC)
        updated = await registry.heartbeat("agent-1", ts)
        assert updated.last_heartbeat == ts

    async def test_heartbeat_recovers_unhealthy(
        self, registry: InMemoryAgentRegistry, agent: Agent
    ):
        await registry.register(agent)
        await registry.update("agent-1", status=AgentStatus.UNHEALTHY)
        ts = datetime.now(UTC)
        updated = await registry.heartbeat("agent-1", ts)
        assert updated.status == AgentStatus.ACTIVE

    async def test_heartbeat_nonexistent_raises(self, registry: InMemoryAgentRegistry):
        ts = datetime.now(UTC)
        with pytest.raises(KeyError, match="not found"):
            await registry.heartbeat("nonexistent", ts)
