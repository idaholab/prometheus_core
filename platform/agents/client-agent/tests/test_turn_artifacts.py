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

"""Turn-tagged conversation history: stamping, merge on store, atomic writes.

Several turns of one conversation can run at once (a backgrounded turn keeps
running while the user sends the next). A store must not erase another turn's
entries, and a turn's artifact ids must land on that turn's reply. A restored
conversation renders each reply from those ids (Prometheus Artifact Contract,
"Frontend viewer ownership").
"""

import json

import pytest

import conversation_store
from conversation_store import (
    LEGACY_TURN_ID,
    merge_conversation,
    record_turn_artifacts,
    stamp_turn_artifacts,
    store_conversation,
)
from orchestrator import task_tracking


def _entry(role, content, turn, ts, **extra):
    return {"role": role, "content": content, "turn_id": turn, "timestamp": ts, **extra}


# --- stamp_turn_artifacts -------------------------------------------------------


def test_stamps_the_last_reply_of_the_turn():
    history = [
        _entry("user", "mesh it", "T1", "t1"),
        _entry("assistant", "done", "T1", "t2", type="agent_response_mesh"),
        _entry("assistant", "done", "T1", "t3", type="final_report"),
        _entry("user", "done", "T1", "t4"),  # same text, but a user entry
    ]

    assert stamp_turn_artifacts(history, "T1", ["m1"]) is True

    assert history[2]["artifact_ids"] == ["m1"]
    assert [i for i, e in enumerate(history) if "artifact_ids" in e] == [2]


def test_identical_replies_of_two_turns_each_get_their_own_ids():
    # "SVG artifact created successfully." twice: text cannot tell them apart.
    history = [
        _entry("assistant", "SVG artifact created successfully.", "T1", "t1"),
        _entry("assistant", "SVG artifact created successfully.", "T2", "t2"),
    ]

    stamp_turn_artifacts(history, "T1", ["alpha"])
    stamp_turn_artifacts(history, "T2", ["beta"])

    assert [e["artifact_ids"] for e in history] == [["alpha"], ["beta"]]


def test_a_turn_without_a_reply_gets_no_stamp():
    # A plan rejection, or a form with an empty message: no content-bearing reply.
    history = [
        _entry("user", "go", "T1", "t1"),
        _entry("assistant", "", "T1", "t2"),
        _entry("assistant", "hi", "T0", "t0"),
    ]

    assert stamp_turn_artifacts(history, "T1", ["a1"]) is False
    assert all("artifact_ids" not in e for e in history)


def test_a_second_stamp_keeps_existing_ids_and_skips_repeats():
    history = [_entry("assistant", "done", "T1", "t1")]
    stamp_turn_artifacts(history, "T1", ["a1"])

    assert stamp_turn_artifacts(history, "T1", ["a1", "a2"]) is True
    assert history[0]["artifact_ids"] == ["a1", "a2"]
    assert stamp_turn_artifacts(history, "T1", ["a2"]) is False
    assert stamp_turn_artifacts(history, "T1", []) is False
    assert stamp_turn_artifacts(history, "", ["a3"]) is False


# --- merge_conversation -----------------------------------------------------------


def test_a_late_background_store_keeps_the_newer_turns_entries():
    # B (background) read the conversation before F ran; F stored first.
    stored = {
        "conversation_history": [
            _entry("user", "long job", "B", "10:00"),
            _entry("user", "quick svg", "F", "10:02"),
            _entry("assistant", "svg done", "F", "10:03", artifact_ids=["svg"]),
        ],
        "state_turn_id": "F",
        "state_turn_started_at": 200.0,
        "awaiting_approval": True,
        "title": "Quick SVG",
    }
    b_local = {
        "conversation_history": [
            _entry("user", "long job", "B", "10:00"),
            _entry("assistant", "job done", "B", "10:10"),
        ],
        "awaiting_approval": False,
        "title": "",
    }

    merged = merge_conversation(stored, b_local, turn_id="B", started_at=100.0)

    assert [(e["turn_id"], e["content"]) for e in merged["conversation_history"]] == [
        ("B", "long job"),
        ("F", "quick svg"),
        ("F", "svg done"),
        ("B", "job done"),
    ]
    assert merged["conversation_history"][2]["artifact_ids"] == ["svg"]
    # F started later, so it keeps the top-level fields (its pending plan).
    assert merged["awaiting_approval"] is True
    assert merged["state_turn_id"] == "F"


def test_the_newest_started_turn_owns_the_top_level_fields():
    stored = {
        "conversation_history": [],
        "state_turn_id": "A",
        "state_turn_started_at": 100.0,
        "plan": "old",
        "title": "Kept",
    }
    local = {"conversation_history": [_entry("user", "hi", "B", "t1")], "plan": "new", "title": ""}

    merged = merge_conversation(stored, local, turn_id="B", started_at=200.0)

    assert merged["plan"] == "new"
    assert merged["title"] == "Kept"  # a title is never cleared
    assert (merged["state_turn_id"], merged["state_turn_started_at"]) == ("B", 200.0)


