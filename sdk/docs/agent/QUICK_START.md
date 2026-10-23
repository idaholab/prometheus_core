# PrometheusAgent Quick Start

Subclass `PrometheusAgent`, implement `_execute`, return a dict. The base class handles everything else.

## Install

```bash
pip install "git+https://github.com/idaholab/prometheus_core.git#subdirectory=sdk"
```

The agent stack is included in the base package.

Migrating an existing agent from direct provider SDK calls? See
[LLM Client Migration Guide](LLM_CLIENT_MIGRATION.md).

## Minimal agent

```python
from prometheus_api.agent import EventQueue, PrometheusAgent, RequestContext


class MyAgent(PrometheusAgent):
    async def _execute(self, params, context: RequestContext, event_queue: EventQueue) -> dict:
        return {
            "message": f"Received skill={params.get('skill_id')!r}.",
            "agent": self.agent_name,
        }


if __name__ == "__main__":
    MyAgent(agent_name="My Agent").run()
```

## Minimal `agent_card.json`

```json
{
  "name": "My Agent",
  "description": "One-sentence description for orchestrator routing.",
  "version": "1.0.0",
  "capabilities": { "streaming": true, "pushNotifications": false },
  "skills": [
    {
      "id": "do_analysis",
      "name": "Do Analysis",
      "description": "Runs an analysis. Requests any missing parameters interactively.",
      "usage_notes": "Use when the user asks for analysis, lookup, or evaluation.",
      "tags": ["analysis"],
      "inputSchema": {
        "type": "object",
        "properties": {
          "material_id": { "type": "string", "description": "Material identifier" }
        },
        "required": ["material_id"]
      }
    }
  ]
}
```

The base class supplies the A2A v1 `supportedInterfaces` JSON-RPC entry from
`EXTERNAL_AGENT_URL` or the runtime host and port.

## Status updates

```python
await self.send_status_update(context, event_queue, message="Loading data…")
await self.send_status_update(context, event_queue, message="Running model…")
# base class emits final "completed" status from your return dict — don't emit it manually
```

## Prompt templates

Put large static LLM prompts in `prompts/` next to `agent.py`, then load them
with the shared helper:

```python
from prometheus_api import load_prompt

SYSTEM_PROMPT = load_prompt("system_prompt.txt")
prompt = SYSTEM_PROMPT.format(input_data=params["input_data"])
```

`load_prompt()` reads UTF-8 text from the entrypoint-adjacent `prompts/`
directory by default. Pass `prompts_dir=...` only for custom layouts or tests.

## JSON artifact

```python
await self.send_json_artifact(
    context=context, event_queue=event_queue,
    payload={"score": 0.95, "status": "acceptable"},
    name="result",
    description="Analysis result",
    json_type="prometheus.my_agent.result.v1",
    catalog_artifact=True,    # registers for downstream reuse
)
return {"message": "Analysis complete.", "agent": self.agent_name}
```

## File artifact

```python
artifact = await self.send_artifact_reference(
    context=context, event_queue=event_queue,
    name="report.pdf",
    description="Generated report",
    uri="file:///tmp/report.pdf",
    mime_type="application/pdf",
)
return {"message": "Report ready.", "agent": self.agent_name}
```

## DeepLynx artifact

Upload a local file to DeepLynx, attach metadata, and emit a `deeplynx://` URI reference.

```python
from pathlib import Path
from prometheus_api.storage_client.connection import ConnectionConfig

config = ConnectionConfig.from_env()   # reads DEEPLYNX_KEY / DEEPLYNX_SECRET / etc.

artifact = await self.send_deeplynx_artifact(
    context=context, event_queue=event_queue,
    file_path=Path("/tmp/results.csv"),
    name="results.csv",
    description="Simulation output",
    storage_config=config,
    mime_type="text/csv",
    json_type="prometheus.my_agent.results.v1",   # optional semantic tag
    tags=["simulation", "validated"],
    metadata={"run_id": "abc123"},
)
# artifact.uri  → "deeplynx://organizations/1/projects/2/items/42"
# artifact.metadata["deeplynx_item_id"]  → 42
# artifact.metadata["deeplynx_file_id"]  → 99
return {"message": "Results uploaded.", "agent": self.agent_name}
```

