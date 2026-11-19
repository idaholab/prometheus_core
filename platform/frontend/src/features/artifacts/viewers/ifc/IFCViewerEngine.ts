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

import * as OBC from "@thatopen/components";
import * as FRAGS from "@thatopen/fragments";
import CameraControls from "camera-controls";
import * as THREE from "three";
import * as WEBIFC from "web-ifc";
import {
  groupColumnsWithBasePlates,
  groupRoofPieces,
  groupWallPieces,
  type NameGroup,
  type NamedItem,
  type TreeGroup,
  type TreeGroupMember,
} from "./treeGrouping";

export type LoadProgress = {
  stage: "downloading" | "parsing" | "rendering";
  progress: number;
  message: string;
};

export type ViewerOptions = {
  container: HTMLElement;
  wasmCdnPath?: string;
};

export type EquipmentItem = { key: string; label: string };

// A single pipe segment/fitting, nested under its parent run.
export type PipeMemberItem = { key: string; label: string };

// A connected pipe run, with its member segments/fittings nested inside.
export type PipeRunItem = {
  key: string;
  label: string;
  members: PipeMemberItem[];
};

// A node in a visibility tree (walls / roof / columns): a parent group with its
// member pieces nested. Structurally identical to a pipe run — the overlay
// renders both through the same GroupedTreeSection. Defined in ./treeGrouping
// (shared with the OBJ engine); re-exported here for existing importers.
export type { TreeGroup, TreeGroupMember } from "./treeGrouping";

// Elements that resolve to no colour at all, neither on their geometry nor
// through any material chain (see computeMaterialColors), land on three.js's
// default white material. This is Blender's default "no material" object
// colour (0.8, 0.8, 0.8) used as a neutral stand-in so those elements read as
// gray instead of stark white. Applied only after the material pass has run.
const UNSTYLED_FALLBACK_COLOR = 0xcccccc;

// IFC entity types that count as "pipe" elements.
const PIPE_MEMBER_IFC_CLASSES = ["IfcPipeSegment", "IfcPipeFitting"];

// IFC entity types that represent a "piece of equipment" — concrete classes plus
// the abstract flow-element bases so we catch elements that weren't given a
// concrete subtype during authoring.
const EQUIPMENT_IFC_CLASSES = [
  "IfcPump",
  "IfcValve",
  "IfcTank",
  "IfcFan",
  "IfcChiller",
  "IfcCompressor",
  "IfcBoiler",
  "IfcCoolingTower",
  "IfcHeatExchanger",
  "IfcEvaporator",
  "IfcCondenser",
  "IfcFilter",
  "IfcMotor",
  "IfcTransformer",
  "IfcAirTerminal",
  "IfcAirTerminalBox",
  "IfcSanitaryTerminal",
  "IfcFlowMeter",
  "IfcUnitaryEquipment",
  "IfcDistributionChamberElement",
  "IfcFlowTerminal",
  "IfcFlowStorageDevice",
  "IfcFlowMovingDevice",
  "IfcFlowTreatmentDevice",
  "IfcEnergyConversionDevice",
];

// Categories matched by IFC entity type. This is the full catalog the engine
// understands — products decide which subset to expose as toggles; presence
// on a given model is resolved at runtime via enumerateCategories().
const CATEGORY_IFC_CLASSES: Record<string, string[]> = {
  walls: ["IfcWall", "IfcWallStandardCase"],
  floors: ["IfcSlab"],
  columns: ["IfcColumn"],
  beams: ["IfcBeam"],
  doors: ["IfcDoor"],
  windows: ["IfcWindow"],
  pipes: ["IfcPipeSegment", "IfcPipeFitting"],
  equipment: ["IfcFlowTerminal", "IfcFlowStorageDevice", "IfcFlowMovingDevice"],
  // Catches IfcRoof entities (e.g. reactor containment domes) in addition to
  // the name-pattern path that handles IfcSlab "Roof Slab" elements below.
  roofs: ["IfcRoof"],
};

// Categories matched by IFC Name attribute regex instead of entity type.
// A category may carry several patterns; every one is applied, and the results
// union with that category's CATEGORY_IFC_CLASSES matches.
// pattern: regex tested against Name; categories: optional entity-type filter.
//
// The envelope patterns are here because a clear-span industrial building's
// insulated metal panels carry no geometry on the panel itself: each
// "Envelope Panel - ..." IfcWall/IfcRoof is a bodyless container decomposed
// into two IfcPlate skins and an IfcBuildingElementPart core, and the flashing
// closing the joints between panels is IfcDiscreteAccessory, which belongs to
// no entity-type category at all. Matching by class alone would hide the
// containers and leave every visible surface standing.
//
// These strings are authored by the backend in
// ifcplus/api/building/clear_span_industrial_building.py (panel and flashing
// names) and ifcplus/api/built_element/insulated_metal_panel.py (the
// " - Outer Skin" / " - Core" / " - Inner Liner" suffixes). Renaming them there
// would silently break these toggles, which is what
// src/tests/components/viewer/IFCViewerEngine.test.ts exists to catch.
const CATEGORY_NAME_PATTERNS: Record<
  string,
  { pattern: RegExp; categories?: RegExp[] }[]
> = {
  walls: [
    // The skins and core of each wall panel - the pieces that own a body.
    {
      pattern: /^Envelope Panel - (?:Side|End) Wall .+ - .+$/i,
      categories: [/^IfcPlate$/i, /^IfcBuildingElementPart$/i],
    },
    // Corner flashing runs vertically and closes two wall faces, so it
    // follows the walls rather than the roof.
    {
      pattern: /^Envelope Flashing - Corner .+$/i,
      categories: [/^IfcDiscreteAccessory$/i],
    },
  ],
  roofs: [
    // Reactor containment domes author their roof as an IfcSlab named this.
    {
      pattern: /^Roof Slab$/i,
      categories: [/^IfcSlab$/i],
    },
    // Nuclear reactor models author the containment dome as a named
    // IfcBuildingElementProxy (predefined type CONTAINMENT_DOME), not an
    // IfcRoof or a "Roof Slab" — see create_dome() in
    // alchemy-backend/app/ifc_authoring_tools.py. Without this pattern the dome
    // matches no category and gets no sidebar toggle at all. (The containment
    // shell wall alongside it is an IfcWall, so the Walls toggle already owns
    // it — only the dome needed routing here.)
    {
      pattern: /^Containment Dome$/i,
      categories: [/^IfcBuildingElementProxy$/i],
    },
    {
      pattern: /^Envelope Panel - Roof - .+$/i,
      categories: [/^IfcPlate$/i, /^IfcBuildingElementPart$/i],
    },
    // Eave and rake flashing cap the roof edge, so they follow the roof.
    {
      pattern: /^Envelope Flashing - (?:Eave|Rake) .+$/i,
      categories: [/^IfcDiscreteAccessory$/i],
    },
  ],
};

// ============================================================================
// Pipe-run grouping — port connectivity (mirrors the backend Python splitter's
// group_piping_systems: connected-component analysis over the port graph,
// restricted to pipe segment/fitting entities, severed at equipment ports).
// ============================================================================

class UnionFind {
  private parent = new Map<string, string>();
  private rank = new Map<string, number>();

  find(x: string): string {
    if (!this.parent.has(x)) {
      this.parent.set(x, x);
      this.rank.set(x, 0);
    }
    let root = x;
    while (this.parent.get(root) !== root) root = this.parent.get(root)!;
    let cur = x;
    while (cur !== root) {
      const next = this.parent.get(cur)!;
      this.parent.set(cur, root);
      cur = next;
    }
    return root;
  }

  union(a: string, b: string): void {
    const ra = this.find(a);
    const rb = this.find(b);
    if (ra === rb) return;
    const rankA = this.rank.get(ra)!;
    const rankB = this.rank.get(rb)!;
    if (rankA < rankB) {
      this.parent.set(ra, rb);
    } else if (rankA > rankB) {
      this.parent.set(rb, ra);
    } else {
      this.parent.set(rb, ra);
      this.rank.set(ra, rankA + 1);
    }
  }

  components(ids: Iterable<string>): Map<string, Set<string>> {
    const groups = new Map<string, Set<string>>();
    for (const id of ids) {
      const root = this.find(id);
      if (!groups.has(root)) groups.set(root, new Set());
      groups.get(root)!.add(id);
    }
    return groups;
  }
}

