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

"""Tests for the shared A2A stream-consumption helpers."""

import json

import pytest

from prometheus_api.a2a_stream import (
    A2AStreamError,
    apply_stream_event,
    consume_stream_response,
    extract_status_message_text,
    merge_artifacts,
    new_task_accumulator,
)


class _FakeStreamResponse:
    def __init__(self, lines, *, content_type="application/x-ndjson"):
        self._lines = lines
        self.headers = {"content-type": content_type}

    async def aiter_lines(self):
        for line in self._lines:
            yield line


def _status_event(
    text,
    *,
    task_id="task-1",
    context_id="ctx-1",
    state="TASK_STATE_WORKING",
):
    return {
        "result": {
            "statusUpdate": {
                "taskId": task_id,
                "contextId": context_id,
                "status": {
                    "state": state,
                    "message": {"parts": [{"text": text}]},
                },
            }
        }
    }


def _artifact_event(artifact):
    return {"result": {"artifactUpdate": {"artifact": artifact}}}


# ---------------------------------------------------------------------------
# extract_status_message_text
# ---------------------------------------------------------------------------


def test_extract_text_from_bare_part():
    status = {"message": {"parts": [{"text": " hello "}]}}
    assert extract_status_message_text(status) == "hello"


def test_extract_text_ignores_valid_non_text_parts():
    status = {
        "message": {
            "parts": [
                {"data": {"x": 1}},
                {"text": "found"},
            ]
        }
    }
    assert extract_status_message_text(status) == "found"
    assert extract_status_message_text(None) == ""
    assert extract_status_message_text({}) == ""


@pytest.mark.parametrize(
    "part",
    [
        "garbage",
        {"root": {"kind": "text", "text": "pre-v1"}},
        {"kind": "text", "text": "pre-v1"},
    ],
)
def test_extract_text_rejects_malformed_or_pre_v1_parts(part):
    with pytest.raises(A2AStreamError, match="Part"):
        extract_status_message_text({"message": {"parts": [part]}})


# ---------------------------------------------------------------------------
# merge_artifacts
# ---------------------------------------------------------------------------


def test_merge_artifacts_dedupes_by_artifact_id_then_name():
    existing = [{"artifactId": "a-1", "name": "one"}, {"name": "keyed-by-name"}]
    incoming = [
        {"artifactId": "a-1", "name": "duplicate"},
        {"name": "keyed-by-name"},
        {"artifactId": "a-2", "name": "two"},
        "not-a-dict",
    ]
    merged = merge_artifacts(existing, incoming)
    assert [a.get("artifactId") or a.get("name") for a in merged] == [
        "a-1",
        "keyed-by-name",
        "a-2",
    ]


def test_merge_artifacts_keeps_unkeyed_artifacts():
    merged = merge_artifacts([], [{"parts": []}, {"parts": []}])
    assert len(merged) == 2


# ---------------------------------------------------------------------------
# apply_stream_event
# ---------------------------------------------------------------------------


async def test_initial_v1_task_populates_accumulator():
    result = await apply_stream_event(
        new_task_accumulator(),
        {
            "result": {
                "task": {
                    "id": "task-1",
                    "contextId": "ctx-1",
                    "status": {"state": "TASK_STATE_SUBMITTED"},
                    "artifacts": [{"artifactId": "a-1", "name": "input"}],
                }
            }
        },
    )

    assert result["id"] == "task-1"
    assert result["contextId"] == "ctx-1"
    assert result["status"]["state"] == "TASK_STATE_SUBMITTED"
    assert result["artifacts"] == [{"artifactId": "a-1", "name": "input"}]


async def test_status_update_accumulates_and_fires_callback():
    seen = []

    async def on_status(text):
        seen.append(text)

    result = new_task_accumulator()
    result = await apply_stream_event(
        result, _status_event("Working on it"), status_callback=on_status
    )
    result = await apply_stream_event(
        result,
        _status_event("Done", state="TASK_STATE_COMPLETED"),
        status_callback=on_status,
    )

    # Terminal status events do not fire the status callback.
    assert seen == ["Working on it"]
    assert result["id"] == "task-1"
    assert result["contextId"] == "ctx-1"
    assert result["status"]["state"] == "TASK_STATE_COMPLETED"


