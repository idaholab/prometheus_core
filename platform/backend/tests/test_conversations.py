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

"""Offline tests for GET /api/conversations/recent (task 08).

Drive the endpoint against a ``TestClient`` with ``ConversationStateClient``
replaced by an in-memory fake — no live Redis. Covers the Redis-down graceful
degrade, populated results, auth, and limit validation. The 200 cases also prove
the router is mounted in ``app/main.py``.
"""

from fastapi.testclient import TestClient

from app.routers import conversations as conversations_router


class _FakeClient:
    """Stand-in for ConversationStateClient with canned availability + rows."""

    def __init__(self, *, available: bool, rows: list[dict]):
        self._available = available
        self._rows = rows
        self.last_limit: int | None = None
        self.last_user_id: str | None = None

    @property
    def available(self) -> bool:
        return self._available

    def get_conversation_history(self, limit: int = 20, user_id: str | None = None) -> list[dict]:
        self.last_limit = limit
        self.last_user_id = user_id
        return self._rows[:limit]


def _patch_client(monkeypatch, *, available: bool, rows: list[dict]) -> _FakeClient:
    fake = _FakeClient(available=available, rows=rows)
    monkeypatch.setattr(conversations_router, "ConversationStateClient", lambda _url: fake)
    return fake


def _authed_client(monkeypatch) -> TestClient:
    from app import security
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "jwt_secret", "test-secret", raising=False)
    monkeypatch.setattr(security.settings, "jwt_secret", "test-secret", raising=False)

    token = security.issue_token(security.User(identifier="alice"), sid="sid-conv")
    client = TestClient(app)
    client.cookies.set(settings.cookie_name, token)
    return client


def test_recent_requires_auth():
    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/conversations/recent")
    assert resp.status_code == 401


def test_recent_degrades_gracefully_when_redis_down(monkeypatch):
    _patch_client(monkeypatch, available=False, rows=[])
    client = _authed_client(monkeypatch)

    resp = client.get("/api/conversations/recent")
    assert resp.status_code == 200
    assert resp.json() == {"available": False, "conversations": []}


def test_recent_returns_conversations(monkeypatch):
    rows = [
        {
            "conversation_id": "c2",
            "query": "corrosion rate?",
            "status": "completed",
            "timestamp": "2026-08-11T10:00:00Z",
        },
        {
            "conversation_id": "c1",
            "query": "hello",
            "status": "unknown",
            "timestamp": "2026-08-10T09:00:00Z",
        },
    ]
    _patch_client(monkeypatch, available=True, rows=rows)
    client = _authed_client(monkeypatch)

    resp = client.get("/api/conversations/recent")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert [c["conversation_id"] for c in body["conversations"]] == ["c2", "c1"]
    assert [c["status"] for c in body["conversations"]] == ["completed", "unknown"]
    assert all("material_id" not in c for c in body["conversations"])


def test_recent_scopes_by_authenticated_user(monkeypatch):
    """GET /api/conversations/recent must pass the caller's own user_id, not
    some other user's -- this is the fix for the pre-multi-user global scan."""
    fake = _patch_client(monkeypatch, available=True, rows=[])
    client = _authed_client(monkeypatch)  # issues a token for identifier="alice"

    resp = client.get("/api/conversations/recent")
    assert resp.status_code == 200
    assert fake.last_user_id == "alice"


def test_recent_forwards_limit(monkeypatch):
    fake = _patch_client(monkeypatch, available=True, rows=[])
    client = _authed_client(monkeypatch)

    resp = client.get("/api/conversations/recent?limit=5")
    assert resp.status_code == 200
    assert fake.last_limit == 5


def test_recent_rejects_out_of_range_limit(monkeypatch):
    _patch_client(monkeypatch, available=True, rows=[])
    client = _authed_client(monkeypatch)

    assert client.get("/api/conversations/recent?limit=0").status_code == 422
    assert client.get("/api/conversations/recent?limit=1000").status_code == 422


