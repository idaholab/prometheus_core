# Visualization plugins

The Chainlit frontend includes custom React elements for rendering specialized content. These are located in `frontend/public/elements/` and are rendered via Chainlit's `cl.CustomElement` API.

## ExodusViewer

Renders Exodus II simulation meshes using VTK.js.

**File:** `public/elements/ExodusViewer.jsx`

**What it does:** Displays 3D mesh data from Exodus II files with timestep animation, variable selection, color mapping, and interactive controls (orbit, zoom, pick).

**How to trigger it:**

1. **File upload**: User uploads an `.exo` or `.e` file in the chat. The frontend processes it through `components/exodus_integration.py`, which converts the mesh to VTP format using VTK and creates the viewer element.

2. **Agent artifact**: An agent returns an artifact with `_type: "exodus_dataset"`. The message handler creates the viewer from the artifact metadata.

**Supported formats:** `.exo`, `.e` (Exodus II)

**Props:**

| Prop | Type | Description |
|------|------|-------------|
| `datasetId` | string | Unique dataset identifier |
| `baseUrl` | string | URL prefix for VTP files (`/public/exodus-data/{id}`) |
| `metadata` | object | Timesteps, variables, bounds |
| `manifest` | object | File listing with VTP paths per timestep |
| `initialTimestep` | number | Starting timestep index |
| `initialVariable` | string | Initial variable to color by |
| `initialColorPreset` | string | Color map name (e.g., `coolToWarm`) |
| `height` | string | Viewer height (e.g., `500px`) |
| `showControls` | boolean | Show playback and variable controls |
| `allowPicking` | boolean | Enable point/cell selection |

**Python usage:**

```python
from components.exodus_integration import process_exodus_upload

dataset = await process_exodus_upload(Path("model.exo"))
viewer = dataset.to_chainlit_element()
await cl.Message(content="Mesh loaded", elements=[viewer]).send()
```

**Processing pipeline:** The Exodus file goes through a VTK pipeline (`components/exodus/vtk_pipeline.py`) that extracts geometry, variables, and timesteps into VTP (VTK PolyData) format. A manifest JSON file is generated listing all output files. The VTP files are written to `public/exodus-data/{id}/` for web access.

## IFCViewer

Renders IFC (Industry Foundation Classes) 3D building models using the ThatOpen Components (OBC) engine with THREE.js.

**File:** `public/elements/IFCViewer.jsx`

**What it does:** Displays 3D building/component models from IFC files with orbit controls, element selection, and property inspection.

**How to trigger it:**

1. **File upload**: User uploads an `.ifc` file. The frontend copies it to the public directory and creates a viewer element.

2. **Agent artifact**: An agent returns an artifact with `_type: "ifc_dataset"`.

**Supported formats:** `.ifc`

**Props:**

| Prop | Type | Description |
|------|------|-------------|
| `datasetId` | string | Unique dataset identifier |
| `fileUrl` | string | URL path to the IFC file |
| `filename` | string | Original filename |
| `height` | string | Viewer height |

**Python usage:**

```python
from components.ifc_integration import process_ifc_upload

dataset = await process_ifc_upload(Path("building.ifc"))
viewer = dataset.to_chainlit_element()
await cl.Message(content="IFC model loaded", elements=[viewer]).send()
```

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
export default function MyViewer({ data, height = "400px" }) {
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
