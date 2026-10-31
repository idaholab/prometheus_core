# backend wire contract (v1)

Human-readable spec for the standalone FastAPI backend's JSON/SSE API. The
authoritative machine definition is [`app/contract.py`](app/contract.py); this
document explains it and gives a JSON example per payload.

This **supersedes** the Chainlit-flavored
[`frontend/AGENT-CONTRACT.md`](../frontend/AGENT-CONTRACT.md) for the
new API. That document described how agents emit Chainlit `step.elements`; the new
frontend consumes the normalized shapes below instead — the backend does the
element/artifact classification and hands the frontend `render_hint`s.

## Principles

- **Own the contract.** These shapes mirror `prometheus_api`'s `ConversationRequest` /
  `ConversationResponse` but are defined independently. Normalization happens at the
  service boundary (task 04); base-image types never reach the wire.
- **`render_hint`, not raw dispatch.** The backend classifies each artifact and emits a
  `render_hint` so a thin frontend routes to the right viewer without re-implementing
  MIME / `json_type` / extension dispatch. Raw `mime_type` / `json_type` / `tags` ride
  along so the frontend can override.
- **Session-carried `conversation_id`.** The `conversation_id` lives in server-side
  session state (keyed by the auth JWT's session id), never in a request body.

## Status values

`ChatStatus` mirrors `prometheus_api.ConversationStatus`:

| status | meaning | key fields |
|---|---|---|
| `needs_info` | follow-up questions for the user | `followup_questions` |
| `plan_ready` | plan awaiting approval | `plan`, `auto_approve` |
| `executing` | plan execution in progress | `message` |
| `completed` | multi-step plan finished | `report`, `artifacts`, `recommended_materials`, `follow_up_suggestions` |
| `answer` | direct single-agent answer | `response_text`, `artifacts` |
| `recommendation` | direct recommendation | `response_text`, `recommended_materials` |
| `backgrounded` | turn detached to a task | `task_id` |
| `error` | request failed | `message` |

---

## `POST /api/sessions` → `SessionResponse`

Explicit session creation (not implicit-on-first-message). Returns the new
`conversation_id` and the chat-profile content.

Optional body: `{ "profile": "Beginner Chat", "bind_seq": 1759060000123 }`.
`bind_seq` orders session rebinds (this and `/resume`) by when the user clicked
rather than by when the request finished: the server applies a rebind only if its
`bind_seq` is greater than the last one applied to the session. The frontend sends
a strictly increasing, `Date.now()`-based value. Omitted → always applied. A
superseded create still returns `200` with a fresh `conversation_id`, but the
session stays where the newer rebind put it, so that id is not bound. A client that
has sent a newer rebind must discard the response.

```json
{
  "conversation_id": "c-8f2a…",
  "chat_intro": "Welcome to the Prometheus Platform.",
  "chat_suggestion_title": "What would you like to do today?",
  "workflow_suggestions": ["Design a nuclear system", "Run FTL Safety Analysis"],
  "auto_approve_steps": false
}
```

## `GET /api/config` → `ConfigResponse`

Static, non-session settings (no `conversation_id`).

```json
{
  "chat_intro": "Welcome to the Prometheus Platform.",
  "chat_suggestion_title": "What would you like to do today?",
  "workflow_suggestions": ["Design a nuclear system"],
  "auto_approve_steps": false,
  "max_upload_bytes": 104857600
}
```

## `POST /api/uploads` → `UploadDescriptor`

Multipart upload; staged toward DeepLynx (task 06). The returned descriptor is
echoed back in the next `ChatMessageRequest.upload_ids`.

```json
{ "upload_id": "u-1a2b", "name": "part.stl", "mime_type": "model/stl", "size_bytes": 40213 }
```

## `POST /api/chat/messages`

### Request — `ChatMessageRequest`

Mirrors the args `A2AClient.send()` accepts. `conversation_id` is **not** here.

```json
{
  "query": "Perform a thermal analysis of SS316 at 400C",
  "followup_answers": null,
  "plan_approved": false,
  "plan_rejected": false,
  "workflow_id": null,
  "upload_ids": [
    { "upload_id": "u-1a2b", "name": "part.stl", "mime_type": "model/stl", "size_bytes": 40213 }
  ]
}
```

A follow-up submission reuses the same endpoint with `followup_answers` populated
(keys are `FormField.id`s):

```json
{ "query": "Perform a thermal analysis of SS316", "followup_answers": { "temp_c": 400 } }
```

Plan approval / rejection:

```json
{ "query": "", "plan_approved": true }
```

### Response — `ChatMessageResponse`

One model covers every `status`; only the status-relevant fields are populated.

**`needs_info`** — `followup_questions` is a list of normalized `FormField`s:

```json
{
  "turn_id": "turn-01",
  "status": "needs_info",
  "message": "Additional information needed",
  "followup_questions": [
    {
      "id": "temp_c",
      "label": "Operating temperature?",
      "input_type": "number",
      "required": true,
      "options": null,
      "default": null,
      "help": "Degrees Celsius",
      "placeholder": null,
      "rows": null,
      "min": 0,
      "max": 1000,
      "step": null
    },
    {
      "id": "material",
      "label": "Material?",
      "input_type": "select",
      "required": true,
      "options": [
        { "label": "SS316", "value": "SS316" },
        { "label": "SS347", "value": "ss347" }
      ]
    }
  ]
}
```

**`plan_ready`** — `auto_approve` tells the frontend whether to show approve/reject buttons:

```json
{
  "turn_id": "turn-02",
  "status": "plan_ready",
  "message": "Here's my plan",
  "plan": { "steps": [{ "agent": "thermal-agent", "description": "…" }] },
  "auto_approve": false
}
```

**`executing`**:

```json
{ "turn_id": "turn-03", "status": "executing", "message": "Running step 2 of 4…" }
```

**`completed`** — report + artifacts (each with a `render_hint`) + suggestions:

```json
{
  "turn_id": "turn-04",
  "status": "completed",
  "report": "## Thermal Analysis\nSS316 at 400°C …",
  "artifacts": [
    {
      "artifact_id": "art-9",
      "name": "temperature_field.e",
      "mime_type": "application/x-exodus",
      "json_type": null,
      "description": "Steady-state temperature field",
      "uri": "deeplynx://…",
      "tags": ["mesh", "thermal"],
      "json_body": null,
      "render_hint": "mesh",
      "producer_agent_id": "thermal-agent",
      "created_at": "2026-08-10T12:00:00Z"
    }
  ],
  "recommended_materials": ["SS316", "SS347"],
  "follow_up_suggestions": ["Compare against SS347", "Export the mesh"]
}
```

**`answer`**:

```json
{ "turn_id": "turn-05", "status": "answer", "response_text": "The yield strength is …", "artifacts": null }
```

**`recommendation`**:

```json
{ "turn_id": "turn-06", "status": "recommendation", "response_text": "Use SS347 because …", "recommended_materials": ["SS347"] }
```

**`backgrounded`** — the server registers `task_id` as awaited; progress arrives on the SSE stream:

```json
{ "turn_id": "turn-07", "status": "backgrounded", "task_id": "bg-42", "message": "This is running in the background." }
```

**`error`**:

```json
{ "turn_id": "turn-08", "status": "error", "message": "The thermal agent is unavailable." }
```

### Artifact `render_hint` values

This table is the authoritative enum, mirroring the `RenderHint` `Literal` in
[`app/contract.py`](app/contract.py) exactly (a contract test asserts they stay in
lockstep). Note two folds: SVG (`image/svg+xml`) classifies as `image`, and the
`data` tag folds into `json` — there is **no** separate `svg` or `data` hint. CSV/TSV
(`text/csv`, `text/tab-separated-values`) classifies as `table`, **not** `json` or `file`.

| `render_hint` | viewer | typical source |
|---|---|---|
| `pdf` | PDF viewer | `application/pdf` |
| `image` | image | `image/png`, `image/jpeg`, `image/svg+xml` (SVG folds in), … |
| `json` | CollapsibleJson | `application/json`, inline `json_body` (CSV/TSV → `table`, not JSON) |
| `ifc` | IFCViewer | `model/ifc`, `.ifc` |
| `mesh` | MeshViewer | Exodus (`application/x-exodus`, `.exo`/`.e`), STL |
| `mermaid` | MermaidViewer | `text/x-mermaid` |
| `thermal` | ThermalAnalysisViewer | `json_type == prometheus.thermal_analysis.result.v1` |
| `uq` | UQDashboard (baked notebook report) | `json_type == prometheus.uq.result.v1` |
| `report` | markdown (rendered inline) | `text/markdown`, `text/plain`, `.md` |
| `code` | source text, syntax-highlighted (rendered inline, not Markdown) | YAML (`application/yaml`, `application/x-yaml`, `text/yaml`, `text/x-yaml`, `.yaml`/`.yml`); MOOSE input (`.i` or the vendor `text/x-moose` MIME); and source/config files by MIME or extension: Python, TOML, INI/`.cfg`/`.conf`, XML (`.xml`/`.xsd`/`.xdmf`), C/C++, Fortran, CMake, Makefile, shell, Dockerfile, SQL, JavaScript/TypeScript, diff/patch, `.jsonc`. Whole file names `Dockerfile`, `Containerfile`, `Makefile`, `GNUmakefile`, `CMakeLists.txt` also route here. A source name or extension wins over `text/plain`/`text/markdown` (which would otherwise be `report`), except the generic `.txt`/`.log` names: those reach `code` only when the MIME type does not decide (no MIME, or a generic or unrecognized one), so default-named text replies (`artifact.txt`) stay `report`. `application/json` / `.json` stay `json`. |
| `table` | sortable table with a raw-text toggle (first 1000 rows shown; the full file via download) | `text/csv`, `application/csv`, `text/tab-separated-values`, `.csv`/`.tsv` (also wins over `report` when `text/plain` or `text/markdown` is paired with a `.csv`/`.tsv` name; the MIME wins over a `data` tag) |
| `reference` | citation card | `reference`/`citation` tag; source/section/page in `citation` |
| `file` | download | CAD/STEP, `application/octet-stream`, zip/gzip |
| `unknown` | download fallback | anything unclassified |

The classifier lives in `classify_render_hint` / `to_artifact_meta`
(`app/services/artifacts.py`); the frontend may override using the raw
`mime_type` / `json_type` / `tags` fields.

For `reference` artifacts, `ArtifactMeta.citation` carries `{source, section, page}`
(lifted from the raw artifact `metadata`) so the frontend can render a citation card:

```json
{
  "artifact_id": "ref-3",
  "name": "ASME BPVC II-D",
  "description": "Allowable stress table",
  "uri": "https://…",
  "tags": ["reference"],
  "render_hint": "reference",
  "citation": { "source": "ASME BPVC", "section": "II-D", "page": "42" }
}
```

Any artifact may carry `ArtifactMeta.links`: buttons the producing agent attaches
(raw `metadata.links`), each `{label, url}`, opened in a new tab. Only absolute
`http`/`https` URLs are kept, at most 5, labels up to 80 characters; anything else
is dropped. Use it to point at a page the agent serves for that artifact (e.g. an
interactive dashboard) or at the job that produced it.

```json
"links": [{ "label": "Open interactive dashboard", "url": "http://localhost:8042/console/run-7" }]
```

---

## `GET /api/events` — Server-Sent Events

Per-session SSE stream (task 05). Session is identified by the auth JWT. Each JSON
event is a discriminated union on `type`; a heartbeat is a bare SSE **comment**
line (`: ping`), not a JSON event.

The `event:` name is the JSON `type`, so the browser can
`addEventListener("status" | "task_progress" | "task_done", …)`.

**`status`** — progress for the in-flight turn. `history` is the accumulated,
consecutive-duplicate-suppressed list of status lines for this turn (drives the running
step list); `message` is the latest line:

```
event: status
data: {"type":"status","turn_id":"turn-04","message":"Invoking thermal-agent…","history":["Understanding query","Planning","Invoking thermal-agent…"]}
```

**`task_progress`** — progress for a detached (backgrounded) task:

```
event: task_progress
data: {"type":"task_progress","task_id":"bg-42","message":"Step 3 of 5…"}
```

**`task_done`** — terminal event for a detached task. `completed` carries the mapped
final response in `response`; non-completed terminal states (failed/canceled/rejected)
carry a human-readable `message` and a null `response`:

```
event: task_done
data: {"type":"task_done","task_id":"bg-42","state":"completed","response":{"turn_id":"bg-42","status":"completed","report":"…"}}
data: {"type":"task_done","task_id":"bg-43","state":"failed","message":"Background task ended (failed).","response":null}
```

**heartbeat** (comment line, ignored by JSON parsers):

```
: ping
```

**Failure and close.** The server subscribes to Valkey before it commits the response:

- If that subscribe fails, the route answers `503` with no stream. `EventSource` treats a
  non-2xx answer as final: `readyState` becomes `CLOSED` and the browser does not retry.
- If the Valkey relay for the session dies after the `200`, the server ends the stream
  cleanly. `EventSource` then reconnects by itself, and the new request subscribes again.

---

## `GET /api/artifacts/{artifact_id}/content`

Resolves `deeplynx://` / remote URIs and streams the artifact bytes with the
correct `Content-Type` (task 07). Replaces the frontend's old
`_render_pdf_artifact` / `_render_remote_file_artifact` / `_render_download_artifact`
download paths.

## `GET /api/artifacts/{artifact_id}/report`

Streams the baked HTML report a producer attached in `metadata.report`
(`ArtifactMeta.has_report`), resolved from DeepLynx or `http(s)` like `/content`.
Served inline with `Content-Security-Policy: sandbox allow-scripts ...`, so the
report's scripts run in an opaque origin. `404` when the artifact has no report in
shared storage, `502` when storage cannot be reached.

## Chat history

Redis-backed (task 08; chat-history feature). Every conversation lives in the
client-agent's `conversation:{id}` document; a small backend-owned
`conv:meta:{id}` hash carries user edits (rename, soft delete) so the
client-agent's whole-document rewrite on every turn can never clobber them.
Every per-conversation route below is scoped to the caller's own conversations
(`user:convs:{user}`, checked via `ConversationStateClient.owns`) and returns
**404** — not 403 — when the caller doesn't own the id, so a guess can't even
confirm the id exists.

### `GET /api/conversations/recent` → `ConversationHistoryResponse`

`title` is the effective title: a user rename (`title_override`) wins over the
client-agent's LLM-generated title (set once, from the `small` model, on the
first turn — see `agents/client-agent/orchestrator/chat_flow.py`), which wins
over the raw first query. Soft-deleted conversations are excluded. `pending`
is true while a turn is actively running against that conversation right now
(`agent:status:{id}.final is False`) — a conversation the caller isn't
currently viewing may still have work in flight. A new conversation is listed
from the start of its first turn, with the raw first query as its `title` and
`pending: true`, until the turn ends and the LLM-generated title lands.

