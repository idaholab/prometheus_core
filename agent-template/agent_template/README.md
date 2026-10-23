# TEMPLATE_NAME Agent

TEMPLATE_DESCRIPTION

A Prometheus specialist agent that speaks the Agent-to-Agent (A2A) protocol. The
platform's orchestrator discovers it, routes user requests to it, and renders its
responses in the Prometheus web UI.

## Files

| File | Purpose |
|------|---------|
| `agent.py` | Your code. Subclass of `PrometheusAgent`; implements `_execute`. |
| `agent_card.json` | Declares the agent's name, description, and skills. The orchestrator reads this to decide when to route to you. |
| `prompts/` | Prompt template files loaded by your agent code when prompts get too large for `agent.py`. |
| `workflows/` | Optional agent-owned workflow definitions inserted into the served agent card. |
| `pyproject.toml` | Extra Python dependencies your code imports directly. |
| `Dockerfile` | Builds the image from the pinned `prometheus_api` base image. |
| `docker-compose.yml` | Common service definition for containerized runs. |
| `docker-compose.net_internal.yml` | Default network include for joining the platform Docker network. |
| `docker-compose.net_external.yml` | Network include for exposing the agent port outside Docker. |
| `Makefile` | Convenience wrapper around `docker compose` (`make up`, `make up-fg`, `make down`, `make logs`). |
| `.env.example` | Template for `.env` — copy and fill in real values. |

`prometheus_api`, `a2a`, `starlette`, and `uvicorn` are already installed in the
base image — do **not** add them to `pyproject.toml`.

## Run locally (fast iteration)

```bash
cp .env.example .env          # then fill in real values

uv sync                       # creates .venv with your deps + dev tools (pytest, ruff)
source .venv/bin/activate

# Install prometheus_api pinned to the platform's base image hash
# (PROMETHEUS_API_BASE_IMAGE_HASH in your .env) so local dev matches the
# container. Re-run this when the platform bumps the hash.
uv pip install "git+https://github.com/idaholab/prometheus_core.git@$(grep -E '^PROMETHEUS_API_BASE_IMAGE_HASH=' .env | cut -d= -f2)#subdirectory=sdk"

AGENT_SECRET_REQUIRED=false python agent.py
```

If the target agent is running in Docker, start it in external network mode so
`localhost:8000` reaches the container; see the
[template README run instructions](https://github.com/idaholab/prometheus_core/blob/devel/agent-template/README.md#run-it).

The agent starts on `http://localhost:8000`. Test it:

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
        "parts": [{"kind": "text", "text": "{\"input_data\": \"hello\"}"}],
        "metadata": {"skillId": "TEMPLATE_SKILL_ID"}
      }
    }
  }' | python -m json.tool
