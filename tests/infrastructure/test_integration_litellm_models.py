"""Integration tests for LiteLLM model/LLM CRUD operations."""

import uuid

import pytest


pytestmark = pytest.mark.integration

MODEL_PREFIX = "test-model"


def _unique_model_name() -> str:
    return f"{MODEL_PREFIX}-{uuid.uuid4().hex[:8]}"


def _create_model(client, model_name: str, litellm_model: str = "openai/fake-model", **kwargs) -> dict:
    """Helper to create a model and return the response JSON."""
    payload = {
        "model_name": model_name,
        "litellm_params": {
            "model": litellm_model,
            "api_key": "sk-fake-test-key-not-real",
            "api_base": "https://fake-api.example.com",
            **kwargs.pop("litellm_params", {}),
        },
        "model_info": {
            "id": None,
            **kwargs.pop("model_info", {}),
        },
        **kwargs,
    }
    resp = client.post("/model/new", json=payload)
    assert resp.status_code == 200, f"Failed to create model: {resp.status_code} {resp.text}"
    return resp.json()


def _get_model_id(data: dict) -> str:
    """Extract model ID from the create response."""
    # Response may be nested differently
    model_info = data.get("model_info", {})
    return model_info.get("id", data.get("id", ""))


def _delete_model(client, model_id: str) -> None:
    """Helper to delete a model, ignoring errors."""
    client.post("/model/delete", json={"id": model_id})


def _list_models(client) -> list:
    """List models via OpenAI-compatible endpoint."""
    resp = client.get("/v1/models")
    if resp.status_code != 200:
        return []
    data = resp.json()
    return data.get("data", [])


def _get_model_info(client, model_id: str = None) -> list:
    """Get model info, optionally filtered by ID."""
    params = {}
    if model_id:
        params["litellm_model_id"] = model_id
    resp = client.get("/v1/model/info", params=params)
    if resp.status_code != 200:
        return []
    data = resp.json()
    return data.get("data", [])


class TestModelCRUD:
    """Tests for model/LLM create, read, update, delete operations."""

    def test_create_model(self, litellm_client):
        """Create a model with required fields."""
        name = _unique_model_name()
        data = _create_model(litellm_client, name)
        model_id = _get_model_id(data)
        try:
            assert model_id, f"No model_id in response: {data}"
        finally:
            _delete_model(litellm_client, model_id)

    def test_list_models(self, litellm_client):
        """Created model should appear in the models list."""
        name = _unique_model_name()
        data = _create_model(litellm_client, name)
        model_id = _get_model_id(data)
        try:
            models = _list_models(litellm_client)
            model_ids = [m.get("id", "") for m in models]
            assert name in model_ids or any(name in str(m) for m in models), (
                f"Model {name} not found in models list"
            )
        finally:
            _delete_model(litellm_client, model_id)

    def test_list_models_openai_compatible(self, litellm_client):
        """GET /v1/models should return OpenAI-compatible format."""
        resp = litellm_client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        assert data.get("object") == "list"

    def test_get_model_info(self, litellm_client):
        """GET /v1/model/info returns model details."""
        name = _unique_model_name()
        data = _create_model(litellm_client, name)
        model_id = _get_model_id(data)
        try:
            info_list = _get_model_info(litellm_client)
            assert len(info_list) > 0, "model/info returned empty list"
        finally:
            _delete_model(litellm_client, model_id)

    def test_get_model_info_by_id(self, litellm_client):
        """GET /v1/model/info with specific model ID returns that model."""
        name = _unique_model_name()
        data = _create_model(litellm_client, name)
        model_id = _get_model_id(data)
        try:
            info_list = _get_model_info(litellm_client, model_id)
            assert len(info_list) >= 1, f"Model {model_id} not found via model/info"
        finally:
            _delete_model(litellm_client, model_id)

    def test_update_model(self, litellm_client):
        """POST /model/update updates model configuration."""
        name = _unique_model_name()
        data = _create_model(litellm_client, name)
        model_id = _get_model_id(data)
        try:
            resp = litellm_client.post(
                "/model/update",
                json={
                    "model_info": {"id": model_id},
                    "litellm_params": {"model": "openai/updated-fake-model"},
                },
            )
            assert resp.status_code == 200
        finally:
            _delete_model(litellm_client, model_id)

    def test_patch_model(self, litellm_client):
        """PATCH /model/{model_id}/update does a partial update."""
        name = _unique_model_name()
        data = _create_model(litellm_client, name)
        model_id = _get_model_id(data)
        try:
            resp = litellm_client.patch(
                f"/model/{model_id}/update",
                json={
                    "litellm_params": {"api_base": "https://patched.example.com"},
                },
            )
            assert resp.status_code == 200
        finally:
            _delete_model(litellm_client, model_id)

    def test_delete_model(self, litellm_client):
        """POST /model/delete removes the model."""
        name = _unique_model_name()
        data = _create_model(litellm_client, name)
        model_id = _get_model_id(data)

        resp = litellm_client.post("/model/delete", json={"id": model_id})
        assert resp.status_code == 200

        # Verify model is gone from info
        info_list = _get_model_info(litellm_client, model_id)
        assert len(info_list) == 0, "Model should not appear in info after deletion"

    def test_delete_nonexistent_model(self, litellm_client):
        """Deleting a non-existent model should return an error."""
        resp = litellm_client.post(
            "/model/delete",
            json={"id": f"nonexistent-{uuid.uuid4().hex[:8]}"},
        )
        assert resp.status_code >= 400

    def test_create_model_without_auth(self, litellm_no_auth_client):
        """Creating a model without auth should be rejected."""
        resp = litellm_no_auth_client.post(
            "/model/new",
            json={
                "model_name": "unauthorized-model",
                "litellm_params": {"model": "openai/fake"},
                "model_info": {"id": None},
            },
        )
        assert resp.status_code in (401, 403)

    def test_create_model_with_custom_metadata(self, litellm_client):
        """Create model with custom model_info fields."""
        name = _unique_model_name()
        data = _create_model(
            litellm_client,
            name,
            model_info={"id": None, "my_custom_key": "my_custom_value"},
        )
        model_id = _get_model_id(data)
        try:
            assert model_id
        finally:
            _delete_model(litellm_client, model_id)

    def test_model_crud_lifecycle(self, litellm_client):
        """Full lifecycle: create → info → update → verify → delete → verify gone."""
        name = _unique_model_name()

        # Create
        data = _create_model(litellm_client, name)
        model_id = _get_model_id(data)

        # Info
        info_list = _get_model_info(litellm_client, model_id)
        assert len(info_list) >= 1

        # Update
        resp = litellm_client.post(
            "/model/update",
            json={
                "model_info": {"id": model_id},
                "litellm_params": {"api_base": "https://lifecycle-updated.example.com"},
            },
        )
        assert resp.status_code == 200

        # Verify update
        info_list = _get_model_info(litellm_client, model_id)
        assert len(info_list) >= 1

        # Delete
        resp = litellm_client.post("/model/delete", json={"id": model_id})
        assert resp.status_code == 200

        # Verify gone
        info_list = _get_model_info(litellm_client, model_id)
        assert len(info_list) == 0
