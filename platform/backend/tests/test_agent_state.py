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

"""Agent state routes (app/routers/agent_state.py)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import identity
from app.config import settings

SECRET = "test-agent-secret"
CONV = "conv-1"
OTHER_CONV = "conv-2"
TASK_URL = "/v1/agent-state/tasks/task-1"
CONV_URL = f"/v1/agent-state/conversations/{CONV}"


@pytest.fixture(scope="module")
def rsa_private_key_pem() -> str:
    from prometheus_api.agent.identity_keygen import generate_keypair

    return generate_keypair(key_size=2048)[0]


@pytest.fixture(autouse=True)
def _env(monkeypatch, rsa_private_key_pem):
    monkeypatch.setattr(settings, "agent_secret", SECRET)
    monkeypatch.setenv("USER_IDENTITY_PRIVATE_KEY", rsa_private_key_pem)


@pytest.fixture
async def tokens(fake_redis) -> dict[str, str]:
    await fake_redis.sadd("user:convs:alice", CONV, OTHER_CONV)
    await fake_redis.sadd("user:convs:bob", "conv-bob")
    out = {}
    for user in ("alice", "bob"):
        token = await identity.mint_for_user(user)
        assert token
        out[user] = token
    return out


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


def h(token: str, *, agent: str = "thermal-agent", conv: str | None = CONV, **extra: str) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {SECRET}", "X-Agent-Name": agent, "X-User-Token": token, **extra}
    if conv is not None:
        headers["X-Conversation-Id"] = conv
    return headers


def create(client: TestClient, url: str, token: str, state: dict, **kw) -> dict:
    resp = client.put(url, json={"state": state}, headers=h(token, **kw, **{"If-None-Match": "*"}))
    assert resp.status_code == 200, resp.text
    return resp.json()


# --------------------------------------------------------------------------- #
# Round trip and versioning, both scopes
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("url", [TASK_URL, CONV_URL])
def test_create_read_replace_delete(client, tokens, url):
    alice = tokens["alice"]
    created = create(client, url, alice, {"stage": "need_bc"})
    assert created["version"] == 1

    got = client.get(url, headers=h(alice))
    assert got.status_code == 200
    assert got.json()["state"] == {"stage": "need_bc"}
    assert got.headers["etag"] == '"1"'

    replaced = client.put(url, json={"state": {"stage": "done"}}, headers=h(alice, **{"If-Match": '"1"'}))
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["version"] == 2
    assert replaced.json()["created_at"] == created["created_at"]

    assert client.delete(url, headers=h(alice)).status_code == 204
    assert client.get(url, headers=h(alice)).status_code == 404
    assert client.delete(url, headers=h(alice)).status_code == 204  # idempotent


@pytest.mark.parametrize("url", [TASK_URL, CONV_URL])
def test_version_conflicts(client, tokens, url):
    alice = tokens["alice"]
    create(client, url, alice, {"n": 1})
    again = client.put(url, json={"state": {}}, headers=h(alice, **{"If-None-Match": "*"}))
    assert again.status_code == 409
    stale = client.put(url, json={"state": {}}, headers=h(alice, **{"If-Match": "7"}))
    assert stale.status_code == 409
    bare = client.put(url, json={"state": {}}, headers=h(alice))
    assert bare.status_code == 428


def test_replace_of_absent_state_is_409(client, tokens):
    resp = client.put(TASK_URL, json={"state": {}}, headers=h(tokens["alice"], **{"If-Match": "1"}))
    assert resp.status_code == 409


def test_state_must_be_an_object_and_within_limit(client, tokens, monkeypatch):
    alice = tokens["alice"]
    not_obj = client.put(TASK_URL, json={"state": [1, 2]}, headers=h(alice, **{"If-None-Match": "*"}))
    assert not_obj.status_code == 422
    monkeypatch.setattr(settings, "agent_state_max_bytes", 32)
    big = client.put(TASK_URL, json={"state": {"x": "y" * 64}}, headers=h(alice, **{"If-None-Match": "*"}))
    assert big.status_code == 413


async def test_write_sets_ttl(client, tokens, fake_redis, monkeypatch):
    monkeypatch.setattr(settings, "agent_state_ttl_seconds", 120)
    create(client, TASK_URL, tokens["alice"], {})
    assert 0 < await fake_redis.ttl("agent_state:task:task-1") <= 120


# --------------------------------------------------------------------------- #
# Isolation: user, agent, conversation
# --------------------------------------------------------------------------- #


def test_task_state_is_private_to_user_agent_and_conversation(client, tokens):
    alice = tokens["alice"]
    create(client, TASK_URL, alice, {"secret": 1})

    assert client.get(TASK_URL, headers=h(alice, agent="osti-agent")).status_code == 404
    assert client.get(TASK_URL, headers=h(alice, conv=OTHER_CONV)).status_code == 404
    # Bob can't see it, through his own conversation or by naming Alice's.
    assert client.get(TASK_URL, headers=h(tokens["bob"], conv="conv-bob")).status_code == 404
    assert client.get(TASK_URL, headers=h(tokens["bob"], conv=CONV)).status_code == 404
    # Nor overwrite or delete it.
    hijack = client.put(TASK_URL, json={"state": {}}, headers=h(alice, agent="osti-agent", **{"If-None-Match": "*"}))
    assert hijack.status_code == 404
    client.delete(TASK_URL, headers=h(alice, agent="osti-agent"))
    assert client.get(TASK_URL, headers=h(alice)).json()["state"] == {"secret": 1}


def test_conversation_state_is_per_agent(client, tokens):
    alice = tokens["alice"]
    create(client, CONV_URL, alice, {"who": "thermal"})
    create(client, CONV_URL, alice, {"who": "osti"}, agent="osti-agent")
    assert client.get(CONV_URL, headers=h(alice)).json()["state"] == {"who": "thermal"}
    assert client.get(CONV_URL, headers=h(alice, agent="osti-agent")).json()["state"] == {"who": "osti"}


def test_conversation_scope_ignores_conversation_header(client, tokens):
    """The path names the conversation; a different X-Conversation-Id can't redirect it."""
    alice = tokens["alice"]
    create(client, CONV_URL, alice, {"a": 1}, conv=OTHER_CONV)
    assert client.get(CONV_URL, headers=h(alice, conv=None)).json()["state"] == {"a": 1}


