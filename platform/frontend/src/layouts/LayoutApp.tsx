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
import { chatStore } from "@/features/chat";
import { useCurrentUser } from "@/features/auth";
import { chatProfileName, useChatType } from "@/features/chat";
import { AdminSection } from "@/features/admin";
import { ChatHistory } from "@/features/chat";
import { SettingsPanel } from "@/features/shell";
import { Header } from "@/features/shell";
import { LeftPanel } from "@/features/shell";
import { Home } from "@/features/dashboard";
import { ComingSoon } from "@/features/shell";
import { navLabel, type NavId } from "@/features/shell";
import { PageAgentRegistry } from "@/pages/PageAgentRegistry";
import { PageApprovalQueue } from "@/pages/PageApprovalQueue";
import { PageDataManagement } from "@/pages/PageDataManagement";
import { PageProjectManagement } from "@/pages/PageProjectManagement";
import { PageWorkflows } from "@/pages/PageWorkflows";

interface Props {
  onLogout: () => void;
}

// Primary navigation lives in the left sidebar (LeftPanel).
export function ProjectView({ onLogout }: Props) {
  const [activeNav, setActiveNav] = useState<NavId>("home");
  // Bumped on every sidebar click and used as the section page's key, so
  // clicking the current section resets it (e.g. Workflows: Builder → Console).
  const [navCount, setNavCount] = useState(0);
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(false);
  const [chatType] = useChatType();
  const currentUser = useCurrentUser();

  // New chat: switch to Home, then a fresh conversation_id + cleared transcript
  // via the store (which returns Home to its idle welcome). No full page reload.
  const handleNewChat = () => {
    setActiveNav("home");
    void chatStore.reset(chatProfileName(chatType));
  };

  return (
    <div className="flex h-screen flex-col bg-base-100 text-base-content">
      <div className="flex flex-1 overflow-hidden">
        <LeftPanel
          isOpen={leftOpen}
          onToggle={() => setLeftOpen((v) => !v)}
          activeNav={activeNav}
          onNavSelect={(id) => {
            setActiveNav(id);
            setNavCount((n) => n + 1);
          }}
          onNewChat={handleNewChat}
        >
          <ChatHistory
            onNewChat={handleNewChat}
            onOpenConversation={() => setActiveNav("home")}
          />
        </LeftPanel>

        <div className="flex flex-1 flex-col overflow-hidden">
          <Header
            title={navLabel(activeNav)}
            onLogout={onLogout}
            onToggleSettings={() => setRightOpen((v) => !v)}
          />
          <main className="flex flex-1 overflow-hidden">
            {/* Home stays mounted and is merely hidden while another section is
                active, so Chat keeps its scroll position and any in-flight
                streaming view across navigation. */}
            <div
              className={`flex flex-1 overflow-hidden ${activeNav === "home" ? "" : "hidden"}`}
            >
              <Home />
            </div>
            {activeNav === "admin" && currentUser?.role === "admin" && <AdminSection />}
            {activeNav === "workflows" && <PageWorkflows key={navCount} />}
            {activeNav === "agent-registry" && <PageAgentRegistry />}
            {activeNav === "approval-queue" && <PageApprovalQueue />}
            {activeNav === "data-management" && <PageDataManagement />}
            {activeNav === "project-management" && <PageProjectManagement />}
            {activeNav !== "home" &&
              activeNav !== "admin" &&
              activeNav !== "workflows" &&
              activeNav !== "agent-registry" &&
              activeNav !== "approval-queue" &&
              activeNav !== "data-management" &&
              activeNav !== "project-management" && <ComingSoon label={navLabel(activeNav)} />}
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
