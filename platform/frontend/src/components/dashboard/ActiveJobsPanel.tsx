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

import { useEffect, useRef, useState } from "react";
import { Cpu, ExternalLink } from "lucide-react";
import { api } from "@/lib/api/client";
import { useChatState } from "@/lib/store/chat";
import {
  type JobRow,
  historyFor,
  recordStatusHistory,
  toJobRows,
} from "@/lib/jobs/activeJobs";

/** How often the tab re-reads the Task Graph while something is running. */
const POLL_MS = 3000;

const STATE_BADGE: Record<string, string> = {
  working: "badge-info",
  submitted: "badge-ghost",
  "input-required": "badge-warning",
  completed: "badge-success",
  failed: "badge-error",
  canceled: "badge-ghost",
  rejected: "badge-error",
};

function JobBody({ job }: { job: JobRow }) {
  return (
    <>
      <div className="flex items-start justify-between gap-2">
        <span className="min-w-0 truncate font-mono text-sm font-semibold text-base-content">
          {job.name}
        </span>
        <span
          className={`badge badge-sm shrink-0 ${STATE_BADGE[job.state] ?? "badge-ghost"}`}
        >
          {job.running && (
            <span
              className="loading loading-spinner loading-xs mr-1"
              aria-hidden
            />
          )}
          {job.state}
        </span>
      </div>
      {job.turnTitle && job.turnTitle !== job.name && (
        <p className="m-0 line-clamp-1 text-[11px] text-base-content/50">
          {job.turnTitle}
        </p>
      )}
      {(job.error || job.message) && (
        <p
          className={`m-0 line-clamp-3 text-xs leading-snug ${job.error ? "text-error" : "text-base-content/70"}`}
        >
          {job.error || job.message}
        </p>
      )}
    </>
  );
}

/**
 * One dispatch. With a single link (the usual one pipeline per job) the whole card
 * opens it, so a click lands on the GitLab pipeline page with its job graph and
 * failing job. With several (a UQ run starts one pipeline per sample) the card lists
 * them, failed ones first.
 */
function JobCard({ job }: { job: JobRow }) {
  const cardClass = "card border border-base-300 bg-base-200";
  if (job.links.length === 1) {
    const link = job.links[0];
    return (
      <a
        href={link.url}
        target="_blank"
        rel="noreferrer"
        title={`Open ${link.label}`}
        className={`${cardClass} transition-colors hover:border-primary/40 hover:bg-base-300`}
      >
        <div className="card-body gap-1.5 p-3">
          <JobBody job={job} />
          <span className="inline-flex items-center gap-1 pt-0.5 text-xs text-primary">
            {link.label}
            <ExternalLink size={11} aria-hidden />
          </span>
        </div>
      </a>
    );
  }
  return (
    <div className={cardClass}>
      <div className="card-body gap-1.5 p-3">
        <JobBody job={job} />
        {job.links.length > 0 && <PipelinePicker job={job} />}
      </div>
    </div>
  );
}

/**
 * A job with several pipelines (a UQ run starts one per sample): pick one from the
 * list, failed ones first, then open it in GitLab to investigate. The first entry is
 * selected by default, so the usual case (open the one that failed) is one click.
 */
export function PipelinePicker({ job }: { job: JobRow }) {
  const [selectedUrl, setSelectedUrl] = useState(job.links[0].url);
  // A newly reported pipeline can reorder the list; keep the choice if it still exists.
  const link = job.links.find((l) => l.url === selectedUrl) ?? job.links[0];
  const failed = job.links.filter((l) => l.state === "failed").length;
  const id = `pipelines-${job.taskId}`;
  return (
    <div className="flex flex-col gap-1.5 pt-0.5">
      <label htmlFor={id} className="text-[11px] text-base-content/60">
        {job.links.length} pipelines{failed > 0 ? `, ${failed} failed` : ""}
      </label>
      <div className="flex items-center gap-2">
        <select
          id={id}
          className="select select-bordered select-xs min-w-0 flex-1"
          value={link.url}
          onChange={(e) => setSelectedUrl(e.target.value)}
        >
          {job.links.map((l) => (
            <option key={l.url} value={l.url}>
              {l.label}
              {l.state ? ` (${l.state})` : ""}
            </option>
          ))}
        </select>
        <a
          href={link.url}
          target="_blank"
          rel="noreferrer"
          title={`Open ${link.label} in GitLab`}
          className={`btn btn-xs shrink-0 ${link.state === "failed" ? "btn-error" : "btn-primary"}`}
        >
          Open in GitLab
          <ExternalLink size={11} aria-hidden />
        </a>
      </div>
    </div>
  );
}

