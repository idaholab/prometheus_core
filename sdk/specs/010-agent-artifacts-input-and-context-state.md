# 010 — Agent artifacts, input, and context state

status: implemented
sources: docs/agent/GUIDE.md, docs/agent/DEEPLYNX_CHUNKED_UPLOAD.md, prometheus_api/agent/base.py, prometheus_api/agent/artifacts.py, prometheus_api/agent/artifact_resolver.py, prometheus_api/agent/context_state.py, prometheus_api/agent/events.py, tests/test_agent.py, tests/test_artifacts.py
depends-on: 008, 009, 012

## Purpose
Let agents request missing structured input, persist per-conversation state, publish reusable artifacts, and resolve artifacts into local files for downstream work.

## Requirements
- REQ-010-01: `MissingInput` and `build_input_required_payload(...)` MUST serialize missing input descriptors under `missing_inputs` and include a stripped `hint`.
- REQ-010-02: `send_input_required(...)` MUST emit a final `input_required` status whose message part is a JSON `DataPart` with canonical missing-input payload.
- REQ-010-03: `get_input_sources(...)` MUST return the `inputSources` message-metadata map (parameter name → `"model"`, `"user"`, or `"context"`) as strings, and `{}` when the message or the map is missing. Late-supplied inputs (INPUT_REQUIRED answers, context fills) MUST arrive in `params`; there is no separate provided-inputs channel. (Reworded 2026-10-20; `get_provided_inputs(...)` was removed in 0.14.1.)
- REQ-010-04: `load_context_state(...)` and `save_context_state(...)` MUST scope state by normalized producer agent ID and A2A `context_id`.
- REQ-010-05: `ContextStateStore.load(...)` MUST return `{}` for blank IDs, missing state, corrupt JSON, or non-dict payloads; `save(...)` MUST reject blank agent/context IDs.
- REQ-010-06: `ArtifactReference` MUST serialize to/from a normalized JSON-compatible dict and MUST normalize native A2A file, data, and text artifact payloads.
- REQ-010-07: `ArtifactRegistry` MUST require conversation scope and one content source (`uri`, `json_body`, or `text_body`) for registration.
- REQ-010-08: Artifact registry lookups MUST be isolated by conversation, resolvable by ID or normalized name, list newest-first, and degrade from Redis to memory.
- REQ-010-09: `send_json_artifact(...)` MUST emit a native A2A data artifact, wrap non-dict payloads under `{"value": ...}`, and catalog inline JSON only when `catalog_artifact=True`.
- REQ-010-10: `send_json_artifact(...)` MUST NOT auto-register URI-shaped JSON payloads unless `catalog_artifact=True`.
- REQ-010-11: `send_artifact_reference(...)` MUST register a URI-backed artifact and emit a native A2A file artifact.
- REQ-010-12: `send_deeplynx_artifact(...)` MUST upload the local file, update the DeepLynx item properties with artifact metadata, apply optional tags, emit a `deeplynx://organizations/{org}/projects/{project}/items/{item}` reference, and include DeepLynx IDs in metadata. ⚠ untested
- REQ-010-13: `send_text_artifact(...)` MUST emit a native A2A text artifact and return the artifact ID.
- REQ-010-14: `send_conversation_message(...)` MUST emit a JSON artifact named `conversation_message` with metadata `kind=conversation_message`.
- REQ-010-15: `get_artifact_file_path(...)` MUST require a conversation ID or context, resolve from registry or provided artifact catalog, and cache provided catalog entries when possible.
- REQ-010-16: Artifact resolution MUST materialize inline JSON/text to cache files, download non-local URI artifacts through `fsspec`, and validate local `file://` or absolute paths against allowed roots.

## Behavior
- BEH-010-01: GIVEN `send_input_required(...)` is called WHEN the event is inspected THEN its status is final `input_required` and the missing input is in a `DataPart`.
- BEH-010-02: GIVEN two conversations register artifacts with the same name or ID WHEN lookups occur THEN each conversation sees only its own artifacts.
- BEH-010-03: GIVEN a local `file://` artifact outside allowed roots WHEN resolving it to a path THEN `PermissionError` is raised.

## Interfaces
- `MissingInput(name: str, description: str, user_prompt: str, type: str, options: list[str] | None = None, resolvable_from_context: bool = False, sensitive: bool = False, required: bool = True)`
- `build_input_required_payload(missing_inputs: list[MissingInput], hint: str) -> dict[str, Any]`
- `PrometheusAgent.send_input_required(context, event_queue, *, missing_inputs: list[MissingInput], hint: str, metadata: dict | None = None) -> None`
- `PrometheusAgent.get_input_sources(context: RequestContext) -> dict[str, str]`
- `PrometheusAgent.load_context_state(context_id: str) -> dict[str, Any]`
- `PrometheusAgent.save_context_state(context_id: str, state: dict[str, Any]) -> None`
- `PrometheusAgent.register_artifact_reference(context: RequestContext, reference: ArtifactReference) -> ArtifactReference`
- `PrometheusAgent.list_artifact_references(conversation_id: str, limit: int | None = None) -> list[ArtifactReference]`
- `PrometheusAgent.resolve_artifact_reference(conversation_id: str, artifact_id: str) -> ArtifactReference | None`
- `PrometheusAgent.resolve_artifact_by_name(conversation_id: str, name_or_alias: str) -> ArtifactReference | None`
- `PrometheusAgent.get_artifact_file_path(artifact_id: str, *, context: RequestContext | None = None, conversation_id: str | None = None, artifacts: Sequence[Mapping[str, Any]] | None = None, cache_dir: Path | None = None, allowed_file_roots: Sequence[Path | str] | None = None, force_download: bool = False) -> Path`
- `PrometheusAgent.send_json_artifact(...) -> str`, `send_artifact_reference(...) -> ArtifactReference`, `send_deeplynx_artifact(...) -> ArtifactReference`, `send_text_artifact(...) -> str`, `send_conversation_message(...) -> str`
- `ArtifactReference(...)`, `to_dict() -> dict`, `from_dict(payload: dict) -> ArtifactReference`, `from_a2a_artifact(payload: Any, *, conversation_id: str | None = None, producer_agent_id: str | None = None) -> ArtifactReference | None`, `from_any(...) -> ArtifactReference | None`, `to_context_dict() -> dict`
- `ArtifactRegistry(redis_url: str | None = None, ttl_seconds: int | None = None).register/resolve_by_id/resolve_by_name/list/clear_conversation`
- `ArtifactResolver(registry: ArtifactRegistry).get_artifact_file_path(...) -> Path`
- `ContextStateStore(redis_url: str | None = None, ttl_seconds: int | None = None).load/save`

## Constraints
- Artifact IDs are conversation-scoped and opaque; callers should pass IDs rather than rely on names when possible.
- Local file artifacts are readable only from explicit allowed roots, configured roots, or the artifact cache root.
- Large result data SHOULD be emitted as artifacts rather than final status payloads.

## Out of scope / Non-goals
- The artifact registry is metadata storage; it does not guarantee remote artifact immutability or retention.
- Local artifact path resolution does not support remote `file://host/...` URIs.

## Open questions
- `send_deeplynx_artifact(...)` is implemented but lacks focused unit tests for upload/update/tag behavior.
- Artifact name resolution is last-write-wins for normalized names; there is no alias history.
