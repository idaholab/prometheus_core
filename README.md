# Prometheus

Prometheus is a multi-agent analysis platform for engineering and science. This
monorepo holds the platform itself, the Python SDK its agents are built on, and a
template for writing new agents.

| Directory | What it is | Docs |
|-----------|------------|------|
| [`platform/`](platform/) | The deployable stack: React frontend, FastAPI backend, the client-agent orchestrator, specialist agents, and the LiteLLM gateway, all run with Docker Compose. | [platform/README.md](platform/README.md) |
| [`sdk/`](sdk/) | `prometheus_api`, the Python toolkit every agent uses: the `PrometheusAgent` base class, `StorageClient` for DeepLynx, and `LLMClient`. Also published as the `prometheus_api` base image that agent containers build `FROM`. | [sdk/README.md](sdk/README.md) |
| [`agent-template/`](agent-template/) | A starting point for a new specialist agent: the canonical agent files plus `setup_agent.py`, which scaffolds a new agent from them. | [agent-template/README.md](agent-template/README.md) |

## How they fit together

```
agent-template/  ──scaffolds──▶  a new agent  ──builds FROM──▶  sdk/ (prometheus_api image)
                                      │
                                      └──registers with──▶  platform/
```

Each directory has its own `Makefile`, dependencies, and tests; run commands from
inside the directory you are working on. The `sdk/` and `agent-template/` histories
were carried over from the former `prometheus_api` and `prometheus_agent_template`
repositories.

## Platform quick start

```
cd platform && make up
```

The first `make up` asks for an LLM profile and its key, and whether to build
the base image locally and run DeepLynx next to the platform (Enter for yes to both).

Needed prerequisites are Docker, python, make.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow
and checks and [DEVELOPMENT.md](DEVELOPMENT.md) for development and pull request
practices, [STANDARDS.md](STANDARDS.md) for coding standards and [TESTING.md](TESTING.md) for how we test, and please follow the [Code of Conduct](CODE_OF_CONDUCT.md). Report
security vulnerabilities privately as described in [SECURITY.md](SECURITY.md).
