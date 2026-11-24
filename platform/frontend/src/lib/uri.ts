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
 * src/lib/uri.ts
 *
 * Artifact URI resolution for the React frontend.
 *
 * Most artifacts arrive with already-resolved URLs because the Chainlit server
 * resolves deeplynx:// in message_handler.render_artifacts() before sending.
 * However, custom-element viewers can receive raw URIs inside their `props`
 * (the server-side plugin system doesn't always rewrite props-embedded URIs).
 *
 * Use resolveUri() at the edge of any viewer that reads a URI from props.
 */

const FILE_PREFIX = "file://";

export type ResolvedUri =
  { ok: true; url: string } | { ok: false; reason: "unsupported_scheme" | "needs_server_proxy"; uri: string };

/**
 * Resolve an artifact URI to something a <img>/<iframe>/fetch() can use.
 *
 * - http(s):// → passthrough
 * - file://    → not browser-fetchable; treated as unsupported
 * - deeplynx:// → needs server proxy (not implemented); returns failure
 *
 * Future: add a /api/resolve-uri endpoint that the server proxies through
 * uri_resolver.resolve_to_local_path, then update the deeplynx branch here.
 */
export function resolveUri(uri: string | undefined | null): ResolvedUri {
  if (!uri) return { ok: false, reason: "unsupported_scheme", uri: uri ?? "" };

  if (uri.startsWith("http://") || uri.startsWith("https://")) {
    return { ok: true, url: uri };
  }

  if (uri.startsWith("deeplynx://")) {
    console.warn(
      "[uri] deeplynx:// URIs are not yet resolvable client-side; viewer should fall through to a download/link fallback.",
      uri,
    );
    return { ok: false, reason: "needs_server_proxy", uri };
  }

  if (uri.startsWith(FILE_PREFIX)) {
    // file:// is unreachable from the browser. The Chainlit server normally
    // rewrites these to /files/ URLs before send — if we see one here it
    // slipped through a plugin's prop construction.
    return { ok: false, reason: "unsupported_scheme", uri };
  }

  return { ok: false, reason: "unsupported_scheme", uri };
}
