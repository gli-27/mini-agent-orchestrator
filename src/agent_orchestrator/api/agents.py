"""Agent management API router."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status

from agent_orchestrator.api.schemas import RegisterAgentRequest, UpdateAgentRequest
from agent_orchestrator.models.agent import Agent
from agent_orchestrator.registry.base import AgentRegistry

router = APIRouter(prefix="/v1/agents", tags=["agents"])

# Registry will be injected via app state
_registry: AgentRegistry | None = None


def init_router(registry: AgentRegistry) -> None:
    """Initialize the router with dependencies."""
    global _registry  # noqa: PLW0603
    _registry = registry


def _get_registry() -> AgentRegistry:
    """Get the agent registry or raise if not initialized."""
    if _registry is None:
        raise RuntimeError("Agent registry not initialized")
    return _registry


@router.post("", status_code=status.HTTP_201_CREATED)
async def register_agent(request: RegisterAgentRequest) -> Agent:
    """Register a new agent."""
    registry = _get_registry()
    agent = Agent(
        agent_id=request.agent_id,
        name=request.name,
        endpoint=request.endpoint,
        description=request.description,
        capabilities=request.capabilities,
        timeout_seconds=request.timeout_seconds,
        max_retries=request.max_retries,
    )
    try:
        return await registry.register(agent)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get("")
async def list_agents() -> list[Agent]:
    """List all registered agents."""
    registry = _get_registry()
    return await registry.list_agents()


@router.get("/{agent_id}")
async def get_agent(agent_id: str) -> Agent:
    """Get agent by ID."""
    registry = _get_registry()
    agent = await registry.get(agent_id)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )
    return agent


@router.patch("/{agent_id}")
async def update_agent(agent_id: str, request: UpdateAgentRequest) -> Agent:
    """Update agent fields."""
    registry = _get_registry()
    update_data = request.model_dump(exclude_none=True)
    try:
        return await registry.update(agent_id, **update_data)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: str) -> None:
    """Delete an agent."""
    registry = _get_registry()
    try:
        await registry.delete(agent_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post("/{agent_id}/heartbeat")
async def agent_heartbeat(agent_id: str) -> Agent:
    """Record a heartbeat for an agent."""
    registry = _get_registry()
    try:
        return await registry.heartbeat(agent_id, datetime.now(UTC))
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
