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

/**
 * LiveAgentPanel — the live agent rail shown in the status panel's Live Agents Arena tab.
 *
 * Reads the in-flight turn's verbatim status log from the chat store (no second SSE
 * connection) and renders it as a vertical column of agents that appear as each status
 * line names them, with A2A connectors, docked report chips, a collapsed per-sample
 * pipeline badge, and a red state for an agent that failed or could not be reached.
 * Everything is derived from the status strings by `parseAgentStream`; no wire change.
 *
 * Design rules:
 *   - Never dim the past. Every revealed agent stays lit and in color; "now" is shown
 *     by motion only (pulsing ring + streaming connector).
 *   - Collapse a per-sample loop into one xN badge, never one row per sample.
 *   - Reduced motion: static ring, no pulse/stream/spin.
 */

import { useMemo } from "react";
import { Bot } from "lucide-react";
import { useChatState, type ToolItem } from "@/lib/store/chat";
import { PLANNER, agentDef, type AgentId } from "@/lib/agentPanel/roster";
import { parseAgentStream, type AgentStatus, type FileState } from "@/lib/agentPanel/parseAgentStream";
import { api } from "@/lib/api/client";
import type { ArtifactMeta } from "@/lib/api/types";

/** Pick the status log to visualize: the in-flight tool step, else the most recent one. */
function activeHistory(items: ReturnType<typeof useChatState>["items"]): {
  history: string[];
  live: boolean;
  turnId?: string;
} {
  const tools = items.filter((it): it is ToolItem => it.kind === "tool");
  const running = tools.find((t) => !t.done);
  const chosen = running ?? tools[tools.length - 1];
  return { history: chosen?.history ?? [], live: Boolean(running), turnId: chosen?.turnId };
}

/** The newest artifact the shown turn produced, so the report chip can open it. */
function reportArtifact(items: ReturnType<typeof useChatState>["items"]): ArtifactMeta | undefined {
  for (let i = items.length - 1; i >= 0; i--) {
    const it = items[i];
    if (it.kind === "tool") break;
    if (it.kind === "assistant" && it.artifacts.length > 0) return it.artifacts[0];
  }
  return undefined;
}

