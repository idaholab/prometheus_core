# Message And Artifact Format Requirements

Status: proposed requirements for standardizing the multi-agent wire contract.

This document is based on the current implementation, on [MESSAGE_SCHEMAS.md](MESSAGE_SCHEMAS.md), and on the current A2A protocol model. It is intentionally stricter than the code as it exists today.

Its main design decision is:

- Prometheus should use native A2A message and artifact primitives on the wire
- Prometheus-specific behavior should be limited to conversation cataloging, persistence, and UI conventions layered on top of A2A

This document therefore does not define a replacement artifact transport. It defines:

- canonical message usage on top of A2A
- canonical artifact usage on top of A2A
- Prometheus-specific conventions needed for conversation-scoped artifact reuse and frontend visualization

## 1. Goals

The message and artifact contract must:

- provide one canonical location for final structured responses
- use native A2A `Artifact` and `Part` objects as the wire format
- support both URI-backed artifacts and inline structured JSON artifacts
- allow the frontend to choose renderers by explicit type identifiers rather than by tags or filename heuristics
- separate conversational messages, progress status, and artifact payloads cleanly

## 2. Non-goals

This document does not require:

- backward compatibility with older payload aliases
- arbitrary inline binary blob conventions beyond what A2A already supports
- dependence on `metadata.type`, `metadata.content`, `metadata.data`, tag-only routing, or URI-extension routing for new producers
- a Prometheus-specific artifact wire schema separate from A2A

## 3. Core Principles

### 3.1 Use A2A natively

Prometheus must treat A2A as the wire-level source of truth for:

- request envelopes
- response envelopes
- artifact transport

Prometheus-specific requirements should only cover:

- how A2A artifacts are interpreted
- how they are persisted across turns
- how the frontend chooses renderers

### 3.2 Canonical response location

Final structured message responses must live in:

- `result.status.message.parts[*].text`

That text payload must contain one serialized JSON object representing the response envelope.

`result.artifacts` is for artifacts only. It must not be used as an alternate location for the primary response envelope.

`result.history` is diagnostic only. Clients must not depend on it for normal result extraction.

### 3.3 Explicit typing over inference

Artifact rendering and downstream consumption must be driven by:

1. explicit MIME metadata on the primary A2A part
2. Prometheus `json_type` for JSON parts

In the currently installed Python A2A library, that means:

- URI-backed artifacts use `kind: "file"` and `file.mimeType`
- inline structured artifacts use `kind: "data"` and part `metadata.mime_type`

Tags, URI extensions, and arbitrary metadata must not be required for correct routing of conforming artifacts.

## 4. Message Requirements

## 4.1 A2A request envelope

The platform must use `message/send` for synchronous agent invocation.

The inner request payload in `params.message.parts[0].text` must be a serialized JSON object.

Required request envelope fields:

```json
{
  "jsonrpc": "2.0",
  "id": "<request_id>",
  "method": "message/send",
  "params": {
    "message": {
      "messageId": "<message_id>",
      "role": "user",
      "parts": [
        {
          "type": "text",
          "text": "{...json object...}"
        }
      ]
    },
    "configuration": {
      "blocking": true
    },
    "context": {
      "conversationId": "<conversation_id>",
      "skillId": "<skill_id>"
    }
  }
}
```

Requirements:

- `params.message.parts` must contain exactly one text part for structured requests.
- The text content must be valid JSON.
- `context.conversationId` must always be present.
- `context.skillId` must be present for specialist-agent invocations and may be omitted only for top-level orchestrator chat endpoints that perform their own routing.

## 4.2 Final response envelope

The canonical final response object for conversation-facing flows must be:

```json
{
  "conversation_id": "<uuid>",
  "status": "needs_info|plan_ready|executing|completed|recommendation|answer|error",
  "message": "..."
}
```

Additional fields by status:

- `needs_info`: `followup_questions`
- `plan_ready`: `plan`
- `completed`: `report`, `tool_results`
- `recommendation|answer`: `response_text`, optional `recommended_materials`

Cross-cutting optional fields:

- `artifacts`: full conversation artifact catalog after this turn
- `new_artifacts`: artifact delta created by this turn
- `message_metadata`: UI-facing metadata such as follow-up suggestions

