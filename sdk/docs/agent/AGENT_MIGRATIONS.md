# Prometheus Agent Migration Guide

This document is the running migration log for `PrometheusAgent` behavior
changes. When a base-agent change requires downstream agent updates, add a short
section here under the relevant version heading with migration steps and a
minimal code example.

## 0.16.0

### Optional: Load Prompts Through the Agent Class

`PrometheusAgent` has a `prompts_dir` class attribute and a `load_prompt` classmethod
(refs #67). No agent has to change. Agents with their own `PROMPTS_DIR` constant and
loader can drop both:

```python
# Before
PROMPTS_DIR = Path(__file__).with_name("prompts")


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


ANALYSIS_PROMPT = _load_prompt("analysis.txt")

# After, below the class definition
ANALYSIS_PROMPT = MyAgent.load_prompt("analysis.txt")
```

Unlike the module-level `prometheus_api.load_prompt`, which looks next to `__main__`, the
classmethod looks next to the agent's own file, so prompts also load when tests import
the agent module.

## 0.15.0

### Register with the Platform Backend; the Platform No Longer Runs LiteLLM

The platform's `litellm` and `litellm-db` containers were removed. The backend now hosts the
agent registry and A2A gateway on the same paths LiteLLM served (`/v1/agents` and
`/a2a/{agent_name}`), so the SDK's registry client is unchanged. Only agent deployment
configuration has to move. Registrations are stored in Valkey under `prometheus:agent-registry`
rather than in `litellm-db`. This applies to agents deployed on the Prometheus platform; agents
registering with their own LiteLLM proxy are unaffected.

Migration steps:

1. Set `REGISTRY_URL=http://backend:8000`. The SDK default is still `http://litellm:4000`, so
   leaving it unset now fails registration.
2. Set `LITELLM_MASTER_KEY` to the value of `AGENT_SECRET`. The SDK still sends that variable
   as its registry bearer token, and the backend checks it against `AGENT_SECRET`. The separate
   LiteLLM master key is gone.
3. Set `LLM_CONFIG_PROFILE` explicitly to a profile that calls a provider directly, such as
   `openai`, `anthropic`, or `inl_hpc`. The `registry` profile does not work on the platform:
   it sends LLM calls to `REGISTRY_URL`, which now points at the agent registry rather than an
   LLM proxy. Platform compose files refuse to start when `LLM_CONFIG_PROFILE` is unset.
4. In `depends_on`, wait for `backend` instead of `litellm`.
5. Use `make clear-agent-registry` instead of `make clear-litellm-db`. Every platform launch
   target still clears the registry first.
6. Delete the leftover `<project>_litellm-db-data` Docker volume from existing deployments.

```yaml
services:
  my-agent:
    environment:
      AGENT_SECRET: ${AGENT_SECRET}
      REGISTRY_URL: ${REGISTRY_URL:-http://backend:8000}
      LLM_CONFIG_PROFILE: ${LLM_CONFIG_PROFILE:?set LLM_CONFIG_PROFILE in .env}
      # The SDK sends this as its registry token; the backend registry checks AGENT_SECRET.
      LITELLM_MASTER_KEY: ${AGENT_SECRET}
    depends_on:
      backend:
        condition: service_healthy
```

### Configure DeepLynx for Automatic Execution Records

Before `_execute(...)`, the standard `PrometheusAgent` executor now creates a mandatory
DeepLynx execution item containing the agent, task, context, verified user, and effective
parameters. Parameters are recursively redacted and stored as JSON in the scalar
`parameters_json` property to avoid DeepLynx's properties-depth limit. Decode them with
`json.loads(...)`. Credential, configuration, data-source, or item-creation failures stop the
execution before subclass work begins.

Migration steps:

1. Ensure the configured credential broker can provide a `deeplynx` credential. When using the
   environment broker, set the existing DeepLynx authentication, organization, and project
   variables.
2. Set `DEEPLYNX_DATA_SOURCE_ID` or configure a default data source for the target project.
3. Read the item ID from `self.execution_record_id` during `_execute(...)` only. This
   request-scoped property is concurrency-safe and otherwise returns `None`.
4. Sensitive values in the stored parameter snapshot are recursively redacted using the existing
   security helper while their keys are retained. Parameters passed to `_execute(...)` remain
   unchanged.

```python
class AnalysisAgent(PrometheusAgent):
    async def _execute(self, params, context, event_queue):
        execution_item_id = self.execution_record_id
        return {"status": "success", "execution_item_id": execution_item_id}
```

## 0.14.1

### INPUT_REQUIRED Answers Arrive in `params`

`PrometheusAgent.get_provided_inputs(...)` was removed, and the client-agent no longer sends a
`provided_inputs` data part. When a task resumes after `INPUT_REQUIRED`, the client-agent
re-sends **every** original argument with the user's answers (and any values it filled in
from the conversation) merged into `params`. Each message also carries `inputSources`
metadata saying who supplied each parameter. Read it with the new
`PrometheusAgent.get_input_sources(context)`, which returns `"model"`, `"user"` or `"context"`
per name.

