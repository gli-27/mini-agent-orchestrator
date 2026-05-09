"""Tests for the DAG engine — Kahn's algorithm, validation."""

import pytest

from agent_orchestrator.dag import DAGEngine, DAGValidationError
from agent_orchestrator.models.workflow import NodeDefinition, Workflow, WorkflowEdge


@pytest.fixture
def engine() -> DAGEngine:
    return DAGEngine()


class TestDAGValidation:
    """Test DAG validation logic."""

    def test_valid_linear_dag(self, engine: DAGEngine, sample_workflow: Workflow):
        """Linear A->B->C should validate without errors."""
        engine.validate(sample_workflow)  # Should not raise

    def test_valid_diamond_dag(self, engine: DAGEngine, diamond_workflow: Workflow):
        """Diamond DAG should validate without errors."""
        engine.validate(diamond_workflow)  # Should not raise

    def test_single_node_no_edges(self, engine: DAGEngine):
        """Single node with no edges is valid."""
        wf = Workflow(
            workflow_id="wf-single",
            name="Single",
            nodes=[NodeDefinition(node_id="a", agent_id="agent-a")],
            edges=[],
        )
        engine.validate(wf)

    def test_cycle_detected(self, engine: DAGEngine):
        """Cycle A->B->C->A should raise DAGValidationError."""
        wf = Workflow(
            workflow_id="wf-cycle",
            name="Cycle",
            nodes=[
                NodeDefinition(node_id="a", agent_id="agent-a"),
                NodeDefinition(node_id="b", agent_id="agent-b"),
                NodeDefinition(node_id="c", agent_id="agent-c"),
            ],
            edges=[
                WorkflowEdge(source="a", target="b"),
                WorkflowEdge(source="b", target="c"),
                WorkflowEdge(source="c", target="a"),
            ],
        )
        with pytest.raises(DAGValidationError, match="Cycle detected"):
            engine.validate(wf)

    def test_self_loop_detected(self, engine: DAGEngine):
        """Self-loop on a node should raise."""
        wf = Workflow(
            workflow_id="wf-loop",
            name="Loop",
            nodes=[NodeDefinition(node_id="a", agent_id="agent-a")],
            edges=[WorkflowEdge(source="a", target="a")],
        )
        with pytest.raises(DAGValidationError, match="Self-loop"):
            engine.validate(wf)

    def test_invalid_edge_source(self, engine: DAGEngine):
        """Edge referencing non-existent source should raise."""
        wf = Workflow(
            workflow_id="wf-bad",
            name="Bad",
            nodes=[NodeDefinition(node_id="a", agent_id="agent-a")],
            edges=[WorkflowEdge(source="nonexistent", target="a")],
        )
        with pytest.raises(DAGValidationError, match="not found in nodes"):
            engine.validate(wf)

    def test_invalid_edge_target(self, engine: DAGEngine):
        """Edge referencing non-existent target should raise."""
        wf = Workflow(
            workflow_id="wf-bad",
            name="Bad",
            nodes=[NodeDefinition(node_id="a", agent_id="agent-a")],
            edges=[WorkflowEdge(source="a", target="nonexistent")],
        )
        with pytest.raises(DAGValidationError, match="not found in nodes"):
            engine.validate(wf)

    def test_duplicate_node_ids(self, engine: DAGEngine):
        """Duplicate node IDs should raise."""
        wf = Workflow(
            workflow_id="wf-dup",
            name="Dup",
            nodes=[
                NodeDefinition(node_id="a", agent_id="agent-a"),
                NodeDefinition(node_id="a", agent_id="agent-b"),
            ],
            edges=[],
        )
        with pytest.raises(DAGValidationError, match="Duplicate node IDs"):
            engine.validate(wf)


class TestDAGLevels:
    """Test parallel execution level computation."""

    def test_linear_three_levels(self, engine: DAGEngine, sample_workflow: Workflow):
        """Linear A->B->C produces 3 levels with 1 node each."""
        levels = engine.compute_levels(sample_workflow)
        assert levels == [["node_a"], ["node_b"], ["node_c"]]

    def test_diamond_three_levels(self, engine: DAGEngine, diamond_workflow: Workflow):
        """Diamond A->(B,C)->D produces 3 levels: [A], [B,C], [D]."""
        levels = engine.compute_levels(diamond_workflow)
        assert levels == [["node_a"], ["node_b", "node_c"], ["node_d"]]

    def test_parallel_roots(self, engine: DAGEngine):
        """Multiple root nodes should all be in level 0."""
        wf = Workflow(
            workflow_id="wf-par",
            name="Parallel",
            nodes=[
                NodeDefinition(node_id="a", agent_id="agent-a"),
                NodeDefinition(node_id="b", agent_id="agent-b"),
                NodeDefinition(node_id="c", agent_id="agent-c"),
            ],
            edges=[],
        )
        levels = engine.compute_levels(wf)
        assert levels == [["a", "b", "c"]]

    def test_complex_dag(self, engine: DAGEngine):
        """Complex DAG with mixed dependencies."""
        #   A -> C
        #   B -> C
        #   C -> D
        #   B -> D
        wf = Workflow(
            workflow_id="wf-complex",
            name="Complex",
            nodes=[
                NodeDefinition(node_id="a", agent_id="x"),
                NodeDefinition(node_id="b", agent_id="x"),
                NodeDefinition(node_id="c", agent_id="x"),
                NodeDefinition(node_id="d", agent_id="x"),
            ],
            edges=[
                WorkflowEdge(source="a", target="c"),
                WorkflowEdge(source="b", target="c"),
                WorkflowEdge(source="c", target="d"),
                WorkflowEdge(source="b", target="d"),
            ],
        )
        levels = engine.compute_levels(wf)
        assert levels == [["a", "b"], ["c"], ["d"]]


class TestDAGHelpers:
    """Test predecessor/successor helpers."""

    def test_get_predecessors(self, engine: DAGEngine, diamond_workflow: Workflow):
        preds = engine.get_predecessors(diamond_workflow, "node_d")
        assert sorted(preds) == ["node_b", "node_c"]

    def test_get_successors(self, engine: DAGEngine, diamond_workflow: Workflow):
        succs = engine.get_successors(diamond_workflow, "node_a")
        assert sorted(succs) == ["node_b", "node_c"]

    def test_root_has_no_predecessors(self, engine: DAGEngine, sample_workflow: Workflow):
        preds = engine.get_predecessors(sample_workflow, "node_a")
        assert preds == []

    def test_leaf_has_no_successors(self, engine: DAGEngine, sample_workflow: Workflow):
        succs = engine.get_successors(sample_workflow, "node_c")
        assert succs == []
