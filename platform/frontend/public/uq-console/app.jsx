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

import React, { useState, useMemo, useEffect, useRef } from "react";
// three is provided by the vendored /public/js/three/bundle.js, loaded BEFORE
// this bundle. It sets window.THREE (see frontend/public/js/three/build.mjs),
// so we read it off the global instead of an npm import that esbuild would try
// to resolve. This is the ONLY change from artifacts/Dashboard.original.jsx in
// the multiphysics-uq-agent repo -- everything below is the original console.
const THREE = window.THREE;

/* ================================================================
   3D ROD-WORTH UQ CONSOLE
   Orbitable 3D generic hexagonal reactor core (illustrative only).
   · Drag control rods vertically with the mouse (or slider / SCRAM)
   · Core glow follows power, flux-lit from inside
   · Every UQ plot recomputes in real time from an LHS Monte Carlo
   Geometry and parameters are generic textbook values, not any design.
   ================================================================ */

/* ---------------- tokens ---------------- */
const C = {
  bg: "#070C16", panel: "#0F1828", panel2: "#0B1220", line: "#20304C",
  text: "#E2E9F6", dim: "#8090AC",
  cyan: "#56CFE1", amber: "#FFB454", coral: "#FF5C5C", green: "#55E6A5",
  violet: "#9F8CFF", coolant: "#3D5A80", steel: "#2B3B57",
};
const MONO = "'IBM Plex Mono', ui-monospace, Menlo, monospace";
const DISP = "'Space Grotesk', ui-sans-serif, system-ui, sans-serif";

/* ---------------- math ---------------- */
function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const invNorm = (p) => {
  const a = [-39.6968302866538, 220.946098424521, -275.928510446969, 138.357751867269, -30.6647980661472, 2.50662827745924];
  const b = [-54.4760987982241, 161.585836858041, -155.698979859887, 66.8013118877197, -13.2806815528857];
  const c = [-0.00778489400243029, -0.322396458041136, -2.40075827716184, -2.54973253934373, 4.37466414146497, 2.93816398269878];
  const d = [0.00778469570904146, 0.32246712907004, 2.445134137143, 3.75440866190742];
  const pl = 0.02425; let q, r;
  if (p < pl) { q = Math.sqrt(-2 * Math.log(p)); return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])/((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1); }
  if (p <= 1 - pl) { q = p - 0.5; r = q*q; return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q/(((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1); }
  q = Math.sqrt(-2 * Math.log(1 - p)); return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])/((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1);
};
const quantile = (s, p) => { const i = p * (s.length - 1), lo = Math.floor(i), hi = Math.ceil(i); return s[lo] + (s[hi] - s[lo]) * (i - lo); };
const meanOf = (a) => { let s = 0; for (const v of a) s += v; return s / a.length; };
const sdOf = (a, m) => { let s = 0; for (const v of a) s += (v - m) ** 2; return Math.sqrt(s / (a.length - 1)); };
const scaler = (d0, d1, r0, r1) => (v) => r0 + ((v - d0) / (d1 - d0)) * (r1 - r0);
const lp = (pts, xs, ys) => pts.map((p, i) => `${i ? "L" : "M"}${xs(p[0]).toFixed(1)},${ys(p[1]).toFixed(1)}`).join("");
const Scurve = (z) => Math.max(0, Math.min(1, z - Math.sin(2 * Math.PI * z) / (2 * Math.PI)));
const T_DROP = 1.6, T_END = 25;
const scramZ = (t) => Math.min(1, (Math.max(0, t) / T_DROP) ** 2);

/* ---------------- hex lattice ---------------- */
function buildLattice() {
  const cells = [], R = 4;
  for (let q = -R; q <= R; q++) for (let r = -R; r <= R; r++) {
    const s = -q - r; if (Math.abs(s) > R) continue;
    const ring = Math.max(Math.abs(q), Math.abs(r), Math.abs(s));
    const x = q + r / 2, y = (r * Math.sqrt(3)) / 2;
    let type = "fuel";
    if (ring === 0) type = "rod";
    else if (ring === 2 && ((q === 2 && r === -1) || (q === -1 && r === 2) || (q === -1 && r === -1) || (q === 1 && r === 1) || (q === 1 && r === -2) || (q === -2 && r === 1))) type = "rod";
    cells.push({ x, y, ring, type });
  }
  return cells;
}
const LATTICE = buildLattice();

