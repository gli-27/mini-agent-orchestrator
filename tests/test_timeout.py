"""Tests for execution timeout feature."""

import asyncio

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient

from agent_orchestrator.execution.manager import ExecutionManager
from agent_orchestrator.main import create_app
from agent_orchestrator.models.agent import Agent
from agent_orchestrator.models.execution import RunStatus
from agent_orchestrator.models.workflow import NodeDefinition, Workflow
from agent_orchestrator.registry.memory import InMemoryAgentRegistry


@pytest.fixture
def slow_agent() -> Agent:
    """Agent that simulates slow responses."""
    return Agent(
        agent_id="agent-slow",
        name="Slow Agent",
        endpoint="http://mock-slow/invoke",
        max_retries=0,
        timeout_seconds=60.0,
    )


@pytest.fixture
async def registry_with_slow_agent(slow_agent: Agent) -> InMemoryAgentRegistry:
    """Registry with slow agent registered."""
    registry = InMemoryAgentRegistry()
    await registry.register(slow_agent)
    return registry


@pytest.fixture
def slow_workflow() -> Workflow:
    """Workflow with a single slow node."""
    return Workflow(
        workflow_id="wf-slow",
        name="Slow Workflow",
        nodes=[
            NodeDefinition(
                node_id="slow_node",
                agent_id="agent-slow",
                input_mapping={"x": "$input.x"},
            ),
        ],
        edges=[],
    )


class TestExecutionTimeout:
    """Test execution-level timeout enforcement."""

    @respx.mock
    async def test_timeout_triggers_timed_out_status(
        self, registry_with_slow_agent: InMemoryAgentRegistry, slow_workflow: Workflow
    ):
        """Execution that exceeds timeout returns TIMED_OUT status."""

        async def slow_response(request):
            await asyncio.sleep(5.0)  # Sleep longer than timeout
            return httpx.Response(200, json={"result": "done"})

        respx.post("http://mock-slow/invoke").mock(side_effect=slow_response)

        manager = ExecutionManager(
            registry=registry_with_slow_agent,
            max_concurrency=5,
            default_timeout=0.1,  # 100ms timeout — will trigger before 5s sleep
        )
        run = await manager.start_run(slow_workflow, input_data={"x": "val"})

        assert run.status == RunStatus.TIMED_OUT
        assert run.completed_at is not None

    @respx.mock
    async def test_explicit_timeout_overrides_default(
        self, registry_with_slow_agent: InMemoryAgentRegistry, slow_workflow: Workflow
    ):
        """Explicit timeout parameter overrides the default."""

        async def slow_response(request):
            await asyncio.sleep(5.0)
            return httpx.Response(200, json={"result": "done"})

        respx.post("http://mock-slow/invoke").mock(side_effect=slow_response)

        manager = ExecutionManager(
            registry=registry_with_slow_agent,
            max_concurrency=5,
            default_timeout=300.0,  # High default — should NOT trigger
        )
        # But explicit timeout of 0.1s should trigger
        run = await manager.start_run(
            slow_workflow, input_data={"x": "val"}, timeout=0.1
        )

        assert run.status == RunStatus.TIMED_OUT

    @respx.mock
    async def test_no_timeout_when_fast_enough(
        self, registry_with_slow_agent: InMemoryAgentRegistry, slow_workflow: Workflow
    ):
        """Execution that completes within timeout returns normally."""
        respx.post("http://mock-slow/invoke").mock(
            return_value=httpx.Response(200, json={"result": "fast"})
        )

        manager = ExecutionManager(
            registry=registry_with_slow_agent,
            max_concurrency=5,
            default_timeout=10.0,  # Generous timeout
        )
        run = await manager.start_run(slow_workflow, input_data={"x": "val"})

        assert run.status == RunStatus.COMPLETED
        assert run.node_results["slow_node"].output == {"result": "fast"}

    @respx.mock
    async def test_timeout_preserves_partial_results(
        self, registry_with_slow_agent: InMemoryAgentRegistry
    ):
        """When timeout fires mid-execution, partial results are preserved."""
        # Register a fast agent too
        fast_agent = Agent(
            agent_id="agent-fast",
            name="Fast Agent",
            endpoint="http://mock-fast/invoke",
            max_retries=0,
            timeout_seconds=5.0,
        )
        await registry_with_slow_agent.register(fast_agent)

        # Workflow: fast_node (level 0) -> slow_node (level 1)
        wf = Workflow(
            workflow_id="wf-partial",
            name="Partial",
            nodes=[
                NodeDefinition(
                    node_id="fast_node",
                    agent_id="agent-fast",
                    input_mapping={"x": "$input.x"},
                ),
                NodeDefinition(
                    node_id="slow_node",
                    agent_id="agent-slow",
                    input_mapping={"x": "fast_node.output.result"},
                ),
            ],
            edges=[{"source": "fast_node", "target": "slow_node"}],
        )

        # Fast node responds immediately
        respx.post("http://mock-fast/invoke").mock(
            return_value=httpx.Response(200, json={"result": "quick"})
        )

        # Slow node takes too long
        async def slow_response(request):
            await asyncio.sleep(5.0)
            return httpx.Response(200, json={"result": "slow"})

        respx.post("http://mock-slow/invoke").mock(side_effect=slow_response)

        manager = ExecutionManager(
            registry=registry_with_slow_agent,
            max_concurrency=5,
            default_timeout=0.5,  # Fast node finishes, slow node times out
        )
        run = await manager.start_run(wf, input_data={"x": "val"})

        assert run.status == RunStatus.TIMED_OUT
        # Fast node result should be preserved
        assert "fast_node" in run.node_results
        assert run.node_results["fast_node"].status == RunStatus.COMPLETED
        # Output includes partial results
        assert run.output is not None
        assert "fast_node" in run.output