# --------------------------------------------------------------------------- #
# AU-2 — ConversationStateClient sorts before slicing (returns the newest)
# --------------------------------------------------------------------------- #


def test_get_history_sorts_before_slicing(monkeypatch):
    """With more conversations than the limit, the newest are returned — not an
    arbitrary unordered subset (the old slice-before-sort bug)."""
    import json as _json

    from app.conversation_state import ConversationStateClient

    # keys() returns them oldest-first; a slice-before-sort with limit=2 would keep
    # {old, mid} and drop the newest. Sort-before-slice must return {new, mid}.
    blobs = {
        "conversation:old": {"user_query": "old", "conversation_history": [{"timestamp": "2026-01-01T00:00:00Z"}]},
        "conversation:mid": {"user_query": "mid", "conversation_history": [{"timestamp": "2026-05-01T00:00:00Z"}]},
        "conversation:new": {"user_query": "new", "conversation_history": [{"timestamp": "2026-08-01T00:00:00Z"}]},
    }

    class _FakeRedis:
        def keys(self, pattern):
            return list(blobs.keys())

        def get(self, key):
            return _json.dumps(blobs[key])

    c = ConversationStateClient("redis://x")
    monkeypatch.setattr(type(c), "client", property(lambda self: _FakeRedis()))

    rows = c.get_conversation_history(limit=2)
    assert [r["conversation_id"] for r in rows] == ["new", "mid"]


# --------------------------------------------------------------------------- #
# Per-user history scoping (user:convs:{user_id} index, not a global scan)
# --------------------------------------------------------------------------- #


def test_get_history_scopes_to_user_id_via_index(monkeypatch):
    """With user_id set, only conversations in that user's index are read --
    conversations belonging to other users must never be scanned or returned."""
    import json as _json

    from app.conversation_state import ConversationStateClient

    blobs = {
        "conversation:mine": {"user_query": "mine", "conversation_history": [{"timestamp": "2026-08-01T00:00:00Z"}]},
        "conversation:theirs": {
            "user_query": "theirs",
            "conversation_history": [{"timestamp": "2026-08-02T00:00:00Z"}],
        },
    }

    class _FakeRedis:
        def keys(self, pattern):  # must NOT be called on the scoped path
            raise AssertionError("global keys() scan used despite user_id being provided")

        def smembers(self, key):
            assert key == "user:convs:alice"
            return {"mine"}

        def get(self, key):
            return _json.dumps(blobs[key])

    c = ConversationStateClient("redis://x")
    monkeypatch.setattr(type(c), "client", property(lambda self: _FakeRedis()))

    rows = c.get_conversation_history(limit=20, user_id="alice")
    assert [r["conversation_id"] for r in rows] == ["mine"]


def test_get_history_falls_back_to_global_scan_without_user_id(monkeypatch):
    """user_id=None preserves the legacy global scan (pre-ownership-tracking data)."""
    import json as _json

    from app.conversation_state import ConversationStateClient

    blobs = {
        "conversation:a": {"user_query": "a", "conversation_history": [{"timestamp": "2026-08-01T00:00:00Z"}]},
    }

    class _FakeRedis:
        def keys(self, pattern):
            assert pattern == "conversation:*"
            return list(blobs.keys())

        def get(self, key):
            return _json.dumps(blobs[key])

    c = ConversationStateClient("redis://x")
    monkeypatch.setattr(type(c), "client", property(lambda self: _FakeRedis()))

    rows = c.get_conversation_history(limit=20)
    assert [r["conversation_id"] for r in rows] == ["a"]


# --------------------------------------------------------------------------- #
# Chat history: ownership, soft delete, title precedence (ConversationStateClient)
# --------------------------------------------------------------------------- #


def test_owns_checks_the_user_index(monkeypatch):
    from app.conversation_state import ConversationStateClient

    class _FakeRedis:
        def sismember(self, key, member):
            assert key == "user:convs:alice"
            return member == "c1"

    c = ConversationStateClient("redis://x")
    monkeypatch.setattr(type(c), "client", property(lambda self: _FakeRedis()))

    assert c.owns("alice", "c1") is True
    assert c.owns("alice", "c2") is False


