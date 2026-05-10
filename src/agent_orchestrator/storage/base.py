"""Abstract base for workflow storage — DynamoDB-ready interface."""

from __future__ import annotations

import abc

from agent_orchestrator.models.workflow import Workflow


class WorkflowStore(abc.ABC):
    """Abstract workflow storage interface."""

    @abc.abstractmethod
    async def save(self, workflow: Workflow) -> Workflow:
        """Save a workflow.

        Raises:
            ValueError: If workflow_id already exists.
        """

    @abc.abstractmethod
    async def get(self, workflow_id: str) -> Workflow | None:
        """Get workflow by ID, or None if not found."""

    @abc.abstractmethod
    async def list_workflows(self) -> list[Workflow]:
        """List all workflows."""

    @abc.abstractmethod
    async def delete(self, workflow_id: str) -> None:
        """Delete workflow by ID.

        Raises:
            KeyError: If workflow_id not found.
        """
