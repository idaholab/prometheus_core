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

"""Coverage tests for the LiteLLM text and embedding clients in core/llm.py."""

import asyncio
import json

import httpx
import respx

from research_agent.core.llm import LiteLLMClient, LiteLLMEmbedder


@respx.mock
def test_text_client_posts_prompt_with_auth_and_returns_content():
    route = respx.post("http://proxy/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "an answer"}}]}
        )
    )
    client = LiteLLMClient("http://proxy/", api_key="secret", model="small")

    result = asyncio.run(client.complete("question?", max_tokens=42))

    assert result == "an answer"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer secret"
    body = json.loads(request.content)
    assert body == {
        "model": "small",
        "messages": [{"role": "user", "content": "question?"}],
        "max_tokens": 42,
    }


@respx.mock
def test_text_client_without_key_omits_auth_and_maps_null_content_to_empty():
    route = respx.post("http://proxy/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": None}}]}
        )
    )
    client = LiteLLMClient("http://proxy")

    assert asyncio.run(client.complete("q", max_tokens=5)) == ""
    request = route.calls.last.request
    assert "Authorization" not in request.headers
    assert json.loads(request.content)["model"] == "medium"


@respx.mock
def test_text_client_raises_on_http_error():
    respx.post("http://proxy/chat/completions").mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )
    client = LiteLLMClient("http://proxy")

    try:
        asyncio.run(client.complete("q", max_tokens=5))
    except httpx.HTTPStatusError as exc:
        assert exc.response.status_code == 500
    else:
        raise AssertionError("HTTP error was swallowed")


@respx.mock
def test_embedder_batch_orders_rows_by_index_and_sends_auth():
    route = respx.post("http://proxy/embeddings").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.2, 0.3]},
                    {"index": 0, "embedding": [0.0, 0.1]},
                ]
            },
        )
    )
    embedder = LiteLLMEmbedder("http://proxy/", api_key="k")

    vectors = asyncio.run(embedder.embed_batch(["a", "b"]))

    assert vectors == [[0.0, 0.1], [0.2, 0.3]]
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer k"
    assert json.loads(request.content) == {"model": "embedding", "input": ["a", "b"]}


def test_embedder_batch_of_nothing_makes_no_request():
    embedder = LiteLLMEmbedder("http://proxy")
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("http://proxy/embeddings")
        assert asyncio.run(embedder.embed_batch([])) == []
        assert not route.called


@respx.mock
def test_embed_single_text_without_key_returns_first_vector():
    route = respx.post("http://proxy/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"embedding": [1.0, 2.0]}]})
    )
    embedder = LiteLLMEmbedder("http://proxy", model="emb-alias")

    assert asyncio.run(embedder.embed("hello")) == [1.0, 2.0]
    request = route.calls.last.request
    assert "Authorization" not in request.headers
    assert json.loads(request.content) == {"model": "emb-alias", "input": ["hello"]}


@respx.mock
def test_embed_returns_empty_when_proxy_returns_no_rows():
    respx.post("http://proxy/embeddings").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    embedder = LiteLLMEmbedder("http://proxy")

    assert asyncio.run(embedder.embed("hello")) == []