/* ---------------- UI atoms ---------------- */
const Panel = ({ title, sub, children, style }) => (
  <div style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 10, padding: 14, ...style }}>
    {title && <div style={{ marginBottom: 8 }}>
      <div style={{ fontFamily: DISP, fontWeight: 600, fontSize: 13, color: C.text }}>{title}</div>
      {sub && <div style={{ fontSize: 10.5, color: C.dim, marginTop: 2 }}>{sub}</div>}
    </div>}
    {children}
  </div>
);
const Slider = ({ label, value, min, max, step, onChange, unit, accent = C.cyan, fmtV }) => (
  <div style={{ marginBottom: 10 }}>
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 3 }}>
      <span style={{ color: C.dim }}>{label}</span>
      <span style={{ fontFamily: MONO, color: accent }}>{fmtV ? fmtV(value) : value}{unit}</span>
    </div>
    <input type="range" min={min} max={max} step={step} value={value}
      onChange={(e) => onChange(parseFloat(e.target.value))} style={{ width: "100%", accentColor: accent, height: 4 }} />
  </div>
);
const Stat = ({ label, value, color = C.text, big }) => (
  <div>
    <div style={{ fontSize: 9, letterSpacing: 1.3, color: C.dim, textTransform: "uppercase" }}>{label}</div>
    <div style={{ fontFamily: MONO, fontSize: big ? 22 : 15, color, fontWeight: 500 }}>{value}</div>
  </div>
);
function Gauge({ value, min, max, zones, label, unit, fmt = (v) => v.toFixed(2), size = 148 }) {
  const W = size, H = size * 0.62, cx = W / 2, cy = H * 0.94, R = W * 0.38;
  const toA = (v) => Math.PI - ((Math.min(max, Math.max(min, v)) - min) / (max - min)) * Math.PI;
  const arc = (v0, v1, col) => {
    const s = toA(v0), e = toA(v1);
    return <path d={`M${cx + R * Math.cos(s)},${cy - R * Math.sin(s)} A${R},${R} 0 0 1 ${cx + R * Math.cos(e)},${cy - R * Math.sin(e)}`} fill="none" stroke={col} strokeWidth={8} />;
  };
  const na = toA(value);
  return (
    <svg width={W} height={H + 30}>
      {zones.map((z, i) => <g key={i}>{arc(z[0], z[1], z[2])}</g>)}
      <line x1={cx} y1={cy} x2={cx + (R - 12) * Math.cos(na)} y2={cy - (R - 12) * Math.sin(na)}
        stroke={C.text} strokeWidth={2.2} style={{ transition: "all .3s cubic-bezier(.4,0,.2,1)" }} />
      <circle cx={cx} cy={cy} r={4} fill={C.text} />
      <text x={cx} y={cy + 17} fill={C.text} fontSize={13.5} fontFamily={MONO} textAnchor="middle" fontWeight={600}>{fmt(value)}{unit}</text>
      <text x={cx} y={cy + 29} fill={C.dim} fontSize={8.5} fontFamily={MONO} textAnchor="middle" letterSpacing={1}>{label}</text>
    </svg>
  );
}

