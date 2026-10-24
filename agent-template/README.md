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
  a new directory with your agent's name, slug, class, and skill filled in, and
  its `_execute` scaffolded to an agentic design pattern (see
  [Design patterns](#design-patterns)).
- **`patterns.json`**, **`patterns.py`**, **`frameworks.py`** — the design-pattern
  catalog (9 families, 36 architectures, 9 agent frameworks), the pattern
  suggester, and the code generators the scaffolder uses.
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
- Docker Desktop (or Podman) — for containerized runs
- Access to the `prometheus_api` base image registry
  (`containers.github.inl.gov/genesis/prometheus_api`)

### Scaffold a new agent

```bash
git clone git@github.com:idaholab/prometheus_core.git
cd prometheus_core/agent-template
python setup_agent.py                        # prompts for everything
python setup_agent.py "Plant Analysis" ../plant-agent   # name and output dir given
python setup_agent.py --yes "Plant Analysis" ../plant-agent   # every other value defaulted, no prompts
python setup_agent.py --env-only ../plant-agent         # only the .env, for an agent you cloned
python setup_agent.py --list-patterns                   # the design-pattern catalog
python setup_agent.py --yes --pattern corrective_rag "Doc QA" ../doc-qa             # pick the pattern
python setup_agent.py --yes --pattern react --framework langgraph "Ops Bot" ../ops  # ...built with LangGraph
python setup_agent.py --llm "Plant Analysis"            # let the platform's LLM suggest the pattern
```

The script prompts for the agent name (unless given as the first argument),
description, slug, class name, primary skill, and design pattern, then writes a ready-to-edit project to the output directory you choose:

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

## Design patterns

`setup_agent.py` scaffolds `_execute` to one agentic design pattern from
[`patterns.json`](patterns.json): 36 architectures in 9 families.

| Family | Examples (`--pattern` slug) |
|---|---|
| Reflection & Refinement | `reflection`, `reflexion`, `chain_of_verification` |
| Retrieval | `agentic_rag`, `corrective_rag`, `self_rag`, `graph_rag` |
| Planning & Chaining | `planning`, `pev`, `tree_of_thoughts`, `lats` |
| Tool Use & Actions | `tool_use`, `react`, `swe_agent`, `browser_agent` |
| Memory | `episodic_semantic`, `graph_memory`, `memgpt`, `voyager` |
| Routing & Governance | `dry_run`, `reflexive_metacognitive` |
| Sampling & Search | `self_consistency`, `forward_sampling_uq`, `ensemble` |
| Multi-Agent | `multi_agent`, `blackboard`, `debate`, `storm`, `meta_controller` |
| Specialty | `constitutional_ai`, `rlhf_self_improvement`, `cellular_automata` |

`python setup_agent.py --list-patterns` prints all of them with when to use each.

Each architecture has ordered steps and a control-flow topology (`linear`,
`loop`, `cycle`, `parallel`, `tree`). The generated agent gets:

- `_run_pattern`, called from `_execute`, which walks the steps in that
  topology (a bounded `MAX_ITERATIONS` loop, an `asyncio.gather` over
  `NUM_SAMPLES`, ...), and one `_step_<name>` method per step with a
  `TODO(author)`. Every step returns `None` until you implement it, so the new
  agent runs, lints, and passes its tests from the start.
- A "Design pattern" section in its `README.md` with the steps and a Mermaid
  diagram.

**Choosing the pattern.** The scaffolder suggests one from the agent
description with an offline keyword score, and you accept it or pick another.
`--pattern <slug>` sets it directly. `--llm` asks the platform's LLM instead,
through `prometheus_api.llm_client.LLMClient` configured from the environment
(`LLM_CONFIG_PROFILE` / `LLM_API_KEY`); any failure falls back to the keyword
suggestion. `--yes` takes the suggestion without prompting.

**Framework variants.** `--framework <slug>` (`langgraph`, `pydantic_ai`,
`crewai`, `smolagents`, `ag2`, `strands`, `openai_agents`, `google_adk`,
`claude_agent_sdk`) also writes `pattern_<framework>.py`, which builds the
same steps with that framework's own primitives (for example a LangGraph
`StateGraph` with the loop as a conditional edge). `agent.py` keeps its
`PrometheusAgent`; `_run_pattern` calls the module's `run_framework` through
`asyncio.to_thread`, so A2A, auth, and registration stay with the platform.
The framework's package is added to the agent's `pyproject.toml`. The default,
`native`, uses no framework.

**In the template itself**, `agent_template/agent.py` keeps a working default
(the Tool Use pattern) between `# >>> design pattern` and `# <<< design pattern`
markers, so the unscaffolded template still runs and lints; the scaffolder
replaces that block.

The taxonomy follows the public literature on agentic design patterns,
including DeepLearning.AI's *Agentic Design Patterns* series and the
MIT-licensed [all-agentic-architectures](https://github.com/FareedKhan-dev/all-agentic-architectures)
collection; each catalog entry links its reference. Pattern names are the
field-standard ones; descriptions, steps, and generated code are our own, and
no third-party code or prose is included.

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
