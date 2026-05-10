"""Workflow management API router."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from agent_orchestrator.api.schemas import CreateWorkflowRequest
from agent_orchestrator.dag import DAGEngine, DAGValidationError
from agent_orchestrator.models.workflow import NodeDefinition, Workflow
from agent_orchestrator.storage.base import WorkflowStore

router = APIRouter(prefix="/v1/workflows", tags=["workflows"])

_dag_engine = DAGEngine()
_store: WorkflowStore | None = None


def init_router(store: WorkflowStore) -> None:
    """Initialize the router with the workflow store."""
    global _store  # noqa: PLW0603
    _store = store


def _get_store() -> WorkflowStore:
    """Get the workflow store or raise if not initialized."""
    if _store is None:
        raise RuntimeError("Workflow store not initialized")
    return _store


def get_workflow_store() -> WorkflowStore:
    """Public accessor for the workflow store (used by executions router)."""
    return _get_store()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_workflow(request: CreateWorkflowRequest) -> Workflow:
    """Create a new workflow. Validates DAG structure on creation."""
    store = _get_store()

    # Check if already exists
    existing = await store.get(request.workflow_id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Workflow '{request.workflow_id}' already exists",
        )

    # Build workflow model
    nodes = [
        NodeDefinition(
            node_id=n.node_id,
            agent_id=n.agent_id,
            input_mapping=n.input_mapping,
            timeout_override=n.timeout_override,
            retry_override=n.retry_override,
        )
        for n in request.nodes
    ]

    workflow = Workflow(
        workflow_id=request.workflow_id,
        name=request.name,
        description=request.description,
        nodes=nodes,
        edges=request.edges,
    )

    # Validate DAG
    try:
        _dag_engine.validate(workflow)
    except DAGValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid DAG: {exc}",
        ) from exc

    await store.save(workflow)
    return workflow


@router.get("")
async def list_workflows() -> list[Workflow]:
    """List all workflows."""
    store = _get_store()
    return await store.list_workflows()


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str) -> Workflow:
    """Get workflow by ID."""
    store = _get_store()
    workflow = await store.get(workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' not found",
        )
    return workflow


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(workflow_id: str) -> None:
    """Delete a workflow."""
    store = _get_store()
    try:
        await store.delete(workflow_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' not found",
        ) from exc
