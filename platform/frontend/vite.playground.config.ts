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

// Builds the viewer playground (dev/viewers/index.html) alone, into dist-playground/,
// and serves that build: `npm run playground:preview`. The app build (vite.config.ts)
// reads index.html only, so it never contains the playground.
import { defineConfig, mergeConfig } from "vite";
import appConfig from "./vite.config";

export default mergeConfig(
  appConfig,
  defineConfig({
    build: {
      outDir: "dist-playground",
      emptyOutDir: true,
      rollupOptions: { input: "dev/viewers/index.html" },
    },
    preview: { port: 5170, strictPort: true, open: "/dev/viewers/" },
  }),
);
