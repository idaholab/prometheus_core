# PrometheusAgent Developer Guide

## Overview

`PrometheusAgent` is the base class for A2A-enabled specialist agents in Prometheus. You subclass it, implement `_execute(params, context, event_queue)`, and call the provided helpers to emit status updates, artifacts, and `INPUT_REQUIRED` forms. The base class handles everything else: serving the agent card, authentication, registry registration, A2A task lifecycle, and automatic final status emission.

---

## How a Request Reaches `_execute`

```
HTTP POST /  (A2A SendMessage or SendStreamingMessage)
  └─ PrometheusAgentExecutor.execute()
      ├─ emits the initial Task required by A2A v1
      ├─ emits "working" status automatically
      ├─ extracts params from message JSON or text
      ├─ injects skill_id from message.metadata.skillId
      └─ calls your _execute(params, context, event_queue)
             │
             ├─ you call helpers (status, artifacts, INPUT_REQUIRED)
             └─ you return a dict
                    └─ base class emits final "completed" status
                       with your dict as the message payload
```

The base class emits the initial `Task`, the first `working` status, and the
terminal `completed` status automatically. You never call those yourself unless
you have a specific reason to deviate.

---

## Executor Design

`PrometheusAgent` owns agent behavior. `PrometheusAgentExecutor` owns the A2A task
lifecycle: parameter extraction, initial status emission, calling `_execute`, automatic
final status emission, cancellation, and failed-status handling. The default executor is
`DelegatingPrometheusAgentExecutor`, which delegates the work step back to your agent's
`_execute()` method.

Most agents should not override `create_executor()`. Override `_execute()` for agent
logic and use helper methods for status updates, artifacts, missing input, and
conversation messages. Override `create_executor()` only when replacing the standard
executor lifecycle.

---

## The `_execute` Contract

### Signature

```python
async def _execute(
    self,
    params: Dict[str, Any],
    context: RequestContext,
    event_queue: EventQueue,
) -> Dict[str, Any]:
```

### `params`

A dict extracted from the incoming A2A message. Populated in priority order:

1. JSON body of the message text (if valid JSON)
2. `{"message": text}` fallback for plain-text messages
3. `skill_id` key injected from `message.metadata.skillId`

```python
params = {
    "skill_id": "analyze_material",    # always present if sent in metadata
    "material_id": "SS316",            # from caller's JSON params
    "temperature_c": 750.0,
}
```

### What to return

Return a plain dict. The base class serializes it as the text payload of the final `completed` status event. The orchestrator reads this dict as the agent's result.

```python
return {
    "message": "Thermal analysis complete for SS316 at 750 °C.",
    "agent": "Thermal Agent",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    # Any other keys your callers need:
    "max_temperature_c": 812.4,
    "status_flag": "acceptable",
}
```

**Rules:**

- Always return a dict — never `None`, a string, or a list
- If you called `send_input_required()`, return `{}` (empty dict) — the task is suspended, not complete
- If you called `send_json_artifact()` or `send_artifact_reference()`, the artifact is already emitted; the return dict is for the conversational summary, not the data
- Do not put large data blobs in the return dict — use artifacts for that
- The `"message"` key is shown as the agent's conversational reply in the frontend

### `context` fields used most often

```python
context.context_id   # str — stable across all turns of a conversation; use as state key
context.task_id      # str — changes per invocation; do not use as state key
```

### Raising exceptions

Unhandled exceptions from `_execute` are caught by the base class, which emits a `failed` status. Raise `ValueError` for user-visible errors; use `logger.exception` for unexpected errors you want logged.

---

## Agent Card and Skill Routing

### `agent_card.json` structure

```json
{
  "name": "My Agent",
  "description": "One-sentence description used for orchestrator routing.",
  "version": "1.0.0",
  "capabilities": {
    "streaming": true,
    "pushNotifications": false
  },
  "skills": [
    {
      "id": "analyze_material",
      "name": "Analyze Material",
      "description": "Runs a thermal/corrosion analysis for a given material ID. Requests missing operating conditions interactively.",
      "usage_notes": "Use when the user asks for material analysis, property lookup, or compatibility checks.",
      "tags": ["materials", "thermal", "analysis", "corrosion"],
      "inputSchema": {
        "type": "object",
        "properties": {
          "material_id": {
            "type": "string",
            "description": "Canonical material identifier, e.g. SS316, Inconel625"
          },
          "temperature_c": {
            "type": "number",
            "description": "Operating temperature in °C"
          }
        },
        "required": ["material_id"]
      }
    }
  ]
}
```

Do not hard-code a card URL. `load_agent_card()` adds the A2A v1
`supportedInterfaces` JSON-RPC entry from `EXTERNAL_AGENT_URL` or the runtime
container host and `AGENT_PORT`.

**Important agent card conventions:**