```json
{
  "available": true,
  "conversations": [
    {
      "conversation_id": "c-8f2a…",
      "title": "Corrosion rate of SS316 in seawater",
      "query": "What is the corrosion rate of SS316 in seawater?",
      "status": "completed",
      "timestamp": "2026-09-01T12:00:00Z",
      "pending": false
    }
  ]
}
```

### `GET /api/conversations/{id}` → `ConversationDetailResponse`

A past conversation's normalized transcript (`conversation_history` filtered
to `role: user|assistant` turns) plus its artifact catalog, shaped the same way
a live turn's `artifacts` are. The catalog leaves out user uploads
(`metadata.source: user-upload`); the session catalog keeps them.

Messages are in time order, so the reply of a turn that ran in the background can
follow later turns. Each message carries `artifact_ids`: the artifacts that turn
produced, which the client-agent records on the reply. Render a restored turn from its own
`artifact_ids`, resolved in `artifacts`. Never render the whole catalog. An id
that `artifacts` does not hold (a user upload) is not rendered. User turns, and
turns stored before the ids were recorded, have an empty list.

```json
{
  "conversation_id": "c-8f2a…",
  "title": "Corrosion rate of SS316 in seawater",
  "profile": "",
  "auto_approve_steps": false,
  "messages": [
    { "role": "user", "content": "What is the corrosion rate of SS316 in seawater?", "timestamp": "…", "artifact_ids": [] },
    { "role": "assistant", "content": "## Corrosion Analysis\n…", "timestamp": "…", "artifact_ids": ["a-41c9…"] }
  ],
  "artifacts": [{ "artifact_id": "a-41c9…", "name": "corrosion_rate.json", "mime_type": "application/json", "description": "", "tags": [], "render_hint": "json", "…": "…" }]
}
```

