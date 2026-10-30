# Improve the agent card

Show the card as the orchestrator LLM reads it, find the weak fields, and rewrite them with the
user. Change card fields only; send no chat message. Every rule here comes from `card.md`: cite
the slide or `path:line` that it cites.

## 1. Read the card

1. A path in the argument is the card; its folder is the agent. Else find the agent
   ("Find your agent"). `<project>` and `<service>` as in "Find your agent".
2. `python3 -m json.tool <folder>/agent_card.json > /dev/null && echo valid`. On an error, fix
   only the syntax ("Before a write").
3. Read the card and `agent.py`: the `send_status_update`, `declare_long_running`, and
   `run_worker` calls, the `skill_id` dispatch, the `return` statements.
4. Primer: each skill is one tool for the LLM (deck 04, slides 5-6). Ask `card-interface`.

## 2. Show it as the LLM sees it

1. When `client-agent` runs, run the first command of `card.md` "See the rendering yourself" on
   the card. Else build it by hand from "What the orchestrator sees", and say so. Show each tool
   as a code block, then "The platform asks with a form for: ..." and "The LLM must fill: ...".
2. List the fields the LLM never sees (`card.md` "What the LLM never sees") with their values.
3. When the agent runs, compare the served card with the file. A difference means an old image;
   step 4 fixes it:

   ```sh
   diff <(docker compose -p <project> exec -T <service> python -c "import json, urllib.request as u; print(json.dumps([{k: s.get(k) for k in ('id', 'description', 'usage_notes', 'requires_approval', 'inputSchema')} for s in json.load(u.urlopen('http://localhost:8000/api/agent-card'))['skills']], indent=1, sort_keys=True))") <(python3 -c "import json, sys; print(json.dumps([{k: s.get(k) for k in ('id', 'description', 'usage_notes', 'requires_approval', 'inputSchema')} for s in json.load(open(sys.argv[1]))['skills']], indent=1, sort_keys=True))" <folder>/agent_card.json) && echo same
   ```

4. Collisions: the second command of "See the rendering yourself" (the live catalog). Report a
   same `routes_to` as a user skill id, and `_2` names. A route key in the registry list while
   the user's container is down belongs to someone else: rename the card.

## 3. Score and rewrite

One table per skill: rule, pass/weak/fail, evidence, source.

1. Prefixed ids: `[a-zA-Z0-9_-]`, at most 64, not `ask_user` or `workflow_*`. 2. The description
starts with a verb and its object, with what goes in and out. 3. `usage_notes` say when not, and
name the neighbour. 4. Each property has a description; `enum` for choices; units; few required.
5. `"type": "object"` on each object. 6. `x_artifact_ref` on file inputs, `x_input_source: runtime`
on produced values. 7. Streaming is true when `agent.py` sends status or runs long work. 8. The
result returns ids and names, not data; errors have `error` (advice only). 9. No template text.

Ask the check question `route-fields`. For each weak field, write 2 rewrites from the card, the
code, and `README.md`; never promise what the code cannot do. Ask one question per field (up to 4
per call): "Rewrite A (Recommended)", "Rewrite B", "Keep current". Rename an id or the card name
only on request or when rule 1 fails; then grep the folder for the old value, and say that a new
card name gives a new route key. With nothing weak, go to step 5.

## 4. Apply and deploy

1. "Before a write", then `Edit`. Check the JSON again, render again, and show each changed tool
   before and after. After an id change, run the tests.
2. Check for activity:
   `docker compose -p <project> logs --no-log-prefix --since 5m <service> 2>&1 | grep -E 'Starting .* execution|execution completed|Error during execution' | tail -3`.
   A last "Starting" line means a running call: ask before `make up`.
3. `make up` (the image holds the card). Wait for `Registered '<route key>'`, up to 5 tries. Then
   the discovery refresh: dispatch tools can stay old for 300 s otherwise. When it fails, warn
   that a client-agent restart stops running turns, then `docker compose -p prometheus_platform restart client-agent`. Compare
   again: expect `same`.

## 5. Hand off

Give three phrasings per changed skill (direct, reworded, vague), each for a fresh conversation.
Then `/diagnose trace my last chat`. Offer `/how explain how the orchestrator reads the card`.
