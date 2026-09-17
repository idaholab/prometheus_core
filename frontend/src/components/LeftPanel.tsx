import { Atom, PanelLeft } from "lucide-react";
import { useCurrentUser } from "@/lib/store/session";
import { NAV_ITEMS, ADMIN_NAV_ITEM, type NavId, type NavItem } from "./dashboard/nav";
import { ChatHistory } from "./dashboard/ChatHistory";

interface Props {
  isOpen: boolean;
  onToggle: () => void;
  activeNav: NavId;
  onNavSelect: (id: NavId) => void;
  onNewChat: () => void;
}

function NavButton({
  item,
  active,
  collapsed,
  onSelect,
}: {
  item: NavItem;
  active: boolean;
  collapsed: boolean;
  onSelect: (id: NavId) => void;
}) {
  return (
    <button
      onClick={() => onSelect(item.id)}
      title={item.label}
      aria-current={active ? "page" : undefined}
      className={`flex items-center rounded-lg border-l-2 text-sm transition-colors cursor-pointer ${
        collapsed ? "size-9 justify-center" : "w-full gap-2.5 px-2.5 py-2"
      } ${
        active
          ? "border-primary bg-primary/15 font-semibold text-base-content"
          : "border-transparent text-base-content/60 hover:bg-base-300 hover:text-base-content"
      }`}
    >
      <span className="flex size-[18px] shrink-0 items-center justify-center">{item.icon}</span>
      {!collapsed && <span className="truncate">{item.label}</span>}
    </button>
  );
}

/**
 * The app shell's left sidebar — now the primary navigation (Figma nav list),
 * plus brand, a mock chat-history tree, and a role-gated Admin entry pinned to
 * the bottom. Collapses to a 64px icon rail.
 */
export function LeftPanel({ isOpen, onToggle, activeNav, onNavSelect, onNewChat }: Props) {
  const collapsed = !isOpen;
  const isAdmin = useCurrentUser()?.role === "admin";

  return (
    <aside
      className={`${isOpen ? "w-64" : "w-16"} flex flex-col overflow-hidden border-r border-base-300 bg-base-200 transition-[width] duration-200`}
    >
      {/* Brand */}
      <div className={`flex items-center gap-2.5 p-3 ${collapsed ? "justify-center" : ""}`}>
        <div className="flex size-8 shrink-0 items-center justify-center rounded-md border border-primary bg-primary/15 text-primary">
          <Atom size={18} />
        </div>
        {!collapsed && (
          <div className="min-w-0">
            <p className="m-0 text-[10px] font-bold tracking-widest text-base-content/50">INL</p>
            <p className="m-0 text-base font-bold leading-tight text-base-content">MARVEL</p>
          </div>
        )}
      </div>
      {!collapsed && (
        <p className="m-0 px-3 pb-1 text-[10px] font-medium text-primary">MARVEL REACTOR PROJECT</p>
      )}

      {/* Collapse toggle */}
      <div className={`flex px-2 pb-2 ${collapsed ? "justify-center" : "justify-end"}`}>
        <button
          className="btn btn-ghost btn-xs btn-square"
          onClick={onToggle}
          aria-label={isOpen ? "Collapse sidebar" : "Expand sidebar"}
          title={isOpen ? "Collapse sidebar" : "Expand sidebar"}
        >
          <PanelLeft size={16} />
        </button>
      </div>

      {/* Primary nav */}
      <nav className={`flex flex-col gap-1 px-2 ${collapsed ? "items-center" : ""}`}>
        {NAV_ITEMS.map((item) => (
          <NavButton
            key={item.id}
            item={item}
            active={activeNav === item.id}
            collapsed={collapsed}
            onSelect={onNavSelect}
          />
        ))}
      </nav>

      {/* Chat history (expanded only) */}
      {collapsed ? (
        <div className="flex-1" />
      ) : (
        <>
          <div className="mx-3 my-3 border-t border-base-300" />
          <div className="min-h-0 flex-1 overflow-y-auto px-2">
            <ChatHistory onNewChat={onNewChat} />
          </div>
        </>
      )}

      {/* Admin (role-gated, pinned bottom) */}
      {isAdmin && (
        <div className={`border-t border-base-300 p-2 ${collapsed ? "flex justify-center" : ""}`}>
          <NavButton
            item={ADMIN_NAV_ITEM}
            active={activeNav === "admin"}
            collapsed={collapsed}
            onSelect={onNavSelect}
          />
        </div>
      )}
    </aside>
  );
}