### `POST /api/conversations/{id}/resume` → `ConversationDetailResponse`

Rebinds the caller's session (`SessionState.conversation_id` + `artifacts`) to
this conversation and returns the same detail shape as `GET /{id}` — so the
frontend can render history and resume in one round-trip. The **next**
`POST /api/chat/messages` continues this conversation rather than starting a
fresh one.

Optional body: `{ "bind_seq": 1759060000123 }` — see `POST /api/sessions`. A
resume superseded by a newer rebind still returns `200` with the detail, but
leaves the session where the newer rebind put it; the frontend discards it.

### `PATCH /api/conversations/{id}` → `ConversationSummary`

Body: `{ "title": "New title" }` (rejects empty/whitespace-only with 422). Sets
`conv:meta:{id}.title_override`.

### `DELETE /api/conversations/{id}` → `204 No Content`

Soft delete: sets `conv:meta:{id}.hidden`, which excludes the conversation from
`recent`. `GET /api/conversations/{id}` and `/resume` then answer `404`, so a tab
that still remembers the id starts a clean chat instead of reopening it. The
underlying `conversation:{id}` document (and its artifacts) are left untouched.

### `GET /api/conversations/{id}/tasks` → `ConversationTasksResponse`

The conversation's background-task tree: the client-agent's Task Graph
(`tasks:graph|roots|node:{id}` in Valkey), as JSON. It's the structured counterpart of the
`/tasks` slash command. Each root is one chat turn that dispatched a specialist,
and its `children` are those skill dispatches (nested further for nested dispatch).
Roots are newest first. Running and finished tasks are both returned until their
nodes expire (24 h by default); filter on `state` / `is_background` client-side.

