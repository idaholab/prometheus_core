# Prometheus API Specs Index

This directory is the spec-driven-development contract for `prometheus_api`.
Specs describe required behavior that future changes must preserve or update.

Spec authors should follow [SDD_SPEC_AUTHORING.md](../docs/SDD_SPEC_AUTHORING.md).
Test coverage and `⚠ untested` handling should follow
[SDD_TESTING_STANDARD.md](../docs/SDD_TESTING_STANDARD.md).

## Architecture in 10 lines
- `prometheus_api.storage_client` wraps [DeepLynx](../docs/DEPENDENCIES.md#deeplynx) HTTP APIs behind typed sync and async clients.
- `ConnectionConfig` centralizes DeepLynx org/project, auth, data source, timeout, retry, and SSL settings.
- Storage resource classes own endpoint contracts for items, tags, search, files, relationships, and timeseries data.
- `DeepLynxFileSystem` exposes DeepLynx file records as an `fsspec` `deeplynx://` filesystem.
- `prometheus_api.llm_client` routes chat and embedding calls through installed [LiteLLM](../docs/DEPENDENCIES.md#litellm) YAML profiles for a registry proxy or direct providers.
- LLM normalization, secret redaction, [A2A](../docs/DEPENDENCIES.md#agent2agent-a2a) credential extraction, tool-call parsing, and optional [MLflow](../docs/DEPENDENCIES.md#mlflow) tracing sit behind provider-agnostic response models.
- `prometheus_api.agent` lets specialist agents subclass `PrometheusAgent` while the base handles A2A execution, app wiring, auth, and registry registration.
- Agent helpers emit status updates, input-required messages, worker-thread progress, and native A2A artifacts.
- `prometheus_api.contract` and `prometheus_api.a2a_stream` define dependency-light frontend/client-agent payload and stream handling.
- Redis helpers persist task, artifact, and context state when available and degrade to process-local memory when unavailable.

## Specs

| NNN | Name | Status | Summary |
| --- | --- | --- | --- |
| 001 | Storage configuration and authentication | implemented | DeepLynx connection settings, auth headers, retries, and storage client lifecycle. |
| 002 | Storage items, tags, search, and pagination | implemented | Item CRUD, tag resolution, search APIs, model parsing, and sync/async parity. |
| 003 | Storage files, relationships, and timeseries | implemented | File upload/download, chunked uploads, relationship APIs, and timeseries calls. |
| 004 | DeepLynx fsspec filesystem | implemented | `deeplynx://` path semantics, metadata versioning, lookup fallbacks, and deletion. |
| 005 | LLM configuration and aliases | implemented | Installed YAML profiles, environment selection, proxy/direct aliases, and alias errors. |
| 006 | LLM chat and embeddings | implemented | Sync/async chat and embedding calls, proxy/fallback execution, and response shaping. |
| 007 | LLM security and tracing | implemented | Secret redaction, no credentials from A2A requests, prompt-safe debug logging, and MLflow tracing. |
| 008 | Agent app, card, auth, and registry | implemented | Agent card loading, workflow injection, Starlette routes, bearer auth, and LiteLLM registration. |
| 009 | Agent execution, events, and workers | implemented | Executor lifecycle, heartbeats, status/background events, cancellation, and blocking worker support. |
| 010 | Agent artifacts, input, and context state | implemented | Input-required payloads, artifact cataloging/resolution, DeepLynx artifact upload, and context state. |
| 011 | A2A conversation contract and streams | implemented | Frontend/client-agent payload models plus NDJSON/SSE stream accumulation. |
| 012 | Redis-backed state and degradation | implemented | Shared Redis client creation and Redis-backed A2A task storage with memory fallback. |
| 013 | Package distribution and developer commands | implemented | Package metadata, version export, Makefile quality gates, install smoke tests, and container build contract. |
| 014 | LLM tool calling | implemented | Tool-call parsing, tool definitions, replayable tool history, and forced single-call tool selection. |

## Interface Ownership

Each public interface should be claimed by exactly one spec:

- Storage exports and resources: 001-004.
- LLM chat, embedding, configuration, security, and tracing exports: 005-007.
- LLM tool-calling exports (`llm_client/tools.py` and `LLMToolCallError`): 014.
- Agent exports and routes: 008-010, 012.
- Top-level contract, stream helpers, and Redis helpers: 011-012.
- Package metadata, Makefile commands, and container packaging: 013.

## How Agents Use These Specs

- Implementing: pick REQ and BEH IDs, write or extend tests that encode them, then code until green. Reference IDs in the commit message.
- Extending: add new front-loaded `REQ-NNN-XX:` and `BEH-NNN-XX:` entries using the next free number before coding; update `status` when done.
- Testing: cite REQ or BEH IDs in tests when useful, and keep inferred-but-untested requirements marked `⚠ untested` until coverage exists.
- Auditing / drift check: walk each REQ, locate the enforcing test or code; report `satisfied / violated / untested / obsolete` per ID. Propose spec edits for intentional drift, code fixes for unintentional drift.
