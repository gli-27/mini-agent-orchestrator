# 🔀 Mini Agent Orchestration Engine

**Production-grade multi-agent workflow execution engine — DAG-based task orchestration with parallel dispatch, real-time streaming, and pluggable persistence.**

```
                    ┌─────────┐
                    │  Client │
                    └────┬────┘
                         │ REST + WebSocket + SSE
                         ▼
              ┌─────────────────────┐
              │    Orchestrator     │
              │  ┌───────┐ ┌─────┐  │
              │  │  DAG  │ │ WS  │  │
              │  │ Engine│ │Push │  │      ┌──────────────┐
              │  └───┬───┘ └─────┘  │      │  Prometheus  │
              │      │    Execution │◀────▶│  /metrics    │
              │      ▼    Manager   │      └──────────────┘
              │  ┌───────────────┐  │
              │  │ Level 0: A    │  │      ┌──────────────┐
              │  │ Level 1: B, C │──┼─────▶│  Agents      │
              │  │ Level 2: D    │  │      │  (HTTP POST) │
              │  └───────────────┘  │      └──────┬───────┘
              └─────────┬───────────┘             │
                        │                         ▼
              ┌─────────▼───────────┐   ┌─────────────────┐
              │  DynamoDB / Memory  │   │ mini-llm-serving│
              │  (pluggable store)  │   │ (LLM inference) │
              └─────────────────────┘   └─────────────────┘
```

---

## Features

- 🔀 **DAG Execution Engine** — Kahn's algorithm (BFS topological sort) produces parallel execution levels
- ⚡ **Parallel Dispatch** — `asyncio.gather` with configurable semaphore for concurrency control
- 🔗 **Declarative Data Flow** — `input_mapping` resolves `$input.field` and `node_id.output.field` between nodes
- 🔄 **Retry with Exponential Backoff** — Per-node retry with configurable attempts and timeout
- 📡 **WebSocket Status Streaming** — Real-time `node_completed` / `execution_done` events via `/ws`
- ⏱️ **Execution Timeout** — Configurable run deadline with `TIMED_OUT` status and partial result preservation
- 🛑 **Cancel/Abort API** — `POST /cancel` stops execution between levels, preserves completed work
- 🔀 **Dual-Mode Execution** — In-process (< 30s) or Step Functions (> 30s) based on DAG critical path
- 📊 **Prometheus Metrics** — Counters, histograms for executions, nodes, agents, and HTTP requests
- 🔌 **Pluggable Persistence** — Abstract interfaces with in-memory (dev) and DynamoDB (prod) implementations

---

## Quick Start

```bash
# Clone
git clone https://github.com/gli-27/mini-agent-orchestrator.git
cd mini-agent-orchestrator

# Install
pip install -e ".[dev]"

# Run
uvicorn agent_orchestrator.main:app --reload
```

Server starts at `http://localhost:8000`. API docs at `http://localhost:8000/docs`.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/agents` | Register a new agent |
| `GET` | `/v1/agents` | List all agents |
| `GET` | `/v1/agents/{agent_id}` | Get agent by ID |
| `PATCH` | `/v1/agents/{agent_id}` | Update agent fields |
| `DELETE` | `/v1/agents/{agent_id}` | Delete an agent |
| `POST` | `/v1/agents/{agent_id}/heartbeat` | Record agent heartbeat |
| `POST` | `/v1/workflows` | Create workflow (validates DAG) |
| `GET` | `/v1/workflows` | List all workflows |
| `GET` | `/v1/workflows/{workflow_id}` | Get workflow by ID |
| `DELETE` | `/v1/workflows/{workflow_id}` | Delete a workflow |
| `POST` | `/v1/executions` | Start workflow execution |
| `GET` | `/v1/executions` | List all executions |
| `GET` | `/v1/executions/{run_id}` | Get execution status |
| `POST` | `/v1/executions/{run_id}/cancel` | Cancel running execution |
| `WS` | `/v1/executions/{run_id}/ws` | WebSocket status stream |
| `GET` | `/health` | Health check |
| `GET` | `/metrics` | Prometheus metrics |

---

## Example: 3-Agent Research Pipeline

A workflow where a **Researcher** gathers information, a **Summarizer** condenses it, and a **Writer** produces the final output — with Researcher and Summarizer running in parallel at Level 1.

```python
import httpx

BASE = "http://localhost:8000"

# 1. Register agents
for agent in [
    {"agent_id": "researcher", "name": "Researcher", "endpoint": "http://agent-research:8001/invoke"},
    {"agent_id": "summarizer", "name": "Summarizer", "endpoint": "http://agent-summarize:8002/invoke"},
    {"agent_id": "writer", "name": "Writer", "endpoint": "http://agent-write:8003/invoke"},
]:
    httpx.post(f"{BASE}/v1/agents", json=agent)

# 2. Create workflow DAG
#    Level 0: researcher + summarizer (parallel)
#    Level 1: writer (depends on both)
httpx.post(f"{BASE}/v1/workflows", json={
    "workflow_id": "research-pipeline",
    "name": "Research Pipeline",
    "nodes": [
        {
            "node_id": "research",
            "agent_id": "researcher",
            "input_mapping": {"query": "$input.topic"},
        },
        {
            "node_id": "summarize",
            "agent_id": "summarizer",
            "input_mapping": {"query": "$input.topic"},
        },
        {
            "node_id": "write",
            "agent_id": "writer",
            "input_mapping": {
                "research": "research.output.findings",
                "summary": "summarize.output.summary",
            },
        },
    ],
    "edges": [
        {"source": "research", "target": "write"},
        {"source": "summarize", "target": "write"},
    ],
})

