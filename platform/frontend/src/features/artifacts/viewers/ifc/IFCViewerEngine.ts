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
import * as THREE from "three";
import * as WEBIFC from "web-ifc";

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
export type PipeRunItem = { key: string; label: string; members: PipeMemberItem[] };

// IFC entity types that count as "pipe" elements.
const PIPE_MEMBER_IFC_CLASSES = ["IfcPipeSegment", "IfcPipeFitting"];

// IFC entity types that represent a "piece of equipment" — concrete classes plus
// the abstract flow-element bases so we catch elements that weren't given a
// concrete subtype during authoring.
const EQUIPMENT_IFC_CLASSES = [
  "IfcPump", "IfcValve", "IfcTank", "IfcFan", "IfcChiller", "IfcCompressor",
  "IfcBoiler", "IfcCoolingTower", "IfcHeatExchanger", "IfcEvaporator",
  "IfcCondenser", "IfcFilter", "IfcMotor", "IfcTransformer",
  "IfcAirTerminal", "IfcAirTerminalBox", "IfcSanitaryTerminal", "IfcFlowMeter",
  "IfcUnitaryEquipment", "IfcDistributionChamberElement",
  "IfcFlowTerminal", "IfcFlowStorageDevice", "IfcFlowMovingDevice",
  "IfcFlowTreatmentDevice", "IfcEnergyConversionDevice",
];

// Categories matched by IFC entity type. This is the full catalog the engine
// understands — products decide which subset to expose as toggles; presence
// on a given model is resolved at runtime via enumerateCategories().
const CATEGORY_IFC_CLASSES: Record<string, string[]> = {
  walls:     ["IfcWall", "IfcWallStandardCase"],
  floors:    ["IfcSlab"],
  columns:   ["IfcColumn"],
  beams:     ["IfcBeam"],
  doors:     ["IfcDoor"],
  windows:   ["IfcWindow"],
  pipes:     ["IfcPipeSegment", "IfcPipeFitting"],
  equipment: ["IfcFlowTerminal", "IfcFlowStorageDevice", "IfcFlowMovingDevice"],
  // Catches IfcRoof entities (e.g. reactor containment domes) in addition to
  // the name-pattern path that handles IfcSlab "Roof Slab" elements below.
  roofs:     ["IfcRoof"],
};

