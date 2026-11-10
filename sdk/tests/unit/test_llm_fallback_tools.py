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

"""Tool calls through the direct-LiteLLM fallback, with the real ``litellm`` package."""

from __future__ import annotations

import json
import re
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import pytest

from prometheus_api.llm_client import (
    AsyncLLMClient,
    LLMClient,
    LLMConfig,
    ToolDefinition,
    parse_tool_calls,
)

_TOOL_ARGUMENTS = {"city": "Idaho Falls"}

_REPLY = {
    "id": "chatcmpl-fallback-tools",
    "object": "chat.completion",
    "created": 0,
    "model": "default-model",
    "choices": [
        {
            "index": 0,
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": json.dumps(_TOOL_ARGUMENTS),
                        },
                    }
                ],
            },
        }
    ],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


class _FakeProvider:
    """An OpenAI-compatible chat endpoint on loopback that records what it receives."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict]] = []
        provider = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                provider.requests.append((self.path, json.loads(self.rfile.read(length))))
                body = json.dumps(_REPLY).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def api_base(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"


@pytest.fixture
def provider():
    fake = _FakeProvider()
    fake.thread.start()
    try:
        yield fake
    finally:
        fake.server.shutdown()
        fake.server.server_close()
        fake.thread.join(timeout=5)


def _fallback_yaml(tmp_path, api_base: str):
    path = tmp_path / "llm_config.yaml"
    path.write_text(
        f"""
model_list:
  - model_name: default
    litellm_params:
      model: openai/default-model
      api_base: {api_base}
      api_key: os.environ/LLM_API_KEY
""".strip(),
        encoding="utf-8",
    )
    return path


_TOOL = ToolDefinition(
    name="get_weather",
    description="Weather for a city.",
    parameters={"type": "object", "properties": {"city": {"type": "string"}}},
)


@pytest.mark.parametrize("client_kind", ["sync", "async"])
async def test_fallback_tool_call_through_real_litellm(
    client_kind, provider, monkeypatch, tmp_path
):
    """Covers REQ-013-04: the fallback tool-calling path needs litellm's mcp extra."""
    monkeypatch.setenv("LLM_API_KEY", "stub-key")
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    config = LLMConfig(
        proxy_url="http://proxy.invalid",
        config_file=_fallback_yaml(tmp_path, provider.api_base),
    )

    if client_kind == "sync":

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("proxy down", request=request)

        client = LLMClient(
            config=config,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        try:
            response = client.chat("Weather in Idaho Falls?", tools=[_TOOL])
        finally:
            client.close()
    else:

        async def async_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("proxy down", request=request)

        async_client = AsyncLLMClient(
            config=config,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(async_handler)),
        )
        try:
            response = await async_client.chat("Weather in Idaho Falls?", tools=[_TOOL])
        finally:
            await async_client.aclose()

    calls = parse_tool_calls(response)
    assert len(calls) == 1
    assert calls[0].name == "get_weather"
    assert calls[0].arguments == _TOOL_ARGUMENTS

    assert len(provider.requests) == 1
    path, body = provider.requests[0]
    assert path == "/chat/completions"
    assert body["tools"][0]["function"]["name"] == "get_weather"


_REQUIREMENT_HEAD = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[([^\]]*)\])?")


def test_sdk_declares_litellm_mcp_extra():
    """Covers REQ-013-04: the runtime dependency on litellm carries its mcp extra."""
    pyproject = tomllib.loads(
        (Path(__file__).parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )

    litellm_extras = []
    for entry in pyproject["project"]["dependencies"]:
        match = _REQUIREMENT_HEAD.match(entry)
        assert match, f"unparseable dependency entry: {entry!r}"
        if re.sub(r"[-_.]+", "-", match.group(1)).lower() == "litellm":
            extras = match.group(2) or ""
            litellm_extras.append({extra.strip().lower() for extra in extras.split(",")})

    assert len(litellm_extras) == 1, f"expected one litellm dependency, got {litellm_extras}"
    assert "mcp" in litellm_extras[0], "litellm dependency must declare the mcp extra"
