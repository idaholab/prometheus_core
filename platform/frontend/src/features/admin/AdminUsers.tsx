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
import { Pencil, Plus, Shield, Trash2, User } from "lucide-react";
import type { AdminUser } from "@/lib/api/types";
import { Button } from "@/components/ui/Button";
import { StatusPill } from "@/components/ui/StatusPill";
import { Tag } from "@/components/ui/Tag";
import {
  errorMessage,
  useCreateAdminUserMutation,
  useDeleteAdminUserMutation,
  useListAdminUsersQuery,
  useUpdateAdminUserMutation,
} from "./adminApi";

/**
 * Admin > Users. First table component in this codebase -- plain DaisyUI
 * `table`, no library. Create/edit use native <dialog class="modal">
 * (DaisyUI's modal pattern), also a first here; controlled via refs rather
 * than a boolean + conditional render so DaisyUI's open/close transition and
 * backdrop-click-to-close (`method="dialog"` inside the form) work for free.
 *
 * Server data comes from RTK Query (adminApi.ts): the list is cached, and a
 * create, edit or delete invalidates it so it refetches. Coming back to the
 * tab shows the cached list at once while it refreshes.
 */
export function AdminUsers() {
  const list = useListAdminUsersQuery(undefined, { refetchOnMountOrArgChange: true });
  const users = list.data ?? null;
  const [createUser] = useCreateAdminUserMutation();
  const [updateUser] = useUpdateAdminUserMutation();
  const [deleteUser] = useDeleteAdminUserMutation();
  const [deleteError, setDeleteError] = useState("");
  const error = list.error ? errorMessage(list.error, "Could not load users") : deleteError;

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
      await createUser({ username: createUsername, password: createPassword, role: createRole }).unwrap();
      createDialogRef.current?.close();
    } catch (err) {
      setCreateError(errorMessage(err, "Could not create user"));
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
      await updateUser({
        id: editing.id,
        patch: {
          role: editRole,
          is_active: editActive,
          ...(editPassword ? { password: editPassword } : {}),
        },
      }).unwrap();
      editDialogRef.current?.close();
    } catch (err) {
      setEditError(errorMessage(err, "Could not update user"));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (user: AdminUser) => {
    if (!window.confirm(`Delete user "${user.username}"? This cannot be undone.`)) return;
    setDeleteError("");
    try {
      await deleteUser(user.id).unwrap();
    } catch (err) {
      setDeleteError(errorMessage(err, "Could not delete user"));
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
                    <Button
                      variant="ghost"
                      size="xs"
                      icon={<Pencil />}
                      ariaLabel={`Edit ${user.username}`}
                      onClick={() => openEdit(user)}
                    />
                    <Button
                      variant="error"
                      soft
                      size="xs"
                      icon={<Trash2 />}
                      ariaLabel={`Delete ${user.username}`}
                      onClick={() => handleDelete(user)}
                    />
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

      <dialog ref={createDialogRef} className="modal" aria-labelledby="admin-create-title">
        <div className="modal-box max-w-sm">
          <h3 id="admin-create-title" className="font-medium mb-3">
            New user
          </h3>
          <div className="space-y-3">
            {createError && (
              <div role="alert" className="alert alert-error text-xs">
                {createError}
              </div>
            )}
            <div className="form-control">
              <label className="label pb-1" htmlFor="admin-create-username">
                <span className="label-text text-xs uppercase tracking-wider">Username</span>
              </label>
              <input
                id="admin-create-username"
                className="input input-bordered w-full"
                value={createUsername}
                onChange={(e) => setCreateUsername(e.target.value)}
                autoFocus
              />
            </div>
            <div className="form-control">
              <label className="label pb-1" htmlFor="admin-create-password">
                <span className="label-text text-xs uppercase tracking-wider">Password</span>
              </label>
              <input
                id="admin-create-password"
                className="input input-bordered w-full"
                type="password"
                value={createPassword}
                onChange={(e) => setCreatePassword(e.target.value)}
              />
            </div>
            <div className="form-control">
              <label className="label pb-1" htmlFor="admin-create-role">
                <span className="label-text text-xs uppercase tracking-wider">Role</span>
              </label>
              <select
                id="admin-create-role"
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

      <dialog ref={editDialogRef} className="modal" aria-labelledby="admin-edit-title">
        <div className="modal-box max-w-sm">
          <h3 id="admin-edit-title" className="font-medium mb-3">
            Edit {editing?.username}
          </h3>
          <div className="space-y-3">
            {editError && (
              <div role="alert" className="alert alert-error text-xs">
                {editError}
              </div>
            )}
            <div className="form-control">
              <label className="label pb-1" htmlFor="admin-edit-role">
                <span className="label-text text-xs uppercase tracking-wider">Role</span>
              </label>
              <select
                id="admin-edit-role"
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
              <label className="label pb-1" htmlFor="admin-edit-password">
                <span className="label-text text-xs uppercase tracking-wider">New password (optional)</span>
              </label>
              <input
                id="admin-edit-password"
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