export function LiveAgentPanel() {
  const { items, awaiting } = useChatState();
  const { history, live } = activeHistory(items);
  const panel = useMemo(() => parseAgentStream(history), [history]);
  const report = live ? undefined : reportArtifact(items);
  const activeName = panel.active ? agentDef(panel.active).name : null;
  const failures = panel.revealed.filter((id) => panel.status[id]?.outcome === "failed");

  return (
    <div className="flex h-full min-h-0 flex-col text-base-content">
      <style>{PANEL_CSS}</style>

      <div className="flex-1 overflow-y-auto px-6 py-4">
        {panel.revealed.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
            <div className="flex items-center justify-center rounded-2xl border border-base-300 bg-base-200 p-4 text-base-content/40">
              <Bot size={32} />
            </div>
            <div className="space-y-1.5">
              <p className="m-0 font-semibold">No Agents Yet</p>
              <p className="m-0 text-xs text-base-content/60">
                Agents appear here as the run calls them
              </p>
            </div>
          </div>
        ) : (
          <div className="lap-col">
            {panel.revealed.map((id, idx) => {
              const below = panel.revealed[idx + 1];
              const edge =
                panel.edge &&
                below &&
                ((panel.edge.from === id && panel.edge.to === below) ||
                  (panel.edge.from === below && panel.edge.to === id))
                  ? panel.edge
                  : null;
              return (
                <div key={id} className="lap-slot">
                  <AgentNode
                    id={id}
                    active={panel.active === id}
                    status={panel.status[id]}
                    files={panel.files
                      .filter((f) => f.at === id)
                      .map((f) => (report ? { ...f, artifactId: report.artifact_id } : f))}
                    loop={panel.loops[id]}
                  />
                  {below && (
                    <div
                      className={`lap-link${edge ? " live" : ""}${edge?.dir === "up" ? " up" : ""}`}
                      style={{ ["--role" as string]: agentDef(below).color }}
                    >
                      <span className="lap-dots" />
                      {edge && <span className="lap-pkt" />}
                      {edge && <span className="lap-lbl">{edge.label}</span>}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="flex items-center gap-2 border-t border-base-300 px-6 py-3 text-[11px] leading-4 text-base-content/50">
        {(live || awaiting) && <span className="lap-livedot" aria-label="run in progress" />}
        <span>
          {failures.length > 0
            ? `${failures.map((id) => agentDef(id).name).join(", ")} failed. See the agent card for the error.`
            : activeName
              ? `Now: ${activeName}.`
              : panel.complete
                ? "Turn complete."
                : "Derived from the live status log."}
        </span>
      </div>
    </div>
  );
}

function AgentNode({
  id,
  active,
  status,
  files,
  loop,
}: {
  id: AgentId;
  active: boolean;
  status?: AgentStatus;
  files: FileState[];
  loop?: { n: number; completed: number; done: boolean };
}) {
  const def = agentDef(id);
  const failed = status?.outcome === "failed";
  const pct = loop && loop.n > 0 ? Math.round((100 * loop.completed) / loop.n) : 0;
  return (
    <div
      className={`lap-agent${active ? " active" : ""}${failed ? " failed" : ""}`}
      style={{ ["--role" as string]: failed ? "#f85149" : def.color }}
    >
      <div className="lap-ico">
        <RobotGlyph color={failed ? "#f85149" : def.color} planner={id === PLANNER} />
      </div>
      <div className="lap-name">{def.name}</div>
      {def.role !== def.name && <div className="lap-role">{def.role}</div>}

      {failed && (
        <div className="lap-err" role="alert">
          <span className="lap-err-tag">{status?.unreachable ? "unreachable" : "failed"}</span>
          {status?.error && <span className="lap-err-msg" title={status.error}>{status.error}</span>}
        </div>
      )}

      {files.length > 0 && (
        <div className="lap-files">
          {files.map((f) => (
            <FileChip key={f.id} file={f} />
          ))}
        </div>
      )}

      {loop && (
        <div className={`lap-loop${loop.done ? "" : " spin"}`} title={`${loop.completed}/${loop.n} cases complete`}>
          <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden>
            <path className="arc" d="M20 12a8 8 0 1 1-2.3-5.6" fill="none" stroke="var(--role)" strokeWidth="2.2" />
            <path className="arc" d="M17.7 3.5v3h-3" fill="none" stroke="var(--role)" strokeWidth="2.2" strokeLinejoin="round" />
          </svg>
          <span className="lap-cnt">×{loop.n}</span>
          <span className="lap-prog">
            <i style={{ width: `${loop.done ? 100 : Math.max(pct, 8)}%` }} />
          </span>
        </div>
      )}
    </div>
  );
}

function FileChip({ file }: { file: FileState }) {
  const inner = (
    <>
      <svg width="22" height="26" viewBox="0 0 34 40" fill="none" aria-hidden>
        <path d="M6 3h15l7 7v27H6z" stroke="currentColor" strokeWidth="2" fill="currentColor" fillOpacity="0.08" />
        <path d="M21 3v7h7" stroke="currentColor" strokeWidth="2" />
        <line x1="11" y1="19" x2="23" y2="19" stroke="currentColor" strokeWidth="1.6" />
        <line x1="11" y1="25" x2="23" y2="25" stroke="currentColor" strokeWidth="1.6" />
      </svg>
      <span className="lap-cap">
        {file.label}
        {file.artifactId ? " ↗" : ""}
      </span>
    </>
  );
  if (file.click && file.artifactId) {
    return (
      <a
        className="lap-file click"
        href={api.artifactContentUrl(file.artifactId)}
        target="_blank"
        rel="noopener noreferrer"
        title="Open the report"
      >
        {inner}
      </a>
    );
  }
  return (
    <span className="lap-file" title={file.label}>
      {inner}
    </span>
  );
}

function RobotGlyph({ color, planner }: { color: string; planner?: boolean }) {
  return (
    <svg width="36" height="36" viewBox="0 0 48 48" fill="none" aria-hidden>
      <rect x="10" y="14" width="28" height="22" rx="6" stroke={color} strokeWidth="2.2" />
      <line x1="24" y1="6" x2="24" y2="14" stroke={color} strokeWidth="2.2" />
      <circle cx="24" cy="5" r="2.4" fill={color} />
      <circle cx="18" cy="24" r="2.6" fill={color} />
      <circle cx="30" cy="24" r="2.6" fill={color} />
      <line x1="18" y1="31" x2="30" y2="31" stroke={color} strokeWidth="2.2" strokeLinecap="round" />
      <line x1="7" y1="22" x2="7" y2="28" stroke={color} strokeWidth="2.2" strokeLinecap="round" />
      <line x1="41" y1="22" x2="41" y2="28" stroke={color} strokeWidth="2.2" strokeLinecap="round" />
      {planner && <rect x="19" y="39" width="10" height="3" rx="1.5" fill={color} />}
    </svg>
  );
}

/**
 * Scoped visuals. Tailwind can't express these keyframes (pulse ring, streaming
 * connector, spinning loop arc, chip landing), so they live here keyed off `.lap-*`
 * classes. Colors come from the per-agent `--role` custom property.
 */
const PANEL_CSS = `
.lap-col{display:flex;flex-direction:column;align-items:center;}
.lap-slot{display:flex;flex-direction:column;align-items:center;}
.lap-livedot{width:8px;height:8px;border-radius:50%;background:#2ea043;display:inline-block;flex-shrink:0;
  animation:lap-blink 1.2s ease-in-out infinite;}
@keyframes lap-blink{0%,100%{opacity:1;}50%{opacity:.25;}}

.lap-agent{display:flex;flex-direction:column;align-items:center;text-align:center;position:relative;
  padding:6px 0;max-width:220px;}
.lap-ico{width:52px;height:52px;display:flex;align-items:center;justify-content:center;border-radius:50%;
  transition:box-shadow .3s ease;}
.lap-name{font-weight:600;font-size:13px;margin-top:4px;color:var(--role);}
.lap-role{font-size:11px;opacity:.6;font-family:ui-monospace,Menlo,monospace;}

.lap-agent.active .lap-ico{animation:lap-pulse 1.4s ease-in-out infinite;}
@keyframes lap-pulse{
  0%,100%{box-shadow:0 0 0 0 color-mix(in srgb,var(--role) 55%,transparent);}
  50%{box-shadow:0 0 20px 3px color-mix(in srgb,var(--role) 55%,transparent);}
}
.lap-agent.failed .lap-ico{box-shadow:0 0 0 2px var(--role);}

.lap-err{display:flex;flex-direction:column;align-items:center;gap:2px;margin-top:5px;}
.lap-err-tag{font:700 10px ui-monospace,Menlo,monospace;text-transform:uppercase;letter-spacing:.04em;
  color:var(--role);border:1px solid var(--role);border-radius:4px;padding:0 5px;}
.lap-err-msg{font-size:10px;line-height:1.3;color:var(--role);opacity:.85;max-width:200px;
  display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;}

.lap-files{display:flex;gap:8px;justify-content:center;flex-wrap:wrap;margin-top:6px;}
.lap-file{display:flex;flex-direction:column;align-items:center;color:#ff9457;text-decoration:none;
  animation:lap-land .5s ease;}
.lap-file.click{cursor:pointer;}
.lap-file.click:hover{filter:brightness(1.15);}
.lap-cap{font-size:10px;margin-top:2px;color:#ff9457;opacity:.85;max-width:84px;}
@keyframes lap-land{0%{opacity:0;transform:translateY(-6px) scale(.9);}100%{opacity:1;transform:none;}}

.lap-loop{display:flex;align-items:center;gap:4px;margin-top:6px;}
.lap-loop .arc{transform-origin:center;}
.lap-loop.spin svg{animation:lap-spin 1.1s linear infinite;}
@keyframes lap-spin{from{transform:rotate(0);}to{transform:rotate(360deg);}}
.lap-cnt{font:700 11px ui-monospace,Menlo,monospace;color:var(--role);}
.lap-prog{display:inline-block;width:40px;height:4px;border-radius:2px;
  background:color-mix(in srgb,var(--role) 20%,transparent);overflow:hidden;}
.lap-prog i{display:block;height:100%;background:var(--role);transition:width .5s ease;}

.lap-link{position:relative;height:40px;width:2px;margin:2px 0;display:flex;align-items:center;
  justify-content:center;}
.lap-dots{position:absolute;inset:0;width:0;border-left:2px dotted color-mix(in srgb,var(--role) 45%,transparent);}
.lap-link.live .lap-dots{border-left-color:var(--role);
  background:linear-gradient(var(--role),var(--role));background-size:2px 8px;animation:lap-stream .7s linear infinite;}
.lap-link.up .lap-dots{animation-direction:reverse;}
@keyframes lap-stream{from{background-position:0 0;}to{background-position:0 8px;}}
.lap-pkt{position:absolute;width:6px;height:6px;border-radius:50%;background:var(--role);
  box-shadow:0 0 8px 1px var(--role);animation:lap-travel 1.1s ease-in-out infinite;}
.lap-link.up .lap-pkt{animation-direction:reverse;}
@keyframes lap-travel{0%{top:2px;}100%{top:32px;}}
.lap-lbl{position:absolute;left:10px;white-space:nowrap;font-size:10px;color:var(--role);
  font-family:ui-monospace,Menlo,monospace;opacity:.85;}

@media (prefers-reduced-motion: reduce){
  .lap-agent.active .lap-ico{animation:none;box-shadow:0 0 0 2px var(--role);}
  .lap-loop.spin svg{animation:none;}
  .lap-link.live .lap-dots{animation:none;}
  .lap-pkt{animation:none;top:16px;}
  .lap-file{animation:none;}
  .lap-livedot{animation:none;}
}
`;
