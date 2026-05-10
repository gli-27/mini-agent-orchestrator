"""Application configuration via pydantic-settings (12-factor, env-driven)."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Service
    app_name: str = "agent-orchestrator"
    debug: bool = False
    log_level: str = "INFO"

    # Execution
    max_concurrency: int = 10
    default_agent_timeout: float = 30.0
    default_max_retries: int = 3
    default_execution_timeout: float = 300.0  # 5 minutes

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    model_config = {"env_prefix": "ORCHESTRATOR_", "extra": "ignore"}


def get_settings() -> Settings:
    """Create settings instance (cached at module level for tests to override)."""
    return Settings()
