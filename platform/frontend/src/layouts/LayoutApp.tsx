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

import { Fragment, useEffect, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router";
import { api } from "@/lib/api/client";
import { setCurrentUser } from "@/features/auth";
import { chatProfileName, chatStore, ChatHistory, useAuthLost, useChatType } from "@/features/chat";
import { Header, LeftPanel, navLabel, SettingsPanel } from "@/features/shell";
import { loginPathFor, NAV_PATHS, navIdForPath, PATHS } from "@/app/paths";
import { PageHome } from "@/pages/PageHome";

/**
 * The signed-in app shell: the sidebar, the header, the settings panel, and
 * the current route's page in the middle. Every signed-in route renders inside
 * it, behind the requireUser guard.
 *
 * Home is rendered here rather than through the outlet, and only hidden while
 * another section is showing, so Chat keeps its scroll position and any
 * streaming reply across navigation.
 */
export function LayoutApp() {
  const location = useLocation();
  const navigate = useNavigate();
  const navId = navIdForPath(location.pathname);
  // Bumped on every sidebar click. Workflows is keyed by it, so clicking
  // Workflows from the Builder returns to the Console. PPLT-240 replaces this
  // with a Builder URL.
  const [navCount, setNavCount] = useState(0);
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(false);
  const [chatType] = useChatType();
  const authLost = useAuthLost();

  // Load config + create a session, then open the SSE stream. The profile is
  // chosen once at session start from the local chat-type toggle. Both calls
  // are idempotent and self-guarding (chatStore.bootstrap checks `ready`,
  // connect() checks for an open stream), so there is no ref guard: a ref
  // survives Fast Refresh while the store's state does not, and that mismatch
  // left the UI permanently not-ready.
  useEffect(() => {
    void chatStore.bootstrap(chatProfileName(chatType));
    chatStore.connect();
  }, [chatType]);

  // The event stream closed and /api/auth/me confirmed the session is gone
  // (24h cookie TTL, so an overnight tab hits this). Ask for credentials, then
  // come back to this page.
  useEffect(() => {
    if (!authLost) return;
    chatStore.suspendForReauth();
    setCurrentUser(null);
    navigate(loginPathFor(location.pathname + location.search), { replace: true });
  }, [authLost, navigate, location.pathname, location.search]);

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
    navigate(PATHS.login, { replace: true });
  };

  // New chat: switch to Home, then a fresh conversation_id + cleared transcript
  // via the store (which returns Home to its idle welcome). No full page reload.
  const handleNewChat = () => {
    navigate(PATHS.home);
    void chatStore.reset(chatProfileName(chatType));
  };

  return (
    <div className="flex h-screen flex-col bg-base-100 text-base-content">
      <div className="flex flex-1 overflow-hidden">
        <LeftPanel
          isOpen={leftOpen}
          onToggle={() => setLeftOpen((v) => !v)}
          navPaths={NAV_PATHS}
          onNavSelect={() => setNavCount((n) => n + 1)}
          onNewChat={handleNewChat}
        >
          <ChatHistory onNewChat={handleNewChat} onOpenConversation={() => navigate(PATHS.home)} />
        </LeftPanel>

        <div className="flex flex-1 flex-col overflow-hidden">
          <Header
            title={navId ? navLabel(navId) : "Page not found"}
            onLogout={handleLogout}
            onToggleSettings={() => setRightOpen((v) => !v)}
          />
          <main className="flex flex-1 overflow-hidden">
            <div className={`flex flex-1 overflow-hidden ${navId === "home" ? "" : "hidden"}`}>
              <PageHome />
            </div>
            <Fragment key={navId === "workflows" ? navCount : undefined}>
              <Outlet />
            </Fragment>
          </main>
        </div>

        <aside
          className={`${rightOpen ? "w-64 border-l bg-base-200 border-base-300" : "w-0"} transition-[width] duration-200 overflow-hidden flex flex-col`}
        >
          <SettingsPanel onClose={() => setRightOpen(false)} />
        </aside>
      </div>
    </div>
  );
}