Migration steps:

1. Replace `self.get_provided_inputs(context)` with plain `params` reads.
2. Delete `load_context_state` / `save_context_state` calls that only kept a copy of earlier
   arguments for the resume. Keep state only for what `params` can't carry, such as the
   phase of a multi-round form or answers from earlier rounds.
3. If your agent expects a value nested (e.g. `params["context"]["temperature_c"]`), also
   accept it at the top level: a form answer arrives as `params["temperature_c"]`.
4. Use `self.get_input_sources(context)` when the agent's output should say who chose a
   value.
5. Build on a client-agent and base image that include this change. With an older
   client-agent, answers to `INPUT_REQUIRED` won't reach the agent.

```python
# Before
state = self.load_context_state(str(context.context_id))
resolved = {**state.get("resolved", {}), **self.get_provided_inputs(context)}
temperature_c = resolved.get("temperature_c")

# After
temperature_c = params.get("temperature_c")
if temperature_c is None:
    await self.send_input_required(context=context, event_queue=event_queue,
                                   missing_inputs=[...], hint="...")
    return {}
```

### `MissingInput.sensitive` Removed

The `sensitive` field was removed from `MissingInput`, and the client-agent now rejects an
`INPUT_REQUIRED` descriptor that carries it. Delete `sensitive=...` from your
`MissingInput(...)` calls. Every answer is merged into `params` and kept with the
conversation, so don't ask the user for a secret through `INPUT_REQUIRED`.

## 0.14.0

### LLM Credentials No Longer Come from A2A Requests

`LLMClient.from_a2a_context(...)`, `AsyncLLMClient.from_a2a_context(...)` and
`extract_llm_api_key_from_a2a_context(...)` were removed. They read an `llm_api_key` from
any structured A2A data part (top-level or under `provided_inputs`) and used it as the
LLM credential. Nothing in the platform sent one, but the path let a credential travel on
the parameter channel. `PrometheusAgent.llm_client(context)` keeps its signature and now
takes credentials only from `config` or the environment. A request-independent
credential provider will be designed separately.

Migration steps:

1. Replace `AsyncLLMClient.from_a2a_context(context, ...)` with `AsyncLLMClient(...)`,
   and `LLMClient.from_a2a_context(...)` with `LLMClient(...)`. Keep passing `config=`
   and `app_name=`.
2. Drop imports of `extract_llm_api_key_from_a2a_context` from `prometheus_api.llm_client`.
3. Do not ask the user for LLM keys with `INPUT_REQUIRED`, and do not send them in A2A
   messages. A key sent that way is now ignored.
4. Inside a `PrometheusAgent`, keep using `self.llm_client(context)`; no change needed.

```python
config = LLMConfig.from_env()
if config.proxy_url:
    config = config.with_api_key(os.getenv("LITELLM_MASTER_KEY"))
async with AsyncLLMClient(config=config, app_name="My Agent") as llm:
    response = await llm.medium(prompt)
```

### The Health Endpoint Moved from `/health` to `/healthz`

`PrometheusAgent.build_app()` now serves its health check at `/healthz`, matching the
platform's backend and nginx. The old `/health` route was removed, with no alias: it now
falls through to the auth middleware and answers 401 (or 404 with auth disabled).

Migration steps:

1. Point every container healthcheck, probe, and monitor at `/healthz`.
2. Build agents on a base image that includes this change. A healthcheck probing
   `/healthz` against an older image fails.

```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"]
```

## 0.13.0

### Use the Built-in LLM Tool-Calling Helpers