Requirements:

- the response envelope must appear only in `result.status.message.parts[*].text`
- `result.artifacts` must carry artifacts, not duplicate conversation responses
- `artifacts` must be the post-turn full catalog
- `new_artifacts` must be the delta for the current turn

## 4.3 Status updates

Status updates are separate from final responses.

Requirements:

- progress status updates must use `result.status.state = "working"`
- final success must use `result.status.state = "completed"`
- final failure must use `result.status.state = "failed"`
- status messages should be human-readable text, not artifact payloads
- status updates must not be the only location of durable structured results unless they carry the final canonical response envelope

## 5. Artifact Requirements

## 5.1 Native A2A artifact is the wire format

Prometheus must use native A2A `Artifact` objects on the wire.

A Prometheus-conforming artifact should look like:

```json
{
  "artifactId": "<artifact_id>",
  "name": "Corrosion Summary",
  "description": "Summarized corrosion analysis output for Alloy 600",
  "parts": [
    {
      "kind": "data",
      "data": {
        "material_id": "Alloy 600",
        "findings": ["..."]
      },
      "metadata": {
        "mime_type": "application/json",
        "json_type": "prometheus.analysis.corrosion_summary.v1"
      }
    }
  ],
  "metadata": {
    "conversation_id": "<conversation_id>",
    "producer_agent_id": "corrosion-agent",
    "tags": ["analysis", "corrosion"],
    "created_at": "2026-03-18T00:00:00+00:00"
  }
}
```

Requirements:

- Prometheus must not define a separate artifact transport format in parallel with A2A
- artifact content must be carried using A2A `Part` variants
- Prometheus-specific fields must live in metadata conventions, not in a competing wire schema

## 5.2 URI-backed artifacts

URI-backed artifacts must use an A2A file part.

Example:

```json
{
  "artifactId": "<artifact_id>",
  "name": "Generated Report",
  "description": "PDF report for the corrosion run",
  "parts": [
    {
      "kind": "file",
      "file": {
        "uri": "file:///tmp/report.pdf",
        "mimeType": "application/pdf",
        "name": "report.pdf"
      }
    }
  ],
  "metadata": {
    "conversation_id": "<conversation_id>",
    "producer_agent_id": "corrosion-agent",
    "created_at": "2026-03-18T00:00:00+00:00"
  }
}
```

Requirements:

- URI-backed artifacts are the canonical representation for files and external resources
- the file part `file.uri` must be the authoritative locator for the content
- the file part `file.mimeType` must reflect the content actually available at that URI

## 5.3 Inline JSON artifacts

The system must support inline structured data using an A2A data part.

Example:

```json
{
  "artifactId": "<artifact_id>",
  "name": "Trace Matrix",
  "description": "Requirements traceability matrix",
  "parts": [
    {
      "kind": "data",
      "data": {
        "rows": []
      },
      "metadata": {
        "mime_type": "application/json",
        "json_type": "prometheus.requirements.trace_matrix.v1"
      }
    }
  ],
  "metadata": {
    "conversation_id": "<conversation_id>",
    "producer_agent_id": "requirements-agent",
    "created_at": "2026-03-18T00:00:00+00:00"
  }
}
```

Requirements:

- inline generic structured data must use an A2A data part, not a text-encoded JSON blob
- JSON parts must carry `metadata.mime_type = "application/json"`
- JSON parts must include `metadata.json_type`
- `json_type` must be stable, explicit, and versioned
- the frontend must use `json_type` to choose a specialized renderer when one exists
- when no specialized renderer exists, the frontend must fall back to a generic JSON viewer

Recommended `json_type` naming pattern:

- lowercase dotted identifier with an explicit version suffix
- example: `prometheus.analysis.corrosion_summary.v1`
- example: `prometheus.requirements.trace_matrix.v1`
- example: `prometheus.workflow.execution_trace.v1`

## 5.4 Prometheus conversation catalog

Prometheus still needs a conversation-scoped artifact catalog, but that catalog must be treated as a derived projection of A2A artifacts, not a separate wire format.

