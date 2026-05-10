"""DynamoDB-backed agent registry implementation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import boto3
import structlog
from botocore.exceptions import ClientError

from agent_orchestrator.models.agent import Agent, AgentStatus
from agent_orchestrator.registry.base import AgentRegistry

logger = structlog.get_logger(__name__)


class DynamoDBAgentRegistry(AgentRegistry):
    """DynamoDB implementation of the agent registry.

    Uses asyncio.to_thread to wrap synchronous boto3 calls,
    keeping the async interface non-blocking.
    """

    def __init__(self, table_name: str, region: str = "us-west-2") -> None:
        self._dynamodb = boto3.resource("dynamodb", region_name=region)
        self._table = self._dynamodb.Table(table_name)

    async def register(self, agent: Agent) -> Agent:
        """Register a new agent in DynamoDB.

        Uses ConditionExpression to prevent overwrites.

        Raises:
            ValueError: If agent_id already exists.
        """
        item = self._serialize(agent)
        try:
            await asyncio.to_thread(
                self._table.put_item,
                Item=item,
                ConditionExpression="attribute_not_exists(agent_id)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ValueError(f"Agent '{agent.agent_id}' already exists") from exc
            raise
        return agent

    async def get(self, agent_id: str) -> Agent | None:
        """Get agent by ID from DynamoDB."""
        resp = await asyncio.to_thread(
            self._table.get_item, Key={"agent_id": agent_id}
        )
        item = resp.get("Item")
        return self._deserialize(item) if item else None

    async def list_agents(self) -> list[Agent]:
        """Scan all agents from DynamoDB."""
        resp = await asyncio.to_thread(self._table.scan)
        items = resp.get("Items", [])
        return [self._deserialize(item) for item in items]

    async def update(self, agent_id: str, **kwargs: object) -> Agent:
        """Update agent fields in DynamoDB.

        Raises:
            KeyError: If agent_id not found.
        """
        existing = await self.get(agent_id)
        if existing is None:
            raise KeyError(f"Agent '{agent_id}' not found")

        update_data = {k: v for k, v in kwargs.items() if v is not None}
        update_data["updated_at"] = datetime.now(UTC)
        updated = existing.model_copy(update=update_data)

        item = self._serialize(updated)
        await asyncio.to_thread(self._table.put_item, Item=item)
        return updated

    async def delete(self, agent_id: str) -> None:
        """Delete agent from DynamoDB.

        Raises:
            KeyError: If agent_id not found.
        """
        existing = await self.get(agent_id)
        if existing is None:
            raise KeyError(f"Agent '{agent_id}' not found")

        await asyncio.to_thread(
            self._table.delete_item, Key={"agent_id": agent_id}
        )

    async def heartbeat(self, agent_id: str, timestamp: datetime) -> Agent:
        """Record heartbeat, auto-recover from UNHEALTHY.

        Raises:
            KeyError: If agent_id not found.
        """
        existing = await self.get(agent_id)
        if existing is None:
            raise KeyError(f"Agent '{agent_id}' not found")

        update_data: dict[str, object] = {
            "last_heartbeat": timestamp,
            "updated_at": datetime.now(UTC),
        }
        if existing.status == AgentStatus.UNHEALTHY:
            update_data["status"] = AgentStatus.ACTIVE

        updated = existing.model_copy(update=update_data)
        item = self._serialize(updated)
        await asyncio.to_thread(self._table.put_item, Item=item)
        return updated

    @staticmethod
    def _serialize(agent: Agent) -> dict:
        """Convert Agent to DynamoDB item (datetime → ISO string)."""
        data = agent.model_dump()
        for key in ("created_at", "updated_at", "last_heartbeat"):
            if data.get(key) is not None:
                data[key] = data[key].isoformat()
        status = data["status"]
        data["status"] = status.value if hasattr(status, "value") else status
        return data

    @staticmethod
    def _deserialize(item: dict) -> Agent:
        """Convert DynamoDB item back to Agent model."""
        return Agent.model_validate(item)