- `description` and `usage_notes` at the skill level are the primary routing signals for the orchestrator LLM — write them precisely and distinctively
- `tags` improve keyword-based routing — include domain terms, modalities, and specific noun phrases
- `inputSchema` tells the orchestrator which parameters it can extract from the user's query and pass directly. Parameters listed in `required` will be extracted or prompted for by the orchestrator.
- Mark parameters the agent must collect interactively with `"x-input-source": "agent"` — the orchestrator will not prompt for these:

```json
"initial_query": {
  "type": "string",
  "description": "The user's initial request text",
  "x-input-source": "agent"
}
```

- The `url` field is overridden at startup from `EXTERNAL_AGENT_URL` (if set) or auto-derived from the container hostname and `AGENT_PORT` — set a placeholder in the file.
- Workflow templates in `workflows/*.yaml`, `workflows/*.yml`, or `workflows/*.json` next to `agent_card.json` are inserted into the raw card served at `/api/agent-card` and registered with LiteLLM. Set `AGENT_WORKFLOWS` to use a different directory.

### Routing multiple skills with `skill_id`

When an agent exposes multiple skills, route by `params["skill_id"]`:

```python
async def _execute(self, params, context, event_queue):
    skill_id = params.get("skill_id")

    dispatch = {
        "analyze_material": self._handle_analyze_material,
        "list_materials":   self._handle_list_materials,
        "audit":            self._handle_audit,
    }

    handler = dispatch.get(skill_id)
    if handler is None:
        raise ValueError(
            f"Unknown skill: '{skill_id}'. Valid skills: {', '.join(dispatch)}"
        )

    return await handler(params, context, event_queue)
```

`skill_id` is injected automatically from `message.metadata.skillId` — you do not need to parse it from message text.

---

## Prompt Templates

Put large static LLM prompts in `prompts/` next to the agent entrypoint instead
of embedding long strings in `agent.py`. Load them with the shared helper:

```python
from prometheus_api import load_prompt

SYSTEM_PROMPT = load_prompt("system_prompt.txt")

async def _handle_analysis(self, params, context, event_queue):
    prompt = SYSTEM_PROMPT.format(input_data=params["input_data"])
    async with self.llm_client(context) as llm:
        response = await llm.medium(prompt)
    return {"message": response.text, "agent": self.agent_name}
```

`load_prompt()` reads UTF-8 text and strips leading/trailing whitespace by
default. It resolves relative prompt names inside the prompt directory and
rejects absolute paths or `../` escapes. Pass `prompts_dir=...` for custom
layouts or unit tests.

---

## Status Updates

Use `send_status_update()` to emit transient progress messages visible in the frontend's "thinking" indicator. These are not durable chat messages.

```python
await self.send_status_update(
    context=context,
    event_queue=event_queue,
    message="Loading material database…",
)

# ... do work ...

await self.send_status_update(
    context=context,
    event_queue=event_queue,
    message="Running corrosion model…",
)
```

**Rules:**

- Emit as many intermediate updates as needed — they are cheap
- Do not manually emit the final `completed` or `failed` status; the base class does that from your return value
- Use `TaskState.TASK_STATE_*` enum names when selecting a non-default state
- A2A v1 derives finality from `TaskState`; it has no `TaskStatusUpdateEvent.final` field

---

## Don't block the event loop

Your agent runs on a **single asyncio event loop**. A synchronous call that does
not `await` — a blocking SDK (`anthropic.Anthropic().messages.create(...)`), a
`requests` call, a legacy library, a CPU loop, `time.sleep` — holds that loop
until it returns. While it is blocked, nothing else runs: not the keepalive
**heartbeat** the base executor emits during `_execute`, not the A2A stream that
flushes status updates to the caller, not other in-flight requests. If the gap
exceeds the upstream socket-read timeout (LiteLLM/aiohttp, ~30s), the streaming
connection is torn down **even though your agent is still working**.

The fix is never "raise the timeout" — it is to keep the loop free.

**Offload blocking calls** with `asyncio.to_thread` (or use an async client):

```python
# WRONG — blocks the loop for the whole call; heartbeat and streaming stall
result = blocking_library.run(payload)

# CORRECT — runs off-loop; the loop stays free to flush heartbeats/status
result = await asyncio.to_thread(blocking_library.run, payload)
```

**Reporting progress from a long blocking task (offload-and-observe).** The worker
thread must not touch `event_queue` (it wraps a loop-bound `asyncio.Queue` that is
not thread-safe). Instead the thread writes progress into a thread-safe
`queue.Queue`, and the `_execute` coroutine polls it, emits status on the loop,
and `await`s a short sleep between polls (which keeps the loop alive):

