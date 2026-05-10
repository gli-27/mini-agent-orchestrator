"""Tests for Prometheus metrics endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient

from agent_orchestrator.main import create_app
from agent_orchestrator.metrics import (
    EXECUTION_STATUS,
    EXECUTION_TOTAL,
    NODE_EXECUTION_TOTAL,
)


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


class TestMetricsEndpoint:
    """Test /metrics Prometheus endpoint."""

    async def test_metrics_endpoint_returns_200(self, client: AsyncClient):
        """Metrics endpoint returns 200 with Prometheus content type."""
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]

    async def test_metrics_contains_service_info(self, client: AsyncClient):
        """Metrics response contains orchestrator service info."""
        resp = await client.get("/metrics")
        body = resp.text
        assert "orchestrator_info" in body
        assert 'version="0.1.0"' in body

    async def test_metrics_contains_execution_counters(self, client: AsyncClient):
        """Metrics response includes execution counter definitions."""
        resp = await client.get("/metrics")
        body = resp.text
        assert "orchestrator_executions_total" in body
        assert "orchestrator_execution_status_total" in body

    async def test_metrics_contains_node_counters(self, client: AsyncClient):
        """Metrics response includes node execution counters."""
        resp = await client.get("/metrics")
        body = resp.text
        assert "orchestrator_node_executions_total" in body
        assert "orchestrator_node_duration_seconds" in body

    async def test_metrics_contains_http_metrics(self, client: AsyncClient):
        """Metrics response includes HTTP request metrics."""
        resp = await client.get("/metrics")
        body = resp.text
        assert "orchestrator_http_requests_total" in body
        assert "orchestrator_http_request_duration_seconds" in body


class TestMetricsCounters:
    """Test that metrics counters are accessible and functional."""

    def test_execution_total_counter_increments(self):
        """Execution counter can be incremented."""
        before = EXECUTION_TOTAL.labels(workflow_id="test-wf")._value.get()
        EXECUTION_TOTAL.labels(workflow_id="test-wf").inc()
        after = EXECUTION_TOTAL.labels(workflow_id="test-wf")._value.get()
        assert after == before + 1

    def test_execution_status_counter(self):
        """Status counter tracks different outcomes."""
        EXECUTION_STATUS.labels(status="completed").inc()
        EXECUTION_STATUS.labels(status="failed").inc()
        # Should not raise
        completed = EXECUTION_STATUS.labels(status="completed")._value.get()
        assert completed >= 1

    def test_node_execution_counter(self):
        """Node execution counter tracks by agent and status."""
        NODE_EXECUTION_TOTAL.labels(agent_id="agent-a", status="completed").inc()
        val = NODE_EXECUTION_TOTAL.labels(
            agent_id="agent-a", status="completed"
        )._value.get()
        assert val >= 1