class TestTimeoutAPI:
    """Test timeout via the API layer."""

    @pytest.fixture
    def app(self):
        return create_app()

    @pytest.fixture
    async def client(self, app):
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac

    @respx.mock
    async def test_api_timeout_parameter(self, client: AsyncClient):
        """Timeout parameter is accepted via the API."""
        # Register agent
        await client.post("/v1/agents", json={
            "agent_id": "timeout-agent",
            "name": "Timeout Agent",
            "endpoint": "http://mock-timeout/invoke",
            "max_retries": 0,
        })
        # Create workflow
        await client.post("/v1/workflows", json={
            "workflow_id": "wf-timeout",
            "name": "Timeout WF",
            "nodes": [{"node_id": "n1", "agent_id": "timeout-agent"}],
        })

        # Mock agent that sleeps
        async def slow_response(request):
            await asyncio.sleep(5.0)
            return httpx.Response(200, json={"ok": True})

        respx.post("http://mock-timeout/invoke").mock(side_effect=slow_response)

        # Start execution with short timeout (minimum is 1.0 per schema validation)
        resp = await client.post("/v1/executions", json={
            "workflow_id": "wf-timeout",
            "input_data": {},
            "timeout": 1.0,
        })
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "timed_out"

    @respx.mock
    async def test_api_no_timeout_uses_default(self, client: AsyncClient):
        """Without explicit timeout, default from config is used (300s)."""
        await client.post("/v1/agents", json={
            "agent_id": "fast-agent",
            "name": "Fast",
            "endpoint": "http://mock-fast-api/invoke",
            "max_retries": 0,
        })
        await client.post("/v1/workflows", json={
            "workflow_id": "wf-fast",
            "name": "Fast",
            "nodes": [{"node_id": "n1", "agent_id": "fast-agent"}],
        })
        respx.post("http://mock-fast-api/invoke").mock(
            return_value=httpx.Response(200, json={"done": True})
        )

        resp = await client.post("/v1/executions", json={
            "workflow_id": "wf-fast",
            "input_data": {},
        })
        assert resp.status_code == 202
        assert resp.json()["status"] == "completed"