```python
import asyncio, queue, threading

class ProgressReporter:           # thread writes, loop reads
    def __init__(self):
        self._q: "queue.Queue[str]" = queue.Queue()
    def report(self, message):    # worker thread
        self._q.put(str(message))
    def drain(self):              # event loop
        out = []
        while True:
            try: out.append(self._q.get_nowait())
            except queue.Empty: return out

async def _execute(self, params, context, event_queue):
    progress = ProgressReporter()
    cancel = threading.Event()    # threads can't be killed; cancel cooperatively
    work = asyncio.create_task(asyncio.to_thread(self._run, params, progress, cancel))
    try:
        while not work.done():
            for msg in progress.drain():
                await self.send_status_update(context=context, event_queue=event_queue, message=msg)
            await asyncio.sleep(1.0)          # yields → heartbeat + SSE keep flowing
        for msg in progress.drain():
            await self.send_status_update(context=context, event_queue=event_queue, message=msg)
        return await work                     # recover result / re-raise exceptions
    except asyncio.CancelledError:
        cancel.set()                          # caller went away; ask the worker to stop
        raise
```

Caveats: a client disconnect cancels the *coroutine*, not the *thread* (use the
cancel `Event`); `to_thread` only parallelizes work that releases the GIL — for
sustained CPU use `ProcessPoolExecutor` (progress must then cross processes); and a
truly opaque blocking call that can't report mid-flight relies on the heartbeat
alone. The base executor's heartbeat interval is configurable via
`PROMETHEUS_HEARTBEAT_INTERVAL` (positive seconds; default 15).

---

## Artifacts

### Inline JSON artifact

Use for structured data that the frontend should render and downstream agents might reuse.

```python
artifact_id = await self.send_json_artifact(
    context=context,
    event_queue=event_queue,
    payload={
        "material_id": "SS316",
        "max_temperature_c": 812.4,
        "corrosion_rate_mm_yr": 0.012,
        "status": "acceptable",
    },
    name="material_analysis",
    description="Thermal and corrosion analysis for SS316 at 750 °C.",
    json_type="prometheus.material_analysis.v1",
    catalog_artifact=True,
)
```

- `json_type` is a dot-separated semantic type string used for frontend visualization routing and agent capability matching. Use a stable, versioned name like `prometheus.<domain>.<kind>.v1`.
- `catalog_artifact=True` registers the artifact in the per-conversation artifact catalog so later agent calls can resolve it by name or ID.
- Returns the `artifact_id` string — include it in your return dict if callers need to reference it.

### File artifact

Use for generated files (PDF reports, CSV exports, images).

```python
artifact = await self.send_artifact_reference(
    context=context,
    event_queue=event_queue,
    name="corrosion_report.pdf",
    description="Full corrosion analysis report for SS316",
    uri=f"file:///tmp/{report_filename}",
    mime_type="application/pdf",
    tags=["report", "corrosion", "SS316"],
)
# artifact.artifact_id is available if needed
```

- Always set `mime_type` — it drives frontend rendering (PDF viewer, download button, etc.)
- `uri` supports `file://`, `http://`, and bare absolute paths
- Registers automatically in the artifact catalog

### Text artifact (streaming)

Use for incremental text output like logs or streaming LLM responses.

```python
# First chunk
artifact_id = await self.send_text_artifact(
    context=context,
    event_queue=event_queue,
    name="analysis.log",
    text="Step 1: loading data\n",
    last_chunk=False,
)

# Subsequent chunks
await self.send_text_artifact(
    context=context,
    event_queue=event_queue,
    artifact_id=artifact_id,   # must pass the same id to append
    append=True,
    text="Step 2: running model\n",
    last_chunk=False,
)

# Final chunk
await self.send_text_artifact(
    context=context,
    event_queue=event_queue,
    artifact_id=artifact_id,
    append=True,
    text="Done.\n",
    last_chunk=True,
)
```

### Durable conversation message

Use when you want a message to appear in chat history (not just as a transient spinner update) but it is not a reusable data artifact.

```python
await self.send_conversation_message(
    context=context,
    event_queue=event_queue,
    message="Processing your report — this may take a moment.",
)
```

### Retrieve any artifact as a local file

Use when a downstream skill receives an `artifact_id` and needs to read the
artifact contents. The helper returns a readable local `Path` for URI-backed,
inline JSON, and inline text artifacts:

```python
source_path = await self.get_artifact_file_path(
    params["artifact_id"],
    context=context,
    artifacts=params.get("artifacts"),  # optional orchestrator-provided catalog
)

contents = source_path.read_bytes()
```

Behavior:

- `deeplynx://`, `http://`, `https://`, and other fsspec-supported URI schemes are downloaded into a deterministic artifact cache.
- Inline JSON artifacts are written as formatted UTF-8 `.json` files in the cache.
- Inline text artifacts are written as UTF-8 `.txt` files in the cache.
- `file://` artifacts are validated in place and are only allowed under configured local roots.

