import { useState } from "react";
import { chatStore } from "@/lib/store/chat";
import { useCurrentUser } from "@/lib/store/session";
import { chatProfileName, useChatType } from "@/lib/useChatType";
import { AdminSection } from "../components/admin/AdminSection";
import { SettingsPanel } from "../components/SettingsPanel";
import { Header } from "../components/Header";
import { LeftPanel } from "../components/LeftPanel";
import { Home } from "../components/dashboard/Home";
import { ComingSoon } from "../components/dashboard/ComingSoon";
import { navLabel, type NavId } from "../components/dashboard/nav";

interface Props {
  onLogout: () => void;
}

// Primary navigation lives in the left sidebar now (LeftPanel). The old
// top-of-content tab bar was demoted; its pattern is preserved as the reusable
// <TabBar> component for section sub-navigation (e.g. inside Admin).
export function ProjectView({ onLogout }: Props) {
  const [activeNav, setActiveNav] = useState<NavId>("home");
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(false);
  const [chatType] = useChatType();
  const currentUser = useCurrentUser();

  // New chat: fresh conversation_id + cleared transcript via the store (which
  // returns Home to its idle welcome). No full page reload.
  const handleNewChat = () => {
    void chatStore.reset(chatProfileName(chatType));
  };

  const renderContent = () => {
    if (activeNav === "home") return <Home />;
    if (activeNav === "admin" && currentUser?.role === "admin") return <AdminSection />;
    return <ComingSoon label={navLabel(activeNav)} />;
  };

  return (
    <div className="flex h-screen flex-col bg-base-100 text-base-content">
      <div className="flex flex-1 overflow-hidden">
        <LeftPanel
          isOpen={leftOpen}
          onToggle={() => setLeftOpen((v) => !v)}
          activeNav={activeNav}
          onNavSelect={setActiveNav}
          onNewChat={handleNewChat}
        />

        <div className="flex flex-1 flex-col overflow-hidden">
          <Header
            title={navLabel(activeNav)}
            onLogout={onLogout}
            onToggleSettings={() => setRightOpen((v) => !v)}
          />
          <main className="flex flex-1 overflow-hidden">{renderContent()}</main>
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
