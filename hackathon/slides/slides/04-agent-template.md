---
title: Building an Agent
footer: Day 1 · Building an agent
accent: agt
index:
  time: '2:45'
  heading: Building an agent
  color: var(--orange)
  blurb: 'Built on the challenge: one class with a skill dispatch, scaffolding, the card the orchestrator reads, reading uploads and publishing a table and a PNG, status, asking for columns, background tasks, LLMClient and forced tool calls, running, debugging, testing.'
---

# Building an agent {.title kicker="Day 1 · 2:45 pm" pills="All participants | 45 min | reference material in the appendix"}
Everything you need for tomorrow's Table & Plot agent: the code you write, the card that gets you called, files in and artifacts out, asking the user, LLMs, and how to run and test it.

---

## Your agent in one picture {eyebrow="The big picture"}

::: flow
- [gray flex=1] **User** | uploads `report.md`: "plot the population of Brie Basin"
- ->  {w=44}
- [navy flex=1.1] **Orchestrator LLM** | reads your **card**, picks a skill, fills its parameters
- ->  {w=44}
- [orange flex=1.1] **Your `_execute`** | reads the file, does the work, publishes results
- ->  {w=44}
- [green flex=1] **Artifacts** | a table, a PNG. The UI renders them; the next skill uses them.
:::

:::: grid 3
::: card
#### You write

{.small}
One Python class with one method, plus `agent_card.json`.
:::

::: card
#### The platform gives you

{.small}
Server, auth, registration, file storage (DeepLynx), the chat UI, follow-up forms, LLM access, background tasks.
:::

::: card
#### You never

{.small}
parse the chat, call other agents, or manage HTTP. The orchestrator chains your skills.
:::
::::

---

## One class, one method {eyebrow="The code you write"}

::: cols 1.35fr 1fr gap=28px
```python {.sm}
from prometheus_api.agent import PrometheusAgent

class NeutronAgent(PrometheusAgent):
    async def _execute(self, params, context, event_queue):
        if params["skill_id"] == "neutron_extract_table":
            return await self.extract(params, context, event_queue)
        if params["skill_id"] == "neutron_plot_table":
            return await self.plot(params, context, event_queue)
        return {"status": "error", "error": "unknown skill"}

if __name__ == "__main__":
    NeutronAgent(agent_name="Neutron Table Plot Agent").run()
```

|||

- `params`: the arguments the orchestrator chose, plus `skill_id`
- `context.context_id`: the conversation, your key for state
- **Return a dict.** It becomes the result the orchestrator reads.
- User mistake → `return {"status": "error", …}`. Broken infrastructure → let it raise.
:::

---

## Scaffold it from the template {eyebrow="Getting started"}

:::: grid 2 gap=30px
```bash {.sm}
cd ~/prometheus/prometheus_core/agent-template
python3 setup_agent.py "Neutron Table Plot" \
  ../../neutron-agent               # no ~
#  name: " Agent" is appended
#  skill id:  neutron_extract_table
#  copy secrets from ../platform/.env? yes
cd ../../neutron-agent
uv add pandas matplotlib          # writes uv.lock
git add pyproject.toml uv.lock    # commit both
```

::: callout bad
Prefix the **card name and every skill ID** with your team name. All teams build the same skills; same names overwrite each other in the registry.
:::

|||

| File | You edit it to… |
|---|---|
| `agent.py` | implement the skills {.hl} |
| `agent_card.json` | describe the skills to the orchestrator {.hl} |
| `pyproject.toml` + `uv.lock` | `uv add` *your* imports; commit both |
| `Dockerfile` | add a `COPY` line per extra module |
| `tests/` | test with a mocked context |
| `.env` | nothing. Never commit it. |
::::

---

# The card gets you called {.section num="A"}
The orchestrator LLM decides from your card alone whether to call you, and with what.

---

## Each skill becomes a tool for the orchestrator LLM {eyebrow="agent_card.json"}

:::: cols 1.35fr 1fr gap=28px
```json {.sm hl=9}
{ "id": "neutron_extract_table",
  "description": "Find one table in an uploaded markdown
     document by matching the user's description
     against the captions; publish it as a table.",
  "usage_notes": "Not for CSV files: plot those directly.",
  "inputSchema": { "type": "object",
    "properties": {
      "document_artifact_id": { "type": "string",
        "x_artifact_ref": "single",
        "description": "The markdown document." },
      "table_description": { "type": "string",
        "description": "How the user named the table." } },
    "required": ["document_artifact_id", "table_description"] } }
```

|||

#### The LLM sees {.acc}

{.sm}
- `description` + `usage_notes`
- parameter names, types, descriptions
- which parameters are `required`

#### It does not see {.acc}

{.sm}
- the agent description, `tags`, `output_format`, `examples`

::: callout
`x_artifact_ref` marks a file input: the orchestrator passes the id of an upload or an earlier result.
:::
::::

---

## Five rules for a card that works {eyebrow="Getting routed"}

::: takeaways
### Verb and object first

"Find one table in an uploaded markdown document…", not "Table tool".

### Say when *not* to use it

`usage_notes` steers the LLM away from the wrong skill.

### Describe every parameter; require few

A missing *required* parameter makes the platform ask the user with a form.

### Return what the next step needs

`artifact_id`, the caption, the exact column names. The orchestrator reads your result to plan the next call.

### Test three phrasings in the chat

"plot the census", "chart residents per year", "graph this". Fix the card, not the prompt.
:::

---

# Files in, artifacts out {.section num="B"}
Uploads arrive as artifacts in DeepLynx; your results go back the same way.

---

## Read the uploaded file {eyebrow="Input"}

::: flow
- [gray flex=1] **Chat upload**
- ->  {w=44}
- [sky flex=1] **DeepLynx** | stores the file
- ->  {w=44}
- [teal flex=1] **Artifact catalog** | gets an artifact id
- ->  {w=44}
- [orange flex=1] **Your skill** | `params["document_artifact_id"]`
:::

```python {.sm}
path = await self.get_artifact_file_path(
    params["document_artifact_id"],
    context=context, artifacts=params.get("artifacts"))
text = path.read_text()          # a local file, whatever the source
```

::: callout warn
No DeepLynx configured → uploads never reach your agent. Check it before you start (deck 03).
:::

---

## Publish a table and a plot {eyebrow="Output"}

:::: cols 1.35fr 1fr gap=28px
```python {.sm}
# the table: inline JSON, in the catalog
table_id = await self.send_json_artifact(
    context, event_queue,
    {"caption": caption, "columns": cols, "rows": rows},
    name="population_table", catalog_artifact=True)

# the plot: a PNG file, via DeepLynx
ref = await self.send_deeplynx_artifact(
    context=context, event_queue=event_queue,
    file_path=png_path, name="population.png",
    description="Brie Basin population vs year",
    storage_config=ConnectionConfig.from_env(),
    mime_type="image/png")

return {"status": "success", "artifact_id": ref.artifact_id}
```

|||

{.sm}
- **`mime_type` picks the viewer**: `image/png` → image, JSON → JSON tree, `text/markdown` → report.
- Return **ids and names**, not the data. The data lives in the artifact.
- `ConnectionConfig` comes from `prometheus_api.storage_client` and reads `DEEPLYNX_*` from your `.env`.

::: callout
Working example: `platform/agents/debug-agents/artifact-debug-agent` publishes images exactly like this.
:::
::::

---

## Tell the user what is happening {eyebrow="Feedback"}

::: cols 1.35fr 1fr gap=28px
```python {.sm}
await self.send_status_update(
    context, event_queue,
    message="Found 3 tables; matching captions…")

await self.send_conversation_message(
    context, event_queue,
    "Note: 2 missing values were skipped.")
```

|||

| Helper | Shows up as |
|---|---|
| `send_status_update` | a live progress line, gone when the turn ends |
| `send_conversation_message` | a message that stays in the chat history |
:::

::: callout warn
Status lines appear live only with `"capabilities": {"streaming": true}` in the card. The template ships `false`.
:::

---

## Ask which columns to plot {eyebrow="Asking the user"}

::: cols 1.35fr 1fr gap=28px
```python {.sm}
from prometheus_api.agent import MissingInput

# on the resumed call the answer is in params,
# next to all the original arguments
x = params.get("x_column")
if not x:
    await self.send_input_required(
        context, event_queue,
        missing_inputs=[MissingInput(
            name="x_column", type="enum",
            options=list(df.columns),
            description="Column for the x axis",
            user_prompt="Which column goes on the x axis?")],
        hint="Choose the columns to plot.")
    return {}
```

