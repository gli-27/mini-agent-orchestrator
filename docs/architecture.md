# Architecture — Agent Orchestration Engine

## System Overview

The Agent Orchestration Engine executes multi-agent workflows defined as DAGs
(directed acyclic graphs). Each node in a DAG maps to an agent — a stateless
HTTP service that processes a single task. The engine resolves data dependencies
between nodes, dispatches parallel work, and streams progress to clients.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          CLIENTS                                        │
│   REST API (create/start)     WebSocket (progress)     SSE (final LLM)  │
└──────────┬──────────────────────┬──────────────────────────┬────────────┘
           │                      │                          │
           ▼                      ▼                          │
┌──────────────────────────────────────────────┐             │
│          API GATEWAY (HTTP + WebSocket)       │             │
└──────────┬──────────────────────┬────────────┘             │
           │                      │                          │
           ▼                      ▼                          │
┌──────────────────────────────────────────────────────────┐ │
│                 ECS FARGATE — ORCHESTRATOR                │ │
│                                                           │ │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │ │
│  │  DAG Engine  │  │  Execution   │  │  Agent         │  │ │
│  │  (Kahn's)   │──│  Manager     │──│  Registry      │  │ │
│  └─────────────┘  └──────┬───────┘  └────────────────┘  │ │
│                          │                                │ │
│              ┌───────────┴───────────┐                    │ │
│              │   MODE DECISION       │                    │ │
│              │   < 30s → in-process  │                    │ │
│              │   > 30s → step funcs  │                    │ │
│              └───────┬───────┬───────┘                    │ │
│                      │       │                            │ │
│         ┌────────────┘       └────────────┐               │ │
│         ▼                                 ▼               │ │
│  ┌──────────────┐              ┌──────────────────┐      │ │
│  │  In-Process   │              │  SF Dispatcher    │      │ │
│  │  Executor     │              │  (start + track)  │      │ │
│  └──────┬───────┘              └────────┬─────────┘      │ │
│         │                               │                 │ │
└─────────┼───────────────────────────────┼─────────────────┘ │
          │                               │                   │
          │        ┌──────────────────────┘                   │
          │        │                                          │
          │        ▼                                          │
          │  ┌───────────────────┐     ┌─────────────┐       │
          │  │  AWS STEP         │────▶│  SQS         │       │
          │  │  FUNCTIONS        │     │  (events)    │       │
          │  │                   │     └──────┬──────┘       │
          │  │  state machine    │            │              │
          │  │  retry / catch    │            │ WS Bridge    │
          │  └───────┬───────────┘            │ consumes     │
          │          │                        │ → pushes to  │
          │          │                        │   WebSocket   │
          │          ▼                        │              │
          │  ┌───────────────────┐            │              │
          │  │  LAMBDA           │            │              │
          │  │  (agent sandbox)  │            │              │
          │  └───────┬───────────┘            │              │
          │          │                        │              │
          ▼          ▼                        │              │
   ┌──────────────────────────┐               │              │
   │       AGENTS (HTTP)       │               │              │
   │  ┌───────┐  ┌───────┐   │               │              │
   │  │Agent A│  │Agent B│   │               │              │
   │  └───┬───┘  └───┬───┘   │               │              │
   │      │          │        │               │              │
   │      ▼          ▼        │               │              │
   │  ┌────────────────────┐  │               │              │
   │  │  mini-llm-serving  │  │               │              │
   │  │  (LLM inference)   │──┼───────────────┼──────────────┘
   │  └────────────────────┘  │          SSE pass-through
   └──────────────────────────┘          (final node only)
              │
              ▼
   ┌──────────────────────────┐
   │     PERSISTENCE           │
   │  ┌──────────┐ ┌───────┐  │
   │  │ DynamoDB  │ │  SQS  │  │
   │  │ (state)   │ │ (DLQ) │  │
   │  └──────────┘ └───────┘  │
   │  ┌──────────────────────┐│
   │  │ CloudWatch (metrics) ││
   │  └──────────────────────┘│
   └──────────────────────────┘
```

---

## Dual-Mode Execution Strategy

The orchestrator supports two execution modes based on estimated workflow
duration. The mode is selected automatically from the DAG's critical path
or can be forced by the caller.

### Mode 1: In-Process (short DAGs, < 30 s estimated)

Runs entirely within a single ECS orchestrator task.

```
Client                  Orchestrator (ECS)                Agents
  │                          │                               │
  │  POST /v1/executions     │                               │
  │─────────────────────────▶│                               │
  │                          │                               │
  │  WS connect              │  compute DAG levels           │
  │◀ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ │  (Kahn's algorithm)          │
  │                          │                               │
  │                          │  Level 0: asyncio.gather      │
  │                          │──────────────────────────────▶│
  │  WS: {"node":"A","ok"}   │◀─────────── response ────────│
  │◀─────────────────────────│                               │
  │                          │  Level 1: asyncio.gather      │
  │                          │──────────────────────────────▶│
  │  WS: {"node":"B","ok"}   │◀─────────── response ────────│
  │◀─────────────────────────│                               │
  │                          │                               │
  │  WS: {"status":"done"}   │                               │
  │◀─────────────────────────│                               │
```

**Characteristics:**

- State lives in Python dicts + asyncio tasks (no external store needed)
- Direct WebSocket/SSE streaming to client from the same process
- Last node can pass-through the LLM's SSE stream token-by-token to the user
- Best for: chatbot chains, simple pipelines, interactive workflows

**Benefits:**

- Sub-second startup — no Step Functions cold path
- Simple debugging — single process, standard Python tracebacks
- No external state dependencies during execution

### Mode 2: Step Functions (long DAGs, > 30 s estimated)

Orchestrator delegates execution to AWS Step Functions for durability.

```
Client              Orchestrator          Step Functions       SQS       Agents
  │                      │                      │               │           │
  │  POST /executions    │                      │               │           │
  │─────────────────────▶│                      │               │           │
  │                      │  startExecution()    │               │           │
  │                      │─────────────────────▶│               │           │
  │  202 {run_id, sf_arn}│                      │               │           │
  │◀─────────────────────│                      │               │           │
  │                      │                      │               │           │
  │  WS connect          │                      │  invoke       │           │
  │◀ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│                      │──────────────▶│ Lambda    │
  │                      │                      │               │──────────▶│
  │                      │                      │               │◀──────────│
  │                      │                      │◀──────────────│           │
  │                      │                      │               │           │
  │                      │                      │  emit event   │           │
  │                      │                      │──────────────▶│           │
  │                      │   SQS poll           │               │           │
  │                      │◀─────────────────────┼───────────────│           │
  │  WS: {step done}     │                      │               │           │
  │◀─────────────────────│                      │               │           │
  │                      │                      │  ... repeats  │           │
  │  WS: {completed}     │                      │               │           │
  │◀─────────────────────│                      │               │           │
```

**Characteristics:**

- Step Functions state machine handles retry, catch, timeout per step
- Each step completion emits an event to SQS
- Orchestrator's WebSocket bridge consumes SQS → pushes status to client
- Run state persisted in DynamoDB (survives orchestrator restarts)

**Benefits:**

- Crash recovery — SF resumes from last successful step
- Built-in retry with exponential backoff and catch blocks
- Visual debugging in AWS Step Functions Console
- Native CloudWatch metrics per step

---

## Decision Criteria

| Factor | In-Process | Step Functions |
|--------|-----------|----------------|
| Estimated total duration | < 30 s | > 30 s |
| Number of nodes | Typically ≤ 10 | Unbounded |
| State durability | None (memory) | Full (SF + DynamoDB) |
| Crash recovery | Lost | Automatic resume |
| Retry semantics | Application-level | SF native |
| Latency overhead | ~0 ms | ~200-500 ms SF start |
| Debugging | Logs + tracebacks | SF Console visual |

**How mode is selected:**

1. DAG engine computes the critical path (longest chain through the graph)
2. Sum of `timeout_seconds` along the critical path = estimated duration
3. If estimated ≤ threshold → in-process; otherwise → Step Functions
4. Threshold is configurable (default: 30 s, env: `ORCHESTRATOR_ASYNC_THRESHOLD`)
5. Caller can force async mode via `"force_async": true` in the request body

---

## Data Flow Between Nodes

### Agent-to-Agent Communication

Agents communicate **synchronously** via HTTP POST request-response. This is
intentional: the orchestrator needs the complete output from predecessor nodes
to resolve `input_mapping` for downstream nodes.

```
input_mapping:
  query: "$input.user_question"        ← workflow input
  context: "summarizer.output.summary" ← predecessor output (must be complete)
  history: "retriever.output.docs.0"   ← nested field access
```

The Data Resolver supports:
- `$input.<field>` — reference workflow input data
- `<node_id>.output.<field>` — reference a predecessor's complete output
- Nested dot notation — `node.output.nested.field` or list index `node.output.items.0`

### Client-Facing Communication

| Channel | Use Case | Protocol |
|---------|----------|----------|
| REST API | Create workflows, start executions, query status | HTTP JSON |
| WebSocket | Real-time execution progress (node started/completed/failed) | WS frames |
| SSE pass-through | Token-by-token LLM generation for the final node | text/event-stream |

### Final Node SSE Pass-Through

When the last node in a DAG invokes `mini-llm-serving`, the orchestrator can
optionally pass the LLM's SSE stream directly to the client instead of
buffering the full response:

```
User ◀──SSE──▶ Orchestrator ◀──SSE──▶ Final Agent ◀──SSE──▶ mini-llm-serving
```

This enables token-by-token streaming for user-facing generation tasks while
maintaining the standard request-response pattern for intermediate nodes.

---

## AWS Infrastructure

### Compute

| Service | Role | Scaling |
|---------|------|---------|
| **ECS Fargate** | Orchestrator service (stateless) | Horizontal auto-scaling on CPU/request count |
| **Lambda** | Individual agent sandboxed execution | Per-invocation, 0→N concurrency |

### Storage & Messaging

| Service | Role | Design |
|---------|------|--------|
| **DynamoDB** | Workflow definitions, run state, agent registry | Single-table design, GSI on workflow_id and status |
| **SQS** | Task dispatch queue | Standard queue + DLQ for failed tasks |
| **SQS (events)** | Step Functions → Orchestrator notifications | FIFO queue for ordered step events |

### Orchestration & Networking

| Service | Role |
|---------|------|
| **Step Functions** | Long-running workflow execution engine |
| **API Gateway** | WebSocket API for real-time client status |
| **ALB** | HTTP load balancer for ECS orchestrator REST API |
| **ECR** | Container registry for orchestrator + agent images |

### Observability

| Service | Role |
|---------|------|
| **CloudWatch Logs** | Structured logs (structlog JSON) |
| **CloudWatch Metrics** | Execution duration, node success/failure rates, queue depth |
| **CloudWatch Alarms** | DLQ depth > 0, error rate thresholds, Step Functions failures |

---

## Internal vs External Communication

| Path | Protocol | Why |
|------|----------|-----|
| User → Orchestrator | REST + WebSocket | Standard API + real-time status |
| Orchestrator → Agent | HTTP POST (sync) | Need complete output for DAG resolution |
| Agent → LLM Serving | HTTP POST (stream=false) | Agent needs full response to process |
| SF → Orchestrator | SQS events | Decoupled, durable notification |
| Orchestrator → User (progress) | WebSocket push | Real-time UX |
| Orchestrator → User (final LLM) | SSE pass-through (optional) | Token-by-token for last node |

---

## DynamoDB Schema (Single-Table Design)

```
PK                          SK                    Type        Attributes
──────────────────────────  ────────────────────  ──────────  ─────────────────────
AGENT#<agent_id>            META                  Agent       name, endpoint, status, ...
WF#<workflow_id>            META                  Workflow    name, nodes, edges, ...
RUN#<run_id>                META                  Run         workflow_id, status, input, ...
RUN#<run_id>                NODE#<node_id>        NodeResult  status, output, attempts, ...

GSI1:
  GSI1PK = workflow_id      GSI1SK = created_at   (list runs by workflow)
GSI2:
  GSI2PK = status           GSI2SK = created_at   (query runs by status)
```

---

## SQS Message Format

```json
{
  "message_type": "node_completed",
  "run_id": "run-abc-123",
  "workflow_id": "wf-summarize-pipeline",
  "node_id": "node_b",
  "status": "completed",
  "timestamp": "2024-01-15T10:30:00Z",
  "output_ref": "s3://bucket/runs/run-abc-123/node_b.json"
}
```

Large outputs (> 256 KB SQS limit) are stored in S3 with a reference in the
message. The orchestrator fetches the full output when resolving input mappings.

---

## Local Development

For local development without AWS dependencies:

```yaml
# docker-compose.yml
services:
  orchestrator:
    build: ./mini-agent-orchestrator
    ports: ["8000:8000"]
    environment:
      ORCHESTRATOR_EXECUTION_MODE: in_process  # force in-process mode
  
  dynamodb-local:
    image: amazon/dynamodb-local
    ports: ["8100:8000"]
  
  localstack:
    image: localstack/localstack
    ports: ["4566:4566"]
    environment:
      SERVICES: sqs,stepfunctions
```

The in-memory implementations (registry, workflow store, execution store)
used in the current codebase are designed to be swapped for DynamoDB-backed
implementations via the abstract base classes, with no changes to the
orchestration logic.
