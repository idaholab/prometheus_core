# Testing Guide

For spec-backed behavior, follow the traceability and `⚠ untested` rules in
[SDD_TESTING_STANDARD.md](SDD_TESTING_STANDARD.md).

## Quick Start

Use the locked `uv` environment through the Makefile:

```bash
uv sync
make test             # unit tests only, no DeepLynx credentials required
make test-integration # integration tests, requires .env credentials
make test-all         # all tests, including integration
```

For one-off commands, use `uv run`:

```bash
uv run pytest -m "not integration"
uv run pytest tests/test_agent.py::TestPrometheusAgentExecutor
uv run pytest --cov=prometheus_api --cov-report=html
```

## Test Organization

| File | Description | Marker |
|------|-------------|--------|
| `test_agent.py` | A2A agent executor and event handling | unit |
| `test_artifacts.py` | Artifact registry and helper behavior | unit |
| `test_connection.py` | Connection configuration | unit |
| `test_env_config.py` | Environment variable loading | unit |
| `test_filesystem.py` | `deeplynx://` fsspec behavior | unit |
| `test_llm_client.py` | LLM config, aliases, chat/embedding paths, tracing, redaction | unit |
| `test_llm_configs.py` | Installed LLM YAML profiles and the flavor contract | unit |
| `test_llm_tools.py` | LLM tool-call parsing, definitions, and forced tool calls | unit |
| `test_models.py` | Pydantic models | unit |
| `test_sync_async_parity.py` | Sync/async resource payload and parsing parity | unit |
| `test_tags.py` | Tag endpoint behavior | unit |
| `test_integration.py` | Real DeepLynx API tests | integration |

Tests in `test_integration.py` are automatically marked with `integration` by `tests/conftest.py`.

## Integration Setup

Integration tests require a `.env` file with valid DeepLynx credentials:

```bash
cp .env.example .env
```

Required values:

```env
DEEPLYNX_KEY=your-api-key
DEEPLYNX_SECRET=your-api-secret
DEEPLYNX_ORG_ID=1
DEEPLYNX_PROJECT_ID=32
```

`DEEPLYNX_DATA_SOURCE_ID` is optional but recommended. Without it, some record-creation paths may fail if the project has no default data source.

## Local Quality Gates

Before opening a pull request, run:

```bash
make check
make test
make test-install
```

Install local hooks once per checkout:

```bash
make hooks
```

The hooks come from the repository-wide [`.pre-commit-config.yaml`](../../.pre-commit-config.yaml). The pre-commit hook scans staged changes for secrets with gitleaks and, when `sdk/` files change, runs ruff format and lint checks. The pre-push hook runs mypy and unit tests when `sdk/` files change. To run hooks manually:

```bash
uv run pre-commit run --config ../.pre-commit-config.yaml --all-files
uv run pre-commit run --config ../.pre-commit-config.yaml --all-files --hook-stage pre-push
```

## Writing Tests

Async tests are supported through `asyncio_mode = "auto"` in `pyproject.toml`, so explicit `@pytest.mark.asyncio` decorators are not required.

Keep unit tests hermetic. Anything that requires real DeepLynx credentials belongs in `test_integration.py` or must be explicitly marked `integration`.

Manual environment smoke tests belong outside pytest discovery. Use `examples/verify_connection.py` when you want to check a real `.env` connection interactively.
