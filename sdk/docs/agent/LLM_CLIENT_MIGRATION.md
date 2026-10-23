# LLM Client Migration Guide

Use this guide when moving an agent from hard-coded, vendor-specific LLM code to
`prometheus_api.llm_client`.

The goal is that agent code depends on generic model aliases and Prometheus
configuration, not on provider SDKs, provider-specific model names, or ad hoc
API key handling.

## Target Pattern

Inside Prometheus agents, use the async client:

```python
async with self.llm_client(context) as llm:
    response = await llm.medium(params["query"])

return {
    "status": "completed",
    "answer": response.text,
    "model_alias": response.model_alias,
    "provider_model": response.provider_model,
    "usage": response.usage,
}
```

For non-agent scripts and local tools, use the sync client:

```python
from prometheus_api.llm_client import LLMClient


llm = LLMClient()
response = llm("Summarize this result.")
print(response.text)
```

## What Changes

Replace these agent-local patterns:

- Direct `openai`, `anthropic`, Azure OpenAI, or other provider SDK calls
- Hard-coded provider model names in agent logic
- Agent-specific wrappers such as `call_openai()`, `claude_complete()`, or `make_embedding()`
- API keys read from request text or visible JSON payloads
- Prompt logging that can expose secrets or user content by default

With these shared utilities:

- `self.llm_client(context)` in `PrometheusAgent` subclasses
- `AsyncLLMClient(app_name=...)` when a caller is not inside a `PrometheusAgent`
  subclass
- `LLMClient()` in sync scripts
- Generic aliases: `default`, `small`, `medium`, `large`, `vision`, `embedding`
- `LLM_CONFIG_PROFILE` for an installed registry or provider mapping
- `LLM_CONFIG_FILE` when a deployment needs a custom mapping
- `response.text`, `response.embeddings`, `response.usage`, and `response.provider_model`

## Configuration

Use the default installed registry profile:

```bash
REGISTRY_URL=http://litellm:4000
LLM_CONFIG_PROFILE=registry
LLM_DEBUG_LOG_MESSAGES=false
ENABLE_MLFLOW_TRACING=false
```

Or select an installed provider profile and export its credentials:

```bash
LLM_CONFIG_PROFILE=openai
LLM_API_KEY=...
```

Available profiles are `registry`, `inl_hpc`, `inl_litellm`, `amsc`,
`anthropic`, `openai`, and `anl_asksage`. Their YAML files are installed in
`prometheus_api.llm_configs` and
contain every semantic flavor used by agents. Customize placeholder model IDs
and endpoints in the profile source before building a deployment image, or
copy a profile and select it with `LLM_CONFIG_FILE`:

```bash
cp llm_config.example.yaml llm_config.yaml
export LLM_CONFIG_FILE=./llm_config.yaml
```

Provider keys remain environment variables referenced from YAML:

```yaml
model_list:
  - model_name: medium
    litellm_params:
      model: openai/gpt-5-mini
      api_key: os.environ/LLM_API_KEY
      # Optional for local OpenAI-compatible endpoints or private gateways:
      # api_base: http://localhost:8000/v1
```

A configuration with `proxy_url` uses proxy aliases. A configuration with
`model_list` calls those providers directly. If a custom file contains both,
direct aliases are used only when the proxy cannot be reached; a reachable
proxy rejection is surfaced instead of silently bypassing proxy policy.

## Migration Checklist

1. Find direct provider usage.

   Search for imports and model names:

   ```bash
   rg "openai|anthropic|AzureOpenAI|ChatCompletion|messages.create|embeddings.create|api_key|model="
   ```

2. Remove provider clients from agent constructors.

   Agents should not store `OpenAI(...)`, `AsyncOpenAI(...)`, or
   `Anthropic(...)` clients as instance state unless there is a non-LLM reason.

3. Replace provider calls with `self.llm_client(context)`.

   Use `small`, `medium`, `large`, or `vision` based on intent, not provider
   model names.

4. Replace provider response parsing.

   Use:

   - `response.text` for chat text
   - `response.embeddings` for embedding vectors
   - `response.model_alias` for the requested alias
   - `response.provider_model` for the resolved provider model, when available
   - `response.usage` for token usage, when available

5. Move model selection to configuration.

   If the old code selected `gpt-4o`, `claude-*`, or deployment names directly,
   map that choice into the selected profile's aliases. Keep the agent call at
   the semantic flavor it needs.

6. Remove visible key plumbing.

   Do not accept LLM keys in any part of an A2A request. Credentials come from
   the selected profile and environment only.

