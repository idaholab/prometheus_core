# Artifacts

Artifacts are structured outputs produced by specialist agents. They can be JSON data, file references, 3D models, PDFs, or any other result type. Artifacts are tracked in a conversation-scoped registry and rendered by the frontend using appropriate viewers.

## Artifact reference model

Every artifact is described by an `ArtifactReference`:

```python
@dataclass
class ArtifactReference:
    artifact_id: str            # UUID
    conversation_id: str        # Conversation scope
    name: str                   # Display name
    description: str            # What this artifact contains
    uri: Optional[str]          # Location (deeplynx://, file://, http://, etc.)
    mime_type: Optional[str]    # Content type
    json_type: Optional[str]    # Semantic type for JSON artifacts
    json_body: Optional[Any]    # Inline structured content
    text_body: Optional[str]    # Inline text content
    size_bytes: Optional[int]
    producer_agent_id: Optional[str]
    created_at: str             # ISO 8601
    tags: List[str]
    metadata: Dict[str, Any]    # Arbitrary key-value pairs
```

Artifact references are stored in Redis (conversation-scoped hashes) with in-memory fallback when Redis is unavailable. Prometheus catalog payloads use snake_case field names such as `artifact_id`; camelCase names such as `artifactId` are only part of external A2A wire payloads and should be normalized at the boundary.

## Supported artifact types

| Type | mime_type | Rendered by | Description |
|------|-----------|-------------|-------------|
| JSON data | `application/json` | Text/table | Structured analysis results |
| IFC model | `application/ifc` | IFCViewer | 3D building/component model |
| Exodus mesh | `application/exodus` | MeshViewer | VTK mesh with variables/timesteps |
| STL mesh | `model/stl` | MeshViewer | VTK surface mesh (static geometry) |
| PDF report | `application/pdf` | Inline PDF viewer | Generated reports |
| Mermaid diagram | `text/mermaid` | MermaidViewer | Architecture/flow diagrams |
| Plain text | `text/plain` | Text display | Narrative responses |
| File | *(by extension)* | `cl.File` download | Downloadable files (`.csv`, `.xlsx`, `.zip`, `.tar`, `.gz`, `.txt`, `.log`, `.inp`, `.i`) |
| Reference | *(by tags)* | Citation markdown | Literature references and citations with source, section, and page metadata |
| Visualization | *(by tags)* | MeshViewer / IFCViewer / MermaidViewer | Generic visualization artifacts routed to a viewer by tags |

## Returning artifacts from an agent

### JSON artifact (automatic)

The simplest approach: return a dict from `process_analysis()`. The base class auto-wraps it as a JSON artifact:

```python
async def process_analysis(self, params, context, event_queue):
    result = {"corrosion_rate": 0.02, "unit": "mm/year", "confidence": 0.95}
    return result  # Auto-emitted as JSON artifact
```

### Explicit JSON artifact

For more control over name and metadata:

```python
async def process_analysis(self, params, context, event_queue):
    result = {"analysis": "detailed results..."}

    artifact_id = await self.send_json_artifact(
        context, event_queue,
        payload=result,
        name="corrosion_analysis_result",
    )

    return result
```

### File/URI artifact reference

For artifacts that live outside the agent (filesystem, HTTP, external storage):

```python
async def process_analysis(self, params, context, event_queue):
    # Generate a file
    output_path = "/tmp/model.ifc"
    generate_ifc_model(output_path)

    await self.send_artifact_reference(
        context, event_queue,
        name="Generated CAD Model",
        description="3D IFC model of the reactor vessel",
        uri=f"file://{output_path}",
        mime_type="application/ifc",
    )

    return {"status": "model_generated", "path": output_path}
```

### Links on an artifact

An agent can attach buttons to any artifact through `metadata["links"]`, a list
of `{"label": ..., "url": ...}`. The platform shows them on the artifact's viewer
and opens them in a new tab. Only absolute `http`/`https` URLs are kept (at most
5). Typical use: a page the agent itself serves for that artifact, such as an
interactive dashboard, or the job that produced it.

```python
await self.send_artifact_reference(
    context, event_queue,
    name="Run report",
    description="Baked results report",
    uri=f"file://{report_path}",
    mime_type="text/html",
    metadata={"links": [{"label": "Open interactive dashboard", "url": dashboard_url}]},
)
```

### A baked HTML report on an artifact

An artifact can carry a static HTML view of itself in `metadata["report"]`, a
`{"uri": ..., "deeplynx_file_id": ...}` that points at the HTML in DeepLynx
(or any `http`/`https` URL). The platform shows it inline in a sandboxed frame
(`GET /api/artifacts/{artifact_id}/report`), and the artifact itself stays the
download. A `file://` report is not shown: only shared storage is read, so the
producer can run on any host and any number of replicas.

