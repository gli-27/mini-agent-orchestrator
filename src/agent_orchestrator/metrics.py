"""Prometheus metrics for the agent orchestration engine."""

from __future__ import annotations

from prometheus_client import Counter, Histogram, Info

# Service info
SERVICE_INFO = Info("orchestrator", "Agent Orchestration Engine service info")
SERVICE_INFO.info({"version": "0.1.0", "service": "agent-orchestrator"})

# Execution metrics
EXECUTION_TOTAL = Counter(
    "orchestrator_executions_total",
    "Total number of workflow executions started",
    ["workflow_id"],
)

EXECUTION_STATUS = Counter(
    "orchestrator_execution_status_total",
    "Execution outcomes by status",
    ["status"],
)

EXECUTION_DURATION = Histogram(
    "orchestrator_execution_duration_seconds",
    "Workflow execution duration in seconds",
    ["workflow_id"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
)

# Node metrics
NODE_EXECUTION_TOTAL = Counter(
    "orchestrator_node_executions_total",
    "Total number of node executions",
    ["agent_id", "status"],
)

NODE_DURATION = Histogram(
    "orchestrator_node_duration_seconds",
    "Individual node execution duration in seconds",
    ["agent_id"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

# Agent metrics
AGENT_INVOCATION_TOTAL = Counter(
    "orchestrator_agent_invocations_total",
    "Total agent HTTP invocations",
    ["agent_id"],
)

AGENT_INVOCATION_ERRORS = Counter(
    "orchestrator_agent_invocation_errors_total",
    "Agent invocation errors (retries + final failures)",
    ["agent_id", "error_type"],
)

# API metrics
REQUEST_TOTAL = Counter(
    "orchestrator_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
)

REQUEST_DURATION = Histogram(
    "orchestrator_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)