7. Update tests.

   Mock `prometheus_api.llm_client.AsyncLLMClient` or configure an `LLMConfig`
   with mocked HTTP/LiteLLM behavior. Tests must not call real providers.

8. Update docs and examples.

   If the agent README or card mentions a provider-specific model, replace it
   with alias-based language such as "uses the configured `medium` LLM alias."

## Before And After: OpenAI Chat

Before:

```python
from openai import AsyncOpenAI


class AnalysisAgent(PrometheusAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.openai = AsyncOpenAI(api_key=os.environ["LLM_API_KEY"])

    async def _execute(self, params, context, event_queue):
        result = await self.openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an engineering analyst."},
                {"role": "user", "content": params["query"]},
            ],
        )
        return {"answer": result.choices[0].message.content}
```

After:

```python
class AnalysisAgent(PrometheusAgent):
    async def _execute(self, params, context, event_queue):
        async with self.llm_client(context) as llm:
            response = await llm.medium(
                [
                    {"role": "system", "content": "You are an engineering analyst."},
                    {"role": "user", "content": params["query"]},
                ],
                temperature=0,
            )
        return {
            "answer": response.text,
            "model_alias": response.model_alias,
            "provider_model": response.provider_model,
            "usage": response.usage,
        }
```

## Before And After: Anthropic Chat

Before:

```python
import anthropic


client = anthropic.AsyncAnthropic(api_key=os.environ["LLM_API_KEY"])

message = await client.messages.create(
    model="claude-sonnet-4-5-20250929",
    max_tokens=1024,
    system="You are concise.",
    messages=[{"role": "user", "content": prompt}],
)
answer = message.content[0].text
```

After:

```python
async with self.llm_client(context) as llm:
    response = await llm.large(
        [
            {"role": "system", "content": "You are concise."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=1024,
    )
answer = response.text
```

Configure `large` in LiteLLM instead of in agent code:

```yaml
model_list:
  - model_name: large
    litellm_params:
      model: anthropic/claude-sonnet-4-5-20250929
      api_key: os.environ/LLM_API_KEY
```

## Before And After: Embeddings

Before:

```python
embedding = await client.embeddings.create(
    model="text-embedding-3-large",
    input=["pressure spike", "temperature drift"],
)
vectors = [item.embedding for item in embedding.data]
```

After:

```python
async with self.llm_client(context) as llm:
    response = await llm.embedding(["pressure spike", "temperature drift"])
vectors = response.embeddings
```

## Input Conversion

Chat methods accept either a raw string or OpenAI-style messages:

```python
await llm.medium("Summarize this result.")

await llm.medium([
    {"role": "system", "content": "You are concise."},
    {"role": "user", "content": "Summarize this result."},
])
```

Do not pass provider-native message structures unless they are compatible with
OpenAI-style `role` and `content` dictionaries.

Embedding methods accept one string or a list of strings:

```python
await llm.embedding("bearing temperature rising")
await llm.embedding(["pressure spike", "temperature drift"])
```

## Error Handling

Let LLM errors fail the task unless the agent has a clear fallback behavior.
The base executor will emit a failed task status.

Use explicit alias errors for configuration feedback:

```python
from prometheus_api.llm_client import LLMAliasError


try:
    async with self.llm_client(context) as llm:
        response = await llm.large(params["query"])
except LLMAliasError as exc:
    return {
        "status": "failed",
        "message": str(exc),
    }
```

Avoid catching broad provider exceptions from old SDKs after migration. The
provider should be hidden behind LiteLLM and `LLMClient`.

## Tool Calling

If you hand-rolled a tool-call parser against `ChatResponse.raw`, delete it. The package
now owns the shape-tolerant parsing that proxy dicts and LiteLLM objects both require.

| Replace | With |
| --- | --- |
| a local `_get` / `_as_dict` / `_parse_arguments` trio | `response.tool_calls` (already decoded) |
| `json.loads(call["function"]["arguments"])` | `call.arguments`, with `call.arguments_error` when the model sent invalid JSON |
| reading `raw["choices"][0]["finish_reason"]` | `response.finish_reason` |
| `content = response.text or "Tool calls requested."` | `assistant_message(response)` — it keeps `content` as `None` |
| building a `{"role": "tool", ...}` dict by hand | `tool_result_message(call, result)` |
| `if len(calls) != 1: raise ...` | `require_tool_calls(response, expected=[...], count=1)` |
| wrapping `Model.model_json_schema()` in a function envelope | `ToolDefinition.from_pydantic(name, Model)` |
| `tools=[schema]` and hoping for one call | `call_tool(client, prompt, tool=definition)`, which forces the tool choice |

