# Long-running and blocking work

Facts as of `prometheus_core` `devel` 2026-10-30, after #310 (`prometheus_api` 0.15, no LiteLLM). When the code disagrees with this file, the code is correct.

Your agent has one asyncio loop. A heartbeat runs on it every 15 s (`prometheus_api/prometheus_api/agent/base.py:294-307`).
A call that does not `await` (a solver, `time.sleep`, pandas, matplotlib) freezes it, and the streaming
connection can close (deck 04, slide 13 and A29).

| your work | the tool |
|---|---|
| async I/O (an LLM call, `httpx.AsyncClient`) | `await` it |
| one blocking call, no progress | `await asyncio.to_thread(fn, ...)` |
| blocking work with progress | a `PrometheusWorker` with `await self.run_worker(...)` |
| minutes to hours | `await self.declare_long_running(...)`, a worker, and `"streaming": true` |

```python
png_path = await asyncio.to_thread(render_plot, df, out_dir)  # matplotlib.figure.Figure, not pyplot

class SolveWorker(PrometheusWorker):
    def run(self):  # synchronous, on a thread
        for step in range(100):
            if self.cancelled:
                return {"status": "cancelled"}
            solve_step(step)  # TODO: your work
            self.emit_status_update(f"Step {step}/100")
        return {"status": "success"}

await self.declare_long_running(context, event_queue, estimate_seconds=1800, message="Solving; I'll report back.")
return await self.run_worker(SolveWorker(), context, event_queue)
```

- Inside `run()`, call only `emit_status_update` and `emit_json_artifact`. Do uploads and input-required in
  `_execute` (`prometheus_api/prometheus_api/agent/worker.py:109-161`).
- `declare_long_running` works only with `streaming: true`. The chat then points to `/tasks`. A client-agent
  restart stops the background task.
- Example: `prometheus_platform/agents/debug-agents/thread-pattern-agent/agent.py:57-207`.
