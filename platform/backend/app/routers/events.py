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

"""GET /api/events — the per-session SSE stream (decision D2).

One long-lived ``text/event-stream`` per browser session. It multiplexes two
producers onto a single connection:

- ``status`` frames for the in-flight turn (published by ``routers/chat.py`` via
  the :class:`~app.services.events.EventBus`), replacing Chainlit's ``cl.Step``.
- ``task_progress`` / ``task_done`` frames for backgrounded tasks, produced by the
  Redis subscriber this endpoint owns for the connection's lifetime
  (:func:`~app.services.events.run_task_subscriber`).

The subscriber task is started on connect and cancelled on disconnect so a closed
browser tab never leaks a Redis subscription. Heartbeat comments keep intermediaries
(and the browser's ``EventSource``) from timing the idle connection out.

Infra note: this route must not be buffered — nginx needs ``proxy_buffering off``
and a long ``proxy_read_timeout`` (task 09).
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status as http_status
from fastapi.responses import StreamingResponse

from app.api_responses import AUTH_RESPONSES
from app.config import settings
from app.contract import ServerEvent
from app.redis_client import RedisClient, get_redis
from app.security import TokenClaims, current_claims
from app.services.events import EventBus, StreamItem, run_task_subscriber
from app.sessions import SessionStore, get_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["events"], responses=AUTH_RESPONSES)

# Idle heartbeat cadence (seconds). Sent as an SSE comment when no real event
# arrives within the window, so the connection survives idle turns.
_HEARTBEAT_SECONDS = 15.0


def _get_event_bus(request: Request) -> EventBus:
    return cast(EventBus, request.app.state.event_bus)


def _sse_frame(event: ServerEvent) -> str:
    """Render one typed event as an SSE ``event:``/``data:`` frame.

    The event name is the model's ``type`` discriminator so the browser can
    ``addEventListener("status" | "task_progress" | "task_done", …)``.
    """
    return f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"


async def _event_stream(
    request: Request,
    bus: EventBus,
    store: SessionStore,
    sid: str,
    redis: RedisClient,
    queue: "asyncio.Queue[StreamItem]",
) -> AsyncIterator[str]:
    """Drain this connection's queue as SSE, heart-beating through idle gaps.

    ``queue`` is registered by the route rather than here: ``bus.register`` awaits a
    Valkey ``SUBSCRIBE``, and a failure there has to surface as a 503 on the request.
    Once a ``StreamingResponse`` has been handed back, the status line is already
    committed and the only way to report the failure is a stream that never yields.

    Starts the background-task subscriber, then yields frames until the client
    disconnects — at which point the subscriber is cancelled and the queue unregistered.
    Also ends on the bus's ``None`` sentinel (this worker's Valkey relay for the sid
    died): closing the response makes the browser's ``EventSource`` reconnect, and the
    new request's ``register`` subscribes again.
    """
    # One background-task subscriber per session *per worker*, shared across this
    # worker's connections/tabs (T-5): start it only for the first connection of this
    # sid; the last to close cancels it. A worker with tabs for this sid runs its own
    # subscriber, so that subscriber's task_progress is delivered to this worker's queues
    # only (EventBus.deliver_local) -- publishing it would reach every tab once per
    # worker. task_done is published, deduplicated cluster-wide by claim_task.
    if bus.get_task_subscriber(sid) is None:
        task = asyncio.create_task(
            run_task_subscriber(
                bus,
                store,
                sid,
                redis,
                auto_approve=settings.auto_approve_steps,
            )
        )
        bus.set_task_subscriber(sid, task)
    try:
        # Open the stream immediately so the client's EventSource fires `open`
        # before any real event (and so proxies flush the response headers).
        yield ": connected\n\n"
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            if event is None:
                break  # relay died; let the client reconnect
            yield _sse_frame(event)
    finally:
        await bus.unregister(sid, queue)
        # Tear the shared subscriber down when this sid's last stream *on this worker*
        # closes -- local_listener_count, not has_listeners: the subscriber and the
        # pub/sub relay are both per-worker, and another worker's tabs have their own.
        if bus.local_listener_count(sid) == 0:
            subscriber = bus.get_task_subscriber(sid)
            bus.clear_task_subscriber(sid)
            if subscriber is not None:
                subscriber.cancel()
                try:
                    await subscriber
                except (asyncio.CancelledError, Exception):  # noqa: BLE001 - cleanup only
                    pass


@router.get("/events")
async def events(
    request: Request,
    claims: TokenClaims = Depends(current_claims),
) -> StreamingResponse:
    """Open the session's SSE stream. Auth-required; one per browser connection."""
    store = get_store(request)
    bus = _get_event_bus(request)
    # Subscribe before the response is committed so a Valkey outage is a 503 the client
    # can retry, not a stream that connects and then silently never delivers anything.
    try:
        queue = await bus.register(claims.sid)
    except Exception as exc:  # noqa: BLE001 - reported to the client below
        logger.warning("Could not open the event stream for sid=%s: %s", claims.sid, exc)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Event stream is unavailable (state store unreachable).",
        ) from exc

    return StreamingResponse(
        _event_stream(request, bus, store, claims.sid, get_redis(request), queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # belt-and-suspenders for nginx buffering
        },
    )
