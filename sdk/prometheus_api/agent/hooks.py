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

"""Execution middleware for PrometheusAgent specialist agents.

Named ``hooks.py`` to avoid the Starlette auth middleware in
``prometheus_api.agent.middleware``; functionally this is middleware the base
executor runs around every A2A task execution it performs. It mirrors the
orchestrator's dispatch middleware
(``platform/agents/client-agent/orchestrator/hooks.py``): same protocol
shape, same failure discipline, on the specialist side of the A2A boundary —
the orchestrator observes the dispatch from outside the agent, these hooks
observe the execution from inside it.

One protocol covers the four interception points of one execution:

- ``on_request`` — caller entering the agent (extracted, identity-injected
  params), after :meth:`PrometheusAgentExecutor._extract_params` and before
  the execution-record scope opens, so the durable record snapshots the
  params the middleware left behind
- ``on_event``  — agent leaving progress to the caller (in-flight stream)
- ``on_result`` — agent returning to the caller (parsed payload), before
  automatic finalization, so the final status carries the rewritten result
- ``on_error``  — execution failed

plus a fifth, task-scoped point that brackets the whole execution:

- ``on_task`` — one A2A task finished at its final state (fired after
  finalization, mirroring the orchestrator's ``on_turn`` firing after the
  turn was persisted)

Contract, enforced by the executor:

- Hooks observe and may rewrite values (params dict / result dict / progress
  text), but must not own the framework's reserved keys — the executor strips
  and re-applies those around each rewriting point: ``conversation_id``
  (orchestrator plumbing that arrives in the payload), ``skill_id`` and
  ``user_id`` (base-injected routing and verified identity), and every
  ``_``-prefixed key (the framework's plumbing convention, including keys
  added after this file was written).
- Hook failures degrade, never abort, unless the hook was registered
  ``strict``: the framework catches every hook call, logs it, and passes the
  value through unchanged. Strict rewriting hooks (``on_request`` /
  ``on_event`` / ``on_result``) re-raise instead, failing the task —
  fail-closed middleware. The observing points (``on_error`` / ``on_task``)
  never abort: an observation must not corrupt the outcome it observes.
- Async hook calls are bounded by ``_EXECUTE_HOOK_TIMEOUT_SECONDS`` (10 s): a
  hook that exceeds it is cancelled and treated like any other failure.
  ``on_event`` (sync) must not block.
- ``on_request``/``on_result``/``on_error``/``on_task`` are async (they may
  await); ``on_event`` is sync by decision — progress events are
  latency-sensitive, high-volume, and fire from inside the stream-consume
  loop, so an awaitable would either backpressure the stream or need a side
  queue that does not exist. Sync-only keeps the event path honest.
- Hooks run in registration order and compose: platform-mandated hooks
  (loaded from ``PROMETHEUS_AGENT_MIDDLEWARE`` at agent construction) run
  first, author hooks registered through
  ``PrometheusAgent.add_execute_hook(...)`` run after them, and each
  rewriting hook sees the previous hook's output. With no hooks registered
  the executor skips interception entirely — no wrapping, no per-event work.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import logging
import os
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple, cast

logger = logging.getLogger(__name__)

#: Environment variable listing platform-mandated execution middleware.
#: Comma-separated ``module:ClassName`` entries, loaded (in order) at agent
#: construction, ahead of any author-registered hook. A malformed or
#: unimportable entry raises ``ValueError`` — mandatory middleware that fails
#: to load is a deployment error, not a silent no-op.
ENV_EXECUTE_MIDDLEWARE = "PROMETHEUS_AGENT_MIDDLEWARE"

# A hung async hook must not hang the task (or the streaming connection):
# each async interception point is awaited under this ceiling and a timeout is
# treated like any other hook failure (logged, value passes through — unless
# the hook was registered strict, in which case the task fails).
_EXECUTE_HOOK_TIMEOUT_SECONDS: float = 10.0


def _is_reserved_key(key: str) -> bool:
    """The framework's reserved keys: ``conversation_id``, ``skill_id``,
    ``user_id``, and every ``_``-prefixed key.

    ``skill_id``/``user_id`` are injected by
    :meth:`PrometheusAgentExecutor._extract_params` and the executor's own
    plumbing uses the ``_`` prefix; ``conversation_id`` is reserved without a
    prefix because the orchestrator dispatches it inside the payload. Hooks
    never see — nor can they drop or forge — any such key.
    """
    return key == "conversation_id" or key in ("skill_id", "user_id") or key.startswith("_")


class ExecuteHookError(RuntimeError):
    """A strict hook failed its interception point.

    Raised instead of the hook's own exception so a failing strict middleware
    is distinguishable in logs and error payloads from an agent failure.
    """


@dataclass(frozen=True)
class ExecuteContext:
    """Immutable identity of one A2A task execution, passed to every hook.

    Built once per executor run, after parameter extraction (so ``skill_id``
    and ``user_id`` reflect the base-injected values) and reused for every
    interception point of that run. ``context_id``/``task_id`` are the A2A
    identifiers; a resumed task keeps both, like the orchestrator's
    ``conversation_id``.
    """

    agent_name: str
    context_id: str
    task_id: str
    skill_id: str
    user_id: str


@dataclass(frozen=True)
class TaskSnapshot:
    """Immutable end-of-task snapshot, passed to the ``on_task`` middleware.

    One execution's outcome. ``outcome`` is the final task state's canonical
    proto name (``TASK_STATE_COMPLETED``, ``TASK_STATE_FAILED``,
    ``TASK_STATE_INPUT_REQUIRED``, ...) — the state the task actually ended
    in, whether the executor auto-finalized it or the agent emitted its own
    final status. ``result`` is a deep copy of the final structured payload
    (``None`` when the task failed); ``error`` is the failure text (``None``
    otherwise). ``execution_record_id`` is best-effort: the DeepLynx
    execution item bound to the run when the executor can read it (``None``
    when no execution scope is active or the run is isolated).
    """

    outcome: str
    message: str
    result: Optional[Dict[str, Any]]
    error: Optional[str]
    execution_record_id: Optional[int]


class ExecuteHook(Protocol):
    """Middleware interface around one A2A task execution."""

    async def on_request(self, context: ExecuteContext, params: Dict[str, Any]) -> Dict[str, Any]:
        """Observe or rewrite the extracted params entering the agent."""
        ...

    def on_event(self, context: ExecuteContext, message: str) -> str:
        """Observe or rewrite one in-flight progress message from the agent."""
        ...

    async def on_result(self, context: ExecuteContext, result: Dict[str, Any]) -> Dict[str, Any]:
        """Observe or rewrite the parsed payload the agent returned."""
        ...

    async def on_error(self, context: ExecuteContext, error: BaseException) -> None:
        """Observe a failed execution; read-only (there is no value to rewrite)."""
        ...

    async def on_task(self, context: ExecuteContext, snapshot: TaskSnapshot) -> None:
        """Observe one finished task; read-only (there is no value to rewrite)."""
        ...


class NoopExecuteHook:
    """Dummy middleware: logs every interception point, changes nothing.

    Reference implementation for the interface. Real middleware subclasses
    or composes this to override only the points it needs.
    """

    async def on_request(self, context: ExecuteContext, params: Dict[str, Any]) -> Dict[str, Any]:
        logger.debug("[hook] on_request %s", context.skill_id)
        return params

    def on_event(self, context: ExecuteContext, message: str) -> str:
        logger.debug("[hook] on_event %s: %s", context.skill_id, message)
        return message

    async def on_result(self, context: ExecuteContext, result: Dict[str, Any]) -> Dict[str, Any]:
        logger.debug("[hook] on_result %s", context.skill_id)
        return result

    async def on_error(self, context: ExecuteContext, error: BaseException) -> None:
        logger.debug("[hook] on_error %s: %s", context.skill_id, error)

    async def on_task(self, context: ExecuteContext, snapshot: TaskSnapshot) -> None:
        logger.debug("[hook] on_task %s: %s", context.skill_id, snapshot.outcome)


def validate_execute_hook(hook: ExecuteHook) -> None:
    """Reject hooks whose methods would be silently ignored or fail at call time.

    Only ``on_event`` is sync; an ``async def on_event`` is silently ignored
    at call time, and a sync ``on_request``/``on_result``/``on_error``/
    ``on_task`` fails with a TypeError at call time — both are registration
    errors instead. Methods a hook omits (duck typing) still degrade per
    point.
    """
    for name in ("on_request", "on_result", "on_error", "on_task"):
        method = getattr(hook, name, None)
        if method is not None and not inspect.iscoroutinefunction(method):
            raise ValueError(f"hook.{name} must be an async def (only on_event is sync)")
    on_event = getattr(hook, "on_event", None)
    if on_event is not None and inspect.iscoroutinefunction(on_event):
        raise ValueError(
            "hook.on_event must be a plain def (sync by decision; see the module docstring)"
        )


def strip_reserved(params: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a copy of ``params`` without the framework's reserved keys."""
    return {key: value for key, value in params.items() if not _is_reserved_key(key)}