def test_other_turns_come_from_the_stored_copy():
    # The local copy is the snapshot a turn read; the stored copy has the stamp.
    stored = {"conversation_history": [_entry("assistant", "old", "A", "t1", artifact_ids=["a1"])]}
    local = {"conversation_history": [_entry("assistant", "old", "A", "t1"), _entry("user", "next", "B", "t2")]}

    merged = merge_conversation(stored, local, turn_id="B", started_at=1.0)

    assert merged["conversation_history"] == [
        _entry("assistant", "old", "A", "t1", artifact_ids=["a1"]),
        _entry("user", "next", "B", "t2"),
    ]


def test_a_late_turn_that_leaves_a_form_takes_the_fields_from_one_that_left_none():
    # The user answers B's form next; chat() resumes it from the top-level fields.
    stored = {"conversation_history": [], "state_turn_id": "F", "state_turn_started_at": 200.0, "missing_info": []}
    b_local = {"conversation_history": [], "missing_info": ["width"], "pending_calls": [{"id": "c1"}]}

    merged = merge_conversation(stored, b_local, turn_id="B", started_at=100.0)

    assert merged["missing_info"] == ["width"]
    assert merged["pending_calls"] == [{"id": "c1"}]
    assert merged["state_turn_id"] == "B"


def test_unfinished_pending_calls_alone_count_as_pending_input():
    stored = {"conversation_history": [], "state_turn_id": "F", "state_turn_started_at": 200.0}
    b_local = {"conversation_history": [], "pending_calls": [{"id": "c1", "status": "waiting_input"}]}

    merged = merge_conversation(stored, b_local, turn_id="B", started_at=100.0)

    assert merged["pending_calls"] == [{"id": "c1", "status": "waiting_input"}]
    assert merged["state_turn_id"] == "B"


# --- llm_messages merge ----------------------------------------------------------


def _msg(content, turn, started_at, role="user"):
    return {"role": role, "content": content, "turn_id": turn, "turn_started_at": started_at}


def test_llm_messages_keep_each_turns_block_ordered_by_turn_start():
    # A (started 100) runs in the background; F (started 200) stored first.
    stored = {
        "conversation_history": [],
        "state_turn_id": "F",
        "state_turn_started_at": 200.0,
        "llm_messages": [
            _msg("old", "legacy", 0.0),
            _msg("f question", "F", 200.0),
            _msg("f answer", "F", 200.0, "assistant"),
        ],
    }
    a_local = {
        "conversation_history": [],
        "llm_messages": [
            _msg("old", "legacy", 0.0),
            _msg("a question", "A", 100.0),
            _msg("a answer", "A", 100.0, "assistant"),
        ],
    }

    merged = merge_conversation(stored, a_local, turn_id="A", started_at=100.0)

    assert [m["content"] for m in merged["llm_messages"]] == ["old", "a question", "a answer", "f question", "f answer"]
    # F still owns the other fields; only the transcripts merged.
    assert merged["state_turn_id"] == "F"


def test_merged_llm_messages_stay_bounded():
    from orchestrator.agent_loop import MAX_TRANSCRIPT_MESSAGES

    # Earlier turns' messages come back from storage on every merge.
    earlier = [_msg(f"{role} {i}", f"T{i}", float(i), role) for i in range(60) for role in ("user", "assistant")]
    stored = {"conversation_history": [], "llm_messages": earlier}
    local = {
        "conversation_history": [],
        "llm_messages": [_msg("new question", "N", 100.0), _msg("new answer", "N", 100.0, "assistant")],
    }

    merged = merge_conversation(stored, local, turn_id="N", started_at=100.0)

    assert len(merged["llm_messages"]) <= MAX_TRANSCRIPT_MESSAGES
    assert merged["llm_messages"][0]["role"] == "user"  # cut only at a user message
    assert [m["content"] for m in merged["llm_messages"][-2:]] == ["new question", "new answer"]


def test_when_both_turns_leave_pending_input_the_newer_one_wins():
    stored = {
        "conversation_history": [],
        "state_turn_id": "F",
        "state_turn_started_at": 200.0,
        "awaiting_approval": True,
    }
    b_local = {"conversation_history": [], "missing_info": ["width"]}

    merged = merge_conversation(stored, b_local, turn_id="B", started_at=100.0)

    assert merged["awaiting_approval"] is True
    assert "missing_info" not in merged
    assert merged["state_turn_id"] == "F"


def test_an_entry_without_a_timestamp_goes_after_the_stored_ones():
    stored = {"conversation_history": [_entry("user", "a", "A", "t1")]}
    local = {"conversation_history": [_entry("user", "b", "B", "")]}

    merged = merge_conversation(stored, local, turn_id="B", started_at=1.0)

    assert [e["content"] for e in merged["conversation_history"]] == ["a", "b"]