# 3. Execute with timeout
resp = httpx.post(f"{BASE}/v1/executions", json={
    "workflow_id": "research-pipeline",
    "input_data": {"topic": "transformer architectures in 2024"},
    "timeout": 60.0,
})

run = resp.json()
print(f"Status: {run['status']}")
print(f"Writer output: {run['output']['write']}")
```

**DAG visualization:**
```
research ──┐
           ├──▶ write
summarize ─┘
```

---

## Configuration

All settings are controlled via environment variables with the `ORCHESTRATOR_` prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `ORCHESTRATOR_APP_NAME` | `agent-orchestrator` | Service name |
| `ORCHESTRATOR_DEBUG` | `false` | Debug mode |
| `ORCHESTRATOR_LOG_LEVEL` | `INFO` | Log level |
| `ORCHESTRATOR_MAX_CONCURRENCY` | `10` | Max parallel node executions |
| `ORCHESTRATOR_DEFAULT_AGENT_TIMEOUT` | `30.0` | Default per-agent timeout (seconds) |
| `ORCHESTRATOR_DEFAULT_MAX_RETRIES` | `3` | Default retry attempts per node |
| `ORCHESTRATOR_DEFAULT_EXECUTION_TIMEOUT` | `300.0` | Default run deadline (seconds) |
| `ORCHESTRATOR_REGISTRY_BACKEND` | `memory` | Agent registry backend (`memory` \| `dynamodb`) |
| `ORCHESTRATOR_WORKFLOW_BACKEND` | `memory` | Workflow store backend (`memory` \| `dynamodb`) |
| `ORCHESTRATOR_DYNAMODB_TABLE_AGENTS` | `orchestrator-agents` | DynamoDB agents table name |
| `ORCHESTRATOR_DYNAMODB_TABLE_WORKFLOWS` | `orchestrator-workflows` | DynamoDB workflows table name |
| `ORCHESTRATOR_DYNAMODB_REGION` | `us-west-2` | AWS region for DynamoDB |
| `ORCHESTRATOR_HOST` | `0.0.0.0` | Server bind host |
| `ORCHESTRATOR_PORT` | `8000` | Server bind port |

---

## Observability

### Structured Logging (structlog)

JSON-formatted logs with context (run_id, node_id, agent_id, level):

```json
{"event": "execution_started", "run_id": "abc-123", "workflow_id": "research-pipeline", "timeout": 300.0}
{"event": "executing_level", "run_id": "abc-123", "level": 0, "nodes": ["research", "summarize"]}
{"event": "node_completed", "node_id": "research", "agent_id": "researcher", "duration_ms": 1250.5}
{"event": "execution_completed", "run_id": "abc-123", "status": "completed"}
```

### Prometheus Metrics (`GET /metrics`)

| Metric | Type | Labels |
|--------|------|--------|
| `orchestrator_executions_total` | Counter | workflow_id |
| `orchestrator_execution_status_total` | Counter | status |
| `orchestrator_execution_duration_seconds` | Histogram | workflow_id |
| `orchestrator_node_executions_total` | Counter | agent_id, status |
| `orchestrator_node_duration_seconds` | Histogram | agent_id |
| `orchestrator_agent_invocations_total` | Counter | agent_id |
| `orchestrator_http_requests_total` | Counter | method, path, status_code |

### Health Check (`GET /health`)

```json
{"status": "healthy", "service": "agent-orchestrator"}
```

### WebSocket (`WS /v1/executions/{run_id}/ws`)

Real-time events: `connected` → `node_completed` (per node) → `execution_done`.

---

## Companion Project

| | mini-llm-serving | mini-agent-orchestrator |
|---|---|---|
| **Role** | Single-inference optimization | Multi-inference orchestration |
| **Analogy** | The engine | The conductor |
| **Focus** | GPU memory, KV-cache, speculative decoding, batching | DAG scheduling, parallel dispatch, data flow, persistence |
| **Repo** | [gli-27/mini-llm-serving](https://github.com/gli-27/mini-llm-serving) | [gli-27/mini-agent-orchestrator](https://github.com/gli-27/mini-agent-orchestrator) |

> **Project 1** optimizes how a single LLM inference request is served (memory management, speculative decoding, request batching). **Project 2** orchestrates multiple such requests across agents in a DAG — one is the engine, the other is the conductor.

---

## Documentation

| Document | Description |
|----------|-------------|
| [`docs/architecture.md`](docs/architecture.md) | System architecture, dual-mode execution, data flow, AWS infrastructure |

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| Framework | FastAPI |
| Validation | Pydantic v2 |
| HTTP Client | httpx (async) |
| AWS SDK | boto3 + asyncio.to_thread |
| Logging | structlog (JSON) |
| Metrics | prometheus-client |
| WebSocket | websockets + Starlette |
| Testing | pytest + pytest-asyncio + respx |
| Linting | ruff |

---

## Testing

```bash
# Run all tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=agent_orchestrator --cov-report=term-missing

# Run specific test file
pytest tests/test_dag.py -v
```

**109 tests** covering: DAG engine, data resolver, registry (in-memory + DynamoDB mock), workflow store, execution manager, timeout, cancellation, WebSocket, metrics, and full API integration.

---

## License

MIT
