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

"""Conversation state persistence for the client-agent.

A conversation is one ``conversation:{id}`` JSON document. Several turns of one
conversation can run at once: a turn detached to the background keeps running while
the user sends the next one, and each ``chat()`` works on the copy it read when it
started. So a store never overwrites the document wholesale:

- Every history entry carries the ``turn_id`` of the turn that wrote it. An entry is
  tagged when it is first stored (``store_conversation``), and an untagged entry read
  back is a legacy one (``LEGACY_TURN_ID``). So an untagged entry at store time was
  written by the current turn.
- A store merges (``merge_conversation``): the turn's own entries come from its copy,
  every other turn's from the stored document, interleaved by timestamp. The other
  top-level fields belong to the newest-*started* turn, so a background turn that
  finishes late cannot wipe the plan or form a newer turn left pending. The one
  exception: a late turn that leaves pending input (a form, a plan to approve) takes
  the fields from a newer turn that left none, because its form is what the user
  answers next.
- The LLM transcript (``llm_messages``) is merged by turn too: each message carries
  the ``turn_id`` and ``turn_started_at`` of the turn that wrote it, and each turn's
  messages stay one contiguous block, ordered by when the turn started.
- ``record_turn_artifacts`` stamps the ids of the artifacts a turn produced on that
  turn's reply, which a restored conversation renders from.

Both writes are one ``WATCH``/``MULTI`` transaction on the document.
"""

import json
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

import redis
from prometheus_api.redis_utils import create_redis_client

#: ``turn_id`` of a history entry stored before entries were tagged.
LEGACY_TURN_ID = "legacy"

_conversation_store_client: Optional[redis.Redis] = None


def _get_conversation_store_client() -> redis.Redis:
    """Get or create the singleton Redis client for conversation storage."""
    global _conversation_store_client
    if _conversation_store_client is None:
        _conversation_store_client = create_redis_client(ping=False)
        if _conversation_store_client is None:
            raise RuntimeError("Redis client could not be created; check REDIS_URL/REDIS_PASSWORD")
    return _conversation_store_client


def _key(conv_id: str) -> str:
    return f"conversation:{conv_id}"


