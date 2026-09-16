import { useRef, useState } from "react";
import { LayoutDashboard, MessageSquare, FolderOpen, Bot, ShieldCheck } from "lucide-react";
import { chatStore } from "@/lib/store/chat";
import { useCurrentUser } from "@/lib/store/session";
import { chatProfileName, useChatType } from "@/lib/useChatType";
import { AdminSection } from "../components/admin/AdminSection";
import { Chat } from "../components/Chat";
import { SettingsPanel } from "../components/SettingsPanel";
import { Header } from "../components/Header";
import { LeftPanel } from "../components/LeftPanel";
import { DashboardHome } from "../components/dashboard/DashboardHome";

type TabId = "chat" | "dashboard" | "artifacts" | "agents" | "admin";

const TABS: { id: TabId; label: string; icon: React.ReactNode }[] = [
  { id: "chat",      label: "Chat",      icon: <MessageSquare size={15} /> },
  { id: "dashboard", label: "Dashboard", icon: <LayoutDashboard size={15} /> },
  { id: "artifacts", label: "Artifacts", icon: <FolderOpen size={15} /> },
  { id: "agents",    label: "Agents",    icon: <Bot size={15} /> },
];

// Only shown to role: "admin" -- appended to TABS below, not part of the
// always-visible set. Sub-navigation between Users/Signing Keys/(Identity
// Providers, Phase 4) lives inside AdminSection, not as separate top-level tabs.
const ADMIN_TAB: { id: TabId; label: string; icon: React.ReactNode } = {
  id: "admin",
  label: "Admin",
  icon: <ShieldCheck size={15} />,
};

interface Props {
  onLogout: () => void;
}

export function ProjectView({ onLogout }: Props) {
  const [activeTab, setActiveTab] = useState<TabId>("chat");
  const [leftOpen, setLeftOpen] = useState(false);
  const [rightOpen, setRightOpen] = useState(false);
  const [chatType] = useChatType();
  const currentUser = useCurrentUser();
  const tabs = currentUser?.role === "admin" ? [...TABS, ADMIN_TAB] : TABS;

  // Owned here (not in Chat) so that when the artifact-viewer panel is
  // added alongside Chat, each panel gets its own scroll ref and scrolls
  // independently — the scrollbar sits at this panel's edge, not hugging
  // the narrower centered message column inside Chat.
  const chatScrollRef = useRef<HTMLDivElement>(null);

  // New chat: fresh conversation_id + cleared transcript via the store — no full
  // page reload (the old Chainlit path called clear() + window.location.reload()).
  const handleNewChat = () => {
    void chatStore.reset(chatProfileName(chatType));
  };

  return (
    <div className="flex flex-col h-screen bg-base-100 text-base-content">
      <Header onLogout={onLogout} onToggleSettings={() => setRightOpen((v) => !v)} />
      <div className="flex flex-1 overflow-hidden">
        <LeftPanel
          isOpen={leftOpen}
          onToggle={() => setLeftOpen((v) => !v)}
          onNewChat={handleNewChat}
        />

        <main className="flex flex-col flex-1 overflow-hidden">
          {/* Tab bar */}
          <div className="px-4 pt-3 pb-3">
            <div className="inline-flex items-center gap-1 bg-base-200 rounded-xl p-1">
              {tabs.map((tab) => {
                const isActive = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`
                      flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium
                      transition-all duration-150 cursor-pointer
                      ${isActive
                        ? "bg-primary text-primary-content shadow-sm"
                        : "text-base-content/60 hover:text-base-content hover:bg-base-300"
                      }
                    `}
                  >
                    {tab.icon}
                    {tab.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Tab content */}
          <div className={`flex flex-col flex-1 overflow-hidden ${activeTab === "chat" ? "" : "hidden"}`}>
            <Chat scrollContainerRef={chatScrollRef} />
          </div>
          {activeTab === "dashboard" && (
            <div className="flex flex-1 overflow-hidden">
              {/* Launching from dashboard-home drops the user into the chat tab.
                  Seeding the conversation with the prompt is a follow-up. */}
              <DashboardHome onStart={() => setActiveTab("chat")} />
            </div>
          )}
          {activeTab === "artifacts" && (
            <div className="flex flex-1 items-center justify-center text-base-content/40 text-sm">
              Artifacts coming soon
            </div>
          )}
          {activeTab === "agents" && (
            <div className="flex flex-1 items-center justify-center text-base-content/40 text-sm">
              Agents coming soon
            </div>
          )}
          {activeTab === "admin" && currentUser?.role === "admin" && <AdminSection />}
        </main>

        <aside
          className={`${rightOpen ? "w-64 border-l bg-base-200 border-base-300" : "w-0"} transition-[width] duration-200 overflow-hidden flex flex-col`}
        >
          <SettingsPanel onClose={() => setRightOpen(false)} />
        </aside>
      </div>
    </div>
  );
}
