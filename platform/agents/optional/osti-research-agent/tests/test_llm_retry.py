# This file is part of Prometheus
# https://inl.gov/super-intelligence/prometheus/
#
# Copyright 2026 Battelle Energy Alliance, LLC
# All rights reserved, see NOTICE.txt for full restrictions
# https://github.com/idaholab/prometheus_core/blob/main/NOTICE.txt
#
# Licensed under the MIT License, please see LICENSE for details
# https://github.com/idaholab/prometheus_core/blob/main/LICENSE
#
# SPDX-License-Identifier: MIT

"""Model calls retry a transient failure, such as the LiteLLM proxy's passing
404 "page not found", and fail at once on an error that would repeat.

conftest.py sets the retry waits to zero."""

import asyncio

import httpx
import litellm
import pytest
import respx
from langchain_core.messages import HumanMessage

from research_agent.core import llm
from research_agent.core.config import AgentConfig
from research_agent.core.llm import LiteLLMClient, chat_model, is_transient, with_retries

_ATTEMPTS = len(llm.RETRY_DELAYS_S) + 1


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://proxy/chat/completions")
    return httpx.HTTPStatusError(
        "error", request=request, response=httpx.Response(status, request=request)
    )


def _litellm_error(cls, **kwargs):
    return cls(message="error", model="medium", llm_provider="openai", **kwargs)


@pytest.mark.parametrize(
    "exc",
    [
        _status_error(404),
        _status_error(429),
        _status_error(503),
        httpx.ConnectError("refused"),
        _litellm_error(litellm.NotFoundError),
        _litellm_error(litellm.RateLimitError),
        _litellm_error(litellm.ServiceUnavailableError),
        _litellm_error(litellm.InternalServerError),
        _litellm_error(litellm.APIConnectionError),
    ],
)
def test_passing_errors_are_transient(exc):
    assert is_transient(exc)


@pytest.mark.parametrize(
    "exc",
    [
        _status_error(400),
        _status_error(401),
        _status_error(403),
        httpx.ReadTimeout("slow"),
        asyncio.TimeoutError(),
        _litellm_error(litellm.Timeout),
        _litellm_error(litellm.BadRequestError),
        _litellm_error(litellm.AuthenticationError),
        _litellm_error(litellm.ContextWindowExceededError),
        ValueError("bad JSON"),
    ],
)
def test_errors_that_would_repeat_are_not_transient(exc):
    assert not is_transient(exc)


def _flaky(failures, exc, result="done"):
    calls = []

    async def call():
        calls.append(1)
        if len(calls) <= failures:
            raise exc
        return result

    return call, calls


def test_with_retries_recovers_from_a_passing_failure(caplog):
    call, calls = _flaky(2, _status_error(404))

    assert asyncio.run(with_retries(call, "Test call")) == "done"
    assert len(calls) == 3
    assert "Test call failed (HTTPStatusError" in caplog.text
    assert "retrying in 0 s" in caplog.text


def test_with_retries_gives_up_after_every_retry():
    call, calls = _flaky(_ATTEMPTS, _status_error(404))

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(with_retries(call, "Test call"))
    assert len(calls) == _ATTEMPTS


def test_with_retries_raises_a_lasting_error_at_once():
    call, calls = _flaky(1, _status_error(401))

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(with_retries(call, "Test call"))
    assert len(calls) == 1


def test_with_retries_waits_the_configured_delays(monkeypatch):
    waits = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(llm, "RETRY_DELAYS_S", (2.0, 8.0))
    monkeypatch.setattr(llm.asyncio, "sleep", fake_sleep)
    call, calls = _flaky(2, _status_error(503))

    assert asyncio.run(with_retries(call, "Test call")) == "done"
    assert waits == [2.0, 8.0]


@respx.mock
def test_text_client_retries_the_proxy_404():
    route = respx.post("http://proxy/chat/completions").mock(
        side_effect=[
            httpx.Response(404, text="404 page not found"),
            httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}),
        ]
    )

    result = asyncio.run(LiteLLMClient("http://proxy").complete("q", max_tokens=5))

    assert result == "ok"
    assert route.call_count == 2


@respx.mock
def test_text_client_does_not_retry_a_bad_request():
    route = respx.post("http://proxy/chat/completions").mock(
        return_value=httpx.Response(400, json={"error": "bad"})
    )

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(LiteLLMClient("http://proxy").complete("q", max_tokens=5))
    assert route.call_count == 1


def _config():
    return AgentConfig(litellm_base_url="http://proxy:4000", litellm_api_key="k")


def _fake_acompletion(monkeypatch, failures, exc):
    calls = []

    async def acompletion(**kwargs):
        calls.append(kwargs)
        if len(calls) <= failures:
            raise exc
        return litellm.ModelResponse(
            choices=[{"message": {"role": "assistant", "content": "ok"}}]
        )

    monkeypatch.setattr(litellm, "acompletion", acompletion)
    return calls


@pytest.mark.parametrize("forced_tool_choice", [True, False])
def test_chat_model_retries_the_proxy_404(monkeypatch, forced_tool_choice):
    calls = _fake_acompletion(monkeypatch, 2, _litellm_error(litellm.NotFoundError))
    model = chat_model(_config(), "orchestrator", forced_tool_choice=forced_tool_choice)

    reply = asyncio.run(model.ainvoke([HumanMessage(content="hi")]))

    assert reply.content == "ok"
    assert len(calls) == 3
    assert calls[-1]["model"] == "medium"


def test_chat_model_retries_a_streamed_call(monkeypatch):
    calls = []

    async def chunks():
        yield litellm.ModelResponseStream(
            choices=[{"delta": {"role": "assistant", "content": "ok"}}]
        )

    async def acompletion(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise _litellm_error(litellm.ServiceUnavailableError)
        return chunks()

    monkeypatch.setattr(litellm, "acompletion", acompletion)
    model = chat_model(_config(), "analyzer")

    async def stream():
        return "".join([chunk.content async for chunk in model.astream("hi")])

    assert asyncio.run(stream()) == "ok"
    assert len(calls) == 2
    assert calls[-1]["stream"] is True


def test_chat_model_does_not_retry_a_bad_request(monkeypatch):
    calls = _fake_acompletion(monkeypatch, 1, _litellm_error(litellm.BadRequestError))
    model = chat_model(_config(), "verifier")

    with pytest.raises(litellm.BadRequestError):
        asyncio.run(model.ainvoke([HumanMessage(content="hi")]))
    assert len(calls) == 1


def test_chat_model_gives_up_after_every_retry(monkeypatch):
    calls = _fake_acompletion(monkeypatch, _ATTEMPTS, _litellm_error(litellm.NotFoundError))
    model = chat_model(_config(), "verifier")

    with pytest.raises(litellm.NotFoundError):
        asyncio.run(model.ainvoke([HumanMessage(content="hi")]))
    assert len(calls) == _ATTEMPTS
