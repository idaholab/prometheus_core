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
import { Button } from "@/components/ui/Button";
import { api, ApiError } from "@/lib/api/client";
import type { AuthProvider } from "@/lib/api/types";
import { setCurrentUser } from "@/lib/store/session";
import { AuthError, AuthField, AuthLayout } from "./AuthLayout";

interface Props {
  onSuccess: () => void;
}

export function Login({ onSuccess }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [providers, setProviders] = useState<AuthProvider[]>([]);

  // Best-effort: an empty list just means no "sign in with ..." buttons show,
  // never a hard error blocking the password form.
  useEffect(() => {
    api
      .listAuthProviders()
      .then(setProviders)
      .catch(() => setProviders([]));
  }, []);

  const handleSubmit = async () => {
    if (loading) return;
    setLoading(true);
    setError("");
    try {
      const user = await api.login(username, password);
      setCurrentUser(user);
      onSuccess();
    } catch (err) {
      // Only a real 401 means the credentials were wrong. Any other failure
      // (5xx, or a network/proxy blip right after startup) can happen *after*
      // the backend already set the session cookie, so the login actually
      // succeeded and only the response was lost -- which is why a manual
      // reload used to "fix" it. Re-check the session before giving up: if the
      // cookie is live, go straight to chat instead of showing a false error.
      if (err instanceof ApiError && err.status === 401) {
        setError("Invalid credentials");
      } else {
        try {
          const user = await api.me();
          setCurrentUser(user);
          onSuccess();
          return;
        } catch (meErr) {
          if (meErr instanceof ApiError && (meErr.status === 401 || meErr.status === 403)) {
            setError("Invalid credentials");
          } else {
            setError("Could not reach the server, please try again");
          }
        }
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthLayout
      title="Sign in"
      subtitle="Enter your INL credentials to continue"
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
        autoComplete="current-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />

      <Button
        variant="primary"
        wide
        type="submit"
        loading={loading}
        label={loading ? "Signing in..." : "Sign in"}
      />

      {providers.length > 0 && (
        <>
          <div className="divider text-xs text-base-content/40">or</div>
          <div className="space-y-2">
            {providers.map((provider) => (
              <Button
                key={provider.provider_id}
                outline
                wide
                label={`Sign in with ${provider.display_name}`}
                onClick={() => window.location.assign(api.loginUrl(provider.provider_id))}
              />
            ))}
          </div>
        </>
      )}
    </AuthLayout>
  );
}