```python
storage = ConnectionConfig.from_env()
async with AsyncStorageClient(storage) as client:
    html = await client.files.upload(html_path, name=html_path.name)
await self.send_deeplynx_artifact(
    context, event_queue,
    file_path=notebook_path,
    name=notebook_path.name,
    description="UQ notebook",
    storage_config=storage,
    mime_type="application/x-ipynb+json",
    metadata={
        "json_type": "prometheus.uq.result.v1",
        "report": {
            "uri": f"deeplynx://organizations/{storage.organization_id}"
                   f"/projects/{storage.project_id}/items/{html.id}",
            "deeplynx_file_id": html.id,
        },
    },
)
```

### Retrieving artifacts as files

Downstream agents should consume reusable artifacts through the shared
`PrometheusAgent.get_artifact_file_path()` helper:

```python
source_path = await self.get_artifact_file_path(
    params["artifact_id"],
    context=context,
    artifacts=params.get("artifacts"),  # optional catalog from the client-agent
)
```

The helper returns a readable local `Path` for every reusable artifact shape:

- URI-backed artifacts (`deeplynx://`, `http://`, `https://`, S3-style fsspec protocols, etc.) are downloaded into a deterministic cache directory.
- Inline JSON artifacts are written as formatted UTF-8 `.json` files in the cache.
- Inline text artifacts are written as UTF-8 `.txt` files in the cache.
- `file://` artifacts are not copied; the existing path is resolved, checked for readability, and allowed only under configured local roots.

Configuration:

- `PROMETHEUS_ARTIFACT_CACHE_DIR` sets the cache directory. Default: `/tmp/prometheus-artifact-cache`.
- `PROMETHEUS_ARTIFACT_FILE_ALLOWED_ROOTS` sets the local directories that `file://` artifacts may read, separated by the platform path separator (`:` on Linux/macOS).

### Status updates during long operations

For long-running analyses, send progress updates before emitting the final artifact:

```python
async def process_analysis(self, params, context, event_queue):
    await self.send_status_update(
        context, event_queue,
        state="working",
        message="Loading material database...",
        final=False,
    )

    data = load_data(params["material_id"])

    await self.send_status_update(
        context, event_queue,
        state="working",
        message="Running simulation (this may take a few minutes)...",
        final=False,
    )

    result = run_simulation(data)

    # The return value becomes the final artifact
    return result
```

## How artifacts are rendered in Chainlit

The frontend inspects artifact metadata and routes to the appropriate viewer:

1. **IFC files**: Rendered with `IFCViewer.jsx` -- a ThatOpen/OBC-based 3D viewer with orbit controls, section planes, and property inspection
2. **Mesh files (Exodus, STL)**: Rendered with `MeshViewer.jsx` -- a VTK.js-based mesh viewer. Exodus gets timestep playback, variable selection, and color presets; STL renders as static geometry (the viewer hides the timestep/variable controls when there are none)
3. **PDF files**: Rendered inline using Chainlit's built-in `cl.Pdf` element
4. **Mermaid diagrams**: Rendered with `MermaidViewer.jsx` using the Mermaid.js library
5. **JSON/text data**: Displayed as formatted text in the chat message
6. **File artifacts**: Rendered as a downloadable `cl.File` element for formats like `.csv`, `.xlsx`, `.zip`, `.log`, `.inp`
7. **Reference artifacts**: Rendered as formatted markdown citations with bold name, description, and source/section/page metadata
8. **Visualization artifacts**: Routed to MeshViewer, IFCViewer, or MermaidViewer based on tags (`exodus`/`stl`/`vtk`, `ifc`, `mermaid`)

The mapping from artifact to viewer happens in the message handler's `_classify_artifact()` function, which checks (in order):

1. `metadata.type` -- explicit type string (e.g., `"ifc"`, `"exodus"`, `"data"`, `"report"`, `"mermaid"`, `"file"`, `"reference"`, `"visualization"`)
2. URI file extension -- `.ifc`, `.exo`/`.e`, `.pdf`
3. Tags -- `"ifc"`, `"exodus"`, `"pdf"`, `"data"`, `"report"`, `"mermaid"`, `"reference"`/`"citation"`, `"visualization"`/`"vtk"`
4. File extension for downloads -- `.csv`, `.xlsx`, `.zip`, `.tar`, `.gz`, `.txt`, `.log`, `.inp`, `.i`
5. MIME type -- `model/ifc`, `application/pdf`, `application/json`, `text/markdown`, etc.

```python
# Classification logic in message_handler.py
artifact_type = _classify_artifact(uri, mime_type, tags, metadata)
# Returns: "ifc" | "exodus" | "pdf" | "data" | "report" | "mermaid" |
#          "file" | "reference" | "visualization" | "unknown"
```

## Artifact catalog

The client-agent maintains an artifact catalog per conversation. On each turn:

1. The frontend passes the current artifact catalog to the client-agent
2. Specialist agents can reference artifacts from previous steps (e.g., using a data agent's output as input to a corrosion agent)
3. New artifacts from the current turn are added to the catalog
4. The updated catalog is returned to the frontend and stored in the Chainlit session

This enables multi-step workflows where later agents consume earlier agents' outputs.