# --------------------------------------------------------------------------- #
# Authentication and conversation checks
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("url", [TASK_URL, CONV_URL])
def test_auth_failures(client, tokens, url):
    alice = tokens["alice"]
    no_secret = {k: v for k, v in h(alice).items() if k != "Authorization"}
    assert client.get(url, headers=no_secret).status_code == 401
    assert client.get(url, headers=h("not-a-jwt")).status_code == 401
    assert client.get(url, headers={**h(alice), "X-User-Token": ""}).status_code == 401


def test_task_scope_needs_an_owned_conversation(client, tokens):
    alice = tokens["alice"]
    assert client.get(TASK_URL, headers=h(alice, conv=None)).status_code == 404
    assert client.get(TASK_URL, headers=h(alice, conv="conv-bob")).status_code == 404


def test_conversation_scope_needs_an_owned_conversation(client, tokens):
    resp = client.get("/v1/agent-state/conversations/conv-bob", headers=h(tokens["alice"], conv=None))
    assert resp.status_code == 404


@pytest.mark.parametrize("url", [TASK_URL, CONV_URL])
async def test_deleted_conversation_hides_state(client, tokens, fake_redis, url):
    alice = tokens["alice"]
    create(client, url, alice, {})
    await fake_redis.hset(f"conv:meta:{CONV}", mapping={"hidden": "1"})
    assert client.get(url, headers=h(alice)).status_code == 404
    write = client.put(url, json={"state": {}}, headers=h(alice, **{"If-Match": "1"}))
    assert write.status_code == 404


@pytest.mark.parametrize("url", [TASK_URL, CONV_URL])
async def test_not_found_says_whether_state_or_conversation_is_missing(client, tokens, fake_redis, url):
    alice = tokens["alice"]
    absent = client.get(url, headers=h(alice))
    assert absent.status_code == 404
    assert absent.headers["x-agent-state-not-found"] == "state"

    if url == TASK_URL:  # Conversation keys include the agent, so only a task key can be someone else's
        # Someone else's record at the key is "no state" too, so it doesn't leak.
        create(client, url, alice, {})
        hijack = client.put(url, json={"state": {}}, headers=h(alice, agent="osti-agent", **{"If-None-Match": "*"}))
        assert hijack.status_code == 404
        assert hijack.headers["x-agent-state-not-found"] == "state"

    await fake_redis.hset(f"conv:meta:{CONV}", mapping={"hidden": "1"})
    deleted = client.get(url, headers=h(alice))
    assert deleted.status_code == 404
    assert deleted.headers["x-agent-state-not-found"] == "conversation"
