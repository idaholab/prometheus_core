# Dependencies

This document is a glossary for major external software that appears by name in
Prometheus API documentation. It is not an exhaustive package manifest; use
`pyproject.toml` and `uv.lock` for exact Python dependency versions.

## Agent2Agent (A2A)

[Agent2Agent (A2A)](https://a2a-protocol.org/latest/) is an open protocol for
communication and interoperability between AI agents. Prometheus agents use A2A
as their external request, streaming, task, status, and artifact contract.

The Python implementation used by this package is the
[official A2A Python SDK](https://github.com/a2aproject/a2a-python), published
to Python packaging as `a2a-sdk`.

## DeepLynx

[DeepLynx](https://github.com/idaholab/DeepLynx) is an open-source data
warehouse developed by Idaho National Laboratory. It supports digital
engineering by integrating data from disparate tools and formats across a
project lifecycle, such as CAD models, requirements, and simulations, into an
ontology-backed graph store.

Prometheus API's `storage_client` uses DeepLynx as its storage backend for
items, files, relationships, tags, search, and timeseries data.

[Instructions for setting up DeepLynx locally](https://github.com/idaholab/prometheus_core/blob/devel/platform/docs/docs/local-deeplynx.md)

## Docker

[Docker](https://docs.docker.com/) is a container build and runtime platform.
Prometheus API uses Docker for packaging deployable runtime images, including
multi-architecture image builds through the Makefile.

## fsspec

[fsspec](https://filesystem-spec.readthedocs.io/en/latest/) provides filesystem
interfaces for Python. Prometheus API registers a `deeplynx://` filesystem so
callers can interact with DeepLynx-backed files through fsspec-compatible
tooling.

## LiteLLM

[LiteLLM](https://docs.litellm.ai/) provides a Python SDK and proxy server for
calling many LLM providers through OpenAI-compatible request and response
formats.

Prometheus uses LiteLLM in two related ways selected by an installed or custom
YAML configuration:

- The installed `registry` profile routes aliases through the LiteLLM proxy or
  gateway referenced by `REGISTRY_URL`.
- The Python `litellm` package calls providers directly for profiles containing
  `model_list`, such as `inl_hpc`, `inl_litellm`, `amsc`, `anthropic`,
  `openai`, and `anl_asksage`.

## MLflow

[MLflow](https://mlflow.org/docs/latest/) is an open-source platform for
tracking, evaluating, and observing machine learning, LLM, and agent workflows.
Prometheus API treats MLflow as an optional integration: LLM tracing is used only
when `ENABLE_MLFLOW_TRACING=true` and the runtime environment has `mlflow`
installed.

## Starlette and uvicorn

[Starlette](https://www.starlette.io/) is a lightweight ASGI framework for
building async Python web services. [uvicorn](https://www.uvicorn.org/) is an
ASGI web server for Python.

Prometheus agents use this stack to expose A2A HTTP endpoints, agent card
routes, bearer-token middleware, and debug compatibility routes.

## uv

[uv](https://docs.astral.sh/uv/) is the Python package and project manager used
for this repository's locked development environment. The Makefile runs tests,
linting, type checks, packaging, and install checks through uv.

## Valkey and Redis

[Valkey](https://valkey.io/) is an open-source, high-performance in-memory
key/value datastore and a community-driven fork of Redis stewarded by the Linux
Foundation. [Redis](https://redis.io/) is the Redis-protocol datastore family
and ecosystem that many libraries and docs still refer to by name.

Prometheus uses Redis-compatible storage for agent task state, artifact
catalogs, and per-context state. Platform deployments commonly use the
[valkey-bundle](https://github.com/valkey-io/valkey-bundle) image, which
packages Valkey with additional modules including search support.