def test_the_first_store_takes_the_local_copy():
    local = {"conversation_history": [_entry("user", "hi", "B", "t1")], "user_query": "hi"}

    merged = merge_conversation(None, local, turn_id="B", started_at=5.0)

    assert merged["conversation_history"] == local["conversation_history"]
    assert (merged["user_query"], merged["state_turn_id"]) == ("hi", "B")


# --- I/O -------------------------------------------------------------------------


class _FakePipe:
    def __init__(self, store):
        self._store = store
        self._queued = []

    def get(self, key):
        return self._store.get(key)

    def multi(self):
        self._in_multi = True

    def set(self, key, value):
        assert getattr(self, "_in_multi", False), "set() must be queued after multi()"
        self._queued.append((key, value))


class _FakeClient:
    """Just enough of redis-py: ``get`` and ``transaction(fn, key)``."""

    def __init__(self, store=None):
        self.store = dict(store or {})
        self.transactions = 0

    def get(self, key):
        return self.store.get(key)

    def transaction(self, fn, *keys):
        assert keys, "transaction() must WATCH the conversation key"
        self.transactions += 1
        pipe = _FakePipe(self.store)
        fn(pipe)
        for key, value in pipe._queued:
            assert key in keys, f"{key} was written without being watched"
            self.store[key] = value


@pytest.fixture()
def client(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(conversation_store, "_get_conversation_store_client", lambda: fake)
    task_tracking._turn.set(None)
    return fake


def test_store_tags_this_turns_entries_and_reads_untagged_ones_as_legacy(client):
    client.store["conversation:c1"] = json.dumps(
        {"conversation_history": [{"role": "user", "content": "old", "timestamp": "t0"}]}
    )
    task_tracking.begin_turn("c1", "new")
    turn_id = task_tracking.current_turn_id()

    state = conversation_store.get_conversation("c1")
    state["conversation_history"].append({"role": "user", "content": "new", "timestamp": "t1"})
    store_conversation("c1", state)

    saved = json.loads(client.store["conversation:c1"])
    assert [(e["content"], e["turn_id"]) for e in saved["conversation_history"]] == [
        ("old", LEGACY_TURN_ID),
        ("new", turn_id),
    ]
    assert saved["state_turn_id"] == turn_id


def test_early_and_final_store_keep_one_user_entry(client):
    """A store at turn start, then the final store of the same turn, leave one user
    entry tagged with that turn and keep the title the final store sets."""
    task_tracking.begin_turn("c1", "q")
    turn_id = task_tracking.current_turn_id()
    state = {"conversation_history": [{"role": "user", "content": "q", "timestamp": "t1"}]}
    store_conversation("c1", state)

    state["conversation_history"].append({"role": "assistant", "content": "the reply", "timestamp": "t2"})
    state["title"] = "Q chat"
    store_conversation("c1", state)

    saved = json.loads(client.store["conversation:c1"])
    assert [(e["content"], e["turn_id"]) for e in saved["conversation_history"]] == [
        ("q", turn_id),
        ("the reply", turn_id),
    ]
    assert saved["title"] == "Q chat"


def test_store_tags_this_turns_llm_messages_and_reads_untagged_ones_as_legacy(client):
    client.store["conversation:c1"] = json.dumps(
        {"conversation_history": [], "llm_messages": [{"role": "user", "content": "old"}]}
    )
    state = conversation_store.get_conversation("c1")
    assert state["llm_messages"][0]["turn_id"] == LEGACY_TURN_ID

    task_tracking.begin_turn("c1", "next")
    turn = task_tracking.current_turn()
    state["llm_messages"].append({"role": "user", "content": "new"})
    store_conversation("c1", state)

    stored = json.loads(client.store["conversation:c1"])["llm_messages"]
    assert [m["turn_id"] for m in stored] == [LEGACY_TURN_ID, turn.turn_id]
    assert stored[1]["turn_started_at"] == turn.started_at


def test_record_turn_artifacts_stamps_the_stored_reply(client):
    client.store["conversation:c1"] = json.dumps(
        {"conversation_history": [_entry("assistant", "done", "T1", "t1"), _entry("assistant", "done", "T2", "t2")]}
    )

    record_turn_artifacts("c1", "T1", ["a1"])

    saved = json.loads(client.store["conversation:c1"])
    assert [e.get("artifact_ids") for e in saved["conversation_history"]] == [["a1"], None]


def test_record_turn_artifacts_without_ids_touches_nothing(monkeypatch):
    def _no_redis():
        raise AssertionError("no Redis access expected")

    monkeypatch.setattr(conversation_store, "_get_conversation_store_client", _no_redis)

    record_turn_artifacts("c1", "T1", [])
    record_turn_artifacts("c1", "", ["a1"])


def test_record_turn_artifacts_skips_the_write_without_a_matching_reply(client):
    untouched = json.dumps({"conversation_history": [_entry("assistant", "done", "T2", "t2")]}, indent=1)
    client.store["conversation:c1"] = untouched

    record_turn_artifacts("c1", "T1", ["a1"])
    record_turn_artifacts("missing", "T1", ["a1"])

    assert client.store == {"conversation:c1": untouched}