|||

{.sm}
1. Your task pauses; the chat shows a form with a **dropdown** of the real column names.
2. The user picks; the platform calls you **again** with the answers.
3. The answers arrive **merged into `params`**, together with the original arguments. `self.get_input_sources(context)` tells you who supplied each value (`model`, `user`, `context`).

{.small}
Need a yes/no before something costly? Put `"requires_approval": true` on the skill: the user approves before you are called.
:::

---

## Long-running work {eyebrow="Background tasks"}

{.lede}
Your agent sends a heartbeat every 15 s from its event loop. Blocking code (a solver, `time.sleep`, a sync SDK) freezes it.

| Your work is… | Use |
|---|---|
| async I/O, LLM calls | `await` it |
| a blocking call (pandas, matplotlib, a CLI) | `await asyncio.to_thread(fn, …)` |
| blocking, with progress messages | a `PrometheusWorker` run with `self.run_worker(...)` |
| minutes to hours | `await self.declare_long_running(context, event_queue, estimate_seconds=1800)`: the chat turn ends, and the result arrives later as a background task (`/tasks`) {.hl} |

{.small}
Working example: `platform/agents/debug-agents/thread-pattern-agent`. Details in the appendix.

---

# Using an LLM {.section num="C"}
One client in the base image. You pick a flavor in code; your `.env` picks the provider.

---

## Call an LLM {eyebrow="LLMClient"}

:::: cols 1.35fr 1fr gap=28px
```python {.sm}
from prometheus_api.llm_client import LLMProviderError

try:
    async with self.llm_client(context) as llm:
        r = await llm.small(
            f"Which caption matches '{desc}'? {captions}")
except LLMProviderError as e:   # one readable line
    return {"status": "error", "error": str(e)}
answer = r.text
```

|||

{.sm}
| Flavor | Good for |
|---|---|
| `small` | quick classification, picking a caption |
| `medium` | general reasoning, column matching |
| `large` | hard reasoning |
| `vision` | checking your own plot image |
| `embedding` | similarity search |

::: callout
Which provider answers is set by `LLM_CONFIG_PROFILE` in your agent's `.env` (the platform's, copied by `setup_agent.py`; deck 03). Your agent calls the provider directly with `LLM_API_KEY`.
:::

Note: The template compose forwards LLM_API_KEY, which every profile reads, and requires LLM_CONFIG_PROFILE. self.llm_client(context) reads config from the environment only (no key in A2A messages since prometheus-api 0.14.0).
::::

---

## Get a value back, not prose: a forced tool call {eyebrow="Structured answers"}

::: cols 1.35fr 1fr gap=28px
```python {.sm}
from pydantic import BaseModel
from prometheus_api.llm_client import (
    ToolDefinition, acall_tool)

class Pick(BaseModel):
    index: int          # which caption matches

PICK = ToolDefinition.from_pydantic(
    "pick_table", Pick,
    description="Choose the table whose caption matches")

async with self.llm_client(context, config=cfg) as llm:
    call = await acall_tool(llm, prompt, tool=PICK,
                            model="small")
idx = call.arguments["index"]
```

|||

{.sm}
- The model **must** answer by calling your tool, so you get a dict that matches your schema.
- Ideal for "which table?" and "which columns?".
- Validate the value anyway (an index within range, a real column name).
- Multi-step tool loops are possible too; see the appendix.

{.small}
Needs `prometheus_api` ≥ v0.13.0, which `prometheus_api:local` built from your clone has.
:::

---

# Run, register, test {.section num="D"}
Get your agent onto the platform, find out why it isn't called, and test it without a server.

---

## Next to your platform, in Docker {eyebrow="Running it"}

:::: cols 1.35fr 1fr gap=28px
```bash {.sm}
cd ~/prometheus/neutron-agent
make up                  # build + join the platform network
make logs                # "Registered 'neutron-table-plot-agent' …"

# in the chat
/agents                  # your agent is listed

# after you change code or the card
make up                  # rebuilds and restarts

# after the PLATFORM restarted (registry wiped)
docker compose -p neutron-agent restart
```

|||

{.sm}
- At startup the agent **registers itself** with the platform **backend** (`REGISTRY_URL=http://backend:8000`). Nothing to configure beyond the `.env`.
- The orchestrator notices new or changed agents within about a minute.
- Every platform `make up`/`make restart` empties the registry: restart your agent afterwards.

::: callout
Start a **fresh conversation** for each test. Old uploads and results stay visible to the orchestrator and can confuse it.
:::
::::

---

## Not called? Called wrong? Look here {eyebrow="When it doesn't work"}

{widths="420px|"}
| Symptom | Look at / fix |
|---|---|
| Container exits at startup | `make logs`: DeepLynx settings (`DEEPLYNX_*`) missing or wrong, or `LLM_CONFIG_PROFILE` not set |
| Build fails: `uv.lock not found` / out of date | `uv sync` (or `uv add …`), commit `uv.lock` |
| Not in `/agents` | `make logs` in your agent dir; restart it if the platform restarted |
| Listed, but never called | the skill `description` and `usage_notes`; try other phrasings |
| Called with the wrong arguments | parameter descriptions; what your previous result returned |
| Crashes on the file | `make logs`: your traceback is there |
| The plot doesn't render | `mime_type="image/png"`, DeepLynx configured |
| `LLMProviderError` (401, 404…) | `LLM_API_KEY` and `LLM_CONFIG_PROFILE` in `.env` |
| `ModuleNotFoundError` in the container | `uv add` the package; a `COPY` line for your own modules |

{.small}
What the orchestrator decided, and why: `docker compose -p prometheus_platform logs --no-log-prefix -f client-agent` in the platform.

---

## Test without a platform {eyebrow="Testing"}

::: cols 1.35fr 1fr gap=28px
```python {.sm}
# tests/conftest.py already provides `context` and
# `event_queue` fixtures (mocks)
async def test_finds_census(context, event_queue, monkeypatch):
    agent = NeutronAgent(agent_name="Neutron Table Plot Agent")
    monkeypatch.setattr(agent, "get_artifact_file_path",
                        fake_path("fixtures/report.md"))
    out = await agent._execute(
        {"skill_id": "neutron_extract_table",
         "document_artifact_id": "a1",
         "table_description": "population"},
        context, event_queue)
    assert "Census" in out["caption"]
```

|||

{.sm}
- Most of your logic (parsing, cleaning, plotting) is plain Python: test it as functions.
- **Mock the LLM** in tests; never call a real one.
- Keep your own test files in `tests/fixtures/`.

```bash {.sm}
uv sync
uv pip install -e ~/prometheus/prometheus_core/sdk
uv run pytest      # incl. test_build_app_loads_agent_card
uv run ruff check .
```

{.small}
Both must pass for the gate. A broken `agent_card.json` or `workflows/` file fails `pytest` too. `fake_path` is your own small helper.
:::

---

## Remember three things {eyebrow="Takeaways"}

::: takeaways
### The card is the interface

The orchestrator LLM knows only your skill descriptions and parameters, and reads your result to plan the next step.

### Files travel as artifacts

`get_artifact_file_path` in, `send_json_artifact` / `send_deeplynx_artifact` out. Return ids, not data.

### The platform does the plumbing

Forms for missing inputs, status in the chat, LLM access, background tasks. Use them instead of building your own.
:::

::: callout good
Next: the end-to-end dry run (3:30 pm). The appendix of this deck has every detail behind these slides.
:::

---

# Appendix: reference {.section .appendix num="A"}
Reference material behind the talk. Skipped in the session; use it when you need the details.

---

## You write `_execute`. The base class does the rest. {eyebrow="Mental model"}

::: grid 2 gap=30px
```python {.sm}
from prometheus_api.agent import (
    EventQueue, PrometheusAgent, RequestContext)

class HelloAgent(PrometheusAgent):
    async def _execute(self, params, context: RequestContext,
                       event_queue: EventQueue) -> dict:
        name = params.get("input_data")
        if not name:
            return {"status": "error", "error": "input_data is required"}
        await self.send_status_update(context, event_queue,
                                      message="Saying hello…")
        return {"status": "success", "greeting": f"Hello, {name}!"}

if __name__ == "__main__":
    HelloAgent(agent_name="Hello Agent").run()   # :8000
```

|||

#### `PrometheusAgent` gives you {.acc}

