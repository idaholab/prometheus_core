# Visualization plugins

> **Note:** The Chainlit frontend has been removed; the platform's frontend is now the React
> app in `frontend/`. Current viewers live in `frontend/src/features/artifacts/viewers/` (with some custom-element
> JSX still in `frontend/public/elements/`) and are driven by the backend's artifact payloads.
> The `cl.CustomElement` API and the Python integration-module workflow described below are from
> the removed Chainlit frontend and are retained here only as historical reference.

The former Chainlit frontend included custom React elements for rendering specialized content, located in `frontend/public/elements/` and rendered via Chainlit's `cl.CustomElement` API.

> **Future:** letting *agents* ship their own viewers (rendered in a sandboxed iframe, not baked into the
> frontend) is designed in [`agent-provided-plugins.md`](../../dev-docs/agent-provided-plugins.md).

## MeshViewer

Renders 3D meshes using VTK.js. A single source-agnostic viewer for **Exodus II** and **STL** files (and any future format that converts to VTP).

**File:** `public/elements/MeshViewer.jsx`

**What it does:** Displays 3D mesh data with interactive controls (orbit, zoom, pick). It is driven by a manifest of VTP files and adapts to the source: with multiple timesteps it shows playback controls; with field variables it shows a variable selector and colorbar; with neither (e.g. an STL) it just renders the geometry with solid shading.

**How to trigger it:**

1. **File upload**: A user uploads a mesh file in the chat:
   - `.exo` / `.e` → converted via `components/exodus_integration.py`.
   - `.stl` → converted via `components/stl_integration.py`.
   Both convert the mesh to VTP using the shared VTK pipeline and create the viewer element.

2. **Agent artifact**: An agent returns an artifact. Either a converted-dataset result with `_type: "mesh_dataset"`, or a plain file artifact whose `mime_type` is recognized (`application/exodus` for Exodus, `model/stl` for STL) — the matching plugin converts it and creates the viewer.

**Supported formats:** `.exo`, `.e` (Exodus II); `.stl` (STL, ASCII or binary).

**Props:**

| Prop | Type | Description |
|------|------|-------------|
| `datasetId` | string | Unique dataset identifier |
| `baseUrl` | string | URL prefix for VTP files (`/public/mesh-data/{id}`) |
| `title` | string | Header label (e.g., `Exodus Viewer`, `STL Viewer`; defaults to `Mesh Viewer`) |
| `metadata` | object | Timesteps, variables, bounds, counts |
| `manifest` | object | File listing with VTP paths per timestep |
| `initialTimestep` | number | Starting timestep index |
| `initialVariable` | string | Initial variable to color by (`null` for variable-less meshes like STL) |
| `initialColorPreset` | string | Color map name (e.g., `coolToWarm`) |
| `height` | string | Viewer height (e.g., `500px`) |
| `showControls` | boolean | Show playback and variable controls |
| `allowPicking` | boolean | Enable point/cell selection |

**Python usage:**

```python
from components.exodus_integration import process_exodus_upload
from components.stl_integration import process_stl_upload

dataset = await process_exodus_upload(Path("model.exo"))   # or: process_stl_upload(Path("part.stl"))
viewer = dataset.to_chainlit_element()                      # → a MeshViewer element
await cl.Message(content="Mesh loaded", elements=[viewer]).send()
```

Both return a `MeshDataset` (`components/mesh_view.py`) whose `to_chainlit_element()` yields the shared `MeshViewer`.

**Processing pipeline:** The input goes through a VTK pipeline that extracts geometry (and, for Exodus, variables/timesteps) into VTP (VTK PolyData) format, writing a `manifest.json` listing the output files. STL is the simplest case — a single static surface, one VTP, no variables. VTP files are written to `public/mesh-data/{id}/` for web access. Exodus conversion lives in `components/exodus/vtk_pipeline.py`; STL reuses its polydata helpers in `components/stl_integration.py`.

## IFCViewer

