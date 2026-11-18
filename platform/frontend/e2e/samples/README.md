# Viewer samples

This directory holds the sample files for the artifact viewers. These files use them today:

- The viewer playground cases in `platform/frontend/src/dev/viewer-playground/cases/`.
- `platform/frontend/src/dev/viewer-playground/sampleFetch.test.ts`.
- `platform/frontend/src/features/artifacts/playgroundCases.test.ts`.
- `platform/backend/tests/test_viewer_samples.py`.

The PPLT-402 end-to-end viewer tests will use the samples again later.

The production image does not contain the samples, because it copies only the built `dist/` folder.
The build stage of `platform/frontend/Dockerfile` does not copy the `e2e/` folder.

## The samples

| File | Viewer | Source | Content |
|---|---|---|---|
| `part.stl` | mesh | script | A small bracket: a base plate, an upright plate and a round boss, as a binary STL. |
| `mesh/surface_t0000.vtp` | mesh | script | The VTP surface that the backend mesh conversion makes from `part.stl`. |
| `mesh/manifest.json` | mesh | script | The manifest that the backend mesh conversion writes beside the VTP. |
| `mesh/meta.json` | mesh | script | The metadata that the backend mesh conversion writes beside the VTP. |
| `mesh/json_body.json` | mesh | script | The MeshViewer props that the backend sends in `json_body`. The `baseUrl` is `/api/artifacts/mesh/<dataset_id>`. |
| `model.ifc` | IFC | script | An IFC4 building: 4 walls, a floor slab, 2 columns, a beam, a door, a window, a roof slab, a pump and 2 pipe segments. The file names only the project, `Viewer sample project`. It has no person, organization or owner history. |
| `diagram.mmd` | Mermaid | by hand | A flowchart of a sample analysis workflow. |
| `results.json` | JSON | by hand | A made-up analysis result. |

The script is `platform/backend/scripts/export_viewer_samples.py`. It makes the mesh samples
with the backend's own conversion code (`app/services/mesh/service.py`), so they agree with what a
chat turn gets. It writes the IFC model with the Python standard library only. Its output does not
change from one run to the next.

## Regenerate the samples

Regenerate the samples after a change to the script or to the backend mesh conversion.

1. Go to `platform/backend`.
2. Run `uv run python scripts/export_viewer_samples.py`.
3. Commit the changed files in this directory.

The script does not write `diagram.mmd`, `results.json` or this file. Edit them by hand.

## The drift test

The backend test `platform/backend/tests/test_viewer_samples.py` runs the script into a temporary
directory. It compares that output with the committed files. The test fails when a committed sample
is different from the script output. It compares the VTP files by their points and cells, and the
other files byte for byte. When the test fails, regenerate the samples.

## Add a sample

1. Keep each file smaller than 200 KB.
2. Put a generated file in the script, not here by hand.
3. Add a row for the file to the table above.
