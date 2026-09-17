import { useState } from "react";
import { Atom, Flame, Network, ShieldCheck, SplitSquareHorizontal, Terminal } from "lucide-react";
import { SuggestionCard } from "./SuggestionCard";

const SUGGESTIONS = [
  {
    icon: <Flame size={14} />,
    title: "Run Thermal Analysis",
    description: "Simulate heat distribution across reactor assembly RC-7",
    prompt: "Run a thermal analysis on reactor assembly RC-7.",
  },
  {
    icon: <Network size={14} />,
    title: "Generate Mesh",
    description: "Create high-fidelity mesh for boundary layer refinement",
    prompt: "Generate a high-fidelity mesh with boundary layer refinement.",
  },
  {
    icon: <ShieldCheck size={14} />,
    title: "Review Safety Report",
    description: "Analyze neutron flux safety margins for current config",
    prompt: "Review the safety report and analyze neutron flux safety margins.",
  },
  {
    icon: <SplitSquareHorizontal size={14} />,
    title: "Compare Configurations",
    description: "Side-by-side comparison of reactor parameter sets",
    prompt: "Compare reactor parameter sets side by side.",
  },
];

interface Props {
  /** Launch a conversation from a suggestion or the composer. */
  onStart: (prompt: string) => void;
}

/**
 * The idle state of Home (Figma 131:161 chat panel): a welcome launcher.
 * Selecting a card or submitting the composer seeds the conversation — the
 * same "get started" behavior as Chat's WelcomeScreen — after which Home
 * swaps this out for the live Chat.
 */
export function HomeWelcome({ onStart }: Props) {
  const [input, setInput] = useState("");

  const submit = () => {
    const text = input.trim();
    if (!text) return;
    onStart(text);
    setInput("");
  };

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center justify-between px-6 pb-4 pt-6">
        <div>
          <p className="m-0 text-base font-bold text-base-content">New Session</p>
          <p className="m-0 text-xs text-base-content/60">Initialize reactor planner agent</p>
        </div>
        <span className="badge badge-outline border-base-300 bg-base-200 font-mono text-[11px] text-primary">
          SYSTEM_IDLE
        </span>
      </div>

      <div className="flex flex-1 flex-col items-center justify-center gap-8 overflow-y-auto px-6 py-10">
        <div className="rounded-full border border-primary bg-primary/10 p-3">
          <Atom size={28} className="text-primary" />
        </div>
        <div className="max-w-md space-y-2 text-center">
          <p className="m-0 text-2xl font-bold text-base-content">What would you like to work on?</p>
          <p className="m-0 text-sm text-base-content/60">
            Start a new analysis, run a simulation, or ask a question about your reactor models.
          </p>
        </div>
        <div className="grid w-full max-w-2xl grid-cols-1 gap-3 sm:grid-cols-2">
          {SUGGESTIONS.map((s) => (
            <SuggestionCard
              key={s.title}
              icon={s.icon}
              title={s.title}
              description={s.description}
              onClick={() => onStart(s.prompt)}
            />
          ))}
        </div>
      </div>

      <div className="shrink-0 px-6 pb-6 pt-2">
        <div className="flex items-center gap-3">
          <label className="input input-bordered flex flex-1 items-center gap-2 rounded-full bg-base-200">
            <Terminal size={18} className="shrink-0 text-base-content/50" />
            <input
              type="text"
              className="grow"
              placeholder="Propose a workflow or command..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") submit();
              }}
            />
          </label>
          <button
            type="button"
            className="btn btn-primary rounded-full px-6"
            onClick={submit}
            disabled={!input.trim()}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