The DeepLynx item's `properties` store `mime_type`, `json_type`, `file_id`, and any
extra `metadata` keys, so the artifact is queryable in DeepLynx independently of
the Prometheus catalog.

## Use an existing artifact as a local file

When a skill receives an `artifact_id`, use `get_artifact_file_path()` to turn it
into a readable local file path. The helper resolves the conversation catalog,
downloads URI-backed artifacts through `fsspec` into a cache, and materializes
inline JSON/text artifacts as UTF-8 files in the same cache.

```python
source_path = await self.get_artifact_file_path(
    params["artifact_id"],
    context=context,
    artifacts=params.get("artifacts"),  # optional catalog from an orchestrator
)

with open(source_path, "rb") as source:
    data = source.read()
```

For `file://` artifacts, the helper validates the existing path instead of
copying it. Set `PROMETHEUS_ARTIFACT_FILE_ALLOWED_ROOTS` to the directories an
agent is allowed to read, separated by the platform path separator.

## `INPUT_REQUIRED` — requesting user input

Call `send_input_required`, then **always** `return {}`. On resume, `params` holds every
original argument plus the user's answers, so no saved state is needed.

```python
from prometheus_api.agent import MissingInput


async def _execute(self, params, context, event_queue):
    if params.get("temperature_c") is None:
        await self.send_input_required(
            context=context, event_queue=event_queue,
            missing_inputs=[
                MissingInput(
                    name="temperature_c",
                    description="Operating temperature in °C.",
                    user_prompt="What operating temperature (°C)?",
                    type="number",
                    required=True,
                )
            ],
            hint="I need an operating temperature to continue.",
        )
        return {}   # ← required — task is suspended

    return {"message": f"Running at {params['temperature_c']} °C.", "agent": self.agent_name}
```

Key rules:
- Answers arrive in `params` on resume; `self.get_input_sources(context)` says whether each value came from the `"model"`, the `"user"` or the `"context"`
- If you do keep state (e.g. a multi-round form's phase), key it by `context.context_id` (not `task_id`, which changes each turn)
- Bundle all missing fields into **one** `send_input_required` call — the form renders them as separate widgets
- `type="boolean"` renders as a checkbox; `options=[...]` renders as a dropdown (options may be computed per request)

## Multiple skills

```python
async def _execute(self, params, context, event_queue):
    skill_id = params.get("skill_id")
    dispatch = {
        "analyze": self._handle_analyze,
        "list":    self._handle_list,
    }
    handler = dispatch.get(skill_id)
    if handler is None:
        raise ValueError(f"Unknown skill: {skill_id!r}")
    return await handler(params, context, event_queue)
```

## Sync code in async context

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

_POOL = ThreadPoolExecutor(max_workers=4)

async def _execute(self, params, context, event_queue):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_POOL, self._sync_computation, params)
    return {"result": result}

def _sync_computation(self, params):
    return heavy_library_call(params)
```

## `.env`

```env
AGENT_PORT=8000
# EXTERNAL_AGENT_URL=http://my-host:9002  # set only for port-mapped / cross-host deployments
AGENT_SECRET=my-secret
REGISTRY_URL=http://litellm:4000
LITELLM_MASTER_KEY=sk-...
```

## Next steps

- [PrometheusAgent Guide](./GUIDE.md) — full reference with pitfalls, multi-round forms, lifecycle hooks
- [`examples/agent_patterns.py`](../../examples/agent_patterns.py) — runnable reference agent
- [Environment Setup](../ENV_SETUP.md)