def _history(state: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    history = (state or {}).get("conversation_history")
    return [e for e in history if isinstance(e, dict)] if isinstance(history, list) else []


def _messages(state: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    messages = (state or {}).get("llm_messages")
    return [m for m in messages if isinstance(m, dict)] if isinstance(messages, list) else []


def _tag_legacy(state: Dict[str, Any]) -> Dict[str, Any]:
    for entry in _history(state):
        entry.setdefault("turn_id", LEGACY_TURN_ID)
    for message in _messages(state):
        message.setdefault("turn_id", LEGACY_TURN_ID)
        message.setdefault("turn_started_at", 0.0)
    return state


def _merge_messages(
    stored: List[Dict[str, Any]],
    local: List[Dict[str, Any]],
    *,
    turn_id: str,
    started_at: float,
) -> List[Dict[str, Any]]:
    """Every other turn's messages from *stored*, this turn's from *local*, as one
    contiguous block placed before the first other turn that started later."""
    others = [m for m in stored if m.get("turn_id") != turn_id]
    mine = [m for m in local if m.get("turn_id") == turn_id]
    position = len(others)
    for index, message in enumerate(others):
        if float(message.get("turn_started_at") or 0) > started_at:
            position = index
            break
    return others[:position] + mine + others[position:]


def _current_turn() -> tuple[str, float]:
    """The current turn's id and start time; a one-off pair outside a turn."""
    from orchestrator import task_tracking  # lazy: task_tracking imports task_graph

    turn = task_tracking.current_turn()
    if turn is not None:
        return turn.turn_id, turn.started_at
    return task_tracking.new_turn_id(), time.time()


def _leaves_pending_input(state: Dict[str, Any]) -> bool:
    """Whether *state* waits on the user: a form, a specialist's input request, or a
    plan to approve (unfinished ``pending_calls``, which ``chat_flow.chat`` resumes)."""
    return bool(state.get("missing_info") or state.get("pending_calls") or state.get("awaiting_approval"))


def merge_conversation(
    stored: Optional[Dict[str, Any]],
    local: Dict[str, Any],
    *,
    turn_id: str,
    started_at: float,
) -> Dict[str, Any]:
    """The document to store when turn *turn_id* stores *local* over *stored*.

    History: every other turn's entries come from *stored*, which is authoritative
    for them (their ``artifact_ids`` included); this turn's come from *local*. The
    two lists are interleaved by ``timestamp``, each keeping its own order, so a
    background reply lands after the turns that ran meanwhile, as it did live.

    Other fields: *local*'s, unless *stored*'s ``state_turn_id`` names a turn that
    started after this one; then *stored*'s are kept and only the history and LLM
    transcript change (``llm_messages`` merges per turn like history; see
    :func:`_merge_messages`).
    Except when this turn leaves pending input and that newer one left none: the
    user answers this turn's form next, and ``chat()`` reads it from these fields.
    If both left pending input, the newer one wins, and the older form is lost. A
    title is never cleared.
    """
    from orchestrator.agent_loop import trim_transcript

    if not stored:
        merged = dict(local)
        merged["state_turn_id"] = turn_id
        merged["state_turn_started_at"] = started_at
        return merged

    others = [e for e in _history(stored) if e.get("turn_id") != turn_id]
    mine = [e for e in _history(local) if e.get("turn_id") == turn_id]
    history: List[Dict[str, Any]] = []
    i = j = 0
    while i < len(others) or j < len(mine):
        if j >= len(mine):
            history.append(others[i])
            i += 1
        elif i >= len(others):
            history.append(mine[j])
            j += 1
        else:
            mine_at = str(mine[j].get("timestamp") or "")
            other_at = str(others[i].get("timestamp") or "")
            if mine_at and other_at and mine_at < other_at:
                history.append(mine[j])
                j += 1
            else:
                history.append(others[i])
                i += 1

    newer_owner = (
        stored.get("state_turn_id") not in (None, turn_id)
        and float(stored.get("state_turn_started_at") or 0) > started_at
    )
    if newer_owner and _leaves_pending_input(local) and not _leaves_pending_input(stored):
        newer_owner = False
    if newer_owner:
        merged = dict(stored)
    else:
        merged = dict(local)
        merged["state_turn_id"] = turn_id
        merged["state_turn_started_at"] = started_at
        if not merged.get("title") and stored.get("title"):
            merged["title"] = stored["title"]
    merged["conversation_history"] = history
    # Other turns' messages come back from storage, so bound the merged transcript too.
    merged["llm_messages"] = trim_transcript(
        _merge_messages(_messages(stored), _messages(local), turn_id=turn_id, started_at=started_at)
    )
    return merged


def _update_conversation(
    conv_id: str,
    mutate: Callable[[Optional[Dict[str, Any]]], Optional[Dict[str, Any]]],
) -> None:
    """Read, *mutate* and write ``conversation:{id}`` in one ``WATCH`` transaction,
    retried when another writer gets in between. *mutate* returns ``None`` to skip
    the write."""
    key = _key(conv_id)

    def _apply(pipe: Any) -> None:
        raw = pipe.get(key)
        stored = _tag_legacy(json.loads(raw)) if raw else None
        updated = mutate(stored)
        if updated is None:
            return
        pipe.multi()
        pipe.set(key, json.dumps(updated, default=str))

    _get_conversation_store_client().transaction(_apply, key)


def store_conversation(conv_id: str, state: Dict[str, Any]) -> None:
    """Persist *state* as the current turn's view of the conversation.

    Tags the turn's new history entries and LLM messages in place (so later stores of
    the same turn agree), then merges with what is stored; see
    :func:`merge_conversation`.
    """
    turn_id, started_at = _current_turn()
    for entry in _history(state):
        entry.setdefault("turn_id", turn_id)
    for message in _messages(state):
        message.setdefault("turn_id", turn_id)
        message.setdefault("turn_started_at", started_at)
    _update_conversation(
        conv_id,
        lambda stored: merge_conversation(stored, state, turn_id=turn_id, started_at=started_at),
    )


def get_conversation(conv_id: str) -> Optional[Dict[str, Any]]:
    """Load a conversation state document. Untagged history entries are legacy."""
    data = _get_conversation_store_client().get(_key(conv_id))
    return _tag_legacy(json.loads(data)) if data else None


def stamp_turn_artifacts(
    history: List[Dict[str, Any]],
    turn_id: str,
    artifact_ids: Sequence[str],
) -> bool:
    """Record on turn *turn_id*'s reply which artifacts that turn produced.

    A restored conversation renders each turn from these ids, never from the whole
    conversation catalog (Prometheus Artifact Contract, "Frontend viewer ownership").
    The target is the turn's last assistant entry with content: its ``final_report``
    when there is one, which the transcript collapses with the matching
    ``agent_response_*`` entry, so each id renders once. A turn with no such entry (a
    follow-up question, a plan rejection) gets no stamp; the live reply showed no
    artifacts either. Ids already on the entry are kept. Returns whether *history*
    changed.
    """
    ids = [str(i) for i in artifact_ids if i]
    if not ids or not turn_id:
        return False
    replies = [
        e for e in history
        if isinstance(e, dict)
        and e.get("role") == "assistant"
        and e.get("turn_id") == turn_id
        and e.get("content")
    ]
    if not replies:
        return False
    entry = replies[-1]
    existing = [str(i) for i in entry.get("artifact_ids") or []]
    merged = existing + [i for i in ids if i not in existing]
    if merged == existing:
        return False
    entry["artifact_ids"] = merged
    return True


def record_turn_artifacts(conv_id: str, turn_id: str, artifact_ids: Sequence[str]) -> None:
    """Stamp *artifact_ids* on turn *turn_id*'s reply in ``conversation:{id}``.

    Runs after the turn's last :func:`store_conversation`, so no later store of the
    same turn replaces the stamp. See :func:`stamp_turn_artifacts`.
    """
    ids = [str(i) for i in artifact_ids if i]
    if not ids or not turn_id:
        return

    def _stamp(stored: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not stored:
            return None
        history = stored.get("conversation_history")
        if isinstance(history, list) and stamp_turn_artifacts(history, turn_id, ids):
            return stored
        return None

    _update_conversation(conv_id, _stamp)
