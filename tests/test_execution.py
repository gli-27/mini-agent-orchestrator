"""Tests for the execution manager and node runner."""

import httpx
import pytest
import respx

from agent_orchestrator.execution.manager import ExecutionManager
from agent_orchestrator.execution.runner import NodeRunner
from agent_orchestrator.models.agent import Agent, AgentStatus
from agent_orchestrator.models.execution import RunStatus
from agent_orchestrator.models.workflow import NodeDefinition, Workflow
from agent_orchestrator.registry.memory import InMemoryAgentRegistry


@pytest.fixture
def agents() -> dict[str, Agent]:
    """Set of test agents."""
    return {
        "agent-a": Agent(
            agent_id="agent-a",
            name="Agent A",
            endpoint="http://mock-a/invoke",
            max_retries=1,
            timeout_seconds=5.0,
        ),
        "agent-b": Agent(
            agent_id="agent-b",
            name="Agent B",
            endpoint="http://mock-b/invoke",
            max_retries=1,
            timeout_seconds=5.0,
        ),
        "agent-c": Agent(
            agent_id="agent-c",
            name="Agent C",
            endpoint="http://mock-c/invoke",
            max_retries=1,
            timeout_seconds=5.0,
        ),
        "agent-d": Agent(
            agent_id="agent-d",
            name="Agent D",
            endpoint="http://mock-d/invoke",
            max_retries=1,
            timeout_seconds=5.0,
        ),
    }


@pytest.fixture
async def populated_registry(agents: dict[str, Agent]) -> InMemoryAgentRegistry:
    """Registry pre-populated with test agents."""
    registry = InMemoryAgentRegistry()
    for agent in agents.values():
        await registry.register(agent)
    return registry


class TestNodeRunner:
    """Test individual node execution."""

    @respx.mock
    async def test_successful_invocation(self):
        """Agent responds 200 with JSON output."""
        respx.post("http://mock/invoke").mock(
            return_value=httpx.Response(200, json={"result": "done"})
        )
        agent = Agent(
            agent_id="a", name="A", endpoint="http://mock/invoke", max_retries=0
        )
        node = NodeDefinition(node_id="n1", agent_id="a")
        runner = NodeRunner()
        result = await runner.run(node, agent, {"input": "test"})
        assert result.status == RunStatus.COMPLETED
        assert result.output == {"result": "done"}
        assert result.attempts == 1

    @respx.mock
    async def test_retry_on_500(self):
        """Retries on server error, eventually succeeds."""
        route = respx.post("http://mock/invoke")
        route.side_effect = [
            httpx.Response(500, json={"error": "internal"}),
            httpx.Response(200, json={"result": "ok"}),
        ]
        agent = Agent(
            agent_id="a", name="A", endpoint="http://mock/invoke", max_retries=2
        )
        node = NodeDefinition(node_id="n1", agent_id="a")
        runner = NodeRunner()
        result = await runner.run(node, agent, {})
        assert result.status == RunStatus.COMPLETED
        assert result.attempts == 2

    @respx.mock
    async def test_all_retries_exhausted(self):
        """All retries fail, returns FAILED status."""
        respx.post("http://mock/invoke").mock(
            return_value=httpx.Response(500, json={"error": "boom"})
        )
        agent = Agent(
            agent_id="a", name="A", endpoint="http://mock/invoke",
            max_retries=1, timeout_seconds=5.0,
        )
        node = NodeDefinition(node_id="n1", agent_id="a")
        runner = NodeRunner()
        result = await runner.run(node, agent, {})
        assert result.status == RunStatus.FAILED
        assert result.attempts == 2  # initial + 1 retry
        assert "HTTPStatusError" in (result.error or "")

    @respx.mock
    async def test_timeout_override(self):
        """Node timeout override is respected."""
        respx.post("http://mock/invoke").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        agent = Agent(
            agent_id="a", name="A", endpoint="http://mock/invoke",
            timeout_seconds=30.0, max_retries=0,
        )
        node = NodeDefinition(node_id="n1", agent_id="a", timeout_override=5.0)
        runner = NodeRunner()
        result = await runner.run(node, agent, {})
        assert result.status == RunStatus.COMPLETED