Configuration:

- `PROMETHEUS_ARTIFACT_CACHE_DIR` sets the cache root. Default: `/tmp/prometheus-artifact-cache`.
- `PROMETHEUS_ARTIFACT_FILE_ALLOWED_ROOTS` sets which local directories `file://` artifacts may read, separated by the platform path separator (`:` on Linux/macOS).

---

## `INPUT_REQUIRED` — Requesting User Input

### Basic pattern

When a required value is missing, emit `INPUT_REQUIRED` and return `{}`. The platform suspends the task and asks the user. When the user responds, your `_execute` is called again with **all** the original params plus the answers merged into `params`. You don't need saved state to remember the first call's arguments.

```python
from prometheus_api.agent import MissingInput

class MyAgent(PrometheusAgent):
    async def _execute(self, params, context, event_queue):
        if params.get("temperature_c") is None:
            await self.send_input_required(
                context=context,
                event_queue=event_queue,
                missing_inputs=[
                    MissingInput(
                        name="temperature_c",
                        description="Operating temperature in degrees Celsius.",
                        user_prompt="What operating temperature should I use (°C)?",
                        type="number",
                        required=True,
                    )
                ],
                hint="Please provide the operating temperature to continue.",
            )
            return {}   # ← MUST return {} here — task is suspended

        temp = float(params["temperature_c"])
        return {"message": f"Analysis complete at {temp} °C.", "temperature_c": temp}
```