`LLMClient.chat(...)` and `AsyncLLMClient.chat(...)` now accept keyword-only `tools`
and `tool_choice`, and `ChatResponse` exposes decoded `tool_calls` and `finish_reason`.
Existing chat calls keep working, with two exceptions: `tool_choice` without tools raises
`LLMToolCallError`, and a truthy `stream` raises `LLMClientError`. Both raise before any
backend is contacted. Agents that hand-rolled tool-call parsing against `ChatResponse.raw`
should migrate to the package helpers.

Migration steps:

1. Follow the [Tool Calling](LLM_CLIENT_MIGRATION.md#tool-calling) section of the LLM
   client migration guide to replace local parsers with `response.tool_calls`,
   `assistant_message(...)`, `tool_result_message(...)`, and `require_tool_calls(...)`.
2. Terminate multi-turn loops on `not response.tool_calls`, never on
   `finish_reason == "stop"`.
3. Bound the number of turns in every multi-turn loop.
4. Do not pass `tool_choice` without tools; it now raises `LLMToolCallError`.

```python
async with self.llm_client(context) as llm:
    response = await llm.medium(history, tools=TOOLS, tool_choice="auto")
    history.append(assistant_message(response))
    for call in response.tool_calls:
        history.append(tool_result_message(call, run_tool(call)))
```

## 0.12.1

### Platform Backend Is Now the Recommended JWKS Host

No code change in `prometheus_api` itself — this is a guidance update
following new capability on the platform side (`prometheus_platform`'s admin
UI, Admin > Signing Keys and Admin > Identity Providers). Recording it here
because it changes the *recommended* value of `JWKS_URL` for every agent,
including third-party ones.

The platform backend can now generate, activate, and retire RS256 signing
keys through Postgres instead of a hand-managed `USER_IDENTITY_PRIVATE_KEY`
env var, and serves its own `GET /.well-known/jwks.json` built from that
store. Point `JWKS_URL` at the **platform backend**, not at an individual
agent's own JWKS endpoint (every `PrometheusAgent` still serves one, per
`identity.py::get_jwks_document()`, but it only reflects that one agent's own
static env vars and can't see a DB-driven rotation):

```bash
# Every agent's .env, including third-party -- was previously pointed at
# some agent's own host; point it at the platform backend now.
JWKS_URL=https://<platform-backend-host>/.well-known/jwks.json
```

Migration steps:

1. If any agent currently sets `JWKS_URL` to a peer agent's host, change it
   to the platform backend's host instead.
2. If any agent currently sets only `USER_IDENTITY_PUBLIC_KEY` (static value,
   no `JWKS_URL`), consider switching to `JWKS_URL` — it's the only setup
   that survives a key rotation done through the admin UI with no further
   agent-side change.
3. No action needed for a platform still running purely on
   `USER_IDENTITY_PRIVATE_KEY`/`_PUBLIC_KEY` env vars with no admin-db (that
   path is unchanged and still fully supported as a bootstrap fallback).

See [IDENTITY_KEY_MANAGEMENT.md](./IDENTITY_KEY_MANAGEMENT.md) (updated:
"Option B", "Key rotation") for the full picture, and
`platform/docs/docs/dev-docs/encryption-and-keys.md` for how this
fits into the platform's other secrets.

## 0.12.0

### HS256 Identity Tokens Removed — RS256 Only

`prometheus_api.agent.identity` no longer supports HS256 (symmetric-secret)
signing for the multi-user identity JWT. Signing is **RS256 only**: the platform
backend mints with `USER_IDENTITY_PRIVATE_KEY`; every agent verifies with
`USER_IDENTITY_PUBLIC_KEY` or `JWKS_URL`. `USER_IDENTITY_SECRET` and
`USER_IDENTITY_ALG` are no longer read anywhere — setting them has no effect.

This closes a real weakness: under HS256 every agent held the same secret used to
*mint* tokens, so a compromised or careless agent deployment could forge a token
for any user. Under RS256, only the backend can forge; every agent (including
third-party ones) holds only a verification key.

Migration steps:

1. If you were running `USER_IDENTITY_ALG=HS256` + `USER_IDENTITY_SECRET`,
   generate an RSA keypair instead:
   ```bash
   prometheus-identity-keygen --out-dir ./keys
   # or: openssl genrsa -out identity_private.pem 4096 && \
   #     openssl rsa -in identity_private.pem -pubout -out identity_public.pem
   ```
2. Set `USER_IDENTITY_PRIVATE_KEY` on the platform backend only.
3. Set `USER_IDENTITY_PUBLIC_KEY` (or `JWKS_URL`) on every agent — never the
   private key.
4. Remove `USER_IDENTITY_SECRET` and `USER_IDENTITY_ALG` from every `.env` /
   compose file; they are now unused.

No code changes are needed if you were already using RS256 — this is a
configuration-only migration for anyone still on HS256. See
[IDENTITY_KEY_MANAGEMENT.md](./IDENTITY_KEY_MANAGEMENT.md) for the full guide.

## 0.11.0

### Select an Installed LLM Profile; Do Not Configure Agent Flavors

`LLMClient` now always loads a YAML configuration. It uses the installed
`registry` profile by default, or selects `inl_hpc`, `inl_litellm`, `amsc`,
`anthropic`, or `openai` through `LLM_CONFIG_PROFILE`. A custom
`LLM_CONFIG_FILE` takes precedence. `LLM_DEFAULT_MODEL` has been removed: a bare
`llm(...)` or `llm.chat(...)` call always requests `default`, while agents
should continue hardcoding the semantic flavor their task needs, such as
`llm.medium(...)`.

Migration steps:

1. Remove `LLM_DEFAULT_MODEL` from deployment configuration.
2. Set `LLM_CONFIG_PROFILE` and provide the API keys referenced by that profile,
   or keep `REGISTRY_URL` for the default registry profile.
3. Put provider model names and endpoints in the YAML profile, not agent code.

```bash
LLM_CONFIG_PROFILE=openai
LLM_API_KEY=...
```

```python
async with self.llm_client(context) as llm:
    response = await llm.medium(params["query"])
```

## 0.10.0

### Identity verification runs before `_execute` — coordinated deployment required

`PrometheusAgentExecutor.execute()` now verifies a platform-signed JWT
(`message.metadata["userToken"]`) before calling `_execute()`. When
`USER_IDENTITY_REQUIRED=true` (the **new default**), any request that arrives
without a valid token is rejected with `IdentityError` and the task is failed
before your code runs.

**This is a two-repo upgrade.** Requests without a `userToken` come from the
current `prometheus_platform` stack, which only attaches the token after the
platform's own `multi_user` branch is deployed. Upgrade the base image and the
platform stack together, or use the `false` escape hatch during the transition
window:

```bash
# Add to every agent's docker-compose environment block during transition:
USER_IDENTITY_REQUIRED=false
# Switch to true only after prometheus_platform multi_user is fully deployed.
USER_IDENTITY_REQUIRED=true
```

No agent code changes are needed for the common case. See the specific cases
below.

#### Case 1: agent test suites that call `execute()` directly

Tests that call `execute()` or make ASGI requests without attaching `userToken`
will now fail. Add `USER_IDENTITY_REQUIRED=false` to the test environment — the
same pattern used by `prometheus_api`'s own `conftest.py`:

```python
# conftest.py
import pytest

@pytest.fixture(autouse=True)
def _disable_identity(monkeypatch):
    monkeypatch.setenv("USER_IDENTITY_REQUIRED", "false")
```

Or in individual test fixtures:

```python
@pytest.fixture
def test_app(monkeypatch):
    monkeypatch.setenv("USER_IDENTITY_REQUIRED", "false")
    agent = MyAgent()
    return agent.build_app(register_on_startup=False)
```

#### Case 2: agents with `extra="forbid"` Pydantic input schemas

`_extract_params` now injects `params["user_id"]` for every request. If your
`_execute` passes `params` directly to a Pydantic model with `extra="forbid"`,
validation will raise on the new key.

Option A — add `user_id` to your schema:
```python
class MyInput(BaseModel):
    material_id: str
    user_id: Optional[str] = None  # injected by base class
```

Option B — strip it before validation:
```python
async def _execute(self, params, context, event_queue):
    clean = {k: v for k, v in params.items() if k != "user_id"}
    inp = MyInput.model_validate(clean)
```

Option C — switch to `extra="ignore"` (simplest if you do not need the key):
```python
class MyInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    material_id: str
```

#### Case 3: reading the verified user identity

If your agent needs to know who is calling it, use the base-class helpers — do
not read `params["user_id"]` directly, as that value is always present but its
presence alone does not prove the token was verified.

```python
async def _execute(self, params, context, event_queue):
    user_id = self.current_user_id()   # None when USER_IDENTITY_REQUIRED=false
    if user_id:
        await self.send_status_update(context, event_queue,
                                      message=f"Running for {user_id}.")
```

#### Case 4: agents that fetch per-user credentials

Agents that access external resources on behalf of a user should call
`self.get_credential(resource)` instead of reading env vars directly. Set
`requires_user_isolation = True` if the agent holds a live credential across
multiple `await` boundaries.

```python
class MyAgent(PrometheusAgent):
    requires_user_isolation = True   # run _execute in a per-user process

    async def _execute(self, params, context, event_queue):
        cred = await self.get_credential("deeplynx")
        config = ConnectionConfig.from_credential(cred)
        # use config for this operation only — do not store cred
```

See [MULTI_USER.md](./MULTI_USER.md) for the full reference.

## 0.9.0

### A2A SDK v1 Uses Protobuf Types and Strict Task Streams

`prometheus-api` now requires `a2a-sdk[http-server]>=1.0.0,<2` and serves A2A
Protocol v1. The base executor emits the required initial `Task` before status
or artifact updates, so normal `PrometheusAgent._execute()` implementations do
not need to manage the task lifecycle themselves.

Downstream code that directly constructs or inspects SDK objects must migrate:

1. Replace lower-case enum attributes with the v1 names, such as
   `TaskState.TASK_STATE_WORKING` and `Role.ROLE_USER`.
2. Replace `TextPart`, `DataPart`, `FilePart`, and `Part(root=...)` with unified
   `Part(text=...)`, `Part(data=...)`, `Part(url=...)`, or `Part(raw=...)`.
   Convert Python data payloads with `ParseDict(..., Value())` and protobuf
   payloads with `MessageToDict(...)`.
3. Stop reading `TaskStatusUpdateEvent.final`; v1 removed it. Determine whether
   work stopped from `event.status.state`. The Prometheus
   `send_status_update(..., final=...)` parameter remains accepted for source
   compatibility, but finality on the wire comes from the state.
4. Replace direct `A2AClient` use with `await create_client(...)`, then inspect
   each `StreamResponse` with `HasField("task")`, `HasField("status_update")`,
   or `HasField("artifact_update")`.
5. Raw JSON-RPC callers must use v1 method names such as `SendMessage` and
   `SendStreamingMessage` and send `A2A-Version: 1.0`.
6. The shared `prometheus_api.a2a_stream` parser accepts only v1 `task`,
   `statusUpdate`, and `artifactUpdate` envelopes with direct `Part` fields. It
   preserves exact ProtoJSON `TASK_STATE_*` values and raises `A2AStreamError`
   for invalid state spellings or malformed parts. Remove lowercase state
   aliases, pre-v1 dashed event kinds, root-wrapped parts, and `final` fields
   from downstream stream producers and test fixtures.

LiteLLM deployments that route A2A traffic must use version 1.92.0 or newer;
older releases embed the 0.3 SDK and cannot invoke a protocol-v1 agent. The base
registry client automatically adds LiteLLM's top-level `url` and
`protocolVersion` routing fields to the registered copy of the v1 card. These
compatibility fields are not added to the strict card served by the agent.

```python
from a2a.types import Part, Role, TaskState
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Value

text_part = Part(text="Working")
data_part = Part(data=ParseDict({"score": 0.95}, Value()))
state = TaskState.TASK_STATE_WORKING
payload = MessageToDict(data_part.data)
```

### Agent Cards and Server Assembly Use v1 Interfaces and Route Factories

The base agent now advertises a JSON-RPC `AgentInterface` in
`supportedInterfaces`, passes the card to `DefaultRequestHandler`, and builds
Starlette with `create_agent_card_routes()` and `create_jsonrpc_routes()`.
Existing cards may continue omitting endpoint fields: `load_agent_card()`
creates the JSON-RPC interface from `EXTERNAL_AGENT_URL` or the container host
and `AGENT_PORT`. If a v1 JSON-RPC interface is present, its URL receives the
same runtime override.

The canonical v1 card is served at `/.well-known/agent-card.json` and at the
legacy discovery alias `/.well-known/agent.json`. Prometheus-only extensions
such as workflows remain on `/api/agent-card`. `build_app()` also preserves the
previous 10 MiB request limit; pass `max_content_length=None` only when a custom
host intentionally allows larger requests.

Agents that use `PrometheusAgent.build_app()` need no server-assembly changes.
Custom hosts should replace the removed `A2AStarletteApplication` wrapper with
the v1 route factories, or switch to `build_app()`.

## 0.8.0

### Shared Client-Side Helpers — Stop Copying Stream/Redis Boilerplate

Three pieces of logic that downstream code tended to copy now have single
canonical implementations:

- `prometheus_api.a2a_stream` — consume A2A `SendStreamingMessage` responses
  (SSE/NDJSON parsing, heartbeat skipping, status/background callbacks, artifact
  merge/dedup). Use `stream_a2a_request(...)` for a full call or
  `consume_stream_response(...)` on an open httpx stream.
- `prometheus_api.redis_utils.create_redis_client(...)` — the platform-wide
  Redis connection recipe (`REDIS_URL`/`REDIS_PASSWORD` env defaults,
  `decode_responses=True`, fail-fast ping, returns `None` with a logged warning
  on failure). `redis` is now a declared dependency of `prometheus-api` instead
  of optional-at-runtime.
- `prometheus_api.agent.ArtifactResolver` — artifact-to-local-file resolution,
  extracted from `PrometheusAgent`. The public
  `PrometheusAgent.get_artifact_file_path(...)` API is unchanged; only the
  private helpers (`_materialize_inline_artifact`,
  `_download_artifact_uri_to_cache`, `_artifact_cache_path`, …) moved.

Migration steps:

1. If your agent or client code copied the SSE/NDJSON stream-parsing pattern,
   replace it with `prometheus_api.a2a_stream`. Note error envelopes now raise
   `a2a_stream.A2AStreamError` (an `Exception` subclass).
2. Replace hand-rolled `redis.Redis.from_url(...)` setup with
   `create_redis_client()`. If you relied on the password being embedded in
   `REDIS_URL`, that still works; a separate `REDIS_PASSWORD` overrides it.
3. If you called private `PrometheusAgent._*` artifact helpers (you should not
   have), call them on `agent.artifact_resolver` instead.

```python
from prometheus_api.a2a_stream import stream_a2a_request
from prometheus_api.redis_utils import create_redis_client

result = await stream_a2a_request(endpoint, message, headers=headers,
                                  status_callback=on_status)
client = create_redis_client()  # REDIS_URL/REDIS_PASSWORD from env
```

## 0.7.0

### Context State Is Now Conversation-Scoped — Not Per-Task

The platform's client-agent now propagates the conversation ID as the A2A
`message.contextId` on every call, so `RequestContext.context_id` (and therefore
`load_context_state` / `save_context_state` and artifact metadata's
`conversation_id`) is the stable conversation ID instead of an SDK-generated
per-task ID. State you save in one `_execute` call is now visible to later calls
— including calls to *other* skills of your agent — within the same
conversation.

Migration steps:

1. If your agent assumed `context.context_id` was unique per invocation (e.g.
   used it as a scratch key or a "fresh run" marker), switch to
   `context.task_id` for per-invocation scoping.
2. If you persist state with `save_context_state`, make sure stale keys from
   earlier turns in the same conversation cannot be misread as fresh input —
   namespace by skill or clear what you consumed.
3. No change is needed for agents that already treat context state as
   conversation memory; this is the behavior the API always documented.

```python
async def _execute(self, params, context, event_queue):
    # Conversation-scoped (survives across turns and skills):
    memo = self.load_context_state(context.context_id)

    # Per-invocation scoping, if you really need it:
    scratch_key = f"{context.context_id}:{context.task_id}"
```

### Use the Shared Wire Contract from `prometheus_api.contract`

The frontend ↔ client-agent payload models (`ConversationRequest`,
`ConversationResponse`, `ConversationStatus`) now live in
`prometheus_api.contract` and are the single source of truth. The module is
dependency-light (pydantic only) so frontends can import it without the agent
runtime. Specialist agents are unaffected unless they construct or parse these
payloads — if yours does, import the models instead of redefining them.

```python
from prometheus_api.contract import ConversationResponse, ConversationStatus

response = ConversationResponse(
    conversation_id=conv_id,
    status=ConversationStatus.ANSWER,
    response_text="...",
)
```

`ConversationResponse.status` is validated against `ConversationStatus`;
inventing ad-hoc status strings now fails loudly at construction/parse time.

### Drop `url` from `agent_card.json`; `AGENT_HOST` Is Dead

`load_agent_card` has overwritten the card's `url` since 0.6.0
(`EXTERNAL_AGENT_URL` if set, else `http://{container hostname}:{AGENT_PORT}`),
and `AGENT_HOST` is not read at all. Remove both from your agent card and
compose files to avoid implying an unreachable `localhost` registration.

Migration steps:

1. Delete the `url` field from `agent_card.json`.
2. Delete `AGENT_HOST` from your compose `environment` block.
3. Set `EXTERNAL_AGENT_URL` only when the agent is port-mapped or runs on a
   different host than the platform; inside Docker Compose the default
   (container hostname == service name) is correct.

## 0.6.0

### Keepalive Heartbeats During `_execute` — Do Not Block the Event Loop

The base executor now emits periodic non-final "working" status events while
your `_execute` runs, so long-running agents keep traffic on the wire and do not
trip upstream idle-connection timeouts (LiteLLM/aiohttp) mid-task.

This only works if your `_execute` does not block the single event loop. A
synchronous call that does not `await` — a blocking SDK
(`anthropic.Anthropic().messages.create(...)`), `requests`, a legacy library, a
CPU loop, `time.sleep` — freezes the loop, so the heartbeat (and your own
`send_status_update` calls) cannot be sent and the very timeout the heartbeat
prevents will still fire. The fix is never a bigger timeout; it is to keep the
loop free.

Migration steps:

1. Audit `_execute` for synchronous, blocking calls and offload them with
   `asyncio.to_thread` (or use an async client). For long blocking work that
   needs to stream progress, use `PrometheusWorker` (below).
2. If you consume or inspect the raw event stream, ignore heartbeat events: they
   carry no message and are tagged `metadata.heartbeat=true`.
3. Tune the cadence with `PROMETHEUS_HEARTBEAT_INTERVAL` (positive seconds;
   default `15`). A non-numeric or non-positive value is rejected; heartbeats
   cannot be disabled.

```python
# WRONG — blocks the loop for the whole call; heartbeat and streaming stall
result = blocking_library.run(payload)

# CORRECT — runs off-loop; the loop stays free to flush heartbeats/status
result = await asyncio.to_thread(blocking_library.run, payload)
```

### Run Blocking Workloads with `PrometheusWorker`

For genuinely blocking work that should still stream progress, subclass
`PrometheusWorker` and dispatch it with `PrometheusAgent.run_worker`. The
worker's `run()` executes on a worker thread; from there it cannot touch the
loop-bound A2A event queue, so it emits a safe subset of events into a
thread-safe mailbox that `run_worker` drains and forwards from the loop. Only
pure, no-I/O event construction is exposed — `emit_status_update` and
`emit_json_artifact` (inline, not cataloged). DeepLynx uploads, catalog
registration, conversation messages, and `INPUT_REQUIRED` are intentionally
unavailable; do those on the loop, before or after `run_worker`.

Migration steps:

1. Move the blocking work into a `PrometheusWorker.run()` (plain synchronous
   code).
2. Stream progress with `self.emit_status_update(...)` and, for verbose output,
   `self.emit_json_artifact(...)` (supports `append`/`last_chunk` for chunks).
3. Check `self.cancelled` periodically and stop early — threads cannot be
   force-killed, so cancellation is cooperative.
4. Dispatch from `_execute` with
   `await self.run_worker(worker, context, event_queue)`, which returns
   `run()`'s result and re-raises its exceptions.

```python
from prometheus_api.agent import PrometheusAgent, PrometheusWorker


class CrunchWorker(PrometheusWorker):
    def run(self):
        total = len(self.items)
        for i, item in enumerate(self.items, 1):
            if self.cancelled:
                return {"status": "cancelled", "done": i - 1}
            self.emit_status_update(f"Crunching {i}/{total}…")
            heavy_blocking_call(item)
        return {"status": "success", "processed": total}


class CrunchAgent(PrometheusAgent):
    async def _execute(self, params, context, event_queue):
        worker = CrunchWorker()
        worker.items = params["items"]
        return await self.run_worker(worker, context, event_queue)
```

## 0.5.0

### Use the Agent `_execute` Hook

Most agents should implement `PrometheusAgent._execute()` and let the base class
create the executor. The executor now delegates to the agent's `_execute` method
through `DelegatingPrometheusAgentExecutor`; downstream agents do not need a
custom nested executor just to run their logic.

Migration steps:

1. Remove custom `create_executor()` methods that only wrap the agent's
   `_execute`.
2. Keep the existing async `_execute(params, context, event_queue)`
   implementation on the `PrometheusAgent` subclass.
3. Override `create_executor()` only when replacing the standard execution
   lifecycle.

```python
from prometheus_api.agent import PrometheusAgent


class MyAgent(PrometheusAgent):
    async def _execute(self, params, context, event_queue):
        await self.send_status_update(
            context=context,
            event_queue=event_queue,
            message="Running analysis.",
        )
        return {"message": "Analysis complete.", "agent": self.agent_name}
```

### Build Apps Through `build_app`

Agents that host the Starlette app themselves should call `build_app()` instead
of constructing `A2AStarletteApplication`, request handlers, middleware, and
debug routes manually. This keeps authentication, health routes, debug routes,
lifespan hooks, and registry startup behavior consistent.

Migration steps:

1. Replace manual Starlette/A2A app assembly with `agent.build_app()`.
2. Use `register_on_startup=False` in tests or harnesses that should not contact
   the registry.
3. Put custom routes in `configure_app(app)` and startup/shutdown work in
   `lifespan(app)`.

```python
agent = MyAgent(agent_name="My Agent")

# Production/custom host:
app = agent.build_app()

# Tests:
test_app = agent.build_app(register_on_startup=False)
```

### Configure Required Auth Explicitly

When `AGENT_SECRET_REQUIRED=true` (the default), `AGENT_SECRET` must be
configured before the agent app is built. The base agent fails fast at app
construction time instead of starting a server with unusable authentication
middleware.

Migration steps:

1. Set `AGENT_SECRET` for deployed agents.
2. Keep `AGENT_SECRET_REQUIRED=true` outside local unauthenticated development.
3. Set `AGENT_SECRET_REQUIRED=false` only for local tests or demos that
   intentionally do not require bearer-token auth.

```bash
AGENT_SECRET=shared-agent-token
AGENT_SECRET_REQUIRED=true
```

```python
# Local unauthenticated test harness only.
monkeypatch.setenv("AGENT_SECRET_REQUIRED", "false")
app = agent.build_app(register_on_startup=False)
```

### Let Startup Handle Registry Registration

Registry registration now runs as an asynchronous background task from app
lifespan startup. The task keeps exponential backoff retries so an agent can
come up while the LiteLLM registry is still becoming ready.

Migration steps:

1. Remove explicit startup calls to `register_with_registry()` from agent
   entrypoints unless a non-Starlette host truly needs them.
2. Use `agent.run()` or `agent.build_app()` so lifespan startup schedules
   registration.
3. Use `REGISTRY_MAX_RETRIES` to tune retries after the first attempt.
4. Set `register_on_startup=False` for tests that should not start registration.

```python
if __name__ == "__main__":
    agent = MyAgent(agent_name="My Agent")
    agent.run()
```

```bash
REGISTRY_URL=http://litellm:4000
REGISTRY_MAX_RETRIES=10
```

### Use Status Helpers Instead of Manual Events

Status event construction is centralized so `task_id`, `context_id`, text
messages, and metadata stay consistent across the executor and public helper
APIs.

Migration steps:

1. Replace direct `TaskStatusUpdateEvent(...)` progress events with
   `send_status_update(...)`.
2. Keep returning a dict from `_execute`; the base executor emits the final
   completed event automatically.
3. Use `send_input_required(...)` for final input-required responses.

```python
class MyAgent(PrometheusAgent):
    async def _execute(self, params, context, event_queue):
        await self.send_status_update(
            context=context,
            event_queue=event_queue,
            message="Loading source data.",
        )
        return {"message": "Done.", "agent": self.agent_name}
```