export default class IFCViewerEngine {
  private components: OBC.Components;
  private world: OBC.SimpleWorld<
    OBC.SimpleScene,
    OBC.OrthoPerspectiveCamera,
    OBC.SimpleRenderer
  >;
  private fragments: OBC.FragmentsManager;
  private hider: OBC.Hider;
  private disposed = false;
  // Resolves when the first colour-correction pass finishes after a load.
  // loadIfcFromUrl awaits this before returning so the viewer's onLoad (which
  // dismisses the loading spinner) only fires once the model is actually
  // coloured — never during the settle-poll window when the dome still shows
  // default white and unstyled elements their stale Fragments gray. Created at
  // the start of each load; resolved in applyColorCorrections (and on dispose),
  // with a timeout backstop in waitForFirstColorPass so it can never hang.
  private colorPassDeferred: {
    promise: Promise<void>;
    resolve: () => void;
  } | null = null;
  private equipmentIdMaps = new Map<string, OBC.ModelIdMap>();
  private pipeRunIdMaps = new Map<string, OBC.ModelIdMap>(); // whole-run toggle
  private pipeMemberIdMaps = new Map<string, OBC.ModelIdMap>(); // single-segment toggle
  // Walls / roof / columns trees share these; keys are prefixed by category so
  // the three enumerations don't clobber one another (see clearTreePrefix).
  private treeGroupIdMaps = new Map<string, OBC.ModelIdMap>(); // whole-group toggle
  private treeMemberIdMaps = new Map<string, OBC.ModelIdMap>(); // single-piece toggle
  private ifcBuffers = new Map<string, Uint8Array>(); // raw bytes per modelId, for pipe-run grouping
  // Per-model set of Fragments localIds that have body geometry, computed once
  // from the raw IFC and memoised (standaloneBodyGroups is called once per
  // GROUPABLE category). Caches the in-flight promise so concurrent wall/roof
  // enumeration parses the buffer only once. Cleared on dispose.
  private bodyBearingCache = new Map<string, Promise<Set<number> | null>>();

  constructor(private opts: ViewerOptions) {
    this.components = new OBC.Components();

    const worlds = this.components.get(OBC.Worlds);
    this.world = worlds.create<
      OBC.SimpleScene,
      OBC.OrthoPerspectiveCamera,
      OBC.SimpleRenderer
    >();

    this.world.scene = new OBC.SimpleScene(this.components);
    this.world.scene.setup();

    // Keep ambient low so the directional creates real surface definition.
    // Total lit-face irradiance is 1.5 + 0.5 (+0.6 fill on back faces), so a
    // mid-gray albedo lands well under 1.0 before tone mapping.
    this.world.scene.config.directionalLight.intensity = 1.5;
    this.world.scene.config.ambientLight.intensity = 0.5;

    // Fill light from the opposite side so back faces aren't pitch black
    const fill = new THREE.DirectionalLight(0xffffff, 0.6);
    fill.position.set(-5, 8, -3);
    this.world.scene.three.add(fill);

    // Logarithmic depth so sub-millimetre layers (panel skins over cores) are
    // resolvable at building-scale camera distances instead of z-fighting.
    this.world.renderer = new OBC.SimpleRenderer(
      this.components,
      opts.container,
      { logarithmicDepthBuffer: true },
    );

    // Without this, three defaults to NoToneMapping: any lit color channel
    // over 1.0 hard-clips to pure white instead of rolling off smoothly.
    // A near-white albedo (e.g. foam cores, glass) under the combined light
    // above can exceed 1.0 on a face toward the light; this rolls it off.
    // `.three` here follows the same convention already used for
    // `world.camera.three` / `world.scene.three` elsewhere in this file.
    this.world.renderer.three.toneMapping = THREE.ACESFilmicToneMapping;
    this.world.renderer.three.toneMappingExposure = 1.0;

    this.world.camera = new OBC.OrthoPerspectiveCamera(this.components);

    this.components.init();

    this.fragments = this.components.get(OBC.FragmentsManager);
    this.hider = this.components.get(OBC.Hider);
  }

  // ── Init ──────────────────────────────────────────────────────────────────

  async init(): Promise<void> {
    const workerUrl = await OBC.FragmentsManager.getWorker();
    this.fragments.init(workerUrl);

    this.world.camera.controls.addEventListener("update", () => {
      this.fragments.core.update();
    });

    this.fragments.core.models.materials.list.onItemSet.add(
      ({ value: material }: { value: THREE.Material }) => {
        if (!("isLodMaterial" in material && material.isLodMaterial)) {
          // Fixed offset. A random factor here made coincident-face tiebreaks
          // nondeterministic across loads (white vs gray envelope panels).
          material.polygonOffset = true;
          material.polygonOffsetUnits = 1;
          material.polygonOffsetFactor = 1;
        }
        // Colour corrections happen later in applyColorCorrections(), once
        // materials have settled. A material can exist at default white for a
        // moment before its real authored colour lands; touching it here
        // risks locking in the wrong value.
      },
    );

    this.fragments.list.onItemSet.add(
      ({ value: model }: { value: FRAGS.FragmentsModel }) => {
        model.useCamera(this.world.camera.three);
        this.world.scene.three.add(model.object);
        this.fragments.core.update(true);

        // This first update(true) call runs on an empty model — its meshes
        // populate asynchronously afterward, and nothing re-triggers LOD
        // resolution once they do unless the camera happens to still be
        // actively moving (the only other thing calling update() is the
        // controls "update" listener above). Without a second pass, the LOD
        // proxy and the real mesh for the same geometry can both end up stuck
        // visible simultaneously, fighting over which one actually renders.
        // Force a few more passes shortly after load so this settles on its
        // own instead of requiring the user to nudge the camera first.
        for (const delay of [250, 750, 1500, 3000]) {
          setTimeout(() => this.fragments.core.update(true), delay);
        }

        // There's no verified "this model's materials are fully resolved"
        // event available here — onFragmentsLoaded was tried earlier and
        // doesn't fire in this load path (OBC.IfcLoader), which is why that
        // attempt was reverted. Rather than guess a fixed delay (which just
        // trades one failure mode for another — too short races ahead of a
        // real color still in flight, too long leaves a visible stale period
        // for no reason), poll until materials actually stop changing across
        // consecutive checks, then apply the colour corrections once.
        this.pollUntilMaterialsSettle(model);
      },
    );
  }

  // Snapshot every non-LOD material's color as one string, so two snapshots
  // can be compared for equality to detect "nothing changed since last
  // check" without caring which specific materials changed.
  private snapshotMaterialColors(model: FRAGS.FragmentsModel): string {
    const colors: string[] = [];
    model.object.traverse((child: THREE.Object3D) => {
      const mesh = child as THREE.Mesh;
      if (!mesh.isMesh) return;
      const mats = Array.isArray(mesh.material)
        ? mesh.material
        : [mesh.material];
      for (const m of mats) {
        if (
          "isLodMaterial" in m &&
          (m as { isLodMaterial?: boolean }).isLodMaterial
        )
          continue;
        const color = (m as THREE.MeshStandardMaterial).color;
        colors.push(color ? color.getHexString() : "none");
      }
    });
    return colors.join(",");
  }

  // Polls material colors instead of guessing a fixed delay: checks every
  // 250ms, and only treats the model as settled once two consecutive checks
  // come back identical (one match alone could be coincidence between two
  // different in-flight states happening to look the same for an instant).
  // Caps out at 20 checks (5s) so a model that genuinely never stabilizes
  // doesn't poll forever — at that point it applies the corrections anyway
  // using whatever state currently exists, same as the old fixed-delay
  // behavior would have.
  private pollUntilMaterialsSettle(
    model: FRAGS.FragmentsModel,
    maxChecks = 20,
    intervalMs = 250,
  ): void {
    let previousSnapshot: string | null = null;
    let stableCount = 0;
    let checks = 0;

    const check = () => {
      checks++;
      const snapshot = this.snapshotMaterialColors(model);
      if (snapshot === previousSnapshot) {
        stableCount++;
      } else {
        stableCount = 0;
        previousSnapshot = snapshot;
      }

      if (stableCount >= 2 || checks >= maxChecks) {
        void this.applyColorCorrections(model);
        return;
      }
      setTimeout(check, intervalMs);
    };

    setTimeout(check, intervalMs);
  }

  // Order matters: resolve authored material colours first, then gray out
  // whatever is still white. Doing the fallback first would paint over
  // elements the material pass is about to colour correctly.
  private async applyColorCorrections(
    model: FRAGS.FragmentsModel,
  ): Promise<void> {
    try {
      if (this.disposed) return;
      await this.applyMaterialColors(model);
      if (this.disposed) return;
      this.applyUnstyledFallback(model);
    } finally {
      // Whatever happened above (success, early dispose return, or a throw),
      // the first colour pass is now "done" as far as the reveal is concerned —
      // unblock loadIfcFromUrl so it never waits on a pass that already ran.
      this.colorPassDeferred?.resolve();
    }
  }

