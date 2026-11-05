---
title: Live demo reference
footer: One day · Live demo reference · https://idaholab.github.io/prometheus_core/hackathon/one-day
accent: dep
index:
  time: '9:30'
  heading: Live demo reference
  color: var(--sky)
  blurb: 'The patterns shown in the live demo, in the order shown: start the platform and try the debug agents, scaffold an agent, add a skill, call an LLM, read and publish artifacts, give the LLM a tool. Generic code with placeholders, and one watch-out each.'
---

# Live demo reference {.title kicker="Agent developer hackathon · One day · 9:30 am" pills="Reference | 6 patterns | Keep it open while you build"}
The patterns from the live demo, in the order they appear.
Note: This deck is a reference to keep open, not a script to present. The presenter builds an agent live; these slides carry the generic version of each step.

---

## Start the platform and try the debug agents {eyebrow="Step 1 of 6 · setup block"}

:::: cols 1.2fr 1fr gap=28px
```bash {.sm}
cd prometheus_core/platform
make up
#  asks: local SDK? local DeepLynx?
#  asks: LLM profile and your API key

# chat:  http://localhost:5150
# DeepLynx:  http://localhost:3000

# switch the debug agents on
make down
echo "DEBUG_AGENTS=true" >> .env
make up
```
|||
- Answer yes to **local SDK** and **local DeepLynx**. `make up` then builds the SDK image and starts DeepLynx for you.
- Create the admin account the first time you open the chat.
- Type `/agents` in the chat to list every registered agent.
- Try a debug agent so you can see routing and artifacts before you write any code.

::: callout warn
**Every platform `make up` empties the agent registry.** Restart your own agent afterwards.
:::
::::

---

## Scaffold an agent {eyebrow="Step 2 of 6 · setup block"}

:::: cols 1.2fr 1fr gap=28px
```bash {.sm}
cd prometheus_core/agent-template
python setup_agent.py
#  name, description, slug,
#  class name, first skill id

cd ../../<your-agent>
uv sync
uv add <package>

make up        # build and start
make logs      # look for "Registered ..."
```
|||
- `setup_agent.py` copies the template into a folder of your own and copies the keys from the platform's `.env`.
- The folder holds `agent.py` (the class), `agent_card.json` (what the orchestrator reads), `tests/`, and the `Dockerfile`.
- The agent should appear under `/agents` after a minute.

::: callout warn
**The template's tests break** once `_execute` reads `params["skill_id"]`. The image build also **fails without a current `uv.lock`**: run `uv add` for every new package.
:::
::::

---

## Add a skill {eyebrow="Step 3 of 6 · checkpoint 1"}

:::: cols 1.2fr 1fr gap=28px
```json {.xs}
{ "id": "<skill_id>",
  "name": "<Skill name>",
  "description": "What it does, and when to use it.",
  "usage_notes": "When to use it rather than another skill.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "<param>": { "type": "string",
                   "description": "What this is." } },
    "required": ["<param>"] } }
```

```python {.xs}
skill_router = {"<skill_id>": self._handle_<name>}
handler = skill_router.get(params["skill_id"])
if handler is None:
    return {"status": "error", "message": "Unknown skill"}
return await handler(params, context, event_queue)
```
|||
- The orchestrator chooses a skill from its **card**, not from your Python. A clear `description` and `usage_notes` are what get you called.
- Return a plain dict. The base class turns it into the final result.
- Fill in `<param>` values from `params`.

::: callout warn
**Rebuild after every change** with `make up`, wait about a minute for the card to refresh, and test in a **fresh chat**.
:::
::::

---

## Call an LLM {eyebrow="Step 4 of 6 · checkpoint 3"}

:::: cols 1.2fr 1fr gap=28px
```python {.sm}
messages = [{"role": "user", "content": "<prompt>"}]

async with self.llm_client(context) as llm:
    r = await llm.medium(messages)

answer = r.text.strip()

# check it in Python before you use it
```
|||
- A prompt is a list of messages, each a dict with a `role` and `content`.
- Ask for a **flavor**: `small`, `medium`, `large` or `vision`. The platform's `LLM_CONFIG_PROFILE` decides which model that means.
- No keys or model names in your code. They come from the environment.
- Ask for an answer you can check: JSON, a number, or a fixed word such as `NO_MATCH` for "nothing fits".

::: callout warn
**Never trust the reply as-is.** Models add commentary or wrap answers in code fences. Parse the answer, validate it, and return an error if it is not what you asked for.
:::
::::

---

## Read and publish artifacts {eyebrow="Step 5 of 6 · checkpoint 2"}

:::: cols 1fr 1fr gap=24px
::: col
### Artifact in
```json {.xs}
"<param>": { "type": "string",
             "x_artifact_ref": "single" }
```

```python {.xs}
path = await self.get_artifact_file_path(
    params["<param>"],
    context=context,
    artifacts=params.get("artifacts"))
text = path.read_text()
```
:::
|||
::: col
### Artifact out
```python {.xs}
with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "<file name>"
    out.write_text(<content>)
    ref = await self.send_deeplynx_artifact(
        context=context,
        event_queue=event_queue,
        file_path=out, name=out.name,
        description="<what it is>",
        storage_config=ConnectionConfig.from_env(),
        mime_type="<type>")
return {"artifact_id": ref.artifact_id}
```
:::
::::

{.small}
An uploaded file is an artifact. `x_artifact_ref` makes the orchestrator fill the parameter with its id, so pass the **artifact id**, not a DeepLynx id. Upload while the temporary folder still exists, and return the id so a later skill can use it.

::: callout warn
**Set `mime_type`.** It picks the viewer in the chat (`text/csv` a table, `image/png` an image). Left out, the file shows as a plain download.
:::

---

## Give the LLM a tool {eyebrow="Step 6 of 6 · stretch goal"}

:::: cols 1.35fr 1fr gap=28px
```python {.xs}
class Args(BaseModel):
    <field>: <type>

TOOL = ToolDefinition.from_pydantic(
    "<tool_name>", Args, description="<when to use it>")

history = [{"role": "user", "content": "<prompt>"}]
async with self.llm_client(context) as llm:
    for _ in range(<MAX_TURNS>):          # bounded
        r = await llm.medium(
            history, tools=[TOOL], tool_choice="auto")
        if not r.tool_calls:              # stop here
            break
        history.append(assistant_message(r))
        for call in r.tool_calls:
            result = <your_function>(**call.arguments)
            history.append(tool_result_message(call, result))
answer = r.text
```
|||
- The model **asks** for a tool; your code **runs** it and sends the result back. The model never does the exact work.
- End the loop when there are **no tool calls**, never on `finish_reason`, and always cap the turns.
- Return errors as the tool result, not as exceptions, so the model can correct itself.

::: callout warn
**Append `assistant_message(r)` before the tool results.** Without it the next request fails with "unexpected `tool_use_id` found in `tool_result` blocks".
:::
::::

{.small}
Imports: `from pydantic import BaseModel` and `from prometheus_api.llm_client import ToolDefinition, assistant_message, tool_result_message`.