To know *who* supplied a value, call `self.get_input_sources(context)`. It maps each parameter name to `"model"` (the orchestrator's tool call), `"user"` (a form answer) or `"context"` (filled in from the conversation), and returns `{}` when the caller sent no sources:

```python
if self.get_input_sources(context).get("weekday") == "user":
    note = "You chose this day."
```

Never ask for credentials (API keys, tokens) with `INPUT_REQUIRED`: they would travel as parameters.

### `MissingInput` fields

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | `str` | yes | Field identifier — the answer arrives as `params[name]` on resume |
| `description` | `str` | yes | Explanation for the orchestrator LLM; shown as help text in the form |
| `user_prompt` | `str` | yes | The question label shown to the user in the form |
| `type` | `str` | yes | Input type — controls form widget (see table below) |
| `options` | `List[str]` | no | Enum values — renders as a dropdown select |
| `required` | `bool` | no | Default `True`. Set `False` for optional fields — form can be submitted without filling them |
| `resolvable_from_context` | `bool` | no | Default `False`. If `True`, the orchestrator will try to auto-resolve from session context without asking the user |

### Type → form widget mapping

| `type` value | Form widget | Notes |
|---|---|---|
| `"string"` | Text input | Free text |
| `"string"` + `options=[...]` | Dropdown select | Preferred over `"enum"`. `options` may be computed per request, so they can list values the agent card can't know in advance |
| `"number"` or `"integer"` | Number input | Validates numeric input |
| `"boolean"` | Checkbox | `True`/`False`; never required even if `required=True` |

### Sending multiple fields at once

Send all required fields in a **single** `send_input_required()` call. The frontend renders each `MissingInput` as a separate form field. Never call `send_input_required()` multiple times in one `_execute` invocation.

```python
await self.send_input_required(
    context=context,
    event_queue=event_queue,
    missing_inputs=[
        MissingInput(
            name="material_id",
            description="Canonical material identifier.",
            user_prompt="Material ID",
            type="string",
            required=True,
        ),
        MissingInput(
            name="reactor_type",
            description="Reactor type this material will be used in.",
            user_prompt="Reactor type",
            type="string",
            options=["PWR", "BWR", "SFR", "HTGR"],
            required=True,
        ),
        MissingInput(
            name="design_temperature_c",
            description="Peak design temperature in °C. Leave blank to use code minimum.",
            user_prompt="Design temperature (°C)",
            type="number",
            required=False,   # optional — submit button activates without it
        ),
        MissingInput(
            name="safety_related",
            description="Whether the component is safety-related.",
            user_prompt="Safety-related component?",
            type="boolean",
        ),
    ],
    hint="Please complete the component profile.",
)
return {}
```

### Multi-round INPUT_REQUIRED (phase state machine)

For workflows that need several distinct forms (e.g. classification fields then sizing parameters), use a `phase` key in context state:

```python
async def _execute(self, params, context, event_queue):
    context_id = str(context.context_id)
    state = self.load_context_state(context_id)
    phase = state.get("phase", "start")

    if phase == "start":
        return await self._phase_start(params, context, event_queue, context_id)
    if phase == "awaiting_classification":
        return await self._phase_classification(params, context, event_queue, context_id, state)
    if phase == "awaiting_sizing":
        return await self._phase_sizing(params, context, event_queue, context_id, state)
    raise ValueError(f"Unknown phase: {phase!r}")

async def _phase_start(self, params, context, event_queue, context_id):
    self.save_context_state(context_id, {
        "phase": "awaiting_classification",
        "initial_params": params,
    })
    await self.send_input_required(
        context=context, event_queue=event_queue,
        missing_inputs=[
            MissingInput(name="code_class", user_prompt="ASME code class",
                         description="...", type="string",
                         options=["Class_1", "Class_2", "Class_3", "NonCode"]),
            MissingInput(name="safety_category", user_prompt="Safety category",
                         description="...", type="string",
                         options=["safety_related", "non_safety"]),
        ],
        hint="Please provide the classification fields.",
    )
    return {}

async def _phase_classification(self, params, context, event_queue, context_id, state):
    # This round's answers arrive in params; earlier rounds' answers live in state.
    profile = {**state.get("profile", {}), **{k: params[k] for k in ("code_class", "safety_category") if k in params}}

    self.save_context_state(context_id, {
        "phase": "awaiting_sizing",
        "profile": profile,
        "initial_params": state.get("initial_params"),
    })
    await self.send_input_required(
        context=context, event_queue=event_queue,
        missing_inputs=[
            MissingInput(name="design_pressure_mpa", user_prompt="Design pressure (MPa)",
                         description="...", type="number", required=False),
            MissingInput(name="design_temp_c", user_prompt="Design temperature (°C)",
                         description="...", type="number", required=False),
        ],
        hint="Optional sizing parameters — leave blank to skip.",
    )
    return {}

async def _phase_sizing(self, params, context, event_queue, context_id, state):
    profile = {**state.get("profile", {})}
    for k in ("design_pressure_mpa", "design_temp_c"):
        if params.get(k) is not None:
            profile[k] = params[k]

    self.save_context_state(context_id, {})   # clear state when done

    result = run_analysis(profile)   # your business logic
    await self.send_json_artifact(
        context=context, event_queue=event_queue,
        payload=result, name="requirements", catalog_artifact=True,
    )
    return {"message": "Analysis complete.", "agent": self.agent_name}
```

### Common pitfalls

**1. Forgetting `return {}` after `send_input_required`**

`send_input_required` emits a *final* A2A status with `state=input_required`. The task is now suspended. If you continue executing and return a normal dict afterwards, the base class will try to emit a second final status — causing a protocol error or overwriting the `INPUT_REQUIRED`.

```python
# WRONG
await self.send_input_required(...)
result = do_expensive_work()   # This runs unnecessarily
return {"result": result}      # Overwrites INPUT_REQUIRED with "completed"

# CORRECT
await self.send_input_required(...)
return {}
```

**2. Saving state after sending `INPUT_REQUIRED`**

Save state *before* calling `send_input_required`, not after. Once you call it, the current invocation should immediately `return {}`.

```python
# WRONG — state is saved after the final event is emitted
await self.send_input_required(...)
self.save_context_state(context_id, state)   # may not persist reliably
return {}

# CORRECT
self.save_context_state(context_id, state)
await self.send_input_required(...)
return {}
```

**3. Using `task_id` as the state key**

`task_id` changes on every invocation (each turn is a new task). `context_id` is stable for the entire conversation. Always use `context_id` as the state key.

```python
# WRONG — state is lost on resume
self.save_context_state(context.task_id, state)

# CORRECT
self.save_context_state(str(context.context_id), state)
```

**4. Copying params into context state "for the resume"**

Not needed: on resume the platform re-sends every original argument with the answers merged in. Save state only for what `params` can't carry, such as the phase of a multi-round form or answers from earlier rounds.

```python
# WRONG — redundant; params already has material_id on resume
self.save_context_state(context_id, {"resolved": {"material_id": params["material_id"]}})

# CORRECT
material_id = params.get("material_id")
```

**5. Assuming `skill_id` persists across turns**

`skill_id` is injected from message metadata on each call. If your agent dispatches multiple skills and needs to resume across an `INPUT_REQUIRED` boundary, save the `skill_id` in context state on the first turn and restore it on resume.

```python
# First turn
skill_id = params.get("skill_id")
self.save_context_state(context_id, {"skill_id": skill_id, "phase": "awaiting_input"})

# Resume turn
state = self.load_context_state(context_id)
skill_id = params.get("skill_id") or state.get("skill_id")
```

**6. Calling `send_input_required` more than once per invocation**

Only one `INPUT_REQUIRED` event can be pending at a time. Bundle all missing fields into a single call (the form renders them as separate widgets). If you need multiple distinct forms, use the phase state machine pattern above.

**7. Sending status updates after `send_input_required`**

Any event emitted after a final-status event is dropped by the A2A transport. Do all status updates before calling `send_input_required()`.

---

## Running Synchronous Code

`_execute` is `async` but most data-processing libraries are synchronous. Run blocking code in a thread pool to avoid blocking the event loop:

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

_EXECUTOR = ThreadPoolExecutor(max_workers=4)

class MyAgent(PrometheusAgent):
    async def _execute(self, params, context, event_queue):
        await self.send_status_update(context, event_queue, message="Running model…")

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            _EXECUTOR, self._run_sync_model, params
        )

        await self.send_json_artifact(
            context=context, event_queue=event_queue,
            payload=result, name="model_output", catalog_artifact=True,
        )
        return {"message": "Model complete.", "agent": self.agent_name}

    def _run_sync_model(self, params):
        # Synchronous heavy computation here
        return {"output": 42}
