"""Execution API router — start and monitor workflow runs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from agent_orchestrator.api.schemas import StartExecutionRequest
from agent_orchestrator.api.workflows import get_workflow_store
from agent_orchestrator.execution.manager import ExecutionManager
from agent_orchestrator.models.execution import ExecutionRun

router = APIRouter(prefix="/v1/executions", tags=["executions"])

# Execution manager injected at startup
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


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def start_execution(request: StartExecutionRequest) -> ExecutionRun:
    """Start a workflow execution.

    Returns the completed execution run (synchronous for now;
    can be made async with SQS/task queue later).
    """
    manager = _get_manager()
    workflows = get_workflow_store()

    workflow = workflows.get(request.workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{request.workflow_id}' not found",
        )

    run = await manager.start_run(workflow=workflow, input_data=request.input_data)
    return run


@router.get("/{run_id}")
async def get_execution(run_id: str) -> ExecutionRun:
    """Get execution run status by ID."""
    manager = _get_manager()
    run = await manager.get_run(run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution run '{run_id}' not found",
        )
    return run


@router.get("")
async def list_executions() -> list[ExecutionRun]:
    """List all execution runs."""
    manager = _get_manager()
    return list(manager.runs.values())
