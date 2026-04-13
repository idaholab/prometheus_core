"""Tests for final response rendering."""

from __future__ import annotations

import asyncio
import json
import sys
import types
from types import SimpleNamespace

FRONTEND_DIR = __import__("pathlib").Path(__file__).resolve().parents[1]
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))

if "chainlit" not in sys.modules:
    chainlit = types.ModuleType("chainlit")
    chainlit.Message = object
    chainlit.CustomElement = object
    chainlit.AskElementMessage = object
    chainlit.AskActionMessage = object
    chainlit.Action = object
    chainlit.Step = object
    chainlit.user_session = SimpleNamespace(get=lambda *args, **kwargs: None, set=lambda *args, **kwargs: None)
    sys.modules["chainlit"] = chainlit

from components import message_handler as handler
from utils.a2a_client import ConversationResponse


def test_handle_final_response_renders_artifacts_from_artifacts_list(monkeypatch):
    sent_messages = []

    class DummyMessage:
        def __init__(self, content="", elements=None):
            self.content = content
            self.elements = elements
            sent_messages.append(self)

        async def send(self):
            return self

    class DummyUserSession:
        def __init__(self):
            self._store = {}

        def get(self, key, default=None):
            return self._store.get(key, default)

        def set(self, key, value):
            self._store[key] = value

    session = DummyUserSession()

    async def _fake_render_artifacts(artifacts):
        return ["viewer"], "Artifact text"

    monkeypatch.setattr(handler.cl, "Message", DummyMessage)
    monkeypatch.setattr(handler.cl, "user_session", session)
    monkeypatch.setattr(handler, "render_artifacts", _fake_render_artifacts)

    response = ConversationResponse(
        conversation_id="conv-1",
        status="success",
        message=json.dumps(
            {
                "status": "success",
                "agent": "Alchemy Agent",
                "final_step": "completed",
            }
        ),
        artifacts=[{"name": "model.ifc", "mime_type": "application/ifc"}],
    )

    asyncio.run(handler._handle_final_response(response))

    assert session.get("artifacts") == response.artifacts
    assert len(sent_messages) == 1
    assert sent_messages[0].elements == ["viewer"]
    assert '"agent": "Alchemy Agent"' in sent_messages[0].content
    assert "Artifact text" in sent_messages[0].content