```

---

## Lifecycle Hooks

`agent.run()` calls `build_app()` and starts uvicorn. Use
`build_app(register_on_startup=False)` when tests or custom hosts need a
Starlette app without background registry registration. The app uses the A2A
v1 route factories and defaults to a 10 MiB request-body limit.

### Custom HTTP endpoints

Use `add_http_endpoint(...)` or `add_static_endpoint(...)` when an agent owns
small HTTP endpoints in addition to A2A execution. Routes registered this way
are installed before bearer-token middleware, so they use the same
`Authorization: Bearer <AGENT_SECRET>` policy as normal agent traffic. The base
class also advertises them in the raw agent card under the Prometheus
`endpoints` extension.

Register endpoints in `__init__` after `super().__init__(...)`:

```python
from pathlib import Path

from prometheus_api.agent import PrometheusAgent
from starlette.responses import JSONResponse


class ViewerAgent(PrometheusAgent):
    def __init__(self):
        super().__init__(agent_name="Viewer Agent")

        self.add_http_endpoint(
            "/api/preview/{artifact_id}",
            self.preview_artifact,
            methods=["GET"],
            endpoint_id="artifact_preview",
            purpose="artifact",
            description="Return preview metadata for one artifact.",
            content_types=["application/json"],
        )

        self.add_static_endpoint(
            "/viewer",
            Path("viewer-assets"),
            endpoint_id="viewer_assets",
            purpose="viewer_plugin",
            description="Serve viewer plugin JavaScript and CSS.",
            content_types=["text/javascript", "text/css"],
        )

    async def preview_artifact(self, request):
        artifact_id = request.path_params["artifact_id"]
        return JSONResponse({"artifact_id": artifact_id, "ok": True})
```

Relative static directories are resolved next to `agent_card.json`, matching
workflow directory resolution. If the agent runs in Docker, copy the static
asset directory into the image.

Endpoint metadata shape in `/api/agent-card`:

```json
{
  "endpoints": [
    {
      "id": "viewer_assets",
      "path": "/viewer",
      "methods": ["GET", "HEAD"],
      "purpose": "viewer_plugin",
      "auth_required": true,
      "description": "Serve viewer plugin JavaScript and CSS.",
      "content_types": ["text/javascript", "text/css"]
    }
  ]
}
```

Custom endpoints are intended for provider-to-platform traffic. Browser-facing
features should still go through the client-agent or another deliberate
platform boundary rather than giving the frontend arbitrary direct access to
specialist agents.

### `configure_app(app)`

Override to add advanced custom Starlette routes or middleware when the helper
methods are not enough:

```python
def configure_app(self, app):
    from starlette.routing import Route
    from starlette.responses import JSONResponse

    async def custom_endpoint(request):
        return JSONResponse({"status": "ok"})

    app.routes.append(Route("/api/custom", custom_endpoint))
```

Routes added through `configure_app(app)` also run behind the same auth
middleware, but they are not automatically advertised in the agent card. Prefer
`add_http_endpoint(...)` or `add_static_endpoint(...)` when the platform should
discover the endpoint.

### `lifespan(app)`

Override for startup/shutdown work (loading models, opening connections):

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(self, app):
    self._model = load_expensive_model()
    yield
    self._model = None
```

---

## Environment Variables

For migrating existing agents from direct provider SDKs or hard-coded LLM
utilities, see [LLM Client Migration Guide](LLM_CLIENT_MIGRATION.md). For base-agent
behavior changes, see [Prometheus Agent Migration Guide](AGENT_MIGRATIONS.md).

