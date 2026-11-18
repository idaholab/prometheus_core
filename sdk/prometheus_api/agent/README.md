# Agent Utilities

Utilities for building A2A Protocol v1 multi-agent systems with `PrometheusAgent`.

## Core Contract

```python
from prometheus_api.agent import EventQueue, PrometheusAgent, RequestContext


class MyAgent(PrometheusAgent):
    async def _execute(self, params, context: RequestContext, event_queue: EventQueue):
        return {
            "conversation_id": context.context_id,
            "status": "completed",
            "message": "Request handled.",
        }


if __name__ == "__main__":
    agent = MyAgent(agent_name="My Agent")
    agent.run()
```

The base class handles:

- agent-card loading
- auth middleware
- registry registration
- A2A request handling
- final status emission from your returned dict

Use helper methods when needed:

- `send_status_update(...)` for transient progress
- `send_artifact_reference(...)` for URI-backed file artifacts
- `send_json_artifact(..., catalog_artifact=True)` for reusable inline JSON artifacts
- `send_conversation_message(...)` for durable chat-visible messages
- `send_input_required(...)` for missing-input requests
- `load_context_state(...)` / `save_context_state(...)` for resumable agent-local state keyed by `contextId`

### Request-scoped alternative

Instead of overriding `_execute`, subclass `PrometheusRequestAgent` and put the
work in a `PrometheusRequest`. A new request object is built for every A2A
request with the params, context and event queue, so the helpers on `self` need
no `context` or `event_queue`, and per-request values can safely live on `self`:

```python
from prometheus_api.agent import PrometheusRequest, PrometheusRequestAgent


class MyRequest(PrometheusRequest["MyAgent"]):
    async def execute(self):
        await self.send_status_update(message="Working")
        source = self.resolve_artifact_reference(self.params["artifact_id"])
        return {"status": "completed", "source": source.name if source else None}


class MyAgent(PrometheusRequestAgent):
    request_class = MyRequest  # long-lived resources stay on the agent
```

`self.agent` is the long-lived agent. Request helpers keep the agent helper's
name and arguments minus `context`, `event_queue` and `conversation_id`. After
`execute()` returns, the request is closed and any further helper call raises
`RequestClosedError`. Nothing on the request survives an `INPUT_REQUIRED` pause.

To enable streaming (`SendStreamingMessage`), set
`"capabilities": {"streaming": true}` in `agent_card.json`.

The base class constructs the card's v1 JSON-RPC `supportedInterfaces` entry
from `EXTERNAL_AGENT_URL` (or container hostname plus `AGENT_PORT`) and emits
the initial `Task` required by v1 before any status or artifact updates.

While `_execute()` runs, the base executor emits periodic non-final keepalive
("heartbeat") status events so streaming connections survive long gaps between
substantive updates. Heartbeats carry no message and are tagged
`metadata.heartbeat=true`, so consumers ignore them for display. Tune via
`PROMETHEUS_HEARTBEAT_INTERVAL` (positive seconds; default `15`).

## Documentation

- **[PrometheusAgent Guide](../../docs/agent/GUIDE.md)**: full API reference, patterns, and examples
- **[Quick Start](../../docs/agent/QUICK_START.md)**: minimal setup plus common agent actions
- **[Prometheus Agent Migration Guide](../../docs/agent/AGENT_MIGRATIONS.md)**: running migration notes for base-agent behavior changes
- **[LLM Client Migration Guide](../../docs/agent/LLM_CLIENT_MIGRATION.md)**: replace vendor-specific LLM utilities with `llm_client`
- **[Environment Setup](../../docs/ENV_SETUP.md)**: environment variables
- **[Reference Example](../../examples/agent_patterns.py)**: one example agent showing status, artifacts, input requests, and stateful resume

## Components

- `PrometheusAgent`: base class for A2A-enabled specialists
- `PrometheusAgentExecutor` / `DelegatingPrometheusAgentExecutor`: standard A2A task lifecycle and delegation to agent `_execute`
- `PrometheusRequestAgent` / `PrometheusRequest`: one request object per A2A request, with request-bound helpers
- `MissingInput`: canonical descriptor for `INPUT_REQUIRED`
- `ArtifactReference` / `ArtifactRegistry`: conversation artifact helpers
- `AgentRegistryClient`: LiteLLM registry registration client with exponential retries
- `ContextStateStore`: per-agent state persistence keyed by `contextId`
- `BearerTokenMiddleware`: shared-secret auth middleware

## Installation

```bash
pip install "git+https://github.com/idaholab/prometheus_core.git#subdirectory=sdk"
```

The agent stack is part of the base package.
