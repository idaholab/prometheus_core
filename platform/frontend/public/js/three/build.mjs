#!/usr/bin/env node
/**
 * Build script for the three.js bundle.
 *
 * Run with: node build.mjs
 * Requires: npm install
 *
 * Produces an IIFE that sets `window.THREE` and dispatches a `three-ready`
 * CustomEvent, mirroring the vtk/ifc vendoring pattern so a Chainlit custom
 * element can read `window.THREE` without an npm `import` (only react,
 * @/components/ui/*, and lucide-react resolve inside element JSX). The UQ
 * dashboard uses this dedicated ~600 KB core-three bundle instead of the
 * 5.3 MB IFC bundle that also happens to expose window.THREE.
 */

import * as esbuild from 'esbuild';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));

// Entry point: expose the full three namespace on window, then announce readiness.
const entryContent = `
import * as THREE from 'three';

// Do not clobber a three already provided by another bundle (e.g. the IFC
// bundle also sets window.THREE); first writer wins, and we still announce.
if (!window.THREE) {
  window.THREE = THREE;
}

console.log('[three-bundle] three.js loaded (r' + THREE.REVISION + ')');
window.dispatchEvent(new CustomEvent('three-ready', { detail: { version: THREE.REVISION } }));
`;

async function build() {
  console.log('Building three.js bundle...');

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
      logLevel: 'info',
    });

    console.log('three.js bundle created at public/js/three/bundle.js');
  } catch (err) {
    console.error('Build failed:', err);
    process.exit(1);
  }
}

build();
