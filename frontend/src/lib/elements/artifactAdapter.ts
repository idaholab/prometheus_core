/**
 * Artifact adapter (frontend cutover Step 05).
 *
 * Maps a wire `ArtifactMeta` (backend contract) onto the app's `AnyElement`
 * shape so the existing `ElementRenderer` / `VIEWER_REGISTRY` route it to a viewer
 * with **no changes to the viewers themselves**. This is the seam that replaces the
 * old Chainlit `render_artifacts()` element construction.
 *
 * The backend has already done MIME/json_type/tag/extension dispatch and handed us a
 * `render_hint`; this function turns that hint into an element the classifier
 * (`classifyElement`) will recognize:
 *
 *   - file bytes (image/pdf/ifc/file/unknown) → `element.url` points at the content
 *     proxy `GET /api/artifacts/{id}/content`; viewers fetch from there.
 *   - inline structured data (json/thermal) → props built from `json_body`.
 *   - report/reference → dedicated lightweight viewers (markdown / citation card).
 *
 * Notes on the two gaps carried over from the Chainlit stack:
 *   - **mesh**: the old app rendered Exodus/STL via a Chainlit-side VTK→VTP pipeline
 *     that produced a `baseUrl` + `manifest`. The backend has no such pipeline
 *     (the CONTRACT example ships `json_body: null` for a mesh artifact), so unless a
 *     manifest arrives inline we degrade to a file download rather than mount a viewer
 *     with nothing to show. Restoring interactive mesh rendering is a backend follow-up.
 *   - **mermaid**: no agent currently emits mermaid artifacts, and the diagram source
 *     is not a wire field. We extract it best-effort from `json_body`; an empty source
 *     surfaces the viewer's own "no diagram" state.
 */

import { api } from "@/lib/api/client";
import type { ArtifactMeta } from "@/lib/api/types";
import { languageForArtifact } from "@/lib/highlight/language";
import { delimiterFor } from "@/lib/table/csv";
import type { AnyElement } from "./elements";

/** Best-effort mermaid diagram source from an inline body (string or `{diagram|chart|content}`). */
function mermaidSource(body: unknown): string {
  if (typeof body === "string") return body;
  if (body && typeof body === "object") {
    const o = body as Record<string, unknown>;
    for (const key of ["diagram", "chart", "content"]) {
      if (typeof o[key] === "string") return o[key] as string;
    }
  }
  return "";
}

/** A mesh body is renderable only if it carries the VTP manifest the MeshViewer needs. */
function meshManifestProps(body: unknown): Record<string, unknown> | null {
  if (body && typeof body === "object") {
    const o = body as Record<string, unknown>;
    if (o.baseUrl || o.manifest || o.datasetId) return o;
  }
  return null;
}

/** Convert one wire artifact into a viewer-ready element. */
export function artifactToElement(artifact: ArtifactMeta): AnyElement {
  const element = buildElement(artifact);
  // Stamp the unique artifact id into props so `dedupeElements` keys on it:
  // `resourceSignature` derives a custom element's identity from `props.artifact_id`
  // (among others), and several viewers carry no other distinguishing prop — without
  // this, two IFC/mermaid/report artifacts sharing a component name would collapse to one.
  element.props = { ...(element.props ?? {}), artifact_id: artifact.artifact_id };
  return element;
}

function buildElement(artifact: ArtifactMeta): AnyElement {
  const url = api.artifactContentUrl(artifact.artifact_id);
  const name = artifact.name || artifact.artifact_id;
  const base = { id: artifact.artifact_id, name };

  switch (artifact.render_hint) {
    case "image":
      return { ...base, type: "image", mime: artifact.mime_type ?? undefined, url };

    case "pdf":
      return { ...base, type: "pdf", url };

    case "ifc":
      // IFCViewer loads the raw .ifc in-browser (ThatOpen) from a URL; the content
      // proxy resolves the staged file:// upload and streams it inline.
      return {
        ...base,
        type: "custom",
        name: "IFCViewer",
        url,
        props: { fileUrl: url, filename: artifact.name || "model.ifc" },
      };

    case "mesh": {
      const manifest = meshManifestProps(artifact.json_body);
      if (manifest) {
        return {
          ...base,
          type: "custom",
          name: "MeshViewer",
          props: { ...manifest, title: artifact.name || "Mesh Viewer" },
        };
      }
      // No inline VTP manifest (see module note) → offer the raw file for download.
      return { ...base, type: "file", url, props: { description: artifact.description } };
    }

    case "mermaid":
      return {
        ...base,
        type: "custom",
        name: "MermaidViewer",
        props: { diagram: mermaidSource(artifact.json_body), title: artifact.name },
      };

    case "json":
      return {
        ...base,
        type: "custom",
        name: "CollapsibleJson",
        props: { data: artifact.json_body, name: artifact.name },
      };

    case "thermal":
      return {
        ...base,
        type: "custom",
        name: "ThermalAnalysisViewer",
        props: {
          name: artifact.name || "thermal_analysis",
          description: artifact.description,
          analysis: artifact.json_body ?? {},
        },
      };

    case "report":
      return {
        ...base,
        type: "custom",
        name: "ReportViewer",
        // Inline body when present; otherwise ReportElement fetches markdown from `url`.
        props: {
          markdown: typeof artifact.json_body === "string" ? artifact.json_body : "",
          title: artifact.name,
          url,
        },
      };

    case "code":
      return {
        ...base,
        type: "custom",
        name: "CodeViewer",
        // Inline body when present; otherwise CodeElement fetches source from `url`.
        props: {
          source: typeof artifact.json_body === "string" ? artifact.json_body : "",
          title: artifact.name,
          url,
          language: languageForArtifact(artifact),
        },
      };

    case "table":
      return {
        ...base,
        type: "custom",
        name: "TableViewer",
        // Inline body when present; otherwise TableElement fetches the text from `url`.
        props: {
          source: typeof artifact.json_body === "string" ? artifact.json_body : "",
          title: artifact.name,
          url,
          // Only TSV is known up front; CSV-ish delimiters are detected from the content.
          delimiter: delimiterFor(artifact.name, artifact.mime_type),
        },
      };

    case "reference":
      return {
        ...base,
        type: "custom",
        name: "ReferenceViewer",
        props: {
          citation: artifact.citation ?? null,
          uri: artifact.uri ?? null,
          name: artifact.name,
          description: artifact.description,
        },
      };

    case "file":
    case "unknown":
    default:
      return { ...base, type: "file", url, props: { description: artifact.description } };
  }
}

/** Convert a turn's artifacts into viewer elements for `ElementList`. */
export function artifactsToElements(artifacts: ArtifactMeta[]): AnyElement[] {
  return artifacts.map(artifactToElement);
}
