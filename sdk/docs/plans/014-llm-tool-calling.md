# Add first-class LLM tool calling to `prometheus-api`

> Historical implementation plan, kept for reference. It predates the review changes in this pull request; `specs/014-llm-tool-calling.md` and the code are authoritative where they differ.

## Context

You were right: **LLM tool calling is not supported.** More precisely, it is *unspecified and
unsupported*, but it half-works by accident — which is worse than not working, because three
consumers have already built on the accident.

What works today: `chat()` takes `**kwargs` and splats them straight onto the wire, on both
dispatch paths ([client.py:505](../../prometheus_api/llm_client/client.py#L505) for the proxy payload,
[client.py:151](../../prometheus_api/llm_client/client.py#L151) via `_litellm_kwargs` for the LiteLLM
fallback). So `llm.medium(msgs, tools=[...], tool_choice="auto")` reaches the provider.

What does not work — three concrete gaps:

1. **Hard blocker.** [normalization.py:29-38](../../prometheus_api/llm_client/normalization.py#L29-L38)
   rejects the canonical assistant tool-call message `{"role":"assistant","content":None,
   "tool_calls":[...]}` — `content` is a required key, `None` is rejected, `""` is rejected. You
   cannot replay a tool-call turn into history. Consumers work around it by injecting fake
   content: `prometheus_llm.py:74` writes the literal string `"Tool calls requested."` onto the
   wire, and `planner.py:1221` writes `"Planning tool calls requested."`.
2. **No response surface.** `ChatResponse`
   ([models.py:9-17](../../prometheus_api/llm_client/models.py#L9-L17)) has no `tool_calls` and no
   `finish_reason`. A pure tool-call turn has `content: null`, so `_chat_text`
   ([client.py:63-64](../../prometheus_api/llm_client/client.py#L63-L64)) returns `""` — a caller who
   doesn't reach into `.raw` sees an empty string and no signal that tools were requested.
3. **No parsing helper, so it got written three times.** Responses are dual-shaped: a **dict** on
   the proxy path (`response.json()`) and a **LiteLLM `ModelResponse` object** on the fallback
   path. Three consumers each hand-rolled a shape-tolerant parser, and they disagree on error
   policy and on the termination condition:

| Consumer | Parser | Disagreement |
| --- | --- | --- |
| `prometheus_agents/bim_agent/alchemy-backend/app/prometheus_llm.py:59` | `parse_tool_turn` | `done = finish_reason == "stop" or not invocations` — **silently drops tool calls** when a model returns `stop` alongside them. Loop is `while True` (unbounded). Logs via `print()`. |
| `prometheus_platform/agents/client-agent/planner.py:1213` | `_planning_tool_calls` | Swallows `JSONDecodeError` to `{}` silently. |
| `.../client-agent/orchestrator/parameter_extraction.py:110` | `_parse_tool_calls` | Raises on bad JSON. |

Nothing in `specs/`, `tests/`, `docs/`, or `README.md` mentions tool calling. Since this repo is
spec-driven, the deliverable is a spec **plus** the implementation and tests that satisfy it.

## Decisions (confirmed)

| Question | Decision |
| --- | --- |
| Scope | Spec **+ implementation**: tool-call surface on `ChatResponse`, parsing helpers, the `normalize_messages` fix, tests. |
| Spec layout | New `specs/014-llm-tool-calling.md` + surgical amendments to `006`, `007`, `005`. |
| Flavor | **Per-call only.** No 7th YAML alias. The six-flavor contract is untouched. |
| Stale test | Fix the dead `llm_config.example.yaml` test and the six stale doc references in this change. |

**Why per-call, not a `tools` flavor:** `vision` is a flavor because it changes the *input schema*.
Tool calling changes neither the message schema nor the model tier — it is an orthogonal request
parameter, and callers want the cross-product (tools with `small` for cheap extraction, with
`large` for planning). The three existing consumers prove it: all three already pick a flavor
(`large`, `medium`, `medium`) and pass `tools=` alongside. A flavor would also break a contract
pinned in four places ([test_llm_configs.py:13](../../tests/test_llm_configs.py#L13) exact-set `==`,
`specs/005` REQ-005-16, `AGENTS.md:5`, `docs/ENV_SETUP.md:154`) and require a cross-repo LiteLLM
deployment change this package can't ship — for zero gain, since every model the six profiles map
to already supports tool calling.

**Deferred to a follow-up (your scope choice):** the tool-execution loop —
`run_tool_loop`/`arun_tool_loop`, `ToolResult`, `ToolLoopResult`, and the `dispatch` mapping. This
plan ships the primitives all three consumers can delegate to; the loop stays hand-rolled in
consumers for now. Consequence to accept knowingly: bim_agent's unbounded `while True` bug is not
fixed by this change.

## Phase 0 — green baseline (do first, separate commit)

[tests/test_llm_client.py:224-232](../../tests/test_llm_client.py#L224-L232)
`test_local_development_example_config_parses` reads `llm_config.example.yaml`, which was deleted
(not on disk, not in `git ls-files`). It fails today. You cannot use `make test-unit` as the
acceptance gate for a new spec while a test in the file you're editing is red.

1. Delete that test. Its claim is already covered by `test_fallback_yaml_parsing_resolves_env_refs`
   ([tests/test_llm_client.py:213](../../tests/test_llm_client.py#L213)) and
   `test_provider_profiles_scaffold_every_flavor`. Do **not** restore the YAML — the installed
   profiles superseded it.
2. Drop `llm_config.example.yaml` from the `sources:` line of `specs/005`.
3. Fix six stale references: `AGENTS.md:7,21`; `docs/ENV_SETUP.md:178,186-187`;
   `docs/agent/LLM_CLIENT_MIGRATION.md:85`. Point them at `prometheus_api/llm_configs/` and
   `LLM_CONFIG_FILE` (e.g. `cp prometheus_api/llm_configs/openai.yaml llm_config.yaml`).

## Phase 1 — specs first

Follow [docs/SDD_SPEC_AUTHORING.md](../../docs/SDD_SPEC_AUTHORING.md) exactly: front-loaded IDs,
MUST/SHOULD/MAY, `⚠ untested` on every new REQ until its test lands (strip per ID in Phase 2/3).

### New `specs/014-llm-tool-calling.md`

`status: draft` → flipped to `implemented` in Phase 4. `depends-on: 005, 006, 007`.

**Purpose:** give agents one canonical, provider-agnostic way to declare tools, read tool calls off
a chat response, and replay tool results into history, so consumers stop hand-rolling
shape-tolerant parsers.

Requirements (`REQ-014-01` … `REQ-014-12`):

- **01** `ToolCall` MUST be a frozen dataclass exposing `id`, `name`, `arguments`,
  `arguments_error`, `raw`, where `arguments` is an already-decoded JSON object.
- **02** `parse_tool_calls(value)` MUST accept a `ChatResponse` or a raw provider payload, MUST read
  `choices[0].message.tool_calls` from both mapping-shaped proxy payloads and attribute-shaped
  LiteLLM responses, MUST return an empty tuple when choices/message/tool_calls are absent, and
  MUST NOT raise for provider-shaped input.
- **03** Argument decoding MUST accept a JSON-object string or a mapping, MUST copy mappings, and
  MUST record a non-null `arguments_error` with `arguments == {}` when the value is not a decodable
  JSON object — rather than raising.
- **04** `parse_finish_reason(value)` MUST return `choices[0].finish_reason` as a string when
  present and `None` otherwise.
- **05** `assistant_message(response)` MUST return a replayable assistant message carrying the
  provider `tool_calls` verbatim with `role` set to `assistant`, and MUST NOT substitute placeholder
  text for missing or null `content`.
- **06** `tool_result_message(call, result)` MUST return
  `{"role": "tool", "tool_call_id": <id>, "content": <text>}`, accept a `ToolCall` or a call-id
  string, and JSON-encode non-string results with `default=str`.
- **07** `require_tool_calls(response, *, expected=None, count=None)` MUST raise
  `LLMToolCallError` when there are no tool calls, when any call has a blank `id` or `name`, when
  any call carries an `arguments_error`, when a name falls outside `expected`, or when the count
  differs from `count`.
- **08** `ToolDefinition` MUST expose `name`, `description`, `parameters`; `as_schema()` MUST return
  `{"type": "function", "function": {...}}`; `from_pydantic(name, model, description=...)` MUST
  build `parameters` from `model_json_schema()`.
- **09** `tool_schemas(definitions)` MUST convert `ToolDefinition` values to OpenAI function schemas
  and MUST pass mapping schemas through unchanged, so hand-built tool dictionaries keep working.
- **10** `LLMToolCallError` MUST subclass `LLMClientError` so tool failures stay in the existing
  `RuntimeError` tree rather than the `LLMAliasError` `ValueError` tree.
- **11** `prometheus_api.llm_client.__all__` MUST export `ToolCall`, `ToolDefinition`,
  `LLMToolCallError`, `parse_tool_calls`, `parse_finish_reason`, `assistant_message`,
  `tool_result_message`, `require_tool_calls`, and `tool_schemas`.
- **12** `llm_client/tools.py` MUST NOT import `llm_client/client.py` at runtime, so the client can
  import tool parsing without a circular import.

Behavior (`BEH-014-01` … `BEH-014-05`):

- **01** GIVEN a proxy response whose `choices[0].message` has `content: null` and one `tool_calls`
  entry WHEN chat returns THEN `text == ""`, `finish_reason == "tool_calls"`, and `tool_calls` holds
  one decoded `ToolCall`.
- **02** GIVEN a tool call whose `arguments` is `"{not json"` WHEN parsed THEN `arguments == {}`,
  `arguments_error` is non-null, and nothing raises.
- **03** GIVEN a LiteLLM object response with attribute-shaped tool calls WHEN `assistant_message`
  builds history THEN the message keeps `content: None` plus its `tool_calls` and
  `normalize_messages` accepts it.
- **04** GIVEN a response whose only tool call has an `arguments_error` WHEN `require_tool_calls`
  runs THEN `LLMToolCallError` is raised.
- **05** GIVEN a hand-built `{"type": "function", ...}` dict WHEN passed through `tool_schemas`
  THEN it is returned unchanged.

Constraints: sync/async parity per 006; tool names and schemas are developer-authored while
arguments are **model-authored and untrusted**; tool calling is per-call and MUST NOT introduce a
YAML flavor; new `ChatResponse` fields MUST carry defaults and be appended after `raw`.

Non-goals: streaming tool-call deltas; the tool-execution loop and dispatch (follow-up);
provider-native `response_format`/strict-JSON modes; a tool registry, permission model, or sandbox;
retry policy; MCP/A2A tool discovery.

### Amend `specs/006-llm-chat-and-embeddings.md`

Amend in place (intentional behavior change, same commit as the code):

- `REQ-006-01` — append `, except as relaxed by REQ-006-15`.
- `REQ-006-02` — rewrite the rejection list as `missing role, empty roles, and missing/null/empty-string content for any message not covered by REQ-006-15`.
- `REQ-006-12` — add `tool_calls` and `finish_reason` to the `ChatResponse` field list.
- Interfaces line 34 — `ChatResponse(..., raw: Any, tool_calls: tuple[ToolCall, ...] = (), finish_reason: str | None = None)`.
- Interfaces line 40 — add keyword-only `tools` and `tool_choice` to the `chat(...)` signature.
- Non-goals line 54 — cross-reference `REQ-006-18` for streaming.

New: `REQ-006-15` (the normalization relaxation, spelled out in Phase 2), `REQ-006-16` (new fields
appended after `raw` with defaults for downstream compatibility), `REQ-006-17` (`chat()` accepts
keyword-only `tools`/`tool_choice`, converts `ToolDefinition` to schemas while passing mappings
through, and sends both on the proxy payload and the LiteLLM kwargs), `REQ-006-18` (reject a truthy
`stream` with `LLMClientError` before contacting any backend). `BEH-006-04` (assistant `content:
None` + `tool_calls` followed by a `role: "tool"` reply normalizes), `BEH-006-05` (`stream=True`
raises and no request is sent).

### Amend `specs/007-llm-security-and-tracing.md`

- `REQ-007-11` — append: record supplied tool **names** as inputs when tools are provided, and add
  `tool_calls`/`finish_reason` to outputs **only when the response contains tool calls**.
- `REQ-007-13` — tool-call arguments in MLflow span outputs MUST pass through `redact_secrets(...)`;
  full tool JSON schemas MUST NOT be recorded as span inputs.
- `REQ-007-14` — debug logging MUST include tool names, tool count, tool-call count, and
  `finish_reason` while withholding model-authored arguments unless `debug_log_messages` is enabled,
  in which case they MUST be redacted.
- `BEH-007-04` (tool arguments containing an `api_key` appear `[REDACTED]` in span outputs),
  `BEH-007-05` (a response without tool calls yields span outputs with only the original four keys).

### Amend `specs/005` and `specs/000-index.md`

`005`: no REQ change — add one Out-of-scope bullet recording that tool calling is a per-call chat
capability, not a flavor, and that REQ-005-16 is unchanged. Fix the `sources:` line (Phase 0).

`000-index.md`: add the `014` table row; split the Interface Ownership line
`- LLM exports: 005-007.` into an LLM-core line plus `- LLM tool-calling exports (llm_client/tools.py, tool exceptions, ChatResponse.tool_calls): 014.`
The "Architecture in 10 lines" section is pinned at 10 lines — extend line 16 in place rather than
adding an 11th.

## Phase 2 — implementation

### 2a. `normalization.py` — the relaxation

The **ordering change is load-bearing**: today line 29 checks `"role" not in message or "content"
not in message` together, before the role is validated. Split them so the role check still runs
first, then gate the content checks on a new helper:

```python
def _has_tool_calls(message: ChatMessage) -> bool:
    tool_calls = message.get("tool_calls")
    return isinstance(tool_calls, (list, tuple)) and bool(tool_calls)
```

Missing, `None`, or empty-string `content` is permitted **if and only if** `role.strip() ==
"assistant"` **and** `_has_tool_calls(message)`. When permitted and the key is absent, set
`content = None` explicitly (some OpenAI-compatible endpoints reject an assistant message with no
`content` key at all; we already copy the dict, so explicit `null` is free).

Preserve the existing error **message strings** for the missing-role and missing-content cases —
that way the parametrized matrix at
[tests/test_llm_client.py:305-318](../../tests/test_llm_client.py#L305-L318) passes unchanged, including
its `([{"role": "user"}], ValueError)` row. Newly rejected cases to add to that matrix:
`assistant` + `content: None` with no `tool_calls`; `assistant` + `tool_calls: []` (empty list is
falsy); `role: "tool"` + `content: None` + `tool_calls`; and a message missing `role` entirely.

Do **not** add a rule requiring `tool_call_id` on `role: "tool"` messages — correct strictness, but
a new rejection that could break an existing caller. Record it in 006's Open questions.

### 2b. New module `prometheus_api/llm_client/tools.py`

One module, not two. Import graph must stay `models ← tools ← client` (REQ-014-12); `tools.py`
imports `client.py` only under `TYPE_CHECKING`.

`ToolCall`, `ToolDefinition`, `tool_schemas`, `parse_tool_calls`, `parse_finish_reason`,
`assistant_message`, `tool_result_message`, `require_tool_calls`.

**The key design call — lenient parse, one explicit strict gate.** This resolves the three
consumers' disagreement:

- `chat()` always populates `tool_calls` and **never raises** on model-authored garbage. Malformed
  arguments become `arguments={}` with `arguments_error` set; a missing `id`/`name` becomes `""`.
  The model is an untrusted input source — turning a recoverable model mistake into a `chat()`
  exception is worse than surfacing it as data. This matches the planner's swallow-to-`{}` policy
  without its silence.
- `require_tool_calls(...)` is the strict gate, matching `parameter_extraction`'s policy plus the
  planner's `len(calls) != 1` checks.

Reuse the shape-tolerant `_get` idiom already at
[client.py:35-38](../../prometheus_api/llm_client/client.py#L35-L38) and the `_as_dict` /
`_parse_arguments` logic from `prometheus_llm.py:38-56` — but **not** its placeholder injection at
`prometheus_llm.py:71-74`. `assistant_message` forces `role="assistant"` and sets `content = None`
when absent or blank; it never writes `"Tool calls requested."`.

Deliberate divergence to note in the spec: bim_agent's `parse_tool_turn` *raises* when `choices` is
empty (`prometheus_llm.py:62-63`); ours returns `()`, consistent with `_chat_text`
([client.py:58-59](../../prometheus_api/llm_client/client.py#L58-L59)) returning `""`.

`tool_schemas` passing mapping schemas through unchanged is **non-negotiable** — it is what lets all
three consumers adopt `tools=` with a byte-identical wire payload.

### 2c. `exceptions.py`

Add `LLMToolCallError(LLMClientError)`. Note the existing pair are in **unrelated** trees
(`LLMClientError(RuntimeError)` vs `LLMAliasError(ValueError)`), so subclassing `LLMClientError` is
a deliberate choice worth a test.

### 2d. `models.py` — `ChatResponse`

Append after `raw`, with defaults — the single most important backwards-compatibility decision,
since three consumers construct and consume this frozen dataclass:

```python
    tool_calls: tuple["ToolCall", ...] = ()
    finish_reason: str | None = None
```

`tuple` not `list` (a frozen dataclass with a mutable field is a smell, and `()` is a valid literal
default). `ToolCall` imported under `TYPE_CHECKING` with a string annotation.

**Do not change `_chat_text`.** A pure tool-call turn keeps `text == ""`; `finish_reason ==
"tool_calls"` plus a non-empty `tool_calls` is the signal. Synthesizing text is the bug we're
removing.

### 2e. `client.py` — four construction sites, hoisted

`ChatResponse` is built at four sites: [client.py:372](../../prometheus_api/llm_client/client.py#L372),
[:394](../../prometheus_api/llm_client/client.py#L394) (sync normal + proxy-unavailable fallback), and the
two async equivalents at ~`:648` and ~`:670`. Rather than editing four literals, add one builder to
`_ClientMixin` so future field additions are a one-site change and 006's parity constraint is
enforced structurally:

```python
    def _build_chat_response(self, *, raw, alias, provider_model) -> ChatResponse:
        return ChatResponse(
            text=_chat_text(raw),
            model_alias=alias,
            provider_model=_provider_model(raw, provider_model),
            usage=_usage(raw),
            raw=raw,
            tool_calls=parse_tool_calls(raw),
            finish_reason=parse_finish_reason(raw),
        )
```

Add `_prepare_chat_kwargs` to `_ClientMixin` too — it holds the `stream` guard (REQ-006-18) and the
`ToolDefinition` → schema conversion, so both clients get it free. Then add keyword-only `tools` and
`tool_choice` to both `chat()` signatures ([:343](../../prometheus_api/llm_client/client.py#L343) and
~`:619`), after a `*`.

**`small`/`medium`/`large`/`vision` need no change** — they forward `**kwargs`, which binds to the
new named parameters automatically, so every existing `llm.large(msgs, tools=[...])` call site keeps
working identically.

Add a durable parity guard, since 006's sync/async constraint currently has no automated
enforcement:

```python
def test_sync_and_async_chat_signatures_match():
    assert (set(inspect.signature(LLMClient.chat).parameters)
            == set(inspect.signature(AsyncLLMClient.chat).parameters))
```

**mypy note:** `warn_return_any = true` will flag the parser internals, since `_get(...)` returns
`Any`. Every extracted value needs explicit narrowing (`str(...)`, `isinstance`, or `cast`). Budget
time — this is the most likely source of `make typecheck` churn.

### 2f. `__init__.py`

Add the nine new symbols to the imports and to `__all__` (REQ-014-11).

## Phase 3 — logging and tracing

**The governing distinction:** tool names and schemas are developer-authored; tool-call arguments
and results are model-authored. Names are always safe to log and are the most useful debug datum.
Arguments never are.

`_log_chat_request` ([client.py:229-246](../../prometheus_api/llm_client/client.py#L229-L246)) never sees
`kwargs` today. Add `tool_names` and `tool_choice` parameters and thread them through both `chat()`
bodies; add `tool_count`/`tool_names` to the payload. `_log_response` gains `tool_call_count` and
`finish_reason`. Arguments only under `debug_log_messages`, always via `redact_secrets`.

Useful existing behavior: `redact_secrets(messages)` already recurses lists and dicts and applies
`_SECRET_ASSIGNMENT_RE` to the `tool_calls[].function.arguments` JSON **string**, so an `api_key`
inside an argument blob is already redacted on the request side. Gap to document: a value containing
whitespace is only partially redacted.

**Tracing — the exact-dict problem.** `_set_chat_trace_outputs`
([client.py:217-227](../../prometheus_api/llm_client/client.py#L217-L227)) builds exactly four keys, and
[tests/test_llm_client.py:450-456](../../tests/test_llm_client.py#L450-L456) asserts both span inputs and
outputs as **exact dicts** (pinned by REQ-007-11).

Solution: add `tool_calls` and `finish_reason` to outputs **only when `response.tool_calls` is
non-empty**, and add `tools` (names only) to inputs only when tools were supplied. That leaves the
pinned assertions passing byte-for-byte unchanged, keeps text-only traces clean, and gives
tool-calling traces what matters.

Two details: serialize `ToolCall` explicitly to plain dicts (don't hand MLflow dataclasses), and
run the arguments through `redact_secrets` (REQ-007-13) — traces persist to a remote server and
model-authored arguments can echo a secret out of the prompt. This is the most important security
detail in the change. Span inputs get tool **names only**, never full schemas, which can be tens of
KB per span.

## Phase 4 — docs, examples, release

| File | Change |
| --- | --- |
| `CLAUDE.md` | **The largest doc gap.** Line 7 says the package ships "two cooperating components" and the file never mentions `llm_client` at all — while line 100 mandates keeping it current. Change "two" → "three", add the LLM component, and add an "LLM client layout" Architecture Note: sync/async are two independent implementations that must be edited together, shared behavior belongs in `_ClientMixin`, `tools.py` must not import `client.py` at runtime, flavors live in YAML and per-call capabilities live in `chat()` kwargs. |
| `AGENTS.md` | Self-update mandated at line 93. Extend the `llm_client/` sentence (line 5); add a coding-style paragraph recording the per-call-not-a-flavor rule, the import-direction rule, the exception-tree rule, and "build `ChatResponse` through `_build_chat_response`". |
| `README.md` | Tool-calling bullet in the LLMClient feature list (~line 171); short snippet after the Quick Start; new example in the examples list. |
| `docs/ENV_SETUP.md` | New "Tool Calling" subsection stating explicitly that tool calling needs **zero configuration and adds no env vars** — a reader who just learned about flavors will look for one. Note that MLflow traces record *redacted* tool arguments when tracing is on. |
| `docs/agent/LLM_CLIENT_MIGRATION.md` | New "Tool Calling" section with before/after: hand-rolled `_get`/`_parse_arguments` → `response.tool_calls`; placeholder content → `assistant_message(response)`; hand-wrapped `model_json_schema()` → `ToolDefinition.from_pydantic`. Add "do not `print()` tool dispatch" to Logging And Security. |
| `examples/llm_tool_calling_usage.py` | New. Two tools via `ToolDefinition.from_pydantic`, a manual parse-and-reply turn using `assistant_message` + `tool_result_message`, and a `require_tool_calls` error path. Follow `examples/llm_client_usage.py`'s shape; `examples/` is ruff/mypy-excluded. |

Then `make bump-minor` → **0.11.0** (new public exports plus a relaxed validator is a minor), and
flip `specs/014` status `draft` → `implemented`.

No dependency change: `litellm>=1.80,<2` ([pyproject.toml:27](../../pyproject.toml#L27)) already covers
this, and nothing here calls a new litellm API. No `Makefile` or `make test-install` change.

## Tests

Follow the existing conventions exactly — **no fixtures**, module-level helpers, `monkeypatch`,
`httpx.MockTransport` handlers branching on `request.url.path` (every handler must answer
`/v1/models` or you get `LLMAliasError`), reuse `_proxy_response`/`_proxy_models`, assert payloads
via a `posted: list[dict]` closure, and stub the fallback path with `import litellm` inside the test
body then `monkeypatch.setattr(litellm, "completion", fake)` returning **plain dicts**. Cite REQ/BEH
IDs in a docstring or an inline comment above the assert. Line length 100.

Added to `tests/test_llm_client.py`: normalization acceptance + the extended rejection matrix
(REQ-006-15, REQ-006-02, BEH-006-04); `tool_calls`/`finish_reason` populated from a proxy dict and
from a LiteLLM object, **sync and async** (REQ-014-02, BEH-014-01); `tools`/`tool_choice` forwarded
to the proxy payload and to the LiteLLM kwargs (REQ-006-17); `ToolDefinition` objects serialized;
flavor methods forward `tools`; `stream=True` rejected with no request sent (REQ-006-18,
BEH-006-05); the signature parity guard; redacted tool calls in span outputs and their absence
without tool calls (REQ-007-13, BEH-007-04/05); debug logging with and without opt-in (REQ-007-14).

New `tests/test_llm_tools.py`: both response shapes at the parser level; `ChatResponse`-or-raw
input; empty-tuple cases; JSON-string vs mapping arguments; `arguments_error` for malformed and for
non-object JSON (BEH-014-02); `parse_finish_reason` both shapes; `assistant_message` preserves
`content: None` and **explicitly asserts no `"Tool calls requested."`** (BEH-014-03); the
`assistant_message` → `normalize_messages` round trip, which is the load-bearing integration;
`tool_result_message` JSON-encoding and id-or-`ToolCall` input; a parametrized `require_tool_calls`
matrix (BEH-014-04); `from_pydantic` schema shape; `tool_schemas` dict pass-through (BEH-014-05);
`LLMToolCallError` subclasses `LLMClientError`; `__all__` membership; and `tools.py` importable
without `client.py` in `sys.modules` (REQ-014-12).

Dual-shape coverage is the thing most likely to be under-tested — make sure proxy-dict **and**
LiteLLM-object are each covered in both sync and async.

## Optional additions (easy to cut)

- **`call_tool` / `acall_tool`** — force one named tool via
  `tool_choice={"type":"function","function":{"name": ...}}` and return exactly one validated
  `ToolCall`. ~12 lines on top of `require_tool_calls`, and the highest value-per-line in the whole
  change: the planner has **three** near-identical "build a schema, send one tool, assert
  `len(calls) == 1`" sites (`planner.py:282-330`, `:376-392`, `:438-492`) that currently just *hope*
  for one call. It makes an LLM call rather than only parsing one, so it sits just outside the
  chosen scope — say the word and I'll drop it (and REQ-014-13/14 with it).
- **The `stream` guard** (REQ-006-18). Five lines. Today `stream=True` gives an opaque
  `json.JSONDecodeError` on the proxy path and a **silent empty string** on the fallback path. Tool
  calling drives people toward streaming, so the footgun is about to get more traffic. Cut only if
  you want the tightest possible diff.

## Verification

```bash
# Run from the sdk/ directory.

# Baseline — confirm exactly one pre-existing failure before Phase 0
uv run pytest tests/test_llm_client.py tests/test_llm_configs.py -v

make format && make lint && make typecheck && make test-unit

uv run pytest tests/test_llm_tools.py -v
uv run pytest tests/test_llm_configs.py -v                 # 6-flavor contract untouched
uv run pytest tests/test_llm_client.py -k "mlflow" -v      # exact-dict span contract holds
uv run pytest tests/test_llm_client.py -k "normalize" -v   # REQ-006-02 rejections intact

make check && make test-install
```

**Cross-repo additive-compatibility smoke** (read-only; proves nothing downstream broke):

```bash
cd ../prometheus_agents/bim_agent/alchemy-backend && uv run pytest tests/test_prometheus_llm.py -v
```

All three of its tests must pass **unmodified**. If they don't, the change wasn't additive and
something needs a default.

## Follow-ups (separate PRs, separate repos)

This change is **purely additive** — the defaults on `ChatResponse` and the pass-through in
`tool_schemas` guarantee all three consumers keep working with zero edits. Migrations are follow-ups:

1. `parameter_extraction.py` — easiest; its error policy already matches `require_tool_calls`.
2. `planner.py` — the parser and the three forced-single-call sites. Its main loop injects a domain
   nudge and terminates on external state, so it may legitimately stay hand-rolled.
3. `bim_agent/prometheus_llm.py` — deletes ~100 of 161 lines. Its PR must call out that
   `tests/test_prometheus_llm.py:99` asserts the exact string `"Tool calls requested."` and needs to
   become `content is None`, and that `print()` → package logger removes output from Celery stdout.
4. The tool-execution loop, if you want it in the package later — that's where bim_agent's unbounded
   `while True` and dropped-tools-on-`finish_reason=="stop"` bugs get fixed centrally.

## Risks and open questions (to record in the spec)

- **`content: null` vs. absent `content`** on the replayed assistant message is provider-specific.
  We send explicit `null`, unverified against all six installed profiles or a live proxy. Most
  likely source of a field bug.
- **Lenient `tool_calls` by default** is right for a retry-capable caller and feels wrong for
  structured output, which is why `require_tool_calls` exists. Two consumers currently *raise* on
  malformed arguments, so they must opt back into strictness.
- **Logging model-authored tool *names*** from the response at DEBUG is the one place this plan
  knowingly relaxes the "model-authored is untrusted" rule (names are drawn from a developer-supplied
  enum, and the debug value is high).
- **`assistant_message`** is a broad name for a package-level export; `response_to_message` was the
  alternative.
- **No integration coverage** — everything is unit-level with stubbed transports. The dual-shape
  handling in particular is validated against a *model* of litellm's `ModelResponse`, not the real
  object.
- A tool call with a blank `id` cannot produce a valid `tool_call_id`; `require_tool_calls` rejects
  it rather than fabricating one.
