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
import { ProjectView } from "@/layouts/ProjectView";
import { Login } from "@/components/Login";
import { SetupWizard } from "@/components/SetupWizard";
import { api, ApiError } from "@/lib/api/client";
import { chatStore, useAuthLost } from "./features/chat/store/chat";
import { setCurrentUser } from "@/lib/store/session";
import { chatProfileName, useChatType } from "./features/chat/useChatType";

/**
 * Boot sequence, in order: "loading" while the two probes below settle,
 * "needs_setup" if no admin-plane user exists yet (first-run wizard takes
 * over), else "unauthed"/"authed" from the existing session-cookie probe.
 *
 * No router yet -- this is one more branch alongside the existing
 * Login/ProjectView split, not a new architecture. A router is worth
 * introducing once nested Admin pages (users, signing keys, OIDC providers)
 * land and actually need one.
 */
type BootState = "loading" | "needs_setup" | "unauthed" | "authed";

/** Retry schedule for the auth probe, in ms. Only a real 401/403 means "not
 * signed in"; a network failure or 5xx means "ask again shortly". Short and
 * finite — after the last attempt we give up and show Login, which is at least
 * an actionable screen. */
const AUTH_PROBE_BACKOFF_MS = [500, 1500, 3000];

export default function App() {
  const [boot, setBoot] = useState<BootState>("loading");
  const [chatType] = useChatType();
  const authLost = useAuthLost();

  // Setup-status probe runs first: while no admin exists, /api/auth/me would
  // just 401 regardless, so there's nothing to gain by racing the two. If the
  // setup-status probe itself fails (e.g. admin-db unreachable), fall through
  // to the normal auth probe rather than getting stuck on "loading" forever.
  useEffect(() => {
    let cancelled = false;

    // Treating *any* me() failure as "unauthenticated" is what made a transient
    // proxy blip look like being logged out — the dev log has several
    // `http proxy error: /api/auth/me — getaddrinfo ENOTFOUND backend`, each of
    // which dropped the user to Login and lost their chat. Only 401/403 is an
    // answer about identity; everything else is a question to ask again.
    const probeAuth = async (attempt = 0): Promise<void> => {
      try {
        const user = await api.me();
        if (cancelled) return;
        setCurrentUser(user);
        setBoot("authed");
      } catch (err) {
        if (cancelled) return;
        const definitive = err instanceof ApiError && (err.status === 401 || err.status === 403);
        if (definitive || attempt >= AUTH_PROBE_BACKOFF_MS.length) {
          setBoot("unauthed");
          return;
        }
        const delay = AUTH_PROBE_BACKOFF_MS[attempt];
        await new Promise((resolve) => setTimeout(resolve, delay));
        if (!cancelled) await probeAuth(attempt + 1);
      }
    };

    api
      .setupStatus()
      .then((status) => (status.needs_setup ? setBoot("needs_setup") : probeAuth()))
      .catch(() => probeAuth());

    return () => {
      cancelled = true;
    };
  }, []);

  // On auth, load config + create a session, then open the SSE stream. The profile
  // is chosen once at session start from the local chat-type toggle.
  useEffect(() => {
    if (boot !== "authed") return;
    // Both calls are idempotent and self-guarding (chatStore.bootstrap checks
    // `ready`, connect() checks for an open stream), which is why there is no
    // ref guard here any more: a ref survives Fast Refresh while the store's
    // state does not, and that mismatch left the UI permanently not-ready.
    void chatStore.bootstrap(chatProfileName(chatType));
    chatStore.connect();
  }, [boot, chatType]);

  // The event stream closed and /api/auth/me confirmed the session is gone
  // (24h cookie TTL, so an overnight tab hits this). Previously the stream just
  // went quiet: no more status or task events, and the next message failed with
  // a generic "Error communicating with agent". Ask for credentials instead.
  useEffect(() => {
    if (!authLost) return;
    chatStore.suspendForReauth();
    setCurrentUser(null);
    setBoot("unauthed");
  }, [authLost]);

  const handleLogout = async () => {
    try {
      await api.logout();
    } catch {
      /* clear client state regardless */
    }
    // clear(), not disconnect(): also forgets this tab's remembered
    // conversation id, so signing in as someone else doesn't try to resume the
    // previous user's conversation.
    chatStore.clear();
    setCurrentUser(null);
    setBoot("unauthed");
  };

  if (boot === "loading") return null;
  if (boot === "needs_setup") return <SetupWizard onSuccess={() => setBoot("authed")} />;
  if (boot === "unauthed") return <Login onSuccess={() => setBoot("authed")} />;
  return <ProjectView onLogout={handleLogout} />;
}
