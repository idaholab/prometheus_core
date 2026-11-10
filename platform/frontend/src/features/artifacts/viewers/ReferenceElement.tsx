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

/**
 * src/viewers/ReferenceElement.tsx
 *
 * Renders a `reference` artifact (render_hint === "reference") as a citation card.
 * Replaces the old Chainlit `_render_reference_artifact` inline citation markdown
 * (frontend/components/message_handler.py). The adapter (artifactAdapter.ts) feeds
 * it the typed `citation` ({source, section, page}) plus name/description/uri from
 * `ArtifactMeta`.
 */

import { BookMarked, ExternalLink } from "lucide-react";
import type { ViewerProps } from "@/features/artifacts/elements";
import type { Citation } from "@/lib/api/types";

interface ReferenceProps {
  citation?: Citation | null;
  uri?: string | null;
  name?: string;
  description?: string;
}

export function ReferenceElement({ element }: ViewerProps) {
  const { citation, uri, name, description } = (element.props ?? {}) as ReferenceProps;
  const title = name || element.name || "Reference";

  // "ASME BPVC · II-D · p. 42" — only the parts that are present.
  const parts = [
    citation?.source,
    citation?.section,
    citation?.page ? `p. ${citation.page}` : undefined,
  ].filter((p): p is string => Boolean(p && p.trim()));

  return (
    <div className="flex gap-3 bg-base-200 border border-base-300 rounded-lg px-3 py-2.5 my-2 max-w-2xl">
      <BookMarked size={15} className="text-base-content/50 mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1">
        {uri ? (
          <a
            href={uri}
            target="_blank"
            rel="noreferrer"
            className="text-sm font-medium text-primary underline inline-flex items-center gap-1 break-words"
          >
            {title}
            <ExternalLink size={12} className="shrink-0" />
          </a>
        ) : (
          <p className="text-sm font-medium text-base-content break-words">{title}</p>
        )}
        {description && (
          <p className="text-sm text-base-content/70 mt-0.5 break-words">{description}</p>
        )}
        {parts.length > 0 && (
          <p className="text-xs text-base-content/50 mt-1">{parts.join(" · ")}</p>
        )}
      </div>
    </div>
  );
}

export default ReferenceElement;