  // Fresh deferred for one load. Must be created before ifcLoader.load() so the
  // onItemSet → pollUntilMaterialsSettle → applyColorCorrections chain (which
  // the load triggers) resolves this instance, not a stale one.
  private createColorPassDeferred(): void {
    let resolve!: () => void;
    const promise = new Promise<void>((r) => {
      resolve = r;
    });
    this.colorPassDeferred = { promise, resolve };
  }

  // Wait for the first colour pass, with a timeout backstop. The settle-poll
  // itself caps at 5s (pollUntilMaterialsSettle) and always ends by calling
  // applyColorCorrections, so this normally resolves well under the timeout;
  // the race only guards the pathological case where onItemSet never fires for
  // this load (e.g. an empty model), so the spinner can't hang indefinitely.
  private async waitForFirstColorPass(timeoutMs = 8000): Promise<void> {
    const deferred = this.colorPassDeferred;
    if (!deferred) return;
    await Promise.race([
      deferred.promise,
      new Promise<void>((r) => setTimeout(r, timeoutMs)),
    ]);
  }

  // Run only once pollUntilMaterialsSettle above has confirmed materials
  // have actually stopped changing — not at material-creation time, and not
  // after a guessed delay. Anything still at three's default white at that
  // point has had its chance; this is a heuristic (pure white could in
  // principle be a real authored color on some future model), not a
  // definitive "has no material" check.
  private applyUnstyledFallback(model: FRAGS.FragmentsModel): void {
    model.object.traverse((child: THREE.Object3D) => {
      const mesh = child as THREE.Mesh;
      if (!mesh.isMesh) return;
      const mats = Array.isArray(mesh.material)
        ? mesh.material
        : [mesh.material];
      for (const m of mats) {
        if (
          "isLodMaterial" in m &&
          (m as { isLodMaterial?: boolean }).isLodMaterial
        )
          continue;
        const color = (m as THREE.MeshStandardMaterial).color;
        if (color && color.getHex() === 0xffffff) {
          color.setHex(UNSTYLED_FALLBACK_COLOR);
        }
      }
    });
  }

  // ── Load ──────────────────────────────────────────────────────────────────

  async loadIfcFromUrl(
    url: string,
    onProgress?: (p: LoadProgress) => void,
  ): Promise<void> {
    const ifcLoader = this.components.get(OBC.IfcLoader);

    // Arm the reveal gate before the load so the colour pass this load kicks
    // off (asynchronously, via the onItemSet listener) resolves it.
    this.createColorPassDeferred();

    // Pipe-run grouping (see enumeratePipeRuns) is computed by parsing the
    // raw IFC bytes directly with web-ifc — bypassing @thatopen/fragments'
    // IfcImporter entirely for that purpose — so ports/relations don't need
    // to survive the Fragments conversion at all. The buffer is kept so
    // enumeratePipeRuns can re-parse it later without re-fetching the file.
    await ifcLoader.setup({
      autoSetWasm: false,
      wasm: {
        path: this.opts.wasmCdnPath ?? "https://unpkg.com/web-ifc@0.0.77/",
        absolute: true,
      },
    });

    onProgress?.({
      stage: "downloading",
      progress: 0,
      message: "Downloading IFC file…",
    });

    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`IFC fetch failed: ${resp.status}`);
    const buffer = new Uint8Array(await resp.arrayBuffer());
    this.ifcBuffers.set("model", buffer);

    onProgress?.({
      stage: "parsing",
      progress: 0,
      message: "Processing geometry…",
    });

    await ifcLoader.load(buffer, false, "model", {
      processData: {
        progressCallback: (progress: number) => {
          onProgress?.({
            stage: "parsing",
            progress: Math.round(progress * 100),
            message: `Processing geometry… ${Math.round(progress * 100)}%`,
          });
        },
      },
    });

    // Hold the "ready" signal until the first colour-correction pass lands, so
    // the viewer dismisses its loading spinner onto an already-coloured model
    // instead of flashing default white/gray for ~1-2s while the settle-poll
    // runs. Geometry is fully present throughout — only colour is pending — so
    // framing and interaction are unaffected by the extra wait.
    await this.waitForFirstColorPass();

    onProgress?.({ stage: "rendering", progress: 100, message: "Complete!" });

