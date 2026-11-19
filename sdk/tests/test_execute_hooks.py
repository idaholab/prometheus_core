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

"""Tests for execution middleware (``prometheus_api.agent.hooks``).

Covers the executor's interception points (``on_request`` / ``on_event`` /
``on_result`` / ``on_error`` / ``on_task``), the reserved-key contract, the
degradation rules (fail-open by default, fail-closed when strict), the
timeout ceiling, env-based mandatory loading, and the no-hook zero-change
baseline.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from a2a.types import Message, Part, Role, TaskState, TaskStatusUpdateEvent

from prometheus_api.agent import (
    ExecuteContext,
    ExecuteHookError,
    PrometheusAgent,
    PrometheusAgentExecutor,
    TaskSnapshot,
)
from prometheus_api.agent.events import (
    build_status_update_event,
    emit_status_update,
    status_event_message_text,
)
from prometheus_api.agent.hooks import (
    ENV_EXECUTE_MIDDLEWARE,
    NoopExecuteHook,
    apply_reserved,
    load_env_execute_hooks,
    run_error_hooks,
    run_event_hooks,
    run_request_hooks,
    run_result_hooks,
    run_task_hooks,
    strip_reserved,
    validate_execute_hook,
)


@pytest.fixture(autouse=True)
def clean_middleware_env(monkeypatch):
    """Keep the platform middleware env var from leaking between tests."""
    monkeypatch.delenv(ENV_EXECUTE_MIDDLEWARE, raising=False)


@pytest.fixture
def mock_context():
    """Create a mock RequestContext."""
    context = MagicMock(spec=RequestContext)
    context.task_id = "test-task-123"
    context.context_id = "test-context-456"
    context.current_task = None
    context.message = None
    context.get_user_input.return_value = '{"input_data": "test data"}'
    return context


@pytest.fixture
def mock_event_queue():
    """Create a mock EventQueue."""
    return AsyncMock(spec=EventQueue)


def make_context(skill_id="skill-1", user_id="user-1") -> ExecuteContext:
    return ExecuteContext(
        agent_name="TestAgent",
        context_id="ctx-1",
        task_id="task-1",
        skill_id=skill_id,
        user_id=user_id,
    )


class RecordingHook:
    """Middleware that records every point and optionally rewrites or fails."""

    def __init__(
        self,
        *,
        request_rewrite=None,
        event_rewrite=None,
        result_rewrite=None,
        request_error=None,
        event_error=None,
        result_error=None,
        error_error=None,
        task_error=None,
        request_sleep=0.0,
        junk_request=False,
        junk_result=False,
    ):
        self.request_rewrite = request_rewrite
        self.event_rewrite = event_rewrite
        self.result_rewrite = result_rewrite
        self.request_error = request_error
        self.event_error = event_error
        self.result_error = result_error
        self.error_error = error_error
        self.task_error = task_error
        self.request_sleep = request_sleep
        self.junk_request = junk_request
        self.junk_result = junk_result
        self.requests = []
        self.events = []
        self.results = []
        self.errors = []
        self.snapshots = []

    async def on_request(self, context, params):
        self.requests.append(dict(params))
        if self.request_sleep:
            await asyncio.sleep(self.request_sleep)
        if self.request_error is not None:
            raise self.request_error
        if self.junk_request:
            return "not-a-dict"
        return self.request_rewrite if self.request_rewrite is not None else params

    def on_event(self, context, message):
        self.events.append(message)
        if self.event_error is not None:
            raise self.event_error
        return self.event_rewrite if self.event_rewrite is not None else message

    async def on_result(self, context, result):
        self.results.append(dict(result))
        if self.result_error is not None:
            raise self.result_error
        if self.junk_result:
            return 42
        return self.result_rewrite if self.result_rewrite is not None else result

    async def on_error(self, context, error):
        self.errors.append(error)
        if self.error_error is not None:
            raise self.error_error

    async def on_task(self, context, snapshot):
        self.snapshots.append(snapshot)
        if self.task_error is not None:
            raise self.task_error


def make_executor(*hooks, execution_record_id_fn=None, execute_fn=None):
    """Create a concrete executor with the given middleware chain."""
    if execute_fn is None:

        async def execute_fn(self, params, context, event_queue):
            self.received_params = dict(params)
            return {"status": "success", "data": params.get("input_data")}

    body = {"received_params": None, "_execute": execute_fn}
    cls = type("TestExecutor", (PrometheusAgentExecutor,), body)
    return cls(
        agent_name="TestAgent",
        execute_hooks=list(hooks),
        execution_record_id_fn=execution_record_id_fn,
    )


def status_events(mock_event_queue):
    return [
        call[0][0]
        for call in mock_event_queue.enqueue_event.call_args_list
        if isinstance(call[0][0], TaskStatusUpdateEvent)
    ]


class SyncRequestHook:
    """Env-loadable middleware with the wrong on_request shape (sync)."""

    def on_request(self, context, params):
        return params


class TestReservedKeys:
    def test_strip_reserved_removes_framework_keys(self):
        params = {
            "input_data": "x",
            "conversation_id": "c1",
            "skill_id": "s1",
            "user_id": "u1",
            "_internal": "plumbing",
        }
        assert strip_reserved(params) == {"input_data": "x"}

    def test_apply_reserved_carries_and_blocks_forgery(self):
        source = {"input_data": "x", "skill_id": "s1", "_internal": "p"}
        target = {"input_data": "y", "skill_id": "forged", "_forged": 1}
        assert apply_reserved(source, target) == {
            "input_data": "y",
            "skill_id": "s1",
            "_internal": "p",
        }

    def test_apply_reserved_from_reservedless_source_strips_target(self):
        assert apply_reserved({}, {"skill_id": "forged", "ok": 1}) == {"ok": 1}


class TestRunnerUnits:
    async def test_request_chain_composes_in_order(self):
        first = RecordingHook(request_rewrite={"input_data": "one"})
        second = RecordingHook(request_rewrite={"input_data": "two"})
        result = await run_request_hooks(
            [(first, False), (second, False)], make_context(), {"input_data": "zero"}
        )
        assert result["input_data"] == "two"
        assert first.requests == [{"input_data": "zero"}]
        assert second.requests == [{"input_data": "one"}]

    async def test_request_empty_chain_returns_copy(self):
        params = {"input_data": "x"}
        result = await run_request_hooks([], make_context(), params)
        assert result == params and result is not params

    async def test_empty_chain_event_result_and_task_unchanged(self):
        result_payload = {"status": "success"}
        assert run_event_hooks([], make_context(), "msg") == "msg"
        passed = await run_result_hooks([], make_context(), result_payload)
        assert passed == result_payload and passed is not result_payload
        # A task observer over an empty chain is a no-op that must not raise.
        await run_task_hooks(
            [],
            make_context(),
            outcome="TASK_STATE_COMPLETED",
            message="",
            result=result_payload,
            error=None,
            execution_record_id=None,
        )

    async def test_noop_hook_passes_everything_through(self):
        noop = NoopExecuteHook()
        params = {"input_data": "x"}
        result = {"status": "success"}
        chain = [(noop, False)]
        assert await run_request_hooks(chain, make_context(), params) == params
        assert run_event_hooks(chain, make_context(), "msg") == "msg"
        assert await run_result_hooks(chain, make_context(), result) == result
        await run_error_hooks(chain, make_context(), ValueError("e"))
        await run_task_hooks(
            chain,
            make_context(),
            outcome="TASK_STATE_COMPLETED",
            message="",
            result=result,
            error=None,
            execution_record_id=None,
        )

    async def test_result_junk_return_degrades(self):
        hook = RecordingHook(junk_result=True)
        result = await run_result_hooks([(hook, False)], make_context(), {"status": "success"})
        assert result == {"status": "success"}

    async def test_request_failure_degrades_to_entering_value(self):
        failing = RecordingHook(request_error=ValueError("boom"))
        trailing = RecordingHook(request_rewrite={"input_data": "after"})
        result = await run_request_hooks(
            [(failing, False), (trailing, False)], make_context(), {"input_data": "orig"}
        )
        assert result["input_data"] == "after"
        assert trailing.requests == [{"input_data": "orig"}]

    async def test_request_strict_failure_raises_execute_hook_error(self):
        hook = RecordingHook(request_error=ValueError("boom"))
        with pytest.raises(ExecuteHookError) as excinfo:
            await run_request_hooks([(hook, True)], make_context(), {"input_data": "orig"})
        assert excinfo.value.__cause__ is hook.request_error

    async def test_request_junk_return_degrades(self):
        hook = RecordingHook(junk_request=True)
        result = await run_request_hooks([(hook, False)], make_context(), {"input_data": "orig"})
        assert result == {"input_data": "orig"}

    async def test_request_timeout_degrades_like_failure(self, monkeypatch):
        monkeypatch.setattr("prometheus_api.agent.hooks._EXECUTE_HOOK_TIMEOUT_SECONDS", 0.05)
        hook = RecordingHook(request_sleep=0.2)
        result = await run_request_hooks([(hook, False)], make_context(), {"input_data": "orig"})
        assert result == {"input_data": "orig"}

    async def test_request_reserved_keys_never_reach_hook(self):
        seen = {}

        class SpyHook:
            async def on_request(self, context, params):
                seen.update(params)
                return params

        await run_request_hooks(
            [(SpyHook(), False)],
            make_context(),
            {"input_data": "x", "skill_id": "s", "user_id": "u", "conversation_id": "c", "_p": 1},
        )
        assert seen == {"input_data": "x"}

    def test_event_chain_composes_and_degrades(self):
        first = RecordingHook(event_rewrite="a->b")
        failing = RecordingHook(event_error=RuntimeError("nope"))
        third = RecordingHook(event_rewrite="c->d")
        result = run_event_hooks(
            [(first, False), (failing, False), (third, False)], make_context(), "c"
        )
        # first rewrites c -> a->b; the failing hook degrades to a->b; third
        # rewrites a->b -> c->d.
        assert result == "c->d"
        assert first.events == ["c"]
        assert third.events == ["a->b"]

    def test_event_strict_failure_raises(self):
        hook = RecordingHook(event_error=RuntimeError("nope"))
        with pytest.raises(ExecuteHookError):
            run_event_hooks([(hook, True)], make_context(), "msg")

    def test_event_non_string_return_ignored(self):
        class JunkHook:
            def on_event(self, context, message):
                return 42

        assert run_event_hooks([(JunkHook(), False)], make_context(), "msg") == "msg"

    async def test_result_chain_reserved_reapplied(self):
        hook = RecordingHook(result_rewrite={"data": "rewritten"})
        result = await run_result_hooks(
            [(hook, False)], make_context(), {"status": "success", "skill_id": "s1", "_p": 1}
        )
        # A rewriting hook owns the non-reserved payload wholesale; only the
        # framework's reserved keys survive from the original.
        assert result == {"data": "rewritten", "skill_id": "s1", "_p": 1}

    async def test_result_strict_failure_raises(self):
        hook = RecordingHook(result_error=ValueError("boom"))
        with pytest.raises(ExecuteHookError):
            await run_result_hooks([(hook, True)], make_context(), {"status": "success"})

    async def test_error_observers_never_abort_even_strict(self):
        class FailingObserver:
            async def on_error(self, context, error):
                raise RuntimeError("observer broke")

        await run_error_hooks([(FailingObserver(), True)], make_context(), ValueError("task error"))

    async def test_task_snapshot_deepcopies_result(self):
        result = {"status": "success", "nested": {"a": 1}}
        seen = []
        hook = RecordingHook()
        original_on_task = hook.on_task

        async def on_task(context, snapshot):
            seen.append(snapshot)
            return await original_on_task(context, snapshot)

        hook.on_task = on_task
        await run_task_hooks(
            [(hook, False)],
            make_context(),
            outcome="completed",
            message="done",
            result=result,
            error=None,
            execution_record_id=7,
        )
        result["nested"]["a"] = 999
        assert seen[0].result == {"status": "success", "nested": {"a": 1}}
        assert seen[0].outcome == "completed"
        assert seen[0].execution_record_id == 7

    async def test_task_undeepcopyable_result_skips_hooks(self):
        class Uncopyable:
            def __deepcopy__(self, memo):
                raise TypeError("cannot copy")

        hook = RecordingHook()
        await run_task_hooks(
            [(hook, False)],
            make_context(),
            outcome="completed",
            message="",
            result={"bad": Uncopyable()},
            error=None,
            execution_record_id=None,
        )
        assert hook.snapshots == []


class TestHookValidation:
    def test_async_on_event_rejected(self):
        class BadHook:
            async def on_event(self, context, message):
                return message

        with pytest.raises(ValueError, match="on_event must be a plain def"):
            validate_execute_hook(BadHook())

    def test_sync_rewrite_points_rejected(self):
        class BadHook:
            def on_request(self, context, params):
                return params

        with pytest.raises(ValueError, match="on_request must be an async def"):
            validate_execute_hook(BadHook())

    def test_duck_typed_omission_is_valid(self):
        class PartialHook:
            async def on_request(self, context, params):
                return params

        validate_execute_hook(PartialHook())
        validate_execute_hook(NoopExecuteHook())


class TestEnvLoading:
    def test_unset_env_returns_empty(self):
        assert load_env_execute_hooks() == []

    def test_entries_load_in_order(self, monkeypatch):
        monkeypatch.setenv(
            ENV_EXECUTE_MIDDLEWARE,
            " prometheus_api.agent.hooks:NoopExecuteHook , prometheus_api.agent.hooks:NoopExecuteHook ",
        )
        chain = load_env_execute_hooks()
        assert len(chain) == 2
        assert all(isinstance(hook, NoopExecuteHook) and not strict for hook, strict in chain)

    def test_blank_entries_skipped(self, monkeypatch):
        monkeypatch.setenv(
            ENV_EXECUTE_MIDDLEWARE, " , prometheus_api.agent.hooks:NoopExecuteHook, "
        )
        assert len(load_env_execute_hooks()) == 1

    def test_missing_colon_raises(self, monkeypatch):
        monkeypatch.setenv(ENV_EXECUTE_MIDDLEWARE, "prometheus_api.agent.hooks.NoopExecuteHook")
        with pytest.raises(ValueError, match="module:ClassName"):
            load_env_execute_hooks()

    def test_unimportable_module_raises(self, monkeypatch):
        monkeypatch.setenv(ENV_EXECUTE_MIDDLEWARE, "not_a_real_module:Hook")
        with pytest.raises(ValueError, match="cannot import module"):
            load_env_execute_hooks()

    def test_missing_attribute_raises(self, monkeypatch):
        monkeypatch.setenv(ENV_EXECUTE_MIDDLEWARE, "prometheus_api.agent.hooks:NotAThing")
        with pytest.raises(ValueError, match="has no attribute"):
            load_env_execute_hooks()

    def test_wrong_shape_hook_raises(self, monkeypatch):
        # A sync on_request would fail at call time; the loader rejects it.
        monkeypatch.setenv(ENV_EXECUTE_MIDDLEWARE, f"{__name__}:SyncRequestHook")
        with pytest.raises(ValueError, match="on_request must be an async def"):
            load_env_execute_hooks()


class TestExecutorIntegration:
    async def test_no_hooks_execution_unchanged(self, mock_context, mock_event_queue):
        executor = make_executor()
        await executor.execute(mock_context, mock_event_queue)
        events = status_events(mock_event_queue)
        assert [event.status.state for event in events] == [
            TaskState.TASK_STATE_WORKING,
            TaskState.TASK_STATE_COMPLETED,
        ]
        assert json.loads(events[1].status.message.parts[0].text) == {
            "status": "success",
            "data": "test data",
        }

    async def test_on_request_rewrite_reaches_execute_with_reserved_reapplied(
        self, mock_context, mock_event_queue
    ):
        context = MagicMock(spec=RequestContext)
        context.task_id = "test-task-123"
        context.context_id = "test-context-456"
        context.current_task = None
        context.message = None
        context.get_user_input.return_value = json.dumps(
            {"input_data": "secret", "conversation_id": "conv-9", "_internal": "plumb"}
        )
        hook = RecordingHook(request_rewrite={"input_data": "REDACTED"})
        executor = make_executor((hook, False))

        await executor.execute(context, mock_event_queue)

        assert executor.received_params["input_data"] == "REDACTED"
        # The base injects user_id (the synthetic local identity in tests);
        # conversation_id and the _-prefixed plumbing survive the rewrite.
        assert executor.received_params["user_id"] == "local"
        assert executor.received_params["conversation_id"] == "conv-9"
        assert executor.received_params["_internal"] == "plumb"

    async def test_on_request_cannot_forge_reserved_keys(self, mock_context, mock_event_queue):
        hook = RecordingHook(
            request_rewrite={"input_data": "ok", "skill_id": "forged", "_forged": 1}
        )
        executor = make_executor((hook, False))

        await executor.execute(mock_context, mock_event_queue)

        assert "_forged" not in executor.received_params
        assert "skill_id" not in executor.received_params
        assert executor.received_params["input_data"] == "ok"

    async def test_on_request_fail_open_completes(self, mock_context, mock_event_queue):
        hook = RecordingHook(request_error=ValueError("middleware down"))
        executor = make_executor((hook, False))

        await executor.execute(mock_context, mock_event_queue)

        events = status_events(mock_event_queue)
        assert events[-1].status.state == TaskState.TASK_STATE_COMPLETED
        assert executor.received_params["input_data"] == "test data"

    async def test_on_request_strict_fails_task_and_observers_fire(
        self, mock_context, mock_event_queue
    ):
        hook = RecordingHook(request_error=ValueError("middleware down"))
        observer = RecordingHook()
        executor = make_executor((hook, True), (observer, False))

        with pytest.raises(ExecuteHookError):
            await executor.execute(mock_context, mock_event_queue)

        events = status_events(mock_event_queue)
        assert events[-1].status.state == TaskState.TASK_STATE_FAILED
        assert isinstance(observer.errors[0], ExecuteHookError)
        assert observer.errors[0].__cause__ is hook.request_error
        assert len(observer.snapshots) == 1
        assert observer.snapshots[0].outcome == "TASK_STATE_FAILED"
        assert "on_request" in observer.snapshots[0].error

    async def test_on_event_rewrites_agent_progress_only(self, mock_context, mock_event_queue):
        hook = RecordingHook(event_rewrite="[hooked] Processing your request…")

        async def execute_fn(self, params, context, event_queue):
            await emit_status_update(
                context=context,
                event_queue=event_queue,
                state=TaskState.TASK_STATE_WORKING,
                final=False,
                message="Processing your request…",
            )
            return {"status": "success"}

        executor = make_executor((hook, False), execute_fn=execute_fn)
        await executor.execute(mock_context, mock_event_queue)

        # The agent's one progress message is intercepted; the framework's
        # working status (message-less) and the final status (emitted through
        # the plain tracked queue) are not.
        assert hook.events == ["Processing your request…"]
        events = status_events(mock_event_queue)
        texts = [status_event_message_text(event) for event in events]
        assert texts == [
            "",
            "[hooked] Processing your request…",
            json.dumps({"status": "success"}),
        ]

    async def test_on_event_structured_message_passes_through(self, mock_context, mock_event_queue):
        hook = RecordingHook()

        async def execute_fn(self, params, context, event_queue):
            event = build_status_update_event(
                context=context,
                state=TaskState.TASK_STATE_WORKING,
                final=False,
            )
            # The a2a event types are protobuf messages: install the
            # multi-part message through CopyFrom, not field assignment.
            event.status.message.CopyFrom(
                Message(
                    message_id="m-1",
                    role=Role.ROLE_AGENT,
                    parts=[Part(text="one"), Part(text="two")],
                    context_id=event.context_id,
                    task_id=event.task_id,
                )
            )
            await event_queue.enqueue_event(event)
            return {"status": "success"}

        executor = make_executor((hook, False), execute_fn=execute_fn)
        await executor.execute(mock_context, mock_event_queue)

        assert hook.events == []

    async def test_on_event_failure_degrades(self, mock_context, mock_event_queue):
        hook = RecordingHook(event_error=RuntimeError("nope"))

        async def execute_fn(self, params, context, event_queue):
            await emit_status_update(
                context=context,
                event_queue=event_queue,
                state=TaskState.TASK_STATE_WORKING,
                final=False,
                message="progress",
            )
            return {"status": "success"}

        executor = make_executor((hook, False), execute_fn=execute_fn)
        await executor.execute(mock_context, mock_event_queue)

        events = status_events(mock_event_queue)
        # events[0] is the framework's message-less working status; the
        # agent's degraded progress text follows.
        assert status_event_message_text(events[1]) == "progress"
        assert events[-1].status.state == TaskState.TASK_STATE_COMPLETED

    async def test_on_event_strict_failure_fails_task(self, mock_context, mock_event_queue):
        hook = RecordingHook(event_error=RuntimeError("nope"))

        async def execute_fn(self, params, context, event_queue):
            await emit_status_update(
                context=context,
                event_queue=event_queue,
                state=TaskState.TASK_STATE_WORKING,
                final=False,
                message="progress",
            )
            return {"status": "success"}

        executor = make_executor((hook, True), execute_fn=execute_fn)
        with pytest.raises(ExecuteHookError):
            await executor.execute(mock_context, mock_event_queue)

        events = status_events(mock_event_queue)
        assert events[-1].status.state == TaskState.TASK_STATE_FAILED

    async def test_on_result_rewrite_reaches_final_status(self, mock_context, mock_event_queue):
        hook = RecordingHook(result_rewrite={"status": "success", "data": "rewritten"})
        executor = make_executor((hook, False))

        await executor.execute(mock_context, mock_event_queue)

        events = status_events(mock_event_queue)
        assert json.loads(events[-1].status.message.parts[0].text) == {
            "status": "success",
            "data": "rewritten",
        }

    async def test_on_result_fail_open_passes_original(self, mock_context, mock_event_queue):
        hook = RecordingHook(result_error=ValueError("middleware down"))
        executor = make_executor((hook, False))

        await executor.execute(mock_context, mock_event_queue)

        events = status_events(mock_event_queue)
        assert json.loads(events[-1].status.message.parts[0].text) == {
            "status": "success",
            "data": "test data",
        }

    async def test_on_result_strict_fails_task(self, mock_context, mock_event_queue):
        hook = RecordingHook(result_error=ValueError("middleware down"))
        observer = RecordingHook()
        executor = make_executor((hook, True), (observer, False))

        with pytest.raises(ExecuteHookError):
            await executor.execute(mock_context, mock_event_queue)

        events = status_events(mock_event_queue)
        assert events[-1].status.state == TaskState.TASK_STATE_FAILED
        assert isinstance(observer.errors[0], ExecuteHookError)

    async def test_on_error_observes_agent_failure_without_aborting(
        self, mock_context, mock_event_queue
    ):
        hook = RecordingHook(error_error=RuntimeError("observer broke"))

        async def execute_fn(self, params, context, event_queue):
            raise ValueError("boom")

        executor = make_executor((hook, True), execute_fn=execute_fn)
        with pytest.raises(ValueError, match="boom"):
            await executor.execute(mock_context, mock_event_queue)

        assert isinstance(hook.errors[0], ValueError)
        assert hook.snapshots[0].outcome == "TASK_STATE_FAILED"
        assert hook.snapshots[0].error == "boom"

    async def test_on_task_success_snapshot_after_finalization(
        self, mock_context, mock_event_queue
    ):
        hook = RecordingHook()
        executor = make_executor((hook, False), execution_record_id_fn=lambda: 42)

        await executor.execute(mock_context, mock_event_queue)

        assert len(hook.snapshots) == 1
        snapshot = hook.snapshots[0]
        assert isinstance(snapshot, TaskSnapshot)
        assert snapshot.outcome == "TASK_STATE_COMPLETED"
        assert snapshot.result == {"status": "success", "data": "test data"}
        assert snapshot.error is None
        assert snapshot.execution_record_id == 42

    async def test_on_task_agent_self_finalized_outcome(self, mock_context, mock_event_queue):
        hook = RecordingHook()

        async def execute_fn(self, params, context, event_queue):
            await emit_status_update(
                context=context,
                event_queue=event_queue,
                state=TaskState.TASK_STATE_INPUT_REQUIRED,
                final=True,
                message="need more input",
            )
            return {"status": "input_required"}

        executor = make_executor((hook, False), execute_fn=execute_fn)
        await executor.execute(mock_context, mock_event_queue)

        assert len(hook.snapshots) == 1
        assert hook.snapshots[0].outcome == "TASK_STATE_INPUT_REQUIRED"
        assert hook.snapshots[0].message == "need more input"
        assert hook.snapshots[0].result == {"status": "input_required"}

    async def test_on_task_without_record_fn_reports_none(self, mock_context, mock_event_queue):
        hook = RecordingHook()
        executor = make_executor((hook, False))

        await executor.execute(mock_context, mock_event_queue)

        assert hook.snapshots[0].execution_record_id is None

    async def test_on_task_hook_failure_does_not_fail_task(self, mock_context, mock_event_queue):
        hook = RecordingHook(task_error=RuntimeError("memory backend down"))
        executor = make_executor((hook, True))

        await executor.execute(mock_context, mock_event_queue)

        events = status_events(mock_event_queue)
        assert events[-1].status.state == TaskState.TASK_STATE_COMPLETED


class TestAgentWiring:
    def test_add_execute_hook_appends_after_env_hooks(self, monkeypatch):
        monkeypatch.setenv(ENV_EXECUTE_MIDDLEWARE, "prometheus_api.agent.hooks:NoopExecuteHook")
        agent = PrometheusAgent(agent_name="MyAgent")
        author_hook = RecordingHook()
        agent.add_execute_hook(author_hook)

        executor = agent.create_executor()
        assert executor._execute_hooks[0][0].__class__ is NoopExecuteHook
        assert executor._execute_hooks[0][1] is False
        assert executor._execute_hooks[1][0] is author_hook

    def test_add_execute_hook_rejects_wrong_shape(self):
        agent = PrometheusAgent(agent_name="MyAgent")

        class BadHook:
            def on_request(self, context, params):
                return params

        with pytest.raises(ValueError, match="on_request must be an async def"):
            agent.add_execute_hook(BadHook())

    def test_malformed_env_var_fails_agent_construction(self, monkeypatch):
        monkeypatch.setenv(ENV_EXECUTE_MIDDLEWARE, "no-colon-here")
        with pytest.raises(ValueError, match="module:ClassName"):
            PrometheusAgent(agent_name="MyAgent")

    async def test_agent_hooks_drive_executor_end_to_end(self, mock_context, mock_event_queue):
        agent = PrometheusAgent(agent_name="MyAgent")
        hook = RecordingHook(request_rewrite={"input_data": "via agent"})
        agent.add_execute_hook(hook)
        executor = agent.create_executor()

        received = {}

        async def replacement(params, context, event_queue):
            received.update(params)
            return {"status": "success", "data": params.get("input_data")}

        executor._execute_fn = replacement

        # The delegating executor's standard scope creates a DeepLynx
        # execution record; this test wires hooks, not storage.
        async def no_scope(params, context):
            yield

        from contextlib import asynccontextmanager

        executor._establish_request_scope = asynccontextmanager(no_scope)
        await executor.execute(mock_context, mock_event_queue)

        assert executor._execute_hooks[0][0] is hook
        assert received["input_data"] == "via agent"
        events = status_events(mock_event_queue)
        assert json.loads(events[-1].status.message.parts[0].text) == {
            "status": "success",
            "data": "via agent",
        }
