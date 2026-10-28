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

"""Stack test: a chat-driven SVG-to-PNG run leaves ADK provenance edges in DeepLynx.

The test sends one chat turn straight to the client-agent on its published port
(``CLIENT_AGENT_PORT``, default 8001, Bearer ``AGENT_SECRET``), as tests/system does,
so it needs no session cookie. The artifact-debug-agent runs ``create_svg_artifact``
and then ``convert_svg_to_png``. The test then reads the PNG item's relationship
graph from DeepLynx with the SDK storage client and checks the provenance edges.
It never starts or stops a container, so it does not use the ``docker_compose_up``
fixture. When the client-agent or the backend container does not answer, the test
skips with the reason; when the stack is up, a missing .env prerequisite fails it.
"""

import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit, urlunsplit

import httpx
import pytest

from prometheus_api.agent.identity import mint_user_token
from prometheus_api.storage_client import AsyncStorageClient, ConnectionConfig
from prometheus_api.storage_client.exceptions import StorageClientError
from system.a2a_client import A2AClient


pytestmark = pytest.mark.integration

PROMPT = "Make an SVG that says hello, then convert it to a PNG."
# A fixed test user; the client-agent rejects a message without a userToken while
# USER_IDENTITY_REQUIRED=true (the platform/docker-compose.yml default).
TEST_USER_ID = "adk-provenance-stack-test"

# The edge names that sdk/prometheus_api/adk/plugins/provenance.py writes (INPUT_TO,
# GENERATED, CHILD_OF). The pinned prometheus_api in platform/tests has no ``adk``
# module, so the strings are repeated here.
INPUT_TO = "input_to"
GENERATED = "generated"
CHILD_OF = "child_of"

# The same item-URI form that provenance.py parses.
_DEEPLYNX_ITEM_URI = re.compile(r"deeplynx://[^\s\"']*?/items/(\d+)")
_DEEPLYNX_REQUIRED = ("DEEPLYNX_ORG_ID", "DEEPLYNX_PROJECT_ID")
_DEEPLYNX_AUTH = ("DEEPLYNX_KEY", "DEEPLYNX_JWT_TOKEN")


def _env_value(project_root: Path, name: str) -> str:
    """Return a variable from the process environment, then platform/.env, else an empty string."""
    value = (os.getenv(name) or "").strip()
    if value:
        return value
    env_path = project_root / ".env"
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            key, sep, raw = line.partition("=")
            if sep and key.strip() == name:
                return raw.strip().strip('"').strip("'")
    return ""


class _Secret:
    """A secret string whose repr and str are redacted, so a traceback or fixture repr never shows it.

    Only ``reveal()`` returns the value; call it where the value goes into a header or the
    environment, and never bind its result to a local.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __repr__(self) -> str:
        return "_Secret('***')"

    def __str__(self) -> str:
        return "***"


def _with_auth(headers: dict[str, str], agent_secret: _Secret) -> dict[str, str]:
    return {**headers, "Authorization": f"Bearer {agent_secret.reveal()}"}


def _with_identity(message: dict[str, Any], user_token: _Secret) -> dict[str, Any]:
    inner = {**message["params"]["message"], "metadata": {"userToken": user_token.reveal()}}
    return {**message, "params": {**message["params"], "message": inner}}


class _IdentityA2AClient(A2AClient):
    """An A2AClient that puts the identity JWT in message.metadata.userToken of every message.

    The backend does the same in backend/app/a2a_client.py; the system-test client sends no
    metadata, so the token is added to the envelope before it is streamed. Both secrets stay
    wrapped in ``_Secret``: the parent builds its header from ``str(secret)``, which is
    redacted, and ``_stream_request`` replaces that header with the real one.
    """

    def __init__(self, agent_url: str, agent_secret: _Secret, user_token: _Secret) -> None:
        super().__init__(agent_url, agent_secret)  # type: ignore[arg-type]
        self._agent_secret = agent_secret
        self._user_token = user_token

    async def _stream_request(self, message: dict[str, Any], headers: dict[str, str], **kwargs: Any) -> dict[str, Any]:
        return await super()._stream_request(
            _with_identity(message, self._user_token), _with_auth(headers, self._agent_secret), **kwargs
        )


# Runs inside the backend container, which holds admin-db's active signing key. It calls
# the backend's own minter (app/identity.py mint_for_user, the call routers/chat.py makes
# for every turn), so the kid matches the backend's JWKS. It prints only the token.
_BACKEND_MINT_SCRIPT = """
import asyncio, sys
from app.identity import mint_for_user
token = asyncio.run(mint_for_user(sys.argv[1]))
if not token:
    sys.exit("mint_for_user returned no token: the backend has no active signing key")
