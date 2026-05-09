"""Node runner — invokes an agent via HTTP with retry and exponential backoff."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import httpx
import structlog

from agent_orchestrator.models.agent import Agent
from agent_orchestrator.models.execution import NodeResult, RunStatus
from agent_orchestrator.models.workflow import NodeDefinition

logger = structlog.get_logger(__name__)


class NodeRunner:
    """Executes a single node by calling its agent's HTTP endpoint.

    Features:
    - Exponential backoff with jitter on retries
    - Configurable timeout per node (override or agent default)
    - Structured logging of attempts and outcomes
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def run(
        self,
        node: NodeDefinition,
        agent: Agent,
        resolved_input: dict,
    ) -> NodeResult:
        """Execute a node by invoking its agent.

        Args:
            node: Node definition (may override timeout/retries).
            agent: The agent to invoke.
            resolved_input: Pre-resolved input data.

        Returns:
            NodeResult with status, output, error, and timing info.
        """
        timeout = node.timeout_override or agent.timeout_seconds
        max_retries = node.retry_override if node.retry_override is not None else agent.max_retries

        started_at = datetime.now(UTC)
        start_time = time.monotonic()
        last_error: str | None = None
        attempts = 0

        for attempt in range(max_retries + 1):
            attempts = attempt + 1
            try:
                output = await self._invoke_agent(agent, resolved_input, timeout)
                elapsed_ms = (time.monotonic() - start_time) * 1000

                logger.info(
                    "node_completed",
                    node_id=node.node_id,
                    agent_id=agent.agent_id,
                    attempts=attempts,
                    duration_ms=round(elapsed_ms, 2),
                )

                return NodeResult(
                    node_id=node.node_id,
                    status=RunStatus.COMPLETED,
                    output=output,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    attempts=attempts,
                    duration_ms=round(elapsed_ms, 2),
                )

            except (httpx.HTTPStatusError, httpx.RequestError, TimeoutError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "node_attempt_failed",
                    node_id=node.node_id,
                    agent_id=agent.agent_id,
                    attempt=attempts,
                    max_retries=max_retries,
                    error=last_error,
                )

                if attempt < max_retries:
                    backoff = min(2**attempt * 0.5, 30.0)
                    await asyncio.sleep(backoff)

        # All retries exhausted
        elapsed_ms = (time.monotonic() - start_time) * 1000
        logger.error(
            "node_failed",
            node_id=node.node_id,
            agent_id=agent.agent_id,
            attempts=attempts,
            error=last_error,
        )

        return NodeResult(
            node_id=node.node_id,
            status=RunStatus.FAILED,
            error=last_error,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            attempts=attempts,
            duration_ms=round(elapsed_ms, 2),
        )

    async def _invoke_agent(
        self, agent: Agent, payload: dict, timeout: float
    ) -> dict:
        """Make HTTP POST to agent endpoint.

        Returns:
            Parsed JSON response as dict.

        Raises:
            httpx.HTTPStatusError: On 4xx/5xx responses.
            httpx.RequestError: On connection/network errors.
            TimeoutError: On request timeout.
        """
        client = self._client or httpx.AsyncClient()
        should_close = self._client is None

        try:
            response = await client.post(
                agent.endpoint,
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json()
        finally:
            if should_close:
                await client.aclose()