def test_get_history_excludes_soft_deleted_conversations(monkeypatch):
    import json as _json

    from app.conversation_state import ConversationStateClient

    blobs = {
        "conversation:visible": {"user_query": "keep", "conversation_history": [{"timestamp": "2026-08-01T00:00:00Z"}]},
        "conversation:hidden": {"user_query": "gone", "conversation_history": [{"timestamp": "2026-08-02T00:00:00Z"}]},
    }
    meta = {"conv:meta:hidden": {"hidden": "1", "hidden_at": "2026-08-03T00:00:00Z"}}

    class _FakeRedis:
        def keys(self, pattern):
            return list(blobs.keys())

        def get(self, key):
            return _json.dumps(blobs[key])

        def hgetall(self, key):
            return meta.get(key, {})

    c = ConversationStateClient("redis://x")
    monkeypatch.setattr(type(c), "client", property(lambda self: _FakeRedis()))

    rows = c.get_conversation_history(limit=20)
    assert [r["conversation_id"] for r in rows] == ["visible"]


def test_get_history_title_precedence(monkeypatch):
    """A user rename wins over the client-agent's LLM title, which wins over the
    raw first query."""
    import json as _json

    from app.conversation_state import ConversationStateClient

    blobs = {
        "conversation:renamed": {
            "user_query": "raw query",
            "title": "llm title",
            "conversation_history": [{"timestamp": "2026-08-01T00:00:00Z"}],
        },
        "conversation:llm-only": {
            "user_query": "raw query 2",
            "title": "llm title 2",
            "conversation_history": [{"timestamp": "2026-08-01T00:00:01Z"}],
        },
        "conversation:no-title": {
            "user_query": "raw query 3",
            "conversation_history": [{"timestamp": "2026-08-01T00:00:02Z"}],
        },
    }
    meta = {"conv:meta:renamed": {"title_override": "my rename"}}

    class _FakeRedis:
        def keys(self, pattern):
            return list(blobs.keys())

        def get(self, key):
            return _json.dumps(blobs[key])

        def hgetall(self, key):
            return meta.get(key, {})

    c = ConversationStateClient("redis://x")
    monkeypatch.setattr(type(c), "client", property(lambda self: _FakeRedis()))

    rows = {r["conversation_id"]: r for r in c.get_conversation_history(limit=20)}
    assert rows["renamed"]["title"] == "my rename"
    assert rows["llm-only"]["title"] == "llm title 2"
    assert rows["no-title"]["title"] == "raw query 3"


def test_is_pending_reflects_agent_status_final_flag(monkeypatch):
    import json as _json

    from app.conversation_state import ConversationStateClient

    status = {
        "agent:status:running": _json.dumps({"message": "Executing…", "final": False}),
        "agent:status:done": _json.dumps({"message": "Response ready.", "final": True}),
    }

    class _FakeRedis:
        def get(self, key):
            return status.get(key)

    c = ConversationStateClient("redis://x")
    monkeypatch.setattr(type(c), "client", property(lambda self: _FakeRedis()))

    assert c.is_pending("running") is True
    assert c.is_pending("done") is False
    assert c.is_pending("never-started") is False  # no key at all -> not pending