```

(`skillId` lives in `message.metadata` — that is where the base class reads it.)

Without Redis, per-conversation state and the artifact registry fall back to an
in-memory dict — fine for local development.

## Run the tests

```bash
uv run pytest                 # tests/ — extend as you implement _execute
uv run ruff check .           # lint
```

## Run with Docker

Optionally set `PROMETHEUS_API_BASE_IMAGE_HASH` in `.env` (find the current value in
`platform/Makefile`), or let it default to `latest`. Without registry access, set
`LOCAL_SDK=true` instead to build FROM the `prometheus_api:local` image the platform
builds (`make base-image` in `platform/`). Then:

```bash
make up-fg       # build + start in the foreground (Ctrl-C to stop)
make up          # build + start detached
make logs        # tail logs (add SERVICE=<name> for one service)
make down        # stop and remove
```

These wrap `docker compose` and layer in the network-mode override.

By default, `make` includes `docker-compose.net_internal.yml`, so the agent joins
the platform's Docker network. Start the platform first, then run `make up` or
`make up-fg` here. Without a running platform, Docker cannot attach to that network.

To expose the agent port outside Docker instead, set both external mode variables:

```bash
EXTERNAL_AGENT_HOST=my-host.example.gov EXTERNAL_AGENT_PORT=8042 make up
```

`prometheus.host.internal` is the hostname for "the host machine from inside a
container." `docker-compose.yml` maps it to Docker's host gateway on every OS,
so the agent container can call host-published platform services.

If exactly one of `EXTERNAL_AGENT_HOST` or `EXTERNAL_AGENT_PORT` is set, `make`
stops before running Compose.

For in-tree platform deployment, copy this directory into
`platform/agents/<name>/` and run `make generate && make up` from the
`platform/` directory.

## Customizing

1. **`agent_card.json`** — set `name`, `description` (a one-sentence capability
   statement the orchestrator reads), and the skill's `inputSchema`,
   `output_format`, and `usage_notes`.
2. **`agent.py`** — read your inputs from `params`, do the work, return a plain
   `dict`. Use `self.send_status_update(...)` for progress messages.
3. **`prompts/`** — move large static LLM prompts into text files and load them
   with `load_prompt(...)` from `prometheus_api`.
4. **`workflows/`** — add workflow YAML/JSON files when this agent should publish
   workflow templates to the platform. Rename `example_workflow.yaml.example` to
   `.yaml` only after reviewing it; `.yaml` files are auto-published.
5. **Custom HTTP endpoints** — use `self.add_http_endpoint(...)` for small JSON
   endpoints or `self.add_static_endpoint(...)` for authenticated static assets
   such as viewer plugin files. Registered endpoints are advertised in the raw
   agent card under `endpoints`.
6. **`pyproject.toml`** — add any packages your code imports.

See **TUTORIAL.md** in the template repository for a full walkthrough, including
emitting artifacts, asking the user for missing inputs (`INPUT_REQUIRED`),
multiple skills, agent-owned workflows, custom endpoints, prompt files, and
DeepLynx file storage.

## Key environment variables

| Variable | Purpose |
|----------|---------|
| `AGENT_PORT` | Port the agent listens on (default `8000`). |
| `EXTERNAL_AGENT_HOST` / `EXTERNAL_AGENT_PORT` | Optional Docker external mode. Leave both unset to join the platform Docker network; set both to expose the agent port and register `http://{host}:{port}`. |
| `AGENT_SECRET` | Shared bearer token for A2A auth. Must match the platform's. |
| `AGENT_SECRET_REQUIRED` | Set `false` to disable auth — local development only. |
| `AGENT_WORKFLOWS` | Optional workflow directory override. Defaults to `workflows` next to `agent_card.json`. |
| `REGISTRY_URL` | LiteLLM proxy URL where the agent registers on startup. |
| `LITELLM_MASTER_KEY` | LiteLLM gateway auth. |
| `REDIS_URL` / `REDIS_PASSWORD` | Conversation state and artifact registry. |
| `PROMETHEUS_API_BASE_IMAGE_HASH` | Base image tag the Dockerfile builds from. |
| `LOCAL_SDK` | `true` builds FROM the locally built `prometheus_api:local` instead of the registry. |
| `JWKS_URL` | Multi-user identity (recommended): the platform operator's JWKS URL — point it at the **platform backend** (`https://<platform-host>/.well-known/jwks.json`), not at another agent. Fetches the verification key automatically, including any rotation done through the platform's admin UI. See below. |
| `USER_IDENTITY_PUBLIC_KEY` | Multi-user identity (alternative to `JWKS_URL`): a static public key from the platform operator. **Never** the private key — this agent only verifies. Won't observe a key rotated through the admin UI; re-ask the operator for the new key if verification starts failing. |
| `USER_IDENTITY_ISS` / `USER_IDENTITY_AUD` | Must match the platform operator's values exactly. |
| `DEEPLYNX_KEY` / `DEEPLYNX_SECRET` | Required DeepLynx authentication pair; alternatively use `DEEPLYNX_JWT_TOKEN`. |
| `DEEPLYNX_JWT_TOKEN` | Alternative to key/secret authentication; do not set both methods. |
| `DEEPLYNX_ORG_ID` / `DEEPLYNX_PROJECT_ID` | Required DeepLynx organization and project IDs. |
| `DEEPLYNX_DATA_SOURCE_ID` | Optional when the project has a default data source. |
| `DEEPLYNX_BASE_URL` | Optional; uses the SDK default when omitted. |

See `.env.example` for the full list, including proxy and runtime settings.

### Verifying platform users (multi-user)

If the platform is running in multi-user mode, every request carries a verified
`user_id`:

```python
async def _execute(self, params, context, event_queue):
    user_id = params["user_id"]  # verified by the base class; never spoofable
```

Signing is RS256 only, so this agent never needs (or should have) a private
key — only `JWKS_URL` or `USER_IDENTITY_PUBLIC_KEY`. Prefer `JWKS_URL` pointed
at the platform backend: platforms with an admin UI can generate, activate,
and retire signing keys through Postgres, and only `JWKS_URL` picks that up
automatically (a static `USER_IDENTITY_PUBLIC_KEY` needs manual updating after
every rotation). Generate/inspect keys with `prometheus-identity-keygen`
(ships in `prometheus_api`, already installed in this image) or `openssl`.
See
[TUTORIAL.md](https://github.com/idaholab/prometheus_core/blob/devel/agent-template/TUTORIAL.md#verifying-which-platform-user-is-calling-you-multi-user-identity)
and
[Identity Key Management](https://github.com/idaholab/prometheus_core/blob/devel/sdk/docs/agent/IDENTITY_KEY_MANAGEMENT.md)
for the full picture.
