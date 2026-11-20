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

import { useEffect, useRef } from "react";
import { GripVertical, Lock } from "lucide-react";
import { SearchInput } from "@/components/ui/SearchInput";
import { SectionLabel } from "@/components/ui/SectionLabel";
import { SKILL_TONE_DOT_CLASSES, type SkillTone } from "@/features/workflows/skillTone";

export interface Skill {
  id: string;
  name: string;
}

export interface SkillGroup {
  id: string;
  /** Group heading, e.g. "Data". Uppercased with CSS. */
  label: string;
  tone: SkillTone;
  skills: Skill[];
}

interface SkillLibraryItemProps {
  name: string;
  tone: SkillTone;
}

/**
 * One skill in the library: its group's dot, its name and a drag handle.
 * Display only until WB-3 makes it draggable onto the canvas.
 */
export function SkillLibraryItem({ name, tone }: SkillLibraryItemProps) {
  return (
    <div className="flex h-8.5 items-center gap-2.5 rounded-md border border-base-content/10 bg-base-100 pr-2 pl-3">
      <span aria-hidden="true" className={`size-1.5 shrink-0 rounded-full ${SKILL_TONE_DOT_CLASSES[tone]}`} />
      <span className="min-w-0 flex-1 truncate text-xs text-base-content" title={name}>
        {name}
      </span>
      <GripVertical size={12} aria-hidden="true" className="shrink-0 text-base-content/40" />
    </div>
  );
}

/**
 * Skill Library column of the Builder (Figma D.2): a search field over the
 * skills, grouped by kind. Display only: search filtering and dragging skills
 * onto the canvas come in later tickets.
 *
 * `locked` is "this run" mode (PPLT-409 D.2a): adding a step changes the
 * template, so a note says so and the library is dimmed and inert, which
 * takes it out of the tab order and the accessibility tree, leaving the note.
 */
export function SkillLibrary({ groups, locked = false }: { groups: SkillGroup[]; locked?: boolean }) {
  // Set on the element: React 18 doesn't know the inert attribute yet.
  const skillsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    skillsRef.current?.toggleAttribute("inert", locked);
  }, [locked]);

  return (
    <div className="flex flex-col gap-4">
      <SectionLabel variant="panel">Skill Library</SectionLabel>
      {locked && (
        <p className="m-0 flex gap-2.5 rounded-md border border-info/40 bg-info/10 p-3 text-[11px] leading-snug text-base-content">
          <Lock aria-hidden="true" size={12} className="mt-0.5 shrink-0 text-base-content/70" />
          Adding, wiring and removing steps changes the template. Switch to "the template" to do that.
        </p>
      )}
      <div ref={skillsRef} className={`flex flex-col gap-4 ${locked ? "opacity-40" : ""}`}>
        <SearchInput placeholder="Search skills..." label="Search skills" />
        {groups.map((group) => (
        <section key={group.id} className="flex flex-col gap-2">
          <SectionLabel variant="panel" as="h3">
            {group.label}
          </SectionLabel>
          <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
            {group.skills.map((skill) => (
              <li key={skill.id}>
                <SkillLibraryItem name={skill.name} tone={group.tone} />
              </li>
            ))}
          </ul>
        </section>
        ))}
      </div>
    </div>
  );
}
