# Trace a chat turn

Rebuild one chat turn from Valkey, then the logs, and explain the orchestrator's choices. Run
each command as written; replace only `<...>`. `client-agent/` means
`prometheus_platform/agents/client-agent/`. Read Valkey only through `docker compose -p prometheus_platform exec -T redis
sh -c '...'` (the container's own password) and through the filters below, which cut and redact.
Never repeat a value that looks like a key.

## 1. Set up

Read `card.md` ("What the orchestrator sees"). No agent is fine. Run
`docker compose -p prometheus_platform ps --services | grep -x -e redis -e client-agent -e backend`;
without `redis` or `client-agent`, go on with `fix-problem.md`. Primer: the LLM sees the
conversation, the artifact catalog, and each skill and workflow as a tool; it calls, reads, and
decides again, for at most 12 steps; the turn ends in one status (deck 01, A9-A11).

## 2. Find the conversation

Use a conversation id from the argument. Otherwise list the recent ones (the list command):

```sh
docker compose -p prometheus_platform exec -T redis sh -c 'for k in $(valkey-cli --no-auth-warning -a "$REDIS_PASSWORD" --scan --pattern "agent:status_history:*"); do printf "%s\t" "${k#agent:status_history:}"; valkey-cli --no-auth-warning -a "$REDIS_PASSWORD" --raw LINDEX "$k" -1; done' | python3 -c '
import json, sys
rows = []
for line in sys.stdin:
    cid, _, raw = line.rstrip("\n").partition("\t")
    try: e = json.loads(raw)
    except ValueError: continue
    rows.append((str(e.get("timestamp") or e.get("state_turn_started_at") or ""), cid, str(e.get("message") or e.get("title") or "")[:70]))
for ts, cid, msg in sorted(rows, reverse=True)[:10]: print(ts[:19].replace("T", " "), "UTC |", cid, "|", msg)'
```

One row: use it. More: ask (header `Turn`) with the 4 newest. None: the history expires after 15
minutes (`client-agent/orchestrator/runtime.py:149-159`). Offer a fresh retry, or the document only
(`conversation:` as pattern and prefix, `GET` for `LINDEX`; no expiry, epoch time; skip step 3).

## 3. Read the status history

```sh
docker compose -p prometheus_platform exec -T redis sh -c 'valkey-cli --no-auth-warning -a "$REDIS_PASSWORD" --raw LRANGE "agent:status_history:$1" 0 -1' sh '<conversation_id>' | python3 -c '
import json, re, sys
S = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_.-]+|Bearer\s+\S+)")
for n, line in enumerate(sys.stdin, 1):
    try: e = json.loads(line)
    except ValueError: continue
    print("%3d %s %s %s" % (n, str(e.get("timestamp", ""))[11:19], "FINAL" if e.get("final") else "     ", S.sub("<redacted>", str(e.get("message", "")))[:300]))'
```

The last 300 entries, UTC (`runtime.py:139-161`). A turn starts at "Processing orchestration request.".

| entry | meaning (`client-agent/orchestrator/`) |
|---|---|
| `Next step: '<target>'.` | a call passed the checks: a skill id, a workflow id, or `ask_user` (`agent_loop.py:1301-1303`) |
| `Invoking '<skill_id>'.` | the call to the agent starts (`skills.py:70`) |
| `Capability '<skill_id>' is currently unavailable.` / `Missing required parameters for '<skill_id>': ...` | no dispatch tool, also after a refresh / a required field is empty: no call (`skills.py:72-131`) |
| `[<skill_id>] <text>` / `[<skill_id>] running in the background.` | a status line / `declare_long_running` (`skills.py:100-113`) |
| `'<skill_id>' completed.` / `'<skill_id>' failed: <error>` | a result without `error` / the wrapper raised (`skills.py:160-168`) |

"Invoking" with no "completed" or "failed" after it: the agent asked for input, or returned an
A2A error or crashed, which writes no status line (`client-agent/tool_discovery.py:631-643`). A
call rejected before the dispatch has no "Next step": its error is only in the document (step 4).

## 4. Read the conversation document

```sh
docker compose -p prometheus_platform exec -T redis sh -c 'valkey-cli --no-auth-warning -a "$REDIS_PASSWORD" --raw GET "conversation:$1"' sh '<conversation_id>' | python3 -c '
import json, re, sys
S = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_.-]+|Bearer\s+\S+)")
def cut(v, n):
    t = S.sub("<redacted>", v if isinstance(v, str) else json.dumps(v, default=str))
    return t if len(t) <= n else t[:n] + " ...[cut]"
doc = json.loads(sys.stdin.read().strip() or sys.exit("No conversation document for this id.")); print("TITLE:", cut(doc.get("title") or "", 80))
for m in doc.get("llm_messages") or []:
    r = m.get("role")
    if r == "user": print("\nUSER:", cut(m.get("content") or "", 400))
    elif r == "assistant":
        if m.get("content"): print("MODEL TEXT:", cut(m["content"], 800))
        for c in m.get("tool_calls") or []:
            f = c.get("function") or {}; print("CALL", str(c.get("id"))[-6:], f.get("name"), cut(f.get("arguments") or "", 1500))
    elif r == "tool": print("RESULT", str(m.get("tool_call_id"))[-6:], cut(m.get("content") or "", 1500))
h = [e for e in doc.get("conversation_history") or [] if isinstance(e, dict)]; last = h[-1] if h else {}; print("\nLAST HISTORY ENTRY:", last.get("role"), last.get("type") or "-", str(last.get("timestamp", ""))[:19])
for k in ("tool_inputs", "tool_results"):
    for name, v in (last.get(k) or {}).items(): print(k.upper(), name, cut(v, 1500))
print("PENDING FORM:", doc.get("missing_info") or "-", "| AWAITING APPROVAL:", bool(doc.get("awaiting_approval")))'
```

`llm_messages` is the transcript that the LLM replays. A `CALL` holds the exact arguments; its
`RESULT` (same last 6 id characters) is `succeeded` or `failed` with `error`. The last history
entry holds `tool_inputs` and `tool_results` (`orchestrator/chat_flow.py:157-168`).

## 5. Read the logs

`<n>` = the minutes since the turn plus 2. The client-agent logs no status lines (deck 04, slide 19 is wrong):

```sh
docker compose -p prometheus_platform logs --no-log-prefix --since <n>m client-agent 2>&1 | grep -E "Cached capability|Capability cache refreshed|Tool call .* failed|Request failed for conversation|Traceback|Error" | tail -40
docker compose -p prometheus_platform logs --no-log-prefix --since <n>m backend 2>&1 | grep -E "A2A proxy to|Registered agent|Removed agent registration" | tail -20
docker compose -p <project> logs --no-log-prefix --since <n>m <service> 2>&1 | grep -E "Starting .* execution|Extracted parameter keys|execution completed successfully|Error during execution|Identity verification failed" | tail -30
```

The gateway line shows the route key (format not confirmed yet). "Extracted parameter keys" lists
keys only (`base.py:479`); `skill_id`, `user_id`, `conversation_id`, `artifacts` come from the
platform. A crash: `docker compose -p <project> logs --no-log-prefix --since <n>m <service> 2>&1 | grep -A 20 "Error during execution" | tail -40`.

## 6. Rebuild and explain the turn

1. Write a numbered timeline by time and call id: per LLM step, what it saw, the calls, what the
   platform and the agent did. End with the last `MODEL TEXT`, cut to 3 lines.
2. Name the end state (`prometheus_platform/backend/app/contract.py:35-48`; `chat_flow.py:112-193`):

   | final entry | history type | status |
   |---|---|---|
   | `Response ready.` | `final_report` (at least one dispatch) / `answer` | `completed` / `answer` |
   | `Plan rejected by user.`, `Handled /<cmd> slash command.` | `plan_rejected` / - | `answer` |
   | `Awaiting additional information.` | `followup_questions` | `needs_info` |
   | `Plan ready for approval.` | `plan` | `plan_ready` |
   | `Task is now running in the background.` | - | `backgrounded` (later "Background task complete." or "…failed") |
   | other, for example `Request failed: ...`, `Stopped after 12 orchestration steps ...` | `error` or none | `error` |

3. Render the tools the LLM had (`card.md` "See the rendering yourself"; `workflows.md`), plus
   `ask_user`, and compare them with the prompt. The system prompt answers chat directly, prefers
   a `workflow_*`, and never invents a required value (`client-agent/prompts/orchestrator_system.txt:9-15`).
4. Name the cause:

   | evidence | cause | next |
   |---|---|---|
   | no `Next step`, end state `answer` | no tool fit, or the message looked conversational | improve the card (`/create-agent`) |
   | `Next step` names another agent's skill | another description fits better | name the neighbour in `usage_notes` |
   | a `RESULT` with "Invalid arguments", "Unknown artifact_id", "Missing required input(s)"; or wrong but accepted arguments | rejected before the dispatch; weak parameter descriptions; the previous result lacked a value | parameter descriptions, `x_artifact_ref`, `x_input_source`; the previous result |
   | `Capability '<id>' is currently unavailable.` | not discovered | `discovery-refresh`; after a platform restart, `docker compose -p <project> restart <service>` |
   | end state `needs_info` | a required field, `ask_user`, or the agent's own input request | expected; or fewer required fields |
   | `Invoking`, then `failed`; or `Request failed: ...` | an error dict or a crash; the orchestrator's own LLM call failed | `fix-problem.md` |
5. For argument values, offer `logger.info("params: %s", params)` in `_execute` (a yes, then
   `make up`; the SDK logs keys only, REQ-009-03; remove it before a commit). Ask `chat-turn`.
