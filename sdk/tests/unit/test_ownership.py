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

"""Unit tests for prometheus_api.agent.ownership."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from prometheus_api.agent.ownership import (
    assert_conversation_owner,
    get_conversation_owner,
    list_user_conversations,
    record_conversation_owner,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_redis(owner_value=None, smembers_value=None):
    """Build a minimal Redis mock."""
    r = MagicMock()
    r.get.return_value = owner_value
    r.smembers.return_value = smembers_value or set()
    return r


# ---------------------------------------------------------------------------
# record_conversation_owner
# ---------------------------------------------------------------------------


def test_record_sets_owner_with_nx():
    r = _make_redis()
    with patch("prometheus_api.agent.ownership._get_redis", return_value=r):
        record_conversation_owner("conv-1", "alice")
    r.set.assert_called_once_with("conv_owner:conv-1", "alice", nx=True)


def test_record_adds_to_user_index():
    r = _make_redis()
    with patch("prometheus_api.agent.ownership._get_redis", return_value=r):
        record_conversation_owner("conv-2", "bob")
    r.sadd.assert_called_once_with("user:convs:bob", "conv-2")


def test_record_skips_when_conversation_id_empty():
    r = _make_redis()
    with patch("prometheus_api.agent.ownership._get_redis", return_value=r):
        record_conversation_owner("", "alice")
    r.set.assert_not_called()


def test_record_skips_when_user_id_empty():
    r = _make_redis()
    with patch("prometheus_api.agent.ownership._get_redis", return_value=r):
        record_conversation_owner("conv-3", "")
    r.set.assert_not_called()


def test_record_tolerates_redis_error():
    r = MagicMock()
    r.set.side_effect = ConnectionError("redis down")
    with patch("prometheus_api.agent.ownership._get_redis", return_value=r):
        # Must not raise
        record_conversation_owner("conv-4", "carol")


def test_record_tolerates_none_redis():
    with patch("prometheus_api.agent.ownership._get_redis", return_value=None):
        # Must not raise
        record_conversation_owner("conv-5", "dave")


# ---------------------------------------------------------------------------
# get_conversation_owner
# ---------------------------------------------------------------------------


def test_get_returns_owner_string():
    r = _make_redis(owner_value=b"alice")
    with patch("prometheus_api.agent.ownership._get_redis", return_value=r):
        assert get_conversation_owner("conv-1") == "alice"


def test_get_returns_none_when_missing():
    r = _make_redis(owner_value=None)
    with patch("prometheus_api.agent.ownership._get_redis", return_value=r):
        assert get_conversation_owner("conv-missing") is None


def test_get_returns_none_on_redis_error():
    r = MagicMock()
    r.get.side_effect = ConnectionError("redis down")
    with patch("prometheus_api.agent.ownership._get_redis", return_value=r):
        assert get_conversation_owner("conv-6") is None


def test_get_returns_none_when_conversation_empty():
    with patch("prometheus_api.agent.ownership._get_redis") as mock_get_redis:
        result = get_conversation_owner("")
    mock_get_redis.assert_not_called()
    assert result is None


# ---------------------------------------------------------------------------
# assert_conversation_owner
# ---------------------------------------------------------------------------


def test_assert_passes_for_correct_owner():
    r = _make_redis(owner_value=b"alice")
    with patch("prometheus_api.agent.ownership._get_redis", return_value=r):
        # No exception
        assert_conversation_owner("conv-1", "alice")


def test_assert_raises_for_wrong_user():
    r = _make_redis(owner_value=b"alice")
    with patch("prometheus_api.agent.ownership._get_redis", return_value=r):
        with pytest.raises(PermissionError, match="owned by a different user"):
            assert_conversation_owner("conv-1", "bob")


def test_assert_passes_when_no_record_exists():
    r = _make_redis(owner_value=None)
    with patch("prometheus_api.agent.ownership._get_redis", return_value=r):
        # No record = first touch; should not raise
        assert_conversation_owner("conv-new", "alice")


def test_assert_passes_on_redis_error():
    r = MagicMock()
    r.get.side_effect = ConnectionError("redis down")
    with patch("prometheus_api.agent.ownership._get_redis", return_value=r):
        # Degraded mode — should not block the request
        assert_conversation_owner("conv-7", "carol")


def test_assert_skips_when_conversation_empty():
    with patch("prometheus_api.agent.ownership._get_redis") as mock_get_redis:
        assert_conversation_owner("", "alice")
    mock_get_redis.assert_not_called()


# ---------------------------------------------------------------------------
# list_user_conversations
# ---------------------------------------------------------------------------


def test_list_returns_conversation_ids():
    members = {b"conv-a", b"conv-b", b"conv-c"}
    r = _make_redis(smembers_value=members)
    with patch("prometheus_api.agent.ownership._get_redis", return_value=r):
        result = list_user_conversations("alice")
    assert set(result) == {"conv-a", "conv-b", "conv-c"}


def test_list_returns_empty_for_unknown_user():
    r = _make_redis(smembers_value=set())
    with patch("prometheus_api.agent.ownership._get_redis", return_value=r):
        result = list_user_conversations("nobody")
    assert result == []


def test_list_returns_empty_on_redis_error():
    r = MagicMock()
    r.smembers.side_effect = ConnectionError("redis down")
    with patch("prometheus_api.agent.ownership._get_redis", return_value=r):
        assert list_user_conversations("dave") == []


def test_list_returns_empty_for_empty_user_id():
    with patch("prometheus_api.agent.ownership._get_redis") as mock_get_redis:
        result = list_user_conversations("")
    mock_get_redis.assert_not_called()
    assert result == []


def test_list_decodes_bytes_members():
    r = _make_redis(smembers_value={b"conv-x", "conv-y"})
    with patch("prometheus_api.agent.ownership._get_redis", return_value=r):
        result = list_user_conversations("eve")
    assert "conv-x" in result
    assert "conv-y" in result
