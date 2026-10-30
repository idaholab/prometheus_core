# Calling an LLM

Facts as of `prometheus_core` `devel` 2026-10-30, after #310 (`prometheus_api` 0.15, no LiteLLM). When the code disagrees with this file, the code is correct.

Your code picks a flavor (`small`, `medium`, `large`, `vision`, `embedding`, `default`). The `.env` profile
picks the model behind it (deck 04, slides 14-15). Import no provider SDK and hard-code no model ID.

```python
from prometheus_api.llm_client import LLMProviderError
try:
    async with self.llm_client(context) as llm:
        r = await llm.medium(prompt, max_tokens=1800)
except LLMProviderError as e:  # bad key, quota, provider down; one-line message, no secrets
    return {"status": "error", "error": str(e)}
return {"summary": r.text}
```

`self.llm_client(context)` builds an `AsyncLLMClient` from the environment (`LLM_CONFIG_FILE` or
`LLM_CONFIG_PROFILE`, key from `LLM_API_KEY`) and calls the provider directly. There is no LLM proxy
and no key swap: `from_a2a_context` and `with_api_key(LITELLM_MASTER_KEY)` are gone (SDK 0.14).
Other errors: `LLMConfigError` (unknown profile, lists the installed ones), `LLMEndpointUnavailableError`
(endpoint unreachable), `LLMAliasError` (flavor not in the profile); all subclass `LLMClientError`.

**Flavors:** every shipped profile defines `default`, `small`, `medium`, `large`, `vision` (and
`embedding` where the provider has one). List them for a profile:

```sh
grep 'model_name:' <platform>/../sdk/prometheus_api/llm_configs/<profile>.yaml
```

**Structured answer** (deck 04, slide 16; `prometheus_api/prometheus_api/llm_client/tools.py:335-352`):

```python
PICK = ToolDefinition.from_pydantic("pick_table", Pick, description="Choose the matching table")
async with self.llm_client(context) as llm:
    call = await acall_tool(llm, prompt, tool=PICK, model="medium")  # always pass model=
pick = Pick.model_validate(call.arguments)  # then check the range
```

## Profile to key map

`LLM_CONFIG_FILE` wins, then `LLM_CONFIG_PROFILE` (`llm_client/config.py`). The platform requires the profile (`make init-env` asks; compose stops when it is empty) and rejects `registry`. `list_llm_config_profiles()` lists the installed ones.

Every profile reads its provider key from `LLM_API_KEY`; the template compose forwards it and
`EMBEDDING_API_KEY`, and `setup_agent.py` copies both from the platform `.env`.

| profile | `LLM_API_KEY` holds |
|---|---|
| `inl_litellm` | the INL LiteLLM key |
| `genesis` | the Genesis MAG key |
| `ollama` | nothing: first `ollama cp <model> default` (and `small`, `medium`, `large`, `vision`) |
| `inl_hpc` | the INL HPC key |
| `amsc` | the AMSC I2 key |
| `anthropic` | the Anthropic key (+ `EMBEDDING_API_KEY`) |
| `openai` | the OpenAI key |
| `anl_asksage` | the AskSage static key (+ `EMBEDDING_API_KEY`) |

## Key missing in the agent

For `<KEY>` (`LLM_API_KEY`, or `EMBEDDING_API_KEY` for embeddings):

1. `grep -c '^<KEY>=.' .env`. When `0`, copy it: `grep '^<KEY>=' <platform>/.env >> .env`, or add it in your editor.
2. Add `<KEY>: ${<KEY>:-}` under `environment:` in the agent `docker-compose.yml`, then `make up`.
3. Check: `docker compose -p <project> exec -T <service> sh -c 'test -n "$<KEY>" && echo set || echo missing'`.
