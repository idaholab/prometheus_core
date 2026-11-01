# Prometheus Agent Template

A template for building specialist agents for the [Prometheus](https://github.com/idaholab/prometheus_core)
multi-agent platform (it lives in the `agent-template/` directory of that
monorepo). Agents speak the Agent-to-Agent (A2A) protocol; the
platform's orchestrator discovers them, routes user requests to them, and renders
their responses in the Prometheus web UI.

This repository gives you two things:

- **`agent_template/`** — the canonical set of files for one agent
  (`agent.py`, `agent_card.json`, `pyproject.toml`, `Dockerfile`,
  `docker-compose.yml`, network compose includes, `Makefile`, `.env.example`,
  `prompts/`, and `workflows/`).
- **`setup_agent.py`** — an interactive scaffolder that copies the template into
  a new directory with your agent's name, slug, class, and skill filled in.
- **[`TUTORIAL.md`](TUTORIAL.md)** — a step-by-step guide that explains every file
  and walks you through building, containerizing, and deploying an agent.

Each agent builds **`FROM`** the prebuilt `prometheus_api` base image, which
already bundles Python 3.12, `prometheus_api`, and the A2A server stack
(`a2a`, `starlette`, `uvicorn`). Your image only adds your code and any extra
dependencies — builds are small and fast.

## Quick start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Docker Desktop (or Podman) — for containerized runs. The `prometheus_api` base
  image (`ghcr.io/idaholab/prometheus_core/prometheus_sdk-devel`) is public, so
  no registry login is needed

### Scaffold a new agent

```bash
git clone git@github.com:idaholab/prometheus_core.git
cd prometheus_core/agent-template
python setup_agent.py                        # prompts for everything
python setup_agent.py "Plant Analysis" ../plant-agent   # name and output dir given
python setup_agent.py --yes "Plant Analysis" ../plant-agent   # every other value defaulted, no prompts
python setup_agent.py --env-only ../plant-agent         # only the .env, for an agent you cloned
```

The script prompts for the agent name (unless given as the first argument),
description, slug, class name, and primary skill, then writes a ready-to-edit project to the output directory you choose:

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
├── docker-compose.net_internal.yml
├── docker-compose.net_external.yml
├── Makefile
└── .env.example
```

if you have created the platform's `.env` (`platform/.env` in this repository),
the `setup_agent.py` script will optionally inspect it and copy over all required
secrets to make the newly instantiated agent register with the platform out of the box.

<!-- Keep in sync with the "agent-template: platform" job in
     .github/workflows/test.yml, which creates platform/.env, scaffolds with
     --yes, and starts the agent on the platform in CI. If you change the
     scaffolding or .env behavior described here, update the job to match. -->

> Prefer to do it by hand? Copy `agent_template/` and replace the `TEMPLATE_*`
> placeholders yourself. See [`TUTORIAL.md`](TUTORIAL.md).

### Run it

```bash
cd ../my-agent

# optionally (only if you declined to have a .env created during setup)
cp .env.example .env          # fill in real values

# Local (fast iteration):
uv sync && source .venv/bin/activate
# Pin prometheus_api to the platform's base image hash (see .env):
uv pip install "git+ssh://git@github.com/idaholab/prometheus_core.git@3407a82#subdirectory=sdk"
# or https
uv pip install "git+https://github.com/idaholab/prometheus_core.git@3407a82#subdirectory=sdk"
AGENT_SECRET_REQUIRED=false python agent.py

# Tests / lint:
uv run pytest && uv run ruff check .

# Or with Docker (set PROMETHEUS_API_BASE_IMAGE_HASH in .env first):
make up

# Or run in the foreground:
make up-fg

# Standalone Docker curl testing (no platform running):
EXTERNAL_AGENT_HOST=localhost EXTERNAL_AGENT_PORT=8000 make up-fg

# Platform integration through a host-published port:
EXTERNAL_AGENT_HOST=prometheus.host.internal EXTERNAL_AGENT_PORT=8042 make up
```

Plain `make up` / `make up-fg` defaults to the platform Docker network. If the
platform is not running, `prometheus_platform_agent-network` will not exist and
the agent port will not be published to the host. Use external mode with
`EXTERNAL_AGENT_HOST=localhost EXTERNAL_AGENT_PORT=8000` when you only want to
start one agent container and test it from your host with `curl`.

For external mode, `prometheus.host.internal` is the hostname for the host
machine from inside a container. Every platform and agent compose service maps
it to Docker's host gateway, on macOS and Linux alike.

See the generated `README.md` in your agent directory, and
[`TUTORIAL.md`](TUTORIAL.md) for the full walkthrough — agent card design,
emitting artifacts, multi-turn input (`INPUT_REQUIRED`), multiple skills,
agent-owned workflows, prompt templates, custom HTTP endpoints, DeepLynx
storage, and both deployment paths (external repo vs. in-tree).

## Repository development

This repository's own tooling (the scaffolder) is uv-managed:

```bash
make check      # ruff lint + format check + mypy
make fix        # auto-fix lint + format
make test       # pytest
```

CI runs `pytest --cov` and fails if coverage drops below `fail_under` in `[tool.coverage.report]`, the lowest total across the supported Python versions. Raise it as coverage improves; never lower it. Running a subset of tests with `--cov` will fail the floor, so leave `--cov` off for targeted runs.

## Further reading

These live in the SDK ([`sdk/`](https://github.com/idaholab/prometheus_core/tree/devel/sdk)) directory of the monorepo:

| Document | Description |
|----------|-------------|
| [PrometheusAgent Guide](https://github.com/idaholab/prometheus_core/blob/devel/sdk/docs/agent/GUIDE.md) | Full API reference, pitfalls, lifecycle hooks |
| [PrometheusAgent Quick Start](https://github.com/idaholab/prometheus_core/blob/devel/sdk/docs/agent/QUICK_START.md) | Condensed recipes for every helper |
| [Environment Setup](https://github.com/idaholab/prometheus_core/blob/devel/sdk/docs/ENV_SETUP.md) | All environment variables for agents and storage |
| [StorageClient Guide](https://github.com/idaholab/prometheus_core/blob/devel/sdk/docs/storage-client/GUIDE.md) | Reading and writing to DeepLynx |
| [Multi-User Identity & Credentials](https://github.com/idaholab/prometheus_core/blob/devel/sdk/docs/agent/MULTI_USER.md) | Verifying which platform user is calling your agent, per-user credentials |
| [Identity Key Management](https://github.com/idaholab/prometheus_core/blob/devel/sdk/docs/agent/IDENTITY_KEY_MANAGEMENT.md) | RS256 keys, `prometheus-identity-keygen`, JWKS for third-party agents (this template) |

## Support

Reach out on Teams.
