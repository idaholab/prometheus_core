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

import { Search } from "lucide-react";

type Props = {
  placeholder: string;
  label: string;
} & (
  | {
      /** Controlled: shows value and reports every change through onChange. */
      value: string;
      onChange: (value: string) => void;
    }
  | { value?: undefined; onChange?: (value: string) => void }
);

/** Search field with an icon. Props only; pass value and onChange to control it. */
export function SearchInput({ placeholder, label, value, onChange }: Props) {
  return (
    <label className="input input-sm w-full">
      <Search size={14} aria-hidden="true" className="text-base-content/50" />
      <input
        type="search"
        className="grow"
        placeholder={placeholder}
        aria-label={label}
        value={value}
        onChange={onChange ? (event) => onChange(event.target.value) : undefined}
      />
    </label>
  );
}