def apply_reserved(source: Mapping[str, Any], target: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a copy of ``target`` with the framework's reserved keys re-applied.

    The framework re-applies its bookkeeping after hooks run, so a rewriting
    hook (e.g. redaction) can never drop ``conversation_id``/``skill_id``/
    ``user_id`` or the ``_``-prefixed plumbing by accident — nor forge them:
    the hook's reserved keys are always stripped from ``target`` first, and
    the source's own reserved keys are carried back over the result. A source
    with no reserved keys therefore still yields a stripped target.
    """
    carried = {key: source[key] for key in source if _is_reserved_key(key)}
    stripped_target = {key: value for key, value in target.items() if not _is_reserved_key(key)}
    return {**stripped_target, **carried}


async def _await_hook(call) -> Any:
    """Await one async hook point under the timeout ceiling."""
    return await asyncio.wait_for(call(), _EXECUTE_HOOK_TIMEOUT_SECONDS)


def _log_hook_failure(point: str, context: ExecuteContext, strict: bool) -> None:
    if strict:
        logger.warning(
            "[hook] %s failed (strict) for %s; failing the task", point, context.skill_id
        )
    else:
        logger.warning("[hook] %s failed for %s; passing value through", point, context.skill_id)


async def run_request_hooks(
    chain: Sequence[Tuple[ExecuteHook, bool]],
    context: ExecuteContext,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Run the chain's ``on_request`` in order, reserved keys preserved.

    Each hook sees the previous hook's output (minus reserved keys). Degrades
    to the value entering the failed hook when the hook raises, times out, or
    returns junk — unless the hook was registered strict, in which case
    :class:`ExecuteHookError` propagates and the task fails.
    """
    if not chain:
        return dict(params)
    current = dict(params)
    for hook, strict in chain:
        base = strip_reserved(current)
        try:
            rewritten = await _await_hook(lambda: hook.on_request(context, base))
        except Exception as exc:
            _log_hook_failure("on_request", context, strict)
            if strict:
                raise ExecuteHookError(
                    f"strict execution middleware failed on_request for {context.skill_id}"
                ) from exc
            continue
        if not isinstance(rewritten, dict):
            logger.warning(
                "[hook] on_request returned %s for %s; passing params through",
                type(rewritten).__name__,
                context.skill_id,
            )
            continue
        current = apply_reserved(current, rewritten)
    return current


def run_event_hooks(
    chain: Sequence[Tuple[ExecuteHook, bool]],
    context: ExecuteContext,
    message: str,
) -> str:
    """Run the chain's sync ``on_event`` in order; degrades per failing hook.

    Each hook sees the previous hook's output. A strict hook failure
    re-raises (:class:`ExecuteHookError`); otherwise the text entering the
    failed hook passes through.
    """
    if not chain:
        return str(message or "")
    current = str(message or "")
    for hook, strict in chain:
        try:
            rewritten = hook.on_event(context, current)
        except Exception as exc:
            _log_hook_failure("on_event", context, strict)
            if strict:
                raise ExecuteHookError(
                    f"strict execution middleware failed on_event for {context.skill_id}"
                ) from exc
            continue
        current = str(rewritten) if isinstance(rewritten, str) else current
    return current


async def run_result_hooks(
    chain: Sequence[Tuple[ExecuteHook, bool]],
    context: ExecuteContext,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    """Run the chain's ``on_result`` in order, reserved keys re-applied last.

    Same composition and degradation rules as :func:`run_request_hooks`.
    """
    if not chain:
        return dict(result)
    current = dict(result)
    for hook, strict in chain:
        base = strip_reserved(current)
        try:
            rewritten = await _await_hook(lambda: hook.on_result(context, base))
        except Exception as exc:
            _log_hook_failure("on_result", context, strict)
            if strict:
                raise ExecuteHookError(
                    f"strict execution middleware failed on_result for {context.skill_id}"
                ) from exc
            continue
        if not isinstance(rewritten, dict):
            logger.warning(
                "[hook] on_result returned %s for %s; passing result through",
                type(rewritten).__name__,
                context.skill_id,
            )
            continue
        current = apply_reserved(current, rewritten)
    return current


async def run_error_hooks(
    chain: Sequence[Tuple[ExecuteHook, bool]],
    context: ExecuteContext,
    error: BaseException,
) -> None:
    """Run the chain's ``on_error`` in order; hook errors are logged, never raised.

    Observers never abort the task — not even strict ones: an observation
    must not replace the agent failure it is reporting.
    """
    for hook, _strict in chain:
        try:
            await _await_hook(lambda: hook.on_error(context, error))
        except Exception:
            logger.warning("[hook] on_error failed for %s", context.skill_id, exc_info=True)


async def run_task_hooks(
    chain: Sequence[Tuple[ExecuteHook, bool]],
    context: ExecuteContext,
    *,
    outcome: str,
    message: str,
    result: Optional[Dict[str, Any]],
    error: Optional[str],
    execution_record_id: Optional[int],
) -> None:
    """Run the chain's ``on_task`` in order with a deep-copied end-of-task snapshot.

    Hook errors are logged, never raised — a memory write must not fail a
    task that already reached its final state. The snapshot's ``result`` is
    ``copy.deepcopy``-ed so the hook can never observe or mutate the live
    payload, and so later framework mutations of the stored dicts cannot
    reach a retained snapshot. Snapshot construction sits inside the
    ``try``: a copy failure (an un-deepcopyable object in the payload) must
    not fail a task that already finalized — the hook simply does not fire.
    """
    if not chain:
        return
    try:
        snapshot = TaskSnapshot(
            outcome=str(outcome or ""),
            message=str(message or ""),
            result=copy.deepcopy(result),
            error=error,
            execution_record_id=execution_record_id,
        )
        for hook, _strict in chain:
            await _await_hook(lambda: hook.on_task(context, snapshot))
    except Exception:
        logger.warning("[hook] on_task failed for %s", context.skill_id, exc_info=True)


def load_env_execute_hooks() -> List[Tuple[ExecuteHook, bool]]:
    """Load platform-mandated middleware from ``PROMETHEUS_AGENT_MIDDLEWARE``.

    Returns an empty list when unset/blank. Entries are comma-separated
    ``module:ClassName`` import paths, kept in order, each non-strict
    (fail-open; strictness is an author-registration decision, not a
    deployment default). A malformed entry, an unimportable module, a missing
    attribute, or a wrong-shape hook raises ``ValueError`` — mandatory
    middleware must fail loudly at construction, not silently at request time.
    """
    raw = (os.getenv(ENV_EXECUTE_MIDDLEWARE) or "").strip()
    if not raw:
        return []
    chain: List[Tuple[ExecuteHook, bool]] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        chain.append((_import_hook_entry(entry), False))
    return chain


def _import_hook_entry(entry: str) -> ExecuteHook:
    """Import one ``module:ClassName`` middleware entry."""
    module_name, sep, attr = entry.partition(":")
    if not sep or not module_name.strip() or not attr.strip():
        raise ValueError(f"{ENV_EXECUTE_MIDDLEWARE} entry {entry!r} must be 'module:ClassName'")
    module_name = module_name.strip()
    attr = attr.strip()
    try:
        module = import_module(module_name)
    except ImportError as exc:
        raise ValueError(
            f"{ENV_EXECUTE_MIDDLEWARE} entry {entry!r}: cannot import module {module_name!r}"
        ) from exc
    hook = getattr(module, attr, None)
    if hook is None:
        raise ValueError(
            f"{ENV_EXECUTE_MIDDLEWARE} entry {entry!r}: module {module_name!r} has no attribute {attr!r}"
        )
    if isinstance(hook, type):
        # A class entry names the middleware; the framework owns the instance.
        hook = hook()
    try:
        validate_execute_hook(hook)
    except ValueError as exc:
        raise ValueError(f"{ENV_EXECUTE_MIDDLEWARE} entry {entry!r}: {exc}") from exc
    return cast(ExecuteHook, hook)