// Categories matched by IFC Name attribute regex instead of entity type.
// value: regex tested against Name; categories: optional entity-type filter.
const CATEGORY_NAME_PATTERNS: Record<string, { pattern: RegExp; categories?: RegExp[] }> = {
  roofs: {
    pattern:    /^Roof Slab$/i,
    categories: [/^IfcSlab$/i],
  },
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
  private world: OBC.SimpleWorld<OBC.SimpleScene, OBC.SimpleCamera, OBC.SimpleRenderer>;
  private fragments: OBC.FragmentsManager;
  private hider: OBC.Hider;
  private disposed = false;
  private equipmentIdMaps  = new Map<string, OBC.ModelIdMap>();
  private pipeRunIdMaps    = new Map<string, OBC.ModelIdMap>(); // whole-run toggle
  private pipeMemberIdMaps = new Map<string, OBC.ModelIdMap>(); // single-segment toggle
  private ifcBuffers       = new Map<string, Uint8Array>();     // raw bytes per modelId, for pipe-run grouping

  constructor(private opts: ViewerOptions) {
    this.components = new OBC.Components();

    const worlds = this.components.get(OBC.Worlds);
    this.world = worlds.create <
      OBC.SimpleScene,
      OBC.SimpleCamera,
      OBC.SimpleRenderer
    >();

    this.world.scene = new OBC.SimpleScene(this.components);
    this.world.scene.setup();

    // Keep ambient low so the directional creates real surface definition
    this.world.scene.config.directionalLight.intensity = 2.5;
    this.world.scene.config.ambientLight.intensity = 0.6;

    // Fill light from the opposite side so back faces aren't pitch black
    const fill = new THREE.DirectionalLight(0xffffff, 1.2);
    fill.position.set(-5, 8, -3);
    this.world.scene.three.add(fill);

    this.world.renderer = new OBC.SimpleRenderer(this.components, opts.container);
    this.world.camera = new OBC.SimpleCamera(this.components);

    this.components.init();

    this.fragments = this.components.get(OBC.FragmentsManager);
    this.hider     = this.components.get(OBC.Hider);
  }

  // ── Init ──────────────────────────────────────────────────────────────────

  async init(): Promise<void> {
    const workerUrl = await OBC.FragmentsManager.getWorker();
    this.fragments.init(workerUrl);

    this.world.camera.controls.addEventListener("update", () => {
      this.fragments.core.update();
    });

    this.fragments.core.models.materials.list.onItemSet.add(({ value: material }: { value: THREE.Material }) => {
      if (!("isLodMaterial" in material && material.isLodMaterial)) {
        material.polygonOffset = true;
        material.polygonOffsetUnits = 1;
        material.polygonOffsetFactor = Math.random();
      }
    });

    this.fragments.list.onItemSet.add(({ value: model }: { value: FRAGS.FragmentsModel }) => {
      model.useCamera(this.world.camera.three);
      this.world.scene.three.add(model.object);
      this.fragments.core.update(true);
    });
  }

  // ── Load ──────────────────────────────────────────────────────────────────

  async loadIfcFromUrl(
    url: string,
    onProgress?: (p: LoadProgress) => void,
  ): Promise<void> {
    const ifcLoader = this.components.get(OBC.IfcLoader);

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

    onProgress?.({ stage: "downloading", progress: 0, message: "Downloading IFC file…" });

    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`IFC fetch failed: ${resp.status}`);
    const buffer = new Uint8Array(await resp.arrayBuffer());
    this.ifcBuffers.set("model", buffer);

    onProgress?.({ stage: "parsing", progress: 0, message: "Processing geometry…" });

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

    onProgress?.({ stage: "rendering", progress: 100, message: "Complete!" });

    this.fitToFrame();
  }

  // ── Visibility ────────────────────────────────────────────────────────────

  async setCategoryVisible(category: string, visible: boolean): Promise<void> {
    if (category in CATEGORY_NAME_PATTERNS) {
      const { pattern, categories } = CATEGORY_NAME_PATTERNS[category];
      await this.setCategoryVisibleByName(pattern, visible, categories);
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
        console.warn(`[IFCViewerEngine] getItemsOfCategories failed for "${category}":`, err);
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
    const queryKey = `__name_${namePattern.source}_${categories?.map(r => r.source).join("_") ?? ""}`;

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
      console.warn(`[IFCViewerEngine] ItemsFinder query failed for pattern "${namePattern}":`, err);
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
    if (category in CATEGORY_NAME_PATTERNS) {
      const { pattern, categories } = CATEGORY_NAME_PATTERNS[category];
      if (await this.nameQueryHasItems(pattern, categories)) return true;
    }

    const classes = CATEGORY_IFC_CLASSES[category];
    if (!classes) return false;

    const regexes = classes.map((c) => new RegExp(`^${c}$`, "i"));
    for (const [, model] of this.fragments.list) {
      try {
        const items = await model.getItemsOfCategories(regexes);
        if (Object.values(items).flat().length > 0) return true;
      } catch (err) {
        console.warn(`[IFCViewerEngine] getItemsOfCategories failed for "${category}":`, err);
      }
    }
    return false;
  }

  private async nameQueryHasItems(namePattern: RegExp, categories?: RegExp[]): Promise<boolean> {
    const finder = this.components.get(OBC.ItemsFinder);
    const queryKey = `__name_${namePattern.source}_${categories?.map(r => r.source).join("_") ?? ""}`;

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
      return Object.values(modelIdMap).some((ids) => (ids as Set<number>).size > 0);
    } catch (err) {
      console.warn(`[IFCViewerEngine] ItemsFinder query failed for pattern "${namePattern}":`, err);
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
        const rawName = nameAttr && typeof nameAttr === "object" && "value" in nameAttr
          ? nameAttr.value
          : undefined;
        const label = (typeof rawName === "string" && rawName.length > 0)
          ? rawName
          : `#${localId}`;
        const key = `${model.modelId}:${localId}`;
        this.equipmentIdMaps.set(key, { [model.modelId]: new Set([localId]) });
        items.push({ key, label });
      }
    }

    items.sort((a, b) => a.label.localeCompare(b.label, undefined, { numeric: true }));
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

  private async computePipeRunGlobalIdGroups(buffer: Uint8Array): Promise<Set<string>[]> {
    const ifcApi = new WEBIFC.IfcAPI();
    ifcApi.SetWasmPath(this.opts.wasmCdnPath ?? "https://unpkg.com/web-ifc@0.0.77/", true);
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
        const type = (WEBIFC as unknown as Record<string, number>)[className.toUpperCase()];
        for (const id of getIds(type)) equipmentIds.add(id);
      }

      const portToParent = new Map<number, number>();
      for (const relId of getIds(WEBIFC.IFCRELNESTS)) {
        const rel = getLine(relId);
        const parent = (rel.RelatingObject as { value?: number } | undefined)?.value;
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
        const globalIdAttr = getLine(id).GlobalId as { value?: string } | undefined;
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
        try { ifcApi.CloseModel(modelID); } catch { /* ignore */ }
      }
    }
  }

  async enumeratePipeRuns(): Promise<PipeRunItem[]> {
    this.pipeRunIdMaps.clear();
    this.pipeMemberIdMaps.clear();
    const runs: PipeRunItem[] = [];

    for (const [, model] of this.fragments.list) {
      const pipeRegexes = PIPE_MEMBER_IFC_CLASSES.map((c) => new RegExp(`^${c}$`, "i"));

      let pipeByCategory: { [category: string]: number[] };
      try {
        pipeByCategory = await model.getItemsOfCategories(pipeRegexes);
      } catch (err) {
        console.warn("[IFCViewerEngine] getItemsOfCategories(pipe runs) failed:", err);
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
        const rawName = nameAttr && typeof nameAttr === "object" && "value" in nameAttr
          ? nameAttr.value
          : undefined;
        nameByLocalId.set(
          localId,
          typeof rawName === "string" && rawName.length > 0 ? rawName : `#${localId}`,
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
          "if the model was loaded via loadIfcFromUrl()."
        );
      } else {
        try {
          globalIdGroups = await this.computePipeRunGlobalIdGroups(buffer);
        } catch (err) {
          console.warn("[IFCViewerEngine] computePipeRunGlobalIdGroups failed:", err);
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
          this.pipeMemberIdMaps.set(memberKey, { [model.modelId]: new Set([localId]) });
          memberItems.push({ key: memberKey, label: nameByLocalId.get(localId) ?? `#${localId}` });
        }

        memberItems.sort((a, b) => a.label.localeCompare(b.label, undefined, { numeric: true }));
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
        this.pipeMemberIdMaps.set(memberKey, { [model.modelId]: new Set([localId]) });
        this.pipeRunIdMaps.set(runKey, { [model.modelId]: new Set([localId]) });
        runs.push({
          key: runKey,
          label: `Pipe run ${runIndex} (1 segments)`,
          members: [{ key: memberKey, label: nameByLocalId.get(localId) ?? `#${localId}` }],
        });
      }
      console.debug(
        `[IFCViewerEngine] model "${model.modelId}": ${runIndex} pipe run(s) ` +
        `(${fallbackCount} ungrouped fallback${fallbackCount === 1 ? "" : "s"} out of ${pipeIds.length} pipe elements)`
      );
    }

    runs.sort((a, b) => a.label.localeCompare(b.label, undefined, { numeric: true }));
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

  // ── Camera ────────────────────────────────────────────────────────────────

  fitToFrame(): void {
    const bbox = new THREE.Box3();
    this.fragments.list.forEach((model: FRAGS.FragmentsModel) => {
      if (model.box) bbox.union(model.box);
    });
    if (bbox.isEmpty()) return;

    const center = bbox.getCenter(new THREE.Vector3());
    const size   = bbox.getSize(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z);
    const cam    = this.world.camera.three as THREE.PerspectiveCamera;
    const fov    = cam.fov * (Math.PI / 180);
    const dist   = (maxDim / (2 * Math.tan(fov / 2))) * 1.5;

    this.world.camera.controls.setLookAt(
      center.x + dist, center.y + dist, center.z + dist,
      center.x, center.y, center.z,
    );
  }

  resetCamera(): void { this.fitToFrame(); }

  setTopView(): void {
    const controls = this.world.camera.controls;
    const target   = controls.getTarget(new THREE.Vector3());
    const dist     = controls.distance;
    controls.setLookAt(target.x, target.y + dist, target.z, target.x, target.y, target.z, true);
  }

  setFrontView(): void {
    const controls = this.world.camera.controls;
    const target   = controls.getTarget(new THREE.Vector3());
    const dist     = controls.distance;
    controls.setLookAt(target.x, target.y, target.z + dist, target.x, target.y, target.z, true);
  }

  setSideView(): void {
    const controls = this.world.camera.controls;
    const target   = controls.getTarget(new THREE.Vector3());
    const dist     = controls.distance;
    controls.setLookAt(target.x + dist, target.y, target.z, target.x, target.y, target.z, true);
  }

  setIsometricView(): void {
    const controls = this.world.camera.controls;
    const target   = controls.getTarget(new THREE.Vector3());
    const dist     = controls.distance;
    const off      = dist / Math.sqrt(3);
    controls.setLookAt(
      target.x + off, target.y + off, target.z + off,
      target.x, target.y, target.z,
      true,
    );
  }

  // ── Lifecycle ─────────────────────────────────────────────────────────────

  resize(): void {
    const el = this.opts.container;
    const w  = el.clientWidth;
    const h  = el.clientHeight;
    if (!w || !h) return;

    this.world.renderer?.resize(new THREE.Vector2(w, h));
    const cam = this.world.camera.three as THREE.PerspectiveCamera;
    cam.aspect = w / h;
    cam.updateProjectionMatrix();
    this.world.update();
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.ifcBuffers.clear();
    try {
      this.components.dispose();
    } catch (e) {
      console.error("[IFCViewerEngine] Dispose error:", e);
    }
  }
}
