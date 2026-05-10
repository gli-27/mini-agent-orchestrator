"""Tests for DynamoDB agent registry with mocked boto3."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from agent_orchestrator.models.agent import Agent, AgentStatus
from agent_orchestrator.registry.dynamodb import DynamoDBAgentRegistry


@pytest.fixture
def mock_table():
    """Mock DynamoDB table."""
    table = MagicMock()
    table.put_item = MagicMock(return_value=None)
    table.get_item = MagicMock(return_value={})
    table.scan = MagicMock(return_value={"Items": []})
    table.delete_item = MagicMock(return_value=None)
    return table


@pytest.fixture
def registry(mock_table) -> DynamoDBAgentRegistry:
    """DynamoDB registry with mocked table."""
    with patch("boto3.resource") as mock_resource:
        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table
        mock_resource.return_value = mock_dynamodb
        reg = DynamoDBAgentRegistry(table_name="test-agents", region="us-east-1")
    # Replace internal table with our mock
    reg._table = mock_table
    return reg


@pytest.fixture
def agent() -> Agent:
    return Agent(
        agent_id="agent-1",
        name="Test Agent",
        endpoint="http://localhost:9000/invoke",
        capabilities=["test"],
    )


class TestDynamoDBAgentRegistry:
    """Test DynamoDB agent registry with mocked boto3."""

    async def test_register_calls_put_item(
        self, registry: DynamoDBAgentRegistry, agent: Agent, mock_table: MagicMock
    ):
        """Register calls put_item with ConditionExpression."""
        result = await registry.register(agent)
        assert result.agent_id == "agent-1"
        mock_table.put_item.assert_called_once()
        call_kwargs = mock_table.put_item.call_args[1]
        assert call_kwargs["ConditionExpression"] == "attribute_not_exists(agent_id)"
        assert call_kwargs["Item"]["agent_id"] == "agent-1"

    async def test_register_duplicate_raises_value_error(
        self, registry: DynamoDBAgentRegistry, agent: Agent, mock_table: MagicMock
    ):
        """Register raises ValueError on ConditionalCheckFailedException."""
        from botocore.exceptions import ClientError

        mock_table.put_item.side_effect = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": "exists"}},
            "PutItem",
        )
        with pytest.raises(ValueError, match="already exists"):
            await registry.register(agent)

    async def test_get_existing_agent(
        self, registry: DynamoDBAgentRegistry, mock_table: MagicMock
    ):
        """Get returns agent when found."""
        mock_table.get_item.return_value = {
            "Item": {
                "agent_id": "agent-1",
                "name": "Test",
                "endpoint": "http://x/invoke",
                "description": "",
                "status": "active",
                "capabilities": [],
                "timeout_seconds": 30.0,
                "max_retries": 3,
                "last_heartbeat": None,
                "created_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:00:00+00:00",
            }
        }
        result = await registry.get("agent-1")
        assert result is not None
        assert result.agent_id == "agent-1"
        assert result.status == AgentStatus.ACTIVE

    async def test_get_nonexistent_returns_none(
        self, registry: DynamoDBAgentRegistry, mock_table: MagicMock
    ):
        """Get returns None when item not found."""
        mock_table.get_item.return_value = {}
        result = await registry.get("nonexistent")
        assert result is None

    async def test_list_agents_scans_table(
        self, registry: DynamoDBAgentRegistry, mock_table: MagicMock
    ):
        """List calls scan and deserializes results."""
        mock_table.scan.return_value = {
            "Items": [
                {
                    "agent_id": "a1",
                    "name": "A1",
                    "endpoint": "http://x/invoke",
                    "description": "",
                    "status": "active",
                    "capabilities": [],
                    "timeout_seconds": 30.0,
                    "max_retries": 3,
                    "last_heartbeat": None,
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "updated_at": "2024-01-01T00:00:00+00:00",
                }
            ]
        }
        agents = await registry.list_agents()
        assert len(agents) == 1
        assert agents[0].agent_id == "a1"

    async def test_update_nonexistent_raises_key_error(
        self, registry: DynamoDBAgentRegistry, mock_table: MagicMock
    ):
        """Update raises KeyError when agent not found."""
        mock_table.get_item.return_value = {}
        with pytest.raises(KeyError, match="not found"):
            await registry.update("nonexistent", name="new")

    async def test_update_existing_agent(
        self, registry: DynamoDBAgentRegistry, mock_table: MagicMock
    ):
        """Update fetches, modifies, and puts back."""
        mock_table.get_item.return_value = {
            "Item": {
                "agent_id": "agent-1",
                "name": "Old",
                "endpoint": "http://x/invoke",
                "description": "",
                "status": "active",
                "capabilities": [],
                "timeout_seconds": 30.0,
                "max_retries": 3,
                "last_heartbeat": None,
                "created_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:00:00+00:00",
            }
        }
        result = await registry.update("agent-1", name="New")
        assert result.name == "New"
        mock_table.put_item.assert_called_once()

    async def test_delete_nonexistent_raises_key_error(
        self, registry: DynamoDBAgentRegistry, mock_table: MagicMock
    ):
        """Delete raises KeyError when agent not found."""
        mock_table.get_item.return_value = {}
        with pytest.raises(KeyError, match="not found"):
            await registry.delete("nonexistent")

    async def test_delete_existing(
        self, registry: DynamoDBAgentRegistry, mock_table: MagicMock
    ):
        """Delete calls delete_item after existence check."""
        mock_table.get_item.return_value = {
            "Item": {
                "agent_id": "agent-1",
                "name": "X",
                "endpoint": "http://x/invoke",
                "description": "",
                "status": "active",
                "capabilities": [],
                "timeout_seconds": 30.0,
                "max_retries": 3,
                "last_heartbeat": None,
                "created_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:00:00+00:00",
            }
        }
        await registry.delete("agent-1")
        mock_table.delete_item.assert_called_once_with(Key={"agent_id": "agent-1"})

    async def test_heartbeat_updates_timestamp(
        self, registry: DynamoDBAgentRegistry, mock_table: MagicMock
    ):
        """Heartbeat updates last_heartbeat and calls put_item."""
        mock_table.get_item.return_value = {
            "Item": {
                "agent_id": "agent-1",
                "name": "X",
                "endpoint": "http://x/invoke",
                "description": "",
                "status": "active",
                "capabilities": [],
                "timeout_seconds": 30.0,
                "max_retries": 3,
                "last_heartbeat": None,
                "created_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:00:00+00:00",
            }
        }
        ts = datetime.now(UTC)
        result = await registry.heartbeat("agent-1", ts)
        assert result.last_heartbeat == ts
        mock_table.put_item.assert_called_once()

    async def test_heartbeat_recovers_unhealthy(
        self, registry: DynamoDBAgentRegistry, mock_table: MagicMock
    ):
        """Heartbeat transitions UNHEALTHY → ACTIVE."""
        mock_table.get_item.return_value = {
            "Item": {
                "agent_id": "agent-1",
                "name": "X",
                "endpoint": "http://x/invoke",
                "description": "",
                "status": "unhealthy",
                "capabilities": [],
                "timeout_seconds": 30.0,
                "max_retries": 3,
                "last_heartbeat": None,
                "created_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:00:00+00:00",
            }
        }
        ts = datetime.now(UTC)
        result = await registry.heartbeat("agent-1", ts)
        assert result.status == AgentStatus.ACTIVE

    async def test_serialize_datetime_to_iso(
        self, registry: DynamoDBAgentRegistry, agent: Agent
    ):
        """Serialization converts datetime fields to ISO strings."""
        item = DynamoDBAgentRegistry._serialize(agent)
        assert isinstance(item["created_at"], str)
        assert "T" in item["created_at"]  # ISO format
        assert item["status"] == "active"
