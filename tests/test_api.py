"""Integration tests for the API endpoints."""

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient

from agent_orchestrator.main import create_app


@pytest.fixture
def app():
    """Fresh app for each test."""
    return create_app()


@pytest.fixture
async def client(app):
    """Async test client with lifespan triggered."""
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


class TestHealthEndpoint:
    """Test health check."""

    async def test_health(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["service"] == "agent-orchestrator"


class TestAgentsAPI:
    """Test /v1/agents endpoints."""

    async def test_register_agent(self, client: AsyncClient):
        resp = await client.post("/v1/agents", json={
            "agent_id": "agent-1",
            "name": "Test Agent",
            "endpoint": "http://localhost:9000/invoke",
            "capabilities": ["test"],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["agent_id"] == "agent-1"
        assert data["status"] == "active"

    async def test_register_duplicate_409(self, client: AsyncClient):
        await client.post("/v1/agents", json={
            "agent_id": "dup",
            "name": "Dup",
            "endpoint": "http://x/invoke",
        })
        resp = await client.post("/v1/agents", json={
            "agent_id": "dup",
            "name": "Dup2",
            "endpoint": "http://y/invoke",
        })
        assert resp.status_code == 409

    async def test_list_agents(self, client: AsyncClient):
        await client.post("/v1/agents", json={
            "agent_id": "a1",
            "name": "A1",
            "endpoint": "http://x/invoke",
        })
        resp = await client.get("/v1/agents")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    async def test_get_agent(self, client: AsyncClient):
        await client.post("/v1/agents", json={
            "agent_id": "get-me",
            "name": "GetMe",
            "endpoint": "http://x/invoke",
        })
        resp = await client.get("/v1/agents/get-me")
        assert resp.status_code == 200
        assert resp.json()["agent_id"] == "get-me"

    async def test_get_nonexistent_404(self, client: AsyncClient):
        resp = await client.get("/v1/agents/nope")
        assert resp.status_code == 404

    async def test_update_agent(self, client: AsyncClient):
        await client.post("/v1/agents", json={
            "agent_id": "upd",
            "name": "Original",
            "endpoint": "http://x/invoke",
        })
        resp = await client.patch("/v1/agents/upd", json={"name": "Updated"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated"

    async def test_delete_agent(self, client: AsyncClient):
        await client.post("/v1/agents", json={
            "agent_id": "del-me",
            "name": "DeleteMe",
            "endpoint": "http://x/invoke",
        })
        resp = await client.delete("/v1/agents/del-me")
        assert resp.status_code == 204

        resp = await client.get("/v1/agents/del-me")
        assert resp.status_code == 404

    async def test_heartbeat(self, client: AsyncClient):
        await client.post("/v1/agents", json={
            "agent_id": "hb",
            "name": "HB",
            "endpoint": "http://x/invoke",
        })
        resp = await client.post("/v1/agents/hb/heartbeat")
        assert resp.status_code == 200
        assert resp.json()["last_heartbeat"] is not None


class TestWorkflowsAPI:
    """Test /v1/workflows endpoints."""

    async def test_create_workflow(self, client: AsyncClient):
        resp = await client.post("/v1/workflows", json={
            "workflow_id": "wf-1",
            "name": "Test WF",
            "nodes": [
                {"node_id": "n1", "agent_id": "a1"},
                {"node_id": "n2", "agent_id": "a2"},
            ],
            "edges": [{"source": "n1", "target": "n2"}],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["workflow_id"] == "wf-1"
        assert len(data["nodes"]) == 2

    async def test_create_workflow_with_cycle_422(self, client: AsyncClient):
        resp = await client.post("/v1/workflows", json={
            "workflow_id": "wf-cycle",
            "name": "Cycle WF",
            "nodes": [
                {"node_id": "a", "agent_id": "x"},
                {"node_id": "b", "agent_id": "x"},
            ],
            "edges": [
                {"source": "a", "target": "b"},
                {"source": "b", "target": "a"},
            ],
        })
        assert resp.status_code == 422

    async def test_create_duplicate_409(self, client: AsyncClient):
        payload = {
            "workflow_id": "wf-dup",
            "name": "Dup",
            "nodes": [{"node_id": "n1", "agent_id": "a1"}],
        }
        await client.post("/v1/workflows", json=payload)
        resp = await client.post("/v1/workflows", json=payload)
        assert resp.status_code == 409

    async def test_list_workflows(self, client: AsyncClient):
        await client.post("/v1/workflows", json={
            "workflow_id": "wf-list",
            "name": "List",
            "nodes": [{"node_id": "n1", "agent_id": "a1"}],
        })
        resp = await client.get("/v1/workflows")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    async def test_get_workflow(self, client: AsyncClient):
        await client.post("/v1/workflows", json={
            "workflow_id": "wf-get",
            "name": "Get",
            "nodes": [{"node_id": "n1", "agent_id": "a1"}],
        })
        resp = await client.get("/v1/workflows/wf-get")
        assert resp.status_code == 200

    async def test_delete_workflow(self, client: AsyncClient):
        await client.post("/v1/workflows", json={
            "workflow_id": "wf-del",
            "name": "Del",
            "nodes": [{"node_id": "n1", "agent_id": "a1"}],
        })
        resp = await client.delete("/v1/workflows/wf-del")
        assert resp.status_code == 204


class TestExecutionsAPI:
    """Test /v1/executions endpoints."""

    @respx.mock
    async def test_start_execution(self, client: AsyncClient):
        """Full execution flow through the API."""
        # Register agent
        await client.post("/v1/agents", json={
            "agent_id": "exec-agent",
            "name": "Exec Agent",
            "endpoint": "http://mock-exec/invoke",
            "max_retries": 0,
        })
        # Create workflow
        await client.post("/v1/workflows", json={
            "workflow_id": "wf-exec",
            "name": "Exec WF",
            "nodes": [
                {"node_id": "n1", "agent_id": "exec-agent", "input_mapping": {"q": "$input.query"}},
            ],
        })
        # Mock agent response
        respx.post("http://mock-exec/invoke").mock(
            return_value=httpx.Response(200, json={"answer": "42"})
        )
        # Start execution
        resp = await client.post("/v1/executions", json={
            "workflow_id": "wf-exec",
            "input_data": {"query": "meaning of life"},
        })
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "completed"
        assert data["node_results"]["n1"]["output"] == {"answer": "42"}

    async def test_start_execution_missing_workflow_404(self, client: AsyncClient):
        resp = await client.post("/v1/executions", json={
            "workflow_id": "nonexistent",
            "input_data": {},
        })
        assert resp.status_code == 404

    @respx.mock
    async def test_get_execution(self, client: AsyncClient):
        """Can retrieve execution by run_id."""
        await client.post("/v1/agents", json={
            "agent_id": "get-exec-agent",
            "name": "Agent",
            "endpoint": "http://mock-get/invoke",
            "max_retries": 0,
        })
        await client.post("/v1/workflows", json={
            "workflow_id": "wf-get-exec",
            "name": "Get Exec",
            "nodes": [{"node_id": "n1", "agent_id": "get-exec-agent"}],
        })
        respx.post("http://mock-get/invoke").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        start_resp = await client.post("/v1/executions", json={
            "workflow_id": "wf-get-exec",
        })
        run_id = start_resp.json()["run_id"]

        resp = await client.get(f"/v1/executions/{run_id}")
        assert resp.status_code == 200
        assert resp.json()["run_id"] == run_id

    async def test_get_nonexistent_execution_404(self, client: AsyncClient):
        resp = await client.get("/v1/executions/fake-id")
        assert resp.status_code == 404

    @respx.mock
    async def test_list_executions(self, client: AsyncClient):
        """List all executions."""
        await client.post("/v1/agents", json={
            "agent_id": "list-agent",
            "name": "Agent",
            "endpoint": "http://mock-list/invoke",
            "max_retries": 0,
        })
        await client.post("/v1/workflows", json={
            "workflow_id": "wf-list-exec",
            "name": "List Exec",
            "nodes": [{"node_id": "n1", "agent_id": "list-agent"}],
        })
        respx.post("http://mock-list/invoke").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        await client.post("/v1/executions", json={"workflow_id": "wf-list-exec"})

        resp = await client.get("/v1/executions")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1
