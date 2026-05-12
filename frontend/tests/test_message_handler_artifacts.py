"""Tests for artifact fallback rendering."""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace

FRONTEND_DIR = Path(__file__).resolve().parents[1]
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))

if "chainlit" not in sys.modules:
    chainlit = types.ModuleType("chainlit")
    chainlit.File = object
    chainlit.Pdf = object
    chainlit.CustomElement = object
    chainlit.Message = object
    chainlit.AskElementMessage = object
    chainlit.AskActionMessage = object
    chainlit.Action = object
    chainlit.Step = object
    chainlit.user_session = SimpleNamespace(get=lambda *args, **kwargs: None, set=lambda *args, **kwargs: None)
    sys.modules["chainlit"] = chainlit

from components import message_handler as handler


def test_render_artifacts_downloads_remote_json_file(monkeypatch, tmp_path: Path) -> None:
    created = []

    class DummyFile:
        def __init__(self, *, name: str, path: str, display: str, mime: str = ""):
            self.name = name
            self.path = path
            self.display = display
            self.mime = mime
            created.append(self)

    class _FakeResponse:
        def __init__(self, content: bytes):
            self.content = content

        def raise_for_status(self) -> None:
            return None

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, uri: str):
            assert uri == "http://example.test/output.json"
            return _FakeResponse(b'{\"status\":\"ok\"}\n')

    monkeypatch.setattr(handler.cl, "File", DummyFile, raising=False)
    monkeypatch.setattr("components.message_handler.httpx.AsyncClient", _FakeAsyncClient)

    elements, text = asyncio.run(
        handler.render_artifacts(
            [
                {
                    "name": "output.json",
                    "mime_type": "application/json",
                    "uri": "http://example.test/output.json",
                    "description": "Generated ANL JSON intermediate output.",
                }
            ],
            tmp_path,
        )
    )

    assert len(elements) == 1
    assert len(created) == 1
    assert created[0].name == "output.json"
    assert Path(created[0].path).exists()
    assert "Generated ANL JSON intermediate output." in text


def test_render_artifacts_treats_step_as_downloadable_file(monkeypatch, tmp_path: Path) -> None:
    created = []

    class DummyFile:
        def __init__(self, *, name: str, path: str, display: str, mime: str = ""):
            self.name = name
            self.path = path
            self.display = display
            self.mime = mime
            created.append(self)

    monkeypatch.setattr(handler.cl, "File", DummyFile, raising=False)

    async def _no_plugin(artifact):
        return None

    monkeypatch.setattr(handler._plugins, "render_artifact", _no_plugin)

    step_file = tmp_path / "bracket.stp"
    step_file.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n")

    elements, text = asyncio.run(
        handler.render_artifacts(
            [
                {
                    "name": "bracket.stp",
                    "mime_type": "model/step",
                    "uri": f"file://{step_file}",
                    "description": "STEP CAD model.",
                }
            ],
            tmp_path,
        )
    )

    assert len(elements) == 1
    assert created[0].name == "bracket.stp"
    assert created[0].mime == "model/step"
    assert "no viewer available" not in text