| Variable | Default | Description |
|---|---|---|
| `AGENT_PORT` | `8000` | Port uvicorn binds to (internal) |
| `EXTERNAL_AGENT_URL` | auto | Full URL advertised to the registry. Auto-derived from the container hostname and `AGENT_PORT` when not set. Set explicitly for port-mapped or cross-host deployments (e.g. `http://my-host:9002`, where `9002` is the host-side port and `8000` is `AGENT_PORT` inside the container). |
| `AGENT_WORKFLOWS` | `workflows` | Directory of JSON/YAML workflow templates inserted into the raw agent card. Relative paths are resolved next to `agent_card.json`. |
| `AGENT_SECRET` | — | Bearer token for inbound authentication |
| `AGENT_SECRET_REQUIRED` | `true` | Reject requests without a valid `Authorization: Bearer` header. If true and `AGENT_SECRET` is unset, app startup fails fast. |
| `REGISTRY_URL` | `http://litellm:4000` | LiteLLM gateway URL for registry registration |
| `REGISTRY_MAX_RETRIES` | `10` | Registration retries after the first attempt, used for both explicit `REGISTRY_URL` and the built-in fallback URL. |
| `REGISTRY_CHECK_INTERVAL_SECONDS` | `5` | After startup, how often the agent checks the registry still lists it and re-registers if not (also after startup retries ran out). `0` disables; minimum `0.1`. Skipped for an agent that overrides `register_with_registry_async`. |
| `LITELLM_MASTER_KEY` | — | LiteLLM admin key |
| `LLM_API_KEY` | — | If the agent calls Claude directly |
| `REDIS_URL` | `redis://localhost:6379` | Redis for artifact catalog and context state |
| `REDIS_PASSWORD` | — | Redis auth password |
| `AGENT_CONTEXT_TTL_SECONDS` | `86400` | TTL for per-context persisted state (24 h) |

---

## Built-in HTTP Endpoints

`agent.run()` exposes these endpoints automatically:

Registry registration starts as a background async task during app lifespan startup, after
subclass `lifespan(app)` startup completes. Registration retries do not block `uvicorn.run()`
from starting the HTTP server.

| Method | Path | Description |
|---|---|---|
| `POST` | `/` | A2A v1 `SendMessage` and `SendStreamingMessage` |
| `GET` | `/.well-known/agent-card.json` | Canonical A2A v1 agent card (public, unauthenticated) |
| `GET` | `/.well-known/agent.json` | Canonical v1 card at the legacy discovery alias |
| `GET` | `/healthz` | Health check — `{"ok": true}` (unauthenticated) |
| `GET` | `/api/agent-card` | Raw agent card JSON |
| `POST` | `/api/chat` | Debug endpoint: same execution path as A2A but simpler request/response |
| `GET` | `/api/artifacts/{conversation_id}` | List artifact catalog for a conversation |

---

## Project Structure

```text
my-agent/
├── agent.py              # PrometheusAgent subclass + if __name__ == "__main__": agent.run()
├── agent_card.json       # Skill definitions, capabilities, tags
├── prompts/              # Optional prompt templates loaded with load_prompt()
├── workflows/            # Optional workflow templates inserted into /api/agent-card
├── Dockerfile
├── docker-compose.yml
└── .env                  # AGENT_PORT, REGISTRY_URL, AGENT_SECRET, etc.
```

Minimal `agent.py`:

```python
from prometheus_api.agent import EventQueue, MissingInput, PrometheusAgent, RequestContext


class MyAgent(PrometheusAgent):
    async def _execute(
        self,
        params: dict,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> dict:
        skill_id = params.get("skill_id")

        if skill_id == "do_analysis":
            return await self._handle_analysis(params, context, event_queue)

        raise ValueError(f"Unknown skill: {skill_id!r}")

    async def _handle_analysis(self, params, context, event_queue):
        material_id = params.get("material_id")
        if not material_id:
            await self.send_input_required(
                context=context,
                event_queue=event_queue,
                missing_inputs=[
                    MissingInput(
                        name="material_id",
                        description="Canonical material ID to analyze.",
                        user_prompt="Which material should I analyze?",
                        type="string",
                        required=True,
                    )
                ],
                hint="Please specify the material.",
            )
            return {}

        await self.send_status_update(context, event_queue, message=f"Analyzing {material_id}…")

        result = {"material_id": material_id, "score": 0.95}
        await self.send_json_artifact(
            context=context, event_queue=event_queue,
            payload=result, name="analysis_result",
            json_type="prometheus.my_agent.analysis.v1",
            catalog_artifact=True,
        )

        return {
            "message": f"Analysis complete for {material_id}.",
            "agent": self.agent_name,
        }


if __name__ == "__main__":
    agent = MyAgent(agent_name="My Agent")
    agent.run()
```

---

## API Reference

### `MissingInput`

```python
@dataclass
class MissingInput:
    name: str                             # Key of the answer in params on resume
    description: str                      # Orchestrator context + form help text
    user_prompt: str                      # Label shown to user in the form
    type: str                             # "string" | "number" | "integer" | "boolean"
    options: Optional[List[str]] = None   # Renders as dropdown; works with any type
    resolvable_from_context: bool = False # Orchestrator tries to auto-resolve
    required: bool = True                 # False = optional form field
```

### `build_app(register_on_startup=True, max_content_length=10 * 1024 * 1024)`

