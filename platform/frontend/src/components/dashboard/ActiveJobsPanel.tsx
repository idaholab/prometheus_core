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
  recordStatusHistory,
  toJobRows,
} from "@/lib/jobs/activeJobs";

/** How often the tab re-reads the Task Graph while it is open. */
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
        {job.links.length > 0 && (
          <ul className="m-0 max-h-48 list-none space-y-1 overflow-y-auto p-0 pt-0.5">
            {job.links.map((link) => (
              <li key={link.url} className="flex items-center gap-2">
                <a
                  href={link.url}
                  target="_blank"
                  rel="noreferrer"
                  className="link link-primary inline-flex items-center gap-1 text-xs"
                >
                  {link.label}
                  <ExternalLink size={11} aria-hidden />
                </a>
                {link.state && (
                  <span
                    className={`badge badge-xs ${link.state === "failed" ? "badge-error" : "badge-ghost"}`}
                  >
                    {link.state}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/**
 * The status panel's Active Jobs tab: every specialist dispatch of the open
 * conversation (from the backend's Task Graph), running ones first, with links to
 * any solver pipeline they reported (e.g. a GitLab pipeline URL in a status update).
 * Polls while mounted; the Task Graph keeps finished tasks for about a day.
 */
export function ActiveJobsPanel() {
  const { conversationId } = useChatState();
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [available, setAvailable] = useState(true);
  const history = useRef(new Map<string, string[]>());

  useEffect(() => {
    history.current = new Map();
    setJobs([]);
    if (!conversationId) return;
    let cancelled = false;
    const load = async () => {
      try {
        const res = await api.getConversationTasks(conversationId);
        if (cancelled) return;
        setAvailable(res.available);
        recordStatusHistory(res.tasks, history.current);
        const rows = toJobRows(res.tasks, history.current);
        setJobs([
          ...rows.filter((r) => r.running),
          ...rows.filter((r) => !r.running),
        ]);
      } catch {
        /* a transient error keeps the last list; the next poll retries */
      }
    };
    void load();
    const timer = window.setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [conversationId]);

  if (jobs.length === 0) {
    return (
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
    );
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-6 py-4">
      {jobs.map((job) => (
        <JobCard key={job.taskId} job={job} />
      ))}
    </div>
  );
}
