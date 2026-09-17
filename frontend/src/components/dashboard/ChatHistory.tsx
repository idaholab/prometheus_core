import { useState } from "react";
import { ChevronDown, ChevronRight, Plus } from "lucide-react";

interface Session {
  id: string;
  title: string;
  date: string;
  active?: boolean;
}
interface Topic {
  name: string;
  sessions: Session[];
}

// Mock/static per Figma. The flat list can later bind to
// client.getRecentConversations(); the topic grouping is aspirational and has
// no backing data source yet (ConversationSummary has no category field).
const MOCK_TOPICS: Topic[] = [
  {
    name: "Reactor Components",
    sessions: [
      { id: "1", title: "Thermal Analysis RC-7", date: "Today", active: true },
      { id: "2", title: "Neutronics Solver Config", date: "Oct 24" },
      { id: "3", title: "Coolant Loop Review", date: "Oct 22" },
    ],
  },
  {
    name: "Flow Simulation",
    sessions: [
      { id: "4", title: "CFD Flow Simulation", date: "Oct 20" },
      { id: "5", title: "Turbulence Model Tuning", date: "Oct 18" },
      { id: "6", title: "Boundary Layer Analysis", date: "Oct 15" },
      { id: "7", title: "Inlet Pressure Study", date: "Oct 12" },
      { id: "8", title: "Mesh Refinement Check", date: "Oct 10" },
    ],
  },
  {
    name: "Assembly QA",
    sessions: [{ id: "9", title: "Reactor Assembly QA", date: "Oct 8" }],
  },
];

interface Props {
  onNewChat: () => void;
}

/**
 * Chat-history tree for the sidebar (mock UI for now). Topic groups collapse;
 * sessions are non-interactive placeholders until history is ported.
 */
export function ChatHistory({ onNewChat }: Props) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const toggle = (name: string) => setCollapsed((c) => ({ ...c, [name]: !c[name] }));

  return (
    <div className="flex flex-col gap-2 pb-3">
      <p className="m-0 px-1 text-[11px] font-semibold text-base-content/60">Chat History</p>
      <button
        onClick={onNewChat}
        className="flex items-center gap-1.5 px-1 text-xs text-base-content/60 transition-colors hover:text-base-content cursor-pointer"
      >
        <Plus size={12} />
        New Chat
      </button>

      <div className="flex flex-col gap-1">
        {MOCK_TOPICS.map((topic) => {
          const isCollapsed = collapsed[topic.name];
          return (
            <div key={topic.name} className="flex flex-col gap-0.5">
              <button
                onClick={() => toggle(topic.name)}
                className="flex items-center justify-between px-2 py-1.5 text-xs font-semibold text-base-content/50 transition-colors hover:text-base-content/80 cursor-pointer"
              >
                <span>{topic.name}</span>
                {isCollapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
              </button>
              {!isCollapsed &&
                topic.sessions.map((s) => (
                  <div
                    key={s.id}
                    className={`flex items-center justify-between rounded-md py-1.5 pl-3 pr-2 ${
                      s.active
                        ? "border border-primary bg-primary/15"
                        : "hover:bg-base-300"
                    }`}
                  >
                    <span
                      className={`truncate text-[13px] ${
                        s.active ? "font-semibold text-base-content" : "text-base-content/80"
                      }`}
                    >
                      {s.title}
                    </span>
                    <span className="shrink-0 pl-2 text-[11px] text-base-content/50">{s.date}</span>
                  </div>
                ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
