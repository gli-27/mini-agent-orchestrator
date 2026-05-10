"""Tests for the workflow store."""

import pytest

from agent_orchestrator.models.workflow import NodeDefinition, Workflow, WorkflowEdge
from agent_orchestrator.storage.memory import InMemoryWorkflowStore


@pytest.fixture
def store() -> InMemoryWorkflowStore:
    return InMemoryWorkflowStore()


@pytest.fixture
def workflow() -> Workflow:
    return Workflow(
        workflow_id="wf-test",
        name="Test Workflow",
        nodes=[
            NodeDefinition(node_id="n1", agent_id="a1"),
            NodeDefinition(node_id="n2", agent_id="a2"),
        ],
        edges=[WorkflowEdge(source="n1", target="n2")],
    )


class TestInMemoryWorkflowStore:
    """Test in-memory workflow store operations."""

    async def test_save_workflow(self, store: InMemoryWorkflowStore, workflow: Workflow):
        result = await store.save(workflow)
        assert result.workflow_id == "wf-test"

    async def test_save_duplicate_raises(self, store: InMemoryWorkflowStore, workflow: Workflow):
        await store.save(workflow)
        with pytest.raises(ValueError, match="already exists"):
            await store.save(workflow)

    async def test_get_existing(self, store: InMemoryWorkflowStore, workflow: Workflow):
        await store.save(workflow)
        result = await store.get("wf-test")
        assert result is not None
        assert result.workflow_id == "wf-test"
        assert len(result.nodes) == 2

    async def test_get_nonexistent_returns_none(self, store: InMemoryWorkflowStore):
        result = await store.get("nonexistent")
        assert result is None

    async def test_list_workflows(self, store: InMemoryWorkflowStore, workflow: Workflow):
        await store.save(workflow)
        wf2 = Workflow(
            workflow_id="wf-2",
            name="WF 2",
            nodes=[NodeDefinition(node_id="n1", agent_id="a1")],
        )
        await store.save(wf2)
        workflows = await store.list_workflows()
        assert len(workflows) == 2

    async def test_delete_workflow(self, store: InMemoryWorkflowStore, workflow: Workflow):
        await store.save(workflow)
        await store.delete("wf-test")
        result = await store.get("wf-test")
        assert result is None

    async def test_delete_nonexistent_raises(self, store: InMemoryWorkflowStore):
        with pytest.raises(KeyError, match="not found"):
            await store.delete("nonexistent")
