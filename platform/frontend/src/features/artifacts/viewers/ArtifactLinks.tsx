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
 * src/viewers/ArtifactLinks.tsx
 *
 * Buttons a producing agent attached to its artifact (`ArtifactMeta.links`, from
 * the artifact's `metadata.links`). Either an absolute http(s) URL (e.g. the job
 * that produced it) or, for a page the agent serves itself, the platform's own
 * `/api/artifacts/{id}/links/{n}`, which proxies that page so it opens wherever
 * the agent runs. The backend has already validated both; this re-checks before
 * rendering and always opens a new tab with no opener. Any viewer can drop it into
 * its header.
 */

import { ExternalLink } from "lucide-react";
import type { ArtifactLink } from "@/lib/api/types";

const isWebUrl = (url: string) => /^https?:\/\//i.test(url);
/** A link the platform proxies to the agent's page (same origin). */
const isAgentPage = (url: string) => /^\/api\/artifacts\/[^/]+\/links\/\d+$/.test(url);

export function ArtifactLinks({ links }: { links?: ArtifactLink[] }) {
  const shown = (links ?? []).filter((l) => l.label && (isWebUrl(l.url) || isAgentPage(l.url)));
  if (shown.length === 0) return null;
  return (
    <>
      {shown.map((link) => (
        <a
          key={link.url}
          href={link.url}
          target="_blank"
          rel="noopener noreferrer"
          className="btn btn-ghost btn-xs"
          aria-label={`${link.label} (opens in a new tab)`}
        >
          <ExternalLink size={13} />
          {link.label}
        </a>
      ))}
    </>
  );
}

export default ArtifactLinks;
