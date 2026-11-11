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
import { Pencil, Plus, Shield, Trash2, User } from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import type { AdminUser } from "@/lib/api/types";
import { Button } from "@/components/ui/Button";
import { StatusPill } from "@/components/ui/StatusPill";
import { Tag } from "@/components/ui/Tag";

/**
 * Admin > Users. First table component in this codebase -- plain DaisyUI
 * `table`, no library. Create/edit use native <dialog class="modal">
 * (DaisyUI's modal pattern), also a first here; controlled via refs rather
 * than a boolean + conditional render so DaisyUI's open/close transition and
 * backdrop-click-to-close (`method="dialog"` inside the form) work for free.
 */
export function AdminUsers() {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [error, setError] = useState("");

  const createDialogRef = useRef<HTMLDialogElement>(null);
  const [createUsername, setCreateUsername] = useState("");
  const [createPassword, setCreatePassword] = useState("");
  const [createRole, setCreateRole] = useState("user");
  const [createError, setCreateError] = useState("");
  const [creating, setCreating] = useState(false);

  const editDialogRef = useRef<HTMLDialogElement>(null);
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [editRole, setEditRole] = useState("user");
  const [editActive, setEditActive] = useState(true);
  const [editPassword, setEditPassword] = useState("");
  const [editError, setEditError] = useState("");
  const [saving, setSaving] = useState(false);

  const refresh = () => {
    api
      .listAdminUsers()
      .then((list) => setUsers(list))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load users"));
  };

  useEffect(refresh, []);

  const openCreate = () => {
    setCreateUsername("");
    setCreatePassword("");
    setCreateRole("user");
    setCreateError("");
    createDialogRef.current?.showModal();
  };

  const submitCreate = async () => {
    if (!createUsername.trim() || !createPassword) {
      setCreateError("Username and password are required");
      return;
    }
    setCreating(true);
    setCreateError("");
    try {
      await api.createAdminUser({ username: createUsername, password: createPassword, role: createRole });
      createDialogRef.current?.close();
      refresh();
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "Could not create user");
    } finally {
      setCreating(false);
    }
  };

  const openEdit = (user: AdminUser) => {
    setEditing(user);
    setEditRole(user.role);
    setEditActive(user.is_active);
    setEditPassword("");
    setEditError("");
    editDialogRef.current?.showModal();
  };

  const submitEdit = async () => {
    if (!editing) return;
    setSaving(true);
    setEditError("");
    try {
      await api.updateAdminUser(editing.id, {
        role: editRole,
        is_active: editActive,
        ...(editPassword ? { password: editPassword } : {}),
      });
      editDialogRef.current?.close();
      refresh();
    } catch (err) {
      setEditError(err instanceof ApiError ? err.message : "Could not update user");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (user: AdminUser) => {
    if (!window.confirm(`Delete user "${user.username}"? This cannot be undone.`)) return;
    try {
      await api.deleteAdminUser(user.id);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not delete user");
    }
  };

  return (
    <div className="flex flex-col gap-4 p-4 flex-1 overflow-y-auto">
      <div className="flex items-center justify-between">
        <h3>Users</h3>
        <Button variant="primary" size="sm" icon={<Plus />} label="New user" onClick={openCreate} />
      </div>

      {error && (
        <div role="alert" className="alert alert-error text-xs">
          {error}
        </div>
      )}

      {users === null ? (
        <div className="text-sm text-base-content/50">Loading...</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="table table-sm">
            <thead>
              <tr>
                <th>Username</th>
                <th>Role</th>
                <th>Provider</th>
                <th>Status</th>
                <th>Last login</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id}>
                  <td>{user.username}</td>
                  <td>
                    <Tag label={user.role} icon={user.role === "admin" ? Shield : User} />
                  </td>
                  <td className="text-base-content/60">{user.provider}</td>
                  <td>
                    <StatusPill
                      label={user.is_active ? "active" : "inactive"}
                      tone={user.is_active ? "success" : "neutral"}
                    />
                  </td>
                  <td className="text-base-content/60">
                    {user.last_login_at ? new Date(user.last_login_at).toLocaleString() : "never"}
                  </td>
                  <td className="flex gap-1 justify-end">
                    <Button variant="ghost" size="xs" icon={<Pencil />} ariaLabel="Edit user" onClick={() => openEdit(user)} />
                    <Button variant="error" soft size="xs" icon={<Trash2 />} ariaLabel="Delete user" onClick={() => handleDelete(user)} />
                  </td>
                </tr>
              ))}
              {users.length === 0 && (
                <tr>
                  <td colSpan={6} className="text-center text-base-content/50">
                    No users yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <dialog ref={createDialogRef} className="modal">
        <div className="modal-box max-w-sm">
          <h3 className="font-medium mb-3">New user</h3>
          <div className="space-y-3">
            {createError && (
              <div role="alert" className="alert alert-error text-xs">
                {createError}
              </div>
            )}
            <div className="form-control">
              <label className="label pb-1">
                <span className="label-text text-xs uppercase tracking-wider">Username</span>
              </label>
              <input
                className="input input-bordered w-full"
                value={createUsername}
                onChange={(e) => setCreateUsername(e.target.value)}
                autoFocus
              />
            </div>
            <div className="form-control">
              <label className="label pb-1">
                <span className="label-text text-xs uppercase tracking-wider">Password</span>
              </label>
              <input
                className="input input-bordered w-full"
                type="password"
                value={createPassword}
                onChange={(e) => setCreatePassword(e.target.value)}
              />
            </div>
            <div className="form-control">
              <label className="label pb-1">
                <span className="label-text text-xs uppercase tracking-wider">Role</span>
              </label>
              <select
                className="select select-bordered w-full"
                value={createRole}
                onChange={(e) => setCreateRole(e.target.value)}
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

      <dialog ref={editDialogRef} className="modal">
        <div className="modal-box max-w-sm">
          <h3 className="font-medium mb-3">Edit {editing?.username}</h3>
          <div className="space-y-3">
            {editError && (
              <div role="alert" className="alert alert-error text-xs">
                {editError}
              </div>
            )}
            <div className="form-control">
              <label className="label pb-1">
                <span className="label-text text-xs uppercase tracking-wider">Role</span>
              </label>
              <select
                className="select select-bordered w-full"
                value={editRole}
                onChange={(e) => setEditRole(e.target.value)}
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
                  checked={editActive}
                  onChange={(e) => setEditActive(e.target.checked)}
                />
                <span className="label-text text-xs uppercase tracking-wider">Active</span>
              </label>
            </div>
            <div className="form-control">
              <label className="label pb-1">
                <span className="label-text text-xs uppercase tracking-wider">New password (optional)</span>
              </label>
              <input
                className="input input-bordered w-full"
                type="password"
                placeholder="Leave blank to keep current password"
                value={editPassword}
                onChange={(e) => setEditPassword(e.target.value)}
              />
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
