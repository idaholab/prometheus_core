# Testing your agent

Facts as of `prometheus_core` `devel` 2026-10-30, after #310 (`prometheus_api` 0.15, no LiteLLM). When the code disagrees with this file, the code is correct.

Test without a platform (deck 04, slide 20 and A21): plain functions for the logic, mocks for
`_execute`, never a real LLM. `uv run pytest` and `uv run ruff check .` must pass (ruff: `E`,
`F`, `I`; `uv run ruff check . --fix` sorts imports).

## Set up the host once

In the agent folder: `uv sync`, then `uv pip install <platform>/../sdk` (the SDK from the `prometheus_core`
clone; elsewhere `"git+https://github.com/idaholab/prometheus_core.git@devel#subdirectory=sdk"`). The template does not list `prometheus_api`, so without
it the tests fail with `ModuleNotFoundError: No module named 'prometheus_api'`. A later bare
`uv sync` removes it again: use `uv sync --inexact`. Add a dependency with
`uv add --no-sync <pkg>`, then `uv sync --inexact`; commit `uv.lock` with `pyproject.toml`.

## Fixtures and mocks

`tests/conftest.py` sets `AGENT_SECRET=test-secret` and `PROMETHEUS_TASK_STORE=memory`, and gives
`context` (`context_id = "test-conversation"`) and `event_queue` (an `AsyncMock`; check
`event_queue.enqueue_event.await_count`). `asyncio_mode = "auto"`. Pass
`skill_id` in `params` yourself: the base class sets it from the metadata only in production
(`prometheus_api/prometheus_api/agent/base.py:462-469`). Write one test per skill, and one for an
unknown `skill_id`.

| your code calls | in a test |
|---|---|
| `get_artifact_file_path` | `monkeypatch.setattr(agent, "get_artifact_file_path", fake)`, where `async def fake(artifact_id, **kw): return TESTS_DIR / "fixtures/x.md"` |
| `send_json_artifact`, `send_status_update` | leave them: they emit on the mocked `event_queue` |
| `send_deeplynx_artifact` | `AsyncMock(return_value=SimpleNamespace(artifact_id="png-1", uri="deeplynx://test"))` |
| `ConnectionConfig.from_env()`, `LLMConfig.from_env()` | patch them on `agent.` when the `.env` points to container paths |
| `self.llm_client(...)` | a fake with `__aenter__`/`__aexit__` and `chat()`/`medium()` that return `ChatResponse(text=..., tool_calls=...)` |
| `load_prompt(...)` | pass `prompts_dir=Path(__file__).with_name("prompts")` (`prometheus_api/prometheus_api/prompts.py:11-35`) |

## Mock the LLM

Patch `monkeypatch.setattr(agent, "llm_client", lambda context, **kw: fake)`. For `acall_tool`,
give the fake `tool_calls=[ToolCall(id="c1", name="pick", arguments={...})]`
(`prometheus_api/prometheus_api/llm_client/tools.py:34-46`). For input-required, call `_execute`
twice: first without the answer (it returns `{}`), then with the answer merged into `params`, as the
client-agent sends it (`asking-the-user.md`). `test_build_app_loads_agent_card` fails on a broken card. Tests do
not prove routing: after they pass, `make up` and test in a fresh chat.
