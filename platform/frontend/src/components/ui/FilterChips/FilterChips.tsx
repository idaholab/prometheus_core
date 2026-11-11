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

type Chip = {
  id: string;
  label: string;
};

type Props = {
  chips: Chip[];
  selected: string;
  label: string;
  onSelect?: (id: string) => void;
};

/** Row of filter chips; props only, selected decides the active chip and onSelect reports a click. */
export function FilterChips({ chips, selected, label, onSelect }: Props) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-2">
      {chips.map((chip) => {
        const isSelected = chip.id === selected;
        return (
          <button
            key={chip.id}
            type="button"
            aria-pressed={isSelected}
            onClick={onSelect ? () => onSelect(chip.id) : undefined}
            className={`btn btn-sm rounded-full ${isSelected ? "btn-ghost border border-primary bg-primary/20 text-base-content font-bold" : "btn-ghost border border-base-300"}`}
          >
            {chip.label}
          </button>
        );
      })}
    </div>
  );
}