/* ================================================================ */
export default function RodWorthUQConsole() {
  /* ---------- UQ parameters ---------- */
  const [w0, setW0] = useState(3200);
  const [ndU, setNdU] = useState(4);
  const [methU, setMethU] = useState(3);
  const [betaN, setBetaN] = useState(680);
  const [betaU, setBetaU] = useState(4);
  const [rhoEx, setRhoEx] = useState(1400);
  const [tDefU, setTDefU] = useState(120);
  const [posTol, setPosTol] = useState(1.5);
  const [N, setN] = useState(2000);
  const [seed, setSeed] = useState(7);

  /* ---------- rod bank state + SCRAM clock ---------- */
  const [insertion, setInsertion] = useState(0.35);
  const [simT, setSimT] = useState(null);
  const [autoOrbit, setAutoOrbit] = useState(true);
  useEffect(() => {
    if (simT === null) return;
    let raf, last = performance.now();
    const tick = (now) => {
      const dt = (now - last) / 1000; last = now;
      setSimT((t) => (t === null ? null : Math.min(T_END, t + dt * 2.2)));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [simT === null]);
  const liveZ = simT === null ? insertion : scramZ(simT);

  /* ---------- Monte Carlo ---------- */
  const mc = useMemo(() => {
    const rng = mulberry32(seed);
    const cl = (u) => Math.min(0.999999, Math.max(0.000001, u));
    const dims = 5;
    const U = Array.from({ length: dims }, () => {
      const idx = Array.from({ length: N }, (_, i) => i);
      for (let i = N - 1; i > 0; i--) { const j = Math.floor(rng() * (i + 1)); [idx[i], idx[j]] = [idx[j], idx[i]]; }
      return Float64Array.from(idx, (v) => (v + rng()) / N);
    });
    const fnd = new Float64Array(N), fm = new Float64Array(N), be = new Float64Array(N), td = new Float64Array(N), dz = new Float64Array(N);
    const W = new Float64Array(N), SDM = new Float64Array(N);
    for (let i = 0; i < N; i++) {
      fnd[i] = 1 + (ndU / 100) * invNorm(cl(U[0][i]));
      fm[i] = 1 + (methU / 100) * invNorm(cl(U[1][i]));
      be[i] = betaN * (1 + (betaU / 100) * invNorm(cl(U[2][i])));
      td[i] = tDefU * invNorm(cl(U[3][i]));
      dz[i] = (posTol / 100) * (2 * U[4][i] - 1);
      W[i] = w0 * fnd[i] * fm[i] * Scurve(Math.max(0, Math.min(1, 1 + dz[i])));
      SDM[i] = (W[i] - rhoEx - td[i]) / be[i];
    }
    const sortW = Float64Array.from(W).sort(), sortS = Float64Array.from(SDM).sort();
    const mW = meanOf(W), sW = sdOf(W, mW), mS = meanOf(SDM), sS = sdOf(SDM, mS);
    let nf = 0; for (let i = 0; i < N; i++) if (SDM[i] < 1) nf++;
    const pFail = nf / N;
    /* SRC² of SDM */
    const X = [fnd, fm, be, td, dz];
    const mx = X.map(meanOf), sx = X.map((c, j) => sdOf(c, mx[j]));
    const Z = X.map((c, j) => Float64Array.from(c, (v) => (v - mx[j]) / (sx[j] || 1)));
    const zy = Float64Array.from(SDM, (v) => (v - mS) / sS);
    const G = Array.from({ length: 5 }, () => new Float64Array(6));
    for (let a = 0; a < 5; a++) {
      for (let b2 = a; b2 < 5; b2++) { let s = 0; for (let i = 0; i < N; i++) s += Z[a][i] * Z[b2][i]; G[a][b2] = s / N; G[b2][a] = s / N; }
      let s = 0; for (let i = 0; i < N; i++) s += Z[a][i] * zy[i]; G[a][5] = s / N;
    }
    const M = G.map((r) => Array.from(r));
    for (let c0 = 0; c0 < 5; c0++) {
      let piv = c0; for (let r = c0 + 1; r < 5; r++) if (Math.abs(M[r][c0]) > Math.abs(M[piv][c0])) piv = r;
      [M[c0], M[piv]] = [M[piv], M[c0]];
      for (let r = 0; r < 5; r++) if (r !== c0 && Math.abs(M[c0][c0]) > 1e-12) {
        const f = M[r][c0] / M[c0][c0];
        for (let cc = c0; cc < 6; cc++) M[r][cc] -= f * M[c0][cc];
      }
    }
    const beta = M.map((r, i) => (Math.abs(r[i]) > 1e-12 ? r[5] / r[i] : 0));
    const src2 = beta.map((b) => b * b);
    const fTot = Float64Array.from({ length: N }, (_, i) => fnd[i] * fm[i]).sort();
    const band = { p05: quantile(fTot, 0.05), p25: quantile(fTot, 0.25), p50: quantile(fTot, 0.5), p75: quantile(fTot, 0.75), p95: quantile(fTot, 0.95) };
    return { W, SDM, sortW, sortS, mW, sW, mS, sS, pFail, nf, src2, band, mKeff: 1 / (1 + (mW - rhoEx) * 1e-5) };
  }, [w0, ndU, methU, betaN, betaU, rhoEx, tDefU, posTol, N, seed]);

  /* ---------- SCRAM ensemble (prompt-jump kinetics) ---------- */
  const trans = useMemo(() => {
    const M = 220, NT = 130, LAM = 0.078;
    const ts = Float64Array.from({ length: NT }, (_, i) => (i / (NT - 1)) * T_END);
    const rng = mulberry32(seed + 991);
    const cl = (u) => Math.min(0.999999, Math.max(0.000001, u));
    const P = Array.from({ length: M }, () => new Float64Array(NT));
    for (let m = 0; m < M; m++) {
      const wtot = w0 * (1 + (ndU / 100) * invNorm(cl(rng()))) * (1 + (methU / 100) * invNorm(cl(rng()))) * 1e-5;
      const b = betaN * (1 + (betaU / 100) * invNorm(cl(rng()))) * 1e-5;
      let logC = 0;
      for (let it = 0; it < NT; it++) {
        const t = ts[it], rho = -wtot * Scurve(scramZ(t));
        const dt = it ? ts[it] - ts[it - 1] : 0;
        logC += -LAM * (-rho / (b - rho)) * dt;
        P[m][it] = Math.max((b / (b - rho)) * Math.exp(logC) * (1 - 0.062), 0.062 * Math.pow(t + 0.8, -0.2));
      }
    }
    const fan = { p05: new Float64Array(NT), p25: new Float64Array(NT), p50: new Float64Array(NT), p75: new Float64Array(NT), p95: new Float64Array(NT) };
    const col = new Float64Array(M);
    for (let it = 0; it < NT; it++) {
      for (let m = 0; m < M; m++) col[m] = P[m][it];
      const s = Float64Array.from(col).sort();
      fan.p05[it] = quantile(s, 0.05); fan.p25[it] = quantile(s, 0.25); fan.p50[it] = quantile(s, 0.5);
      fan.p75[it] = quantile(s, 0.75); fan.p95[it] = quantile(s, 0.95);
    }
    return { ts, fan, NT, spag: [5, 60, 120, 180].map((m) => P[m]) };
  }, [w0, ndU, methU, betaN, betaU, seed]);

  const livePower = useMemo(() => {
    if (simT === null) return 1;
    const it = Math.min(trans.NT - 1, Math.round((simT / T_END) * (trans.NT - 1)));
    return trans.fan.p50[it];
  }, [simT, trans]);
  const liveRho = -(mc.mW * Scurve(liveZ)) / betaN;
  const status = mc.pFail < 0.001 ? ["MARGIN OK", C.green] : mc.pFail < 0.05 ? ["REVIEW", C.amber] : ["INSUFFICIENT", C.coral];

  /* ================================================================
     THREE.JS SCENE — built once, animated via refs
     ================================================================ */
  const mountRef = useRef(null);
  const threeRef = useRef({});
  const stateRef = useRef({ z: liveZ, power: 1, autoOrbit: true, dragRod: false });
  stateRef.current.z = liveZ;
  stateRef.current.power = livePower;
  stateRef.current.autoOrbit = autoOrbit;
  const setInsertionRef = useRef(setInsertion);
  const setSimTRef = useRef(setSimT);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    const Wpx = mount.clientWidth, Hpx = mount.clientHeight;
    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x070c16, 0.028);
    const camera = new THREE.PerspectiveCamera(42, Wpx / Hpx, 0.1, 100);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(Wpx, Hpx);
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
    mount.appendChild(renderer.domElement);
    renderer.domElement.style.borderRadius = "10px";
    renderer.domElement.style.cursor = "grab";

    /* lights */
    scene.add(new THREE.AmbientLight(0x8090ac, 0.5));
    const key = new THREE.DirectionalLight(0xdfe7f5, 0.9); key.position.set(6, 9, 5); scene.add(key);
    const rim = new THREE.DirectionalLight(0x56cfe1, 0.35); rim.position.set(-7, 3, -6); scene.add(rim);
    const coreLight = new THREE.PointLight(0xffb454, 2.2, 12, 2); coreLight.position.set(0, 0, 0); scene.add(coreLight);

    const S = 0.5;                      // lattice pitch
    const CORE_H = 2.4;                 // core height
    const group = new THREE.Group(); scene.add(group);

    /* materials */
    const matFuel = new THREE.MeshStandardMaterial({ color: 0x8a5a2b, emissive: 0xff8c2e, emissiveIntensity: 0.55, roughness: 0.55, metalness: 0.3 });
    const matRod = new THREE.MeshStandardMaterial({ color: 0x9f8cff, emissive: 0x4a3f8f, emissiveIntensity: 0.35, roughness: 0.4, metalness: 0.5 });
    const matGuide = new THREE.MeshStandardMaterial({ color: 0x9f8cff, transparent: true, opacity: 0.14, roughness: 0.2 });
    const matSteel = new THREE.MeshStandardMaterial({ color: 0x2b3b57, roughness: 0.45, metalness: 0.85 });
    const matVessel = new THREE.MeshPhysicalMaterial({ color: 0x3d5a80, transparent: true, opacity: 0.13, roughness: 0.15, metalness: 0.2, side: THREE.DoubleSide, depthWrite: false });

    /* fuel pins + guide tubes */
    const pinGeo = new THREE.CylinderGeometry(0.155, 0.155, CORE_H, 14);
    const guideGeo = new THREE.CylinderGeometry(0.185, 0.185, CORE_H + 0.06, 14, 1, true);
    const rodPositions = [];
    LATTICE.forEach((c) => {
      const x = c.x * S, zP = c.y * S;
      if (c.type === "fuel") {
        const m = new THREE.Mesh(pinGeo, matFuel); m.position.set(x, 0, zP); group.add(m);
      } else if (c.type === "rod") {
        const g = new THREE.Mesh(guideGeo, matGuide); g.position.set(x, 0, zP); group.add(g);
        rodPositions.push([x, zP]);
      }
    });

    /* control rods: absorber + drive shaft, slide from above */
    const ROD_H = CORE_H;
    const yOut = CORE_H / 2 + ROD_H / 2 + 0.12;   // fully withdrawn: absorber parked above core
    const rodGeo = new THREE.CylinderGeometry(0.16, 0.16, ROD_H, 14);
    const shaftGeo = new THREE.CylinderGeometry(0.05, 0.05, 3.4, 8);
    const rodMeshes = [], shaftMeshes = [];
    rodPositions.forEach(([x, zP]) => {
      const rod = new THREE.Mesh(rodGeo, matRod); rod.position.set(x, yOut, zP); group.add(rod); rodMeshes.push(rod);
      const sh = new THREE.Mesh(shaftGeo, matSteel); sh.position.set(x, yOut + ROD_H / 2 + 1.7, zP); group.add(sh); shaftMeshes.push(sh);
    });

    /* hex reflector shroud */
    const shroud = new THREE.Mesh(new THREE.CylinderGeometry(2.55, 2.55, CORE_H + 0.15, 6, 1, false),
      new THREE.MeshStandardMaterial({ color: 0x2b3b57, transparent: true, opacity: 0.4, roughness: 0.5, metalness: 0.7 }));
    shroud.position.y = 0; group.add(shroud);
    const shroudInner = new THREE.Mesh(new THREE.CylinderGeometry(2.28, 2.28, CORE_H + 0.16, 6),
      new THREE.MeshBasicMaterial({ color: 0x070c16 }));
    group.add(shroudInner);
    /* re-add pins in front of inner blank — instead just shrink inner: skip inner, keep shroud translucent */
    group.remove(shroudInner);

    /* vessel + head + support skirt */
    const vessel = new THREE.Mesh(new THREE.CylinderGeometry(3.95, 3.95, 7.4, 48, 1, true), matVessel);
    vessel.position.y = 1.0; scene.add(vessel);
    const vesselBot = new THREE.Mesh(new THREE.SphereGeometry(3.95, 48, 16, 0, Math.PI * 2, Math.PI / 2, Math.PI / 2), matVessel);
    vesselBot.position.y = -2.7; scene.add(vesselBot);
    const head = new THREE.Mesh(new THREE.CylinderGeometry(4.1, 4.1, 0.35, 48), matSteel);
    head.position.y = 4.85; scene.add(head);
    /* drive housings on head */
    rodPositions.forEach(([x, zP]) => {
      const h = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, 1.1, 10), matSteel);
      h.position.set(x, 5.55, zP); scene.add(h);
    });
    /* ground grid */
    const grid = new THREE.GridHelper(30, 30, 0x20304c, 0x131d31);
    grid.position.y = -4.6; scene.add(grid);

    /* ---------- custom orbit + rod-drag controls ---------- */
    const sph = { theta: 0.7, phi: 1.12, radius: 13.5 };
    const applyCam = () => {
      camera.position.set(
        sph.radius * Math.sin(sph.phi) * Math.cos(sph.theta),
        sph.radius * Math.cos(sph.phi) + 0.8,
        sph.radius * Math.sin(sph.phi) * Math.sin(sph.theta));
      camera.lookAt(0, 0.6, 0);
    };
    applyCam();
    const ray = new THREE.Raycaster();
    const ndc = new THREE.Vector2();
    let mode = null, px = 0, py = 0, z0 = 0;
    const onDown = (e) => {
      const r = renderer.domElement.getBoundingClientRect();
      ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(ndc, camera);
      const hits = ray.intersectObjects([...rodMeshes, ...shaftMeshes]);
      if (hits.length) { mode = "rod"; z0 = stateRef.current.z; renderer.domElement.style.cursor = "ns-resize"; setSimTRef.current(null); }
      else { mode = "orbit"; renderer.domElement.style.cursor = "grabbing"; }
      px = e.clientX; py = e.clientY;
      stateRef.current.dragRod = mode === "rod";
    };
    const onMove = (e) => {
      if (!mode) {
        const r = renderer.domElement.getBoundingClientRect();
        ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
        ray.setFromCamera(ndc, camera);
        renderer.domElement.style.cursor = ray.intersectObjects([...rodMeshes, ...shaftMeshes]).length ? "ns-resize" : "grab";
        return;
      }
      const dx = e.clientX - px, dy = e.clientY - py;
      if (mode === "orbit") {
        sph.theta += dx * 0.0065;
        sph.phi = Math.max(0.25, Math.min(1.5, sph.phi - dy * 0.0055));
        applyCam();
      } else if (mode === "rod") {
        const nz = Math.max(0, Math.min(1, z0 + dy / 220));
        setInsertionRef.current(nz);
        stateRef.current.z = nz;
      }
    };
    const onUp = () => { mode = null; stateRef.current.dragRod = false; renderer.domElement.style.cursor = "grab"; };
    const onWheel = (e) => { e.preventDefault(); sph.radius = Math.max(6, Math.min(26, sph.radius + e.deltaY * 0.012)); applyCam(); };
    renderer.domElement.addEventListener("pointerdown", onDown);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    renderer.domElement.addEventListener("wheel", onWheel, { passive: false });

    /* ---------- animation loop ---------- */
    let raf, tPrev = performance.now();
    const animate = (now) => {
      const dt = (now - tPrev) / 1000; tPrev = now;
      const st = stateRef.current;
      /* rods */
      const y = yOut - st.z * ROD_H;
      rodMeshes.forEach((m) => (m.position.y = y));
      shaftMeshes.forEach((m) => (m.position.y = y + ROD_H / 2 + 1.7));
      /* power → glow */
      const glow = 0.06 + 0.94 * st.power * (1 - 0.55 * st.z);
      matFuel.emissiveIntensity = 0.15 + 0.75 * glow;
      coreLight.intensity = 0.3 + 3.2 * glow;
      /* idle auto-orbit */
      if (st.autoOrbit && !mode) { sph.theta += dt * 0.12; applyCam(); }
      renderer.render(scene, camera);
      raf = requestAnimationFrame(animate);
    };
    raf = requestAnimationFrame(animate);

    const onResize = () => {
      const w = mount.clientWidth, h = mount.clientHeight;
      camera.aspect = w / h; camera.updateProjectionMatrix(); renderer.setSize(w, h);
    };
    window.addEventListener("resize", onResize);
    threeRef.current = { renderer };
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      renderer.dispose();
      mount.removeChild(renderer.domElement);
    };
  }, []);

  /* ================================================================
     LIVE PLOTS (SVG) — recompute on every param / rod change
     ================================================================ */
  const WorthCurve = () => {
    const W = 380, H = 210, pad = { l: 46, r: 10, t: 8, b: 28 };
    const ymax = w0 * mc.band.p95 * 1.05;
    const xs = scaler(0, 1, pad.l, W - pad.r), ys = scaler(0, ymax, H - pad.b, pad.t);
    const zz = Array.from({ length: 70 }, (_, i) => i / 69);
    const cv = (f) => zz.map((z) => [z, w0 * f * Scurve(z)]);
    const up = cv(mc.band.p95), dn = cv(mc.band.p05).reverse();
    return (
      <svg width="100%" viewBox={`0 0 ${W} ${H}`}>
        {[0, ymax / 2, ymax].map((v, i) => (
          <g key={i}><line x1={pad.l} x2={W - pad.r} y1={ys(v)} y2={ys(v)} stroke={C.line} strokeWidth={0.6} />
            <text x={pad.l - 5} y={ys(v) + 3} fill={C.dim} fontSize={8.5} fontFamily={MONO} textAnchor="end">{v.toFixed(0)}</text></g>
        ))}
        <path d={lp(up, xs, ys) + lp(dn, xs, ys).replace("M", "L") + "Z"} fill={C.cyan} opacity={0.15} />
        <path d={lp(cv(mc.band.p25), xs, ys) + lp(cv(mc.band.p75).reverse(), xs, ys).replace("M", "L") + "Z"} fill={C.cyan} opacity={0.18} />
        <path d={lp(cv(mc.band.p50), xs, ys)} fill="none" stroke={C.amber} strokeWidth={2.2} />
        <line x1={pad.l} x2={W - pad.r} y1={ys(rhoEx)} y2={ys(rhoEx)} stroke={C.coral} strokeDasharray="4 3" strokeWidth={1.4} />
        <text x={W - pad.r} y={ys(rhoEx) - 4} fill={C.coral} fontSize={8.5} fontFamily={MONO} textAnchor="end">excess ρ</text>
        <circle cx={xs(liveZ)} cy={ys(w0 * mc.band.p50 * Scurve(liveZ))} r={5} fill={C.violet} stroke={C.text} strokeWidth={1.4} />
        <line x1={xs(liveZ)} x2={xs(liveZ)} y1={pad.t} y2={H - pad.b} stroke={C.violet} strokeDasharray="2 3" opacity={0.6} />
        {[0, 0.5, 1].map((t) => <text key={t} x={xs(t)} y={H - pad.b + 13} fill={C.dim} fontSize={8.5} fontFamily={MONO} textAnchor="middle">{(t * 100).toFixed(0)}%</text>)}
        <text x={W / 2} y={H - 4} fill={C.dim} fontSize={9} fontFamily={MONO} textAnchor="middle">bank insertion → integral worth [pcm]</text>
      </svg>
    );
  };

  const Fan = () => {
    const W = 380, H = 200, pad = { l: 44, r: 10, t: 8, b: 26 };
    const xs = scaler(0, T_END, pad.l, W - pad.r);
    const ys = scaler(0, 1.05, H - pad.b, pad.t);
    const band = (lo, hi, op) => {
      const up = Array.from(trans.ts, (t, i) => [t, hi[i]]);
      const dn = Array.from(trans.ts, (t, i) => [t, lo[i]]).reverse();
      return <path d={lp(up, xs, ys) + lp(dn, xs, ys).replace("M", "L") + "Z"} fill={C.cyan} opacity={op} />;
    };
    return (
      <svg width="100%" viewBox={`0 0 ${W} ${H}`}>
        {[0, 0.5, 1].map((t) => (
          <g key={t}><line x1={pad.l} x2={W - pad.r} y1={ys(t)} y2={ys(t)} stroke={C.line} strokeWidth={0.6} />
            <text x={pad.l - 5} y={ys(t) + 3} fill={C.dim} fontSize={8.5} fontFamily={MONO} textAnchor="end">{(t * 100).toFixed(0)}%</text></g>
        ))}
        {band(trans.fan.p05, trans.fan.p95, 0.14)}
        {band(trans.fan.p25, trans.fan.p75, 0.2)}
        {trans.spag.map((tr, i) => (
          <path key={i} d={lp(Array.from(trans.ts, (t, j) => [t, tr[j]]), xs, ys)} fill="none" stroke={C.cyan} strokeWidth={0.6} opacity={0.35} />
        ))}
        <path d={lp(Array.from(trans.ts, (t, i) => [t, trans.fan.p50[i]]), xs, ys)} fill="none" stroke={C.amber} strokeWidth={2.2} />
        {simT !== null && (
          <g>
            <line x1={xs(simT)} x2={xs(simT)} y1={pad.t} y2={H - pad.b} stroke={C.coral} strokeWidth={1.5} />
            <circle cx={xs(simT)} cy={ys(livePower)} r={4} fill={C.coral} />
          </g>
        )}
        {[0, 10, 20].map((t) => <text key={t} x={xs(t)} y={H - pad.b + 13} fill={C.dim} fontSize={8.5} fontFamily={MONO} textAnchor="middle">{t}s</text>)}
        <text x={W / 2} y={H - 4} fill={C.dim} fontSize={9} fontFamily={MONO} textAnchor="middle">power after trip · P5–P95 / P25–P75 fan</text>
      </svg>
    );
  };

  const SDMHist = () => {
    const arr = mc.sortS, lo = arr[0], hi = arr[arr.length - 1];
    const nb = 36, bins = new Array(nb).fill(0), bw0 = (hi - lo) / nb || 1;
    arr.forEach((v) => bins[Math.min(nb - 1, Math.floor((v - lo) / bw0))]++);
    const maxc = Math.max(...bins);
    const W = 380, H = 180, pad = { l: 8, r: 8, t: 8, b: 26 };
    const xs = scaler(lo, hi, pad.l, W - pad.r), bw = (W - pad.l - pad.r) / nb;
    return (
      <svg width="100%" viewBox={`0 0 ${W} ${H}`}>
        {bins.map((c, i) => {
          const xv = lo + (i + 0.5) * bw0;
          return <rect key={i} x={pad.l + i * bw} y={H - pad.b - (c / maxc) * (H - 46)} width={bw - 1}
            height={(c / maxc) * (H - 46)} fill={xv < 1 ? C.coral : C.green} opacity={0.65} rx={1} />;
        })}
        <path d={lp(Array.from({ length: 70 }, (_, i) => {
          const idx = Math.floor((i / 69) * (arr.length - 1)); return [arr[idx], idx / (arr.length - 1)];
        }), xs, scaler(0, 1, H - pad.b, pad.t))} fill="none" stroke={C.amber} strokeWidth={1.8} />
        <line x1={xs(1)} x2={xs(1)} y1={pad.t} y2={H - pad.b} stroke={C.coral} strokeWidth={2} />
        <text x={xs(1)} y={pad.t + 9} fill={C.coral} fontSize={9} fontFamily={MONO} textAnchor="middle">$1</text>
        <text x={pad.l} y={H - 8} fill={C.dim} fontSize={8.5} fontFamily={MONO}>${lo.toFixed(2)}</text>
        <text x={W - pad.r} y={H - 8} fill={C.dim} fontSize={8.5} fontFamily={MONO} textAnchor="end">${hi.toFixed(2)}</text>
        <text x={W / 2} y={H - 4} fill={C.dim} fontSize={9} fontFamily={MONO} textAnchor="middle">shutdown margin [$] · histogram + CDF</text>
      </svg>
    );
  };

  const SensBars = () => {
    const names = ["Nuclear data", "Methods bias", "β_eff", "Temp defect", "Position tol."];
    const cols = [C.violet, C.violet, C.amber, C.green, C.green];
    const order = mc.src2.map((v, i) => [v, i]).sort((a, b) => b[0] - a[0]);
    const maxv = Math.max(order[0][0], 0.001);
    return (
      <div>
        {order.map(([v, i]) => (
          <div key={i} style={{ marginBottom: 8 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10.5, marginBottom: 2 }}>
              <span style={{ color: C.text }}>{names[i]}</span>
              <span style={{ fontFamily: MONO, color: cols[i] }}>{(v * 100).toFixed(1)}%</span>
            </div>
            <div style={{ height: 10, background: C.panel2, borderRadius: 3, overflow: "hidden" }}>
              <div style={{ width: `${(v / maxv) * 100}%`, height: "100%", background: cols[i], transition: "width .25s" }} />
            </div>
          </div>
        ))}
      </div>
    );
  };

  const fmt = (v, d = 1) => v.toFixed(d);

  /* ================================================================ */
  return (
    <div style={{ minHeight: "100vh", background: C.bg, color: C.text, fontFamily: DISP }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
        input[type=range]{ -webkit-appearance:none; background:${C.line}; border-radius:2px; }
        input[type=range]::-webkit-slider-thumb{ -webkit-appearance:none; width:13px; height:13px; border-radius:50%; background:${C.cyan}; border:2px solid ${C.bg}; cursor:pointer; }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }
        button:focus-visible{ outline:2px solid ${C.cyan}; outline-offset:2px; }
        @media (prefers-reduced-motion: reduce){ *{ animation:none!important; transition:none!important; } }
      `}</style>

      {/* ========== instrument bar ========== */}
      <div style={{ borderBottom: `1px solid ${C.line}`, background: C.panel2, padding: "12px 18px", display: "flex", flexWrap: "wrap", gap: 20, alignItems: "center" }}>
        <div style={{ minWidth: 225 }}>
          <div style={{ fontSize: 10, letterSpacing: 2.5, color: C.amber, fontFamily: MONO }}>GENERIC CORE · 3D UQ CONSOLE</div>
          <div style={{ fontSize: 16, fontWeight: 700 }}>Control-Rod Worth & Shutdown Margin</div>
          <div style={{ fontSize: 9.5, color: C.dim, fontFamily: MONO }}>generic illustrative core · textbook parameters</div>
        </div>
        <div style={{ display: "flex", gap: 22, flexWrap: "wrap", flex: 1 }}>
          <Stat label="Bank worth" value={`${fmt(mc.mW, 0)} pcm`} />
          <Stat label="Worth [$]" value={`$${fmt(mc.mW / betaN, 2)}`} color={C.violet} />
          <Stat label="SDM" value={`$${fmt(mc.mS, 2)} ± ${fmt(mc.sS, 2)}`} color={C.green} />
          <Stat label="P(SDM<$1)" value={mc.pFail < 5e-4 ? "<5e-4" : mc.pFail.toExponential(1)} color={status[1]} big />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button onClick={() => setSimT(0)} style={{
            background: simT !== null && simT < T_END ? C.coral : "transparent",
            color: simT !== null && simT < T_END ? "#12060A" : C.coral,
            border: `2px solid ${C.coral}`, borderRadius: 8, padding: "8px 16px", fontFamily: MONO,
            fontSize: 13, fontWeight: 700, letterSpacing: 2, cursor: "pointer",
            animation: simT !== null && simT < T_END ? "pulse .7s infinite" : "none",
          }}>SCRAM</button>
          {simT !== null && <button onClick={() => setSimT(null)} style={{ background: "transparent", border: `1px solid ${C.line}`, color: C.dim, borderRadius: 6, padding: "6px 10px", fontFamily: MONO, fontSize: 11, cursor: "pointer" }}>reset</button>}
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontFamily: MONO, fontSize: 11 }}>
            <span style={{ width: 9, height: 9, borderRadius: "50%", background: status[1], boxShadow: `0 0 9px ${status[1]}` }} />
            <span style={{ color: status[1], letterSpacing: 1.5 }}>{status[0]}</span>
          </div>
        </div>
      </div>

      {/* ========== main layout: controls | 3D | plots ========== */}
      <div style={{ display: "flex", gap: 14, padding: 16, flexWrap: "wrap", alignItems: "stretch" }}>

        {/* controls */}
        <div style={{ width: 236, flexShrink: 0, display: "flex", flexDirection: "column", gap: 12 }}>
          <Panel title="Uncertainty budget" sub="1σ · everything updates live">
            <Slider label="Nominal bank worth" value={w0} min={2000} max={4500} step={25} onChange={setW0} unit=" pcm" />
            <Slider label="Nuclear data (B₄C σₐ)" value={ndU} min={0.5} max={10} step={0.25} onChange={setNdU} unit=" %" accent={C.violet} />
            <Slider label="Methods / code bias" value={methU} min={0.5} max={8} step={0.25} onChange={setMethU} unit=" %" accent={C.violet} />
            <Slider label="β_eff nominal" value={betaN} min={550} max={800} step={5} onChange={setBetaN} unit=" pcm" accent={C.amber} />
            <Slider label="β_eff uncertainty" value={betaU} min={1} max={10} step={0.5} onChange={setBetaU} unit=" %" accent={C.amber} />
            <Slider label="Excess reactivity" value={rhoEx} min={800} max={2400} step={25} onChange={setRhoEx} unit=" pcm" accent={C.coral} />
            <Slider label="Temp-defect unc." value={tDefU} min={20} max={300} step={10} onChange={setTDefU} unit=" pcm" accent={C.green} />
            <Slider label="Position tolerance" value={posTol} min={0.2} max={5} step={0.1} onChange={setPosTol} unit=" %" accent={C.green} />
          </Panel>
          <Panel title="Rod bank">
            <Slider label="Insertion" value={insertion} min={0} max={1} step={0.01}
              onChange={(v) => { setSimT(null); setInsertion(v); }} fmtV={(v) => `${(v * 100).toFixed(0)}%`} unit="" accent={C.violet} />
            <div style={{ fontSize: 10, color: C.dim, lineHeight: 1.5 }}>
              …or <b style={{ color: C.violet }}>grab a rod in the 3D view and drag it</b> up/down. SCRAM in the header runs the gravity drop.
            </div>
          </Panel>
          <Panel title="Monte Carlo">
            <Slider label="Samples N (LHS)" value={N} min={500} max={6000} step={100} onChange={setN} unit="" />
            <button onClick={() => setSeed((s) => s + 1)} style={{ width: "100%", padding: 6, borderRadius: 6, background: "transparent", border: `1px solid ${C.line}`, color: C.dim, fontFamily: MONO, fontSize: 11, cursor: "pointer" }}>↻ Re-seed ({seed})</button>
          </Panel>
        </div>

        {/* 3D viewport */}
        <div style={{ flex: "1.4 1 480px", minWidth: 360, display: "flex", flexDirection: "column", gap: 10 }}>
          <div ref={mountRef} style={{ width: "100%", height: 560, background: `radial-gradient(ellipse at 50% 35%, #0D1626 0%, ${C.bg} 75%)`, border: `1px solid ${C.line}`, borderRadius: 10, position: "relative", overflow: "hidden" }}>
            <div style={{ position: "absolute", top: 10, left: 12, fontFamily: MONO, fontSize: 10, color: C.dim, pointerEvents: "none", lineHeight: 1.7 }}>
              DRAG · orbit&nbsp;&nbsp;&nbsp;WHEEL · zoom&nbsp;&nbsp;&nbsp;GRAB ROD · insert/withdraw
            </div>
            <div style={{ position: "absolute", bottom: 10, left: 12, fontFamily: MONO, fontSize: 11, color: C.violet, pointerEvents: "none" }}>
              bank insertion {(liveZ * 100).toFixed(0)}%{simT !== null ? ` · SCRAM t=${Math.min(simT, T_END).toFixed(1)}s` : ""}
            </div>
            <button onClick={() => setAutoOrbit((v) => !v)} style={{
              position: "absolute", top: 10, right: 12, background: autoOrbit ? C.cyan + "22" : "transparent",
              border: `1px solid ${autoOrbit ? C.cyan : C.line}`, color: autoOrbit ? C.cyan : C.dim,
              borderRadius: 6, padding: "4px 10px", fontFamily: MONO, fontSize: 10, cursor: "pointer",
            }}>auto-orbit {autoOrbit ? "✓" : "off"}</button>
          </div>
          <div style={{ display: "flex", justifyContent: "space-around", flexWrap: "wrap", background: C.panel, border: `1px solid ${C.line}`, borderRadius: 10, padding: "6px 4px" }}>
            <Gauge value={livePower * 100} min={0} max={110} zones={[[0, 90, C.steel], [90, 103, C.green], [103, 110, C.coral]]} label="THERMAL POWER" unit="%" fmt={(v) => v.toFixed(1)} />
            <Gauge value={liveRho} min={-6} max={0.5} zones={[[-6, -1, C.green], [-1, 0, C.amber], [0, 0.5, C.coral]]} label="REACTIVITY" unit="$" />
            <Gauge value={Scurve(liveZ) * mc.mW} min={0} max={4500} zones={[[0, rhoEx, C.coral], [rhoEx, rhoEx + betaN, C.amber], [rhoEx + betaN, 4500, C.green]]} label="INSERTED WORTH" unit="" fmt={(v) => v.toFixed(0)} />
            <Gauge value={mc.mS} min={-1} max={6} zones={[[-1, 1, C.coral], [1, 2, C.amber], [2, 6, C.green]]} label="SHUTDOWN MARGIN" unit="$" />
          </div>
        </div>

        {/* live plots */}
        <div style={{ flex: "1 1 380px", minWidth: 340, display: "flex", flexDirection: "column", gap: 12 }}>
          <Panel title="Integral rod worth — uncertainty band" sub="violet marker tracks the 3D bank position">
            <WorthCurve />
          </Panel>
          <Panel title="SCRAM transient — probabilistic fan" sub="220-member point-kinetics ensemble · cursor syncs with 3D">
            <Fan />
          </Panel>
          <Panel title="Shutdown margin distribution" sub={`${mc.nf}/${N} samples violate the $1 criterion`}>
            <SDMHist />
          </Panel>
          <Panel title="Variance decomposition (SRC²)" sub="what drives shutdown-margin uncertainty">
            <SensBars />
          </Panel>
        </div>
      </div>

      <div style={{ padding: "6px 18px 16px", fontSize: 10, color: C.dim, fontFamily: MONO, borderTop: `1px solid ${C.line}` }}>
        Generic illustrative core with in-core control rods. Reduced-order physics for demonstration — production console couples to MCNP/Shift/Griffin surrogates. N={N} LHS · seed {seed}.
      </div>
    </div>
  );
}
