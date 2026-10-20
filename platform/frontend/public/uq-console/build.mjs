#!/usr/bin/env node
/**
 * Build script for the standalone 3D UQ console page.
 *
 * Run with: node build.mjs
 * Requires: npm install
 *
 * Mirrors public/js/three/build.mjs (esbuild IIFE, browser, es2020, minified,
 * sourcemap) but bundles a full React app instead of a single global. The entry
 * imports the RodWorthUQConsole component from app.jsx and mounts it into the
 * page's #root with React 18's createRoot.
 *
 * three is NOT bundled here: app.jsx reads THREE off window.THREE (set by the
 * vendored public/js/three/bundle.js, which index.html loads first), so nothing
 * in this graph imports "three" and esbuild has nothing to pull in. React and
 * ReactDOM ARE bundled -- unlike Chainlit element JSX, this is a plain static
 * page with no host-provided React.
 */

import * as esbuild from 'esbuild';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));

// Entry: mount the original console into #root. The ?result= param is read here
// and stashed on window for the deferred honest-wiring step; today the page runs
// exactly as the original standalone component did.
const entryContent = `
import React from 'react';
import { createRoot } from 'react-dom/client';
import RodWorthUQConsole from './app.jsx';

const params = new URLSearchParams(window.location.search);
// TODO: honest wiring -- fetch this run's uq_result from window.__UQ_RESULT_URL__
// (same-origin /notebook/result/<name>.ipynb) to seed the mapped sliders and
// overlay the agent's real p05/p50/p95 on the existing fan chart. Additive only;
// the original 8 sliders + full scene stay intact. Unused for now.
window.__UQ_RESULT_URL__ = params.get('result') || null;

const el = document.getElementById('root');
createRoot(el).render(React.createElement(RodWorthUQConsole));
`;

async function build() {
  console.log('Building 3D UQ console bundle...');
  try {
    await esbuild.build({
      stdin: {
        contents: entryContent,
        resolveDir: __dirname,
        loader: 'js',
      },
      bundle: true,
      outfile: join(__dirname, 'bundle.js'),
      format: 'iife',
      platform: 'browser',
      target: ['es2020'],
      minify: true,
      sourcemap: true,
      // app.jsx is JSX; the entry uses the automatic runtime so it needs no
      // explicit React import in every file (app.jsx keeps its own import anyway).
      loader: { '.jsx': 'jsx' },
      jsx: 'automatic',
      logLevel: 'info',
    });
    console.log('3D UQ console bundle created at public/uq-console/bundle.js');
  } catch (err) {
    console.error('Build failed:', err);
    process.exit(1);
  }
}

build();
