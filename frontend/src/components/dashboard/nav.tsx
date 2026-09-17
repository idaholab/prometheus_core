import type { ReactNode } from "react";
import { Cpu, Database, GitBranch, Home, ShieldCheck, Shield, Terminal, Users } from "lucide-react";

/**
 * Primary navigation model for the app shell's left sidebar (Figma nav list).
 * Shared between LeftPanel (renders the items) and ProjectView (dispatches
 * content + derives the header title). Only `home` and `admin` are wired;
 * the rest render a ComingSoon placeholder until scoped individually.
 */
export type NavId =
  | "home"
  | "agent-registry"
  | "workflows"
  | "approval-queue"
  | "project-management"
  | "data-management"
  | "jobs-console"
  | "admin";

export interface NavItem {
  id: NavId;
  label: string;
  icon: ReactNode;
}

export const NAV_ITEMS: NavItem[] = [
  { id: "home", label: "Home", icon: <Home size={18} /> },
  { id: "agent-registry", label: "Agent Registry", icon: <Cpu size={18} /> },
  { id: "workflows", label: "Workflows", icon: <GitBranch size={18} /> },
  { id: "approval-queue", label: "Approval Queue", icon: <ShieldCheck size={18} /> },
  { id: "project-management", label: "Project Management", icon: <Users size={18} /> },
  { id: "data-management", label: "Data Management", icon: <Database size={18} /> },
  { id: "jobs-console", label: "Jobs Console", icon: <Terminal size={18} /> },
];

/** Role-gated, pinned to the bottom of the sidebar. Not in the Figma nav list. */
export const ADMIN_NAV_ITEM: NavItem = { id: "admin", label: "Admin", icon: <Shield size={18} /> };

export function navLabel(id: NavId): string {
  return [...NAV_ITEMS, ADMIN_NAV_ITEM].find((n) => n.id === id)?.label ?? "";
}
