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
import { Button } from "@/components/ui/Button";
import { api, ApiError } from "@/lib/api/client";
import { setCurrentUser } from "@/lib/store/session";
import { AuthError, AuthField, AuthLayout } from "./AuthLayout";

interface Props {
  onSuccess: () => void;
}

/**
 * First-run screen: shown instead of <Login> whenever GET /api/setup/status
 * reports `needs_setup: true` (no admin-plane `users` row exists yet). Creates
 * the first account -- always role "admin" server-side -- and logs it in
 * immediately, same as a successful <Login>.
 */
export function SetupWizard({ onSuccess }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    if (loading) return;
    if (!username.trim() || !password) {
      setError("Username and password are required");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const user = await api.bootstrap(username, password);
      setCurrentUser(user);
      onSuccess();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // Another browser/tab won the race to bootstrap first. Reloading picks
        // up needs_setup: false and shows <Login> instead.
        setError("Setup was already completed. Reloading...");
        setTimeout(() => window.location.reload(), 1500);
      } else {
        setError("Could not create the admin account. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthLayout
      title="Welcome, set up your admin account"
      subtitle="This platform has no users yet. Create the first account below; it will be an administrator."
      onSubmit={handleSubmit}
    >
      <AuthError message={error} />

      <AuthField
        label="Username"
        placeholder="username"
        autoComplete="username"
        value={username}
        onChange={(e) => setUsername(e.target.value)}
        autoFocus
      />
      <AuthField
        label="Password"
        type="password"
        placeholder="••••••••"
        autoComplete="new-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <AuthField
        label="Confirm password"
        type="password"
        placeholder="••••••••"
        autoComplete="new-password"
        value={confirmPassword}
        onChange={(e) => setConfirmPassword(e.target.value)}
      />

      <Button
        variant="primary"
        wide
        type="submit"
        loading={loading}
        label={loading ? "Creating account..." : "Create admin account"}
      />
    </AuthLayout>
  );
}