{.sm}
- An A2A v1 JSON-RPC server (a2a-sdk + Starlette + uvicorn) on `AGENT_PORT`
- `agent_card.json` loading, normalization, and serving
- **Registration** with the platform backend at startup, with retries
- Bearer auth (`AGENT_SECRET`) and user identity (RS256 JWT)
- Task lifecycle: initial Task → WORKING → your result → COMPLETED/FAILED
- Heartbeats every 15 s while you work
- Artifact catalog, context state, and a Redis task store
- LLM client, DeepLynx upload, and artifact download helpers
:::

---

## `agent-template/` at a glance {eyebrow="The template, inside prometheus_core"}

:::: grid 2 gap=30px
{.sm}
| File | Purpose |
|---|---|
| `setup_agent.py` | Interactive scaffolder (stdlib only). Copies `agent_template/` and replaces the placeholders. {.hl} |
| `agent_template/` | The canonical agent files (next slides) |
| `TUTORIAL.md` | A 1,247-line walkthrough: card, code, Docker, deploy, and every advanced pattern |
| `README.md` | Quick start, run modes, further reading |
| `success_message.txt` | The next-steps text printed after scaffolding |
| `tests/test_setup_agent.py` | Tests for the scaffolder itself (CI also scaffolds an agent and runs its tests) |
| `Makefile` | `check`, `fix`, `test` for this repo |

|||

