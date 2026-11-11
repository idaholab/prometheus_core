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

import { useState } from "react";
import type { ViewerProps } from "@/features/artifacts/elements";

interface FollowUpSuggestionsProps {
  suggestions?: string[];
  title?: string;
}

export function FollowUpSuggestionsElement({ element, onSend }: ViewerProps) {
  const props = ((element as { props?: FollowUpSuggestionsProps }).props) ?? {};
  const suggestions = props.suggestions ?? [];
  const title = props.title ?? "What would you like to do next?";

  const [used, setUsed] = useState(false);

  if (!suggestions.length) return null;

  const handleClick = (suggestion: string) => {
    if (used || !onSend) return;
    setUsed(true);
    onSend(suggestion);
  };

  return (
    <div className="border border-base-300 rounded-lg p-4 my-2 bg-base-200/40 space-y-2 max-w-xl">
      <div className="text-sm font-medium text-base-content/80">{title}</div>
      <div className="flex flex-col gap-2">
        {suggestions.map((s, i) => (
          <button
            key={i}
            className="btn btn-sm btn-outline justify-start text-left normal-case"
            onClick={() => handleClick(s)}
            disabled={used}
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
