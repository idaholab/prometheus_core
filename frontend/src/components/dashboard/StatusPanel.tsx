import { useState } from "react";
import { Cpu, FolderOpen } from "lucide-react";

type StatusTab = "jobs" | "artifacts";

function EmptyState({ icon, title, hint }: { icon: React.ReactNode; title: string; hint: string }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 text-center">
      <div className="flex items-center justify-center rounded-2xl border border-base-300 bg-base-200 p-4 text-base-content/40">
        {icon}
      </div>
      <div className="space-y-1.5">
        <p className="m-0 font-semibold text-base-content">{title}</p>
        <p className="m-0 text-xs text-base-content/60">{hint}</p>
      </div>
    </div>
  );
}

/**
 * Right-hand status rail for dashboard-home: a DaisyUI tab bar switching
 * between Active Jobs and Artifacts. Both are empty states for now; job
 * cards and artifact cards get wired in as those data sources land.
 */
export function StatusPanel() {
  const [tab, setTab] = useState<StatusTab>("jobs");

  return (
    <div className="flex h-full flex-col">
      <div role="tablist" className="tabs tabs-border px-6 pt-6">
        <button
          role="tab"
          className={`tab text-xs font-bold uppercase tracking-wide ${tab === "jobs" ? "tab-active" : ""}`}
          onClick={() => setTab("jobs")}
        >
          Active Jobs
        </button>
        <button
          role="tab"
          className={`tab text-xs font-bold uppercase tracking-wide ${tab === "artifacts" ? "tab-active" : ""}`}
          onClick={() => setTab("artifacts")}
        >
          Artifacts
        </button>
      </div>

      {tab === "jobs" ? (
        <EmptyState
          icon={<Cpu size={32} />}
          title="No Active Jobs"
          hint="Assigned solver pipelines will display here"
        />
      ) : (
        <EmptyState
          icon={<FolderOpen size={32} />}
          title="No Artifacts Yet"
          hint="Generated artifacts will display here"
        />
      )}
    </div>
  );
}