def test_get_history_marks_actively_running_conversations_pending(monkeypatch):
    import json as _json

    from app.conversation_state import ConversationStateClient

    blobs = {
        "conversation:running": {
            "user_query": "still going",
            "conversation_history": [{"timestamp": "2026-08-01T00:00:00Z"}],
        },
        "conversation:done": {
            "user_query": "finished",
            "conversation_history": [{"timestamp": "2026-08-01T00:00:01Z"}],
        },
    }
    status = {"agent:status:running": _json.dumps({"message": "…", "final": False})}

    class _FakeRedis:
        """Serves both `conversation:{id}` and `agent:status:{id}` reads —
        `is_pending` calls `.get()` on the same client the history scan uses."""

        def keys(self, pattern):
            return list(blobs.keys()) if pattern == "conversation:*" else []

        def get(self, key):
            # `blobs` is keyed by the full "conversation:{id}" key, matching what
            # the history scan passes here -- not by the bare id.
            if key.startswith("conversation:"):
                return _json.dumps(blobs[key]) if key in blobs else None
            return status.get(key)

        def hgetall(self, key):
            return {}

    c = ConversationStateClient("redis://x")
    monkeypatch.setattr(type(c), "client", property(lambda self: _FakeRedis()))

    rows = {r["conversation_id"]: r for r in c.get_conversation_history(limit=20)}
    assert rows["running"]["pending"] is True
    assert rows["done"]["pending"] is False


def test_get_transcript_normalizes_and_drops_orchestration_noise(monkeypatch):
    import json as _json

    from app.conversation_state import ConversationStateClient

    conv = {
        "conversation_history": [
            {"role": "user", "content": "hello", "timestamp": "t1"},
            {"routing_decision": {"primary_skill": "corrosion"}},  # no role -> dropped
            {"role": "assistant", "content": "hi there", "timestamp": "t2"},
            {"role": "assistant", "content": "", "timestamp": "t3"},  # empty -> dropped
        ],
    }

    class _FakeRedis:
        def get(self, key):
            assert key == "conversation:c1"
            return _json.dumps(conv)

    c = ConversationStateClient("redis://x")
    monkeypatch.setattr(type(c), "client", property(lambda self: _FakeRedis()))

    messages = c.get_transcript("c1")
    assert messages == [
        {"role": "user", "content": "hello", "timestamp": "t1", "artifact_ids": []},
        {"role": "assistant", "content": "hi there", "timestamp": "t2", "artifact_ids": []},
    ]


def test_get_transcript_collapses_the_duplicate_final_report_turn(monkeypatch):
    """The client-agent logs each answer twice (``agent_response_*`` then
    ``final_report``) with identical content; the transcript must show it once."""
    import json as _json

    from app.conversation_state import ConversationStateClient

    conv = {
        "conversation_history": [
            {"role": "user", "content": "mesh it", "timestamp": "t1"},
            {"role": "assistant", "content": "done", "type": "agent_response_meshing", "timestamp": "t2"},
            {"role": "assistant", "content": "done", "type": "final_report", "timestamp": "t3"},
            {"role": "user", "content": "again", "timestamp": "t4"},
            # Same content as an earlier turn but NOT adjacent -> kept.
            {"role": "assistant", "content": "done", "type": "final_report", "timestamp": "t5"},
        ],
    }

    class _FakeRedis:
        def get(self, key):
            return _json.dumps(conv)

    c = ConversationStateClient("redis://x")
    monkeypatch.setattr(type(c), "client", property(lambda self: _FakeRedis()))

    assert c.get_transcript("c1") == [
        {"role": "user", "content": "mesh it", "timestamp": "t1", "artifact_ids": []},
        {"role": "assistant", "content": "done", "timestamp": "t2", "artifact_ids": []},
        {"role": "user", "content": "again", "timestamp": "t4", "artifact_ids": []},
        {"role": "assistant", "content": "done", "timestamp": "t5", "artifact_ids": []},
    ]


def test_get_transcript_collapses_duplicates_only_within_one_turn(monkeypatch):
    """Two turns can reply with the same text ("SVG artifact created successfully.").
    The client-agent tags each entry with its turn, and only one turn's own
    ``agent_response_*`` / ``final_report`` pair collapses; each turn keeps its ids.
    Untagged (legacy) entries keep the old adjacent-duplicate rule."""
    import json as _json

    from app.conversation_state import ConversationStateClient

    conv = {
        "conversation_history": [
            {"role": "assistant", "content": "done", "turn_id": "T1", "type": "agent_response_x"},
            {"role": "assistant", "content": "done", "turn_id": "T1", "type": "final_report", "artifact_ids": ["a1"]},
            {"role": "assistant", "content": "done", "turn_id": "T2", "type": "final_report", "artifact_ids": ["a2"]},
            {"role": "assistant", "content": "old", "type": "agent_response_x"},
            {"role": "assistant", "content": "old", "turn_id": "legacy", "type": "final_report"},
        ],
    }

    class _FakeRedis:
        def get(self, key):
            return _json.dumps(conv)

    c = ConversationStateClient("redis://x")
    monkeypatch.setattr(type(c), "client", property(lambda self: _FakeRedis()))

    assert [(m["content"], m["artifact_ids"]) for m in c.get_transcript("c1")] == [
        ("done", ["a1"]),
        ("done", ["a2"]),
        ("old", []),
    ]


