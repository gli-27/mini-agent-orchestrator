"""Shared test fixtures."""

from __future__ import annotations

import pytest
import respx
from httpx import AsyncClient

from agent_orchestrator.main import create_app
from agent_orchestrator.models.agent import Agent
from agent_orchestrator.models.workflow import NodeDefinition, Workflow, WorkflowEdge
from agent_orchestrator.registry.memory import InMemoryAgentRegistry


@pytest.fixture
def registry() -> InMemoryAgentRegistry:
    """Fresh in-memory agent registry."""
    return InMemoryAgentRegistry()


@pytest.fixture
def sample_agent() -> Agent:
    """Sample agent for testing."""
    return Agent(
        agent_id="agent-summarizer",
        name="Summarizer",
        endpoint="http://localhost:9001/summarize",
        description="Summarizes text",
        capabilities=["summarize"],
        timeout_seconds=10.0,
        max_retries=2,
    )


@pytest.fixture
def sample_workflow() -> Workflow:
    """Simple linear workflow: A -> B -> C."""
    return Workflow(
        workflow_id="wf-linear",
        name="Linear Workflow",
        nodes=[
            NodeDefinition(
                node_id="node_a",
                agent_id="agent-a",
                input_mapping={"text": "$input.query"},
            ),
            NodeDefinition(
                node_id="node_b",
                agent_id="agent-b",
                input_mapping={"text": "node_a.output.result"},
            ),
            NodeDefinition(
                node_id="node_c",
                agent_id="agent-c",
                input_mapping={"text": "node_b.output.result"},
            ),
        ],
        edges=[
            WorkflowEdge(source="node_a", target="node_b"),
            WorkflowEdge(source="node_b", target="node_c"),
        ],
    )


@pytest.fixture
def diamond_workflow() -> Workflow:
    """Diamond DAG: A -> B, A -> C, B -> D, C -> D."""
    return Workflow(
        workflow_id="wf-diamond",
        name="Diamond Workflow",
        nodes=[
            NodeDefinition(
                node_id="node_a",
                agent_id="agent-a",
                input_mapping={"query": "$input.query"},
            ),
            NodeDefinition(
                node_id="node_b",
                agent_id="agent-b",
                input_mapping={"text": "node_a.output.result"},
            ),
            NodeDefinition(
                node_id="node_c",
                agent_id="agent-c",
                input_mapping={"text": "node_a.output.result"},
            ),
            NodeDefinition(
                node_id="node_d",
                agent_id="agent-d",
                input_mapping={
                    "summary": "node_b.output.result",
                    "translation": "node_c.output.result",
                },
            ),
        ],
        edges=[
            WorkflowEdge(source="node_a", target="node_b"),
            WorkflowEdge(source="node_a", target="node_c"),
            WorkflowEdge(source="node_b", target="node_d"),
            WorkflowEdge(source="node_c", target="node_d"),
        ],
    )


@pytest.fixture
def app():
    """Create a fresh app instance for testing."""
    return create_app()


@pytest.fixture
async def client(app) -> AsyncClient:
    """Async HTTP client for testing the FastAPI app."""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # Trigger lifespan
        async with app.router.lifespan_context(app):
            yield ac


@pytest.fixture
def mock_respx():
    """Respx mock context for HTTP calls."""
    with respx.mock(assert_all_called=False) as mock:
        yield mock
