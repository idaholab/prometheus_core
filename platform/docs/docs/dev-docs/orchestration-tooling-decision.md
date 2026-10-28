# Orchestration Tooling — Homegrown vs. Prefect/Airflow

!!! warning "Superseded by the ADK runtime ADR (2026-10)"
    The "keep the homegrown stack" decision below no longer applies. Agents and the
    client-agent orchestrator now run on Google ADK through `prometheus_api.adk`. The
    hand-written loop and `workflow_library/executor.py` are removed, and workflow templates
    compile to ADK graphs with `to_adk_workflow`. The decision record is the ADR draft
    `specs/adk-runtime/adr-adk-runtime.md` in the Genesis control repository, which goes to the
    Prometheus Confluence space. The current design is in
    [Client-Agent Orchestration as a Tool-Calling Loop](agent-loop-orchestration.md). The
    rationale below stays as history.

**Date:** 2026-06-11
**Scope:** Review question: should `task_graph.py` / `workflow_library/` be replaced by an off-the-shelf orchestrator?

---

## Decision

Keep the homegrown stack. Revisit only on the triggers below, and then only for workloads *above* the A2A boundary.

## Rationale

1. **`task_graph.py` is not a workflow engine.** It is conversation-scoped A2A task-state tracking with percolation into the chat UI (`/tasks`, notifications). No orchestrator provides this; we would write it either way. The actual comparison target is `workflow_library/executor.py` (~260 lines).

2. **These are running conversations with agents.** Intermediate user input percolates through A2A: `input_required` → Chainlit form → resume the *same* A2A task. An orchestrator would have to own exactly the boundary this path runs through. Neither Prefect nor Airflow saves us anything here.

3. **Workflows are LLM-planned per request and executed once, interactively.** Airflow's scheduled, pre-declared DAG model is the wrong shape outright (scheduler dispatch latency alone disqualifies it for a chat turn). Prefect tolerates dynamic flows, but its pause/resume routes input through the Prefect server API — a second, parallel task lifecycle next to A2A.

4. **Step transitions are now LLM-mediated** (`orchestrator/step_transition.py`): dataflow between chain steps is decided at runtime from upstream result text and artifact metadata. Neither tool has a primitive for this. The more orchestration becomes LLM-driven, the thinner the slice an engine could own.

5. **The bespoke surface is ~2,200 tested lines.** Owning it is a bounded cost; adopting an orchestrator is a permanent operational and conceptual coupling for every agent author. Two real gaps to close in-tree instead: per-step retries in the executor, and Redis checkpoints of executor loop state so runs survive a client-agent restart.

## When to revisit

1. **Scheduled / recurring / event-triggered workloads** (nightly re-analysis, data-arrival triggers). This is the carve-out: run Prefect (self-hosted) *beside* the platform as just another A2A client, the way Chainlit is. No specialist agent learns Prefect exists. Not a trigger: "notify me when done" — that is `task_graph` background tasks.

2. **Durability stops being optional** — multi-hour runs, restarts mid-run reported as bugs. Checkpointing first; the moment we are implementing replay semantics or idempotency keys, that is Temporal territory (noting its determinism constraints wrap every LLM/agent call in activity ceremony).

3. **Fleet-level ops** — cross-conversation run views, retention beyond the 24 h TTL, global per-agent rate limits. Exhaust LiteLLM rate limiting and a global Redis index before reaching for Prefect's server UI.

4. **Executor feature creep** — work queues, priorities, step-result caching, re-run-from-step. Any one is fine; three together means we are rebuilding Prefect without its test matrix. Then port the *template* executor only (compiled YAML → flow); ad-hoc LLM chains and `task_graph` stay homegrown regardless, per (2).