/** Rows for the tab: running dispatches first, each group in Task Graph order. */
function sortRows(rows: JobRow[]): JobRow[] {
  return [...rows.filter((r) => r.running), ...rows.filter((r) => !r.running)];
}

/**
 * The status panel's Active Jobs tab: every specialist dispatch of the open
 * conversation (from the backend's Task Graph), running ones first, with links to
 * any solver pipeline they reported (a GitLab pipeline URL in a status update).
 *
 * Polling: every POLL_MS while a turn is in flight or any job is still running;
 * a tick is skipped while the previous read is in flight or the browser tab is
 * hidden (and runs as soon as it is visible again). Once nothing is running and no
 * turn is awaited, polling stops; the next turn starts it again. A failed read
 * keeps the last list and shows an error line. The status history that keeps early
 * pipeline links lives per conversation outside this component (`historyFor`), so
 * switching tabs does not lose it. The Task Graph keeps finished tasks for about a day.
 */
export function ActiveJobsPanel() {
  const { conversationId, awaiting } = useChatState();
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [available, setAvailable] = useState(true);
  const [failed, setFailed] = useState(false);
  // Read inside the poll without restarting it (which would clear the list).
  const awaitingRef = useRef(awaiting);
  awaitingRef.current = awaiting;
  // Restarts a stopped poll; set by the effect below for the open conversation.
  const kick = useRef<() => void>(() => {});

  useEffect(() => {
    setJobs([]);
    setFailed(false);
    if (!conversationId) return;
    const history = historyFor(conversationId);
    let cancelled = false;
    let inFlight = false;
    let timer: number | undefined;
    let polling = true;

    const schedule = (keepGoing: boolean) => {
      polling = !cancelled && keepGoing;
      if (polling) timer = window.setTimeout(tick, POLL_MS);
    };
    const load = async (): Promise<boolean> => {
      inFlight = true;
      try {
        const res = await api.getConversationTasks(conversationId);
        if (cancelled) return false;
        setAvailable(res.available);
        setFailed(false);
        recordStatusHistory(res.tasks, history);
        const rows = toJobRows(res.tasks, history);
        setJobs(sortRows(rows));
        return awaitingRef.current || rows.some((r) => r.running);
      } catch {
        if (cancelled) return false;
        setFailed(true); // keep the last list; retry on the next tick
        return true;
      } finally {
        inFlight = false;
      }
    };
    async function tick() {
      timer = undefined;
      if (inFlight || document.hidden) return schedule(true);
      schedule(await load());
    }
    const onVisible = () => {
      if (!document.hidden && timer !== undefined && !inFlight) {
        window.clearTimeout(timer);
        void tick();
      }
    };

    kick.current = () => {
      if (cancelled || polling) return;
      polling = true;
      void tick();
    };

    void load().then(schedule);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      kick.current = () => {};
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [conversationId]);

  // A new turn on this conversation may dispatch new jobs: resume a stopped poll.
  useEffect(() => {
    if (awaiting) kick.current();
  }, [awaiting]);

  const errorLine = failed && (
    <p role="status" className="m-0 px-6 pt-3 text-xs text-error">
      Could not refresh jobs; retrying.
    </p>
  );

  if (jobs.length === 0) {
    return (
      <div className="flex flex-1 flex-col">
        {errorLine}
        <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 text-center">
          <div className="flex items-center justify-center rounded-2xl border border-base-300 bg-base-200 p-4 text-base-content/40">
            <Cpu size={32} />
          </div>
          <div className="space-y-1.5">
            <p className="m-0 font-semibold text-base-content">No Active Jobs</p>
            <p className="m-0 text-xs text-base-content/60">
              {available
                ? "Assigned solver pipelines will display here"
                : "Task status is unavailable right now"}
            </p>
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {errorLine}
      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-6 py-4">
        {jobs.map((job) => (
          <JobCard key={job.taskId} job={job} />
        ))}
      </div>
    </div>
  );
}
