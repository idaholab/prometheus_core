# The agent card

Facts as of `prometheus_core` `devel` 2026-10-30, after #310 (`prometheus_api` 0.15, no LiteLLM). When the code disagrees with this file, the code is correct.

Short paths: `base.py` and `registry.py` are in `prometheus_api/prometheus_api/agent/`; `orchestrator/...`,
`capability_cache.py`, `tool_discovery.py`, `artifact_handling.py`, and `param_schema.py` are in
`prometheus_platform/agents/client-agent/`.

The orchestrator LLM decides from the card alone whether to call your agent, and with which arguments
(deck 04, slide 5). Each skill becomes one tool (deck 04, slide 6).

## The fields

| field | the LLM sees it | notes |
|---|---|---|
| `name` (agent) | no | gives the route key |
| `description`, `version` (agent) | no | for people and the A2A card |
| `capabilities.streaming` | no | `true`: streaming call; status lines show live, `declare_long_running` works (`orchestrator/skills.py:98-116`). Template: `false` (deck 04, slide 11) |
| `skills[].id` | yes, as the tool name | arrives as `params["skill_id"]` |
| `skills[].name` | only when `description` is empty | the plan card label |
| `skills[].description`, `usage_notes` | yes | the tool description |
| `skills[].requires_approval` | yes, one line | Approve/Reject before the call |
| `skills[].inputSchema` | yes, cleaned | the parameters, the forms, the checks |
| `expected_duration_seconds`, `output_format`, `examples`, `tags` | no | the call timeout stays 900 s (`tool_discovery.py:515`) |

Sources: `capability_cache.py:250-271`; deck 04, A10-A11. Never put a `url` in the file (`base.py:1259`).
`tags` and `examples` must be lists of strings (`base.py:1319-1326`). The client-agent reads
`GET /api/agent-card`, not the registry copy (`tool_discovery.py:122-128`). The image holds the card.

## Naming rules

1. **The route key** is the card `name` in lowercase, each space changed to a hyphen: "Neutron Table Plot
   Agent" gives `neutron-table-plot-agent` (`registry.py:51-53`). The scaffolder appends " Agent".
2. **The route key is unique.** At registration the agent deletes an entry with the same key
   (`registry.py:123-130`). Two teams with the same name delete each other.
3. **The skill id is the tool name.** Use `[a-zA-Z0-9_-]`, at most 64 characters (deck 04, A4;
   `orchestrator/agent_loop.py:165-167`).
4. **The skill id is unique on the platform.** A call routes by the raw id to the first agent that has it
   (`orchestrator/skills.py:16-28`). A duplicate shows as `x_2`, but both calls reach the same agent.
5. **Prefix with your team name**, in the card name and every skill id (deck 04, slide 4).
6. **Reserved:** never `ask_user` (it becomes `ask_user_2`, `agent_loop.py:310-313`), never `workflow_*`.

## Five rules for a card that works

From deck 04, slide 7 and A13.

1. **Verb and object first:** "Find one table in an uploaded markdown document", not "Table tool".
2. **Say when not to use it** in `usage_notes`, and name the neighbour skill to prefer.
3. **Describe every parameter; require few.** `enum` for fixed choices, units in the description. File
   inputs get `"x_artifact_ref": "single"`; values from another skill get `"x_input_source": "runtime"`.
4. **Return what the next step needs:** the `artifact_id`, the caption, the exact column names.
5. **Test three phrasings,** each in a fresh conversation. Fix the card, not the prompt.

## What the orchestrator sees

The tool list is rebuilt each turn from the capability cache, which refreshes every 60 s
(`agent_loop.py:307-324`, `capability_cache.py:96`): `ask_user`, one tool per skill, one `workflow_*` tool per
workflow.

- **Name:** the skill id, with each run outside `[A-Za-z0-9_-]` changed to `_`, cut to 64. A taken name
  gets `_2` (`agent_loop.py:165-177`). The call still goes to the raw id.
- **Description** (`agent_loop.py:236-240`): the skill `description` (else `name`), then
  `Usage: <usage_notes>`, then `Requires user approval before it runs.` when set.

### The tool parameters

From `agent_loop.py:180-221` and `artifact_handling.py:6-103`:

