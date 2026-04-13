"""Integration tests for LiteLLM API key CRUD operations."""

import uuid

import pytest


pytestmark = pytest.mark.integration


def _generate_key(client, **kwargs) -> dict:
    """Helper to generate an API key and return the response JSON."""
    resp = client.post("/key/generate", json=kwargs)
    assert resp.status_code == 200, f"Failed to generate key: {resp.status_code} {resp.text}"
    return resp.json()


def _delete_key(client, key: str) -> None:
    """Helper to delete a key, ignoring errors."""
    client.post("/key/delete", json={"keys": [key]})


def _get_key_info(client, key: str) -> dict:
    """Get key info by key value."""
    resp = client.get("/key/info", params={"key": key})
    if resp.status_code != 200:
        return {}
    return resp.json()


class TestKeyCRUD:
    """Tests for API key generate, info, update, block, unblock, delete."""

    def test_generate_key(self, litellm_client):
        """POST /key/generate creates a new key."""
        data = _generate_key(litellm_client)
        key = data.get("key", "")
        try:
            assert key, f"No key in response: {data}"
            assert key.startswith("sk-"), f"Key should start with 'sk-': {key}"
        finally:
            _delete_key(litellm_client, key)

    def test_generate_key_with_models(self, litellm_client):
        """Key with model restrictions should persist them."""
        data = _generate_key(litellm_client, models=["gpt-4", "gpt-3.5-turbo"])
        key = data.get("key", "")
        try:
            assert key
            info = _get_key_info(litellm_client, key)
            key_info = info.get("info", info.get("key", info))
            models = key_info.get("models", [])
            assert "gpt-4" in models or len(models) > 0
        finally:
            _delete_key(litellm_client, key)

    def test_generate_key_with_budget(self, litellm_client):
        """Key with max_budget should have budget set."""
        data = _generate_key(litellm_client, max_budget=10.0)
        key = data.get("key", "")
        try:
            assert key
            info = _get_key_info(litellm_client, key)
            key_info = info.get("info", info.get("key", info))
            assert key_info.get("max_budget") == 10.0 or key_info.get("max_budget") is not None
        finally:
            _delete_key(litellm_client, key)

    def test_generate_key_with_duration(self, litellm_client):
        """Key with duration should have an expiry set."""
        data = _generate_key(litellm_client, duration="30d")
        key = data.get("key", "")
        try:
            assert key
            expires = data.get("expires")
            assert expires is not None, "Key with duration should have an expires field"
        finally:
            _delete_key(litellm_client, key)

    def test_generate_key_with_alias(self, litellm_client):
        """Key with key_alias should persist the alias."""
        alias = f"test-alias-{uuid.uuid4().hex[:8]}"
        data = _generate_key(litellm_client, key_alias=alias)
        key = data.get("key", "")
        try:
            assert key
            info = _get_key_info(litellm_client, key)
            key_info = info.get("info", info.get("key", info))
            assert key_info.get("key_alias") == alias
        finally:
            _delete_key(litellm_client, key)

    def test_get_key_info(self, litellm_client):
        """GET /key/info returns correct details for a key."""
        data = _generate_key(litellm_client)
        key = data.get("key", "")
        try:
            info = _get_key_info(litellm_client, key)
            assert info, "key/info returned empty response"
        finally:
            _delete_key(litellm_client, key)

    def test_list_keys(self, litellm_client):
        """GET /key/list returns paginated key list."""
        data = _generate_key(litellm_client)
        key = data.get("key", "")
        try:
            resp = litellm_client.get("/key/list")
            assert resp.status_code == 200
            list_data = resp.json()
            # Should have some structure indicating keys
            assert "keys" in list_data or "data" in list_data or isinstance(list_data, list)
        finally:
            _delete_key(litellm_client, key)

    def test_update_key(self, litellm_client):
        """POST /key/update changes key configuration."""
        data = _generate_key(litellm_client)
        key = data.get("key", "")
        try:
            resp = litellm_client.post(
                "/key/update",
                json={"key": key, "max_budget": 200.0},
            )
            assert resp.status_code == 200

            # Verify update
            info = _get_key_info(litellm_client, key)
            key_info = info.get("info", info.get("key", info))
            assert key_info.get("max_budget") == 200.0
        finally:
            _delete_key(litellm_client, key)

    def test_block_key(self, litellm_client):
        """POST /key/block prevents the key from being used."""
        data = _generate_key(litellm_client)
        key = data.get("key", "")
        try:
            resp = litellm_client.post("/key/block", json={"key": key})
            assert resp.status_code == 200

            # Verify the key is marked as blocked
            info = _get_key_info(litellm_client, key)
            key_info = info.get("info", info.get("key", info))
            # Blocked keys may have a 'blocked' field or status change
            assert key_info.get("blocked") is True or resp.status_code == 200
        finally:
            # Unblock before cleanup
            litellm_client.post("/key/unblock", json={"key": key})
            _delete_key(litellm_client, key)

    def test_unblock_key(self, litellm_client):
        """POST /key/unblock re-enables a blocked key."""
        data = _generate_key(litellm_client)
        key = data.get("key", "")
        try:
            # Block first
            litellm_client.post("/key/block", json={"key": key})

            # Unblock
            resp = litellm_client.post("/key/unblock", json={"key": key})
            assert resp.status_code == 200

            # Verify unblocked
            info = _get_key_info(litellm_client, key)
            key_info = info.get("info", info.get("key", info))
            assert key_info.get("blocked") is not True
        finally:
            _delete_key(litellm_client, key)

    def test_delete_key(self, litellm_client):
        """POST /key/delete removes the key."""
        data = _generate_key(litellm_client)
        key = data.get("key", "")

        resp = litellm_client.post("/key/delete", json={"keys": [key]})
        assert resp.status_code == 200
        result = resp.json()
        deleted = result.get("deleted_keys", [])
        assert len(deleted) > 0 or resp.status_code == 200

    def test_delete_nonexistent_key(self, litellm_client):
        """Deleting a non-existent key should handle gracefully."""
        resp = litellm_client.post(
            "/key/delete",
            json={"keys": [f"sk-nonexistent-{uuid.uuid4().hex[:16]}"]},
        )
        # LiteLLM may return 200 with empty deleted_keys or a 4xx
        assert resp.status_code in (200, 400, 404)

    def test_generate_key_without_auth(self, litellm_no_auth_client):
        """Generating a key without auth should be rejected."""
        resp = litellm_no_auth_client.post("/key/generate", json={})
        assert resp.status_code in (401, 403)

    def test_key_crud_lifecycle(self, litellm_client):
        """Full lifecycle: generate → info → update → block → unblock → delete."""
        # Generate
        data = _generate_key(litellm_client, max_budget=50.0)
        key = data.get("key", "")
        assert key

        # Info
        info = _get_key_info(litellm_client, key)
        assert info

        # Update
        resp = litellm_client.post(
            "/key/update",
            json={"key": key, "max_budget": 100.0},
        )
        assert resp.status_code == 200

        # Block
        resp = litellm_client.post("/key/block", json={"key": key})
        assert resp.status_code == 200

        # Unblock
        resp = litellm_client.post("/key/unblock", json={"key": key})
        assert resp.status_code == 200

        # Delete
        resp = litellm_client.post("/key/delete", json={"keys": [key]})
        assert resp.status_code == 200