The catalog may expose normalized fields such as:

- `artifact_id`
- `conversation_id`
- `name`
- `description`
- `mime_type`
- `json_type`
- `uri`
- `producer_agent_id`
- `created_at`
- `tags`

Requirements:

- the catalog entry must be derived from the native A2A artifact
- the catalog exists for persistence, lookup, and UI state across turns
- the catalog must not become an alternate wire format between agents

## 5.5 Required Prometheus metadata conventions

The following metadata conventions are required on Prometheus-produced artifacts:

Artifact-level metadata:

- `conversation_id`
- `producer_agent_id`
- `created_at`

Optional artifact-level metadata:

- `tags`

Part-level metadata for JSON parts:

- `json_type`

Requirements:

- `conversation_id` is required because A2A artifact identity is task-scoped, while Prometheus needs conversation-scoped persistence
- `producer_agent_id` is required for provenance
- `created_at` is required for ordering, catalog hydration, and TTL management
- `json_type` is required for JSON visualization routing

## 5.6 Prohibited legacy dependency fields

New producers must not rely on any of the following for core semantics:

- top-level `content`
- `metadata.content`
- `metadata.data`
- `metadata.type`
- tag-only viewer routing
- URI-extension-only viewer routing

Those fields may still exist during migration, but they must not be required for correct interpretation of a conforming artifact.

## 6. Artifact Event Requirements

When an artifact is emitted in an A2A artifact slot, the payload itself must already be the native A2A artifact. Prometheus should not require an extra wrapper such as:

```json
{
  "artifact": { "...custom object..." }
}
```

Requirements:

- `result.artifacts[*]` should each contain one native A2A artifact
- Prometheus ingestion should normalize from native A2A artifacts directly
- Prometheus should not require a second custom artifact wrapper for conforming producers

## 7. Frontend Rendering Requirements

The frontend renderer must dispatch in this order:

1. explicit MIME metadata on the primary part
2. `metadata.json_type` for JSON parts

Requirements:

- media type is the primary renderer key
- `json_type` is the subtype key for JSON artifacts
- tags may be used for display or search, not as the primary rendering contract
- URI extensions may be used only as a temporary migration fallback, not as the required long-term contract

Expected behaviors:

- `application/pdf` -> PDF viewer
- canonical IFC media type adopted by the platform -> IFC viewer
- canonical Exodus media type adopted by the platform -> Exodus viewer
- `text/mermaid` -> Mermaid viewer
- `application/json` + known `json_type` -> specialized JSON viewer
- `application/json` + unknown `json_type` -> generic JSON viewer

## 8. Validation Requirements

Artifact validation must enforce:

- every Prometheus artifact is a valid native A2A artifact
- every artifact has exactly one primary part for current Prometheus usage
- every primary part has explicit MIME metadata
- JSON parts use `metadata.mime_type = "application/json"`
- JSON parts include `metadata.json_type`
- Prometheus metadata includes `conversation_id`, `producer_agent_id`, and `created_at`

Message validation must enforce:

- A2A request body is valid JSON
- final structured responses appear only in the canonical response location
- artifact payloads are not overloaded as alternate response envelopes

## 9. Migration Guidance

The current codebase still contains fallback-oriented behavior:

- layered A2A response extraction across status, artifacts, and history
- artifact rendering by MIME type, tags, URI extension, and metadata conventions
- ad hoc inline content paths for some plugins
- compatibility parsing for older text-encoded artifact payloads

Migration should converge on this order:

1. standardize the canonical response location
2. emit native A2A artifacts directly
3. map URI-backed outputs to A2A file parts
4. map inline structured JSON outputs to A2A data parts
5. add required Prometheus metadata conventions
6. update frontend rendering to use media type then `json_type`
7. remove producer reliance on metadata- and extension-based routing

## 10. Summary

The required long-term contract is:

- one canonical response envelope location
- native A2A artifacts as the only wire-level artifact format
- Prometheus metadata conventions layered on top for conversation scope and UI routing
- explicit media-type-driven rendering
- explicit `json_type` routing for JSON artifacts
- support for both URI-backed and inline JSON artifacts without inventing a parallel artifact transport
