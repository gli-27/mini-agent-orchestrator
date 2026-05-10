"""WebSocket endpoint for real-time execution status streaming."""

from __future__ import annotations

import asyncio
import json

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from agent_orchestrator.execution.manager import ExecutionManager

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["websocket"])

_manager: ExecutionManager | None = None


def init_router(manager: ExecutionManager) -> None:
    """Initialize the router with the execution manager."""
    global _manager  # noqa: PLW0603
    _manager = manager


def _get_manager() -> ExecutionManager:
    """Get the execution manager or raise if not initialized."""
    if _manager is None:
        raise RuntimeError("Execution manager not initialized")
    return _manager


class ConnectionManager:
    """Manages WebSocket connections per execution run.

    Clients subscribe to a run_id and receive real-time status events
    as nodes complete or the execution finishes.
    """

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, run_id: str, websocket: WebSocket) -> None:
        """Accept and register a WebSocket connection for a run."""
        await websocket.accept()
        if run_id not in self._connections:
            self._connections[run_id] = []
        self._connections[run_id].append(websocket)
        logger.info("ws_connected", run_id=run_id)

    def disconnect(self, run_id: str, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        if run_id in self._connections:
            self._connections[run_id] = [
                ws for ws in self._connections[run_id] if ws is not websocket
            ]
            if not self._connections[run_id]:
                del self._connections[run_id]
        logger.info("ws_disconnected", run_id=run_id)

    async def broadcast(self, run_id: str, event: dict) -> None:
        """Send an event to all connections for a run."""
        connections = self._connections.get(run_id, [])
        if not connections:
            return

        message = json.dumps(event)
        dead: list[WebSocket] = []

        for ws in connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)

        # Clean up dead connections
        for ws in dead:
            self.disconnect(run_id, ws)

    def has_subscribers(self, run_id: str) -> bool:
        """Check if a run has active WebSocket subscribers."""
        return bool(self._connections.get(run_id))

    @property
    def active_connections(self) -> dict[str, list[WebSocket]]:
        """Access active connections (for testing)."""
        return self._connections


# Singleton connection manager
ws_manager = ConnectionManager()


@router.websocket("/v1/executions/{run_id}/ws")
async def execution_ws(websocket: WebSocket, run_id: str) -> None:
    """WebSocket endpoint for streaming execution status.

    Connects to a run_id and polls for status changes, sending
    events as nodes complete.
    """
    manager = _get_manager()

    await ws_manager.connect(run_id, websocket)
    try:
        # Send initial status
        run = await manager.get_run(run_id)
        if run is None:
            await websocket.send_json({"error": f"Run '{run_id}' not found"})
            return

        await websocket.send_json({
            "event": "connected",
            "run_id": run_id,
            "status": run.status.value,
        })

        # Poll for updates until execution completes or client disconnects
        seen_nodes: set[str] = set()
        terminal_statuses = {"completed", "failed", "partially_failed", "timed_out", "cancelled"}

        while True:
            run = await manager.get_run(run_id)
            if run is None:
                break

            # Send events for newly completed nodes
            for node_id, result in run.node_results.items():
                if node_id not in seen_nodes:
                    seen_nodes.add(node_id)
                    await websocket.send_json({
                        "event": "node_completed",
                        "run_id": run_id,
                        "node_id": node_id,
                        "status": result.status.value,
                        "duration_ms": result.duration_ms,
                    })

            # Check if execution is done
            if run.status.value in terminal_statuses:
                await websocket.send_json({
                    "event": "execution_done",
                    "run_id": run_id,
                    "status": run.status.value,
                })
                break

            await asyncio.sleep(0.1)  # Poll interval

    except WebSocketDisconnect:
        logger.info("ws_client_disconnected", run_id=run_id)
    finally:
        ws_manager.disconnect(run_id, websocket)