::: callout warn
**Outdated in the template docs** (use this deck's versions):

<ul class="b xs" style="margin-top:6px">
<li>curl examples use A2A v0.3 <code>message/send</code>, which now returns "Method not found"</li>
<li>older copies install <code>prometheus_api</code> from the old repo; install from <code>sdk/</code> in the monorepo instead</li>
<li>local testing also needs <code>USER_IDENTITY_REQUIRED=false</code></li>
<li>the tutorial's minimal workflow YAML is missing the required <code>description</code></li>
<li>verifying <code>/v1/agents</code> needs <code>Authorization: Bearer $AGENT_SECRET</code></li>
</ul>
:::

{.small}
CI runs the template's tests and a scaffold smoke test (`setup_agent.py --yes`). Generated agents get tests and ruff config, but no workflow files.
::::

---

## `python setup_agent.py` {eyebrow="Scaffolding"}

:::: grid 2 gap=30px
::: col
{.sm}
| Prompt | Default | Becomes |
|---|---|---|
| Agent name | 1st argument, else prompted | card `name` "Hello World Agent" |
| Description | "A specialized agent for …" | card `description` |
| Slug | kebab-case name | service / container `hello-world-agent` |
| Class name | PascalCase | `HelloWorldAgent` |
| Primary skill ID | `<snake>_analysis` | `hello_world_analysis` |
| Skill name / description | "… Analysis" | skill fields |
| Output directory | 2nd argument, else `../<slug>` | a new folder (`~` is not expanded); for the hackathon `../../<team>-agent`, the team repo |
| Trim comments? | no | strips the teaching comments in `agent.py` |
:::

|||

::: card acc
#### It copies the platform secrets for you

{.small}
If `../platform/.env` exists (the platform in the same clone), it offers to write the agent's `.env` with `AGENT_SECRET`, `REDIS_PASSWORD`, `USER_IDENTITY_PUBLIC_KEY/ISS/AUD`, `LLM_CONFIG_PROFILE`, `LLM_API_KEY`, `EMBEDDING_API_KEY`, and every `DEEPLYNX_*`. With `LOCAL_SDK=true` in the platform it also points your agent at `prometheus_api:local`, the base image the platform built. It never copies the private key.
:::

::: callout bad
**Choose a unique name and skill ID.** The registry keys agents by card name; re-registering *deletes* any agent with the same name. Your skill id becomes the orchestrator's tool name (`[a-zA-Z0-9_-]`, ≤ 64 chars). Prefix both with your team name: type "Team Neutron Mesh QA" (the scaffolder appends " Agent"), skill `neutron_mesh_quality_report`.
:::

```text {.xs}
# non-interactive: every default, incl. copying
# ../platform/.env; fails if the folder exists
python3 setup_agent.py --yes "Hello World" ../hello-world
```
::::

---

## Anatomy of `my-agent/` {eyebrow="The generated agent"}

:::: grid 2 gap=30px
```text {.sm}
hello-world/
├── agent.py                  # your class, _execute()
├── agent_card.json           # what the orchestrator reads
├── prompts/
│   ├── system_prompt.txt     # load_prompt("system_prompt.txt")
│   └── README.md
├── workflows/
│   ├── example_workflow.yaml.example   # rename to enable
│   └── README.md
├── tests/
│   ├── conftest.py           # mocked context + event_queue
│   └── test_agent.py         # 3 tests, incl. the card loads
├── pyproject.toml            # YOUR deps only
├── uv.lock                   # created by uv sync; commit it
├── Dockerfile                # FROM prometheus_api base image
├── docker-compose.yml        # service + env
├── docker-compose.net_internal.yml   # join platform network
├── docker-compose.net_external.yml   # publish a host port
├── Makefile                  # up, up-fg, down, logs
├── .env.example  (.env)
└── README.md
```

|||

::: card
#### `pyproject.toml`

{.small}
`dependencies = []`. `uv add` only what *your* code imports (numpy, httpx, meshio…) and commit `uv.lock`: the image build runs `uv sync --locked` and fails without it. Never add prometheus_api, a2a-sdk, starlette, or uvicorn: the base image provides them.
:::

::: card
#### `Dockerfile` copies only

{.small}
`agent.py`, `agent_card.json`, `prompts/`, `workflows/`. **Adding a module (`tools.py`)? Add a `COPY` line**, or the container fails with `ModuleNotFoundError`.
:::

::: card
#### `Makefile`

{.small}
`make up` checks that `prometheus_platform_agent-network` exists (the platform must be running first) and builds and starts your container. There are no test or lint targets: use `uv run pytest` and `uv run ruff check .`
:::
::::

---

## The hello-world `_execute`, as generated {eyebrow="agent.py"}

::: grid 2 gap=30px
```python {.xs}
from typing import Any
from prometheus_api import load_prompt
from prometheus_api.agent import EventQueue, PrometheusAgent, RequestContext

class HelloWorldAgent(PrometheusAgent):
    async def _execute(self, params: dict[str, Any],
                       context: RequestContext,
                       event_queue: EventQueue) -> dict[str, Any]:
        # 1. Read inputs: keys match inputSchema properties
        input_data = params.get("input_data")
        if not input_data:
            return {"status": "error",
                    "error": "input_data is required"}

        # 2. Optional progress updates
        await self.send_status_update(
            context=context, event_queue=event_queue,
            message="Processing your request…")

        # 3. Do the actual work here
        result = {"status": "success",
                  "input_received": input_data,
                  "message": "Replace this with your agent's processing logic."}

        # 4. Return a plain dict (matches output_format in the card)
        return result

if __name__ == "__main__":
    HelloWorldAgent(agent_name="Hello World Agent").run()
```

|||

#### The `_execute` contract {.acc}

{.sm}
- `params`: the JSON the orchestrator sent, with `skill_id` (from `metadata.skillId`) and `user_id` (from the verified token) injected.
- Non-JSON text arrives as `{"message": text}`.
- `context.context_id` is the **conversation** key for state and artifacts.
- Return a `dict`. The base class sends it as the one text part of `TASK_STATE_COMPLETED`.
- **User or input problem** → `return {"status": "error", "error": …}`.
- **Infrastructure failure** → let it raise → `TASK_STATE_FAILED`. Don't blanket `try/except`.
- Several skills? Dispatch on `params["skill_id"]` with a dict of handlers.
:::

---

## What happens around your code {eyebrow="Lifecycle"}

::: grid 2 gap=30px
#### At startup: `run()` → `build_app()` {.acc}

{.sm}
1. Load `agent_card.json` and merge `workflows/*.yaml`
2. Set the card URL = `EXTERNAL_AGENT_URL` or `http://<hostname>:<AGENT_PORT>` (never put `url` in the file)
3. Build routes: JSON-RPC `/`, card, health, jwks, debug
4. Install bearer auth. Missing `AGENT_SECRET` → `RuntimeError`, unless `AGENT_SECRET_REQUIRED=false`.
5. Lifespan: **register with the backend** in the background
6. uvicorn on `0.0.0.0:$AGENT_PORT` (8000)

|||

#### Per request: `PrometheusAgentExecutor.execute` {.acc}

<div class="dg">
<div class="box gray">enqueue the initial <b>Task</b></div>
<div class="arrow-v" style="height:28px"></div>
<div class="box violet">verify <code>metadata.userToken</code> (RS256) → <code>IdentityError</code> = FAILED</div>
<div class="arrow-v" style="height:28px"></div>
<div class="box gray">parse params · emit <code>TASK_STATE_WORKING</code></div>
<div class="arrow-v" style="height:28px"></div>
<div class="box orange"><b>your <code>_execute()</code></b> + a heartbeat every 15 s</div>
<div class="arrow-v" style="height:28px"></div>
<div class="box green"><code>TASK_STATE_COMPLETED</code> with <code>json.dumps(result)</code><span class="small">(skipped if you already emitted a stopping state such as INPUT_REQUIRED)</span></div>
</div>
:::

---

# The agent card {.section num="A"}
How the orchestrator LLM decides whether and how to call you (and your result JSON is how it decides what to do next). Write it as if a careful colleague had to decide from this text alone.

---

## The template card {eyebrow="agent_card.json"}

:::: grid 2 gap=30px
```json {.sm hl=5}
{
  "name": "Hello World Agent",
  "description": "A specialized agent for hello world",
  "version": "1.0.0",
  "capabilities": { "streaming": false, "pushNotifications": false },
  "skills": [ {
    "id": "hello_world_analysis",
    "name": "Hello World Analysis",
    "description": "Performs analysis using hello world",
    "usage_notes": "When to use this skill vs. other skills.",
    "requires_approval": false,
    "expected_duration_seconds": 30,
    "output_format": "JSON with keys: status, input_received, message",
    "inputSchema": {
      "type": "object",
      "properties": {
        "input_data": { "type": "string",
          "description": "The main input data to process." } },
      "required": ["input_data"] } } ]
}
```

|||

#### Two views of the same card {.acc}

{.sm}
| Endpoint | Content |
|---|---|
| `/api/agent-card` | the **raw** card with Prometheus extensions (`inputSchema`, `usage_notes`, `requires_approval`, workflows, endpoints). The orchestrator reads this. |
| `/.well-known/agent-card.json` | the strict A2A v1 card: standard skill fields only (`id`, `name`, `description`, `tags`, `examples`) |

::: callout warn
`"streaming": false` means the orchestrator makes one blocking call, so your status updates are **not** shown live. Set it to `true` to see progress in the UI.
:::
::::

---

## Card fields (1/2): identity and routing {eyebrow="Field reference"}

{widths="290px|130px|"}
| Field | Required? | Meaning / consumer |
|---|---|---|
| `name` | yes | Display name **and** registry route key: lowercased, spaces → hyphens (`/a2a/hello-world-agent`). Must be unique. |
| `description` | yes | Agent-level summary. **Not shown** to the orchestrator LLM; it routes on the *skill* description. |
| `version`, `defaultInputModes`, `defaultOutputModes` | defaulted | `1.0.0`, `["text"]` |
| `capabilities.streaming` | no | `true` → the orchestrator uses `SendStreamingMessage` and you get live status |
| `skills[].id` | yes | Arrives as `params["skill_id"]`. **Globally unique** across the platform. {.hl} |
| `skills[].description` | yes | The tool description the orchestrator LLM reads: the main routing signal {.hl} |
| `skills[].usage_notes` | ext. | Appended to the tool description as "Usage: …": when to use this skill rather than others {.hl} |
| `skills[].tags` | A2A std. | **Not shown** to the orchestrator LLM (discovery and A2A only) {.hl} |

---

## Card fields (2/2): inputs, approval, extensions {eyebrow="Field reference"}

{widths="290px|130px|"}
| Field | Required? | Meaning / consumer |
|---|---|---|
| `skills[].inputSchema` | ext. | Sent as the tool's JSON Schema (`x_*` keys stripped) and enforced. A required input the model can't fill → follow-up form (enum → dropdown). Optional fields are never asked for by the platform. {.hl} |
| `skills[].requires_approval` | ext. | `true` → Approve/Reject before the call (`plan_ready`); one Approve covers every gated call in that step |
| `skills[].expected_duration_seconds` | ext. | Only for the plan card's time estimate. The call timeout is a fixed 900 s. |
| `skills[].provides`, `derivation_rules`, `execution_priority` | optional | Ignored by the tool-calling loop; drop them |
| `skills[].output_format`, `skills[].examples` | — | **Not read** by the orchestrator today (`examples` is a standard A2A field). Document for humans; put routing hints in `description`. |
| top-level `workflows` | optional | Inline workflow definitions (or ship `workflows/*.yaml`) |

---

## The tool the orchestrator LLM gets, per skill {eyebrow="Getting routed"}

::: col
```yaml {.sm}
tool: geometry_meshing
description: Resolve a STEP file artifact, generate a
  first-order tetrahedral volume mesh with Gmsh, …
  Usage: Use for solid .step or .stp artifacts …
parameters:
  step_artifact_id: string  "Source .step or .stp CAD
     geometry artifact to mesh. artifact_id of an
     existing conversation artifact."
  element_size: number  "Optional global target …"
  required: [step_artifact_id]
```

{.small}
From the real `gmsh_agent` card, as built by `agent_loop._skill_spec`. No tags, no agent description, `x_*` keys stripped.
:::

---

## Writing a card the orchestrator will call {eyebrow="Getting routed"}

- **Lead with the verb and the object**: "Compute scaled-Jacobian quality metrics for an Exodus mesh artifact…"
- `usage_notes`: when *not* to use you, and which neighbour to prefer.
- **Describe every property.** Use `enum` for fixed choices and units in the description. Keep `required` minimal.
- **File inputs**: `"x_artifact_ref": "single"` (or `"multiple"`). The orchestrator LLM passes an artifact id from an upload, an earlier result, or the catalog; unknown ids are bounced back to it.
- **Non-file values** produced by another skill: `"x_input_source": "runtime"`, never asked from the user.
- **Return what the next step needs** (ids, names, column headers) in your result dict: the model reads up to 6000 chars of it.
- Costly or destructive? `"requires_approval": true`.
- Test in the UI with **three phrasings** of the request.

---

# Registry, discovery, and calls {.section num="B"}
How your agent announces itself, how the client-agent finds it, and the exact path a request takes.

---

## One POST to the backend at startup {eyebrow="Registering with the Agent Registry"}

::: grid 2 gap=30px
{.sm}
1. `GET {REGISTRY_URL}/v1/agents`, looking for an entry with the same `agent_name`
2. If one exists: `DELETE {REGISTRY_URL}/v1/agents/{agent_id}`
3. `POST {REGISTRY_URL}/v1/agents`:

```json {.xs}
{ "agent_name": "hello-world-agent",
  "agent_card_params": { …raw card…,
      "url": "http://hello-world-agent:8000",
      "protocolVersion": "1.0" },
  "static_headers": {
      "Authorization": "Bearer <AGENT_SECRET>" } }
# request header: Authorization: Bearer $AGENT_SECRET
```

{.small}
Retries: `REGISTRY_MAX_RETRIES` (default 10), backoff 2 s → ×2 → capped at 30 s. On final failure it logs "Continuing without registration" and **keeps serving, unregistered**.

|||

{.sm}
| Variable | Value |
|---|---|
| `REGISTRY_URL` | in Docker: `http://backend:8000` (template default); on the host: `http://localhost:8600` |
| `AGENT_SECRET` | the platform's value: the registry token, and what the backend sends to you |
| `LITELLM_MASTER_KEY` | legacy SDK name for the registry token; compose sets it to `${AGENT_SECRET}` |
| `EXTERNAL_AGENT_URL` | overrides the registered URL. It must be reachable **from inside** the backend and client-agent containers. |

```bash {.xs}
# verify
curl -s -H "Authorization: Bearer $AGENT_SECRET" \
  http://localhost:8600/v1/agents | python3 -m json.tool
docker compose -p hello-world logs 2>&1 | grep "Registered '"
# → Registered 'hello-world-agent' with LiteLLM at
#   http://backend:8000   (old log wording; it is the backend)
```
:::

---

## How the client-agent finds and calls you {eyebrow="Discovery and dispatch"}

<div class="dg">
<div class="row" style="gap:0; align-items:stretch">
<div class="box navy" style="flex:1"><b>① discover</b><span class="mono">GET backend:8000/v1/agents</span><span class="small">at startup, when the 60 s capability cache expires, on a skill miss, <code>POST /discovery/refresh</code></span></div>
<div class="arrow-h" style="width:40px"></div>
<div class="box navy" style="flex:1"><b>② fetch the full card</b><span class="mono">GET {your url}/api/agent-card</span><span class="small">tried first; falls back to the card stored in the backend registry</span></div>
<div class="arrow-h" style="width:40px"></div>
<div class="box navy" style="flex:1"><b>③ one tool per skill</b><span class="small">built by the orchestrator loop (<code>agent_loop.build_tool_catalog</code>): name = skill id, args = <code>inputSchema</code>. Cards cached 60 s in Valkey.</span></div>
</div>
<div class="arrow-v"><span>the orchestrator LLM calls your skill as a tool</span></div>
<div class="row" style="gap:0; align-items:stretch">
<div class="box orange" style="flex:1.2"><b>④ call via the gateway</b><span class="mono">POST backend:8000/a2a/hello-world-agent</span><span class="small"><code>Authorization: Bearer $AGENT_SECRET</code> · <code>A2A-Version: 1.0</code> · <code>SendMessage</code>, or <code>SendStreamingMessage</code> if streaming</span></div>
<div class="arrow-h" style="width:40px"></div>
<div class="box violet" style="flex:1"><b>⑤ the backend forwards</b><span class="small">to the registered <code>url</code>, adding <code>static_headers</code>: <code>Bearer $AGENT_SECRET</code></span></div>
<div class="arrow-h" style="width:40px"></div>
<div class="box green" style="flex:0.8"><b>⑥ your agent</b><span class="small">timeout 900 s</span></div>
</div>
</div>

:::: grid 3
::: card
#### Missing inputs

{.small}
Required params the model couldn't fill from the conversation → a follow-up form (`needs_info`) before your agent is called. The model is told not to invent them.
:::

::: card
#### Result contract

{.small}
The response must use exact `TASK_STATE_*` values and one final text part. The base class guarantees this if you just `return` a dict.
:::

::: card
#### Changing your card?

{.small}
Restart the agent (re-registers), then refresh discovery or restart the client-agent. Cards are cached.
:::
::::

---

## Four ways onto the platform {eyebrow="Where to run it"}

{.sm .wrap-code widths="250px|420px|"}
| Mode | How | Registered URL / notes |
|---|---|---|
| **Docker, internal network**<br><span class="small">(recommended)</span> | `make up` in the agent dir. It joins `prometheus_platform_agent-network` via `docker-compose.net_internal.yml`. | `http://<service>:8000`. `REGISTRY_URL`, `REDIS_URL`, and `JWKS_URL` resolve by service name. Start the platform first. {.hl} |
| **Docker, external port** | `EXTERNAL_AGENT_HOST=prometheus.host.internal EXTERNAL_AGENT_PORT=8042 make up` | `EXTERNAL_AGENT_URL=http://prometheus.host.internal:8042`. Point `REGISTRY_URL`/`REDIS_URL`/`JWKS_URL` at `prometheus.host.internal:8600/6379/8600`. |
| **Host Python**<br><span class="small">(fastest edit loop)</span> | `python agent.py` in a venv with `prometheus_api` installed | Set `REGISTRY_URL=http://localhost:8600`, `REDIS_URL=redis://localhost:6379`, `JWKS_URL=http://localhost:8600/.well-known/jwks.json`, `EXTERNAL_AGENT_URL=http://prometheus.host.internal:8000` |
| **In-tree** | Copy into `prometheus_core/platform/agents/<name>/`, then `make generate && make up` in `platform/` | Auto-included (one directory level). Uses the platform's `prometheus_api:local`. Copy `agents/synthesis-agent/docker-compose.yml` as the model. |

:::: grid 2
::: callout warn
After every platform `make up`/`make restart` the registry is empty: `docker compose -p <agent-folder> restart` to re-register (an unchanged container is left alone by a second `make up`). Stop your agent before `make down` in the platform, or the network cannot be removed.
:::

::: callout
Standalone curl testing without any platform: `EXTERNAL_AGENT_HOST=localhost EXTERNAL_AGENT_PORT=8000 make up-fg`, with `USER_IDENTITY_REQUIRED=false` in `.env`.
:::
::::

---

## Run the agent on the host, call the debug route {eyebrow="Running and testing locally"}

::: col
```bash {.sm}
cd hello-world
uv sync && source .venv/bin/activate
uv pip install -e \
  ~/prometheus/prometheus_core/sdk     # the SDK from your clone

AGENT_SECRET=dev AGENT_SECRET_REQUIRED=false \
USER_IDENTITY_REQUIRED=false PROMETHEUS_TASK_STORE=memory \
AGENT_PORT=8000 python agent.py    # DEEPLYNX_* from .env
# "Loaded agent card…"  "Starting HTTP server on 0.0.0.0:8000"
# registration retries, then "Continuing without registration"
```

```bash {.sm}
# debug shortcut: plain JSON in, result out
curl -s -X POST localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"params": {"input_data": "hi",
       "skill_id": "hello_world_analysis"},
       "conversation_id": "conv-1"}'
```

{.tiny}
The agent refuses to start without DeepLynx (`DEEPLYNX_ORG_ID`, `DEEPLYNX_PROJECT_ID`, and key + secret or `DEEPLYNX_JWT_TOKEN`); a `.env` in the folder is read. With `AGENT_SECRET_REQUIRED=true`, add `-H "Authorization: Bearer $AGENT_SECRET"` to every call except `/healthz` and the card routes.
:::

---

## A real A2A v1 request, and the errors you may see {eyebrow="Running and testing locally"}

```bash {.sm}
curl -s -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -H "A2A-Version: 1.0" \
  -d '{
  "jsonrpc": "2.0", "id": "1",
  "method": "SendMessage",
  "params": {
    "message": {
      "messageId": "msg-1",
      "role": "ROLE_USER",
      "contextId": "conv-123",
      "parts": [{"text": "{\"input_data\": \"hello world\"}"}],
      "metadata": {"skillId": "hello_world_analysis"}
    },
    "configuration": {"returnImmediately": false}
  }}' | python3 -m json.tool

# → result.task.status.state == "TASK_STATE_COMPLETED"
#   status.message.parts[0].text == "{\"status\": \"success\", …}"

# errors you may hit:
# -32601 Method not found     → you used v0.3 "message/send"
# -32009 version '0.3' …      → missing A2A-Version header
# -32603 No 'userToken' …     → USER_IDENTITY_REQUIRED=true
# -32004 Streaming not supported → card streaming:false
# HTTP 401                    → missing/wrong bearer
```

---

## Endpoints every agent serves {eyebrow="Built in"}

{.sm}
| Route | Auth | What |
|---|---|---|
| `POST /` | bearer | A2A JSON-RPC: `SendMessage`, `SendStreamingMessage`, `GetTask`, `CancelTask`… |
| `GET /healthz` | none | `{"ok": true, "status": "healthy", "timestamp": …}` |
| `GET /api/agent-card` | none | the raw card with extensions |
| `GET /.well-known/agent-card.json` | none | the strict v1 card (also `/.well-known/agent.json`) |
| `GET /.well-known/jwks.json` | none | public keys from this agent's env |
| `GET /api/artifacts/{conversation_id}` | bearer | the artifact catalog |
| `POST /api/chat` | bearer | the debug route (runs the executor in-process) |
| your `add_http_endpoint(…)` | bearer | custom routes, advertised under `endpoints` in the card |
| your `add_static_endpoint(…)` | bearer | static files, e.g. viewer plugin assets |

---

## Tests without a server {eyebrow="Built in"}

::: col
```python {.sm}
# tests/conftest.py provides fixtures
#   context:     MagicMock(spec=RequestContext)
#                context_id="test-conversation"
#   event_queue: AsyncMock(spec=EventQueue)
# and sets AGENT_SECRET, PROMETHEUS_TASK_STORE=memory

async def test_hello(context, event_queue):
    agent = HelloWorldAgent(agent_name="Hello World Agent")
    out = await agent._execute(
        {"input_data": "x"}, context, event_queue)
    assert out["status"] == "success"
    assert event_queue.enqueue_event.await_count >= 1
```

```bash {.sm}
uv run pytest && uv run ruff check .
```

{.small}
Mock `self.llm_client` in tests; never call a real LLM from the test suite. `test_build_app_loads_agent_card` builds the app without serving or registering, so a broken card fails here. PRs to `prometheus_core` also need 100% coverage of changed lines (codecov).
:::

---

# The helpers on `self` {.section num="C"}
Status, artifacts, user input, state, long-running work, and DeepLynx.

---

## Helpers for output: status, messages, artifacts {eyebrow="Reference"}

{.sm .wrap-code widths="420px|"}
| Helper | What it does |
|---|---|
| `send_status_update(context, eq, message=…)` | Transient progress line (WORKING). Live in the UI only with `streaming: true`. |
| `send_conversation_message(context, eq, message)` | A **durable** chat message (a JSON artifact of kind `conversation_message`) |
| `send_json_artifact(context, eq, payload, name=, json_type=, catalog_artifact=)` | An inline data artifact; `catalog_artifact=True` also registers it in the catalog. Returns the id. |
| `send_text_artifact(context, eq, text, name=, append=, last_chunk=)` | Streaming text chunks (not cataloged) |
| `send_artifact_reference(context, eq, name=, description=, uri=, mime_type=, tags=)` | A file by URI (`http(s)://`, `file://`…), registered in the catalog |
| `send_deeplynx_artifact(context, eq, file_path=, name=, description=, storage_config=, mime_type=, json_type=, tags=, metadata=)` | Upload to DeepLynx → `deeplynx://…/items/N`, register and emit. Reads the whole file into memory. {.hl} |
| `await get_artifact_file_path(artifact_id, context=, artifacts=)` | Any artifact → a local `Path`: downloads `deeplynx://`/http, materializes inline JSON/text {.hl} |
| `resolve_artifact_reference(conv_id, id)` · `resolve_artifact_by_name` · `list_artifact_references` | Catalog lookups (Valkey `artifacts:conv:{id}:*`, 7-day TTL) |

---

## Helpers for input, state, long work, and LLMs {eyebrow="Reference"}

{.sm .wrap-code widths="420px|"}
| Helper | What it does |
|---|---|
| `send_input_required(context, eq, missing_inputs=[MissingInput(…)], hint=)` | Pause and ask the user (INPUT_REQUIRED); `return {}` afterwards |
| `get_input_sources(context)` | Who supplied each param: `model`, `user` or `context` (the answers themselves are in `params`) |
| `execution_record_id` | DeepLynx execution record of this call (inside `_execute`) |
| `load_context_state(ctx_id)` / `save_context_state(ctx_id, state)` | Per-agent, per-conversation JSON state in Valkey (24 h TTL) |
| `declare_long_running(context, eq, estimate_seconds=, message=)` | The orchestrator detaches the turn; the result is delivered later over SSE |
| `await run_worker(PrometheusWorker(...), context, eq)` | Run blocking code on a thread and stream its progress |
| `llm_client(context, config=…)` | `AsyncLLMClient` (next section) |
| `current_user_id()` · `identity_metadata()` · `get_credential(resource)` | Who is asking; forward the token downstream; per-user secrets |

---

## Produce and consume artifacts {eyebrow="Artifacts in practice"}

::: col
```python {.sm}
# produce: from gmsh_agent/agent.py
from prometheus_api.storage_client import ConnectionConfig
artifact = await self.send_deeplynx_artifact(
    context=context, event_queue=event_queue,
    file_path=result.exodus_path,
    name=result.exodus_path.name,
    description="Gmsh first-order tetrahedral mesh…",
    storage_config=ConnectionConfig.from_env(),
    mime_type="application/x-exodus",
    json_type="prometheus.mesh.exodus.v1",
    tags=["mesh", "gmsh", "exodus"],
    metadata={"tetrahedron_count": n})
return {"status": "success",
        "artifact_id": artifact.artifact_id, …}
```

```python {.sm}
# consume: card property uses "x_artifact_ref": "single"
path = await self.get_artifact_file_path(
    params["step_artifact_id"], context=context,
    artifacts=params.get("artifacts"))
# → /tmp/prometheus-artifact-cache/<id>/…-part.step
```
:::

---

## Which viewer renders it? (backend `render_hint`) {eyebrow="Artifacts in practice"}

::: col
| Your artifact has… | Viewer |
|---|---|
| `application/x-exodus`, STL MIME, `.exo` `.e` `.stl` | VTK.js mesh (with timesteps) |
| `model/ifc`, `.ifc` | IFC / BIM viewer |
| `image/*`, `.png` `.svg` | image |
| `application/pdf` | PDF |
| `text/x-mermaid` | Mermaid diagram |
| `text/markdown`, `text/plain` | report |
| `application/json` / inline `json_body` | JSON tree |
| csv, zip, ipynb, STEP, octet-stream… | download |
| `json_type` `prometheus.thermal_analysis.result.v1` | thermal (custom) |

{.small}
Priority: `json_type` → MIME → tags → extension. **Set `mime_type`.** `file://` URIs only render if the path exists *inside the backend container*, so prefer DeepLynx or inline JSON.
:::

---

## Plan approval and input-required {eyebrow="Asking the user"}

:::: col
::: card
#### Before you run: `"requires_approval": true`

{.small}
Declarative, in the card (or in a workflow's `metadata`). The orchestrator returns `plan_ready`; the UI shows the plan with Approve/Reject; your agent is called only after approval. One Approve covers every approval-gated call in that step (usually just one); if the user types text instead of clicking, the calls are dropped and the model re-plans. *Planned: multi-agent workflows that show the whole plan up front, to accept or change.*
:::

::: card
#### While you run: `send_input_required`

{.small}
Your task ends in `TASK_STATE_INPUT_REQUIRED`. Inputs with `resolvable_from_context=True` are filled from the call's arguments or earlier answers; otherwise the user gets a form (`options` → dropdown, your `hint` as the message), and you are **resumed** with the same `contextId`/`taskId`, the answers merged into `params` with the original arguments. A typed reply instead of the form abandons the task; the model may call you again.
:::

::: callout warn
Your Python variables do **not** survive between the two calls, but your arguments do: they come back in `params`. Anything else (intermediate results) goes in `save_context_state`. Never ask for secrets this way. `request_user_approval(…)`, mentioned in some docs, does not exist.
:::
::::

---

## Input-required in code {eyebrow="Asking the user"}

```python {.sm}
from prometheus_api.agent import MissingInput

async def _execute(self, params, context, event_queue):
    # resumed call: the original arguments + the answers
    if "confirm" not in params:
        await self.send_input_required(
            context, event_queue,
            missing_inputs=[MissingInput(
                name="confirm",
                description="Launch the 2 h run?",
                user_prompt="Proceed? (yes/no)",
                type="boolean", required=True)],
            hint="Confirm before the expensive job.")
        return {}

    if not params["confirm"]:
        return {"status": "cancelled"}
    who = self.get_input_sources(context)   # {"confirm": "user", …}
    …
```

---

## Never block the event loop {eyebrow="Long-running work"}

::: grid 2 gap=26px
{.body}
The base class sends a heartbeat every `PROMETHEUS_HEARTBEAT_INTERVAL` (15 s) **from the same event loop**. A synchronous call such as `time.sleep`, a sync SDK, or a solver freezes the heartbeat and the whole server.

{.sm}
| Situation | Use |
|---|---|
| async I/O (httpx, LLM) | `await` it directly |
| a blocking call, no progress needed | `await asyncio.to_thread(fn, …)` |
| blocking with progress updates | `PrometheusWorker` + `self.run_worker` |
| minutes to hours | + `declare_long_running` + `streaming: true` |
| CPU-bound pure Python | a process pool (the GIL) |

{.small}
Reference: `platform/agents/debug-agents/thread-pattern-agent` (skills `run_blocking_task`, `run_background_task`).

|||

```python {.xs}
from prometheus_api.agent import PrometheusWorker

class SolveWorker(PrometheusWorker):
    def __init__(self, case):
        super().__init__()
        self.case = case

    def run(self):                  # sync, on a thread
        for step in range(100):
            if self.cancelled:
                return {"status": "cancelled"}
            solve_step(self.case, step)
            if step % 10 == 0:
                self.emit_status_update(f"Step {step}/100")
        return {"status": "success"}

# inside _execute
await self.declare_long_running(
    context, event_queue, estimate_seconds=1800,
    message="Solving; I'll report back.")
result = await self.run_worker(
    SolveWorker(params), context, event_queue)
return result
```
:::

---

# LLMClient {.section num="D"}
The one LLM interface in the base image: flavors in code, profiles in deployment, tool calling per call.

---

## The API {eyebrow="prometheus_api.llm_client"}

:::: cols 1.1fr 1fr gap=26px
{.sm .wrap-code}
| Call | Meaning |
|---|---|
| `LLMClient()` / `AsyncLLMClient()` | sync or async, used as a context manager; config defaults to `LLMConfig.from_env()` |
| `self.llm_client(context, config=…)` | the async client inside an agent (adds tracing tags) |
| `chat(text_or_messages, model=None, *, tools=, tool_choice=, **kw)` | `model=None` → flavor `default`; `kw` such as `max_tokens` and `temperature` pass through |
| `small()` `medium()` `large()` `vision()` | = `chat(model="<flavor>")` |
| `embed(texts)` / `embedding()` | flavor `embedding` → `EmbeddingResponse` |
| `list_models()`, `resolve_model(alias)` | what the active profile offers |

{.small}
`ChatResponse`: `.text`, `.model_alias`, `.provider_model`, `.usage`, `.tool_calls`, `.finish_reason`, `.raw`. There is **no streaming**: `stream=True` raises `LLMClientError`.

|||

#### The pattern {.acc}

```python {.xs}
from prometheus_api.llm_client import LLMClientError

try:
    async with self.llm_client(context) as llm:
        r = await llm.medium(prompt, max_tokens=1800,
                             temperature=0.2)
except LLMClientError as e:
    return {"status": "error", "error": str(e)}
return {"summary": r.text,
        "model": r.provider_model or r.model_alias}
```

{.xs}
| Error (all `LLMClientError`) | Means |
|---|---|
| `LLMConfigError` | unknown `LLM_CONFIG_PROFILE`, bad YAML; lists the profiles |
| `LLMEndpointUnavailableError` | endpoint unreachable; names URL, alias, profile |
| `LLMProviderError` | HTTP ≥ 400 from the provider: `.status_code`, `.detail` |

::: callout
Credentials come only from the environment (`LLM_API_KEY`) or `config=`, never from the A2A message.
:::
::::

---

## Code picks a flavor; deployment picks the model {eyebrow="Flavors and profiles"}

::: grid 2 gap=26px
{.sm}
| Flavor | Intended use |
|---|---|
| `default` | `llm(...)` / `chat(model=None)` |
| `small` | fast, low-cost: titles, classification |
| `medium` | general analysis |
| `large` | deeper reasoning |
| `vision` | multimodal (images in messages) |
| `embedding` | vectors |

{.small}
Six flavors, a fixed contract. There is no "fast/smart" naming and no `MODEL_NAME` (dropped from the template in commit `829ec42`; prometheus_api 0.11.0 removed `LLM_DEFAULT_MODEL`). Tool calling is a per-call option, not a seventh flavor.

|||

#### `LLMConfig.from_env()` resolution {.acc}

<div class="dg">
<div class="box violet"><b><code>LLM_CONFIG_FILE</code></b> set?<span class="small">→ your YAML (path inside the container, <code>~</code> expanded)</span></div>
<div class="arrow-v" style="height:28px"><span>else</span></div>
<div class="box violet"><b><code>LLM_CONFIG_PROFILE</code></b> set?<span class="small">→ <code>sdk/prometheus_api/llm_configs/&lt;name&gt;.yaml</code></span></div>
<div class="arrow-v" style="height:28px"><span>else</span></div>
<div class="box violet"><b><code>registry</code></b><span class="small">an LLM proxy at <code>REGISTRY_URL</code>: <b>not supported</b> on the platform (the backend is no LLM proxy). Always set a profile.</span></div>
</div>

{.xs}
- Profiles: `anthropic`, `openai`, `genesis`, `ollama`, `amsc`, `anl_asksage`, `inl_hpc`, `inl_litellm`; `list_llm_config_profiles()` lists them.
- A flavor the profile doesn't define raises `LLMAliasError`.
- A `.env` in the working directory **overrides** the process env for everything `LLMConfig` reads.
:::

---

## Option A: a custom YAML for one agent {eyebrow="Adding configurations"}

::: card tag="A · custom YAML (per agent)"
```yaml {.sm}
# llm_config.yaml (add to .gitignore)
model_list:
  - model_name: medium
    litellm_params:
      model: openai/claude-sonnet-5-awsgov
      api_base: https://litellm.inl.gov/v1
      api_key: os.environ/LLM_API_KEY
  - model_name: vision
    litellm_params:
      model: openai/claude-opus-4-8-awsgov
      api_base: https://litellm.inl.gov/v1
      api_key: os.environ/LLM_API_KEY
```

{.small}
Start from `sdk/llm_config.example.yaml`. Mount it into the container and set `LLM_CONFIG_FILE=/app/llm_config.yaml`. `LLM_API_KEY` is already forwarded; any other key must be added to compose `environment:`.
:::

---

## Option B: a new installed profile {eyebrow="Adding configurations"}

:::: grid 2 gap=24px
::: card tag="B · new installed profile"
{.sm}
1. Add `sdk/prometheus_api/llm_configs/<name>.yaml` with **all six** flavors
2. Nothing to register: every `*.yaml` there is a profile (`list_llm_config_profiles()`)
3. Update `tests/test_llm_configs.py`, `specs/005`, README/ENV_SETUP
4. Bump the version, and note it in `AGENT_MIGRATIONS.md`
5. `make up` in `platform/` rebuilds `prometheus_api:local` with it
6. Select it with `LLM_CONFIG_PROFILE=<name>`

{.small}
A PR to `prometheus_core` (`sdk/`, base `devel`).
:::

::: card tag="Keys and model strings"
{.small}
The template compose forwards `LLM_API_KEY` (every profile's key) and `EMBEDDING_API_KEY` from your `.env`. A key of your own needs an `environment:` line.

{.small}
Model strings follow LiteLLM: `openai/…` + `api_base` for OpenAI-compatible gateways, `hosted_vllm/…`, `anthropic/…`.
:::
::::

---

## Tool calling with LLMClient {eyebrow="New in v0.13.0"}

:::: grid 2 gap=26px
```python {.xs}
from pydantic import BaseModel
from prometheus_api.llm_client import (
    ToolDefinition, assistant_message, tool_result_message)

class LookupArgs(BaseModel):
    material: str

LOOKUP = ToolDefinition.from_pydantic(
    "lookup_material", LookupArgs,
    description="Look up density and conductivity")
MAX_TOOL_TURNS = 8

async with self.llm_client(context, config=cfg) as llm:
    history = [{"role": "user", "content": question}]
    for _ in range(MAX_TOOL_TURNS):          # always bounded
        r = await llm.medium(history, tools=[LOOKUP],
                             tool_choice="auto")
        if not r.tool_calls:                   # the stop condition
            break
        history.append(assistant_message(r))
        for call in r.tool_calls:              # call.name, .arguments
            history.append(tool_result_message(
                call, lookup(**call.arguments)))
answer = r.text
```

|||

{.sm}
- `ToolDefinition(name, description, parameters)` or `.from_pydantic(...)`
- `response.tool_calls` → `ToolCall(id, name, arguments: dict, arguments_error)`
- `assistant_message(r)` + `tool_result_message(call, result)` replay the turn
- Force one tool: `await acall_tool(llm, msgs, tool=LOOKUP)`; strict check: `require_tool_calls(r)`
- Stop on `not r.tool_calls`, never on `finish_reason == "stop"`. **Bound the loop.**
- `tool_choice` without `tools` → `LLMToolCallError`. There is no package-owned loop and no streaming deltas.
- Structured output = force a single tool whose schema is your output model.

::: callout warn
Needs base image **≥ v0.13.0**: `prometheus_api:local` from your clone has it; the client-agent itself runs on this API.
:::
::::

---

# Workflows and worked examples {.section num="E"}
Chaining your skill with others, and two real agents to borrow from.

---

## `workflows/*.yaml` chain skills across agents {eyebrow="Agent-owned workflows"}

```yaml {.sm}
id: neutron.step_to_checked_mesh     # globally unique; prefix it
name: STEP to checked mesh
version: "1.0.0"
description: Mesh a STEP file, then report mesh quality.  # required!
inputs:
  required: [step_artifact_id]
execution: {mode: sequential, max_concurrency: 1, on_error: fail_fast}
steps:
  - id: mesh
    skill_id: geometry_meshing              # another team's agent
    params:
      step_artifact_id: {from: input.step_artifact_id}
    outputs:
      - {to_context: mesh_id, from: artifact_id}
  - id: check
    skill_id: neutron_mesh_quality_report   # yours
    depends_on: [mesh]
    is_final: true
    params:
      mesh_artifact_id: {from: context.mesh_id}
outputs: {final: {from: step.check.result}}
metadata: {requires_approval: false, estimated_duration_seconds: 90,
           owner: neutron-mesh-qa-agent}
ui: {category: Meshing, display_name: STEP → checked mesh,
     summary: Mesh and quality-check a STEP file}
```

---

## How workflows are found, started, and bound {eyebrow="Agent-owned workflows"}

::: col
{.sm}
- Files next to `agent_card.json` are merged into the card at startup (`AGENT_WORKFLOWS` overrides the directory). The template ships `example_workflow.yaml.example`.
- The client-agent compiles them at discovery. Each becomes an orchestrator tool (`workflow_<id slug>`, parameters = `inputs.required`) **and** a slash command: `/neutron.step_to_checked_mesh` or `/step_to_checked_mesh`.
- **Bindings**: `from: input.<x>`, `from: step.<id>.result`, `from: context.<key>`, `literal: <v>`, `optional: true`. `conversation_id` and `artifacts` are added automatically.
- `mode`: `sequential`, `parallel`, or `dag` (use `depends_on`); `on_error`: `fail_fast` or `continue_with_partial`.
- Before starting, the client-agent calls the owning agent's `/healthz`.
- If a step pauses for input, the whole template **re-runs** with the answers merged into its inputs: bind them as optional inputs (`{from: input.x_column, optional: true}`).

{.small}
Full schema: `platform/docs/docs/workflow-templates.md`. Examples: `platform/agents/debug-agents/artifact-debug-agent/workflows/patriotic_usa_png.yaml` and `platform/agents/client-agent/workflows/comprehensive_material_analysis.yaml` (DAG, approval).
:::

---

## `gmsh_agent` (main): a deterministic tool wrapper {eyebrow="Worked example 1"}

<div class="dg">
<div class="row" style="align-items:stretch; gap:0">
<div class="box sky" style="flex:1"><b>① merge + validate inputs</b><span class="small">late answers already in params; check <code>element_size</code></span></div>
<div class="arrow-h" style="width:40px"></div>
<div class="box sky" style="flex:1"><b>② resolve the STEP artifact</b><span class="small"><code>get_artifact_file_path()</code> → local <code>.step</code></span></div>
<div class="arrow-h" style="width:40px"></div>
<div class="box orange" style="flex:1"><b>③ MeshingWorker</b><span class="small">a <code>PrometheusWorker</code>: Gmsh on a thread, under a lock, with status updates</span></div>
</div>
<div class="arrow-v at-right" style="height:30px"></div>
<div class="row" style="align-items:stretch; gap:0">
<div class="box green" style="flex:1"><b>⑥ return</b><span class="small">summary, metrics, <code>artifact_id</code>, <code>new_artifacts</code></span></div>
<div class="arrow-h left" style="width:40px"></div>
<div class="box green" style="flex:1"><b>⑤ publish</b><span class="small"><code>send_deeplynx_artifact()</code>, MIME <code>application/x-exodus</code></span></div>
<div class="arrow-h left" style="width:40px"></div>
<div class="box sky" style="flex:1"><b>④ meshio → Exodus</b><span class="small">keep tetrahedra only</span></div>
</div>
</div>

:::: grid 3
::: card
#### Card

{.small}
One skill, `geometry_meshing`. `step_artifact_id` with `x_artifact_ref: "single"` + `x_artifact_mime`. Only that field is required; `element_size` is optional with a documented default.
:::

::: card
#### Dockerfile

{.small}
Installs Gmsh per architecture (the Debian `python3-gmsh` on arm64, the PyPI wheel on x86_64), then `python -c "import gmsh, meshio, netCDF4"` at build time to fail fast.
:::

::: card
#### Tests

{.small}
A card-contract test, a heartbeat-while-blocking test, and mesh-size inference tests. Copy this shape for your agent.
:::
::::

{.small}
The pattern for any "wrap an existing code" agent: **artifact in → worker thread → artifact out → small JSON summary**.

---

## `agentic-hex-meshing`: an LLM driving a sandboxed kernel {eyebrow="Worked example 2"}

::: grid 2 gap=26px
<div class="dg">
<div class="row" style="gap:0; align-items:stretch">
<div class="box orange" style="flex:1"><b>meshing agent</b><span class="small">skill <code>agentic_hex_meshing</code>, <code>streaming: true</code>, 1800 s</span></div>
<div class="arrow-h" style="width:70px"><span>MCP</span></div>
<div class="box teal" style="flex:1"><b>meshing-sandbox</b><span class="small">Jupyter kernel + gmsh, pyvista…</span><span class="mono">internal: true network</span></div>
</div>
<div class="arrow-v"><span>vision flavor</span></div>
<div class="box violet"><b>LLM tool loop</b><span class="small">tools: <code>run_python(code, summary)</code> and <code>submit_final_mesh(basename, summary)</code></span></div>
</div>

<ul class="b xs" style="margin-top:10px">
<li>The LLM iterates decompose → constrain → generate → verify, and sees rendered PNGs (only the newest 3 are kept).</li>
<li>Every cell result ends with <code>[Budget: N step(s) left…]</code>. Limits: 40 iterations, 3600 s, 660 s per cell.</li>
<li>The <code>summary</code> argument doubles as the live status update.</li>
<li>The best mesh is scored by hex fraction × min scaled Jacobian.</li>
<li>Outputs to DeepLynx: Exodus, a PNG preview, and <b><code>notebook.ipynb</code> as provenance</b>.</li>
</ul>

|||

#### Patterns worth copying {.acc}

{.sm}
- One code-exec tool plus one submit tool
- Explicit step and time budgets shown to the model
- Images fed back for vision checks
- Geometry facts as **helper functions** inside the sandbox (`face_census()`, `void_report()`…) rather than a precomputed brief. See `DESIGN.md`.
- Restart and re-upload on kernel death or repeated timeouts
- The sandbox on an **egress-free** network; the agent is on both networks

{.small}
Branch `agentic-hex-meshing` of `genesis/gmsh_agent` on github.inl.gov (PR #1): `meshing_loop.py`, `sandbox_client.py`, `DESIGN.md`.
:::

---

## Ship an agent the orchestrator will call {eyebrow="Checklist"}

:::: grid 2 gap=30px
{.sm .check}
- ☐ Unique card `name` and skill `id`s, prefixed with the team name
- ☐ Skill `description` + `usage_notes` say what, when, and when not
- ☐ Every `inputSchema` property described; minimal `required`
- ☐ File inputs use `x_artifact_ref`; chained values use `x_input_source: runtime`
- ☐ `"streaming": true` if you send status updates
- ☐ LLM through `self.llm_client(context)`; the flavor that fits each call; `LLMClientError` handled
- ☐ Nothing blocks the event loop
- ☐ Outputs as artifacts with a correct `mime_type`; return `artifact_id`s
- ☐ Errors: return an error dict for user problems; raise for infrastructure
- ☐ `pyproject.toml` lists your deps only, `uv.lock` committed; `COPY` lines for new modules
- ☐ `uv run pytest` + `uv run ruff check .` pass
- ☐ Registered (`/v1/agents`), visible in `/agents`, routed from a natural-language request

|||

#### Read next {.acc}

<table class="t sm">
<tr><td><code>sdk/docs/agent/GUIDE.md</code></td><td>the complete guide</td></tr>
<tr><td><code>…/docs/agent/QUICK_START.md</code></td><td>the minimal agent</td></tr>
<tr><td><code>…/docs/ENV_SETUP.md</code></td><td>every env var, LLM config</td></tr>
<tr><td><code>…/docs/agent/LLM_CLIENT_MIGRATION.md</code></td><td>tool loops, from vendor SDKs</td></tr>
<tr><td><code>…/docs/agent/MULTI_USER.md</code></td><td>identity, credentials</td></tr>
<tr><td><code>…/examples/agent_patterns.py</code>, <code>llm_tool_calling_usage.py</code></td><td>runnable patterns</td></tr>
<tr><td><code>platform/agents/synthesis-agent/</code></td><td>about 100 lines, the LLM pattern</td></tr>
<tr><td><code>platform/agents/debug-agents/*</code></td><td>every helper in use</td></tr>
</table>

::: callout good
Next: **end-to-end dry run** (3:30 pm). You do all of this yourself, with a mentor nearby.
:::
::::
