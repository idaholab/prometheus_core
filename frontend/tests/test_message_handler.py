"""Tests for components/message_handler.py."""

import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

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


def test_upload_limit_uses_configured_setting() -> None:
    assert handler.MAX_UPLOAD_BYTES == handler.settings.max_upload_bytes
    assert handler.MAX_UPLOAD_MB == max(1, math.ceil(handler.MAX_UPLOAD_BYTES / (1024 * 1024)))


@pytest.mark.asyncio
async def test_capture_uploaded_file_rejects_files_over_limit(monkeypatch, tmp_path):
    sent_messages = _install_message_spy(monkeypatch)
    # MAX_UPLOAD_MB is patched independently to verify the error message reads from it,
    # not from MAX_UPLOAD_BYTES, so the two can stay in sync without arithmetic coupling.
    monkeypatch.setattr(handler, "MAX_UPLOAD_BYTES", 4)
    monkeypatch.setattr(handler, "MAX_UPLOAD_MB", 100)

    upload_path = tmp_path / "large.step"
    upload_path.write_bytes(b"12345")
    element = SimpleNamespace(name="large.step", path=str(upload_path), mime="model/step")

    client = SimpleNamespace(stage_upload=AsyncMock())

    result = await handler._capture_uploaded_file(element, upload_path, client, "conv-1")

    assert result is None
    assert sent_messages[0].content == "**large.step** exceeds the 100 MB upload limit and will not be stored."


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

    upload_match = handler._plugins.UploadMatch(
        mime_type="application/ifc",
        confidence=90,
        plugin=object(),
    )
    inspect_upload = AsyncMock(return_value=upload_match)
    process_upload = AsyncMock(
        return_value=handler._plugins.UploadRenderResult("Upload rendered", ["viewer"])
    )
    monkeypatch.setattr(handler._plugins, "inspect_upload", inspect_upload)
    monkeypatch.setattr(handler._plugins, "process_upload", process_upload)

    created_files = []

    class DummyFile:
        def __init__(self, *, name: str, path: str, display: str, mime: str = ""):
            self.name = name
            self.path = path
            self.display = display
            self.mime = mime
            created_files.append(self)

    monkeypatch.setattr(handler.cl, "File", DummyFile, raising=False)

    response = ConversationResponse(
        conversation_id="conv-123",
        status="completed",
        message="ok",
    )
    client = SimpleNamespace(
        send=AsyncMock(return_value=response),
        stage_upload=AsyncMock(
            return_value={
                "upload_id": "upload-1",
                "name": "model.ifc",
                "mime_type": "application/ifc",
                "size_bytes": 8,
            }
        ),
    )
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

    inspect_upload.assert_awaited_once()
    inspected_context = inspect_upload.await_args.args[0]
    assert inspected_context.file_path == upload_path
    assert inspected_context.display_name == "model.ifc"
    assert inspected_context.mime_type == "application/ifc"
    assert inspected_context.size_bytes == 8
    process_upload.assert_awaited_once()
    processed_context = process_upload.await_args.args[0]
    assert processed_context.file_path == upload_path
    assert processed_context.display_name == "model.ifc"
    assert processed_context.mime_type == "application/ifc"
    assert process_upload.await_args.kwargs == {"match": upload_match}
    assert sent_messages[0].content == "Processing **model.ifc**…"
    assert sent_messages[1].content == "Upload rendered"
    assert sent_messages[1].elements == ["viewer", created_files[0]]
    assert created_files[0].name == "model.ifc"
    assert created_files[0].path == str(upload_path)
    assert created_files[0].mime == "application/ifc"
    client.stage_upload.assert_awaited_once_with(
        upload_path,
        name="model.ifc",
        mime_type="application/ifc",
        conversation_id="conv-123",
    )
    client.send.assert_awaited_once()
    kwargs = client.send.await_args.kwargs
    assert kwargs["query"] == "Please process the uploaded file(s)."
    assert kwargs["conversation_id"] == "conv-123"
    assert kwargs["uploaded_files"] == [
        {
            "name": "model.ifc",
            "mime_type": "application/ifc",
            "size_bytes": 8,
            "upload_id": "upload-1",
        }
    ]
    assert callable(kwargs["on_status"])
    handle_response.assert_awaited_once_with(client, response, "Please process the uploaded file(s).", "conv-123")