sys.stdout.write(token)
"""
_SECRET_TEXT = re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+|-----BEGIN[^-]*-----.*?-----END[^-]*-----", re.DOTALL)


def _mint_in_backend() -> _Secret:
    """Mint the identity JWT with the backend's own minter, inside the running backend container.

    Skips with a reason when Docker or the backend container does not answer.
    """
    try:
        status = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Status}}", "backend"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"Docker is not available: {type(exc).__name__}")
    if status != "running":
        pytest.skip("The backend container is not running")
    try:
        result = subprocess.run(
            ["docker", "exec", "-i", "-w", "/app", "backend", "python", "-", TEST_USER_ID],
            input=_BACKEND_MINT_SCRIPT,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"The backend container does not answer: {type(exc).__name__}")
    if result.returncode != 0:
        stderr = _SECRET_TEXT.sub("[REDACTED]", result.stderr)[-2000:]
        pytest.fail(f"The backend could not mint an identity token (exit {result.returncode}): {stderr}")
    token = _Secret(result.stdout.strip())
    result.stdout = ""
    if token.reveal().count(".") != 2:
        pytest.fail("The backend minter printed no JWT on stdout")
    return token


@pytest.fixture
def user_token(project_root: Path, monkeypatch: pytest.MonkeyPatch) -> _Secret:
    """Return the identity JWT that the backend mints for a turn.

    First choice: USER_IDENTITY_PRIVATE_KEY from the environment or platform/.env. The
    backend's env-key path calls prometheus_api.agent.identity.mint_user_token (RS256;
    sub, iat, exp, iss, aud; kid from the key's JWKS thumbprint), so the test calls it too.
    Without that key, the backend signs with admin-db's active key, so the test mints the
    token inside the backend container with the backend's own minter.
    """
    private_key = _Secret(_env_value(project_root, "USER_IDENTITY_PRIVATE_KEY").replace("\\n", "\n"))
    if not private_key:
        return _mint_in_backend()
    monkeypatch.setenv("USER_IDENTITY_PRIVATE_KEY", private_key.reveal())
    for name, default in (("USER_IDENTITY_ISS", "prometheus-platform"), ("USER_IDENTITY_AUD", "prometheus-agents")):
        monkeypatch.setenv(name, _env_value(project_root, name) or default)
    ttl = _env_value(project_root, "USER_IDENTITY_TTL")
    if ttl:
        monkeypatch.setenv("USER_IDENTITY_TTL", ttl)
    try:
        return _Secret(mint_user_token(TEST_USER_ID))
    except Exception as exc:
        pytest.fail(f"Could not mint the identity token from USER_IDENTITY_PRIVATE_KEY: {type(exc).__name__}")


@pytest.fixture
def stack(project_root: Path) -> dict[str, Any]:
    """Check every prerequisite of the stack phase and return the client-agent URL and secret."""
    # The client-agent port is published only with PROMETHEUS_SYSTEM_TESTING=true
    # (docker-compose.system-test.yml), the same port tests/system/prometheus.py uses.
    port = _env_value(project_root, "CLIENT_AGENT_PORT") or "8001"
    base_url = f"http://localhost:{port}"
    try:
        health = httpx.get(f"{base_url}/healthz", timeout=10)
    except httpx.HTTPError as exc:
        pytest.skip(
            f"The client-agent does not answer on {base_url} ({type(exc).__name__}); "
            "start the stack with PROMETHEUS_SYSTEM_TESTING=true to publish CLIENT_AGENT_PORT"
        )
    if health.status_code != 200:
        pytest.skip(f"The client-agent /healthz on {base_url} returned {health.status_code}")

    agent_secret = _Secret(_env_value(project_root, "AGENT_SECRET"))
    if not agent_secret:
        pytest.fail("AGENT_SECRET is not set in the environment or platform/.env")
    if _env_value(project_root, "DEBUG_AGENTS").lower() != "true":
        pytest.fail("DEBUG_AGENTS=true is required: the artifact-debug-agent owns the SVG and PNG skills")
    missing = [name for name in _DEEPLYNX_REQUIRED if not _env_value(project_root, name)]
    if not any(_env_value(project_root, name) for name in _DEEPLYNX_AUTH):
        missing.append("DEEPLYNX_KEY or DEEPLYNX_JWT_TOKEN")
    if missing:
        pytest.fail(f"platform/.env does not name {', '.join(missing)}")
    return {"agent_url": base_url, "agent_secret": agent_secret, "project_root": project_root}


def _item_id(artifact: dict[str, Any]) -> int | None:
    match = _DEEPLYNX_ITEM_URI.search(str(artifact.get("uri") or ""))
    return int(match.group(1)) if match else None


def _artifact_item(artifacts: list[dict[str, Any]], mime_type: str, suffix: str) -> int:
    for artifact in artifacts:
        mime = str(artifact.get("mime_type") or artifact.get("mimeType") or "").lower()
        name = str(artifact.get("name") or artifact.get("uri") or "").lower()
        if mime == mime_type or name.endswith(suffix):
            item_id = _item_id(artifact)
            if item_id is not None:
                return item_id
    pytest.fail(f"No {mime_type} artifact with a deeplynx:// item URI in the response: {json.dumps(artifacts)[:2000]}")


def _deeplynx_host_url(project_root: Path) -> str:
    """Return the DeepLynx base URL as the host sees it.

    platform/.env gives the containers' URL (often http://host.docker.internal:5000), which the
    host may not resolve. DEEPLYNX_HOST_BASE_URL wins; otherwise host.docker.internal becomes localhost.
    """
    override = _env_value(project_root, "DEEPLYNX_HOST_BASE_URL")
    if override:
        return override.rstrip("/")
    url = _env_value(project_root, "DEEPLYNX_BASE_URL") or "https://deeplynx.inl.gov/api/v1"
    parts = urlsplit(url)
    if parts.hostname == "host.docker.internal":
        netloc = "localhost" + (f":{parts.port}" if parts.port else "")
        parts = parts._replace(netloc=netloc)
    return urlunsplit(parts).rstrip("/")


async def _item_graph(project_root: Path, item_id: int) -> Any:
    """Read the item's relationship graph at the host-side DeepLynx URL.

    The ConnectionConfig holds the DeepLynx key and secret and its repr shows them, so it is
    never bound to a local of any frame.
    """
    try:
        async with AsyncStorageClient(
            ConnectionConfig.from_env(env_file=project_root / ".env").model_copy(
                update={"base_url": _deeplynx_host_url(project_root)}
            )
        ) as storage:
            return await storage.relationships.get_item_graph(item_id, depth=3)
    except StorageClientError as exc:
        pytest.fail(f"DeepLynx rejected the graph query for item {item_id}: {_SECRET_TEXT.sub('[REDACTED]', str(exc))}")


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if data.get(key) not in (None, ""):
            return data[key]
    return None


def _edges(graph: Any) -> Iterator[tuple[int, int, str]]:
    """Yield (origin, destination, name) for every relationship-shaped dict in the graph JSON."""
    if isinstance(graph, dict):
        origin = _first(graph, "originId", "origin_id", "from_item_id", "source", "from")
        destination = _first(graph, "destinationId", "destination_id", "to_item_id", "target", "to")
        name = _first(graph, "relationshipName", "relationship_name", "relationship_type", "name", "type")
        if isinstance(origin, dict):
            origin = _first(origin, "id")
        if isinstance(destination, dict):
            destination = _first(destination, "id")
        if isinstance(name, dict):
            name = _first(name, "name")
        if origin is not None and destination is not None and isinstance(name, str):
            try:
                yield int(origin), int(destination), name
            except (TypeError, ValueError):
                pass
        for value in graph.values():
            yield from _edges(value)
    elif isinstance(graph, list):
        for value in graph:
            yield from _edges(value)


async def test_adk_provenance_on_deeplynx(stack: dict[str, Any], user_token: _Secret) -> None:
    """The SVG and PNG runs each leave an execution record linked by child_of, input_to and generated."""
    client = _IdentityA2AClient(stack["agent_url"], stack["agent_secret"], user_token)
    session = client.start_chat(f"adk-provenance-{uuid.uuid4()}")
    try:
        response = await session.submit(PROMPT)
        if response.status == "plan_ready":
            response = await session.submit(PROMPT, plan_approved=True)
    except httpx.HTTPStatusError as exc:
        pytest.fail(f"The chat turn to the client-agent failed with HTTP {exc.response.status_code}")
    assert response.status not in ("needs_info", "plan_ready", "error"), (
        f"The chat turn did not finish: status={response.status} message={response.message}"
    )
    artifacts = list(response.new_artifacts or response.artifacts or [])
    svg_item = _artifact_item(artifacts, "image/svg+xml", ".svg")
    png_item = _artifact_item(artifacts, "image/png", ".png")

    graph = await _item_graph(stack["project_root"], png_item)

    edges = set(_edges(graph))
    raw = json.dumps(graph, default=str)[:4000]

    generated = {origin: destination for origin, destination, name in edges if name == GENERATED}
    png_records = [record for record, item in generated.items() if item == png_item]
    svg_records = [record for record, item in generated.items() if item == svg_item]
    assert len(png_records) == 1, f"Expected one generated edge to PNG item {png_item}; graph: {raw}"
    assert len(svg_records) == 1, f"Expected one generated edge to SVG item {svg_item}; graph: {raw}"
    png_record, svg_record = png_records[0], svg_records[0]
    assert png_record != svg_record, f"The SVG and PNG runs share one execution record; graph: {raw}"

    assert (svg_item, png_record, INPUT_TO) in edges, (
        f"No input_to edge from SVG item {svg_item} to the PNG run's record {png_record}; graph: {raw}"
    )

    parents = {origin: destination for origin, destination, name in edges if name == CHILD_OF}
    assert svg_record in parents, f"The SVG run's record {svg_record} has no child_of edge; graph: {raw}"
    assert png_record in parents, f"The PNG run's record {png_record} has no child_of edge; graph: {raw}"
    assert parents[svg_record] == parents[png_record], (
        f"The child_of edges point to different parents {parents[svg_record]} and {parents[png_record]}; graph: {raw}"
    )
    assert parents[svg_record] not in (svg_record, png_record), f"A record is its own parent; graph: {raw}"