def test_get_transcript_carries_each_turns_artifact_ids(monkeypatch):
    """The client-agent stamps a turn's artifact ids on its reply. They come through
    per message, and a collapsed duplicate keeps the ids of both copies (the stamp
    lands on the last copy, the ``final_report``)."""
    import json as _json

    from app.conversation_state import ConversationStateClient

    conv = {
        "conversation_history": [
            {"role": "user", "content": "mesh it", "timestamp": "t1"},
            {"role": "assistant", "content": "done", "type": "agent_response_meshing", "artifact_ids": ["m0"]},
            {"role": "assistant", "content": "done", "type": "final_report", "artifact_ids": ["m0", "m1", ""]},
            {"role": "user", "content": "again", "timestamp": "t4"},
            {"role": "assistant", "content": "no files", "type": "final_report", "timestamp": "t5"},
        ],
    }

    class _FakeRedis:
        def get(self, key):
            return _json.dumps(conv)

    c = ConversationStateClient("redis://x")
    monkeypatch.setattr(type(c), "client", property(lambda self: _FakeRedis()))

    assert [m["artifact_ids"] for m in c.get_transcript("c1")] == [[], ["m0", "m1"], [], []]


# --------------------------------------------------------------------------- #
# GET /{id}, PATCH /{id}, DELETE /{id}, POST /{id}/resume
# --------------------------------------------------------------------------- #


class _FakeDetailClient:
    """Stand-in for ConversationStateClient backing the per-conversation endpoints."""

    def __init__(self, *, conversations: dict, owners: dict):
        self._conversations = conversations
        self._owners = owners
        self._meta: dict = {}

    @property
    def available(self) -> bool:
        return True

    def owns(self, user_id: str, conv_id: str) -> bool:
        return self._owners.get(conv_id) == user_id

    def get_conversation(self, conv_id: str):
        return self._conversations.get(conv_id)

    def get_meta(self, conv_id: str) -> dict:
        return self._meta.get(conv_id, {})

    def set_title_override(self, conv_id: str, title: str) -> bool:
        self._meta.setdefault(conv_id, {})["title_override"] = title
        return True

    def set_hidden(self, conv_id: str, hidden: bool) -> bool:
        self._meta.setdefault(conv_id, {})["hidden"] = "1" if hidden else None
        return True

    def get_transcript(self, conv_id: str) -> list[dict]:
        conv = self._conversations.get(conv_id) or {}
        history = conv.get("conversation_history", []) or []
        return [
            {
                "role": e["role"],
                "content": e["content"],
                "timestamp": e.get("timestamp", ""),
                "artifact_ids": e.get("artifact_ids", []),
            }
            for e in history
            if isinstance(e, dict) and e.get("role") in ("user", "assistant") and e.get("content")
        ]

    def get_artifacts(self, conv_id: str) -> list[dict]:
        return []


def _detail_client(monkeypatch, *, conversations: dict, owners: dict) -> _FakeDetailClient:
    fake = _FakeDetailClient(conversations=conversations, owners=owners)
    monkeypatch.setattr(conversations_router, "ConversationStateClient", lambda _url: fake)
    return fake


def test_rename_requires_ownership(monkeypatch):
    _detail_client(monkeypatch, conversations={"c1": {}}, owners={"c1": "bob"})
    client = _authed_client(monkeypatch)  # issues a token for "alice"

    resp = client.patch("/api/conversations/c1", json={"title": "New title"})
    assert resp.status_code == 404


