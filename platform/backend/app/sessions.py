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

"""Valkey-backed per-session state store.

Replaces Chainlit's ``cl.user_session``. Each entry is keyed by the JWT ``sid``
(one per login) and mirrors the keys the Chainlit app kept on ``cl.user_session``:

    cl.user_session key         SessionState field
    ------------------------    ------------------
    conversation_id             conversation_id
    artifacts                   artifacts
    backgrounded_task_ids       awaited_task_ids
    chat_profile                profile

State lives in Valkey, not in this process, so it survives a backend restart and is
identical across ``uvicorn --workers N`` (see ``backend/README.md``). Two keys per
session, both carrying the cookie's TTL, refreshed on every write — no reaper:

    session:{sid}           HASH  conversation_id, profile, consecutive_needs_info,
                                  artifacts (JSON array), bind_seq
    session:{sid}:awaited   SET   root task ids the session is waiting on

**:class:`SessionState` is a read-only snapshot.** It used to be the live object every
caller mutated in place (``session.awaited_task_ids.add(...)``,
``session.consecutive_needs_info += 1``), which only worked because there was exactly
one process holding exactly one copy. A snapshot cannot observe those, and silently
dropping a write is the worst possible failure here — so the dataclass is ``frozen``
and ``awaited_task_ids`` is a ``frozenset``. Every former mutation is now an explicit
``SessionStore`` coroutine below, and anything this migration missed raises
``FrozenInstanceError``/``AttributeError`` rather than quietly losing state.

:meth:`SessionStore.claim_task` deserves its own note: the exactly-once guarantee for
background-task completion used to be a check-then-discard against an in-process set,
safe only because of the single process. It is now a single ``SREM`` whose return count
*is* the claim — atomic, and correct across workers.

The same single-process assumption hid two check-then-write races, now closed in Valkey
itself rather than by re-reading first:

- **Per-conversation writes are guarded.** A chat turn's writes (the artifact catalog,
  an awaited task, the follow-up counter) belong to the conversation the turn was *sent*
  for. Each takes that ``conversation_id`` and applies only if the session is still bound
  to it, checked and written under one ``WATCH`` -- so a "New chat" or resume that lands
  mid-turn, on any worker, can't have its fresh state overwritten by the old
  conversation's response.
- **Rebinds are ordered.** :meth:`SessionStore.reset` takes the client's ``bind_seq`` and
  refuses one older than the last applied, so a slow resume that arrives after a newer
  click can't pull the session back to the conversation the user already left.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, cast

from fastapi import Request

from app.config import settings
from redis.asyncio.client import Pipeline
from redis.exceptions import WatchError
from redis.typing import FieldT

from app.redis_client import RedisClient

logger = logging.getLogger(__name__)


#: One ``session:{sid}`` hash field write. Keyed by ``redis.typing.FieldT`` rather than
#: ``str`` because ``Mapping`` is invariant in its key type, so ``dict[str, ...]`` is not
#: accepted by ``hset(mapping=...)``. Values stay narrow (``str``/``int``) so a
#: non-encodable one -- a list, a dataclass -- is caught here and not by redis-py at run
#: time; every field is stored as a string, ints included.
SessionFields = dict[FieldT, str | int]

# Bound on optimistic-transaction retries (see :meth:`SessionStore._guarded`). A retry
# only happens when another write to the same ``session:{sid}`` hash lands between our
# WATCH and EXEC -- one login's own concurrent requests -- so a handful is plenty; running
# out means something is hammering one hash, and failing loudly beats spinning.
_WATCH_RETRIES = 10


def _hash_key(sid: str) -> str:
    return f"session:{sid}"


def _awaited_key(sid: str) -> str:
    return f"session:{sid}:awaited"


def _turn_key(sid: str, turn_id: str) -> str:
    return f"session:{sid}:turn:{turn_id}"


# How long a chat turn's state outlives the turn. The agent call has no total time bound
# (``A2AClient``'s 900 s httpx timeout applies to each read of the stream), so this is sized
# for a long turn plus the time a client needs to reconnect and read the result.
TURN_TTL_SECONDS = 3600
# A running turn's state is a lease: the worker running the turn refreshes it every
# TURN_LEASE_REFRESH_SECONDS (routers/chat.py). If that worker dies mid-turn, nothing
# will ever finish the turn, so the state expires within TURN_LEASE_SECONDS and a lookup
# answers 404 instead of "running" for an hour.
TURN_LEASE_SECONDS = 60
TURN_LEASE_REFRESH_SECONDS = 20


@dataclass(frozen=True)
class SessionState:
    """Read-only snapshot of one logged-in browser session.

    Frozen on purpose: see the module docstring. To change session state, call the
    corresponding :class:`SessionStore` coroutine; assigning to a field here raises.
    """

    sid: str
    conversation_id: Optional[str] = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    awaited_task_ids: frozenset[str] = field(default_factory=frozenset)
    profile: str = ""
    # Count of consecutive ``needs_info`` turns, for the follow-up depth cap (T-2).
    # Incremented on each needs_info response, reset on any other terminal status.
    consecutive_needs_info: int = 0


def _decode_artifacts(raw: Optional[str]) -> list[dict[str, Any]]:
    """Parse the stored artifacts JSON, treating any corruption as "no catalog".

    A malformed value would only ever come from a hand-edited key or a half-written
    value, and the cost of tolerating it is that ``GET /api/artifacts/{id}/content``
    can't resolve ids until the next turn rewrites the catalog — far better than
    500-ing every request the session makes from then on.
    """
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("session: discarding unparseable artifacts catalog")
        return []
    return [a for a in parsed if isinstance(a, dict)] if isinstance(parsed, list) else []


class SessionStore:
    """Valkey-backed session registry keyed by ``sid``.

    Holds no state of its own beyond the client, so constructing one per request (or
    one per process, as ``main.py`` does) is equivalent.
    """

    def __init__(self, redis: RedisClient, *, ttl_seconds: Optional[int] = None) -> None:
        self._redis = redis
        # Session state is worthless once the cookie that names it has expired, so the
        # two keys carry the token TTL and are refreshed on every write.
        self._ttl = ttl_seconds if ttl_seconds is not None else settings.token_ttl_seconds

    # -- reads -------------------------------------------------------------- #

    async def get(self, sid: str) -> Optional[SessionState]:
        """Snapshot of ``sid``, or ``None`` if the session has no stored state."""
        pipe = self._redis.pipeline()
        pipe.hgetall(_hash_key(sid))
        pipe.smembers(_awaited_key(sid))
        fields, awaited = await pipe.execute()
        if not fields and not awaited:
            return None
        return self._snapshot(sid, fields or {}, awaited or set())

    async def get_or_create(self, sid: str) -> SessionState:
        """Snapshot of ``sid``, defaulting to an empty session.

        Nothing is written: Redis has no empty hash, so "registered but untouched"
        and "absent" are the same state, and both mean the defaults below. The login
        routes call this purely to assert the sid is usable.
        """
        state = await self.get(sid)
        return state if state is not None else SessionState(sid=sid)

    def _snapshot(self, sid: str, fields: dict[str, Any], awaited: Any) -> SessionState:
        try:
            needs_info = int(fields.get("consecutive_needs_info") or 0)
        except (TypeError, ValueError):
            needs_info = 0
        return SessionState(
            sid=sid,
            conversation_id=fields.get("conversation_id") or None,
            artifacts=_decode_artifacts(fields.get("artifacts")),
            awaited_task_ids=frozenset(str(t) for t in awaited),
            profile=fields.get("profile") or "",
            consecutive_needs_info=needs_info,
        )

    # -- writes ------------------------------------------------------------- #

    async def _write(self, sid: str, fields: SessionFields) -> None:
        pipe = self._redis.pipeline()
        pipe.hset(_hash_key(sid), mapping=fields)
        pipe.expire(_hash_key(sid), self._ttl)
        await pipe.execute()

    async def _guarded(
        self,
        sid: str,
        check: Callable[[dict[str, Any]], bool],
        queue_writes: Callable[[Pipeline], None],
    ) -> Optional[list[Any]]:
        """Run ``queue_writes`` in a transaction iff ``check(current hash)`` holds.

        Optimistic concurrency: ``WATCH session:{sid}``, read the hash, and if ``check``
        passes queue the writes in ``MULTI``/``EXEC``. Any write to the hash in between --
        a rebind on another worker included -- aborts the ``EXEC`` with ``WatchError``,
        and the check is re-run against the new state. Watching the hash alone covers
        writes to ``:awaited`` too, because the thing being guarded against (a rebind)
        always rewrites ``conversation_id``.

        Returns the ``EXEC`` results, or ``None`` when ``check`` failed and nothing was
        written.
        """
        key = _hash_key(sid)
        async with self._redis.pipeline(transaction=True) as pipe:
            for _ in range(_WATCH_RETRIES):
                try:
                    await pipe.watch(key)
                    # decode_responses=True: fields and values are str.
                    current = cast(dict[str, Any], await pipe.hgetall(key))
                    if not check(current or {}):
                        await pipe.unwatch()
                        return None
                    pipe.multi()
                    queue_writes(pipe)
                    return cast(list[Any], await pipe.execute())
                except WatchError:
                    continue
        raise WatchError(f"session:{sid} kept changing; gave up after {_WATCH_RETRIES} attempts")

    async def _write_for(
        self, sid: str, conversation_id: str, queue_writes: Callable[[Pipeline], None]
    ) -> Optional[list[Any]]:
        """:meth:`_guarded` on "the session is still bound to ``conversation_id``"."""
        return await self._guarded(sid, lambda current: current.get("conversation_id") == conversation_id, queue_writes)

    async def ensure_conversation(self, sid: str, candidate: str) -> str:
        """Bind ``sid`` to ``candidate`` unless it is already bound; return the binding.

        ``HSETNX`` then ``HGET`` in one transaction, so concurrent first requests -- the
        frontend uploads every selected file in parallel -- all agree on a single id
        instead of each minting its own and staging files under different conversations.
        """
        pipe = self._redis.pipeline(transaction=True)
        pipe.hsetnx(_hash_key(sid), "conversation_id", candidate)
        pipe.expire(_hash_key(sid), self._ttl)
        pipe.hget(_hash_key(sid), "conversation_id")
        _set, _expire, stored = await pipe.execute()
        return str(stored)

    async def set_profile(self, sid: str, profile: str) -> None:
        await self._write(sid, {"profile": profile})

    async def set_artifacts(self, sid: str, artifacts: list[dict[str, Any]], *, conversation_id: str) -> bool:
        """Replace ``conversation_id``'s artifact catalog (task 07 resolves ids from it).

        A no-op returning ``False`` if the session has since moved to another conversation.
        """

        def queue(pipe: Pipeline) -> None:
            pipe.hset(_hash_key(sid), "artifacts", json.dumps(artifacts))
            pipe.expire(_hash_key(sid), self._ttl)

        return await self._write_for(sid, conversation_id, queue) is not None

    async def replace_seeded_artifacts(
        self,
        sid: str,
        artifacts: list[dict[str, Any]],
        *,
        conversation_id: str,
        seeded: list[dict[str, Any]],
    ) -> bool:
        """Replace the catalog :meth:`reset` seeded with ``seeded`` by ``artifacts``.

        Stricter than :meth:`set_artifacts`: it also skips (``False``) when the stored
        catalog is no longer the one ``reset`` wrote. A turn or a backgrounded task of the
        same conversation that finishes in between writes a newer catalog, and an older
        enriched list must not replace it. ``seeded`` must be the list as ``reset`` got it,
        before any in-place enrichment.
        """
        expected = json.dumps(seeded)

        def unchanged(current: dict[str, Any]) -> bool:
            return current.get("conversation_id") == conversation_id and current.get("artifacts") == expected

        def queue(pipe: Pipeline) -> None:
            pipe.hset(_hash_key(sid), "artifacts", json.dumps(artifacts))
            pipe.expire(_hash_key(sid), self._ttl)

        return await self._guarded(sid, unchanged, queue) is not None

    async def reset(
        self,
        sid: str,
        conversation_id: str,
        *,
        profile: Optional[str] = None,
        artifacts: Optional[list[dict[str, Any]]] = None,
        bind_seq: Optional[int] = None,
    ) -> bool:
        """Rebind the session to a conversation, clearing per-conversation state.

        The "New chat" / history-resume path: a different conversation starts with no
        artifact catalog, no awaited background tasks and no follow-up depth. One
        transaction so a concurrent reader can't see the new conversation id alongside
        the old conversation's artifacts.

        ``bind_seq`` orders rebinds by when the user *clicked*, not by when the request
        happened to finish: the frontend stamps each New chat / resume with a strictly
        increasing value, and a rebind whose seq is not greater than the last applied one
        is dropped (returns ``False``). Without it, a slow resume of conversation A that
        completes after a newer click on B rebinds the session back to A, and B's next
        turn is appended to A. ``None`` (tests, internal callers) always applies and
        leaves the stored seq alone.

        ``artifacts`` seeds the catalog in the same transaction -- the resume path already
        holds the list and would otherwise write ``[]`` and immediately overwrite it,
        leaving a window where the content proxy 404s every artifact.

        The awaited-task set is kept when rebinding to the conversation the session is
        *already* on (the reload path: a task backgrounded before the reload still streams
        into the resumed session) and cleared otherwise: the set holds root task ids, and
        every lookup of one (``task_events.fetch_result``, the subscriber's channel) is
        scoped by conversation id, so an id carried across a switch would resolve against
        the wrong conversation. That is decided inside the transaction, against the
        binding it is about to replace, not against a snapshot a caller read earlier.
        """
        fields: SessionFields = {
            "conversation_id": conversation_id,
            "artifacts": json.dumps(artifacts if artifacts is not None else []),
            "consecutive_needs_info": 0,
        }
        if profile is not None:
            fields["profile"] = profile
        if bind_seq is not None:
            fields["bind_seq"] = bind_seq

        same_conversation = False

        def newer(current: dict[str, Any]) -> bool:
            nonlocal same_conversation
            same_conversation = current.get("conversation_id") == conversation_id
            if bind_seq is None:
                return True
            try:
                return bind_seq > int(current.get("bind_seq") or 0)
            except (TypeError, ValueError):
                return True  # a corrupt seq must not wedge the session on one conversation

        def queue(pipe: Pipeline) -> None:
            pipe.hset(_hash_key(sid), mapping=fields)
            pipe.expire(_hash_key(sid), self._ttl)
            if not same_conversation:
                pipe.delete(_awaited_key(sid))

        return await self._guarded(sid, newer, queue) is not None

    async def drop(self, sid: str) -> None:
        """Forget a session (e.g. on logout). Idempotent."""
        await self._redis.delete(_hash_key(sid), _awaited_key(sid))

    # -- follow-up depth cap (T-2) ------------------------------------------ #

    async def bump_needs_info(self, sid: str, *, conversation_id: str) -> Optional[int]:
        """Increment and return ``conversation_id``'s consecutive-``needs_info`` counter.

        ``None`` if the session has moved to another conversation; that one's counter is
        left alone.
        """

        def queue(pipe: Pipeline) -> None:
            pipe.hincrby(_hash_key(sid), "consecutive_needs_info", 1)
            pipe.expire(_hash_key(sid), self._ttl)

        results = await self._write_for(sid, conversation_id, queue)
        return None if results is None else int(results[0])

    async def reset_needs_info(self, sid: str, *, conversation_id: str) -> None:
        def queue(pipe: Pipeline) -> None:
            pipe.hset(_hash_key(sid), "consecutive_needs_info", 0)
            pipe.expire(_hash_key(sid), self._ttl)

        await self._write_for(sid, conversation_id, queue)

    # -- awaited background tasks ------------------------------------------- #

    async def await_task(self, sid: str, task_id: str, *, conversation_id: str) -> bool:
        """Register a backgrounded root task id of ``conversation_id`` (``SADD``).

        Skipped (``False``) if the session has moved on: the awaited set is scoped to the
        current conversation (see :meth:`reset`), and an id from another one would make
        this session wait on a task it never started.
        """

        def queue(pipe: Pipeline) -> None:
            pipe.sadd(_awaited_key(sid), task_id)
            pipe.expire(_awaited_key(sid), self._ttl)

        return await self._write_for(sid, conversation_id, queue) is not None

    async def claim_task(self, sid: str, task_id: str) -> bool:
        """Atomically consume ``task_id``; ``True`` for exactly one caller.

        ``SREM`` returns the number of members actually removed, so the winner of a
        race between the subscriber loop, the fast-finish guard and the router's
        reconcile gets ``1`` and everyone else gets ``0``. Pair a ``False`` return
        with "someone else announced it", and restore a claim you could not honour
        with :meth:`await_task`.
        """
        removed = await self._redis.srem(_awaited_key(sid), task_id)
        return bool(removed)

    async def is_awaiting(self, sid: str, task_id: str) -> bool:
        """Whether ``task_id`` is still awaited. A hint only — :meth:`claim_task` is
        the authority, since this can go stale the moment it returns."""
        return bool(await self._redis.sismember(_awaited_key(sid), task_id))

    # -- chat turns (delivery by turn id) ----------------------------------- #

    async def start_turn(self, sid: str, turn_id: str) -> bool:
        """Record ``turn_id`` as running; ``False`` if this session already used that id.

        ``SET NX`` makes a retried POST with the same id lose the race instead of running
        the agent a second time.
        """
        created = await self._redis.set(
            _turn_key(sid, turn_id), json.dumps({"state": "running"}), nx=True, ex=TURN_LEASE_SECONDS
        )
        return bool(created)

    async def renew_turn(self, sid: str, turn_id: str) -> None:
        """Extend a running turn's lease. Only the turn's own worker calls this, and it
        stops before :meth:`finish_turn`, so it never shortens a stored result."""
        await self._redis.expire(_turn_key(sid, turn_id), TURN_LEASE_SECONDS)

    async def finish_turn(self, sid: str, turn_id: str, response: dict[str, Any]) -> None:
        """Store the turn's final (mapped) response, for a client that lost the POST reply."""
        value = json.dumps({"state": "done", "response": response})
        await self._redis.set(_turn_key(sid, turn_id), value, ex=TURN_TTL_SECONDS)

    async def get_turn(self, sid: str, turn_id: str) -> Optional[dict[str, Any]]:
        """``{"state": "running"}`` or ``{"state": "done", "response": {...}}``; ``None`` if
        this session has no such turn (never started, expired, or another session's)."""
        raw = await self._redis.get(_turn_key(sid, turn_id))
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("session: discarding unparseable turn state for %s", turn_id)
            return None
        return parsed if isinstance(parsed, dict) else None


def get_store(request: Request) -> SessionStore:
    """Look up the process-wide :class:`SessionStore` off app state.

    Shared by every router that touches session state, so there's one place that
    knows where it lives.
    """
    return cast(SessionStore, request.app.state.session_store)
