// This file is part of Prometheus
// https://inl.gov/super-intelligence/prometheus/
//
// Copyright 2026 Battelle Energy Alliance, LLC
// All rights reserved, see NOTICE.txt for full restrictions
// https://github.com/idaholab/prometheus_core/blob/main/NOTICE.txt
//
// Licensed under the MIT License, please see LICENSE for details
// https://github.com/idaholab/prometheus_core/blob/main/LICENSE
//
// SPDX-License-Identifier: MIT

import path from "path";
import react from "@vitejs/plugin-react-swc";
import { defineConfig } from "vitest/config";
import tailwindcss from "@tailwindcss/vite";
import { nodePolyfills } from "vite-plugin-node-polyfills";

const BACKEND_TARGET = process.env.VITE_BACKEND_URL || "http://localhost:8600";
// notebook-render service: serves the baked UQ notebook report + uq_result JSON at
// same-origin `/notebook/...` (origin-agnostic Starlette app). Port matches the
// hybrid-dev map (8876). The standalone 3D UQ console page itself is a static file vite
// serves from `public/` at `/uq-console/` — it needs no proxy key.
const NOTEBOOK_TARGET = process.env.VITE_NOTEBOOK_URL || "http://localhost:8876";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    nodePolyfills({ include: ["events"] }),
  ],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  // mermaid is only reachable through a nested dynamic import inside a lazily
  // loaded viewer (lib/elements/elements.ts -> viewers/MermaidElement.tsx ->
  // `await import("mermaid")`), so on a cold cache Vite can miss it during
  // cold-start scanning, discover it when the first agent-rendered diagram
  // mounts, and then hard-reload the page ("optimized dependencies changed,
  // reloading") in the middle of a live conversation. Naming it here forces it
  // into the first optimize pass, so there is never a second one.
  //
  // The other heavy viewer deps (@thatopen/components + three for IFC,
  // @kitware/vtk.js for meshes) don't need listing: elements.ts top-level-awaits
  // their dynamic imports in DEV, which puts them in the initial scan already.
  optimizeDeps: {
    include: ["mermaid"],
  },
  test: {
    // Off by default; `npm run test:coverage` turns it on. Every source file
    // counts, tested or not, so the total reflects the whole app
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/test/**", "src/**/*.d.ts"],
      reporter: ["text-summary", "json-summary", "cobertura"],
    },
    // Logic tests (*.test.ts) run in Node; component tests (*.test.tsx) get a DOM
    projects: [
      {
        extends: true,
        test: { name: "unit", environment: "node", include: ["src/**/*.test.ts"] },
      },
      {
        extends: true,
        test: {
          name: "component",
          environment: "jsdom",
          include: ["src/**/*.test.tsx"],
          setupFiles: ["src/test/setup.ts"],
        },
      },
    ],
  },
  server: {
    port: 5150,
    watch: {
      // Vite appends this to its own defaults (.git, node_modules, test-results,
      // cacheDir) rather than replacing them. Without it, everything else in this
      // bind-mounted tree is polled too. A leftover Python .venv from the removed
      // Chainlit frontend put ~9.4k files under the watcher; at `interval: 100`
      // that is ~95k stat() calls/second through Docker's filesystem bridge, which
      // pinned frontend-dev at ~58% CPU while idle. The starved event loop let the
      // HMR websocket close uncleanly, and Vite's client answers an unclean close
      // by calling location.reload() -- silently destroying the live conversation,
      // since the transcript lives only in module memory.
      ignored: [
        "**/.venv/**",
        "**/__pycache__/**",
        "**/.*_cache/**",
        "**/tests/**",
        "**/dist/**",
      ],
      // Polling (also forced by CHOKIDAR_USEPOLLING in docker-compose.yml) is here
      // because host filesystem events don't reliably reach the container on
      // Docker Desktop. 1000ms is ample for a hand-edit workflow and costs ~10x
      // less than the old 100ms; worth retesting whether polling can be dropped
      // entirely now that the watched tree is small.
      usePolling: true,
      interval: 1000,
    },
    proxy: {
      // The backend owns the entire client-facing surface (backend/CONTRACT.md).
      // `/api/events` is SSE -- disable timeouts so the long-lived stream isn't
      // cut, and rely on http-proxy's default pass-through streaming.
      "/api": {
        target: BACKEND_TARGET,
        changeOrigin: true,
        ws: false,
        timeout: 0,
        proxyTimeout: 0,
      },
      // notebook-render: baked UQ report (/notebook/render/{id}) + result JSON
      // (/notebook/result/{id}). Same-origin; keeps AGENT_SECRET server-side.
      "/notebook": {
        target: NOTEBOOK_TARGET,
        changeOrigin: true,
      },
    },
  },
});