Renders IFC (Industry Foundation Classes) building models in the browser with the ThatOpen
Components engine and THREE.js. The model file is parsed in the browser by web-ifc; nothing is
converted on the server.

**Code:** `frontend/src/features/artifacts/viewers/ifc/`

**How an artifact reaches it:** the backend gives an artifact the `ifc` render hint when it has the
`ifc` tag, the MIME type `model/ifc` or `application/ifc`, or a file name ending in `.ifc`
(`backend/app/services/artifacts.py`). The frontend (`artifactAdapter.ts`) then mounts the viewer
with the artifact's content URL as `fileUrl` and its name as `filename`.

**What it shows:**

- **Visibility panel:** a flat toggle for each element category the model has (floors, beams, doors,
  windows and so on). Walls, Roof and Columns become trees when their elements have pieces: each
  insulated-metal-panel face with its skins and core, the flashing, and each column with its
  base-plate pieces. Equipment lists every item, and Pipes lists each pipe run with its segments.
- **Controls panel:** Reset View, Top, Front and Side; a pan toggle (with a mouse-control legend);
  a perspective/orthographic toggle; and an IFC download.
- **Theme:** the canvas background follows the app's light or dark theme.

**Where it comes from:** the viewer is copied from Alchemy (`alchemy-frontend/src/components/viewer`
in the Alchemy repository), not forked. Alchemy's team adds features there, and we copy them over.
The last copy (PPLT-322) took Alchemy's version from 2026-10-06.

| File | Origin |
|------|--------|
| `IFCViewer.tsx`, `IFCViewerEngine.ts`, `ViewerOverlayPanels.tsx`, `treeGrouping.ts`, `visibilityCategories.ts`, `modelViewerTypes.ts` | Alchemy's files, with our license header. We add one thing: `setBackground` in the engine and the viewer handle, for the theme. |
| `IFCViewerElement.tsx` | Ours. It wires the panels to the viewer the way Alchemy's `StepModelViewer.tsx` does, and adds the theme, the chat layout and the download. |
| `IFCViewerEngine.dom.test.tsx` | Alchemy's `IFCViewerEngine.test.ts`, with its mock setup from `tests/fixtures/viewerEngine.fixtures.ts` folded in. It checks that the Walls and Roof toggles find the names Alchemy's generator writes. |
| `IFCViewerElement.dom.test.tsx` | Ours. It checks the canvas background follows the theme. |

**Updating it from Alchemy:**

1. Compare Alchemy's viewer folder with ours, ignoring our license header, to see what changed.
2. Copy the changed files over ours, with the license header on top.
3. Add `setBackground` back to `IFCViewerEngine.ts` and to the handle in `IFCViewer.tsx`, if the new
   files dropped it.
4. If Alchemy's `StepModelViewer.tsx` wires a new control or section, wire it the same way in
   `IFCViewerElement.tsx`, and add any new handle methods to the stub in
   `IFCViewerElement.dom.test.tsx`.
5. Copy Alchemy's engine tests again if they changed, then run `make check` in `frontend/`.
6. Compare the two viewers with one model. Alchemy's backend makes one without an LLM: post one of
   its inputs in `alchemy-backend/tests/fixtures/input/` (for example
   `tc_and_sg_and_pumps_in_two_buildings.json`) to its `/api/transform`, then download
   `/api/result/<task_id>/ifc`. Open the file in the viewer playground and in Alchemy, in both
   themes, and put the screenshots in the PR.

**Not ported:** Alchemy's OBJ viewer, which has the same panels (PPLT-462). Our STL and Exodus files
go to the MeshViewer.

## MermaidViewer

Renders Mermaid.js diagrams inline in chat messages.

**File:** `public/elements/MermaidViewer.jsx`

**What it does:** Takes Mermaid diagram syntax and renders it as an SVG diagram.

**How to include diagrams in agent responses:** Agents can include Mermaid diagrams in their response text. The frontend detects Mermaid code blocks and renders them with the MermaidViewer.

**Props:**

