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

"""Call middleware for the orchestrator's specialist dispatches.

Named ``hooks.py`` to avoid the Starlette auth middleware in
``prometheus_api.agent.middleware``; functionally this is middleware that
wraps every specialist dispatch made by :func:`orchestrator.skills.invoke_skill`.

One protocol covers the four interception points of a dispatch:

- ``on_request`` — orchestrator entering the agent (normalized params)
- ``on_event``  — agent leaving progress to the orchestrator (in-flight stream)
- ``on_result`` — agent returning to the orchestrator (parsed payload)
- ``on_error``  — dispatch failed: raised locally, or returned as an error
  *result* (``DispatchError``; the same payload also reaches ``on_result``)

plus a fifth, turn-scoped point that brackets the whole dispatch sequence:

- ``on_turn`` — one user turn finished at a loop outcome
  (:func:`orchestrator.chat_flow._respond`)

Contract, enforced by the framework code in ``skills.py``:

- Hooks observe and may rewrite values (params dict / result dict / progress
  text), but must not own the reserved ``_*`` bookkeeping keys — the framework
  strips and re-applies those around the hooks (``_task_graph_node_id``,
  ``_task_graph_root_id``, ``_a2a_context_id``, ``_a2a_task_id``, and the
  ``_status_callback``/``_background_callback``/``_artifact_callback`` handles).
- Hook failures degrade, never abort: the framework catches every hook call,
  logs it, and passes the value through unchanged.
- ``on_request``/``on_result`` are async (they may await); ``on_event`` is
  sync by decision — progress events are latency-sensitive, high-volume, and
  fire from inside the stream-consume loop, so an awaitable would either
  backpressure the stream or need a side queue that does not exist. Sync-only
  keeps the event path allocation-free and honest.
- At most one hook is registered per process (``set_call_hook``); the current
  hook is read once per dispatch (``current_call_hook``), so swaps are cheap
  and visible on the next dispatch.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Protocol, Tuple

logger = logging.getLogger(__name__)

_CARRIER_KEYS = (
    "_status_callback",
    "_background_callback",
    "_artifact_callback",
)
_RESERVED_PARAM_KEYS = (
    "conversation_id",
    "_task_graph_node_id",
    "_task_graph_root_id",
    "_a2a_context_id",
    "_a2a_task_id",
    "_prefer_streaming",
    "_input_sources",
) + _CARRIER_KEYS
_RESERVED_RESULT_KEYS = (
    "_task_graph_node_id",
    "_task_graph_root_id",
    "_a2a_context_id",
    "_a2a_task_id",
)


class DispatchError(RuntimeError):
    """A dispatch that failed without raising: the transport's error *result*.

    ``tool_discovery.call_agent`` catches every agent failure (unreachable
    agent, timeout, HTTP error) and returns ``{"error": ...}``, so ``skills``
    wraps that error string in this class when it fires ``on_error``. The same
    payload also reaches ``on_result`` (rewritable).
    """


@dataclass(frozen=True)
class AgentCallContext:
    """Immutable identity of one specialist dispatch, passed to every hook."""

    conversation_id: str
    skill_id: str
    agent_name: str
    node_id: Optional[str] = None


@dataclass(frozen=True)
class TurnContext:
    """Immutable end-of-turn snapshot, passed to the ``on_turn`` middleware.

    The whole turn in one value — what the orchestrator did (the trimmed
    ``llm_messages`` transcript, including this turn's assistant messages with
    tool-call ids/arguments and tool-result messages), what it produced
    (``tool_results``/``tool_inputs``, reset by ``begin_user_turn`` so they are
    this turn only), and how it stopped (the ``LoopOutcome``). Snapshots are
    plain copies: the hook must not see (nor mutate) the live ``AgentState``,
    which a sibling backgrounded turn can be writing concurrently.

    One fire per *user reply*, not per logical task: an INPUT_REQUIRED pause and
    its resume are two turns, two ``on_turn`` calls, sharing ``root_id``.
    Consumers building one trajectory per task join on ``conversation_id``.
    """

    conversation_id: str
    turn_id: Optional[str]
    root_id: Optional[str]
    outcome: str
    message: str
    llm_messages: Tuple[Dict[str, Any], ...]
    tool_results: Mapping[str, Any]
    tool_inputs: Mapping[str, Any]


class CallHook(Protocol):
    """Middleware interface around one orchestrator -> specialist dispatch."""

    async def on_request(self, context: AgentCallContext, params: Dict[str, Any]) -> Dict[str, Any]:
        """Observe or rewrite the normalized params entering the agent."""
        ...

    def on_event(self, context: AgentCallContext, message: str) -> str:
        """Observe or rewrite one in-flight progress message from the agent."""
        ...

    async def on_result(self, context: AgentCallContext, result: Dict[str, Any]) -> Dict[str, Any]:
        """Observe or rewrite the parsed payload the agent returned."""
        ...

    async def on_error(self, context: AgentCallContext, error: BaseException) -> None:
        """Observe a failed dispatch: raised locally, or returned as an error result (``DispatchError``)."""
        ...

    async def on_turn(self, context: TurnContext) -> None:
        """Observe one finished user turn; read-only (there is no value to rewrite)."""
        ...


class NoopCallHook:
    """Dummy middleware: logs every interception point, changes nothing.

    Reference implementation for the interface (and the default when
    unset). Real middleware subclasses or composes this to override only
    the points it needs.
    """

    async def on_request(self, context: AgentCallContext, params: Dict[str, Any]) -> Dict[str, Any]:
        logger.debug("[hook] on_request %s", context.skill_id)
        return params

    def on_event(self, context: AgentCallContext, message: str) -> str:
        logger.debug("[hook] on_event %s: %s", context.skill_id, message)
        return message

    async def on_result(self, context: AgentCallContext, result: Dict[str, Any]) -> Dict[str, Any]:
        logger.debug("[hook] on_result %s", context.skill_id)
        return result

    async def on_error(self, context: AgentCallContext, error: BaseException) -> None:
        logger.debug("[hook] on_error %s: %s", context.skill_id, error)

    async def on_turn(self, context: TurnContext) -> None:
        logger.debug("[hook] on_turn %s: %s", context.conversation_id, context.outcome)


_call_hook: CallHook = NoopCallHook()


def set_call_hook(hook: Optional[CallHook]) -> None:
    """Install the process-wide dispatch middleware (None restores default)."""
    global _call_hook
    _call_hook = hook if hook is not None else NoopCallHook()


def current_call_hook() -> CallHook:
    """Return the installed middleware (never None)."""
    return _call_hook


def strip_reserved(params: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of ``params`` without the framework's ``_*`` keys."""
    return {key: value for key, value in params.items() if key not in _RESERVED_PARAM_KEYS}