1. Copy the `inputSchema`. Mark each property with `x_artifact_ref` as an artifact field, and append
   "artifact_id of an existing conversation artifact." to its description.
2. Remove every `x_*` and `x-*` key, and the top-level `artifacts` and `conversation_id` properties.
3. Keep `required` names that still exist. Standard keywords (`title`, `enum`, `default`) stay.

Write `"type": "object"` at the top and on each nested object. Without it the platform finds no artifact
or required fields, and shows no form (`artifact_handling.py:90`, `param_schema.py:82`).

| case (`agent_loop.py:542-648`) | what happens |
|---|---|
| a required user field left empty | a form (`needs_info`); `title` is the label, `enum` a dropdown |
| a required artifact or `runtime` field left empty | no call; the LLM gets "Missing required input(s) ..." |
| an argument that breaks the schema | no call; "Invalid arguments: ..." |
| an unknown artifact id | no call; "Unknown artifact_id ..." |
| `requires_approval: true` | Approve/Reject (`plan_ready`) for that call |

### What the LLM never sees

The agent `name`, `description`, and `version`; the skill `name`; `tags`, `examples`, `output_format`,
`expected_duration_seconds`; `capabilities.streaming`; every `x_*` key. A routing hint there is lost.

### Your result, as the LLM sees it

`_compact_result` (`agent_loop.py:793-811`): `status` (`succeeded`, or `failed` with `error`), the
`artifacts` you produced, a `summary` (the first of `answer`, `response`, `report`, `message`, `result`,
`raw_response`, cut to 2000 characters), and `result`, your whole dict cut to 6000 characters.

### See the rendering yourself

Render your card file with the platform's own code (prints no secret):

```sh
docker compose -p prometheus_platform exec -T client-agent python -c "
import json, sys
from capability_cache import AgentCapability
from orchestrator import agent_loop as al
card = json.load(sys.stdin)
specs = {al.ASK_USER_TOOL: al.ASK_USER_SPEC}
for s in card.get('skills', []):
    c = AgentCapability(agent_id='', agent_name=card.get('name', ''), agent_url='', skill_id=s['id'], skill_name=s.get('name', s['id']), description=s.get('description', ''), usage_notes=s.get('usage_notes'), input_schema=s.get('inputSchema', {}), requires_approval=s.get('requires_approval', False), expected_duration_seconds=s.get('expected_duration_seconds'))
    n = al._unique_tool_name(al._tool_name(c.skill_id), specs)
    specs[n] = t = al._skill_spec(n, c)
    print(json.dumps({'name': n, 'routes_to': t.target, 'description': t.description, 'parameters': t.parameters}, indent=2))
    print('form asks for:', list(t.user_required), '| the LLM must fill:', list(t.runtime_required))
" < <agent folder>/agent_card.json
```

Render every skill tool of the last discovery (the live catalog):

```sh
docker compose -p prometheus_platform exec -T client-agent python -c "
import json
from prometheus_api.redis_utils import create_redis_client
from capability_cache import AgentCapability
from orchestrator import agent_loop as al
raw = create_redis_client(ping=False).get('capability_cache:v4:capabilities') or '[]'
specs = {al.ASK_USER_TOOL: al.ASK_USER_SPEC}
owner = {al.ASK_USER_TOOL: 'orchestrator'}
for c in (AgentCapability.from_dict(d) for d in json.loads(raw)):
    n = al._unique_tool_name(al._tool_name(c.skill_id), specs)
    specs[n] = al._skill_spec(n, c)
    owner[n] = c.agent_id
for n, t in specs.items():
    print(n, '->', t.target, '@', owner[n], '|', t.description.replace(chr(10), ' / ')[:200], '| params:', sorted(t.parameters.get('properties', {})), '| required:', t.parameters.get('required', []))
"
```

## After you change the card

1. Run `make up` in the agent folder.
2. Run the discovery refresh (`conventions.md`, "Safe fixes"). Without it, the dispatch tools can stay old
   for up to 300 s (`orchestrator/runtime.py:21`).
3. Test three phrasings, each in a fresh conversation (deck 04, slide 18), then run
   `/diagnose trace my last chat`.
