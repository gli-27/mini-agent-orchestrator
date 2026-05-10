"""DynamoDB-backed workflow store implementation."""

from __future__ import annotations

import asyncio

import boto3
import structlog
from botocore.exceptions import ClientError

from agent_orchestrator.models.workflow import Workflow
from agent_orchestrator.storage.base import WorkflowStore

logger = structlog.get_logger(__name__)


class DynamoDBWorkflowStore(WorkflowStore):
    """DynamoDB implementation of workflow storage.

    Uses asyncio.to_thread for non-blocking boto3 calls.
    """

    def __init__(self, table_name: str, region: str = "us-west-2") -> None:
        self._dynamodb = boto3.resource("dynamodb", region_name=region)
        self._table = self._dynamodb.Table(table_name)

    async def save(self, workflow: Workflow) -> Workflow:
        """Save a workflow to DynamoDB.

        Raises:
            ValueError: If workflow_id already exists.
        """
        item = self._serialize(workflow)
        try:
            await asyncio.to_thread(
                self._table.put_item,
                Item=item,
                ConditionExpression="attribute_not_exists(workflow_id)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ValueError(
                    f"Workflow '{workflow.workflow_id}' already exists"
                ) from exc
            raise
        return workflow

    async def get(self, workflow_id: str) -> Workflow | None:
        """Get workflow by ID from DynamoDB."""
        resp = await asyncio.to_thread(
            self._table.get_item, Key={"workflow_id": workflow_id}
        )
        item = resp.get("Item")
        return self._deserialize(item) if item else None

    async def list_workflows(self) -> list[Workflow]:
        """Scan all workflows from DynamoDB."""
        resp = await asyncio.to_thread(self._table.scan)
        items = resp.get("Items", [])
        return [self._deserialize(item) for item in items]

    async def delete(self, workflow_id: str) -> None:
        """Delete workflow from DynamoDB.

        Raises:
            KeyError: If workflow_id not found.
        """
        existing = await self.get(workflow_id)
        if existing is None:
            raise KeyError(f"Workflow '{workflow_id}' not found")

        await asyncio.to_thread(
            self._table.delete_item, Key={"workflow_id": workflow_id}
        )

    @staticmethod
    def _serialize(workflow: Workflow) -> dict:
        """Convert Workflow to DynamoDB item."""
        data = workflow.model_dump(mode="json")
        return data

    @staticmethod
    def _deserialize(item: dict) -> Workflow:
        """Convert DynamoDB item back to Workflow model."""
        return Workflow.model_validate(item)
