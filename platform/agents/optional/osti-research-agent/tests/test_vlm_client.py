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

"""Tests for LiteLLMVlmClient against a respx-mocked LiteLLM proxy.

Verifies the OpenAI-style multimodal request shape (a text part followed by
one base64 ``image_url`` data-URI per PNG) and the auth header - no live model.
"""

import asyncio
import json

import httpx
import respx

from research_agent.core.llm import LiteLLMVlmClient


@respx.mock
def test_vlm_client_sends_multimodal_parts():
    route = respx.post("http://proxy/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "analysis"}}]}
        )
    )

    client = LiteLLMVlmClient("http://proxy", api_key="k", model="medium")
    result = asyncio.run(
        client.complete("describe", [b"\x89PNG\r\n", b"\x89PNG2"], max_tokens=100)
    )

    assert result == "analysis"

    body = json.loads(route.calls.last.request.content)
    assert body["model"] == "medium"
    assert body["max_tokens"] == 100
    assert "temperature" not in body

    content = body["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "describe"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    # one image_url part per PNG passed in
    assert sum(1 for part in content if part["type"] == "image_url") == 2

    assert route.calls.last.request.headers["Authorization"] == "Bearer k"


@respx.mock
def test_vlm_client_omits_auth_header_without_key():
    respx.post("http://proxy/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )
    )
    client = LiteLLMVlmClient("http://proxy", model="medium")
    result = asyncio.run(client.complete("x", [b"png"], max_tokens=10))

    assert result == "ok"
