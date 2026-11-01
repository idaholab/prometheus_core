# Writing a Prometheus Agent

This tutorial walks you through building a specialist agent for the Prometheus multi-agent platform from scratch. You will create a stand-alone Python project, containerize it with Docker, and connect it to a running Prometheus platform instance.

**Assumed knowledge:** Basic Python (classes, `async`/`await`). No Docker experience required — Docker concepts are introduced as needed.

---

## What you are building

A Prometheus agent is a small HTTP service that speaks the [A2A protocol](https://google.github.io/A2A/). The platform's orchestrator discovers it, routes user requests to it, and displays its responses in the Prometheus web UI.

```
User → Prometheus UI → Orchestrator (client-agent)
                            │
                            │  A2A JSON-RPC over HTTP
                            ▼
                       Your Agent  ───→ LLM provider (LLM_CONFIG_PROFILE)
                            │
                            └── Redis (state, artifact catalog)
```

Every agent starts from a small project template:

| File | Purpose |
|------|---------|
| `agent_card.json` | Declares the agent's name, description, and skills. The orchestrator reads this at startup. |
| `agent.py` | Your Python code. Subclass `PrometheusAgent`, implement `_execute`. |
| `prompts/` | Optional prompt template files loaded by your agent code. |
| `workflows/` | Optional agent-owned workflow definitions loaded into the served agent card. |
| `pyproject.toml` | Python packaging metadata and your extra dependencies. |
| `Dockerfile` | Turns your code into a Docker image. |
| `docker-compose.yml` | Runs the image as part of (or alongside) the Prometheus platform. |

---

## Prerequisites

- **Python 3.12+** — `python3 --version`
- **uv** — the package manager used across the platform. Install with `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Docker Desktop** (or Podman) — only needed for Steps 6–9
- **Git** — for cloning and version control

---

## Step 1 — Create your project

Clone the template repository and run the interactive scaffolder. It copies the
canonical template (in `agent_template/`) into a new directory, replacing the
`TEMPLATE_*` placeholders with your agent's name, slug, class, and primary skill:

```bash
git clone git@github.com:idaholab/prometheus_core.git
cd prometheus_core/agent-template
python setup_agent.py                        # prompts for everything
python setup_agent.py "Plant Analysis" ../plant-agent   # name and output dir given
```

Answer the prompts (agent name, description, slug, class name, skill, output
directory; a name or directory given on the command line is not asked for). When it
finishes, your new project lives in the output directory you chose:

```
my-agent/
├── agent.py
├── agent_card.json
├── prompts/
├── workflows/
├── pyproject.toml
├── Dockerfile
├── .dockerignore
├── docker-compose.yml
└── .env.example
```

> **Prefer to do it by hand?** Copy `agent_template/` into a new directory and
> replace the `TEMPLATE_*` placeholders (`TEMPLATE_NAME`, `TEMPLATE_DESCRIPTION`,
> `TEMPLATE_CLASS`, `TEMPLATE_SLUG`, `TEMPLATE_SKILL_ID`, `TEMPLATE_SKILL_NAME`,
> `TEMPLATE_SKILL_DESCRIPTION`) yourself. The walkthrough below uses concrete
> example values (`My Agent`, `my_skill`, `input_data`) to show what to put.

Move into your new agent directory and create your `.env` (it holds your secrets
and is never committed):

```bash
cd my-agent
cp .env.example .env
```

Then set up a local Python environment for development:

```bash
uv sync                            # creates .venv with your deps + dev tools (pytest, ruff)
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Install prometheus_api PINNED to the platform's base image hash, so what
# you develop against locally matches what runs in the container. Find the
# hash in your .env (PROMETHEUS_API_BASE_IMAGE_HASH) or the platform Makefile,
# and re-run this when the platform bumps it:
uv pip install "git+https://github.com/idaholab/prometheus_core.git@3407a82#subdirectory=sdk"
```

> **Why pin?** `prometheus_api` evolves without backward-compatibility
> guarantees. An unpinned install tracks `main` and can silently break your
> agent; the pin keeps local dev and the Docker base image on the same
> version. When you bump the hash, read the
> [Agent Migration Guide](https://github.com/idaholab/prometheus_core/blob/devel/sdk/docs/agent/AGENT_MIGRATIONS.md).

---

## Step 2 — The agent card (`agent_card.json`)

The agent card is a JSON file that tells the orchestrator everything it needs to know to route requests to your agent. Open `agent_card.json`:

```json
{
  "name": "My Agent",
  "description": "One sentence description used by the orchestrator to route requests.",
  "version": "1.0.0",
  "capabilities": {
    "streaming": false,
    "pushNotifications": false
  },
  "skills": [ ... ]
}
```

### Top-level fields

| Field | What to put here |
|-------|-----------------|
| `name` | Human-readable name shown in the UI. |
| `description` | **One sentence** used by the LLM orchestrator when deciding which agent to call. Write it as a capability statement: *"Analyzes corrosion rates for stainless steel alloys given temperature and pH."* |
| `version` | Semantic version of your agent. Increment when the skill interface changes. |
| `capabilities.streaming` | Set `true` only if your agent emits streaming partial responses (rare; not needed for most agents). |

There is no `url` field: the base class sets the registered URL at startup —
external Docker mode sets `EXTERNAL_AGENT_URL`; otherwise the agent registers
`http://{container hostname}:{AGENT_PORT}`. Inside Docker Compose the hostname is
the service name, which resolves on `agent-network`, so the default internal mode
does not need any URL configuration.

### Skills

Each skill is one thing your agent can do. Most agents have one skill; some have a few. The orchestrator passes the `skillId` to your `_execute` call as `params["skill_id"]` so you can dispatch to the right handler.

```json
{
  "id": "my_skill",
  "name": "My Skill",
  "description": "What this skill does. One or two sentences.",
  "usage_notes": "When the user asks about X. Use this instead of Y when Z.",
  "requires_approval": false,
  "expected_duration_seconds": 10,
  "output_format": "JSON with keys: status, result",
  "inputSchema": { ... }
}
```

| Field | Notes |
|-------|-------|
| `id` | Snake-case identifier used in code, e.g. `"analyze_corrosion"`. |
| `description` | Read by the LLM to decide when to invoke this skill. Be specific. |
| `usage_notes` | Clarifies edge cases: when to prefer this skill over a similar one, what context is needed. |
| `requires_approval` | If `true`, the UI pauses and asks the user to confirm before the skill runs. |
| `expected_duration_seconds` | Informational; used by the UI to set timeout expectations. |
| `output_format` | Prose description of the return value shape. Used by the orchestrator when constructing multi-step plans. |

### `inputSchema`

This is a [JSON Schema](https://json-schema.org/) object describing the parameters your skill accepts. The orchestrator uses it to know what it needs to collect before calling your agent, and to validate inputs.

```json
"inputSchema": {
  "type": "object",
  "properties": {
    "material_id": {
      "type": "string",
      "description": "Material identifier, e.g. 'SS316L'."
    },
    "temperature_c": {
      "type": "number",
      "description": "Operating temperature in °C."
    },
    "coolant": {
      "type": "string",
      "description": "Coolant type.",
      "enum": ["water", "helium", "sodium"]
    }
  },
  "required": ["material_id"]
}
```

Tips:
- Mark only truly required fields as `required`. Optional fields let the orchestrator call your agent with partial information.
- Use `"description"` on every property — these descriptions are read by the LLM when constructing calls.
- Use `"enum"` for fixed-value fields to prevent the orchestrator from guessing.
- Add `"x_input_source": "runtime"` to a property whose value will be provided by a previous agent's output rather than by the user directly.

**Fill in the specifics.** If you used `setup_agent.py`, the name, skill id, and skill name are already set — you still need to refine the `description`, `usage_notes`, `output_format`, and the `inputSchema` properties for your agent. If you copied the template by hand, replace the `TEMPLATE_*` placeholders too.

---

## Step 3 — The Python agent (`agent.py`)

Open `agent.py`. The structure is:

```python
from prometheus_api.agent import PrometheusAgent
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue

class MyAgent(PrometheusAgent):
    async def _execute(self, params, context, event_queue) -> dict:
        ...
        return {"status": "success", "result": ...}

if __name__ == "__main__":
    MyAgent(agent_name="My Agent").run()
```

That is all the code you need to write. The base class (`PrometheusAgent`) handles the HTTP server, authentication, agent-card serving, and registry registration.

### The `_execute` contract

`_execute` is called once per incoming request. It receives:

| Argument | Type | What it contains |
|----------|------|-----------------|
| `params` | `dict` | Parameters from the caller's JSON payload, plus `skill_id` from message metadata. |
| `context` | `RequestContext` | The A2A request context. Use `context.context_id` as a stable key for per-conversation state. |
| `event_queue` | `EventQueue` | Pass to helper methods to emit progress updates and artifacts. |

It must return a `dict`. The base class automatically wraps the returned dict as the final `completed` task status. The orchestrator receives this dict as the agent's result.

### Reading parameters

```python
async def _execute(self, params, context, event_queue):
    material_id = params.get("material_id")
    temperature  = params.get("temperature_c", 25.0)   # with default
    skill_id     = params.get("skill_id")               # which skill was called

    if not material_id:
        return {"status": "error", "error": "material_id is required"}
```

### Sending status updates

The base class sends the initial `"working"` status automatically. Call `send_status_update` for intermediate messages that appear in the UI while your agent is running:

```python
await self.send_status_update(
    context=context,
    event_queue=event_queue,
    message="Fetching material properties…",
)
# ... do some work ...
await self.send_status_update(
    context=context,
    event_queue=event_queue,
    message="Running analysis…",
)
```

### Returning a result

Just return a plain dict. Keep the keys consistent with what you described in `output_format` in the agent card:

```python
return {
    "status": "success",
    "material_id": material_id,
    "result": { ... },
    "agent": self.agent_name,
}
```

**Errors — return vs raise.** Two distinct failure modes:

- **User/input errors** (missing or invalid parameters, nothing to analyze):
  `return {"status": "error", "error": "<what the user can fix>"}`. The task
  still completes; the orchestrator sees a structured error it can relay or
  recover from (e.g. by asking the user a follow-up).
- **Infrastructure failures** (downstream service unreachable, unexpected
  exception): just let the exception propagate (or `raise`). The base class
  logs it and emits a final `failed` task status.

Don't wrap your whole `_execute` in `try/except Exception` that converts
crashes into `{"status": "error"}` — that hides real failures from the
platform's task accounting.

---

## Step 4 — Adding your logic

This is where you replace the `TODO` placeholder with real work.

### Example A: Calling Claude

**Prefer the built-in `LLMClient`.** It is async (`await`), uses the provider and models of your `LLM_CONFIG_PROFILE`, and never blocks the event loop:

```python
class SummarizerAgent(PrometheusAgent):
    async def _execute(self, params, context, event_queue):
        text = params.get("text")
        if not text:
            return {"status": "error", "error": "text is required"}

        await self.send_status_update(context, event_queue, message="Summarizing…")

        async with self.llm_client(context) as llm:
            response = await llm.medium(f"Summarize this in 2-3 sentences:\n\n{text}")

        return {"status": "success", "summary": response.text}
```

> ⚠️ **Do not call a synchronous SDK directly inside `async def _execute`.** Your
> agent runs on a single event loop. A blocking call — like the synchronous
> `anthropic.Anthropic().messages.create(...)` — does not `await`, so while it
> runs it freezes the whole loop: the keepalive heartbeat stops, streamed status
> updates stop flushing, and the upstream (backend gateway) connection can hit its
> socket-read timeout and tear down mid-task even though your agent is still
> working. See "Don't block the event loop" below.

If you must use the **synchronous** Anthropic SDK (install `anthropic`; see Step 5),
offload the blocking call to a worker thread with `asyncio.to_thread` so the loop
stays free.

This path bypasses `self.llm_client`, so `LLM_CONFIG_PROFILE` does not apply and you
name the model yourself. `MODEL_NAME` below is then *your* variable, not one the
template provides — add it to your `docker-compose.yml` environment block and `.env`
under "your own agent-specific variables", or the `os.getenv` default is all you get:

```python
import asyncio
import os
from anthropic import Anthropic

LLM_API_KEY = os.getenv("LLM_API_KEY")  # an Anthropic key, set in .env
MODEL_NAME = os.getenv("MODEL_NAME", "claude-sonnet-4-6")

class SummarizerAgent(PrometheusAgent):
    async def _execute(self, params, context, event_queue):
        text = params.get("text")
        if not text:
            return {"status": "error", "error": "text is required"}

        await self.send_status_update(context, event_queue, message="Summarizing…")

        client = Anthropic(api_key=LLM_API_KEY)
        # to_thread runs the blocking call off the event loop and awaits the result.
        response = await asyncio.to_thread(
            client.messages.create,
            model=MODEL_NAME,
            max_tokens=512,
            messages=[{"role": "user", "content": f"Summarize this in 2-3 sentences:\n\n{text}"}],
        )

        return {
            "status": "success",
            "summary": response.content[0].text,
        }
```

### Example B: Calling an external HTTP API

```python
import os

import httpx

class DataFetcherAgent(PrometheusAgent):
    async def _execute(self, params, context, event_queue):
        record_id = params.get("record_id")
        await self.send_status_update(context, event_queue, message="Fetching record…")

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.example.com/records/{record_id}",
                headers={"Authorization": f"Bearer {os.getenv('MY_API_KEY')}"},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()

        return {"status": "success", "record": data}
```

### Example C: long blocking work (and reporting progress from it)

If your computation uses a blocking library (NumPy/SciPy, a legacy analysis tool,
a synchronous SDK), run it on a worker thread with `asyncio.to_thread` so it does
not block the event loop. For a short call, fire-and-await is enough:

```python
import asyncio

class SimulationAgent(PrometheusAgent):
    async def _execute(self, params, context, event_queue):
        await self.send_status_update(context, event_queue, message="Running simulation…")
        result = await asyncio.to_thread(self._run_simulation, params)
        return {"status": "success", "result": result}

    def _run_simulation(self, params):
        # blocking computation here — regular synchronous Python, no asyncio.
        import numpy as np
        data = np.array(params.get("values", []))
        return {"mean": float(data.mean()), "std": float(data.std())}
```

#### Streaming progress from a long blocking task

A long task that emits no traffic for tens of seconds will look dead to the
caller and can trip upstream timeouts. The fix is **not** a bigger timeout — it is
to keep bytes on the wire. The worker thread cannot emit directly (`event_queue`
wraps a loop-bound `asyncio.Queue` that is **not thread-safe**), so the blocking
work runs on a thread and emits progress into a thread-safe mailbox that the event
loop drains and forwards while `await`-ing short sleeps that keep the loop alive.

**Recommended: subclass `PrometheusWorker`.** It packages exactly that — a
thread-safe mailbox, cooperative cancellation, and a safe subset of emit helpers
that mirror the agent's (`emit_status_update`, plus `emit_json_artifact` for
verbose/structured output). `PrometheusAgent.run_worker` runs it off-loop, forwards
its events, flushes on completion, re-raises its errors, and signals cancellation:

```python
from prometheus_api.agent import PrometheusAgent, PrometheusWorker

class SimulationWorker(PrometheusWorker):
    def __init__(self, items):
        super().__init__()
        self.items = items

    def run(self):                        # plain synchronous code on a worker thread
        for i, item in enumerate(self.items, 1):
            if self.cancelled:            # threads can't be killed — stop cooperatively
                return {"status": "cancelled", "done": i - 1}
            self.emit_status_update(f"Processing {i}/{len(self.items)}…")
            heavy_blocking_call(item)
        # JSON artifacts are handy for verbose/structured progress (e.g. a long
        # numerical simulation); supports append/last_chunk for streaming chunks.
        self.emit_json_artifact({"processed": len(self.items)}, name="summary")
        return {"status": "success", "processed": len(self.items)}

class SimulationAgent(PrometheusAgent):
    async def _execute(self, params, context, event_queue):
        worker = SimulationWorker(params["items"])
        return await self.run_worker(worker, context, event_queue)
```

`emit_json_artifact` is inline-only (not cataloged). DeepLynx uploads, catalog
registration, conversation messages, and `INPUT_REQUIRED` are intentionally absent
from the worker — do those from `_execute` on the loop, before or after
`run_worker`.

**Under the hood (the manual equivalent).** If you cannot use `PrometheusWorker`,
this is the same pattern by hand — the thread writes progress into a thread-safe
`queue.Queue`, and `_execute` polls it, emits on the loop, and sleeps between polls:

```python
import asyncio
import queue
import threading

class ProgressReporter:
    """Worker thread writes; event loop reads. queue.Queue keeps every
    message (a 'latest value' field would drop updates between polls)."""
    def __init__(self):
        self._queue: "queue.Queue[str]" = queue.Queue()

    def report(self, message):        # called FROM the worker thread
        self._queue.put(str(message))

    def drain(self):                  # called FROM the event loop
        msgs = []
        while True:
            try:
                msgs.append(self._queue.get_nowait())
            except queue.Empty:
                return msgs

class SimulationAgent(PrometheusAgent):
    async def _execute(self, params, context, event_queue):
        progress = ProgressReporter()
        cancel = threading.Event()   # threads can't be killed; cancel cooperatively
        work = asyncio.create_task(asyncio.to_thread(self._run, params, progress, cancel))

        try:
            while not work.done():
                for msg in progress.drain():
                    await self.send_status_update(context, event_queue, message=msg)
                await asyncio.sleep(1.0)   # yields → heartbeat + SSE keep flowing
            for msg in progress.drain():    # flush the last messages
                await self.send_status_update(context, event_queue, message=msg)
            return await work               # recover result / re-raise exceptions
        except asyncio.CancelledError:
            cancel.set()                    # caller disconnected — ask the worker to stop
            raise

    def _run(self, params, progress, cancel):
        """Pure synchronous code — no asyncio, no event_queue."""
        items = params["items"]
        for i, item in enumerate(items, 1):
            if cancel.is_set():
                return {"status": "cancelled", "done": i - 1}
            progress.report(f"Processing {i}/{len(items)}…")
            heavy_blocking_call(item)
        return {"status": "success", "processed": len(items)}
```

Caveats (either way):

- **Cancellation:** a client disconnect cancels the *coroutine*, not the *thread*
  (Python threads cannot be force-killed). `PrometheusWorker` exposes `self.cancelled`;
  by hand, pass a `threading.Event` the worker checks so it stops cooperatively
  instead of running on orphaned.
- **CPU-bound work:** `to_thread` truly parallelizes only work that releases the
  GIL (I/O, heavy NumPy). For sustained pure-Python CPU loops use
  `ProcessPoolExecutor` — but then progress must cross processes (e.g. a
  `multiprocessing.Queue`) rather than a shared object.
- **A truly opaque blocking call** (one `library.run()` with no hooks) cannot
  report mid-flight; there the loop-side heartbeat alone keeps the connection
  alive.

A complete, runnable reference lives in the platform's
`agents/debug-agents/thread-pattern-agent` (skill `run_blocking_task`), which uses
`PrometheusWorker`.

### Reading environment variables

Never hard-code secrets or URLs. Read them from environment variables using `os.getenv`:

```python
API_KEY  = os.getenv("MY_API_KEY")        # returns None if not set
BASE_URL = os.getenv("BASE_URL", "https://api.example.com")  # with default
```

Values come from your `.env` file locally and from the `environment:` block in `docker-compose.yml` when containerized. You add the variables in both places (see Step 7).

---

## Step 5 — Python packaging (`pyproject.toml`)

`pyproject.toml` tells uv (and pip) what packages your agent needs. Open the file:

```toml
[project]
name = "my-agent"
version = "0.1.0"
description = "One-sentence description"
requires-python = ">=3.12"
dependencies = [
    # your packages here
]
```

**Add only packages that your agent code imports directly.** The base image already has `prometheus_api`, `a2a`, `starlette`, and `uvicorn` installed — listing them here would install a second copy and could cause version conflicts.

```toml
dependencies = [
    "anthropic>=0.18.0",   # if you call Claude directly
    "httpx>=0.26.0",       # if you call external HTTP APIs
    "numpy>=1.26.0",       # if you use NumPy
]
```

Add packages with `uv add`, which updates `pyproject.toml` and `uv.lock` and syncs your environment:

```bash
uv add anthropic httpx
```

If you edit `pyproject.toml` by hand, run `uv sync` afterwards. Commit `uv.lock` with `pyproject.toml`.

---

## Step 6 — Docker primer and Dockerfile

### What Docker is

Docker packages your code and all its dependencies into a **container image** — a portable, self-contained unit that runs identically on any machine. You build an image once and run it anywhere.

- An **image** is the blueprint (built from a `Dockerfile`).
- A **container** is a running instance of an image.
- A **base image** is a pre-built image your image extends. The platform publishes one (`prometheus_api`) that already has Python, prometheus_api, and all agent infrastructure installed.

### Your Dockerfile

```dockerfile
ARG PROMETHEUS_API_BASE_IMAGE_REPO=ghcr.io/idaholab/prometheus_core/prometheus_sdk-devel
ARG PROMETHEUS_API_BASE_IMAGE_HASH
FROM ${PROMETHEUS_API_BASE_IMAGE_REPO}:${PROMETHEUS_API_BASE_IMAGE_HASH}
```
Starts from the pre-built base image, pinned to a specific tag for reproducibility. The repo and tag are passed in as build arguments — you never change this line directly; you change the value in `.env` or the platform's `Makefile`. (The real Dockerfile uses the same `FROM` twice: once for a small stage that checks `uv.lock` exists, then for the image itself.)

```dockerfile
WORKDIR /app
```
Sets the working directory inside the container. All subsequent paths are relative to `/app`.

```dockerfile
ENV UV_PROJECT_ENVIRONMENT="/usr/local" \
    UV_LINK_MODE=copy
```
Configures uv to install packages into the system Python (where `prometheus_api` is already installed) rather than a separate virtual environment.

```dockerfile
FROM ... AS lockfile
COPY uv.lock* /lock/
RUN [ -f /lock/uv.lock ] || { echo "ERROR: uv.lock not found. ..."; exit 1; }
```
A throwaway first stage that fails the build with instructions if `uv.lock` is missing. Run `uv sync` in your agent's directory to create it, and commit it. The lockfile is passed to the install step from this stage, so it doesn't end up in the final image.

```dockerfile
RUN --mount=type=cache,...  --mount=type=bind,source=pyproject.toml,... --mount=type=bind,from=lockfile,... \
    uv sync --locked --no-dev --no-install-project --inexact
```
Installs your packages at the versions in `uv.lock`. The build fails if `uv.lock` is out of date with `pyproject.toml`. `pyproject.toml` and `uv.lock` are mounted for this step rather than copied, since the image doesn't need them. This layer is cached by Docker: if neither file has changed since the last build, Docker skips the `RUN` line entirely — making subsequent rebuilds very fast.

```dockerfile
COPY agent.py /app/agent.py
COPY agent_card.json /app/agent_card.json
```
Copies your source files last. This ordering means code changes (the most frequent change) only invalidate the final layer, not the dependency installation layer.

```dockerfile
EXPOSE 8000
CMD ["python", "agent.py"]
```
Documents that the container listens on port 8000 and sets the default startup command.

### Building the image manually

You don't normally need to build manually — `make up` does it. But to check that your Dockerfile is correct:

```bash
# Get the current hash from platform/Makefile or your .env
export PROMETHEUS_API_BASE_IMAGE_HASH=<hash>

docker build \
  --build-arg PROMETHEUS_API_BASE_IMAGE_HASH=$PROMETHEUS_API_BASE_IMAGE_HASH \
  -t my-agent:dev .
```

---

## Step 7 — Platform wiring (`docker-compose.yml`)

### What Docker Compose is

Docker Compose is a tool that starts multiple containers together from a single YAML file. It handles naming, networking, and environment variables so you don't have to pass long `docker run` commands by hand.

### Key sections in your `docker-compose.yml`

```yaml
services:
  my-agent:
    build:
      context: .
      args:
        PROMETHEUS_API_BASE_IMAGE_HASH: ${PROMETHEUS_API_BASE_IMAGE_HASH:-latest}
```
Tells Compose to build the image from the current directory using the `Dockerfile` here. The `${...}` syntax reads values from your `.env` file or the shell environment.

```yaml
    container_name: my-agent
    networks:
      - agent-network
```
Gives the container a stable hostname (`my-agent`) on the shared network. Other containers can reach your agent at `http://my-agent:8000`.

```yaml
    environment:
      AGENT_PORT: 8000
      AGENT_SECRET: ${AGENT_SECRET}
      REGISTRY_URL: ${REGISTRY_URL:-http://backend:8000}
      LITELLM_MASTER_KEY: ${AGENT_SECRET}   # the SDK's name for the registry token
      REDIS_URL: ${REDIS_URL:-redis://redis:6379}
      REDIS_PASSWORD: ${REDIS_PASSWORD}
```
Passes secrets and configuration into the container at runtime. Values come from `.env` (the `${VAR}` references). The `:-` syntax provides a default if the variable is not set.

**Add your own agent-specific variables here and in `.env`:**

```yaml
      MY_API_KEY: ${MY_API_KEY:-}
      MY_BASE_URL: ${MY_BASE_URL:-https://api.example.com}
```

### Network mode selection

The common service definition lives in `docker-compose.yml`. The Makefile adds
one network include file based on `EXTERNAL_AGENT_HOST` and
`EXTERNAL_AGENT_PORT`.

#### Internal network mode

Leave both variables unset to use internal mode. This is the default for a
standalone agent repository running on the same Docker host as the platform.
The Makefile includes `docker-compose.net_internal.yml`:

```yaml
networks:
  agent-network:
    external: true
    name: prometheus_platform_agent-network
```

`external: true` means "this network was created by someone else; don't try to
create it yourself." The `name` must match what the platform actually created.

> **Note:** The network name is `<COMPOSE_PROJECT_NAME>_agent-network`. The
> platform defaults to `prometheus_platform` (the directory name), giving
> `prometheus_platform_agent-network`.

Start your agent after the platform is running:

```bash
# In the platform directory:
make up

# In your agent directory:
make up
```

#### External port mode

Set both variables to expose the agent outside Docker:

```bash
EXTERNAL_AGENT_HOST=my-host.example.gov EXTERNAL_AGENT_PORT=8042 make up
```

If the platform will call the agent through a port published on the same Docker
host, set `EXTERNAL_AGENT_HOST=prometheus.host.internal`. That name means "the
host machine from inside a container": every platform and agent compose service
maps it to Docker's host gateway, on macOS and Linux alike. It does not resolve
on the host itself.

The Makefile includes `docker-compose.net_external.yml`:

```yaml
services:
  my-agent:
    ports:
      - "${EXTERNAL_AGENT_PORT}:${AGENT_PORT:-8000}"
    environment:
      EXTERNAL_AGENT_URL: http://${EXTERNAL_AGENT_HOST}:${EXTERNAL_AGENT_PORT}

networks:
  agent-network:
```

This maps the host port to the container's `AGENT_PORT` and registers the URL
that the platform should call. If exactly one of `EXTERNAL_AGENT_HOST` or
`EXTERNAL_AGENT_PORT` is set, `make` stops before running Compose.

In external port mode, make sure `REGISTRY_URL` and `REDIS_URL` point to
hostnames that are reachable from inside the agent container, such as
`prometheus.host.internal` or a remote platform host. Do not use `localhost` for
host-published platform services from inside the container; inside the container,
`localhost` means the agent container itself.

#### In-tree platform deployment

<!-- Keep in sync with the "agent-template: platform" job in
     .github/workflows/test.yml, which runs these steps in CI. If you change
     the in-tree steps here or in Step 9, update the job to match. -->

If you want your agent to be part of the main platform stack and launched by the
platform's `make up`, copy your project directory into
`platform/agents/<your-agent-name>/`. The platform's Makefile
discovers `docker-compose.yml` files inside `agents/*/` and owns the top-level
network definition.

Then, from the `platform/` directory:

```bash
make generate   # re-discovers agents and regenerates docker-compose.agents.yml
make up         # starts everything including your new agent
```

**Which mode to choose?**

| Scenario | Recommended mode |
|----------|------------------|
| Agent runs in its own repo on the same Docker host as the platform | Internal network mode |
| Platform must reach the agent through a host or remote port | External port mode |
| Agent is maintained inside `platform/agents/` | In-tree deployment |

Most purpose-built agents use internal network mode during integration testing.

---

## Step 8 — Running locally

You have two ways to run your agent during development. Use Python for fast iteration, Docker for integration testing.

### Python directly (no Docker)

This is the fastest way to test your logic. Set your environment variables and run:

```bash
# Load your .env file into the shell
export $(grep -v '^#' .env | xargs)

# Run the agent (the base class starts uvicorn on AGENT_PORT)
python agent.py
```

The agent starts and logs something like:

```
INFO:prometheus_api.agent.base:Loaded agent card: My Agent v1.0.0
INFO:prometheus_api.agent.base:Starting HTTP server on 0.0.0.0:8000
```

If the target agent is running in Docker, start it in external network mode so
`localhost:8000` reaches the container; see the
[template README run instructions](README.md#run-it).

To test it, send a request in a second terminal:


```bash
curl -s -X POST http://localhost:8000 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $AGENT_SECRET" \
  -d '{
    "jsonrpc": "2.0",
    "method": "message/send",
    "id": "1",
    "params": {
      "message": {
        "messageId": "msg-1",
        "role": "user",
        "parts": [{"kind": "text", "text": "{\"input_data\": \"hello world\"}"}],
        "metadata": {"skillId": "my_skill"}
      }
    }
  }' | python -m json.tool
```

You'll see the response with your result dict in the final `completed` status event.

> **Tip:** When running locally without a Redis connection, the agent still works — artifact registry and state storage fall back to an in-memory dict. Set `AGENT_SECRET_REQUIRED=false` in `.env` to skip the bearer token check during development.

### Docker via Makefile

Build and start the container:

```bash
make up-fg
```

Stop with `Ctrl+C`, or run in the background:

```bash
make up        # detached
make logs      # follow logs
make down      # stop and remove container
```

---

## Testing your agent

The scaffold includes a `tests/` directory wired for `pytest` (with
`asyncio_mode = "auto"`, so async tests need no decorators). `RequestContext`
and `EventQueue` are mocked in `tests/conftest.py`, which means `_execute` is
tested directly — no HTTP server, Redis, or registry required:

```bash
uv run pytest
uv run ruff check .
```

The starter tests cover the example skill's success and missing-input paths,
plus `test_build_app_loads_agent_card`, which builds the server without starting
it, so a broken `agent_card.json` or workflow file fails the tests. As you
implement your logic, give every input-validation branch and every
distinct result shape its own test. To assert on emitted progress updates or
artifacts, inspect `event_queue.enqueue_event` calls:

```python
async def test_emits_progress(context, event_queue):
    agent = _make_agent()
    await agent._execute({"input_data": "x"}, context, event_queue)
    events = [call.args[0] for call in event_queue.enqueue_event.await_args_list]
    assert events  # e.g. check TaskStatusUpdateEvent messages or artifacts
```

---

## Step 9 — Deploying to the platform

Once your agent works locally, deploying it means connecting it to a running Prometheus platform instance so the orchestrator can discover and route to it.

### What happens at startup

When your container starts, `PrometheusAgent.run()` calls `register_with_registry_async()`. This sends a POST request to `REGISTRY_URL` (the platform backend's agent registry) advertising your agent's name, URL, and skills. The orchestrator polls the backend's agent list and starts routing requests to you.

Registration retries with exponential backoff (default: 10 attempts, up to 30 seconds between tries), so the order in which containers start does not matter — your agent will wait for the backend to become available.

### External repository deployment

1. Make sure the platform is running (`make up` from `platform/`).
2. Fill in your `.env` with the same `AGENT_SECRET`, `REDIS_PASSWORD`, `LLM_CONFIG_PROFILE`, `LLM_API_KEY` and `DEEPLYNX_*` values that the platform uses (`python setup_agent.py --env-only <agent-dir>` copies them from `platform/.env`). In external mode, set `REGISTRY_URL=http://prometheus.host.internal:8600`.
3. Start your agent: `make up`
4. Verify registration: `curl -s -H "Authorization: Bearer $AGENT_SECRET" http://localhost:8600/v1/agents | python -m json.tool` (replace `8600` with `BACKEND_PORT` from the platform's `.env`). Your agent's name should appear in the list.

If you need the agent to restart automatically when the platform does, add it to the platform team's infrastructure configuration or document the startup order for your deployment environment.

### In-tree deployment

<!-- Keep in sync with the "agent-template: platform" job in
     .github/workflows/test.yml, which runs these steps in CI (scaffold,
     uv sync, copy to platform/agents/, make generate, make up, then a check
     that the agent registered). If you change them, update the job to match. -->

1. Copy your project directory to `platform/agents/<your-agent-name>/`.
2. From `platform/`:
   ```bash
   make generate   # picks up your new docker-compose.yml
   make up         # or make restart if platform is already running
   ```
3. Your agent appears in `docker compose ps` and logs with `make logs SERVICE=your-agent-name`.

> **Note:** The platform's `make generate` discovers agents by looking for `docker-compose.yml` files at exactly one directory level inside `agents/`. The directory name becomes the service name. Make sure your directory name is distinct from existing agents.

---

## Advanced topics

The following capabilities are documented in detail in the linked references. This section shows where to look.

### Prompt template files

Put large static LLM prompts in `prompts/` rather than embedding long strings in
`agent.py`. The template includes `prompts/system_prompt.txt` and uses the
shared `load_prompt(...)` helper from `prometheus_api`.

```python
from prometheus_api import load_prompt

system_prompt = load_prompt("system_prompt.txt").format(input_data=input_data)

async with self.llm_client(context) as llm:
    response = await llm.medium(system_prompt)
```

Prompt files are copied into the Docker image by the template Dockerfile. If
you add new prompt files, keep placeholders explicit and escape literal JSON
braces as `{{` and `}}` when using `str.format`.

### Agent-owned workflows

Use `workflows/` when this agent should contribute reusable workflow templates
to the platform workflow library. `prometheus_api` loads `*.yaml`, `*.yml`, and
`*.json` files from that directory at startup and inserts them into the raw
agent card. The client-agent discovers those workflows from the agent card and
exposes them in the platform workflow library.

The template includes `workflows/example_workflow.yaml.example` so new agents do
not publish a sample workflow accidentally. Rename it to
`example_workflow.yaml` only after reviewing the workflow id, inputs, step
bindings, and output mapping.

```yaml
id: my_agent.example_workflow
name: My Agent Example Workflow
version: "1.0.0"
steps:
  - id: run_primary_skill
    skill_id: my_skill
    is_final: true
    params:
      input_data:
        from: input.input_data
```

If your workflow YAML contains `#`, `:`, or other YAML-sensitive characters in
scalar values, quote them. If you want to place workflows somewhere else, set
`AGENT_WORKFLOWS`; relative paths resolve next to `agent_card.json`.

See the workflow notes in `prometheus_api` and the platform workflow library
docs for schema details.

### Authenticated custom HTTP endpoints

Use custom endpoints for small provider-owned HTTP resources: artifact previews,
derived downloads, workflow support resources, or static viewer plugin assets.
Register them in `__init__` after `super().__init__(...)`.

```python
from starlette.responses import JSONResponse


class MyAgent(PrometheusAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
            "viewer-assets",
            endpoint_id="viewer_assets",
            purpose="viewer_plugin",
            description="Serve viewer plugin JavaScript and CSS.",
            content_types=["text/javascript", "text/css"],
        )

    async def preview_artifact(self, request):
        return JSONResponse({"artifact_id": request.path_params["artifact_id"]})
```

Routes registered this way use the same bearer-token authentication as normal
agent traffic and are advertised in `/api/agent-card` under `endpoints`. Static
directories resolve relative to `agent_card.json`, so copy any asset directory
into the Docker image if you add one.

Keep the platform boundary in mind: browser-facing features should usually be
aggregated, proxied, or cataloged by the client-agent instead of giving the
frontend arbitrary direct access to specialist agents.

### Verifying which platform user is calling you (multi-user identity)

On a multi-user platform deployment, every A2A request carries a short-lived
JWT identifying the human the platform is acting for. The base class verifies
it for you before `_execute` runs — you just read the result:

```python
async def _execute(self, params, context, event_queue):
    user_id = params["user_id"]   # verified by the base class; never spoofable
    # or equivalently: user_id = self.current_user_id()
    ...
```

**Signing is RS256 only.** This agent only ever *verifies* — it can never mint
a token, so it never needs a private key, only a public one (or a JWKS URL).
Set one of these in your `.env` (see `.env.example`):

```bash
# Recommended: fetch and cache the platform's public key(s) automatically,
# including transparent key rotation done through the platform's admin UI.
# Point this at the platform BACKEND's own JWKS endpoint -- every agent
# serves one too, but only the backend's reflects an admin-UI-rotated key.
JWKS_URL=https://prometheus.example.com/.well-known/jwks.json

# Or: a static public key the operator gives you directly. Generate/inspect
# with `prometheus-identity-keygen` (ships in prometheus_api, already
# installed in this image) or `openssl`. Won't observe a key rotated through
# the admin UI -- ask the operator for the new key if verification starts
# failing after a rotation.
USER_IDENTITY_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----\n"

USER_IDENTITY_ISS=prometheus-platform   # must match the operator's setting
USER_IDENTITY_AUD=prometheus-agents     # must match the operator's setting
```

If your agent fetches per-user credentials for a third-party resource (a
database, an HPC cluster, etc.) rather than just reading `user_id`, see the
credential-broker section of
[MULTI_USER.md](https://github.com/idaholab/prometheus_core/blob/devel/sdk/docs/agent/MULTI_USER.md)
in `prometheus_api` — `self.get_credential(resource)` and
`requires_user_isolation` are the two pieces you'll want.

Local/standalone testing without a platform identity configured: set
`USER_IDENTITY_REQUIRED=false` and `params["user_id"]` becomes the synthetic
value `"local"` instead of failing the request.

### Emitting artifacts

Instead of (or in addition to) returning a dict, your agent can emit typed artifacts that the frontend knows how to render — JSON data, files, PDFs.

```python
# Inline JSON artifact (available to downstream agents by artifact_id)
await self.send_json_artifact(
    context=context, event_queue=event_queue,
    payload={"score": 0.95, "label": "acceptable"},
    name="analysis_result",
    json_type="prometheus.my_agent.result.v1",
    catalog_artifact=True,
)
return {"message": "Analysis complete.", "agent": self.agent_name}

# File artifact (URI-backed, e.g. a local file or deeplynx:// reference)
await self.send_artifact_reference(
    context=context, event_queue=event_queue,
    name="report.pdf",
    description="Generated PDF report",
    uri="file:///tmp/report.pdf",
    mime_type="application/pdf",
)
```

See [PrometheusAgent Quick Start](https://github.com/idaholab/prometheus_core/blob/devel/sdk/docs/agent/QUICK_START.md) for the full artifact API including DeepLynx uploads.

### Consuming artifacts from other agents

In a multi-step plan, an upstream agent's output often reaches you as an
`artifact_id` parameter (declare it in your `inputSchema` with
`"x_input_source": "runtime"`). Turn it into a local file path with
`get_artifact_file_path` — it transparently handles inline JSON/text
artifacts, `file://` URIs, and `deeplynx://` URIs (downloaded through a
deterministic cache):

```python
async def _execute(self, params, context, event_queue):
    mesh_path = await self.get_artifact_file_path(
        params["artifact_id"],
        context=context,                      # supplies the conversation scope
        artifacts=params.get("artifacts"),    # catalog passed by the orchestrator
    )
    result = analyze_mesh(mesh_path)          # a plain pathlib.Path
    ...
```

You can also look records up directly: `self.resolve_artifact_reference(conversation_id, artifact_id)` or `self.resolve_artifact_by_name(conversation_id, name)`.

### Conversation messages (vs status updates)

`send_status_update` is transient progress UI; it disappears from view as new
updates arrive. For user-facing text that should be part of the chat history
(an intermediate finding, a caveat about the result), emit a durable
conversation message instead:

```python
await self.send_conversation_message(
    context, event_queue,
    "Corrosion margin is within limits, but the dataset for 350 °C is sparse.",
)
```

### Long-running skills: detach the turn (`declare_long_running`)

For simulation-class skills that you *know* will outlive a normal request
(minutes to hours), tell the orchestrator up front so it hands control back
to the user immediately and delivers your result out-of-band when the work
finishes:

```python
async def _execute(self, params, context, event_queue):
    await self.declare_long_running(
        context, event_queue,
        estimate_seconds=1800,
        message="Meshing and running the simulation — this takes ~30 minutes.",
    )
    # ...then do the work as usual; keep emitting status updates.
```

This composes with `PrometheusWorker` (Example C): declare first, then run the
blocking work off-loop. Without the declaration, long tasks still work — the
orchestrator just keeps the turn open until its own background deadline.

### Multi-turn input (`INPUT_REQUIRED`)

If your agent needs information it cannot infer from the initial call, it can pause and ask the user. The base class provides `send_input_required` which renders a form in the UI:

```python
from prometheus_api.agent import MissingInput

async def _execute(self, params, context, event_queue):
    if params.get("temperature_c") is None:
        await self.send_input_required(
            context=context, event_queue=event_queue,
            missing_inputs=[MissingInput(
                name="temperature_c",
                description="Operating temperature in °C.",
                user_prompt="What operating temperature (°C)?",
                type="number",
                required=True,
            )],
            hint="I need an operating temperature to continue.",
        )
        return {}   # suspend — do NOT return real results here

    # On resume, params holds every original argument plus the answer,
    # so params["temperature_c"] is set; no saved state is needed.
    ...
```

See the `INPUT_REQUIRED` section in [PrometheusAgent Quick Start](https://github.com/idaholab/prometheus_core/blob/devel/sdk/docs/agent/QUICK_START.md) for the full pattern and important rules.

### Multiple skills

When your agent card lists more than one skill, dispatch on `params.get("skill_id")`:

```python
async def _execute(self, params, context, event_queue):
    dispatch = {
        "analyze":  self._handle_analyze,
        "summarize": self._handle_summarize,
    }
    handler = dispatch.get(params.get("skill_id"))
    if handler is None:
        return {"error": f"Unknown skill: {params.get('skill_id')}"}
    return await handler(params, context, event_queue)
```

### DeepLynx file storage

To persist output files (CSVs, HDF5, etc.) to the DeepLynx data platform and make them accessible to other agents:

```python
from pathlib import Path
from prometheus_api.storage_client.connection import ConnectionConfig

config = ConnectionConfig.from_env()
artifact = await self.send_deeplynx_artifact(
    context=context, event_queue=event_queue,
    file_path=Path("/tmp/output.csv"),
    name="simulation_output.csv",
    description="Agent simulation results",
    storage_config=config,
    mime_type="text/csv",
)
# artifact.uri  →  "deeplynx://organizations/1/projects/2/items/42"
```

See [PrometheusAgent Quick Start — DeepLynx artifact](https://github.com/idaholab/prometheus_core/blob/devel/sdk/docs/agent/QUICK_START.md#deeplynx-artifact) and [StorageClient Guide](https://github.com/idaholab/prometheus_core/blob/devel/sdk/docs/storage-client/GUIDE.md).

### Per-conversation state

If your agent needs to remember context between turns (e.g. partial results, user preferences), use the built-in state store keyed by `context_id`:

```python
state = self.load_context_state(str(context.context_id))
state["counter"] = state.get("counter", 0) + 1
self.save_context_state(str(context.context_id), state)
```

State is backed by Redis when `REDIS_URL` is set, with an in-memory fallback for local development.

As of prometheus_api 0.7.0, `context.context_id` is the **stable conversation
ID** propagated by the orchestrator: state saved in one call is visible to
later calls — including calls to *other* skills of your agent — within the
same conversation. If you need per-invocation scoping instead, key by
`context.task_id` (see the [Agent Migration Guide](https://github.com/idaholab/prometheus_core/blob/devel/sdk/docs/agent/AGENT_MIGRATIONS.md)).

---

## Further reading

| Document | Description |
|----------|-------------|
| [PrometheusAgent Guide](https://github.com/idaholab/prometheus_core/blob/devel/sdk/docs/agent/GUIDE.md) | Full API reference, pitfalls, lifecycle hooks |
| [PrometheusAgent Quick Start](https://github.com/idaholab/prometheus_core/blob/devel/sdk/docs/agent/QUICK_START.md) | Condensed recipes for every helper |
| [Agent Migration Guide](https://github.com/idaholab/prometheus_core/blob/devel/sdk/docs/agent/AGENT_MIGRATIONS.md) | **Check this when bumping `PROMETHEUS_API_BASE_IMAGE_HASH`** — behavior changes per prometheus_api version, with migration steps |
| [Environment Setup](https://github.com/idaholab/prometheus_core/blob/devel/sdk/docs/ENV_SETUP.md) | All environment variables for agents and storage |
| [StorageClient Guide](https://github.com/idaholab/prometheus_core/blob/devel/sdk/docs/storage-client/GUIDE.md) | Reading and writing to DeepLynx |
| [Multi-User Identity & Credentials](https://github.com/idaholab/prometheus_core/blob/devel/sdk/docs/agent/MULTI_USER.md) | `params["user_id"]`, per-user credentials, process isolation |
| [Identity Key Management](https://github.com/idaholab/prometheus_core/blob/devel/sdk/docs/agent/IDENTITY_KEY_MANAGEMENT.md) | RS256 keys, `prometheus-identity-keygen`, JWKS setup for this template |
| [`examples/agent_patterns.py`](https://github.com/idaholab/prometheus_core/blob/devel/sdk/examples/agent_patterns.py) | Runnable reference implementation |
