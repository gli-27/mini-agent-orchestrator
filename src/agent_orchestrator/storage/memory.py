"""In-memory workflow store implementation."""

from __future__ import annotations

from agent_orchestrator.models.workflow import Workflow
from agent_orchestrator.storage.base import WorkflowStore


class InMemoryWorkflowStore(WorkflowStore):
    """In-memory implementation of workflow storage.

    Suitable for development, testing, and single-instance deployments.
    """

    def __init__(self) -> None:
        self._workflows: dict[str, Workflow] = {}

    async def save(self, workflow: Workflow) -> Workflow:
        """Save a workflow.

        Raises:
            ValueError: If workflow_id already exists.
        """
        if workflow.workflow_id in self._workflows:
            raise ValueError(f"Workflow '{workflow.workflow_id}' already exists")
        self._workflows[workflow.workflow_id] = workflow
        return workflow

    async def get(self, workflow_id: str) -> Workflow | None:
        """Get workflow by ID, or None if not found."""
        return self._workflows.get(workflow_id)

    async def list_workflows(self) -> list[Workflow]:
        """List all workflows."""
        return list(self._workflows.values())

    async def delete(self, workflow_id: str) -> None:
        """Delete workflow by ID.

        Raises:
            KeyError: If workflow_id not found.
        """
        if workflow_id not in self._workflows:
            raise KeyError(f"Workflow '{workflow_id}' not found")
        del self._workflows[workflow_id]