def test_rename_sets_title_override(monkeypatch):
    fake = _detail_client(monkeypatch, conversations={"c1": {}}, owners={"c1": "alice"})
    client = _authed_client(monkeypatch)

    resp = client.patch("/api/conversations/c1", json={"title": "New title"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "New title"
    assert fake.get_meta("c1")["title_override"] == "New title"


def test_rename_rejects_empty_title(monkeypatch):
    _detail_client(monkeypatch, conversations={"c1": {}}, owners={"c1": "alice"})
    client = _authed_client(monkeypatch)

    resp = client.patch("/api/conversations/c1", json={"title": "   "})
    assert resp.status_code == 422


def test_delete_requires_ownership(monkeypatch):
    _detail_client(monkeypatch, conversations={"c1": {}}, owners={"c1": "bob"})
    client = _authed_client(monkeypatch)

    resp = client.delete("/api/conversations/c1")
    assert resp.status_code == 404


def test_delete_soft_hides_without_touching_the_conversation_document(monkeypatch):
    fake = _detail_client(monkeypatch, conversations={"c1": {"user_query": "hi"}}, owners={"c1": "alice"})
    client = _authed_client(monkeypatch)

    resp = client.delete("/api/conversations/c1")
    assert resp.status_code == 204
    assert fake.get_meta("c1")["hidden"] == "1"
    assert fake.get_conversation("c1") == {"user_query": "hi"}  # untouched


def test_owned_conversation_with_empty_meta_is_found(monkeypatch, session_store):
    # Never renamed or deleted: the conv:meta hash is empty, and ``{}`` is falsy.
    # _owned_meta signals a miss with None, so the routes must not treat {} as one.
    conv = {"user_query": "hi", "conversation_history": [{"role": "user", "content": "hi"}]}
    fake = _detail_client(monkeypatch, conversations={"c1": conv}, owners={"c1": "alice"})
    client = _authed_client(monkeypatch)
    assert fake.get_meta("c1") == {}

    assert client.get("/api/conversations/c1").status_code == 200
    assert client.post("/api/conversations/c1/resume").status_code == 200
    assert client.get("/api/conversations/c1/tasks").status_code == 200


def test_soft_deleted_conversation_is_not_found_for_detail_or_resume(monkeypatch, session_store):
    # A tab that still remembers a deleted conversation's id must not reopen it on
    # reload, or the next turn is appended to a conversation the user deleted.
    conv = {"user_query": "hi", "conversation_history": [{"role": "user", "content": "hi"}]}
    _detail_client(monkeypatch, conversations={"c1": conv}, owners={"c1": "alice"})
    client = _authed_client(monkeypatch)

    assert client.delete("/api/conversations/c1").status_code == 204
    assert client.get("/api/conversations/c1").status_code == 404
    assert client.post("/api/conversations/c1/resume").status_code == 404


def test_resume_requires_ownership(monkeypatch):
    _detail_client(monkeypatch, conversations={"c1": {}}, owners={"c1": "bob"})
    client = _authed_client(monkeypatch)

    resp = client.post("/api/conversations/c1/resume")
    assert resp.status_code == 404


async def test_resume_rebinds_session_and_returns_transcript(monkeypatch, session_store):
    conv = {
        "user_query": "hello",
        "conversation_history": [
            {"role": "user", "content": "hello", "timestamp": "t1"},
            {"role": "assistant", "content": "hi there", "timestamp": "t2"},
        ],
    }
    _detail_client(monkeypatch, conversations={"c1": conv}, owners={"c1": "alice"})
    client = _authed_client(monkeypatch)

    resp = client.post("/api/conversations/c1/resume")
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversation_id"] == "c1"
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]

    session = await session_store.get("sid-conv")
    assert session is not None
    assert session.conversation_id == "c1"


async def test_resume_seeds_session_artifacts_with_the_catalog_it_read(monkeypatch, session_store):
    """``session.artifacts`` (what the session-scoped content route resolves against)
    is the catalog resume already read."""
    fake = _detail_client(monkeypatch, conversations={"c1": {}}, owners={"c1": "alice"})
    monkeypatch.setattr(fake, "get_artifacts", lambda conv_id: [{"artifact_id": "a1", "name": "n"}], raising=False)

    client = _authed_client(monkeypatch)

    assert client.post("/api/conversations/c1/resume").status_code == 200
    session = await session_store.get_or_create("sid-conv")
    assert session.conversation_id == "c1"
    assert [a["artifact_id"] for a in session.artifacts] == ["a1"]


async def test_detail_and_resume_leave_user_uploads_out_of_the_response(monkeypatch, session_store):
    """The Artifact Contract excludes ``user-upload`` entries from rendering, as the live
    turn does; a restored transcript must not show the user's own file in a reply. The
    session catalog keeps them, so the content proxy and later turns still resolve them."""
    catalog = [
        {"artifact_id": "up", "name": "qa-a.txt", "metadata": {"source": "user-upload"}},
        {"artifact_id": "gen", "name": "result.json"},
    ]
    fake = _detail_client(monkeypatch, conversations={"c1": {}}, owners={"c1": "alice"})
    monkeypatch.setattr(fake, "get_artifacts", lambda conv_id: [dict(a) for a in catalog], raising=False)

    client = _authed_client(monkeypatch)

    detail = client.get("/api/conversations/c1").json()
    assert [a["artifact_id"] for a in detail["artifacts"]] == ["gen"]

    resumed = client.post("/api/conversations/c1/resume").json()
    assert [a["artifact_id"] for a in resumed["artifacts"]] == ["gen"]
    session = await session_store.get_or_create("sid-conv")
    assert [a["artifact_id"] for a in session.artifacts] == ["up", "gen"]


def test_detail_messages_name_the_artifacts_each_turn_produced(monkeypatch):
    """A restored turn renders from its own ``artifact_ids``; each id resolves in the
    detail's ``artifacts``, which is a lookup table, not a rendering source."""
    conv = {
        "conversation_history": [
            {"role": "user", "content": "plot it"},
            {"role": "assistant", "content": "here", "artifact_ids": ["gen"]},
        ],
    }
    fake = _detail_client(monkeypatch, conversations={"c1": conv}, owners={"c1": "alice"})
    monkeypatch.setattr(
        fake, "get_artifacts", lambda conv_id: [{"artifact_id": "gen", "name": "plot.png"}], raising=False
    )

    body = _authed_client(monkeypatch).get("/api/conversations/c1").json()

    assert [m["artifact_ids"] for m in body["messages"]] == [[], ["gen"]]
    assert [a["artifact_id"] for a in body["artifacts"]] == ["gen"]
    assert [a["content_url"] for a in body["artifacts"]] == ["/api/conversations/c1/artifacts/gen/content"]


async def test_superseded_resume_does_not_rebind_or_seed_the_session(monkeypatch, session_store):
    """Click A (slow meshes), then B: the session must end on B whichever finishes last.

    Rebinds are ordered by ``bind_seq``: a resume of A that lands after B's newer
    rebind changes nothing.
    """
    fake = _detail_client(monkeypatch, conversations={"A": {}, "B": {}}, owners={"A": "alice", "B": "alice"})
    monkeypatch.setattr(
        fake, "get_artifacts", lambda conv_id: [{"artifact_id": f"{conv_id}-art", "name": "n"}], raising=False
    )

    # B's resume (a newer click) has already landed.
    await session_store.reset("sid-conv", "B", artifacts=[{"artifact_id": "B-art"}], bind_seq=20)
    client = _authed_client(monkeypatch)

    resp = client.post("/api/conversations/A/resume", json={"bind_seq": 10})
    assert resp.status_code == 200  # still answered; the frontend drops it as superseded

    session = await session_store.get_or_create("sid-conv")
    assert session.conversation_id == "B"
    assert session.artifacts == [{"artifact_id": "B-art"}]

    # And a resume that arrives late with an older seq cannot rebind at all.
    assert client.post("/api/conversations/A/resume", json={"bind_seq": 15}).status_code == 200
    assert (await session_store.get_or_create("sid-conv")).conversation_id == "B"


def test_get_artifact_reads_one_catalog_entry(monkeypatch):
    import json as _json

    from app.conversation_state import ConversationStateClient

    stored = {
        ("artifacts:conv:c1:by_id", "a1"): _json.dumps({"artifact_id": "a1"}),
        ("artifacts:conv:c1:by_id", "bad"): "{not json",
    }

    class _FakeRedis:
        def hget(self, key, field):
            return stored.get((key, field))

    c = ConversationStateClient("redis://x")
    monkeypatch.setattr(type(c), "client", property(lambda self: _FakeRedis()))

    assert c.get_artifact("c1", "a1") == {"artifact_id": "a1"}
    assert c.get_artifact("c1", "missing") is None
    assert c.get_artifact("c1", "bad") is None
    assert c.get_artifact("c2", "a1") is None
    assert c.get_artifact("", "a1") is None


def test_get_artifact_logs_why_a_lookup_failed(monkeypatch, caplog):
    """The route answers every miss with the same 404, so the log has to say when the
    cause was Valkey or a bad entry rather than an unknown id."""
    import logging

    from app.conversation_state import ConversationStateClient, logger

    stored = {"bad": "{not json", "list": "[1, 2]"}

    class _FakeRedis:
        def hget(self, key, field):
            return stored.get(field)

    up = ConversationStateClient("redis://x")
    monkeypatch.setattr(type(up), "client", property(lambda self: _FakeRedis()))
    with caplog.at_level(logging.WARNING, logger=logger.name):
        assert up.get_artifact("c1", "missing") is None
        assert caplog.records == []  # an unknown id is not worth a warning
        assert up.get_artifact("c1", "bad") is None
        assert up.get_artifact("c1", "list") is None
        monkeypatch.setattr(type(up), "client", property(lambda self: None))
        assert up.get_artifact("c1", "a1") is None

    messages = [r.getMessage() for r in caplog.records]
    assert messages == [
        "artifact bad of c1: unreadable catalog entry: Expecting property name enclosed in double quotes: "
        "line 1 column 2 (char 1)",
        "artifact list of c1: catalog entry is not an object",
        "artifact a1 of c1: Valkey unavailable",
    ]


async def test_detail_and_resume_do_not_convert_meshes(monkeypatch, session_store):
    """Reopening a conversation never waits on VTK: a mesh comes back as stored, with a
    ``mesh_url`` the viewer fetches when it scrolls into view."""
    from app.services.mesh import service as mesh_service

    from app import uri_resolver

    conversions: list[str] = []

    async def _record(*a, **_k):
        conversions.append(str(a[0]) if a else "?")
        return None

    # Every conversion downloads its source and runs the VTK pool, whichever code path
    # calls it. They are recorded, not made to raise: the shared conversion task logs
    # and swallows errors, so a raise would never reach this test.
    monkeypatch.setattr(uri_resolver, "resolve_to_local_path", _record)
    monkeypatch.setattr(mesh_service, "_convert_offloop", _record)
    mesh = {"artifact_id": "m1", "name": "block.e", "mime_type": "application/x-exodus", "uri": "file:///tmp/block.e"}
    fake = _detail_client(monkeypatch, conversations={"c1": {}}, owners={"c1": "alice"})
    monkeypatch.setattr(fake, "get_artifacts", lambda conv_id: [dict(mesh)], raising=False)
    client = _authed_client(monkeypatch)

    for resp in (client.get("/api/conversations/c1"), client.post("/api/conversations/c1/resume")):
        (artifact,) = resp.json()["artifacts"]
        assert artifact["json_body"] is None
        assert artifact["mesh_url"] == "/api/conversations/c1/artifacts/m1/mesh"
    assert conversions == []
