"""Tests for WebSocket execution status streaming."""

import httpx
import pytest
import respx
from starlette.testclient import TestClient

from agent_orchestrator.main import create_app


@pytest.fixture
def app():
    """Fresh app instance."""
    return create_app()


class TestWebSocketEndpoint:
    """Test WebSocket connection and event receipt."""

    def test_ws_connect_and_receive_events(self, app):
        """WebSocket connects, receives connected event, then execution_done."""
        with TestClient(app) as client:
            # Trigger lifespan
            # First register agent and create workflow via REST
            resp = client.post("/v1/agents", json={
                "agent_id": "ws-agent",
                "name": "WS Agent",
                "endpoint": "http://mock-ws/invoke",
                "max_retries": 0,
            })
            assert resp.status_code == 201

            resp = client.post("/v1/workflows", json={
                "workflow_id": "wf-ws",
                "name": "WS WF",
                "nodes": [{"node_id": "n1", "agent_id": "ws-agent"}],
            })
            assert resp.status_code == 201

            # Start an execution first
            with respx.mock:
                respx.post("http://mock-ws/invoke").mock(
                    return_value=httpx.Response(200, json={"result": "done"})
                )
                resp = client.post("/v1/executions", json={
                    "workflow_id": "wf-ws",
                })
            assert resp.status_code == 202
            run_id = resp.json()["run_id"]

            # Now connect WebSocket to the completed run
            with client.websocket_connect(f"/v1/executions/{run_id}/ws") as ws:
                # Should receive "connected" event
                data = ws.receive_json()
                assert data["event"] == "connected"
                assert data["run_id"] == run_id
                assert data["status"] == "completed"

                # Should receive node_completed for n1
                data = ws.receive_json()
                assert data["event"] == "node_completed"
                assert data["node_id"] == "n1"
                assert data["status"] == "completed"

                # Should receive execution_done
                data = ws.receive_json()
                assert data["event"] == "execution_done"
                assert data["status"] == "completed"

    def test_ws_not_found_run(self, app):
        """WebSocket to non-existent run sends error."""
        with TestClient(app) as client:
            with client.websocket_connect("/v1/executions/fake-run/ws") as ws:
                data = ws.receive_json()
                assert "error" in data
                assert "not found" in data["error"]

    def test_ws_disconnect_handling(self, app):
        """WebSocket gracefully handles client disconnect."""
        with TestClient(app) as client:
            # Register and start execution
            client.post("/v1/agents", json={
                "agent_id": "disc-agent",
                "name": "Disc",
                "endpoint": "http://mock-disc/invoke",
                "max_retries": 0,
            })
            client.post("/v1/workflows", json={
                "workflow_id": "wf-disc",
                "name": "Disc",
                "nodes": [{"node_id": "n1", "agent_id": "disc-agent"}],
            })

            with respx.mock:
                respx.post("http://mock-disc/invoke").mock(
                    return_value=httpx.Response(200, json={"ok": True})
                )
                resp = client.post("/v1/executions", json={
                    "workflow_id": "wf-disc",
                })
            run_id = resp.json()["run_id"]

            # Connect and immediately close
            with client.websocket_connect(f"/v1/executions/{run_id}/ws") as ws:
                data = ws.receive_json()
                assert data["event"] == "connected"
                # Client disconnects here (context manager exit)

            # Should not crash the server — health check still works
            resp = client.get("/health")
            assert resp.status_code == 200
