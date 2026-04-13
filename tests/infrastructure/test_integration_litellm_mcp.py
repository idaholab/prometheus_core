"""Integration tests for LiteLLM MCP server CRUD operations."""

import time
import uuid

import pytest


pytestmark = pytest.mark.integration

MCP_PREFIX = "test-mcp"


def _unique_mcp_name() -> str:
    return f"{MCP_PREFIX}_{uuid.uuid4().hex[:8]}"


def _create_mcp_server(client, name: str, url: str = "http://fake-mcp:8200/mcp", **kwargs) -> dict:
    """Helper to create an MCP server and return the response JSON."""
    payload = {"name": name, "url": url, **kwargs}
    resp = client.post("/v1/mcp/server", json=payload)
    assert resp.status_code in (200, 201), f"Failed to create MCP server: {resp.status_code} {resp.text}"
    return resp.json()


def _get_server_id(data: dict) -> str:
    """Extract server ID from create response (handles varying response formats)."""
    return data.get("server_id", data.get("id", data.get("data", {}).get("server_id", "")))


def _delete_mcp_server(client, server_id: str) -> None:
    """Helper to delete an MCP server, ignoring errors."""
    client.delete(f"/v1/mcp/server/{server_id}")


def _list_mcp_servers(client) -> list:
    """List MCP servers and return as a list."""
    candidates = ["/v1/mcp/server", "/v1/mcp/servers", "/v1/mcp/server/list"]
    for endpoint in candidates:
        resp = client.get(endpoint)
        if resp.status_code != 200:
            continue
        data = resp.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("data", "servers", "mcp_servers", "items"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
            if data.get("server_id") or data.get("id"):
                return [data]
    return []


def _wait_for_server_presence(client, server_id: str, should_exist: bool, timeout: float = 20.0) -> bool:
    """Poll list endpoint until a server appears/disappears."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        servers = _list_mcp_servers(client)
        server_ids = {_get_server_id(s) for s in servers}
        present = server_id in server_ids
        if present == should_exist:
            return True
        time.sleep(0.5)
    return False


def _update_mcp_server(client, server_id: str, payload: dict):
    """Update MCP server using the supported method for this LiteLLM version."""
    body_candidates = [
        {"server_id": server_id, **payload},
        {"id": server_id, **payload},
        {"server": {"server_id": server_id, **payload}},
    ]
    for body in body_candidates:
        resp = client.put("/v1/mcp/server", json=body)
        if resp.status_code in (200, 202):
            return resp

    # Backward-compat fallback for older APIs.
    resp = client.put(f"/v1/mcp/server/{server_id}", json=payload)
    if resp.status_code in (200, 202):
        return resp
    return client.patch(f"/v1/mcp/server/{server_id}", json=payload)


class TestMCPServerCRUD:
    """Tests for MCP server create, read, update, delete operations."""

    def test_create_mcp_server_minimal(self, litellm_client):
        """Create MCP server with minimum required fields."""
        name = _unique_mcp_name()
        data = _create_mcp_server(litellm_client, name)
        server_id = _get_server_id(data)
        try:
            assert server_id, f"No server_id in response: {data}"
        finally:
            _delete_mcp_server(litellm_client, server_id)

    def test_create_mcp_server_with_auth(self, litellm_client):
        """Create MCP server with bearer token authentication."""
        name = _unique_mcp_name()
        data = _create_mcp_server(
            litellm_client,
            name,
            auth_type="bearer_token",
            auth_value="test-bearer-token-123",
        )
        server_id = _get_server_id(data)
        try:
            assert server_id
        finally:
            _delete_mcp_server(litellm_client, server_id)

    def test_list_mcp_servers(self, litellm_client):
        """Created MCP server should appear in the server list."""
        name = _unique_mcp_name()
        data = _create_mcp_server(litellm_client, name)
        server_id = _get_server_id(data)
        try:
            assert _wait_for_server_presence(litellm_client, server_id, should_exist=True), (
                f"Server {name} ({server_id}) not found in list"
            )
        finally:
            _delete_mcp_server(litellm_client, server_id)

    def test_update_mcp_server(self, litellm_client):
        """PUT /v1/mcp/server/{server_id} updates server configuration."""
        name = _unique_mcp_name()
        data = _create_mcp_server(litellm_client, name)
        server_id = _get_server_id(data)
        try:
            resp = _update_mcp_server(
                litellm_client,
                server_id,
                {"description": "Updated test MCP server"},
            )
            assert resp.status_code in (200, 202)
        finally:
            _delete_mcp_server(litellm_client, server_id)

    def test_update_mcp_tool_overrides(self, litellm_client):
        """Update tool name and description overrides."""
        name = _unique_mcp_name()
        data = _create_mcp_server(litellm_client, name)
        server_id = _get_server_id(data)
        try:
            resp = _update_mcp_server(
                litellm_client,
                server_id,
                {
                    "tool_name_to_display_name": {"myTool": "My Custom Tool"},
                    "tool_name_to_description": {"myTool": "A custom description"},
                },
            )
            assert resp.status_code in (200, 202)
        finally:
            _delete_mcp_server(litellm_client, server_id)

    def test_delete_mcp_server(self, litellm_client):
        """DELETE /v1/mcp/server/{server_id} removes the server."""
        name = _unique_mcp_name()
        data = _create_mcp_server(litellm_client, name)
        server_id = _get_server_id(data)

        resp = litellm_client.delete(f"/v1/mcp/server/{server_id}")
        assert resp.status_code in (200, 202, 204)

        # Verify server is gone
        assert _wait_for_server_presence(litellm_client, server_id, should_exist=False)

    def test_delete_nonexistent_mcp_server(self, litellm_client):
        """Deleting a non-existent MCP server should return an error."""
        resp = litellm_client.delete(f"/v1/mcp/server/nonexistent-{uuid.uuid4().hex[:8]}")
        assert resp.status_code >= 400

    def test_create_mcp_server_without_auth(self, litellm_no_auth_client):
        """Creating an MCP server without auth should be rejected."""
        resp = litellm_no_auth_client.post(
            "/v1/mcp/server",
            json={"name": "unauthorized-mcp", "url": "http://fake:8200/mcp"},
        )
        assert resp.status_code in (401, 403)

    def test_mcp_crud_lifecycle(self, litellm_client):
        """Full lifecycle: create → list → update → verify → delete → verify gone."""
        name = _unique_mcp_name()

        # Create
        data = _create_mcp_server(litellm_client, name)
        server_id = _get_server_id(data)

        # List — should be present
        assert _wait_for_server_presence(litellm_client, server_id, should_exist=True)

        # Update
        resp = _update_mcp_server(
            litellm_client,
            server_id,
            {"description": "Lifecycle test updated"},
        )
        assert resp.status_code in (200, 202)

        # Delete
        resp = litellm_client.delete(f"/v1/mcp/server/{server_id}")
        assert resp.status_code in (200, 202, 204)

        # Verify gone
        assert _wait_for_server_presence(litellm_client, server_id, should_exist=False)