    this.fitToFrame();
  }

  // ── Visibility ────────────────────────────────────────────────────────────

  async setCategoryVisible(category: string, visible: boolean): Promise<void> {
    const namePatterns = CATEGORY_NAME_PATTERNS[category];
    if (namePatterns) {
      for (const { pattern, categories } of namePatterns) {
        await this.setCategoryVisibleByName(pattern, visible, categories);
      }
      if (!(category in CATEGORY_IFC_CLASSES)) return;
    }

    const classes = CATEGORY_IFC_CLASSES[category];
    if (!classes) {
      console.warn(`[IFCViewerEngine] Unknown category: "${category}"`);
      return;
    }

    const regexes = classes.map((c) => new RegExp(`^${c}$`, "i"));
    const modelIdMap: OBC.ModelIdMap = {};

    for (const [, model] of this.fragments.list) {
      try {
        const items = await model.getItemsOfCategories(regexes);
        const localIds = Object.values(items).flat();
        if (localIds.length > 0) {
          modelIdMap[model.modelId] = new Set(localIds as number[]);
        }
      } catch (err) {
        console.warn(
          `[IFCViewerEngine] getItemsOfCategories failed for "${category}":`,
          err,
        );
      }
    }

    if (Object.keys(modelIdMap).length === 0) return;
    await this.hider.set(visible, modelIdMap);
  }

  private async setCategoryVisibleByName(
    namePattern: RegExp,
    visible: boolean,
    categories?: RegExp[],
  ): Promise<void> {
    const finder = this.components.get(OBC.ItemsFinder);
    const queryKey = `__name_${namePattern.source}_${categories?.map((r) => r.source).join("_") ?? ""}`;

    if (!finder.list.has(queryKey)) {
      const query: Record<string, unknown> = {
        attributes: { queries: [{ name: /^Name$/, value: namePattern }] },
      };
      if (categories) query.categories = categories;
      finder.create(queryKey, [query]);
    }

    const query = finder.list.get(queryKey);
    if (!query) return;

    let modelIdMap: OBC.ModelIdMap;
    try {
      modelIdMap = await query.test();
    } catch (err) {
      console.warn(
        `[IFCViewerEngine] ItemsFinder query failed for pattern "${namePattern}":`,
        err,
      );
      return;
    }

    if (Object.keys(modelIdMap).length === 0) return;
    await this.hider.set(visible, modelIdMap);
  }

  async resetVisibility(): Promise<void> {
    await this.hider.set(true);
  }

  // ── Category presence ────────────────────────────────────────────────────
  // An IFC can contain anything, so the UI only shows toggles for categories
  // the loaded model actually has. Returns the subset of `categories` present.
  // This is purely a tidiness/fallback layer — it doesn't gate any capability,
  // it just keeps the panel from showing empty accordions.

  async enumerateCategories(categories: string[]): Promise<string[]> {
    const present: string[] = [];
    for (const category of categories) {
      if (await this.categoryHasItems(category)) present.push(category);
    }
    return present;
  }

  private async categoryHasItems(category: string): Promise<boolean> {
    const namePatterns = CATEGORY_NAME_PATTERNS[category];
    if (namePatterns) {
      for (const { pattern, categories } of namePatterns) {
        if (await this.nameQueryHasItems(pattern, categories)) return true;
      }
    }

    const classes = CATEGORY_IFC_CLASSES[category];
    if (!classes) return false;

    const regexes = classes.map((c) => new RegExp(`^${c}$`, "i"));
    for (const [, model] of this.fragments.list) {
      try {
        const items = await model.getItemsOfCategories(regexes);
        if (Object.values(items).flat().length > 0) return true;
      } catch (err) {
        console.warn(
          `[IFCViewerEngine] getItemsOfCategories failed for "${category}":`,
          err,
        );
      }
    }
    return false;
  }

  private async nameQueryHasItems(
    namePattern: RegExp,
    categories?: RegExp[],
  ): Promise<boolean> {
    const finder = this.components.get(OBC.ItemsFinder);
    const queryKey = `__name_${namePattern.source}_${categories?.map((r) => r.source).join("_") ?? ""}`;

    if (!finder.list.has(queryKey)) {
      const query: Record<string, unknown> = {
        attributes: { queries: [{ name: /^Name$/, value: namePattern }] },
      };
      if (categories) query.categories = categories;
      finder.create(queryKey, [query]);
    }

    const query = finder.list.get(queryKey);
    if (!query) return false;

    try {
      const modelIdMap = await query.test();
      return Object.values(modelIdMap).some(
        (ids) => (ids as Set<number>).size > 0,
      );
    } catch (err) {
      console.warn(
        `[IFCViewerEngine] ItemsFinder query failed for pattern "${namePattern}":`,
        err,
      );
      return false;
    }
  }

  // ── Equipment enumeration / toggling ──────────────────────────────────────

  async enumerateEquipment(): Promise<EquipmentItem[]> {
    this.equipmentIdMaps.clear();
    const regexes = EQUIPMENT_IFC_CLASSES.map((c) => new RegExp(`^${c}$`, "i"));
    const items: EquipmentItem[] = [];

    for (const [, model] of this.fragments.list) {
      let byCategory: { [category: string]: number[] };
      try {
        byCategory = await model.getItemsOfCategories(regexes);
      } catch (err) {
        console.warn(`[IFCViewerEngine] getItemsOfCategories failed:`, err);
        continue;
      }

      const localIds = Object.values(byCategory).flat();
      if (localIds.length === 0) continue;

      let dataList: FRAGS.ItemData[] = [];
      try {
        dataList = await model.getItemsData(localIds, {
          attributes: ["Name"],
          attributesDefault: false,
          relationsDefault: { attributes: false, relations: false },
        });
      } catch (err) {
        console.warn(`[IFCViewerEngine] getItemsData failed:`, err);
      }

      for (let i = 0; i < localIds.length; i++) {
        const localId = localIds[i];
        const nameAttr = dataList[i]?.Name as { value?: unknown } | undefined;
        const rawName =
          nameAttr && typeof nameAttr === "object" && "value" in nameAttr
            ? nameAttr.value
            : undefined;
        const label =
          typeof rawName === "string" && rawName.length > 0
            ? rawName
            : `#${localId}`;
        const key = `${model.modelId}:${localId}`;
        this.equipmentIdMaps.set(key, { [model.modelId]: new Set([localId]) });
        items.push({ key, label });
      }
    }

    items.sort((a, b) =>
      a.label.localeCompare(b.label, undefined, { numeric: true }),
    );
    return items;
  }

  async setEquipmentVisible(key: string, visible: boolean): Promise<void> {
    const idMap = this.equipmentIdMaps.get(key);
    if (!idMap) return;
    await this.hider.set(visible, idMap);
  }

  // ── Pipe run enumeration / toggling ───────────────────────────────────────
  // Groups pipe segments/fittings into continuous runs via port connectivity,
  // mirroring the backend splitter's group_piping_systems(): union-find over
  // the port graph, restricted to piping entities, severed at equipment ports.
  //
  // @thatopen/fragments' IfcImporter filters out IfcDistributionPort and the
  // IfcRelNests/IfcRelConnectsPorts relations during IFC->Fragments
  // conversion (confirmed: adding them to importer.classes/importer.relations
  // has no effect on actual output — those configs are apparently snapshotted
  // before onIfcImporterInitialized fires). Rather than fight that, this
  // parses the *raw* IFC bytes a second time with web-ifc directly (the same
  // underlying parser Fragments itself uses, with zero filtering), computes
  // the grouping there, and bridges the result back to Fragments local ids
  // via GlobalId, which does survive the Fragments conversion normally.
  //
  // If a model's ports/nest relations aren't authored (or don't survive
  // export), every pipe simply falls back to its own single-member run below
  // — grouping degrades gracefully rather than requiring the relations.

  private async computePipeRunGlobalIdGroups(
    buffer: Uint8Array,
  ): Promise<Set<string>[]> {
    const ifcApi = new WEBIFC.IfcAPI();
    ifcApi.SetWasmPath(
      this.opts.wasmCdnPath ?? "https://unpkg.com/web-ifc@0.0.77/",
      true,
    );
    await ifcApi.Init();

    let modelID: number | null = null;
    try {
      modelID = ifcApi.OpenModel(buffer);
      const mid = modelID;

      const getIds = (type: number | undefined): number[] => {
        if (type === undefined) return [];
        const ids: number[] = [];
        const vec = ifcApi.GetLineIDsWithType(mid, type);
        for (let i = 0; i < vec.size(); i++) ids.push(vec.get(i));
        return ids;
      };
      const getLine = (id: number): Record<string, unknown> =>
        ifcApi.GetLine(mid, id) as unknown as Record<string, unknown>;
      const asHandleArray = (raw: unknown): { value?: number }[] => {
        if (raw == null) return [];
        return (Array.isArray(raw) ? raw : [raw]) as { value?: number }[];
      };

      const pipeIds = [
        ...getIds(WEBIFC.IFCPIPESEGMENT),
        ...getIds(WEBIFC.IFCPIPEFITTING),
      ];
      const pipeIdSet = new Set(pipeIds);
      if (pipeIds.length === 0) return [];

      const equipmentIds = new Set<number>();
      for (const className of EQUIPMENT_IFC_CLASSES) {
        const type = (WEBIFC as unknown as Record<string, number>)[
          className.toUpperCase()
        ];
        for (const id of getIds(type)) equipmentIds.add(id);
      }

      const portToParent = new Map<number, number>();
      for (const relId of getIds(WEBIFC.IFCRELNESTS)) {
        const rel = getLine(relId);
        const parent = (rel.RelatingObject as { value?: number } | undefined)
          ?.value;
        if (parent === undefined || !pipeIdSet.has(parent)) continue;
        for (const child of asHandleArray(rel.RelatedObjects)) {
          if (child.value !== undefined) portToParent.set(child.value, parent);
        }
      }

      const uf = new UnionFind();
      for (const id of pipeIds) uf.find(String(id));

      for (const relId of getIds(WEBIFC.IFCRELCONNECTSPORTS)) {
        const rel = getLine(relId);
        const a = (rel.RelatingPort as { value?: number } | undefined)?.value;
        const b = (rel.RelatedPort as { value?: number } | undefined)?.value;
        if (a === undefined || b === undefined) continue;
        const parentA = portToParent.get(a);
        const parentB = portToParent.get(b);
        if (parentA === undefined || parentB === undefined) continue;
        if (equipmentIds.has(parentA) || equipmentIds.has(parentB)) continue;
        uf.union(String(parentA), String(parentB));
      }

      const groups = uf.components(pipeIds.map(String));

      const idToGlobalId = new Map<number, string>();
      for (const id of pipeIds) {
        const globalIdAttr = getLine(id).GlobalId as
          | { value?: string }
          | undefined;
        if (globalIdAttr?.value) idToGlobalId.set(id, globalIdAttr.value);
      }

      return [...groups.values()].map((members) => {
        const globalIds = new Set<string>();
        for (const memberIdStr of members) {
          const gid = idToGlobalId.get(Number(memberIdStr));
          if (gid) globalIds.add(gid);
        }
        return globalIds;
      });
    } finally {
      if (modelID !== null) {
        try {
          ifcApi.CloseModel(modelID);
        } catch {
          /* ignore */
        }
      }
    }
  }

  // ── Material colour resolution ───────────────────────────────────────────
  // IFC allows colour to be authored in two places: directly on geometry
  // (IfcStyledItem whose Item points at a representation item) or on the
  // material (IfcStyledItem with a null Item, reached via
  // IfcMaterialDefinitionRepresentation). Geometry styles take precedence.
  //
  // Files produced by IfcOpenShell's material/style API frequently carry
  // *only* material styles (model__89_.ifc has nine IfcStyledItems and every
  // one has a null Item). Reaching that colour from an element means walking
  // IfcRelAssociatesMaterial through whatever the RelatingMaterial is
  // (plain IfcMaterial, LayerSetUsage, LayerSet, ProfileSetUsage, ProfileSet,
  // ConstituentSet, MaterialList) down to an IfcMaterial, and if the element
  // has no association of its own, doing the same for its type via
  // IfcRelDefinesByType. That is what IfcOpenShell's own
  // get_material(should_inherit=True) does, and what this reproduces.
  //
  // This viewer is shared across apps and cannot assume any particular
  // generator authored geometry styles, so the resolution is done here, on
  // the raw IFC bytes via web-ifc (same approach as the pipe-run grouping),
  // and bridged to Fragments local ids via GlobalId. Elements whose geometry
  // already carries a style are skipped so a material style never overrides
  // a geometry style.
  //
  // Multi-material elements (layer sets, profile sets) get the first material
  // in authored order that carries a colour. That is a simplification: a
  // layered wall is really several colours. Good enough for a whole-element
  // tint; refine per-layer only if something actually needs it.

  private async computeMaterialColors(
    buffer: Uint8Array,
  ): Promise<Map<string, string>> {
    const ifcApi = new WEBIFC.IfcAPI();
    ifcApi.SetWasmPath(
      this.opts.wasmCdnPath ?? "https://unpkg.com/web-ifc@0.0.77/",
      true,
    );
    await ifcApi.Init();

    const result = new Map<string, string>();
    let modelID: number | null = null;
    try {
      modelID = ifcApi.OpenModel(buffer);
      const mid = modelID;

      const getIds = (type: number | undefined): number[] => {
        if (type === undefined) return [];
        const ids: number[] = [];
        const vec = ifcApi.GetLineIDsWithType(mid, type);
        for (let i = 0; i < vec.size(); i++) ids.push(vec.get(i));
        return ids;
      };
      const lineCache = new Map<number, Record<string, unknown>>();
      const getLine = (id: number): Record<string, unknown> => {
        let line = lineCache.get(id);
        if (!line) {
          line = ifcApi.GetLine(mid, id) as unknown as Record<string, unknown>;
          lineCache.set(id, line);
        }
        return line;
      };
      const asHandleArray = (raw: unknown): { value?: number }[] => {
        if (raw == null) return [];
        return (Array.isArray(raw) ? raw : [raw]) as { value?: number }[];
      };
      const asHandle = (raw: unknown): number | undefined =>
        (raw as { value?: number } | undefined)?.value;

      // ── Step 1: materialId -> hex, via IfcMaterialDefinitionRepresentation
      // -> IfcStyledRepresentation -> IfcStyledItem -> IfcSurfaceStyle
      // -> IfcSurfaceStyleShading/Rendering -> IfcColourRgb.
      const materialColor = new Map<number, string>();
      for (const mdrId of getIds(WEBIFC.IFCMATERIALDEFINITIONREPRESENTATION)) {
        const mdr = getLine(mdrId);
        const materialId = asHandle(mdr.RepresentedMaterial);
        if (materialId === undefined) continue;

        for (const repHandle of asHandleArray(mdr.Representations)) {
          if (repHandle.value === undefined) continue;
          const rep = getLine(repHandle.value);

          for (const itemHandle of asHandleArray(rep.Items)) {
            if (itemHandle.value === undefined) continue;
            const item = getLine(itemHandle.value);

            for (const styleHandle of asHandleArray(item.Styles)) {
              const styleId = styleHandle.value;
              if (styleId === undefined) continue;
              const style = getLine(styleId);

              // IfcStyledItem.Styles entries are either an IfcSurfaceStyle
              // directly (IFC4 — the common case, and what IfcOpenShell's
              // material/style API writes) or an IfcPresentationStyleAssignment
              // wrapping one (IFC2x3 and some IFC4 writers). BOTH entities
              // expose a `.Styles` attribute — on IfcSurfaceStyle it is the set
              // of shadings/renderings, on the assignment it is the wrapped
              // presentation styles — so the two can only be told apart by
              // entity type, never by presence of `.Styles`. An earlier
              // `style.Styles ?? [styleHandle]` here assumed IfcSurfaceStyle had
              // no `.Styles`, so on a bare IfcSurfaceStyle it descended one
              // level too far (onto the shading), found no SurfaceColour, and
              // left every such element to the unstyled gray fallback — e.g.
              // concrete domes authored with only a material-level surface
              // style rendered white-ish instead of their authored gray.
              const surfaceStyleHandles =
                style.type === WEBIFC.IFCSURFACESTYLE
                  ? [styleHandle]
                  : asHandleArray(style.Styles);

              for (const ssHandle of surfaceStyleHandles) {
                if (ssHandle.value === undefined) continue;
                const surfaceStyle = getLine(ssHandle.value);
                // An IfcPresentationStyleAssignment can also carry curve / text
                // / fill styles; only IfcSurfaceStyle holds the shadings a
                // surface colour comes from, so skip anything else here.
                if (surfaceStyle.type !== WEBIFC.IFCSURFACESTYLE) continue;

                for (const shadingHandle of asHandleArray(
                  surfaceStyle.Styles,
                )) {
                  if (shadingHandle.value === undefined) continue;
                  const shading = getLine(shadingHandle.value);
                  const colourId = asHandle(shading.SurfaceColour);
                  if (colourId === undefined) continue;
                  const colour = getLine(colourId);
                  const r = Number(
                    (colour.Red as { value?: unknown })?.value ??
                      colour.Red ??
                      0,
                  );
                  const g = Number(
                    (colour.Green as { value?: unknown })?.value ??
                      colour.Green ??
                      0,
                  );
                  const b = Number(
                    (colour.Blue as { value?: unknown })?.value ??
                      colour.Blue ??
                      0,
                  );
                  if (!materialColor.has(materialId)) {
                    materialColor.set(
                      materialId,
                      new THREE.Color(r, g, b).getHexString(),
                    );
                  }
                }
              }
            }
          }
        }
      }
      if (materialColor.size === 0) return result;

      // ── Step 2: resolve any IfcMaterialSelect down to the first coloured
      // IfcMaterial. Attribute-name based rather than type-code based so it
      // tolerates IFC2x3 / IFC4 / IFC4x3 differences without a per-schema
      // table. Each attribute below is the single hop that entity makes
      // toward an IfcMaterial:
      //   IfcMaterialLayerSetUsage.ForLayerSet
      //   IfcMaterialProfileSetUsage.ForProfileSet
      //   IfcMaterialLayerSet.MaterialLayers[]
      //   IfcMaterialProfileSet.MaterialProfiles[]
      //   IfcMaterialConstituentSet.MaterialConstituents[]
      //   IfcMaterialList.Materials[]
      //   IfcMaterialLayer / Profile / Constituent.Material
      const CHAIN_ATTRS = [
        "Material",
        "ForLayerSet",
        "ForProfileSet",
        "MaterialLayers",
        "MaterialProfiles",
        "MaterialConstituents",
        "Materials",
      ];
      const resolvedSelect = new Map<number, string | null>();
      const resolveSelect = (
        id: number,
        visited = new Set<number>(),
      ): string | null => {
        if (resolvedSelect.has(id)) return resolvedSelect.get(id)!;
        if (visited.has(id)) return null;
        visited.add(id);

        const direct = materialColor.get(id);
        if (direct !== undefined) {
          resolvedSelect.set(id, direct);
          return direct;
        }

        const line = getLine(id);
        let found: string | null = null;
        for (const attr of CHAIN_ATTRS) {
          if (!(attr in line)) continue;
          for (const h of asHandleArray(line[attr])) {
            if (h.value === undefined) continue;
            found = resolveSelect(h.value, visited);
            if (found) break;
          }
          if (found) break;
        }
        resolvedSelect.set(id, found);
        return found;
      };

      // ── Step 3: objectId -> hex for every object (element or type) that
      // has its own IfcRelAssociatesMaterial resolving to a colour.
      const ownColor = new Map<number, string>();
      for (const relId of getIds(WEBIFC.IFCRELASSOCIATESMATERIAL)) {
        const rel = getLine(relId);
        const selectId = asHandle(rel.RelatingMaterial);
        if (selectId === undefined) continue;
        const hex = resolveSelect(selectId);
        if (!hex) continue;
        for (const objHandle of asHandleArray(rel.RelatedObjects)) {
          if (objHandle.value !== undefined && !ownColor.has(objHandle.value)) {
            ownColor.set(objHandle.value, hex);
          }
        }
      }

      // ── Step 4: elements with no own colour inherit their type's.
      const elementColor = new Map<number, string>(ownColor);
      for (const relId of getIds(WEBIFC.IFCRELDEFINESBYTYPE)) {
        const rel = getLine(relId);
        const typeId = asHandle(rel.RelatingType);
        if (typeId === undefined) continue;
        const typeHex = ownColor.get(typeId);
        if (!typeHex) continue;
        for (const objHandle of asHandleArray(rel.RelatedObjects)) {
          const elementId = objHandle.value;
          if (elementId !== undefined && !elementColor.has(elementId)) {
            elementColor.set(elementId, typeHex);
          }
        }
      }
      if (elementColor.size === 0) return result;

      // ── Step 5: geometry styles win. Collect every representation item that
      // carries an IfcStyledItem of its own, then skip any element whose
      // body (directly or through one IfcMappedItem hop) uses one of them.
      const styledGeometryItems = new Set<number>();
      for (const siId of getIds(WEBIFC.IFCSTYLEDITEM)) {
        const itemId = asHandle(getLine(siId).Item);
        if (itemId !== undefined) styledGeometryItems.add(itemId);
      }
      const hasGeometryStyle = (elementId: number): boolean => {
        if (styledGeometryItems.size === 0) return false;
        const pdsId = asHandle(getLine(elementId).Representation);
        if (pdsId === undefined) return false;
        for (const repHandle of asHandleArray(getLine(pdsId).Representations)) {
          if (repHandle.value === undefined) continue;
          for (const itemHandle of asHandleArray(
            getLine(repHandle.value).Items,
          )) {
            const itemId = itemHandle.value;
            if (itemId === undefined) continue;
            if (styledGeometryItems.has(itemId)) return true;
            const item = getLine(itemId);
            const srcId = asHandle(item.MappingSource);
            if (srcId === undefined) continue;
            const mappedRepId = asHandle(getLine(srcId).MappedRepresentation);
            if (mappedRepId === undefined) continue;
            for (const inner of asHandleArray(getLine(mappedRepId).Items)) {
              if (
                inner.value !== undefined &&
                styledGeometryItems.has(inner.value)
              )
                return true;
            }
          }
        }
        return false;
      };

      // ── Step 6: key by GlobalId for the bridge back to Fragments.
      for (const [elementId, hex] of elementColor) {
        const line = getLine(elementId);
        const globalIdAttr = line.GlobalId as { value?: string } | undefined;
        if (!globalIdAttr?.value) continue; // types have GlobalIds too; harmless
        if (hasGeometryStyle(elementId)) continue;
        result.set(globalIdAttr.value, hex);
      }
    } finally {
      if (modelID !== null) {
        try {
          ifcApi.CloseModel(modelID);
        } catch {
          /* ignore */
        }
      }
    }

    return result;
  }

  // The single place that talks to Fragments' per-item colouring API.
  // Signature in @thatopen/fragments: setColor(localIds, color: THREE.Color).
  private async setItemsColor(
    model: FRAGS.FragmentsModel,
    localIds: number[],
    color: THREE.Color,
  ): Promise<void> {
    await model.setColor(localIds, color);
  }

  private async applyMaterialColors(
    model: FRAGS.FragmentsModel,
  ): Promise<void> {
    const buffer = this.ifcBuffers.get(model.modelId);
    if (!buffer) return;

    let colorsByGlobalId: Map<string, string>;
    try {
      colorsByGlobalId = await this.computeMaterialColors(buffer);
    } catch (err) {
      console.warn("[IFCViewerEngine] computeMaterialColors failed:", err);
      return;
    }
    if (colorsByGlobalId.size === 0) return;

    let byCategory: { [category: string]: number[] };
    try {
      byCategory = await model.getItemsOfCategories([/^Ifc/i]);
    } catch (err) {
      console.warn(
        "[IFCViewerEngine] getItemsOfCategories (material colour) failed:",
        err,
      );
      return;
    }
    const localIds = Object.values(byCategory).flat();
    if (localIds.length === 0) return;

    let guids: (string | null)[] = [];
    try {
      guids = await model.getGuidsByLocalIds(localIds);
    } catch (err) {
      console.warn(
        "[IFCViewerEngine] getGuidsByLocalIds (material colour) failed:",
        err,
      );
      return;
    }

    // One call per distinct colour rather than one per item.
    const idsByColor = new Map<string, number[]>();
    localIds.forEach((localId, i) => {
      const guid = guids[i];
      if (!guid) return;
      const hex = colorsByGlobalId.get(guid);
      if (!hex) return;
      if (!idsByColor.has(hex)) idsByColor.set(hex, []);
      idsByColor.get(hex)!.push(localId);
    });
    if (idsByColor.size === 0) return;

    for (const [hex, ids] of idsByColor) {
      try {
        await this.setItemsColor(model, ids, new THREE.Color(`#${hex}`));
      } catch (err) {
        console.warn(
          `[IFCViewerEngine] setItemsColor failed for colour #${hex}:`,
          err,
        );
      }
    }
    console.debug(
      `[IFCViewerEngine] model "${model.modelId}": material colours applied to ` +
        `${[...idsByColor.values()].flat().length} item(s) across ${idsByColor.size} colour(s): ` +
        [...idsByColor.keys()].map((h) => `#${h}`).join(", "),
    );
  }

  async enumeratePipeRuns(): Promise<PipeRunItem[]> {
    this.pipeRunIdMaps.clear();
    this.pipeMemberIdMaps.clear();
    const runs: PipeRunItem[] = [];

    for (const [, model] of this.fragments.list) {
      const pipeRegexes = PIPE_MEMBER_IFC_CLASSES.map(
        (c) => new RegExp(`^${c}$`, "i"),
      );

      let pipeByCategory: { [category: string]: number[] };
      try {
        pipeByCategory = await model.getItemsOfCategories(pipeRegexes);
      } catch (err) {
        console.warn(
          "[IFCViewerEngine] getItemsOfCategories(pipe runs) failed:",
          err,
        );
        continue;
      }

      const pipeIds = Object.values(pipeByCategory).flat();
      if (pipeIds.length === 0) continue;

      let itemData: FRAGS.ItemData[] = [];
      try {
        itemData = await model.getItemsData(pipeIds, {
          attributes: ["Name"],
          attributesDefault: false,
          relationsDefault: { attributes: false, relations: false },
        });
      } catch (err) {
        console.warn("[IFCViewerEngine] getItemsData(pipe Name) failed:", err);
      }

      let guids: (string | null)[] = [];
      try {
        guids = await model.getGuidsByLocalIds(pipeIds);
      } catch (err) {
        console.warn("[IFCViewerEngine] getGuidsByLocalIds failed:", err);
      }

      const nameByLocalId = new Map<number, string>();
      const localIdByGlobalId = new Map<string, number>();
      pipeIds.forEach((localId, i) => {
        const nameAttr = itemData[i]?.Name as { value?: unknown } | undefined;
        const rawName =
          nameAttr && typeof nameAttr === "object" && "value" in nameAttr
            ? nameAttr.value
            : undefined;
        nameByLocalId.set(
          localId,
          typeof rawName === "string" && rawName.length > 0
            ? rawName
            : `#${localId}`,
        );

        const guid = guids[i];
        if (typeof guid === "string" && guid.length > 0) {
          localIdByGlobalId.set(guid, localId);
        }
      });

      const buffer = this.ifcBuffers.get(model.modelId);
      let globalIdGroups: Set<string>[] = [];
      if (!buffer) {
        console.warn(
          `[IFCViewerEngine] No stored IFC buffer for model "${model.modelId}" — ` +
            "pipe runs will fall back to one run per segment. This shouldn't happen " +
            "if the model was loaded via loadIfcFromUrl().",
        );
      } else {
        try {
          globalIdGroups = await this.computePipeRunGlobalIdGroups(buffer);
        } catch (err) {
          console.warn(
            "[IFCViewerEngine] computePipeRunGlobalIdGroups failed:",
            err,
          );
        }
      }

      const usedLocalIds = new Set<number>();
      let runIndex = 0;
      for (const globalIds of globalIdGroups) {
        const memberLocalIds: number[] = [];
        for (const gid of globalIds) {
          const localId = localIdByGlobalId.get(gid);
          if (localId !== undefined) memberLocalIds.push(localId);
        }
        if (memberLocalIds.length === 0) continue;

        runIndex += 1;
        const runKey = `run:${model.modelId}:${runIndex}`;
        const runIdMap: OBC.ModelIdMap = { [model.modelId]: new Set() };
        const memberItems: PipeMemberItem[] = [];

        for (const localId of memberLocalIds) {
          usedLocalIds.add(localId);
          const memberKey = `${model.modelId}:${localId}`;
          runIdMap[model.modelId]!.add(localId);
          this.pipeMemberIdMaps.set(memberKey, {
            [model.modelId]: new Set([localId]),
          });
          memberItems.push({
            key: memberKey,
            label: nameByLocalId.get(localId) ?? `#${localId}`,
          });
        }

        memberItems.sort((a, b) =>
          a.label.localeCompare(b.label, undefined, { numeric: true }),
        );
        this.pipeRunIdMaps.set(runKey, runIdMap);
        runs.push({
          key: runKey,
          label: `Pipe run ${runIndex} (${memberItems.length} segments)`,
          members: memberItems,
        });
      }

      let fallbackCount = 0;
      for (const localId of pipeIds) {
        if (usedLocalIds.has(localId)) continue;
        fallbackCount++;
        runIndex += 1;
        const runKey = `run:${model.modelId}:${runIndex}`;
        const memberKey = `${model.modelId}:${localId}`;
        this.pipeMemberIdMaps.set(memberKey, {
          [model.modelId]: new Set([localId]),
        });
        this.pipeRunIdMaps.set(runKey, { [model.modelId]: new Set([localId]) });
        runs.push({
          key: runKey,
          label: `Pipe run ${runIndex} (1 segments)`,
          members: [
            {
              key: memberKey,
              label: nameByLocalId.get(localId) ?? `#${localId}`,
            },
          ],
        });
      }
      console.debug(
        `[IFCViewerEngine] model "${model.modelId}": ${runIndex} pipe run(s) ` +
          `(${fallbackCount} ungrouped fallback${fallbackCount === 1 ? "" : "s"} out of ${pipeIds.length} pipe elements)`,
      );
    }

    runs.sort((a, b) =>
      a.label.localeCompare(b.label, undefined, { numeric: true }),
    );
    return runs;
  }

  async setPipeRunVisible(key: string, visible: boolean): Promise<void> {
    const idMap = this.pipeRunIdMaps.get(key);
    if (!idMap) return;
    await this.hider.set(visible, idMap);
  }

  async setPipeMemberVisible(key: string, visible: boolean): Promise<void> {
    const idMap = this.pipeMemberIdMaps.get(key);
    if (!idMap) return;
    await this.hider.set(visible, idMap);
  }

  // ── Element trees (walls / roof / columns) ────────────────────────────────
  // An element with internal structure — an insulated-metal-panel face and its
  // three layers, or a column and the base-plate assembly bolted to it — is
  // presented as a 2-level tree instead of a single flat toggle, mirroring the
  // pipe-run tree above. Grouping is name-based via ./treeGrouping, which the
  // OBJ viewer shares. Each enumeration returns [] when the model has nothing to
  // group, which the UI reads as "keep this category's flat toggle".

  async enumerateWallGroups(): Promise<TreeGroup[]> {
    return this.enumerateTree(
      "wall",
      ["IfcPlate", "IfcBuildingElementPart", "IfcDiscreteAccessory"],
      groupWallPieces,
      ["IfcWall", "IfcWallStandardCase"],
    );
  }

  async enumerateRoofGroups(): Promise<TreeGroup[]> {
    return this.enumerateTree(
      "roof",
      ["IfcPlate", "IfcBuildingElementPart", "IfcDiscreteAccessory"],
      groupRoofPieces,
      ["IfcRoof"],
    );
  }

  async enumerateColumnGroups(): Promise<TreeGroup[]> {
    this.clearTreePrefix("column");
    const groups: TreeGroup[] = [];
    for (const [, model] of this.fragments.list) {
      const columns = await this.namedItemsOfClasses(model, ["IfcColumn"]);
      if (columns.length === 0) continue;
      // Base plates and their fasteners are IfcPlate / IfcMechanicalFastener;
      // the join back to the column is purely by name ("Base Plate for <col>").
      const candidates = await this.namedItemsOfClasses(model, [
        "IfcPlate",
        "IfcMechanicalFastener",
      ]);
      const nameGroups = groupColumnsWithBasePlates(columns, candidates);
      groups.push(...this.materializeTreeGroups("column", model, nameGroups));
    }
    return groups;
  }

  async setTreeGroupVisible(key: string, visible: boolean): Promise<void> {
    const idMap = this.treeGroupIdMaps.get(key);
    if (!idMap) return;
    await this.hider.set(visible, idMap);
  }

  async setTreeMemberVisible(key: string, visible: boolean): Promise<void> {
    const idMap = this.treeMemberIdMaps.get(key);
    if (!idMap) return;
    await this.hider.set(visible, idMap);
  }

  private async enumerateTree(
    prefix: string,
    classes: string[],
    group: (items: NamedItem[]) => NameGroup[],
    // The category's own primary classes (IfcWall for walls, IfcRoof for
    // roofs). When `group` produces a tree, every body-bearing element of these
    // classes that the tree didn't already account for is appended as its own
    // single-element group — see standaloneBodyGroups for why.
    standaloneClasses: string[] = [],
  ): Promise<TreeGroup[]> {
    this.clearTreePrefix(prefix);
    const groups: TreeGroup[] = [];
    for (const [, model] of this.fragments.list) {
      const items = await this.namedItemsOfClasses(model, classes);
      const nameGroups = group(items);
      // No tree for this model → return nothing for it, so the UI keeps the
      // flat class toggle, which already hides/shows every element of the
      // category (including the standalone ones). We only need to augment when
      // the tree exists, because the tree *suppresses* that flat toggle.
      if (nameGroups.length === 0) continue;
      const standalone = standaloneClasses.length
        ? await this.standaloneBodyGroups(model, standaloneClasses)
        : [];
      groups.push(
        ...this.materializeTreeGroups(prefix, model, [
          ...nameGroups,
          ...standalone,
        ]),
      );
    }
    return groups;
  }

  // A GROUPABLE category (walls/roof) builds its tree from the panel *pieces*
  // (IfcPlate / IfcBuildingElementPart), so a plain IfcWall / IfcRoof that isn't
  // part of an insulated-metal-panel — e.g. a reactor containment's cylindrical
  // shell wall or hemispherical dome roof — lands in no group. And because the
  // tree suppresses the category's flat class toggle (StepModelViewer renders
  // "either its flat toggle or its tree, never both"), those elements would have
  // no sidebar control at all. This returns one single-element group per such
  // element so each stays individually toggleable under its category.
  //
  // Only body-bearing elements are included. The insulated-metal-panel faces are
  // authored as bodyless IfcWall/IfcRoof *containers* decomposed into their skin
  // and core pieces (which the tree already groups); including those here would
  // add dead toggles that control no visible geometry. Fragments' own
  // "items with geometry" set cleanly separates the real standalone elements
  // from those containers.
  private async standaloneBodyGroups(
    model: FRAGS.FragmentsModel,
    classes: string[],
  ): Promise<NameGroup[]> {
    const items = await this.namedItemsOfClasses(model, classes);
    if (items.length === 0) return [];
    const bodyIds = await this.getBodyBearingLocalIds(model);
    // bodyIds === null means we couldn't determine geometry (no stored buffer);
    // fall back to including everything so nothing silently loses its toggle.
    const kept = bodyIds ? items.filter((it) => bodyIds.has(it.id)) : items;
    return kept.map((it) => ({
      label: it.name,
      members: [{ id: it.id, label: it.name }],
    }));
  }

  // Fragments localIds of elements that carry body geometry, memoised per model
  // (the promise is cached so concurrent wall/roof enumeration asks Fragments
  // once). Returns null only if the query errors, which callers treat as
  // "can't tell — include everything" rather than silently dropping toggles.
  private getBodyBearingLocalIds(
    model: FRAGS.FragmentsModel,
  ): Promise<Set<number> | null> {
    const cached = this.bodyBearingCache.get(model.modelId);
    if (cached) return cached;
    const pending = this.computeBodyBearingLocalIds(model);
    this.bodyBearingCache.set(model.modelId, pending);
    return pending;
  }

  // Fragments knows which items actually produced geometry; bodyless panel
  // containers (decomposed into their skin/core pieces) produce none, so they
  // fall out here without any IFC re-parse or GlobalId bridging.
  private async computeBodyBearingLocalIds(
    model: FRAGS.FragmentsModel,
  ): Promise<Set<number> | null> {
    try {
      const ids = await model.getItemsIdsWithGeometry();
      return new Set(ids);
    } catch (err) {
      console.warn(
        "[IFCViewerEngine] getItemsIdsWithGeometry failed:",
        err,
      );
      return null;
    }
  }

  // Fetch { id: localId, name } for every element of the given entity classes,
  // reusing the Name-attribute extraction pattern from enumerateEquipment.
  private async namedItemsOfClasses(
    model: FRAGS.FragmentsModel,
    classes: string[],
  ): Promise<NamedItem[]> {
    const regexes = classes.map((c) => new RegExp(`^${c}$`, "i"));
    let byCategory: { [category: string]: number[] };
    try {
      byCategory = await model.getItemsOfCategories(regexes);
    } catch (err) {
      console.warn("[IFCViewerEngine] getItemsOfCategories (tree) failed:", err);
      return [];
    }
    const localIds = Object.values(byCategory).flat();
    if (localIds.length === 0) return [];

    let dataList: FRAGS.ItemData[] = [];
    try {
      dataList = await model.getItemsData(localIds, {
        attributes: ["Name"],
        attributesDefault: false,
        relationsDefault: { attributes: false, relations: false },
      });
    } catch (err) {
      console.warn("[IFCViewerEngine] getItemsData (tree) failed:", err);
    }

    const items: NamedItem[] = [];
    for (let i = 0; i < localIds.length; i++) {
      const localId = localIds[i];
      const nameAttr = dataList[i]?.Name as { value?: unknown } | undefined;
      const rawName =
        nameAttr && typeof nameAttr === "object" && "value" in nameAttr
          ? nameAttr.value
          : undefined;
      items.push({
        id: localId,
        name:
          typeof rawName === "string" && rawName.length > 0
            ? rawName
            : `#${localId}`,
      });
    }
    return items;
  }

  // Turn name-based groups into toggle keys + id maps for one model. Keys are
  // "<prefix>:g:<modelId>:<i>" (group) and "<prefix>:m:<modelId>:<localId>"
  // (member) so clearTreePrefix can wipe exactly one category's entries.
  private materializeTreeGroups(
    prefix: string,
    model: FRAGS.FragmentsModel,
    nameGroups: NameGroup[],
  ): TreeGroup[] {
    return nameGroups.map((g, i) => {
      const groupKey = `${prefix}:g:${model.modelId}:${i}`;
      const groupSet = new Set<number>();
      const members: TreeGroupMember[] = g.members.map((m) => {
        groupSet.add(m.id);
        const memberKey = `${prefix}:m:${model.modelId}:${m.id}`;
        this.treeMemberIdMaps.set(memberKey, {
          [model.modelId]: new Set([m.id]),
        });
        return { key: memberKey, label: m.label };
      });
      this.treeGroupIdMaps.set(groupKey, { [model.modelId]: groupSet });
      return { key: groupKey, label: g.label, members };
    });
  }

  private clearTreePrefix(prefix: string): void {
    for (const map of [this.treeGroupIdMaps, this.treeMemberIdMaps]) {
      for (const key of [...map.keys()]) {
        if (key.startsWith(`${prefix}:`)) map.delete(key);
      }
    }
  }

  // ── Camera ────────────────────────────────────────────────────────────────

  fitToFrame(): void {
    const bbox = new THREE.Box3();
    this.fragments.list.forEach((model: FRAGS.FragmentsModel) => {
      if (model.box) bbox.union(model.box);
    });
    if (bbox.isEmpty()) return;

    const center = bbox.getCenter(new THREE.Vector3());
    const size = bbox.getSize(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z);
    const cam = this.world.camera.three;

    let dist: number;
    if (cam instanceof THREE.PerspectiveCamera) {
      const fov = cam.fov * (Math.PI / 180);
      dist = (maxDim / (2 * Math.tan(fov / 2))) * 1.5;
    } else {
      // Orthographic: camera distance doesn't affect what's visible (only
      // zoom/frustum size does), so this value only matters for near/far
      // clipping headroom. Actual framing is the frustum resize below.
      dist = maxDim * 1.5;
    }

    this.world.camera.controls.setLookAt(
      center.x + dist,
      center.y + dist,
      center.z + dist,
      center.x,
      center.y,
      center.z,
    );

    if (cam instanceof THREE.OrthographicCamera) {
      const aspect = (cam.right - cam.left) / (cam.top - cam.bottom);
      const halfHeight = (maxDim / 2) * 1.2; // ~matches the perspective path's 1.5x headroom
      cam.top = halfHeight;
      cam.bottom = -halfHeight;
      cam.left = -halfHeight * aspect;
      cam.right = halfHeight * aspect;
      cam.zoom = 1;
      cam.updateProjectionMatrix();
    }
  }

  resetCamera(): void {
    this.fitToFrame();
  }

  /** Set the canvas background, an `[r, g, b]` triple in 0..1 (as the mesh viewer's setBackground). */
  setBackground(rgb: [number, number, number]): void {
    this.world.scene.config.backgroundColor = new THREE.Color(...rgb);
  }

  getProjectionMode(): "Perspective" | "Orthographic" {
    return this.world.camera.projection.current;
  }

  async toggleProjection(): Promise<void> {
    await this.world.camera.projection.toggle();

    // OrthoPerspectiveCamera swaps `.three` to a genuinely different THREE
    // camera object on toggle (PerspectiveCamera and OrthographicCamera can't
    // be the same instance). Every already-loaded model was handed the old
    // camera object via useCamera() exactly once, back in the
    // fragments.list.onItemSet listener in init() — if we don't re-point it
    // at the new camera here, the Fragments LOD system keeps tracking a
    // detached, no-longer-moving camera and its detail/material resolution
    // stalls wherever it happened to be at toggle time.
    const cam = this.world.camera.three;
    for (const [, model] of this.fragments.list) {
      model.useCamera(cam);
    }

    // Orthographic's frustum isn't scaled to the model until we size it once;
    // re-fit on every toggle so switching in either direction frames correctly
    // rather than showing whatever zoom/frustum the camera last had.
    this.fitToFrame();
  }

  // Right-drag already pans by default (camera-controls' TRUCK action), but
  // that's not discoverable without prior CAD/DCC experience and doesn't
  // work at all without a right mouse button (trackpads, some tablets). This
  // lets the UI offer an explicit Pan mode that remaps left-drag to the same
  // TRUCK action; right-drag keeps panning either way so it's never a
  // regression for people who already knew the gesture.
  setPanMode(active: boolean): void {
    const controls = this.world.camera.controls;
    controls.mouseButtons.left = active
      ? CameraControls.ACTION.TRUCK
      : CameraControls.ACTION.ROTATE;
    controls.mouseButtons.right = CameraControls.ACTION.TRUCK;
  }

  setTopView(): void {
    const controls = this.world.camera.controls;
    const target = controls.getTarget(new THREE.Vector3());
    const dist = controls.distance;
    controls.setLookAt(
      target.x,
      target.y + dist,
      target.z,
      target.x,
      target.y,
      target.z,
      true,
    );
  }

  setFrontView(): void {
    const controls = this.world.camera.controls;
    const target = controls.getTarget(new THREE.Vector3());
    const dist = controls.distance;
    controls.setLookAt(
      target.x,
      target.y,
      target.z + dist,
      target.x,
      target.y,
      target.z,
      true,
    );
  }

  setSideView(): void {
    const controls = this.world.camera.controls;
    const target = controls.getTarget(new THREE.Vector3());
    const dist = controls.distance;
    controls.setLookAt(
      target.x + dist,
      target.y,
      target.z,
      target.x,
      target.y,
      target.z,
      true,
    );
  }

  setIsometricView(): void {
    const controls = this.world.camera.controls;
    const target = controls.getTarget(new THREE.Vector3());
    const dist = controls.distance;
    const off = dist / Math.sqrt(3);
    controls.setLookAt(
      target.x + off,
      target.y + off,
      target.z + off,
      target.x,
      target.y,
      target.z,
      true,
    );
  }

  // ── Lifecycle ─────────────────────────────────────────────────────────────

  resize(): void {
    const el = this.opts.container;
    const w = el.clientWidth;
    const h = el.clientHeight;
    if (!w || !h) return;

    this.world.renderer?.resize(new THREE.Vector2(w, h));

    const cam = this.world.camera.three;
    const aspect = w / h;
    if (cam instanceof THREE.PerspectiveCamera) {
      cam.aspect = aspect;
      cam.updateProjectionMatrix();
    } else if (cam instanceof THREE.OrthographicCamera) {
      const halfHeight = (cam.top - cam.bottom) / 2;
      cam.left = -halfHeight * aspect;
      cam.right = halfHeight * aspect;
      cam.updateProjectionMatrix();
    }
    this.world.update();
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    // Unblock any in-flight loadIfcFromUrl waiting on the reveal gate so it
    // unwinds promptly on unmount instead of sitting out the timeout.
    this.colorPassDeferred?.resolve();
    this.ifcBuffers.clear();
    this.bodyBearingCache.clear();
    try {
      this.components.dispose();
    } catch (e) {
      console.error("[IFCViewerEngine] Dispose error:", e);
    }
  }
}
