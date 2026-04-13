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
    uri: str                    # Location (file://, http://, etc.)
    mime_type: Optional[str]    # Content type
    size_bytes: Optional[int]
    producer_agent_id: Optional[str]
    created_at: str             # ISO 8601
    tags: List[str]
    metadata: Dict[str, Any]    # Arbitrary key-value pairs
```

Artifact references are stored in Redis (conversation-scoped hashes) with in-memory fallback when Redis is unavailable.

## Supported artifact types

| Type | mime_type | Rendered by | Description |
|------|-----------|-------------|-------------|
| JSON data | `application/json` | Text/table | Structured analysis results |
| IFC model | `application/ifc` | IFCViewer | 3D building/component model |
| Exodus mesh | `application/exodus` | ExodusViewer | VTK mesh with variables |
| PDF report | `application/pdf` | Inline PDF viewer | Generated reports |
| Mermaid diagram | `text/mermaid` | MermaidViewer | Architecture/flow diagrams |
| Plain text | `text/plain` | Text display | Narrative responses |
| File | *(by extension)* | `cl.File` download | Downloadable files (`.csv`, `.xlsx`, `.zip`, `.tar`, `.gz`, `.txt`, `.log`, `.inp`, `.i`) |
| Reference | *(by tags)* | Citation markdown | Literature references and citations with source, section, and page metadata |
| Visualization | *(by tags)* | ExodusViewer / IFCViewer / MermaidViewer | Generic visualization artifacts routed to a viewer by tags |

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
2. **Exodus files**: Rendered with `ExodusViewer.jsx` -- a VTK.js-based mesh viewer with timestep playback, variable selection, and color presets
3. **PDF files**: Rendered inline using Chainlit's built-in `cl.Pdf` element
4. **Mermaid diagrams**: Rendered with `MermaidViewer.jsx` using the Mermaid.js library
5. **JSON/text data**: Displayed as formatted text in the chat message
6. **File artifacts**: Rendered as a downloadable `cl.File` element for formats like `.csv`, `.xlsx`, `.zip`, `.log`, `.inp`
7. **Reference artifacts**: Rendered as formatted markdown citations with bold name, description, and source/section/page metadata
8. **Visualization artifacts**: Routed to ExodusViewer, IFCViewer, or MermaidViewer based on tags (`exodus`/`vtk`, `ifc`, `mermaid`)

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