class TestExecutionManager:
    """Test end-to-end workflow execution."""

    @respx.mock
    async def test_linear_workflow_success(
        self, populated_registry: InMemoryAgentRegistry, sample_workflow: Workflow
    ):
        """Linear A->B->C workflow completes successfully."""
        respx.post("http://mock-a/invoke").mock(
            return_value=httpx.Response(200, json={"result": "from_a"})
        )
        respx.post("http://mock-b/invoke").mock(
            return_value=httpx.Response(200, json={"result": "from_b"})
        )
        respx.post("http://mock-c/invoke").mock(
            return_value=httpx.Response(200, json={"result": "from_c"})
        )

        manager = ExecutionManager(registry=populated_registry, max_concurrency=5)
        run = await manager.start_run(sample_workflow, input_data={"query": "hello"})

        assert run.status == RunStatus.COMPLETED
        assert len(run.node_results) == 3
        assert run.node_results["node_a"].output == {"result": "from_a"}
        assert run.node_results["node_c"].output == {"result": "from_c"}

    @respx.mock
    async def test_diamond_workflow_parallel(
        self, populated_registry: InMemoryAgentRegistry, diamond_workflow: Workflow
    ):
        """Diamond workflow executes B and C in parallel."""
        respx.post("http://mock-a/invoke").mock(
            return_value=httpx.Response(200, json={"result": "from_a"})
        )
        respx.post("http://mock-b/invoke").mock(
            return_value=httpx.Response(200, json={"result": "from_b"})
        )
        respx.post("http://mock-c/invoke").mock(
            return_value=httpx.Response(200, json={"result": "from_c"})
        )
        respx.post("http://mock-d/invoke").mock(
            return_value=httpx.Response(200, json={"result": "from_d"})
        )

        manager = ExecutionManager(registry=populated_registry, max_concurrency=5)
        run = await manager.start_run(diamond_workflow, input_data={"query": "test"})

        assert run.status == RunStatus.COMPLETED
        assert len(run.node_results) == 4

    @respx.mock
    async def test_node_failure_partial(
        self, populated_registry: InMemoryAgentRegistry, diamond_workflow: Workflow
    ):
        """One parallel node fails → PARTIALLY_FAILED."""
        respx.post("http://mock-a/invoke").mock(
            return_value=httpx.Response(200, json={"result": "from_a"})
        )
        respx.post("http://mock-b/invoke").mock(
            return_value=httpx.Response(500, json={"error": "fail"})
        )
        respx.post("http://mock-c/invoke").mock(
            return_value=httpx.Response(200, json={"result": "from_c"})
        )
        # node_d depends on node_b which failed, so data resolution will fail
        respx.post("http://mock-d/invoke").mock(
            return_value=httpx.Response(200, json={"result": "from_d"})
        )

        manager = ExecutionManager(registry=populated_registry, max_concurrency=5)
        run = await manager.start_run(diamond_workflow, input_data={"query": "test"})

        # node_b fails, node_d can't resolve inputs from node_b
        assert run.status in (RunStatus.PARTIALLY_FAILED, RunStatus.FAILED)

    @respx.mock
    async def test_missing_agent_fails_node(
        self, populated_registry: InMemoryAgentRegistry
    ):
        """Node referencing non-existent agent gets FAILED result."""
        wf = Workflow(
            workflow_id="wf-missing",
            name="Missing Agent",
            nodes=[
                NodeDefinition(
                    node_id="n1",
                    agent_id="nonexistent-agent",
                    input_mapping={"x": "$input.x"},
                ),
            ],
            edges=[],
        )
        manager = ExecutionManager(registry=populated_registry, max_concurrency=5)
        run = await manager.start_run(wf, input_data={"x": "val"})
        assert run.status == RunStatus.FAILED
        assert "not found in registry" in (run.node_results["n1"].error or "")

    @respx.mock
    async def test_unhealthy_agent_fails_node(
        self, populated_registry: InMemoryAgentRegistry
    ):
        """Node with unhealthy agent gets FAILED result."""
        await populated_registry.update("agent-a", status=AgentStatus.UNHEALTHY)
        wf = Workflow(
            workflow_id="wf-unhealthy",
            name="Unhealthy",
            nodes=[
                NodeDefinition(
                    node_id="n1", agent_id="agent-a", input_mapping={"x": "$input.x"}
                ),
            ],
            edges=[],
        )
        manager = ExecutionManager(registry=populated_registry, max_concurrency=5)
        run = await manager.start_run(wf, input_data={"x": "val"})
        assert run.status == RunStatus.FAILED
        assert "not healthy" in (run.node_results["n1"].error or "")

    @respx.mock
    async def test_get_run(self, populated_registry: InMemoryAgentRegistry):
        """Can retrieve a completed run by ID."""
        respx.post("http://mock-a/invoke").mock(
            return_value=httpx.Response(200, json={"result": "ok"})
        )
        wf = Workflow(
            workflow_id="wf-get",
            name="Get Test",
            nodes=[
                NodeDefinition(node_id="n1", agent_id="agent-a", input_mapping={}),
            ],
            edges=[],
        )
        manager = ExecutionManager(registry=populated_registry, max_concurrency=5)
        run = await manager.start_run(wf)
        retrieved = await manager.get_run(run.run_id)
        assert retrieved is not None
        assert retrieved.run_id == run.run_id
