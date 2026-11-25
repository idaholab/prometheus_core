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

import { useRef, useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import type { OidcProvider } from "@/lib/api/types";
import { Button } from "@/components/ui/Button";
import { StatusPill } from "@/components/ui/StatusPill";
import {
  errorMessage,
  useCreateOidcProviderMutation,
  useDeleteOidcProviderMutation,
  useListOidcProvidersQuery,
  useUpdateOidcProviderMutation,
  LIST_MAX_AGE_SECONDS,
} from "./adminApi";

const DEFAULT_SCOPES = "openid profile email";

/**
 * Admin > Identity Providers. CRUD for OIDC providers
 * (backend/app/routers/admin_oidc.py) -- client_secret is write-only, never
 * shown back; provider_id is immutable after creation (no field for it in
 * the edit dialog). Same table + native <dialog> pattern as AdminUsers.tsx.
 *
 * Server data comes from RTK Query (adminApi.ts); a create, edit or delete
 * invalidates the list, so it refetches.
 */
export function AdminOidcProviders() {
  const list = useListOidcProvidersQuery(undefined, { refetchOnMountOrArgChange: LIST_MAX_AGE_SECONDS });
  // A failed load shows its error in place of the table, never rows from before
  // it. RTK keeps the error while the list refetches, so it stays up until a load succeeds
  const loadError = list.error ? errorMessage(list.error, "Could not load identity providers") : "";
  const providers = list.error ? null : (list.data ?? null);
  const [createProvider] = useCreateOidcProviderMutation();
  const [updateProvider] = useUpdateOidcProviderMutation();
  const [deleteProvider] = useDeleteOidcProviderMutation();
  const [deleteError, setDeleteError] = useState("");

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
      await createProvider({
        provider_id: createProviderId,
        display_name: createDisplayName,
        issuer_url: createIssuerUrl,
        client_id: createClientId,
        client_secret: createClientSecret,
        scopes: createScopes,
        default_role: createDefaultRole,
        is_enabled: true,
      }).unwrap();
      createDialogRef.current?.close();
    } catch (err) {
      setCreateError(errorMessage(err, "Could not create provider"));
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
      await updateProvider({
        id: editing.id,
        patch: {
          display_name: editDisplayName,
          issuer_url: editIssuerUrl,
          client_id: editClientId,
          scopes: editScopes,
          default_role: editDefaultRole,
          is_enabled: editEnabled,
          ...(editClientSecret ? { client_secret: editClientSecret } : {}),
        },
      }).unwrap();
      editDialogRef.current?.close();
    } catch (err) {
      setEditError(errorMessage(err, "Could not update provider"));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (provider: OidcProvider) => {
    if (!window.confirm(`Delete identity provider "${provider.display_name}"? This cannot be undone.`))
      return;
    setDeleteError("");
    try {
      await deleteProvider(provider.id).unwrap();
    } catch (err) {
      setDeleteError(errorMessage(err, "Could not delete provider"));
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

      {deleteError && (
        <div role="alert" className="alert alert-error text-xs">
          {deleteError}
        </div>
      )}

      {loadError ? (
        <div role="alert" className="alert alert-error text-xs">
          {loadError}
        </div>
      ) : providers === null ? (
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
                    <Button
                      variant="ghost"
                      size="xs"
                      icon={<Pencil />}
                      ariaLabel={`Edit ${provider.display_name}`}
                      onClick={() => openEdit(provider)}
                    />
                    <Button
                      variant="error"
                      soft
                      size="xs"
                      icon={<Trash2 />}
                      ariaLabel={`Delete ${provider.display_name}`}
                      onClick={() => handleDelete(provider)}
                    />
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

      <dialog ref={createDialogRef} className="modal" aria-labelledby="oidc-create-title">
        <div className="modal-box max-w-md">
          <h3 id="oidc-create-title" className="font-medium mb-3">
            New identity provider
          </h3>
          <div className="space-y-3">
            {createError && (
              <div role="alert" className="alert alert-error text-xs">
                {createError}
              </div>
            )}
            <div className="form-control">
              <label className="label pb-1" htmlFor="oidc-create-provider-id">
                <span className="label-text text-xs uppercase tracking-wider">Provider ID</span>
              </label>
              <input
                id="oidc-create-provider-id"
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
              <label className="label pb-1" htmlFor="oidc-create-display-name">
                <span className="label-text text-xs uppercase tracking-wider">Display name</span>
              </label>
              <input
                id="oidc-create-display-name"
                className="input input-bordered w-full"
                placeholder="Okta"
                value={createDisplayName}
                onChange={(e) => setCreateDisplayName(e.target.value)}
              />
            </div>
            <div className="form-control">
              <label className="label pb-1" htmlFor="oidc-create-issuer-url">
                <span className="label-text text-xs uppercase tracking-wider">Issuer URL</span>
              </label>
              <input
                id="oidc-create-issuer-url"
                className="input input-bordered w-full"
                placeholder="https://your-org.okta.com"
                value={createIssuerUrl}
                onChange={(e) => setCreateIssuerUrl(e.target.value)}
              />
            </div>
            <div className="form-control">
              <label className="label pb-1" htmlFor="oidc-create-client-id">
                <span className="label-text text-xs uppercase tracking-wider">Client ID</span>
              </label>
              <input
                id="oidc-create-client-id"
                className="input input-bordered w-full"
                value={createClientId}
                onChange={(e) => setCreateClientId(e.target.value)}
              />
            </div>
            <div className="form-control">
              <label className="label pb-1" htmlFor="oidc-create-client-secret">
                <span className="label-text text-xs uppercase tracking-wider">Client secret</span>
              </label>
              <input
                id="oidc-create-client-secret"
                className="input input-bordered w-full"
                type="password"
                value={createClientSecret}
                onChange={(e) => setCreateClientSecret(e.target.value)}
              />
            </div>
            <div className="form-control">
              <label className="label pb-1" htmlFor="oidc-create-scopes">
                <span className="label-text text-xs uppercase tracking-wider">Scopes</span>
              </label>
              <input
                id="oidc-create-scopes"
                className="input input-bordered w-full"
                value={createScopes}
                onChange={(e) => setCreateScopes(e.target.value)}
              />
            </div>
            <div className="form-control">
              <label className="label pb-1" htmlFor="oidc-create-default-role">
                <span className="label-text text-xs uppercase tracking-wider">
                  Default role for new accounts
                </span>
              </label>
              <select
                id="oidc-create-default-role"
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
            <Button
              variant="primary"
              size="sm"
              type="submit"
              label={creating ? "Creating..." : "Create"}
              loading={creating}
              onClick={submitCreate}
            />
          </div>
        </div>
        <form method="dialog" className="modal-backdrop">
          <button>close</button>
        </form>
      </dialog>

      <dialog ref={editDialogRef} className="modal" aria-labelledby="oidc-edit-title">
        <div className="modal-box max-w-md">
          <h3 id="oidc-edit-title" className="font-medium mb-3">
            Edit {editing?.display_name}
          </h3>
          <div className="space-y-3">
            {editError && (
              <div role="alert" className="alert alert-error text-xs">
                {editError}
              </div>
            )}
            <div className="form-control">
              <label className="label pb-1" htmlFor="oidc-edit-display-name">
                <span className="label-text text-xs uppercase tracking-wider">Display name</span>
              </label>
              <input
                id="oidc-edit-display-name"
                className="input input-bordered w-full"
                value={editDisplayName}
                onChange={(e) => setEditDisplayName(e.target.value)}
              />
            </div>
            <div className="form-control">
              <label className="label pb-1" htmlFor="oidc-edit-issuer-url">
                <span className="label-text text-xs uppercase tracking-wider">Issuer URL</span>
              </label>
              <input
                id="oidc-edit-issuer-url"
                className="input input-bordered w-full"
                value={editIssuerUrl}
                onChange={(e) => setEditIssuerUrl(e.target.value)}
              />
            </div>
            <div className="form-control">
              <label className="label pb-1" htmlFor="oidc-edit-client-id">
                <span className="label-text text-xs uppercase tracking-wider">Client ID</span>
              </label>
              <input
                id="oidc-edit-client-id"
                className="input input-bordered w-full"
                value={editClientId}
                onChange={(e) => setEditClientId(e.target.value)}
              />
            </div>
            <div className="form-control">
              <label className="label pb-1" htmlFor="oidc-edit-client-secret">
                <span className="label-text text-xs uppercase tracking-wider">
                  New client secret (optional)
                </span>
              </label>
              <input
                id="oidc-edit-client-secret"
                className="input input-bordered w-full"
                type="password"
                placeholder="Leave blank to keep current secret"
                value={editClientSecret}
                onChange={(e) => setEditClientSecret(e.target.value)}
              />
            </div>
            <div className="form-control">
              <label className="label pb-1" htmlFor="oidc-edit-scopes">
                <span className="label-text text-xs uppercase tracking-wider">Scopes</span>
              </label>
              <input
                id="oidc-edit-scopes"
                className="input input-bordered w-full"
                value={editScopes}
                onChange={(e) => setEditScopes(e.target.value)}
              />
            </div>
            <div className="form-control">
              <label className="label pb-1" htmlFor="oidc-edit-default-role">
                <span className="label-text text-xs uppercase tracking-wider">
                  Default role for new accounts
                </span>
              </label>
              <select
                id="oidc-edit-default-role"
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
            <Button
              variant="primary"
              size="sm"
              type="submit"
              label={saving ? "Saving..." : "Save"}
              loading={saving}
              onClick={submitEdit}
            />
          </div>
        </div>
        <form method="dialog" className="modal-backdrop">
          <button>close</button>
        </form>
      </dialog>
    </div>
  );
}
