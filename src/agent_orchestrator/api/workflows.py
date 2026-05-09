"""Workflow management API router."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from agent_orchestrator.api.schemas import CreateWorkflowRequest
from agent_orchestrator.dag import DAGEngine, DAGValidationError
from agent_orchestrator.models.workflow import NodeDefinition, Workflow

router = APIRouter(prefix="/v1/workflows", tags=["workflows"])

# In-memory workflow store (DynamoDB-ready interface pattern)
_workflows: dict[str, Workflow] = {}
_dag_engine = DAGEngine()


def get_workflow_store() -> dict[str, Workflow]:
    """Access the workflow store (for testing/dependency injection)."""
    return _workflows


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_workflow(request: CreateWorkflowRequest) -> Workflow:
    """Create a new workflow. Validates DAG structure on creation."""
    if request.workflow_id in _workflows:
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

    _workflows[workflow.workflow_id] = workflow
    return workflow


@router.get("")
async def list_workflows() -> list[Workflow]:
    """List all workflows."""
    return list(_workflows.values())


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str) -> Workflow:
    """Get workflow by ID."""
    workflow = _workflows.get(workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' not found",
        )
    return workflow


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(workflow_id: str) -> None:
    """Delete a workflow."""
    if workflow_id not in _workflows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' not found",
        )
    del _workflows[workflow_id]