Build and return the Starlette app without starting uvicorn. Use
`register_on_startup=False` in tests or custom hosts that should not start background
registry registration.
Set `max_content_length=None` only when the host intentionally permits A2A
request bodies larger than the default 10 MiB.

### `create_executor()`

Return the executor for this agent. The default returns
`DelegatingPrometheusAgentExecutor`, which preserves the standard lifecycle and calls the
agent's `_execute()` method for the work step. Override only for custom executor
lifecycles.

### `run(host="0.0.0.0", port=None)`

Build the app, start background registry registration during lifespan startup, and run uvicorn.

### `send_input_required(context, event_queue, *, missing_inputs, hint, metadata=None)`

Emit a final `INPUT_REQUIRED` status. Must be followed by `return {}`.

### `send_status_update(context, event_queue, state=TaskState.TASK_STATE_WORKING, final=False, message=None, metadata=None)`

Emit a transient progress update.

The `final` argument remains for source compatibility with existing agents.
A2A v1 does not serialize it; the selected `TaskState` determines whether the
status is terminal or interrupted.

### `send_json_artifact(context, event_queue, payload, name="result", description=None, json_type=None, catalog_artifact=False, artifact_id=None, append=False, last_chunk=None, metadata=None) → str`

Emit a structured data artifact. Returns `artifact_id`.

### `send_text_artifact(context, event_queue, text, name="result", artifact_id=None, append=False, last_chunk=None, metadata=None) → str`

Emit or append to a text artifact. Returns `artifact_id`.

### `send_artifact_reference(context, event_queue, *, name, description, uri, mime_type=None, size_bytes=None, artifact_id=None, tags=None, metadata=None) → ArtifactReference`

Register and emit a URI-backed file artifact.

### `send_conversation_message(context, event_queue, message, metadata=None) → str`

Emit a durable chat-visible message.

### `load_context_state(context_id) → Dict`

Load persisted per-context state. Returns `{}` if nothing saved.

### `save_context_state(context_id, state)`

Persist agent-local state (Redis with in-memory fallback, TTL 24 h by default).

### `get_input_sources(context) → Dict[str, str]`

Who supplied each parameter, from the `inputSources` message metadata: `"model"`,
`"user"` (a form answer) or `"context"` (filled from the conversation). The values
themselves are in `params`. Returns `{}` when the caller sent no sources.

### `list_artifact_references(conversation_id, limit=None) → List[ArtifactReference]`

List registered artifacts for a conversation, newest first.

### `resolve_artifact_reference(conversation_id, artifact_id) → Optional[ArtifactReference]`

Resolve one artifact by ID.

### `resolve_artifact_by_name(conversation_id, name_or_alias) → Optional[ArtifactReference]`

Resolve one artifact by name (case-insensitive).

### `get_artifact_file_path(artifact_id, *, context=None, conversation_id=None, artifacts=None, cache_dir=None, allowed_file_roots=None, force_download=False) → Path`

Resolve a catalog artifact to a readable local file path. URI-backed artifacts are
downloaded through fsspec, inline JSON/text artifacts are written to the cache,
and `file://` artifacts are validated against allowed local roots.

---

## Multi-User Identity and Credentials

From `_execute`, the verified user identity and per-user credentials are available
without any additional setup beyond setting `USER_IDENTITY_PUBLIC_KEY` (this agent
verifies) and, on the platform backend only, `USER_IDENTITY_PRIVATE_KEY` (it mints).
Generate a keypair with `prometheus-identity-keygen` (ships in this package):

```python
async def _execute(self, params, context, event_queue):
    user_id = params["user_id"]                  # verified; never spoofable
    cred = await self.get_credential("deeplynx") # JIT per-user credential
    config = ConnectionConfig.from_credential(cred)
    ...
```

For credential-touching agents that hold secrets across multiple `await` calls,
opt into process isolation:

```python
class MyAgent(PrometheusAgent):
    requires_user_isolation = True
    ...
```

See [MULTI_USER.md](./MULTI_USER.md) for the full reference: identity JWT flow,
credential broker backends (env/Vault/bespoke), per-user worker pool, and
conversation ownership.

---

## See Also

- [`examples/agent_patterns.py`](../../examples/agent_patterns.py) — full reference agent demonstrating all patterns
- [`docs/ENV_SETUP.md`](../ENV_SETUP.md) — environment variable details
- [`docs/agent/QUICK_START.md`](./QUICK_START.md) — condensed getting-started version
- [`docs/agent/MULTI_USER.md`](./MULTI_USER.md) — multi-user identity, credentials, and isolation
- [`docs/agent/IDENTITY_KEY_MANAGEMENT.md`](./IDENTITY_KEY_MANAGEMENT.md) — RS256 key generation, key distribution per service, third-party agent integration
