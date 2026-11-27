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

"""Redis-backed client for browsing and lightly editing persisted conversation state.

The client-agent owns the ``conversation:{id}`` document (the full orchestration
state, merged by turn on every store — see ``agents/client-agent/conversation_store.py``).
This client never writes to it. User-driven edits (rename, soft delete) instead
live on a small, backend-owned ``conv:meta:{id}`` hash: writing there can never be
clobbered by a client-agent store, and the client-agent never needs to know these
edits exist.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import settings

try:
    import redis
except ImportError:  # pragma: no cover - only when redis is absent
    redis = None  # type: ignore


logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationStateClient:
    """Client for persisted conversation state: reads + small metadata writes."""

    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._client = None

    @property
    def client(self):
        if self._client is not None:
            return self._client
        if redis is None:
            return None
        try:
            self._client = redis.Redis.from_url(self._redis_url, decode_responses=True)
            self._client.ping()
            return self._client
        except Exception:
            self._client = None
            return None

    @property
    def available(self) -> bool:
        return self.client is not None

    # --------------------------------------------------------------------- #
    # Ownership
    # --------------------------------------------------------------------- #

    def owns(self, user_id: str, conv_id: str) -> bool:
        """Whether *conv_id* is in *user_id*'s conversation index.

        Backs every per-conversation endpoint (fetch/rename/delete/resume) so
        one user can never act on another's conversation. Fails closed (``False``)
        on a missing client, empty ids, or a Redis error.
        """
        client = self.client
        if client is None or not user_id or not conv_id:
            return False
        try:
            return bool(client.sismember(f"user:convs:{user_id}", conv_id))
        except Exception:
            return False

    # --------------------------------------------------------------------- #
    # Raw conversation document + derived views
    # --------------------------------------------------------------------- #

    def get_conversation(self, conv_id: str) -> Optional[Dict[str, Any]]:
        """Load the raw ``conversation:{id}`` document, or ``None``."""
        client = self.client
        if client is None:
            return None
        try:
            data = client.get(f"conversation:{conv_id}")
            return json.loads(data) if data else None
        except Exception:
            return None

    def get_transcript(self, conv_id: str) -> List[Dict[str, Any]]:
        """Normalized user/assistant turns from ``conversation_history``.

        The stored history is an orchestration/evidence log — routing decisions,
        tool results, and follow-up bookkeeping are mixed in with real chat
        turns. This keeps only entries with a ``role`` of ``user``/``assistant``
        and non-empty ``content``, in stored order (time order: the client-agent
        interleaves concurrent turns by timestamp), as ``{role, content, timestamp,
        artifact_ids}``.

        Consecutive entries of the same turn with the same role *and* identical
        content collapse to one. The client-agent logs each answer twice — once as
        ``type: agent_response_<tool>`` and again as ``type: final_report``, with the
        same ``content`` — so without this every restored assistant turn would appear
        duplicated. Only *adjacent* repeats of *one* turn (same ``turn_id``, or both
        untagged) are dropped: a genuinely repeated answer later in the conversation,
        or two turns that both answer "Done.", still show up. A collapsed entry keeps
        the ``artifact_ids`` of both copies.

        ``artifact_ids`` are the artifacts that turn produced, stamped on the reply by
        the client-agent (``conversation_store.stamp_turn_artifacts``). A restored turn
        renders exactly these; a turn stored before the stamp existed has none.
        """
        conv = self.get_conversation(conv_id)
        if not conv:
            return []
        history = conv.get("conversation_history", []) or []
        messages: List[Dict[str, Any]] = []
        turns: List[str] = []  # turn_id per message, for the collapse rule only
        for entry in history:
            if not isinstance(entry, dict):
                continue
            role = entry.get("role")
            content = entry.get("content")
            if role not in ("user", "assistant") or not content:
                continue
            text = str(content)
            ids = [str(i) for i in entry.get("artifact_ids") or [] if i]
            turn = str(entry.get("turn_id") or "legacy")
            if messages and turns[-1] == turn and messages[-1]["role"] == role and messages[-1]["content"] == text:
                kept = messages[-1]["artifact_ids"]
                kept.extend(i for i in ids if i not in kept)
                continue
            turns.append(turn)
            messages.append(
                {
                    "role": role,
                    "content": text,
                    "timestamp": entry.get("timestamp", ""),
                    "artifact_ids": ids,
                }
            )
        return messages

    def get_artifacts(self, conv_id: str) -> List[Dict[str, Any]]:
        """Raw artifact catalog dicts for *conv_id* (best-effort; ``[]`` on any issue).

        Reads the same Redis hash the client-agent's ``ArtifactRegistry`` writes
        (``artifacts:conv:{id}:by_id``, ``ArtifactReference.to_dict()`` values), so
        resume can rehydrate a session's artifact catalog without a round-trip
        through the client-agent.
        """
        client = self.client
        if client is None:
            return []
        try:
            raw = client.hgetall(f"artifacts:conv:{conv_id}:by_id")
        except Exception:
            return []
        artifacts: List[Dict[str, Any]] = []
        for value in (raw or {}).values():
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError):
                continue
            if isinstance(parsed, dict):
                artifacts.append(parsed)
        return artifacts

    def get_artifact(self, conv_id: str, artifact_id: str) -> Optional[Dict[str, Any]]:
        """One raw catalog dict from ``artifacts:conv:{conv_id}:by_id``, or ``None``.

        ``None`` also on a missing client, empty ids, a Redis error or a corrupt value,
        so the content route maps every miss to the same 404.
        """
        if not conv_id or not artifact_id:
            return None
        client = self.client
        if client is None:
            # Logged because the caller's 404 can't say that Valkey, not the id, failed.
            logger.warning("artifact %s of %s: Valkey unavailable", artifact_id, conv_id)
            return None
        try:
            raw = client.hget(f"artifacts:conv:{conv_id}:by_id", artifact_id)
            parsed = json.loads(raw) if raw else None
        except Exception as exc:
            logger.warning("artifact %s of %s: unreadable catalog entry: %s", artifact_id, conv_id, exc)
            return None
        if raw and not isinstance(parsed, dict):
            logger.warning("artifact %s of %s: catalog entry is not an object", artifact_id, conv_id)
            return None
        return parsed

    # --------------------------------------------------------------------- #
    # Per-user metadata (title override / soft delete) — ``conv:meta:{id}``
    # --------------------------------------------------------------------- #

    def get_meta(self, conv_id: str) -> Dict[str, Any]:
        client = self.client
        if client is None:
            return {}
        try:
            return dict(client.hgetall(f"conv:meta:{conv_id}") or {})
        except Exception:
            return {}

    def set_title_override(self, conv_id: str, title: str) -> bool:
        """User-chosen rename. Takes precedence over the LLM-generated title."""
        client = self.client
        if client is None:
            return False
        try:
            client.hset(f"conv:meta:{conv_id}", "title_override", title)
            return True
        except Exception:
            return False

    def is_pending(self, conv_id: str) -> bool:
        """Whether a turn is actively running against *conv_id* right now.

        Reads ``agent:status:{id}`` — written by the client-agent's
        ``runtime.store_status_update`` on every status update, with a
        ``final`` flag (``False`` while a turn is in progress, ``True`` at
        every terminal branch) and a 900s TTL. The TTL means a stalled or
        crashed turn self-heals to "not pending" rather than showing pending
        forever; no new write path is needed since the client-agent already
        emits this for its own live-status SSE stream.
        """
        client = self.client
        if client is None:
            return False
        try:
            raw = client.get(f"agent:status:{conv_id}")
            if not raw:
                return False
            data = json.loads(raw)
            return not bool(data.get("final", True))
        except Exception:
            return False

    def set_hidden(self, conv_id: str, hidden: bool) -> bool:
        """Soft delete/undelete: hidden conversations drop out of ``recent``, and
        detail and resume answer 404 for them (see ``routers/conversations.py``). The
        underlying ``conversation:{id}`` document is left untouched."""
        client = self.client
        if client is None:
            return False
        try:
            if hidden:
                client.hset(
                    f"conv:meta:{conv_id}",
                    mapping={"hidden": "1", "hidden_at": _utc_now_iso()},
                )
            else:
                client.hdel(f"conv:meta:{conv_id}", "hidden", "hidden_at")
            return True
        except Exception:
            return False

    # --------------------------------------------------------------------- #
    # Recent-conversations listing
    # --------------------------------------------------------------------- #

    def get_conversation_history(
        self,
        limit: int = 20,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve recent conversation summaries from Redis.

        When *user_id* is provided, only conversations owned by that user are
        returned (via the ``user:convs:{user_id}`` index populated by
        ``prometheus_api.agent.ownership.record_conversation_owner`` on the
        client-agent side). When *user_id* is absent, falls back to the global
        ``conversation:*`` scan — used only for conversations created before
        ownership tracking existed, or when identity is unconfigured.

        Soft-deleted conversations (``conv:meta:{id}.hidden``) are excluded.
        ``title`` is the effective title: a user rename (``title_override``)
        wins over the client-agent's LLM-generated ``title``, which wins over
        the raw first query. ``pending`` reflects whether a turn is actively
        running against that conversation right now (see :meth:`is_pending`).
        """
        client = self.client
        if client is None:
            return []
        try:
            if user_id:
                try:
                    conv_ids = client.smembers(f"user:convs:{user_id}")
                    keys = [f"conversation:{cid}" for cid in (conv_ids or [])]
                except Exception:
                    keys = []
            else:
                keys = client.keys("conversation:*")
            conversations = []
            # AU-2: build summaries for ALL keys, then sort by timestamp, then slice —
            # ``keys(...)`` is unordered, so the old slice-before-sort could drop the
            # newest conversations. (On a very large keyspace this should move to a
            # sorted-set index; adequate for the current bounded history use.)
            for key in keys:
                data = client.get(key)
                if not data:
                    continue
                conv = json.loads(data)
                conv_id = key.split(":", 1)[1] if ":" in key else key
                meta = self.get_meta(conv_id)
                if meta.get("hidden"):
                    continue
                history = conv.get("conversation_history", []) or []
                latest_entry = history[-1] if history else {}
                query = conv.get("user_query", "")
                title = meta.get("title_override") or conv.get("title") or query
                conversations.append(
                    {
                        "conversation_id": conv_id,
                        "title": title,
                        "query": query,
                        "status": self._infer_status(conv),
                        "timestamp": latest_entry.get("timestamp", ""),
                        "pending": self.is_pending(conv_id),
                    }
                )
            conversations.sort(key=lambda c: c.get("timestamp", ""), reverse=True)
            return conversations[:limit]
        except Exception:
            return []

    @staticmethod
    def _infer_status(conversation: Dict[str, Any]) -> str:
        """Infer a user-facing status from persisted state."""
        if conversation.get("final_report"):
            return "completed"
        if conversation.get("awaiting_approval"):
            return "plan_ready"
        if conversation.get("missing_info"):
            return "needs_info"
        return "unknown"


# One client per class, reused across requests and routers (AU-7): a client caches its
# Redis connection, so sharing one avoids a fresh connect + ping per call. Keyed on the
# class object a caller passes (not id()), so a test that monkeypatches
# ``ConversationStateClient`` in one router module gets its own instance, and the class
# is kept alive as the key.
_shared_clients: dict[type, ConversationStateClient] = {}


def shared_client(cls: type[ConversationStateClient] = ConversationStateClient) -> ConversationStateClient:
    """The process-wide ``cls`` instance for ``settings.redis_url``."""
    inst = _shared_clients.get(cls)
    if inst is None:
        inst = cls(settings.redis_url)
        _shared_clients[cls] = inst
    return inst
