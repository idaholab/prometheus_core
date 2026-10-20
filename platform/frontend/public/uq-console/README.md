# 3D Rod-Worth UQ Console (standalone page)

A self-contained interactive page served as a static asset at
`/uq-console/index.html`. Opened in a **new browser tab** from the "Open
interactive dashboard ↗" link on the inline UQ report element. Not embedded in
chat.

It draws a generic, illustrative hexagonal core with in-core control rods. The
geometry and reactor parameters are textbook-style defaults, not any real
design; the physics is reduced-order and for demonstration only.

Vite serves `frontend/public/` at the root, so this page resolves at
`/uq-console/index.html`. Production nginx serves the same file from the SPA
root (`dist/uq-console/index.html` via `try_files $uri /index.html`). The two
`<script>` sources are root paths (`/js/three/bundle.js`,
`/uq-console/bundle.js`).

## Files

| File | Role |
|---|---|
| `index.html` | Dark page, `<div id="root">`, loads `/js/three/bundle.js` (sets `window.THREE`) **then** `/uq-console/bundle.js`. Reads nothing secret. |
| `app.jsx` | The console component (8 uncertainty sliders, Three.js core, fan chart, gauges, SCRAM). `three` is read off `window.THREE`; React/ReactDOM are bundled. |
| `build.mjs` | esbuild IIFE build (mirrors `frontend/public/js/three/build.mjs`). Mounts the default export into `#root`. |
| `bundle.js` / `.map` | **Committed** build artifacts (like the three bundle). |
| `package.json` | esbuild + react/react-dom devDeps. |

`node_modules/` and `package-lock.json` are gitignored; the committed artifacts
are `build.mjs`, `bundle.js(.map)`, `package.json`, `index.html`, `app.jsx`.

## Build

```bash
cd frontend/public/uq-console && npm install && node build.mjs
```

## This run's data (deferred)

The link carries the run's data via `?result=/notebook/result/{name}` (served
by `notebook-render`, the full `uq_result` with per-sample `samples`). The page
currently **ignores** the parameter and runs its own illustrative physics; a
`// TODO: honest wiring` marks where real data will later seed the mapped
sliders and overlay the agent's p05/p50/p95 on the fan chart. That step is
additive only; the URL is already correct.
