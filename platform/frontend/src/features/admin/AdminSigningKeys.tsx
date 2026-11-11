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

import { useEffect, useState } from "react";
import { Check, Copy, Plus } from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import type { SigningKey } from "@/lib/api/types";
import { Button } from "@/components/ui/Button";
import { StatusPill, type StatusPillTone } from "@/components/ui/StatusPill";

/** An inactive key is waiting to be activated, so it warns; a retired key is done. */
const KEY_STATUS_TONE: Record<"active" | "inactive" | "retired", StatusPillTone> = {
  active: "success",
  inactive: "warning",
  retired: "neutral",
};

/**
 * Admin > Signing Keys. Generate/activate/retire RS256 keys for the identity
 * plane (app/identity.py::mint_for_user() -- see backend/app/routers/admin_keys.py).
 * No modal needed here (unlike AdminUsers) -- generate takes no input, and
 * activate/retire are one-click actions on an existing row.
 */
export function AdminSigningKeys() {
  const [keys, setKeys] = useState<SigningKey[] | null>(null);
  const [error, setError] = useState("");
  const [generating, setGenerating] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const refresh = () => {
    api
      .listSigningKeys()
      .then((list) => setKeys(list))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load signing keys"));
  };

  useEffect(refresh, []);

  const handleGenerate = async () => {
    setGenerating(true);
    setError("");
    try {
      await api.generateSigningKey();
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not generate key");
    } finally {
      setGenerating(false);
    }
  };

  const handleActivate = async (key: SigningKey) => {
    setBusyId(key.id);
    setError("");
    try {
      await api.activateSigningKey(key.id);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not activate key");
    } finally {
      setBusyId(null);
    }
  };

  const handleRetire = async (key: SigningKey) => {
    setBusyId(key.id);
    setError("");
    try {
      await api.retireSigningKey(key.id);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not retire key");
    } finally {
      setBusyId(null);
    }
  };

  const handleCopy = async (key: SigningKey) => {
    try {
      await navigator.clipboard.writeText(key.public_key_pem);
      setCopiedId(key.id);
      setTimeout(() => setCopiedId((id) => (id === key.id ? null : id)), 1500);
    } catch {
      /* clipboard access denied -- not worth surfacing as an error banner */
    }
  };

  return (
    <div className="flex flex-col gap-4 p-4 flex-1 overflow-y-auto">
      <div className="flex items-center justify-between">
        <div>
          <h3>Signing Keys</h3>
          <p className="text-xs text-base-content/50">
            Point every agent's <code>JWKS_URL</code> at this backend's{" "}
            <code>/.well-known/jwks.json</code> instead of distributing a public key by hand.
          </p>
        </div>
        <Button variant="primary" size="sm" icon={<Plus />} label={generating ? "Generating..." : "Generate key"} loading={generating} onClick={handleGenerate} />
      </div>

      {error && (
        <div role="alert" className="alert alert-error text-xs">
          {error}
        </div>
      )}

      {keys === null ? (
        <div className="text-sm text-base-content/50">Loading...</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="table table-sm">
            <thead>
              <tr>
                <th>Key ID</th>
                <th>Status</th>
                <th>Created</th>
                <th>Retired</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {keys.map((key) => {
                const status: keyof typeof KEY_STATUS_TONE = key.retired_at
                  ? "retired"
                  : key.is_active
                    ? "active"
                    : "inactive";
                return (
                  <tr key={key.id}>
                    <td className="font-mono text-xs">{key.kid}</td>
                    <td>
                      <StatusPill label={status} tone={KEY_STATUS_TONE[status]} />
                    </td>
                    <td className="text-base-content/60">{new Date(key.created_at).toLocaleString()}</td>
                    <td className="text-base-content/60">
                      {key.retired_at ? new Date(key.retired_at).toLocaleString() : "—"}
                    </td>
                    <td className="flex gap-1 justify-end">
                      <Button variant="ghost" size="xs" icon={copiedId === key.id ? <Check /> : <Copy />} ariaLabel="Copy public key" onClick={() => handleCopy(key)} />
                      {!key.is_active && !key.retired_at && (
                        <Button variant="ghost" size="xs" label="Activate" disabled={busyId === key.id} onClick={() => handleActivate(key)} />
                      )}
                      {!key.retired_at && (
                        <Button variant="error" soft size="xs" label="Retire" disabled={busyId === key.id} onClick={() => handleRetire(key)} />
                      )}
                    </td>
                  </tr>
                );
              })}
              {keys.length === 0 && (
                <tr>
                  <td colSpan={5} className="text-center text-base-content/50">
                    No signing keys yet -- generate one, then activate it.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
