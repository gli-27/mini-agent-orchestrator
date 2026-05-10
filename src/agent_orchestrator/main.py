"""FastAPI application entry point with lifespan management."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from agent_orchestrator.api import agents as agents_router
from agent_orchestrator.api import executions as executions_router
from agent_orchestrator.api import workflows as workflows_router
from agent_orchestrator.api import ws as ws_router
from agent_orchestrator.api.metrics_router import router as metrics_router
from agent_orchestrator.config import Settings, get_settings
from agent_orchestrator.execution.manager import ExecutionManager
from agent_orchestrator.registry.base import AgentRegistry
from agent_orchestrator.registry.memory import InMemoryAgentRegistry
from agent_orchestrator.storage.base import WorkflowStore
from agent_orchestrator.storage.memory import InMemoryWorkflowStore

logger = structlog.get_logger(__name__)


def create_registry(settings: Settings) -> AgentRegistry:
    """Factory: create the appropriate agent registry based on config."""
    if settings.registry_backend == "dynamodb":
        from agent_orchestrator.registry.dynamodb import DynamoDBAgentRegistry

        return DynamoDBAgentRegistry(
            table_name=settings.dynamodb_table_agents,
            region=settings.dynamodb_region,
        )
    return InMemoryAgentRegistry()


def create_workflow_store(settings: Settings) -> WorkflowStore:
    """Factory: create the appropriate workflow store based on config."""
    if settings.workflow_backend == "dynamodb":
        from agent_orchestrator.storage.dynamodb import DynamoDBWorkflowStore

        return DynamoDBWorkflowStore(
            table_name=settings.dynamodb_table_workflows,
            region=settings.dynamodb_region,
        )
    return InMemoryWorkflowStore()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan — initialize and tear down resources."""
    settings = get_settings()

    # Initialize registry, workflow store, and execution manager
    registry = create_registry(settings)
    workflow_store = create_workflow_store(settings)
    manager = ExecutionManager(
        registry=registry,
        max_concurrency=settings.max_concurrency,
        default_timeout=settings.default_execution_timeout,
    )

    # Wire up routers with dependencies
    agents_router.init_router(registry)
    workflows_router.init_router(workflow_store)
    executions_router.init_router(manager)
    ws_router.init_router(manager)

    # Store on app state for test access
    app.state.registry = registry
    app.state.workflow_store = workflow_store
    app.state.manager = manager

    logger.info(
        "application_started",
        app_name=settings.app_name,
        max_concurrency=settings.max_concurrency,
        registry_backend=settings.registry_backend,
        workflow_backend=settings.workflow_backend,
    )

    yield

    logger.info("application_shutdown")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Agent Orchestration Engine",
        description="Multi-agent DAG workflow execution engine",
        version="0.1.0",
        lifespan=lifespan,
        debug=settings.debug,
    )

    # Include routers
    app.include_router(agents_router.router)
    app.include_router(workflows_router.router)
    app.include_router(executions_router.router)
    app.include_router(ws_router.router)
    app.include_router(metrics_router)

    # Health check
    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "healthy", "service": settings.app_name}

    return app


app = create_app()