Existing hand-built schema dictionaries keep working unchanged — `tools` accepts both
`ToolDefinition` values and raw OpenAI function mappings, and mappings pass through with
a byte-identical payload.

Behavior notes when migrating:

- **Parsing is lenient; the gate is explicit.** `chat(...)` never raises on model-authored
  output: malformed arguments arrive as `arguments == {}` with `arguments_error` set. If
  your old code raised in that case, call `require_tool_calls(...)` to keep raising.
- **`tools=[]` means no tools; `tool_choice` needs tools.** An empty `tools` list is
  omitted from the request, and passing `tool_choice` without at least one tool raises
  `LLMToolCallError` before any backend is contacted.
- **Empty tool results get placeholder text.** `tool_result_message(call, "")` sends
  `"(empty result)"`, since empty message content is rejected on replay.
- **Do not `print()` tool dispatch.** Log through `logging.getLogger("prometheus_api.llm_client")`
  so tool data honors the redaction rules rather than landing in worker stdout.

### Multi-turn Tool Loops

The package deliberately does not ship a tool-execution loop: termination is
application policy. It does define two rules that any loop you write must follow,
and both have been violated in practice.

**1. Terminate on the absence of tool calls, never on `finish_reason`.**

```python
# WRONG - silently discards tool calls
done = finish_reason == "stop" or not tool_calls

# RIGHT
done = not response.tool_calls
```

Some providers return `finish_reason == "stop"` *alongside* tool calls. The wrong
form treats that turn as final, so the tools the model asked for are never
dispatched and the caller gets truncated history with no error. `finish_reason` is
reported for observability, not control flow.

**2. Bound the turns.** Every turn is a billed request with growing context, so
`while True:` has no cost ceiling. Use an explicit budget and treat exhaustion as a
real outcome rather than returning partial history that looks finished.

The canonical shape:

```python
MAX_TOOL_TURNS = 8

history = [{"role": "user", "content": question}]
for turn in range(1, MAX_TOOL_TURNS + 1):
    response = llm.medium(history, tools=TOOLS, tool_choice="auto")

    if not response.tool_calls:          # the only terminator
        return response.text

    history.append(assistant_message(response))
    for call in response.tool_calls:
        history.append(tool_result_message(call, run_tool(call)))

raise RuntimeError(f"No final answer within {MAX_TOOL_TURNS} turns")
```

Skip dispatch when `call.arguments_error` is set. Send that error, an unknown tool
name, or a dispatch exception back to the model as the tool message content, and
continue the loop. The model gets a recovery turn; a raise discards a conversation
that could still succeed. A runnable version of all of this is in
`examples/llm_tool_calling_usage.py`.

## Logging And Security

Use the package logger:

```python
logging.getLogger("prometheus_api.llm_client")
```

By default, prompt and embedding content is not logged. If
`LLM_DEBUG_LOG_MESSAGES=true`, normalized messages and embedding inputs are
logged after secret redaction.

Do not add agent-local logs that print prompts, raw request payloads, API keys,
authorization headers, or provider responses containing sensitive content.

## Guidance For AI Coding Assistants

When asked to migrate an agent:

1. Read the whole agent file before editing.
2. Identify all provider SDK imports, constructors, helper functions, and
   response parsing.
3. Replace LLM calls with `self.llm_client(context)` inside `_execute`.
4. Preserve prompts, system instructions, temperatures, `max_tokens`, and other
   provider-neutral kwargs where possible.
5. Replace provider model names with aliases:
   - cheap or quick work -> `small`
   - normal analysis -> `medium`
   - deep analysis -> `large`
   - image/multimodal work -> `vision`
   - embeddings -> `embedding`
6. Move provider-specific model names, keys, and `api_base` into LiteLLM config.
7. Return `response.text`, `response.model_alias`, `response.provider_model`,
   and `response.usage` when useful.
8. Remove direct API key extraction from text or JSON payloads.
9. Update tests to mock the shared client instead of provider SDKs.
10. Update local docs if public behavior, env vars, or examples changed.

Do not leave unused provider dependencies, imports, or environment variables in
the agent after migration.

## Migration Review Checklist

Before merging, verify:

- Agent code imports `AsyncLLMClient` instead of provider SDK clients
- No hard-coded provider model names remain in agent logic
- No API keys are parsed from visible text JSON
- Prompt content is not logged by the agent
- `REGISTRY_URL` plus any `LLM_CONFIG_PROFILE` or `LLM_CONFIG_FILE` selection
  are documented for the agent
- Tests pass without real network calls or provider credentials
- Any agent-specific examples use aliases, not vendor names
