# Viewer playground

The viewer playground is a developer page. It shows the artifact viewers (mesh, IFC, Mermaid, JSON) with sample data. It does not need an agent run or the backend. Use it to examine a viewer after you change it.

The page sends each sample artifact through `artifactsToElements` and `ElementList`, the same path that the chat uses. A fetch wrapper in `sampleFetch.ts` answers the `/api/artifacts/...` URLs that the viewers request. It gives the sample files for these URLs. It gives a 404 for every other `/api/` URL. Other URLs, for example unpkg for web-ifc, go to the network. The IFC case thus needs network access.

The app does not link to the page. The app build reads `index.html` only, so the page is not in `dist/`.

## Open the page

Run these commands in `platform/frontend`:

```bash
npm run playground           # start the dev server on port 5150 and open /dev/viewers/
npm run playground:preview   # build the page alone into dist-playground/ and serve it on port 5170
```

When the dev server runs already (`npm run dev`, or the Compose stack), open `http://localhost:5150/dev/viewers/`.

## Add a case

1. Copy a file in `cases/`, for example `cases/json.case.ts`, to `cases/<name>.case.ts`.
2. Set `title`, `note` and `viewer`. `viewer` is the custom element name that the chat mounts, for example `MeshViewer`.
3. Set `artifact` to the `ArtifactMeta` that the backend sends in a chat turn.
4. Add each URL path that the viewer fetches to `files`, with the sample asset URL that answers it.

Import a sample with `@viewer-samples/<file>?url` for an asset URL, or `?raw` for its text. The page shows the cases in file-name order. The `ViewerCase` type is in `viewerCase.ts`.

## Samples

The sample files are in `platform/frontend/e2e/samples/`. These tests use them today: `sampleFetch.test.ts`, `src/features/artifacts/playgroundCases.test.ts` and the backend test `tests/test_viewer_samples.py`. The PPLT-402 end-to-end tests will use them later. [The samples README](../../../e2e/samples/README.md) tells what each sample is and how to make it again.