@pytest.mark.asyncio
async def test_message_handler_plugin_upload_failure_is_reported(monkeypatch, tmp_path):
    sent_messages = _install_message_spy(monkeypatch)
    monkeypatch.setattr(handler.cl, "user_session", DummyUserSession())

    monkeypatch.setattr(
        handler._plugins,
        "inspect_upload",
        AsyncMock(
            return_value=handler._plugins.UploadMatch(
                mime_type="application/ifc",
                confidence=90,
                plugin=object(),
            )
        ),
    )
    monkeypatch.setattr(handler._plugins, "process_upload", AsyncMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(handler, "_capture_uploaded_file", AsyncMock(return_value=None))

    upload_path = tmp_path / "model.ifc"
    upload_path.write_bytes(b"IFC data")
    message = SimpleNamespace(
        content="",
        elements=[SimpleNamespace(name="model.ifc", path=str(upload_path))],
    )

    await handler.message_handler(message)

    assert sent_messages[0].content == "Processing **model.ifc**…"
    assert "Failed to process **model.ifc**: boom" in sent_messages[1].content


@pytest.mark.asyncio
async def test_message_handler_plugin_upload_uses_inspected_mime_for_suffixless_path(monkeypatch, tmp_path):
    _install_message_spy(monkeypatch)
    session = DummyUserSession(initial={"artifacts": []})
    monkeypatch.setattr(handler.cl, "user_session", session)
    monkeypatch.setattr(handler.cl, "Step", DummyStep)
    monkeypatch.setattr(handler.uuid, "uuid4", lambda: "conv-123")

    plugin = object()
    upload_match = handler._plugins.UploadMatch(
        mime_type="application/x-exodus",
        confidence=80,
        plugin=plugin,
    )
    inspect_upload = AsyncMock(return_value=upload_match)
    process_upload = AsyncMock(
        return_value=handler._plugins.UploadRenderResult("Upload rendered", ["viewer"])
    )
    monkeypatch.setattr(handler._plugins, "inspect_upload", inspect_upload)
    monkeypatch.setattr(handler._plugins, "process_upload", process_upload)

    class DummyFile:
        def __init__(self, *, name: str, path: str, display: str, mime: str = ""):
            self.name = name
            self.path = path
            self.display = display
            self.mime = mime

    monkeypatch.setattr(handler.cl, "File", DummyFile, raising=False)

    response = ConversationResponse(conversation_id="conv-123", status="completed", message="ok")
    client = SimpleNamespace(
        send=AsyncMock(return_value=response),
        stage_upload=AsyncMock(
            return_value={
                "upload_id": "upload-1",
                "name": "cahnhilliard_out.e",
                "mime_type": "application/x-exodus",
                "size_bytes": 11,
            }
        ),
    )
    monkeypatch.setattr(handler, "_get_a2a_client", lambda: client)
    monkeypatch.setattr(handler, "_handle_response", AsyncMock())

    upload_path = tmp_path / "chainlit-upload"
    upload_path.write_bytes(b"exodus data")

    await handler.message_handler(
        SimpleNamespace(
            content="",
            elements=[SimpleNamespace(name="cahnhilliard_out.e", path=str(upload_path), mime="application/octet-stream")],
        )
    )

    inspect_upload.assert_awaited_once()
    inspected_context = inspect_upload.await_args.args[0]
    assert inspected_context.file_path == upload_path
    assert inspected_context.display_name == "cahnhilliard_out.e"
    assert inspected_context.mime_type == "application/octet-stream"
    process_upload.assert_awaited_once()
    processed_context = process_upload.await_args.args[0]
    assert processed_context.file_path == upload_path
    assert processed_context.display_name == "cahnhilliard_out.e"
    assert processed_context.mime_type == "application/x-exodus"
    assert process_upload.await_args.kwargs == {"match": upload_match}


@pytest.mark.asyncio
async def test_message_handler_pdf_upload_falls_back_to_chainlit_pdf(monkeypatch, tmp_path):
    sent_messages = _install_message_spy(monkeypatch)
    monkeypatch.setattr(handler.cl, "user_session", DummyUserSession())
    monkeypatch.setattr(handler._plugins, "inspect_upload", AsyncMock(return_value=None))
    monkeypatch.setattr(handler, "_capture_uploaded_file", AsyncMock(return_value=None))

    created_pdfs = []
    created_files = []

    class DummyPdf:
        def __init__(self, name, display, path):
            self.name = name
            self.display = display
            self.path = path
            created_pdfs.append(self)

    class DummyFile:
        def __init__(self, *, name: str, path: str, display: str, mime: str = ""):
            self.name = name
            self.path = path
            self.display = display
            self.mime = mime
            created_files.append(self)

    monkeypatch.setattr(handler.cl, "Pdf", DummyPdf)
    monkeypatch.setattr(handler.cl, "File", DummyFile, raising=False)

    upload_path = tmp_path / "report.pdf"
    upload_path.write_bytes(b"%PDF-1.4\n")
    message = SimpleNamespace(
        content="",
        elements=[SimpleNamespace(name="report.pdf", path=str(upload_path))],
    )

    await handler.message_handler(message)

    assert len(created_pdfs) == 1
    assert created_pdfs[0].name == "report.pdf"
    assert created_pdfs[0].display == "inline"
    assert created_pdfs[0].path == str(upload_path)
    assert created_files[0].name == "report.pdf"
    assert created_files[0].path == str(upload_path)
    assert created_files[0].mime == "application/pdf"
    assert sent_messages[0].content == "**PDF loaded:** report.pdf"
    assert sent_messages[0].elements == [created_pdfs[0], created_files[0]]


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
        user_token=None,
    )
    assert callable(client.send.await_args.kwargs["on_status"])
    handle_response.assert_awaited_once_with(client, response, "hello", "conv-123")
