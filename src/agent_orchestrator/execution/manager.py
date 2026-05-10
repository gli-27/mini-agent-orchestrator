"""Execution manager — orchestrates workflow runs using DAG levels.

Dispatches nodes in parallel within each level using asyncio.gather
with a semaphore for concurrency control.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import httpx
import structlog

from agent_orchestrator.dag import DAGEngine
from agent_orchestrator.execution.data_resolver import DataResolver, DataResolverError
from agent_orchestrator.execution.runner import NodeRunner
from agent_orchestrator.models.execution import ExecutionRun, NodeResult, RunStatus
from agent_orchestrator.models.workflow import Workflow
from agent_orchestrator.registry.base import AgentRegistry

logger = structlog.get_logger(__name__)


class ExecutionManager:
    """Manages workflow execution lifecycle.

    Coordinates:
    - DAG level computation
    - Parallel node dispatch with semaphore
    - Data flow between nodes via DataResolver
    - Run state tracking
    """

    def __init__(
        self,
        registry: AgentRegistry,
        dag_engine: DAGEngine | None = None,
        max_concurrency: int = 10,
        client: httpx.AsyncClient | None = None,
        default_timeout: float = 300.0,
    ) -> None:
        self._registry = registry
        self._dag_engine = dag_engine or DAGEngine()
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._data_resolver = DataResolver()
        self._node_runner = NodeRunner(client=client)
        self._runs: dict[str, ExecutionRun] = {}
        self._default_timeout = default_timeout

    @property
    def runs(self) -> dict[str, ExecutionRun]:
        """Access stored execution runs."""
        return self._runs

    async def start_run(
        self,
        workflow: Workflow,
        input_data: dict | None = None,
        timeout: float | None = None,
    ) -> ExecutionRun:
        """Start a new execution run for a workflow.

        Args:
            workflow: The workflow to execute.
            input_data: Input data for the workflow.
            timeout: Execution timeout in seconds. Uses default_timeout if None.

        Returns:
            The completed ExecutionRun with all node results.
        """
        execution_timeout = timeout if timeout is not None else self._default_timeout

        run = ExecutionRun(
            run_id=str(uuid.uuid4()),
            workflow_id=workflow.workflow_id,
            status=RunStatus.RUNNING,
            input_data=input_data or {},
            started_at=datetime.now(UTC),
        )
        self._runs[run.run_id] = run

        logger.info(
            "execution_started",
            run_id=run.run_id,
            workflow_id=workflow.workflow_id,
            timeout=execution_timeout,
        )

        try:
            await asyncio.wait_for(
                self._run_levels(workflow, run),
                timeout=execution_timeout,
            )
        except TimeoutError:
            logger.error(
                "execution_timeout",
                run_id=run.run_id,
                timeout=execution_timeout,
            )
            run = run.model_copy(
                update={
                    "status": RunStatus.TIMED_OUT,
                    "completed_at": datetime.now(UTC),
                    "output": self._aggregate_output(run),
                }
            )
            self._runs[run.run_id] = run
            return run
        except Exception as exc:
            logger.error(
                "execution_error",
                run_id=run.run_id,
                error=str(exc),
            )
            run = run.model_copy(
                update={
                    "status": RunStatus.FAILED,
                    "completed_at": datetime.now(UTC),
                }
            )
            self._runs[run.run_id] = run
            return run

        # Compute final status
        final_status = run.compute_status()
        run = run.model_copy(
            update={
                "status": final_status,
                "completed_at": datetime.now(UTC),
                "output": self._aggregate_output(run),
            }
        )
        self._runs[run.run_id] = run

        logger.info(
            "execution_completed",
            run_id=run.run_id,
            status=final_status.value,
        )

        return run

    async def _run_levels(self, workflow: Workflow, run: ExecutionRun) -> None:
        """Execute all DAG levels sequentially, stopping if an entire level fails."""
        levels = self._dag_engine.compute_levels(workflow)

        for level_idx, level_nodes in enumerate(levels):
            logger.info(
                "executing_level",
                run_id=run.run_id,
                level=level_idx,
                nodes=level_nodes,
            )

            results = await self._execute_level(
                workflow=workflow,
                node_ids=level_nodes,
                run=run,
            )

            # Store results
            for result in results:
                run.node_results[result.node_id] = result

            # Check if we should stop (all nodes in level failed)
            level_statuses = {r.status for r in results}
            if level_statuses == {RunStatus.FAILED}:
                logger.warning(
                    "level_all_failed_stopping",
                    run_id=run.run_id,
                    level=level_idx,
                )
                break

    async def get_run(self, run_id: str) -> ExecutionRun | None:
        """Get an execution run by ID."""
        return self._runs.get(run_id)

    async def _execute_level(
        self,
        workflow: Workflow,
        node_ids: list[str],
        run: ExecutionRun,
    ) -> list[NodeResult]:
        """Execute all nodes in a level concurrently with semaphore."""
        tasks = [
            self._execute_node_with_semaphore(workflow, node_id, run)
            for node_id in node_ids
        ]
        return await asyncio.gather(*tasks)

    async def _execute_node_with_semaphore(
        self,
        workflow: Workflow,
        node_id: str,
        run: ExecutionRun,
    ) -> NodeResult:
        """Execute a single node, respecting the concurrency semaphore."""
        async with self._semaphore:
            return await self._execute_node(workflow, node_id, run)

    async def _execute_node(
        self,
        workflow: Workflow,
        node_id: str,
        run: ExecutionRun,
    ) -> NodeResult:
        """Execute a single node: resolve inputs, lookup agent, invoke."""
        node = workflow.get_node(node_id)
        if node is None:
            return NodeResult(
                node_id=node_id,
                status=RunStatus.FAILED,
                error=f"Node '{node_id}' not found in workflow",
            )

        # Look up agent
        agent = await self._registry.get(node.agent_id)
        if agent is None:
            return NodeResult(
                node_id=node_id,
                status=RunStatus.FAILED,
                error=f"Agent '{node.agent_id}' not found in registry",
            )

        if not agent.is_healthy():
            return NodeResult(
                node_id=node_id,
                status=RunStatus.FAILED,
                error=f"Agent '{node.agent_id}' is not healthy (status={agent.status.value})",
            )

        # Resolve input mappings
        try:
            resolved_input = self._data_resolver.resolve(
                node=node,
                workflow_input=run.input_data,
                node_results=run.node_results,
            )
        except DataResolverError as exc:
            return NodeResult(
                node_id=node_id,
                status=RunStatus.FAILED,
                error=str(exc),
            )

        # Run the node
        return await self._node_runner.run(node, agent, resolved_input)

    def _aggregate_output(self, run: ExecutionRun) -> dict:
        """Aggregate final output from all completed node results."""
        output: dict = {}
        for node_id, result in run.node_results.items():
            if result.status == RunStatus.COMPLETED and result.output:
                output[node_id] = result.output
        return output