def apply_reserved(source: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of ``target`` with ``_*`` keys carried over from ``source``.

    The framework re-applies its bookkeeping after hooks run, so a rewriting
    hook (e.g. redaction) can never drop the task-graph resume ids or the
    status/background/artifact callback handles by accident — nor forge them:
    carried keys override anything the hook itself put under those names.
    """
    carried = {key: source[key] for key in _RESERVED_PARAM_KEYS if key in source}
    if not carried:
        return target
    stripped_target = {key: value for key, value in target.items() if key not in _RESERVED_PARAM_KEYS}
    return {**stripped_target, **carried}


async def run_on_request(
    context: AgentCallContext,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Run the middleware's ``on_request``, reserved keys preserved.

    Degrades to the original params when the hook raises or returns junk.
    """
    hook = current_call_hook()
    base = strip_reserved(params)
    try:
        rewritten = await hook.on_request(context, base)
    except Exception:
        logger.warning("[hook] on_request failed for %s; passing params through", context.skill_id, exc_info=True)
        return dict(params)
    if not isinstance(rewritten, dict):
        return dict(params)
    return apply_reserved(params, rewritten)


def run_on_event(
    context: AgentCallContext,
    message: str,
) -> str:
    """Run the middleware's sync ``on_event``; degrades to the original text."""
    try:
        rewritten = current_call_hook().on_event(context, str(message or ""))
    except Exception:
        logger.warning("[hook] on_event failed for %s; passing message through", context.skill_id, exc_info=True)
        return message
    return str(rewritten) if isinstance(rewritten, str) else message


async def run_on_result(
    context: AgentCallContext,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    """Run the middleware's ``on_result``, reserved keys re-applied last."""
    hook = current_call_hook()
    base = strip_reserved(result)
    try:
        rewritten = await hook.on_result(context, base)
    except Exception:
        logger.warning("[hook] on_result failed for %s; passing result through", context.skill_id, exc_info=True)
        return dict(result)
    if not isinstance(rewritten, dict):
        return dict(result)
    return apply_reserved(result, rewritten)


async def run_on_error(
    context: AgentCallContext,
    error: BaseException,
) -> None:
    """Run the middleware's ``on_error``; hook errors are logged, never raised."""
    try:
        await current_call_hook().on_error(context, error)
    except Exception:
        logger.warning("[hook] on_error failed for %s", context.skill_id, exc_info=True)


async def run_on_turn(
    conversation_id: str,
    outcome_kind: str,
    outcome_message: str,
    llm_messages: Any,
    tool_results: Any,
    tool_inputs: Any,
    turn_id: Optional[str] = None,
    root_id: Optional[str] = None,
) -> None:
    """Run the middleware's ``on_turn`` with a deep-copied end-of-turn snapshot.

    Hook errors are logged, never raised — a memory write must not fail a turn
    that already succeeded. The snapshot is ``copy.deepcopy``-ed so the hook
    can never observe or mutate the live ``AgentState``, which a sibling
    backgrounded turn can be writing concurrently, and so later framework
    mutations of the stored message dicts cannot reach a retained snapshot.
    """
    snapshot = copy.deepcopy(
        dict(
            llm_messages=llm_messages,
            tool_results=tool_results,
            tool_inputs=tool_inputs,
        )
    )
    context = TurnContext(
        conversation_id=str(conversation_id or ""),
        turn_id=turn_id,
        root_id=root_id,
        outcome=str(outcome_kind or ""),
        message=str(outcome_message or ""),
        llm_messages=tuple(snapshot["llm_messages"]),
        tool_results=snapshot["tool_results"],
        tool_inputs=snapshot["tool_inputs"],
    )
    try:
        await current_call_hook().on_turn(context)
    except Exception:
        logger.warning("[hook] on_turn failed for %s", context.conversation_id, exc_info=True)
