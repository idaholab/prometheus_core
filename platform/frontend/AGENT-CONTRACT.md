# Prometheus Platform Agent Output Contract

**Version:** 1.2  
**Status:** Draft (Chainlit-era)  
**Audience:** Frontend (prometheus-frontend) + Backend agent authors

> **Superseded for the new API.** This describes the Chainlit `step.elements`
> pipeline. The standalone FastAPI backend defines its own JSON/SSE wire
> contract — see [`backend/CONTRACT.md`](../backend/CONTRACT.md)
> (machine definition: `backend/app/contract.py`). The backend now performs
> element/artifact classification server-side and hands the frontend `render_hint`s.
> Placement is now chosen per artifact too: an agent sets `metadata.display` to
> `panel` to show an artifact only in the side artifact panel (see "Artifact
> `display`" in `backend/CONTRACT.md`). The `display="inline"`-only rule below
> applies to the old Chainlit `step.elements` only.

This document defines how backend agents must emit elements so the frontend can render them without custom per-agent handling. The frontend maintains a `VIEWER_REGISTRY` keyed on element type and custom element name. As long as agents follow this contract, new agent outputs are automatically routed to the correct viewer.

---

## How the pipeline works

Every element attached to a Chainlit step lands in `step.elements[]` on the frontend. The frontend classifies each element by its `type` field (and for custom elements, its `name` field), looks up the viewer component in the registry, and renders it. If no viewer is registered for a type/name combination, a graceful fallback card renders with a download link : nothing crashes. This mirrors the behavior of the legacy upload pipeline, which also defaulted to a download fallback (`add_download: True`) for unhandled types.

**The frontend never inspects message text content to determine rendering.** All structured output must come through `step.elements`, not embedded in the message string.

---

## Standard element types

These are Chainlit built-in types. Use them for common file output.

### `cl.Pdf`
```python
cl.Pdf(name="report.pdf", display="inline", path="/tmp/report.pdf")
```
- `name` : filename shown to user (include `.pdf` extension)
- `display` : use `"inline"` always; sidebar/page modes are not supported
- `path` OR `url` : one is required; `path` is preferred for locally generated files

### `cl.Image`
```python
cl.Image(name="plot.png", display="inline", path="/tmp/plot.png")
```
- Same rules as `cl.Pdf`
- Supported MIME types: `image/png`, `image/jpeg`, `image/gif`, `image/webp`
- SVG: use `cl.File` with `mime="image/svg+xml"`, not `cl.Image`

### `cl.File`
```python
cl.File(name="model.ifc", display="inline", path="/tmp/model.ifc", mime="application/octet-stream")
```
- Use for any file type without a dedicated built-in (IFC, Exodus, CSV, etc.)
- Set `mime` accurately : the frontend uses it to route to the correct viewer
- Known MIME types with dedicated viewers: see Custom Elements section below

**Mime fallback behavior:** if `mime` is absent, empty, or a generic value (`application/octet-stream`, `binary/octet-stream`), the frontend falls back to routing by file extension from the `name` field. For example, a file named `model.ifc` with no mime set will still reach the IFC viewer. Setting mime explicitly is still preferred — extension fallback is a safety net, not the intended path.

### `cl.Text`
```python
cl.Text(name="summary", content="...", display="inline", language="markdown")
```
- For short inline text blocks that aren't the main message
- `language` hints the renderer (e.g. `"markdown"`, `"json"`, `"python"`)

---

## Custom elements

For structured interactive output that needs a purpose-built viewer, use `cl.CustomElement`. On the wire this arrives as `type: "custom"` — do not use any other type string. The `name` field determines which viewer component handles it. **Do not invent new names** without a corresponding frontend viewer being registered first : coordinate with the frontend team.

### Registered custom element names

| `name` | Purpose | Required `props` keys | Notes |
|---|---|---|---|
| `PlanViewer` | Execution plan approval | `steps: {title, description}[]`  |
| `DynamicForm` | Structured data collection | `fields: FormField[]`, `submitLabel?: string`  |
| `FollowUpSuggestions` | Clickable follow-up prompts | `suggestions: string[]`  |
| `IFCViewer` | 3D IFC model viewer | `url: string` | name unconfirmed, verify before use |
| `CollapsibleJson` | Raw JSON inspection | `data: object`, `label?: string`  |

#### Example: PlanViewer
```python
cl.CustomElement(
    name="PlanViewer",
    display="inline",
    props={
        "steps": [
            {"title": "Search literature", "description": "Query OSTI for relevant papers"},
            {"title": "Extract material properties", "description": "Parse Hastelloy N corrosion data"},
        ]
    }
)
```

#### Example: DynamicForm
```python
cl.CustomElement(
    name="DynamicForm",
    display="inline",
    props={
        "fields": [
            {"id": "material", "label": "Material", "type": "text", "required": True},
            {"id": "temp_range", "label": "Temperature range (°C)", "type": "text", "required": False},
        ],
        "submitLabel": "Submit"
    }
)
```

#### Example: FollowUpSuggestions
```python
cl.CustomElement(
    name="FollowUpSuggestions",
    display="inline",
    props={
        "suggestions": [
            "Show corrosion data for Hastelloy X",
            "Compare with Inconel 617",
            "Export as PDF report"
        ]
    }
)
```

---

## Attaching elements to a step

Elements must be passed to the step or message they belong to. Orphaned elements (emitted without an associated step) will not render.

```python
# Attach to a message
msg = cl.Message(content="Here is the analysis.", elements=[
    cl.Pdf(name="analysis.pdf", display="inline", path="/tmp/analysis.pdf"),
    cl.CustomElement(name="FollowUpSuggestions", display="inline", props={
        "suggestions": ["Run another analysis", "Export data"]
    })
])
await msg.send()
```

```python
# Attach to a step
async with cl.Step(name="Generate report") as step:
    step.elements = [
        cl.Pdf(name="report.pdf", display="inline", path="/tmp/report.pdf")
    ]
```

---

## Rules and constraints

**Always set `display="inline"`** : sidebar and page display modes are not implemented in the custom frontend.

**One element per logical output** : do not bundle multiple files into a single element. Emit one `cl.Pdf` per PDF, one `cl.Image` per image, etc. The frontend renders them as a list.

**No structured data in message text** : if your agent produces JSON or tabular data the user needs to interact with, wrap it in a `cl.CustomElement` with `name="CollapsibleJson"`. Do not embed raw JSON in the message string.

**File paths must be accessible** : the Chainlit backend serves elements via its own file endpoint. Paths must be on the local filesystem at step-send time. Remote URLs are supported via `url=` instead of `path=`.

**Do not emit elements from background tasks** : elements must be attached to a step that is currently active on the main thread. Background task elements will be silently dropped.

---

## Adding a new viewer (coordinate with frontend team)

If you need a new custom element type not listed above:

1. Agree on a `name` string and `props` shape with the frontend team before writing backend code
2. Frontend registers a viewer component for the new name : one-line change to `VIEWER_REGISTRY`
3. Backend emits `cl.CustomElement(name="<agreed name>", props={...})`
4. Update this document

The frontend fallback card (shown for unregistered names) will display the element's name and a download link in the interim, so partial progress is never invisible to the user.

---

## Currently unsupported (do not use)

- `cl.Audio` : no viewer registered
- `cl.Video` : no viewer registered  
- `display="side"` / `display="page"` : not implemented
- Nested elements (elements inside element props) : not supported

These can be added; raise a ticket with the frontend team.