async def test_invalid_task_state_spelling_raises():
    with pytest.raises(A2AStreamError, match="TASK_STATE_"):
        await apply_stream_event(
            new_task_accumulator(),
            _status_event("Done", state="completed"),
        )


async def test_heartbeat_events_are_skipped():
    result = await apply_stream_event(
        {
            "kind": "task",
            "artifacts": [],
            "status": {"state": "TASK_STATE_WORKING"},
        },
        {"result": {"statusUpdate": {"metadata": {"heartbeat": True}, "status": {}}}},
    )
    # Accumulated status not overwritten by the empty heartbeat payload.
    assert result["status"] == {"state": "TASK_STATE_WORKING"}


async def test_background_metadata_fires_background_callback():
    captured = []

    async def on_background(metadata):
        captured.append(metadata)

    await apply_stream_event(
        new_task_accumulator(),
        {
            "result": {
                "statusUpdate": {
                    "metadata": {"background": True, "estimate_seconds": 120},
                    "status": {"state": "TASK_STATE_WORKING"},
                }
            }
        },
        background_callback=on_background,
    )
    assert captured == [{"background": True, "estimate_seconds": 120}]


async def test_error_envelope_raises():
    with pytest.raises(A2AStreamError, match="boom"):
        await apply_stream_event(new_task_accumulator(), {"error": "boom"})


async def test_non_dict_result_raises():
    with pytest.raises(A2AStreamError, match="result must be an object"):
        await apply_stream_event(new_task_accumulator(), {"result": "noise"})


async def test_pre_v1_event_shape_raises():
    """Covers BEH-011-04."""
    with pytest.raises(A2AStreamError, match="exactly one StreamResponse payload"):
        await apply_stream_event(
            new_task_accumulator(),
            {
                "result": {
                    "kind": "status-update",
                    "final": True,
                    "status": {"state": "completed"},
                }
            },
        )


# ---------------------------------------------------------------------------
# consume_stream_response
# ---------------------------------------------------------------------------


async def test_consume_ndjson_stream():
    final_payload = {"status": "completed", "message": "ok"}
    lines = [
        json.dumps(_status_event("Step 1")),
        "",
        json.dumps(_artifact_event({"artifactId": "a-1", "name": "mesh.exo"})),
        json.dumps(
            _status_event(
                json.dumps(final_payload),
                state="TASK_STATE_COMPLETED",
            )
        ),
    ]
    statuses = []

    async def on_status(text):
        statuses.append(text)

    result = await consume_stream_response(_FakeStreamResponse(lines), status_callback=on_status)

    assert statuses == ["Step 1"]
    assert result["artifacts"] == [{"artifactId": "a-1", "name": "mesh.exo"}]
    assert json.loads(extract_status_message_text(result["status"])) == final_payload


async def test_consume_sse_stream_with_comments_and_multiline_data():
    event_one = json.dumps(_status_event("Working"))
    event_two = json.dumps(_status_event("Final", state="TASK_STATE_COMPLETED"))
    lines = [
        ": keepalive comment",
        f"data: {event_one[:10]}",
        f"data: {event_one[10:]}",
        "",
        f"data: {event_two}",
        # stream ends without trailing blank line — final block must still flush
    ]
    result = await consume_stream_response(
        _FakeStreamResponse(lines, content_type="text/event-stream")
    )
    assert result["status"]["state"] == "TASK_STATE_COMPLETED"


async def test_consume_json_response_surfaces_json_rpc_error():
    lines = [json.dumps({"error": {"code": -32601, "message": "Method not found"}})]
    with pytest.raises(A2AStreamError, match="Method not found"):
        await consume_stream_response(_FakeStreamResponse(lines, content_type="application/json"))


async def test_consume_rejects_unknown_content_type():
    with pytest.raises(A2AStreamError, match="content type"):
        await consume_stream_response(_FakeStreamResponse([], content_type="text/plain"))