| Prop | Type | Description |
|------|------|-------------|
| `chart` | string | Mermaid diagram syntax |

**Python usage:**

```python
diagram = """
graph TD
  A[Input] --> B[Process]
  B --> C[Output]
"""
viewer = cl.CustomElement(name="MermaidViewer", props={"chart": diagram})
await cl.Message(content="Analysis flow:", elements=[viewer]).send()
```

## DynamicForm

Renders configurable forms for collecting structured input from users.

**File:** `public/elements/DynamicForm.jsx`

**What it does:** Displays a form with typed fields (text, number, select, checkbox, date, etc.), validation rules, help text, and an optional timeout countdown. Used by agents to request structured input when free-text is insufficient.

**How agents trigger it:** An agent returns a `needs_info` response with a form definition. The frontend renders the DynamicForm and sends the user's responses back as `followup_answers`.

**Supported field types:** `text`, `textarea`, `select`, `checkbox`, `number`, `email`, `password`, `date`, `datetime`

**Props:**

| Prop | Type | Description |
|------|------|-------------|
| `fields` | array | Field definitions with type, label, validation |
| `title` | string | Form title |
| `description` | string | Form description |
| `submitLabel` | string | Submit button text |
| `timeout` | number | Optional timeout in seconds |

## FollowUpSuggestions

Renders clickable suggestion cards for quick actions.

**File:** `public/elements/FollowUpSuggestions.jsx`

**What it does:** Displays a row of suggestion cards. Clicking a card inserts its text as a chat message.

**Props:**

| Prop | Type | Description |
|------|------|-------------|
| `suggestions` | array | List of suggestion strings |
| `title` | string | Section title |

**Used at:** Chat start (shows workflow suggestions from `config.yml`) and after agent responses that include follow-up options.

## PlanViewer

Renders execution plans with step-by-step visualization and status tracking.

**File:** `public/elements/PlanViewer.jsx`

**What it does:** Displays a multi-step execution plan returned by the client-agent when `status == "plan_ready"`. Shows step names, descriptions, and real-time status indicators (pending, running, completed, failed) during plan execution.

**How to trigger it:** The message handler renders it automatically when the client-agent returns a `plan_ready` response.

**Props:**

| Prop | Type | Description |
|------|------|-------------|
| `plan` | object | Plan object with `steps` array from ConversationResponse |
| `stepStatuses` | object | Map of step index to status string (`pending`, `running`, `completed`, `failed`) |

**Python usage:**

```python
plan_viewer = cl.CustomElement(
    name="PlanViewer",
    display="inline",
    props={"plan": response.plan, "stepStatuses": {}},
)
await cl.Message(content="Execution plan:", elements=[plan_viewer]).send()
```

## Adding a new visualization plugin

1. **Create the JSX component** in `frontend/public/elements/`:

```jsx
// MyViewer.jsx
// NOTE: Chainlit injects `props` into scope as a global — it is NOT a function
// argument. Do NOT write `function MyViewer(props)` / destructure args: a
// parameter shadows the injected global and every prop reads as undefined.
export default function MyViewer() {
  const data = props.data;
  const height = props.height || "400px";
  // Render your visualization
  return <div style={{ height }}>{/* ... */}</div>;
}
```

2. **Create a Python integration module** in `frontend/components/`:

```python
# my_viewer_integration.py
import chainlit as cl
from dataclasses import dataclass

@dataclass
class MyDataset:
    dataset_id: str
    data: dict

    def to_chainlit_element(self) -> cl.CustomElement:
        return cl.CustomElement(
            name="MyViewer",
            props={"data": self.data, "height": "500px"},
            display="inline",
        )

    def to_result_dict(self) -> dict:
        return {"_type": "my_dataset", "dataset_id": self.dataset_id, "data": self.data}
```

3. **Add artifact type detection** in the message handler to route the new type to your viewer.

4. **Bundle any JS dependencies** if needed. The IFC and VTK viewers use pre-built bundles in `public/js/`. Use the build scripts in `public/js/{library}/build.mjs` as examples.
