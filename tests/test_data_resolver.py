"""Tests for the data resolver."""

import pytest

from agent_orchestrator.execution.data_resolver import DataResolver, DataResolverError
from agent_orchestrator.models.execution import NodeResult, RunStatus
from agent_orchestrator.models.workflow import NodeDefinition


@pytest.fixture
def resolver() -> DataResolver:
    return DataResolver()


class TestDataResolver:
    """Test input_mapping resolution."""

    def test_resolve_workflow_input(self, resolver: DataResolver):
        """$input.field resolves from workflow input."""
        node = NodeDefinition(
            node_id="n1",
            agent_id="a1",
            input_mapping={"query": "$input.text"},
        )
        result = resolver.resolve(node, {"text": "hello"}, {})
        assert result == {"query": "hello"}

    def test_resolve_nested_workflow_input(self, resolver: DataResolver):
        """$input.user.name resolves nested fields."""
        node = NodeDefinition(
            node_id="n1",
            agent_id="a1",
            input_mapping={"name": "$input.user.name"},
        )
        result = resolver.resolve(node, {"user": {"name": "Alice"}}, {})
        assert result == {"name": "Alice"}

    def test_resolve_node_output(self, resolver: DataResolver):
        """node_a.output.result resolves from predecessor output."""
        node = NodeDefinition(
            node_id="n2",
            agent_id="a2",
            input_mapping={"text": "node_a.output.result"},
        )
        node_results = {
            "node_a": NodeResult(
                node_id="node_a",
                status=RunStatus.COMPLETED,
                output={"result": "processed"},
            ),
        }
        result = resolver.resolve(node, {}, node_results)
        assert result == {"text": "processed"}

    def test_resolve_multiple_mappings(self, resolver: DataResolver):
        """Multiple input mappings resolve correctly."""
        node = NodeDefinition(
            node_id="n3",
            agent_id="a3",
            input_mapping={
                "query": "$input.question",
                "context": "summarizer.output.summary",
            },
        )
        node_results = {
            "summarizer": NodeResult(
                node_id="summarizer",
                status=RunStatus.COMPLETED,
                output={"summary": "TL;DR"},
            ),
        }
        result = resolver.resolve(node, {"question": "What?"}, node_results)
        assert result == {"query": "What?", "context": "TL;DR"}

    def test_missing_workflow_input_raises(self, resolver: DataResolver):
        """Missing field in workflow input raises DataResolverError."""
        node = NodeDefinition(
            node_id="n1",
            agent_id="a1",
            input_mapping={"x": "$input.missing"},
        )
        with pytest.raises(DataResolverError, match="Failed to resolve"):
            resolver.resolve(node, {}, {})

    def test_missing_node_result_raises(self, resolver: DataResolver):
        """Reference to non-existent node raises."""
        node = NodeDefinition(
            node_id="n1",
            agent_id="a1",
            input_mapping={"x": "nonexistent.output.field"},
        )
        with pytest.raises(DataResolverError, match="not found in completed results"):
            resolver.resolve(node, {}, {})

    def test_node_with_no_output_raises(self, resolver: DataResolver):
        """Reference to node with None output raises."""
        node = NodeDefinition(
            node_id="n1",
            agent_id="a1",
            input_mapping={"x": "prev.output.field"},
        )
        node_results = {
            "prev": NodeResult(node_id="prev", status=RunStatus.FAILED, output=None),
        }
        with pytest.raises(DataResolverError, match="has no output data"):
            resolver.resolve(node, {}, node_results)

    def test_invalid_path_format_raises(self, resolver: DataResolver):
        """Invalid path format raises."""
        node = NodeDefinition(
            node_id="n1",
            agent_id="a1",
            input_mapping={"x": "invalid_path"},
        )
        with pytest.raises(DataResolverError, match="Invalid path format"):
            resolver.resolve(node, {}, {})

    def test_empty_input_mapping(self, resolver: DataResolver):
        """Empty input_mapping returns empty dict."""
        node = NodeDefinition(node_id="n1", agent_id="a1", input_mapping={})
        result = resolver.resolve(node, {"anything": "value"}, {})
        assert result == {}

    def test_list_traversal(self, resolver: DataResolver):
        """Can traverse list indices."""
        node = NodeDefinition(
            node_id="n1",
            agent_id="a1",
            input_mapping={"first": "$input.items.0"},
        )
        result = resolver.resolve(node, {"items": ["alpha", "beta"]}, {})
        assert result == {"first": "alpha"}
