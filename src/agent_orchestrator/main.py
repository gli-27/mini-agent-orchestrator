"""FastAPI application entry point with lifespan management."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from agent_orchestrator.api import agents as agents_router
from agent_orchestrator.api import executions as executions_router
from agent_orchestrator.api import workflows as workflows_router
from agent_orchestrator.config import get_settings
from agent_orchestrator.execution.manager import ExecutionManager
from agent_orchestrator.registry.memory import InMemoryAgentRegistry

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan — initialize and tear down resources."""
    settings = get_settings()

    # Initialize registry and execution manager
    registry = InMemoryAgentRegistry()
    manager = ExecutionManager(
        registry=registry,
        max_concurrency=settings.max_concurrency,
    )

    # Wire up routers with dependencies
    agents_router.init_router(registry)
    executions_router.init_router(manager)

    # Store on app state for test access
    app.state.registry = registry
    app.state.manager = manager

    logger.info(
        "application_started",
        app_name=settings.app_name,
        max_concurrency=settings.max_concurrency,
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

    # Health check
    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "healthy", "service": settings.app_name}

    return app


app = create_app()
