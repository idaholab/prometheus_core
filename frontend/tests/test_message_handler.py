"""Tests for components/message_handler.py."""

from pathlib import Path
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

if "chainlit" not in sys.modules:
    chainlit = types.ModuleType("chainlit")
    chainlit.Message = object
    chainlit.Pdf = object
    chainlit.CustomElement = object
    chainlit.AskElementMessage = object
    chainlit.AskActionMessage = object
    chainlit.Action = object
    chainlit.Step = object
    chainlit.user_session = SimpleNamespace(get=lambda *args, **kwargs: None, set=lambda *args, **kwargs: None)
    sys.modules["chainlit"] = chainlit

from components import message_handler as handler
from utils.a2a_client import ConversationResponse


def _install_message_spy(monkeypatch):
    sent_messages = []

    class DummyMessage:
        def __init__(self, content="", elements=None):
            self.content = content
            self.elements = elements
            sent_messages.append(self)

        async def send(self):
            return self

        async def remove(self):
            return self

    monkeypatch.setattr(handler.cl, "Message", DummyMessage)
    return sent_messages


def test_guess_upload_mime_normalizes_step_extensions() -> None:
    assert handler._guess_upload_mime("bracket.stp") == "model/step"
    assert handler._guess_upload_mime("bracket.step") == "model/step"
    assert handler._guess_upload_mime("bracket.stp", "application/octet-stream") == "model/step"


class DummyUserSession:
    def __init__(self, initial: dict | None = None):
        self._store = dict(initial or {})

    def get(self, key, default=None):
        return self._store.get(key, default)

    def set(self, key, value):
        self._store[key] = value


class DummyStep:
    def __init__(self, name="", type="tool"):
        self.name = name
        self.type = type
        self.output = ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def update(self):
        return None


@pytest.mark.asyncio
async def test_message_handler_plugin_upload_sends_processed_elements_and_forwards_file(monkeypatch, tmp_path):
    sent_messages = _install_message_spy(monkeypatch)
    session = DummyUserSession(initial={"artifacts": []})
    monkeypatch.setattr(handler.cl, "user_session", session)
    monkeypatch.setattr(handler.cl, "Step", DummyStep)
    monkeypatch.setattr(handler.uuid, "uuid4", lambda: "conv-123")

    find_plugin = MagicMock(return_value=object())
    process_upload = AsyncMock(return_value=("Upload rendered", ["viewer"]))
    monkeypatch.setattr(handler._plugins, "find_plugin_for_upload", find_plugin)
    monkeypatch.setattr(handler._plugins, "process_upload", process_upload)

    response = ConversationResponse(
        conversation_id="conv-123",
        status="completed",
        message="ok",
    )
    client = SimpleNamespace(send=AsyncMock(return_value=response))
    handle_response = AsyncMock()
    monkeypatch.setattr(handler, "_get_a2a_client", lambda: client)
    monkeypatch.setattr(handler, "_handle_response", handle_response)

    upload_path = tmp_path / "model.ifc"
    upload_path.write_bytes(b"IFC data")
    message = SimpleNamespace(
        content="",
        elements=[SimpleNamespace(name="model.ifc", path=str(upload_path), mime="application/ifc")],
    )

    await handler.message_handler(message)

    find_plugin.assert_called_once_with(upload_path)
    process_upload.assert_awaited_once_with(upload_path)
    assert sent_messages[0].content == "Processing **model.ifc**…"
    assert sent_messages[1].content == "Upload rendered"
    assert sent_messages[1].elements == ["viewer"]
    client.send.assert_awaited_once()
    kwargs = client.send.await_args.kwargs
    assert kwargs["query"] == "Please process the uploaded file(s)."
    assert kwargs["conversation_id"] == "conv-123"
    assert kwargs["uploaded_files"] == [
        {
            "name": "model.ifc",
            "mime_type": "application/ifc",
            "size_bytes": 8,
            "content_b64": "SUZDIGRhdGE=",
        }
    ]
    assert callable(kwargs["on_status"])
    handle_response.assert_awaited_once_with(client, response, "Please process the uploaded file(s).", "conv-123")


@pytest.mark.asyncio
async def test_message_handler_plugin_upload_failure_is_reported(monkeypatch):
    sent_messages = _install_message_spy(monkeypatch)

    monkeypatch.setattr(handler._plugins, "find_plugin_for_upload", MagicMock(return_value=object()))
    monkeypatch.setattr(handler._plugins, "process_upload", AsyncMock(side_effect=RuntimeError("boom")))

    message = SimpleNamespace(
        content="",
        elements=[SimpleNamespace(name="model.ifc", path="/tmp/model.ifc")],
    )

    await handler.message_handler(message)

    assert sent_messages[0].content == "Processing **model.ifc**…"
    assert "Failed to process **model.ifc**: boom" in sent_messages[1].content


@pytest.mark.asyncio
async def test_message_handler_pdf_upload_falls_back_to_chainlit_pdf(monkeypatch):
    sent_messages = _install_message_spy(monkeypatch)
    monkeypatch.setattr(handler._plugins, "find_plugin_for_upload", MagicMock(return_value=None))

    created_pdfs = []

    class DummyPdf:
        def __init__(self, name, display, path):
            self.name = name
            self.display = display
            self.path = path
            created_pdfs.append(self)

    monkeypatch.setattr(handler.cl, "Pdf", DummyPdf)

    message = SimpleNamespace(
        content="",
        elements=[SimpleNamespace(name="report.pdf", path="/tmp/report.pdf")],
    )

    await handler.message_handler(message)

    assert len(created_pdfs) == 1
    assert created_pdfs[0].name == "report.pdf"
    assert created_pdfs[0].display == "inline"
    assert created_pdfs[0].path == "/tmp/report.pdf"
    assert sent_messages[0].content == "**PDF loaded:** report.pdf"
    assert sent_messages[0].elements == [created_pdfs[0]]


@pytest.mark.asyncio
async def test_message_handler_text_query_uses_a2a_client(monkeypatch):
    _install_message_spy(monkeypatch)
    session = DummyUserSession(initial={"artifacts": [{"name": "prior"}]})
    monkeypatch.setattr(handler.cl, "user_session", session)
    monkeypatch.setattr(handler.cl, "Step", DummyStep)
    monkeypatch.setattr(handler.uuid, "uuid4", lambda: "conv-123")

    response = ConversationResponse(
        conversation_id="conv-123",
        status="completed",
        message="ok",
    )
    client = SimpleNamespace(send=AsyncMock(return_value=response))
    handle_response = AsyncMock()
    monkeypatch.setattr(handler, "_get_a2a_client", lambda: client)
    monkeypatch.setattr(handler, "_handle_response", handle_response)

    await handler.message_handler(SimpleNamespace(content="hello", elements=[]))

    assert session.get("conversation_id") == "conv-123"
    client.send.assert_awaited_once_with(
        query="hello",
        conversation_id="conv-123",
        artifacts=[{"name": "prior"}],
        uploaded_files=None,
        on_status=client.send.await_args.kwargs["on_status"],
    )
    assert callable(client.send.await_args.kwargs["on_status"])
    handle_response.assert_awaited_once_with(client, response, "hello", "conv-123")