`state` is the effective A2A task state after children percolate up
(`submitted`, `working`, `input-required`, `completed`, `failed`, `canceled`,
`rejected`); `own_state` is the node's own. `is_background` marks a turn the
client-agent detached (and the skill that asked for it). `skill` is the
dispatched skill id and identifies what a child node runs. `agent` is reserved for
the serving agent; the client-agent does not record it yet, so it is `null`.
`available: false` with an empty `tasks` means Valkey is unreachable (still a
`200`, matching `recent`). A soft-deleted or unowned conversation answers `404`.

```json
{
  "available": true,
  "conversation_id": "c-8f2a…",
  "tasks": [
    {
      "task_id": "t_3c1d…",
      "parent_task_id": null,
      "agent": null,
      "skill": null,
      "title": "Predict the corrosion rate of SS316 in seawater",
      "state": "working",
      "own_state": "working",
      "is_background": false,
      "waiting_on": ["t_9e4b…"],
      "created_at": "2026-09-01T12:00:00+00:00",
      "started_at": "2026-09-01T12:00:00+00:00",
      "updated_at": "2026-09-01T12:00:45+00:00",
      "finished_at": null,
      "last_status_message": "waiting on predict_corrosion_rate — Fitting rate model…",
      "progress": null,
      "result_ref": null,
      "error": null,
      "children": [
        {
          "task_id": "t_9e4b…",
          "parent_task_id": "t_3c1d…",
          "agent": null,
          "skill": "predict_corrosion_rate",
          "title": "predict_corrosion_rate",
          "state": "working",
          "…": "…",
          "last_status_message": "Fitting rate model…",
          "children": []
        }
      ]
    }
  ]
}
```
