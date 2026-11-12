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

import { useEffect, useRef, useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import type { OidcProvider } from "@/lib/api/types";
import { Button } from "@/components/ui/Button";
import { StatusPill } from "@/components/ui/StatusPill";

const DEFAULT_SCOPES = "openid profile email";

/**
 * Admin > Identity Providers. CRUD for OIDC providers
 * (backend/app/routers/admin_oidc.py) -- client_secret is write-only, never
 * shown back; provider_id is immutable after creation (no field for it in
 * the edit dialog). Same table + native <dialog> pattern as AdminUsers.tsx.
 */
export function AdminOidcProviders() {
  const [providers, setProviders] = useState<OidcProvider[] | null>(null);
  const [error, setError] = useState("");

  const createDialogRef = useRef<HTMLDialogElement>(null);
  const [createProviderId, setCreateProviderId] = useState("");
  const [createDisplayName, setCreateDisplayName] = useState("");
  const [createIssuerUrl, setCreateIssuerUrl] = useState("");
  const [createClientId, setCreateClientId] = useState("");
  const [createClientSecret, setCreateClientSecret] = useState("");
  const [createScopes, setCreateScopes] = useState(DEFAULT_SCOPES);
  const [createDefaultRole, setCreateDefaultRole] = useState("user");
  const [createError, setCreateError] = useState("");
  const [creating, setCreating] = useState(false);

  const editDialogRef = useRef<HTMLDialogElement>(null);
  const [editing, setEditing] = useState<OidcProvider | null>(null);
  const [editDisplayName, setEditDisplayName] = useState("");
  const [editIssuerUrl, setEditIssuerUrl] = useState("");
  const [editClientId, setEditClientId] = useState("");
  const [editClientSecret, setEditClientSecret] = useState("");
  const [editScopes, setEditScopes] = useState(DEFAULT_SCOPES);
  const [editDefaultRole, setEditDefaultRole] = useState("user");
  const [editEnabled, setEditEnabled] = useState(true);
  const [editError, setEditError] = useState("");
  const [saving, setSaving] = useState(false);

  const refresh = () => {
    api
      .listOidcProviders()
      .then((list) => setProviders(list))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load identity providers"));
  };

  useEffect(refresh, []);

  const openCreate = () => {
    setCreateProviderId("");
    setCreateDisplayName("");
    setCreateIssuerUrl("");
    setCreateClientId("");
    setCreateClientSecret("");
    setCreateScopes(DEFAULT_SCOPES);
    setCreateDefaultRole("user");
    setCreateError("");
    createDialogRef.current?.showModal();
  };

  const submitCreate = async () => {
    const missingRequiredField =
      !createProviderId.trim() ||
      !createDisplayName.trim() ||
      !createIssuerUrl.trim() ||
      !createClientId.trim() ||
      !createClientSecret;
    if (missingRequiredField) {
      setCreateError("All fields except scopes are required");
      return;
    }
    setCreating(true);
    setCreateError("");
    try {
      await api.createOidcProvider({
        provider_id: createProviderId,
        display_name: createDisplayName,
        issuer_url: createIssuerUrl,
        client_id: createClientId,
        client_secret: createClientSecret,
        scopes: createScopes,
        default_role: createDefaultRole,
        is_enabled: true,
      });
      createDialogRef.current?.close();
      refresh();
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "Could not create provider");
    } finally {
      setCreating(false);
    }
  };

  const openEdit = (provider: OidcProvider) => {
    setEditing(provider);
    setEditDisplayName(provider.display_name);
    setEditIssuerUrl(provider.issuer_url);
    setEditClientId(provider.client_id);
    setEditClientSecret("");
    setEditScopes(provider.scopes);
    setEditDefaultRole(provider.default_role);
    setEditEnabled(provider.is_enabled);
    setEditError("");
    editDialogRef.current?.showModal();
  };

  const submitEdit = async () => {
    if (!editing) return;
    setSaving(true);
    setEditError("");
    try {
      await api.updateOidcProvider(editing.id, {
        display_name: editDisplayName,
        issuer_url: editIssuerUrl,
        client_id: editClientId,
        scopes: editScopes,
        default_role: editDefaultRole,
        is_enabled: editEnabled,
        ...(editClientSecret ? { client_secret: editClientSecret } : {}),
      });
      editDialogRef.current?.close();
      refresh();
    } catch (err) {
      setEditError(err instanceof ApiError ? err.message : "Could not update provider");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (provider: OidcProvider) => {
    if (!window.confirm(`Delete identity provider "${provider.display_name}"? This cannot be undone.`)) return;
    try {
      await api.deleteOidcProvider(provider.id);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not delete provider");
    }
  };

  return (
    <div className="flex flex-col gap-4 p-4 flex-1 overflow-y-auto">
      <div className="flex items-center justify-between">
        <div>
          <h3>Identity Providers</h3>
          <p className="text-xs text-base-content/50">
            Generic OIDC only. Redirect URI to register with the provider: this backend's{" "}
            <code>/api/auth/callback/&lt;provider_id&gt;</code>.
          </p>
        </div>
        <Button variant="primary" size="sm" icon={<Plus />} label="New provider" onClick={openCreate} />
      </div>

      {error && (
        <div role="alert" className="alert alert-error text-xs">
          {error}
        </div>
      )}

      {providers === null ? (
        <div className="text-sm text-base-content/50">Loading...</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="table table-sm">
            <thead>
              <tr>
                <th>Provider ID</th>
                <th>Display name</th>
                <th>Issuer</th>
                <th>Default role</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {providers.map((provider) => (
                <tr key={provider.id}>
                  <td className="font-mono text-xs">{provider.provider_id}</td>
                  <td>{provider.display_name}</td>
                  <td className="text-base-content/60">{provider.issuer_url}</td>
                  <td>{provider.default_role}</td>
                  <td>
                    <StatusPill
                      label={provider.is_enabled ? "enabled" : "disabled"}
                      tone={provider.is_enabled ? "success" : "neutral"}
                    />
                  </td>
                  <td className="flex gap-1 justify-end">
                    <Button variant="ghost" size="xs" icon={<Pencil />} ariaLabel="Edit provider" onClick={() => openEdit(provider)} />
                    <Button variant="error" soft size="xs" icon={<Trash2 />} ariaLabel="Delete provider" onClick={() => handleDelete(provider)} />
                  </td>
                </tr>
              ))}
              {providers.length === 0 && (
                <tr>
                  <td colSpan={6} className="text-center text-base-content/50">
                    No identity providers configured.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <dialog ref={createDialogRef} className="modal">
        <div className="modal-box max-w-md">
          <h3 className="font-medium mb-3">New identity provider</h3>
          <div className="space-y-3">
            {createError && (
              <div role="alert" className="alert alert-error text-xs">
                {createError}
              </div>
            )}
            <div className="form-control">
              <label className="label pb-1">
                <span className="label-text text-xs uppercase tracking-wider">Provider ID</span>
              </label>
              <input
                className="input input-bordered w-full"
                placeholder="okta"
                value={createProviderId}
                onChange={(e) => setCreateProviderId(e.target.value)}
                autoFocus
              />
              <span className="text-xs text-base-content/40 mt-1">
                Lowercase letters, digits, hyphens. Cannot be changed later.
              </span>
            </div>
            <div className="form-control">
              <label className="label pb-1">
                <span className="label-text text-xs uppercase tracking-wider">Display name</span>
              </label>
              <input
                className="input input-bordered w-full"
                placeholder="Okta"
                value={createDisplayName}
                onChange={(e) => setCreateDisplayName(e.target.value)}
              />
            </div>
            <div className="form-control">
              <label className="label pb-1">
                <span className="label-text text-xs uppercase tracking-wider">Issuer URL</span>
              </label>
              <input
                className="input input-bordered w-full"
                placeholder="https://your-org.okta.com"
                value={createIssuerUrl}
                onChange={(e) => setCreateIssuerUrl(e.target.value)}
              />
            </div>
            <div className="form-control">
              <label className="label pb-1">
                <span className="label-text text-xs uppercase tracking-wider">Client ID</span>
              </label>
              <input
                className="input input-bordered w-full"
                value={createClientId}
                onChange={(e) => setCreateClientId(e.target.value)}
              />
            </div>
            <div className="form-control">
              <label className="label pb-1">
                <span className="label-text text-xs uppercase tracking-wider">Client secret</span>
              </label>
              <input
                className="input input-bordered w-full"
                type="password"
                value={createClientSecret}
                onChange={(e) => setCreateClientSecret(e.target.value)}
              />
            </div>
            <div className="form-control">
              <label className="label pb-1">
                <span className="label-text text-xs uppercase tracking-wider">Scopes</span>
              </label>
              <input
                className="input input-bordered w-full"
                value={createScopes}
                onChange={(e) => setCreateScopes(e.target.value)}
              />
            </div>
            <div className="form-control">
              <label className="label pb-1">
                <span className="label-text text-xs uppercase tracking-wider">Default role for new accounts</span>
              </label>
              <select
                className="select select-bordered w-full"
                value={createDefaultRole}
                onChange={(e) => setCreateDefaultRole(e.target.value)}
              >
                <option value="user">user</option>
                <option value="admin">admin</option>
              </select>
            </div>
          </div>
          <div className="modal-action">
            <form method="dialog">
              <Button variant="ghost" size="sm" type="submit" label="Cancel" />
            </form>
            <Button variant="primary" size="sm" type="submit" label={creating ? "Creating..." : "Create"} loading={creating} onClick={submitCreate} />
          </div>
        </div>
        <form method="dialog" className="modal-backdrop">
          <button>close</button>
        </form>
      </dialog>

      <dialog ref={editDialogRef} className="modal">
        <div className="modal-box max-w-md">
          <h3 className="font-medium mb-3">Edit {editing?.display_name}</h3>
          <div className="space-y-3">
            {editError && (
              <div role="alert" className="alert alert-error text-xs">
                {editError}
              </div>
            )}
            <div className="form-control">
              <label className="label pb-1">
                <span className="label-text text-xs uppercase tracking-wider">Display name</span>
              </label>
              <input
                className="input input-bordered w-full"
                value={editDisplayName}
                onChange={(e) => setEditDisplayName(e.target.value)}
              />
            </div>
            <div className="form-control">
              <label className="label pb-1">
                <span className="label-text text-xs uppercase tracking-wider">Issuer URL</span>
              </label>
              <input
                className="input input-bordered w-full"
                value={editIssuerUrl}
                onChange={(e) => setEditIssuerUrl(e.target.value)}
              />
            </div>
            <div className="form-control">
              <label className="label pb-1">
                <span className="label-text text-xs uppercase tracking-wider">Client ID</span>
              </label>
              <input
                className="input input-bordered w-full"
                value={editClientId}
                onChange={(e) => setEditClientId(e.target.value)}
              />
            </div>
            <div className="form-control">
              <label className="label pb-1">
                <span className="label-text text-xs uppercase tracking-wider">New client secret (optional)</span>
              </label>
              <input
                className="input input-bordered w-full"
                type="password"
                placeholder="Leave blank to keep current secret"
                value={editClientSecret}
                onChange={(e) => setEditClientSecret(e.target.value)}
              />
            </div>
            <div className="form-control">
              <label className="label pb-1">
                <span className="label-text text-xs uppercase tracking-wider">Scopes</span>
              </label>
              <input
                className="input input-bordered w-full"
                value={editScopes}
                onChange={(e) => setEditScopes(e.target.value)}
              />
            </div>
            <div className="form-control">
              <label className="label pb-1">
                <span className="label-text text-xs uppercase tracking-wider">Default role for new accounts</span>
              </label>
              <select
                className="select select-bordered w-full"
                value={editDefaultRole}
                onChange={(e) => setEditDefaultRole(e.target.value)}
              >
                <option value="user">user</option>
                <option value="admin">admin</option>
              </select>
            </div>
            <div className="form-control">
              <label className="label cursor-pointer justify-start gap-2">
                <input
                  type="checkbox"
                  className="checkbox checkbox-sm"
                  checked={editEnabled}
                  onChange={(e) => setEditEnabled(e.target.checked)}
                />
                <span className="label-text text-xs uppercase tracking-wider">Enabled</span>
              </label>
            </div>
          </div>
          <div className="modal-action">
            <form method="dialog">
              <Button variant="ghost" size="sm" type="submit" label="Cancel" />
            </form>
            <Button variant="primary" size="sm" type="submit" label={saving ? "Saving..." : "Save"} loading={saving} onClick={submitEdit} />
          </div>
        </div>
        <form method="dialog" className="modal-backdrop">
          <button>close</button>
        </form>
      </dialog>
    </div>
  );
}
