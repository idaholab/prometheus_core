"""Integration tests for LiteLLM A2A agent CRUD operations."""

import uuid

import pytest


pytestmark = pytest.mark.integration

AGENT_PREFIX = "test-agent"


def _unique_agent_name() -> str:
    return f"{AGENT_PREFIX}-{uuid.uuid4().hex[:8]}"


def _default_agent_card_params(name: str, url: str) -> dict:
    """Build a minimal A2A agent card payload accepted by newer LiteLLM versions."""
    return {
        "name": name,
        "description": "Integration test agent",
        "version": "1.0.0",
        "url": url,
        "capabilities": {},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [],
    }


def _create_agent(client, name: str, url: str = "http://fake-agent:8000", **kwargs) -> dict:
    """Helper to create an agent and return the response JSON."""
    agent_card_params = kwargs.pop("agent_card_params", _default_agent_card_params(name, url))
    payload = {"agent_name": name, "url": url, "agent_card_params": agent_card_params, **kwargs}
    resp = client.post("/v1/agents", json=payload)
    assert resp.status_code in (200, 201), f"Failed to create agent: {resp.status_code} {resp.text}"
    return resp.json()


def _delete_agent(client, agent_id: str) -> None:
    """Helper to delete an agent, ignoring errors."""
    client.delete(f"/v1/agents/{agent_id}")


def _find_agent_in_list(client, agent_id: str) -> dict | None:
    """Search for an agent by ID in the agents list."""
    resp = client.get("/v1/agents")
    if resp.status_code != 200:
        return None
    agents = resp.json()
    if isinstance(agents, list):
        return next((a for a in agents if a.get("agent_id") == agent_id or a.get("id") == agent_id), None)
    # Some versions return {"data": [...]}
    data = agents.get("data", agents.get("agents", []))
    return next((a for a in data if a.get("agent_id") == agent_id or a.get("id") == agent_id), None)


class TestAgentCRUD:
    """Tests for A2A agent create, read, update, delete operations."""

    def test_create_agent_minimal(self, litellm_client):
        """Create agent with minimum required fields."""
        name = _unique_agent_name()
        data = _create_agent(litellm_client, name)
        try:
            assert "agent_id" in data
            returned_name = data.get("agent_name") or data.get("name") or (data.get("agent_card", {}) or {}).get("name")
            if returned_name is not None:
                assert returned_name == name
        finally:
            _delete_agent(litellm_client, data.get("agent_id", ""))

    def test_create_agent_with_headers(self, litellm_client):
        """Create agent with static_headers and extra_headers."""
        name = _unique_agent_name()
        data = _create_agent(
            litellm_client,
            name,
            static_headers={"X-Internal-Token": "secret123"},
            extra_headers=["x-user-id"],
        )
        try:
            assert "agent_id" in data
        finally:
            _delete_agent(litellm_client, data.get("agent_id", ""))

    def test_list_agents(self, litellm_client):
        """Created agent should appear in the agents list."""
        name = _unique_agent_name()
        data = _create_agent(litellm_client, name)
        agent_id = data["agent_id"]
        try:
            found = _find_agent_in_list(litellm_client, agent_id)
            assert found is not None, f"Agent {agent_id} not found in list"
        finally:
            _delete_agent(litellm_client, agent_id)

    def test_get_agent_by_id(self, litellm_client):
        """GET /v1/agents/{agent_id} returns correct agent details."""
        name = _unique_agent_name()
        data = _create_agent(litellm_client, name)
        agent_id = data["agent_id"]
        try:
            resp = litellm_client.get(f"/v1/agents/{agent_id}")
            assert resp.status_code == 200
            agent = resp.json()
            assert agent.get("agent_id") == agent_id or agent.get("data", {}).get("agent_id") == agent_id
        finally:
            _delete_agent(litellm_client, agent_id)

    def test_update_agent(self, litellm_client):
        """PATCH /v1/agents/{agent_id} updates agent configuration."""
        name = _unique_agent_name()
        data = _create_agent(litellm_client, name)
        agent_id = data["agent_id"]
        try:
            resp = litellm_client.patch(
                f"/v1/agents/{agent_id}",
                json={"static_headers": {"X-Updated": "new-value"}},
            )
            assert resp.status_code == 200
        finally:
            _delete_agent(litellm_client, agent_id)

    def test_delete_agent(self, litellm_client):
        """DELETE /v1/agents/{agent_id} removes the agent."""
        name = _unique_agent_name()
        data = _create_agent(litellm_client, name)
        agent_id = data["agent_id"]

        resp = litellm_client.delete(f"/v1/agents/{agent_id}")
        assert resp.status_code == 200

        # Verify agent is gone
        found = _find_agent_in_list(litellm_client, agent_id)
        assert found is None, "Agent should not appear in list after deletion"

    def test_delete_nonexistent_agent(self, litellm_client):
        """Deleting a non-existent agent should return an error status."""
        resp = litellm_client.delete(f"/v1/agents/nonexistent-{uuid.uuid4().hex[:8]}")
        assert resp.status_code >= 400

    def test_create_agent_without_auth(self, litellm_no_auth_client):
        """Creating an agent without auth should be rejected."""
        resp = litellm_no_auth_client.post(
            "/v1/agents",
            json={"agent_name": "unauthorized-agent", "url": "http://fake:8000"},
        )
        assert resp.status_code in (401, 403)

    def test_create_duplicate_agent_name(self, litellm_client):
        """Document behavior when creating agents with the same name."""
        name = _unique_agent_name()
        data1 = _create_agent(litellm_client, name)
        agent_ids = [data1["agent_id"]]
        try:
            # Second creation with same name — may succeed or fail
            resp = litellm_client.post(
                "/v1/agents",
                json={"agent_name": name, "url": "http://fake-agent-2:8000"},
            )
            if resp.status_code == 200:
                data2 = resp.json()
                agent_ids.append(data2.get("agent_id", ""))
                # If it succeeds, IDs should be different
                assert data2["agent_id"] != data1["agent_id"]
            else:
                # If it fails, that's also valid (duplicate rejection)
                assert resp.status_code >= 400
        finally:
            for aid in agent_ids:
                _delete_agent(litellm_client, aid)

    def test_agent_crud_lifecycle(self, litellm_client):
        """Full lifecycle: create → read → update → read → delete → verify gone."""
        name = _unique_agent_name()

        # Create
        data = _create_agent(litellm_client, name, url="http://lifecycle-agent:8000")
        agent_id = data["agent_id"]

        # Read
        found = _find_agent_in_list(litellm_client, agent_id)
        assert found is not None

        # Update
        resp = litellm_client.patch(
            f"/v1/agents/{agent_id}",
            json={"static_headers": {"X-Lifecycle": "updated"}},
        )
        assert resp.status_code == 200

        # Read again
        resp = litellm_client.get(f"/v1/agents/{agent_id}")
        assert resp.status_code == 200

        # Delete
        resp = litellm_client.delete(f"/v1/agents/{agent_id}")
        assert resp.status_code == 200

        # Verify gone
        found = _find_agent_in_list(litellm_client, agent_id)
        assert found is None
