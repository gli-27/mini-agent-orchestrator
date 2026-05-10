"""Tests for the cancel/abort execution feature."""

import asyncio
import contextlib

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient

from agent_orchestrator.execution.manager import ExecutionManager
from agent_orchestrator.main import create_app
from agent_orchestrator.models.agent import Agent
from agent_orchestrator.models.execution import RunStatus
from agent_orchestrator.models.workflow import NodeDefinition, Workflow, WorkflowEdge
from agent_orchestrator.registry.memory import InMemoryAgentRegistry


@pytest.fixture
async def registry_with_agents() -> InMemoryAgentRegistry:
    """Registry with test agents."""
    registry = InMemoryAgentRegistry()
    await registry.register(
        Agent(
            agent_id="agent-fast",
            name="Fast",
            endpoint="http://mock-fast/invoke",
            max_retries=0,
            timeout_seconds=30.0,
        )
    )
    await registry.register(
        Agent(
            agent_id="agent-slow",
            name="Slow",
            endpoint="http://mock-slow/invoke",
            max_retries=0,
            timeout_seconds=30.0,
        )
    )
    return registry


class TestCancelExecution:
    """Test execution cancellation."""

    @respx.mock
    async def test_cancel_before_next_level(
        self, registry_with_agents: InMemoryAgentRegistry
    ):
        """Cancel after first level completes prevents second level."""
        # Workflow: fast_node (level 0) -> slow_node (level 1)
        wf = Workflow(
            workflow_id="wf-cancel",
            name="Cancel Test",
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
            edges=[WorkflowEdge(source="fast_node", target="slow_node")],
        )

        # Fast responds immediately
        respx.post("http://mock-fast/invoke").mock(
            return_value=httpx.Response(200, json={"result": "done"})
        )

        # Slow sleeps long enough to be cancelled
        async def slow_response(request):
            await asyncio.sleep(10.0)
            return httpx.Response(200, json={"result": "slow"})

        respx.post("http://mock-slow/invoke").mock(side_effect=slow_response)

        manager = ExecutionManager(
            registry=registry_with_agents,
            max_concurrency=5,
            default_timeout=30.0,
        )

        # Start execution in background
        run_task = asyncio.create_task(
            manager.start_run(wf, input_data={"x": "test"})
        )

        # Wait for first level to complete then cancel
        await asyncio.sleep(0.2)
        # Get the run_id
        run_ids = list(manager.runs.keys())
        assert len(run_ids) == 1
        run_id = run_ids[0]

        result = await manager.cancel_run(run_id)
        assert result is not None
        assert result.status == RunStatus.CANCELLED

        # Clean up the background task
        run_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await run_task

    async def test_cancel_nonexistent_returns_none(
        self, registry_with_agents: InMemoryAgentRegistry
    ):
        """Cancel on non-existent run_id returns None."""
        manager = ExecutionManager(
            registry=registry_with_agents, max_concurrency=5
        )
        result = await manager.cancel_run("fake-id")
        assert result is None

    @respx.mock
    async def test_cancel_completed_run_returns_current_status(
        self, registry_with_agents: InMemoryAgentRegistry
    ):
        """Cancel on already-completed run returns the run without changing status."""
        wf = Workflow(
            workflow_id="wf-done",
            name="Done",
            nodes=[NodeDefinition(node_id="n1", agent_id="agent-fast")],
            edges=[],
        )
        respx.post("http://mock-fast/invoke").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )

        manager = ExecutionManager(
            registry=registry_with_agents, max_concurrency=5
        )
        run = await manager.start_run(wf)
        assert run.status == RunStatus.COMPLETED

        # Try to cancel a completed run
        result = await manager.cancel_run(run.run_id)
        assert result is not None
        assert result.status == RunStatus.COMPLETED  # Unchanged


class TestCancelAPI:
    """Test cancel via API."""

    @pytest.fixture
    def app(self):
        return create_app()

    @pytest.fixture
    async def client(self, app):
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac

    async def test_cancel_endpoint_not_found(self, client: AsyncClient):
        """Cancel non-existent run returns 404."""
        resp = await client.post("/v1/executions/fake-id/cancel")
        assert resp.status_code == 404

    @respx.mock
    async def test_cancel_endpoint_completed_run(self, client: AsyncClient):
        """Cancel completed run returns current status."""
        await client.post("/v1/agents", json={
            "agent_id": "cancel-agent",
            "name": "Agent",
            "endpoint": "http://mock-cancel/invoke",
            "max_retries": 0,
        })
        await client.post("/v1/workflows", json={
            "workflow_id": "wf-cancel-api",
            "name": "Cancel",
            "nodes": [{"node_id": "n1", "agent_id": "cancel-agent"}],
        })
        respx.post("http://mock-cancel/invoke").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )

        # Start and complete
        start_resp = await client.post("/v1/executions", json={
            "workflow_id": "wf-cancel-api",
        })
        run_id = start_resp.json()["run_id"]

        # Try cancel after completion
        resp = await client.post(f"/v1/executions/{run_id}/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"
