"""Validate shared A2A protocol models are importable and correct."""

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def a2a_module(project_root):
    """Import a2a_protocol.py dynamically from the shared directory."""
    module_path = project_root / "shared" / "a2a_protocol.py"
    assert module_path.exists(), "shared/a2a_protocol.py does not exist"

    spec = importlib.util.spec_from_file_location("a2a_protocol", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["a2a_protocol"] = module
    spec.loader.exec_module(module)
    return module


def test_a2a_protocol_importable(a2a_module):
    assert a2a_module is not None


EXPECTED_MODELS = [
    "TaskStatus",
    "AgentCapability",
    "AgentCard",
    "TaskRequest",
    "TaskResponse",
    "TaskStatusUpdate",
    "Goal",
    "AgentRegistration",
    "A2AMessage",
]


@pytest.mark.parametrize("model_name", EXPECTED_MODELS)
def test_expected_model_exists(a2a_module, model_name):
    assert hasattr(a2a_module, model_name), f"Model '{model_name}' not found in a2a_protocol"


def test_task_status_enum_values(a2a_module):
    TaskStatus = a2a_module.TaskStatus
    expected = {"pending", "in_progress", "completed", "failed"}
    actual = {s.value for s in TaskStatus}
    assert actual == expected


def test_task_request_instantiation(a2a_module):
    TaskRequest = a2a_module.TaskRequest
    req = TaskRequest(
        task_id="test-1",
        capability="test_capability",
        parameters={"key": "value"},
    )
    assert req.task_id == "test-1"
    assert req.priority == 5  # default


def test_task_request_priority_bounds(a2a_module):
    TaskRequest = a2a_module.TaskRequest
    # Valid bounds
    TaskRequest(task_id="t", capability="c", parameters={}, priority=1)
    TaskRequest(task_id="t", capability="c", parameters={}, priority=10)
    # Invalid bounds
    with pytest.raises(Exception):
        TaskRequest(task_id="t", capability="c", parameters={}, priority=0)
    with pytest.raises(Exception):
        TaskRequest(task_id="t", capability="c", parameters={}, priority=11)


def test_task_response_instantiation(a2a_module):
    TaskResponse = a2a_module.TaskResponse
    TaskStatus = a2a_module.TaskStatus
    resp = TaskResponse(task_id="test-1", status=TaskStatus.COMPLETED)
    assert resp.status == TaskStatus.COMPLETED
    assert resp.result is None


def test_agent_card_instantiation(a2a_module):
    AgentCard = a2a_module.AgentCard
    AgentCapability = a2a_module.AgentCapability
    card = AgentCard(
        agent_id="agent-1",
        name="Test Agent",
        description="A test agent",
        version="1.0.0",
        capabilities=[
            AgentCapability(
                name="test",
                description="Test capability",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            )
        ],
        endpoint="http://localhost:8000",
    )
    assert card.status == "active"  # default
    assert len(card.capabilities) == 1


def test_a2a_message_has_timestamp_default(a2a_module):
    A2AMessage = a2a_module.A2AMessage
    msg = A2AMessage(
        message_id="msg-1",
        sender="agent-a",
        receiver="agent-b",
        message_type="request",
        payload={"data": "test"},
    )
    assert msg.timestamp is not None
