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

"""Stack test: an ADK run on the database session service resumes after a kill -9 (REQ-016-12).

These five tests are the resume gate of the ADK runtime prototype. Each one runs a probe
script (``_PROBE`` below) inside the already-running ``client-agent`` container with
``docker exec -i client-agent python -u -``. The probe builds a tiny ``PrometheusAgent`` and
an ADK ``LlmAgent`` whose model is a deterministic stub (scripted function calls, no LLM),
and runs it through the SDK's real ``prometheus_api.adk.build_runner(..., test=False)``. So
the session service is ADK's ``DatabaseSessionService`` on ``ADK_SESSION_DB_URL`` (the
``adk`` schema of admin-db) and the artifact service is ``DeepLynxArtifactService`` with the
``DEEPLYNX_*`` service account of the container.

Each tool of the stub plan appends one line per run to
``/tmp/adk-resume-<scenario>-<session>.jsonl`` in the container, so the test can count the
steps that ran again. A test starts the probe, waits for a marker line, kills the probe
process inside the container with ``kill -9``, then runs it again with the same session ID
and the ``invocation_id`` of the first run. A last ``report`` run reads the session back from
the database and queries DeepLynx with the SDK ``AsyncStorageClient`` and prints JSON.

The test never starts, stops or rebuilds a container, so it does not use the
``docker_compose_up`` fixture. When Docker, ``client-agent`` or ``admin-db`` does not answer,
the test skips with the reason (the stack phase reports a skip as a failure). A running stack
that lacks a required .env name or container variable fails the test. Every session, DeepLynx item and file the probe makes is removed by a
``cleanup`` run in a ``finally``.
"""

import json
import os
import queue
import re
import subprocess
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest


pytestmark = pytest.mark.integration

CONTAINER = "client-agent"
DB_CONTAINER = "admin-db"
ENV_NAMES = (
    "ADK_DB_PASSWORD",
    "DEEPLYNX_BASE_URL",
    "DEEPLYNX_KEY",
    "DEEPLYNX_SECRET",
    "DEEPLYNX_ORG_ID",
    "DEEPLYNX_PROJECT_ID",
)
MESSAGE_PREFIX = "@@ "
RUN_TIMEOUT = 180
# <ws>/prometheus_core/platform/tests/infrastructure/<this file> -> <ws>/specs/proof/.
PROOF_PATH = Path(__file__).resolve().parents[4] / "specs" / "proof" / "adk-resume-after.md"
SCENARIOS = {
    1: "LongRunningFunctionTool approval wait, kill, approve",
    2: "slow tool (30 s), kill halfway, resume",
    3: "a step fails and the agent replans",
    4: "forced compaction mid-run",
    5: "artifact saved twice, kill, resume",
}
_results: dict[int, tuple[str, str]] = {}
_prerequisite_failure: list[str] = []
_prerequisite_skip: list[str] = []

# The in-container probe. It reads its arguments as: scenario phase session_id [invocation_id].
# Every line it prints for the test starts with "@@ " and is one JSON object.
_PROBE = r'''
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from a2a.server.agent_execution.context import RequestContext
from google.adk.agents import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import FunctionTool, LongRunningFunctionTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from prometheus_api.adk.artifacts import artifact_key, find_by_property, idempotency_key
from prometheus_api.adk.plugins.compaction import CompactionPolicy
from prometheus_api.adk.plugins.provenance import GENERATED
from prometheus_api.adk.runner import build_runner
from prometheus_api.agent import PrometheusAgent
from prometheus_api.storage_client.async_client import AsyncStorageClient
from prometheus_api.storage_client.connection import ConnectionConfig
from prometheus_api.storage_client.models.item import ItemCreate

SCENARIO, PHASE, SESSION_ID = sys.argv[1], sys.argv[2], sys.argv[3]
INVOCATION_ID = sys.argv[4] if len(sys.argv) > 4 else None
USER_ID = "adk-resume-probe"
BASE = f"/tmp/adk-resume-{SCENARIO}-{SESSION_ID}"
STEPS = Path(f"{BASE}.jsonl")
LEDGER = Path(f"{BASE}.jobs.jsonl")
RECORD = Path(f"{BASE}.record")
FLAG = Path(f"{BASE}.flag")
SLOW_FILE = "slow-job.json"
REPORT_FILE = "report.txt"
PADDING = "x" * 1500
REQUIRED = ("ADK_SESSION_DB_URL", "DEEPLYNX_BASE_URL", "DEEPLYNX_KEY", "DEEPLYNX_SECRET",
            "DEEPLYNX_ORG_ID", "DEEPLYNX_PROJECT_ID")


def say(**message: Any) -> None:
    print("@@ " + json.dumps(message, default=str), flush=True)


def log_step(step: str, **fields: Any) -> None:
    with STEPS.open("a") as handle:
        handle.write(json.dumps({"step": step, "pid": os.getpid(), **fields}) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---- tools -------------------------------------------------------------------------------


def step_one(tool_context: ToolContext) -> dict:
    """The step before the approval."""
    log_step("step_one", call_id=tool_context.function_call_id)
    return {"status": "ok", "step": "one"}


def approve(tool_context: ToolContext) -> dict:
    """Ask a human to approve the plan."""
    log_step("approve", call_id=tool_context.function_call_id)
    return {"status": "pending"}


def step_two(tool_context: ToolContext) -> dict:
    """The step after the approval."""
    log_step("step_two", call_id=tool_context.function_call_id)
    return {"status": "ok", "step": "two"}


def prepare(tool_context: ToolContext) -> dict:
    """The step before the slow job."""
    log_step("prepare", call_id=tool_context.function_call_id)
    return {"status": "ok"}


async def slow_job(tool_context: ToolContext) -> dict:
    """Submit one job, keyed by the call's idempotency key, and wait 30 s for it."""
    key = f"{tool_context.invocation_id}:{tool_context.function_call_id}"
    log_step(
        "slow_job_start",
        call_id=tool_context.function_call_id,
        invocation_id=tool_context.invocation_id,
        key=key,
        sdk_key=idempotency_key(SLOW_FILE),
    )
    jobs = [job for job in read_jsonl(LEDGER) if job["key"] == key]
    if jobs:
        job_id = jobs[0]["job_id"]
    else:
        job_id = f"job-{len(read_jsonl(LEDGER)) + 1}"
        with LEDGER.open("a") as handle:
            handle.write(json.dumps({"key": key, "job_id": job_id}) + "\n")
        log_step("job_created", key=key, job_id=job_id)
    version = await tool_context.save_artifact(
        SLOW_FILE,
        types.Part.from_bytes(data=json.dumps({"job_id": job_id}).encode(), mime_type="application/json"),
    )
    log_step("slow_job_saved", version=version)
    await asyncio.sleep(15)
    say(marker="halfway")
    await asyncio.sleep(15)
    log_step("slow_job_done", job_id=job_id)
    return {"status": "ok", "job_id": job_id}


def flaky_step(tool_context: ToolContext) -> dict:
    """A step that fails."""
    log_step("flaky_step", call_id=tool_context.function_call_id)
    return {"status": "error", "error": "simulated failure of flaky_step"}


def fallback_step(tool_context: ToolContext) -> dict:
    """The step the replan uses instead."""
    log_step("fallback_step", call_id=tool_context.function_call_id)
    return {"status": "ok"}


def produce_artifact(index: int, tool_context: ToolContext) -> dict:
    """Return a large result that names one artifact."""
    artifact_id = f"art-{SESSION_ID[:8]}-{index}"
    log_step("produce_artifact", call_id=tool_context.function_call_id, artifact_id=artifact_id)
    return {
        "artifact_id": artifact_id,
        "uri": f"deeplynx://organizations/1/projects/1/items/{900000 + index}",
        "padding": PADDING,
    }


async def save_report(content: str, tool_context: ToolContext) -> dict:
    """Save one version of report.txt; stop for the kill after the second save."""
    version = await tool_context.save_artifact(REPORT_FILE, types.Part(text=content))
    log_step("save_report", call_id=tool_context.function_call_id, content=content, version=version)
    if content == "v2" and not FLAG.exists():
        FLAG.write_text("killed")
        say(marker="saved_second")
        await asyncio.sleep(600)
    return {"status": "ok", "version": version}


TOOLS = {
    "1": [FunctionTool(step_one), LongRunningFunctionTool(approve), FunctionTool(step_two)],
    "2": [FunctionTool(prepare), FunctionTool(slow_job)],
    "3": [FunctionTool(flaky_step), FunctionTool(fallback_step)],
    "4": [FunctionTool(produce_artifact)],
    "5": [FunctionTool(save_report)],
}


# ---- the scripted model ------------------------------------------------------------------


def responses(contents: list[types.Content]) -> dict[str, list[dict]]:
    found: dict[str, list[dict]] = {}
    for content in contents:
        for part in content.parts or []:
            if part.function_response:
                found.setdefault(part.function_response.name or "", []).append(
                    part.function_response.response or {}
                )
    return found


def called(contents: list[types.Content], name: str) -> bool:
    return any(
        part.function_call and part.function_call.name == name
        for content in contents
        for part in content.parts or []
    )


_issued: list[str] = []


def call(name: str, args: dict | None = None) -> types.Part:
    # Ids that do not start with "adk-", so ADK keeps them in the request to the model.
    call_id = f"probe-{SCENARIO}-{name}-{len(_issued) + 1}-{os.getpid()}"
    _issued.append(call_id)
    log_step("model_call", name=name, call_id=call_id)
    return types.Part(function_call=types.FunctionCall(id=call_id, name=name, args=args or {}))


def next_parts(contents: list[types.Content]) -> list[types.Part]:
    seen = responses(contents)
    done = [types.Part(text="done")]
    if SCENARIO == "1":
        if "step_two" in seen:
            return done
        if any("approved" in json.dumps(r) for r in seen.get("approve", [])):
            return [call("step_two")]
        if called(contents, "approve"):
            return [types.Part(text="waiting for approval")]
        if "step_one" in seen:
            return [call("approve")]
        return [call("step_one")]
    if SCENARIO == "2":
        if "slow_job" in seen:
            return done
        if "prepare" in seen:
            return [call("slow_job")]
        return [call("prepare")]
    if SCENARIO == "3":
        if "fallback_step" in seen:
            return done
        if any(r.get("status") == "error" for r in seen.get("flaky_step", [])):
            return [
                types.Part(text="REPLAN: flaky_step failed; the new plan runs fallback_step."),
                call("fallback_step"),
            ]
        return [call("flaky_step")]
    if SCENARIO == "4":
        # Compaction rewrites old responses, so count the calls this process issued.
        made = sum(1 for c in _issued if "produce_artifact" in c)
        return done if made >= 4 else [call("produce_artifact", {"index": made + 1})]
    if SCENARIO == "5":
        made = len(seen.get("save_report", []))
        return done if made >= 2 else [call("save_report", {"content": f"v{made + 1}"})]
    raise ValueError(SCENARIO)


class ScriptedLlm(BaseLlm):
    model: str = "stub"

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False):
        if SCENARIO == "4":
            dumped = [c.model_dump(mode="json", exclude_none=True) for c in llm_request.contents]
            log_step("llm_request", contents_json=json.dumps(dumped))
        yield LlmResponse(content=types.Content(role="model", parts=next_parts(llm_request.contents)))


class StubSummarizer(BaseLlm):
    model: str = "stub-summarizer"

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False):
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text="Earlier turns made results.")])
        )


# ---- the agent and runner ----------------------------------------------------------------


class ProbeAgent(PrometheusAgent):
    def get_raw_agent_card(self) -> dict[str, Any]:
        return {"name": self.agent_name, "skills": []}


class RecordingQueue:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def enqueue_event(self, event: Any) -> None:
        self.events.append(event)


def make_runner(agent: ProbeAgent):
    context = MagicMock(spec=RequestContext)
    context.task_id = f"adk-resume-task-{SESSION_ID}"
    context.context_id = SESSION_ID
    context.current_task = None
    if SCENARIO == "4":
        compaction = CompactionPolicy(
            trigger_ratio=0.5, tail_tokens=50, cooldown_calls=0, default_input_window=1000
        )
    else:
        compaction = CompactionPolicy()
    root = LlmAgent(
        name="adk_resume_probe",
        model=ScriptedLlm(),
        instruction="Run the scripted plan.",
        tools=TOOLS[SCENARIO],
    )
    return build_runner(
        agent,
        context,
        root,
        event_queue=RecordingQueue(),
        compaction=compaction,
        test=False,
        summarizer_model=StubSummarizer(),
    )


def pending_approval(session) -> types.Content:
    open_calls = [
        fc
        for event in session.events
        if event.invocation_id == INVOCATION_ID
        for fc in event.get_function_calls()
        if fc.name == "approve" and fc.id in (event.long_running_tool_ids or set())
    ]
    if not open_calls:
        raise RuntimeError("no pending approve call in the session")
    fc = open_calls[0]
    return types.Content(
        role="user",
        parts=[types.Part(function_response=types.FunctionResponse(
            id=fc.id, name=fc.name, response={"result": "approved"}
        ))],
    )


def summarize(event) -> dict[str, Any]:
    text = ""
    if event.content and event.content.parts:
        text = "".join(p.text or "" for p in event.content.parts)
    return {
        "author": event.author,
        "invocation_id": event.invocation_id,
        "calls": [[fc.name, fc.id] for fc in event.get_function_calls()],
        "responses": [[r.name, r.id, r.response] for r in event.get_function_responses()],
        "long_running": sorted(event.long_running_tool_ids or []),
        "text": text,
    }


async def run(agent: ProbeAgent) -> None:
    runner = make_runner(agent)
    if PHASE == "start":
        await runner.session_service.create_session(
            app_name=runner.app_name, user_id=USER_ID, session_id=SESSION_ID
        )
        kwargs: dict[str, Any] = {
            "new_message": types.Content(role="user", parts=[types.Part(text="Run the plan.")])
        }
    else:
        kwargs = {"invocation_id": INVOCATION_ID}
        if SCENARIO == "1":
            session = await runner.session_service.get_session(
                app_name=runner.app_name, user_id=USER_ID, session_id=SESSION_ID
            )
            kwargs["new_message"] = pending_approval(session)
    invocation_ids: set[str] = set()
    last = None
    async for event in runner.run_async(user_id=USER_ID, session_id=SESSION_ID, **kwargs):
        if event.invocation_id and event.invocation_id not in invocation_ids:
            invocation_ids.add(event.invocation_id)
            say(marker="invocation", invocation_id=event.invocation_id)
        # With resumability on, ADK ends with empty end_of_agent events; keep the last text.
        if event.content and any(p.text for p in event.content.parts or []):
            last = event
    say(
        marker="run_done",
        invocation_ids=sorted(invocation_ids),
        final=summarize(last) if last is not None else None,
    )
    if SCENARIO == "1" and PHASE == "start":
        # The run paused on the approval; hold the process so the test can kill it.
        say(marker="paused")
        await asyncio.sleep(600)


async def deeplynx_report(app_name: str) -> dict[str, Any]:
    filename = {"2": SLOW_FILE, "5": REPORT_FILE}.get(SCENARIO)
    if filename is None:
        return {}
    key = artifact_key(app_name, USER_ID, SESSION_ID, filename)
    async with AsyncStorageClient(ConnectionConfig.from_env()) as dl:
        items = [i for i in await find_by_property(dl, "artifact_key", key)
                 if i.properties.get("kind") == "artifact"]
        report: dict[str, Any] = {
            "items": [
                {"id": i.id, "version": i.properties.get("version"),
                 "idempotency_key": i.properties.get("idempotency_key")}
                for i in items
            ]
        }
        if RECORD.exists():
            record_id = int(RECORD.read_text())
            rels = await dl.relationships.get_item_relationships(record_id, "outgoing")
            report["record_id"] = record_id
            # Raw evidence: the same GET get_item_relationships makes, through the SDK's
            # authenticated _request. Only the JSON body is kept, never a header.
            raw: dict[str, Any] = {}
            for direction, is_origin in (("outgoing", "true"), ("incoming", "false")):
                try:
                    response = await dl._request(
                        "GET",
                        f"{dl.relationships._base_path}/records/{record_id}/edges",
                        params={"page": 1, "pageSize": 100, "isOrigin": is_origin},
                    )
                    raw[direction] = {"status": response.status_code, "body": response.json()}
                except Exception as error:
                    raw[direction] = {"error": f"{type(error).__name__}: {error}"}
            report["raw_edges"] = raw
            report["generated"] = [
                [r.from_item_id, r.to_item_id] for r in rels if r.relationship_type == GENERATED
            ]
    return report


async def main() -> None:
    say(marker="pid", pid=os.getpid())
    if PHASE == "preflight":
        say(marker="preflight", missing=[n for n in REQUIRED if not (os.getenv(n) or "").strip()])
        return
    agent = ProbeAgent(agent_name="ADK Resume Probe")
    if SCENARIO == "5" and PHASE in ("start", "resume"):
        if PHASE == "start":
            async with AsyncStorageClient(ConnectionConfig.from_env()) as dl:
                record = await dl.items.create(ItemCreate(
                    name=f"ADK resume probe record {SESSION_ID}",
                    description="Execution record of the ADK resume stack test",
                    properties={"kind": "execution", "probe": "adk-resume"},
                    class_id=None,
                    original_id=f"prometheus-execution:adk-resume-probe:{SESSION_ID}",
                ))
            RECORD.write_text(str(record.id))
        # The run's execution record: the ContextVar that PrometheusAgent._create_execution_record
        # sets, bound here to the item this probe made (no verified identity in the probe).
        agent._execution_record_id.set(int(RECORD.read_text()))
    if PHASE in ("start", "resume"):
        await run(agent)
        return
    runner = make_runner(agent)
    if PHASE == "report":
        session = await runner.session_service.get_session(
            app_name=runner.app_name, user_id=USER_ID, session_id=SESSION_ID
        )
        say(
            marker="report",
            events=[summarize(e) for e in (session.events if session else [])],
            steps=read_jsonl(STEPS),
            jobs=read_jsonl(LEDGER),
            deeplynx=await deeplynx_report(runner.app_name),
        )
        return
    if PHASE == "cleanup":
        await runner.session_service.delete_session(
            app_name=runner.app_name, user_id=USER_ID, session_id=SESSION_ID
        )
        report = await deeplynx_report(runner.app_name)
        async with AsyncStorageClient(ConnectionConfig.from_env()) as dl:
            for item in report.get("items", []):
                await dl.items.delete(item["id"])
            if report.get("record_id"):
                await dl.items.delete(report["record_id"])
        for path in (STEPS, LEDGER, RECORD, FLAG):
            path.unlink(missing_ok=True)
        say(marker="cleaned")
        return
    raise ValueError(PHASE)


asyncio.run(main())
'''


class _Secret:
    """A secret value whose repr and str are '***'; ``reveal()`` returns the raw value."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "***"

    __str__ = __repr__


def _env_secrets(project_root: Path) -> dict[str, _Secret]:
    """Return the set ``ENV_NAMES`` from the environment, then platform/.env, each masked.

    No raw value is bound to a plain local, so a traceback with locals shows only '***'.
    """
    found: dict[str, _Secret] = {}
    env_path = project_root / ".env"
    lines = map(_Secret, env_path.read_text().splitlines()) if env_path.is_file() else iter(())
    for line in lines:
        name = line.reveal().partition("=")[0].strip()
        if name in ENV_NAMES and name not in found and line.reveal().partition("=")[2].strip():
            found[name] = _Secret(line.reveal().partition("=")[2].strip())
    for name in ENV_NAMES:
        if (os.getenv(name) or "").strip():
            found[name] = _Secret((os.getenv(name) or "").strip())
    return found


# Masked values of ENV_NAMES, filled by adk_stack, that _scrub removes from any text.
_known_secrets: list[_Secret] = []
_SECRET_PATTERNS = (
    re.compile(r"(://[^:/@\s]+:)[^@\s]+(?=@)"),  # user:password@ in a URL
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"()eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"),  # a JWT
    re.compile(r"(?i)((?:password|secret|api[_-]?key|token)[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+"),
)


def _scrub(text: str) -> str:
    """Remove every known secret value, URL password, bearer token and JWT from ``text``."""
    for secret in _known_secrets:
        if len(secret.reveal()) >= 4:
            text = text.replace(secret.reveal(), "***")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(r"\1***", text)
    return text


def _container_status(name: str) -> str:
    try:
        return subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Status}}", name],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"Docker is not available: {type(exc).__name__}")


def _probe_command(*args: str) -> list[str]:
    return ["docker", "exec", "-i", CONTAINER, "python", "-u", "-", *args]


def _messages(stdout: str) -> list[dict[str, Any]]:
    return [
        json.loads(line[len(MESSAGE_PREFIX) :])
        for line in stdout.splitlines()
        if line.startswith(MESSAGE_PREFIX)
    ]


def _run_scrubbed(command: list[str], **kwargs: Any) -> tuple[int, str, str]:
    """Run ``command``; return its exit code and its scrubbed stdout and stderr.

    No ``CompletedProcess`` is left in a caller's locals, so a traceback shows no raw output.
    """
    try:
        result = subprocess.run(command, capture_output=True, text=True, **kwargs)
    except subprocess.TimeoutExpired:
        # The exception carries the raw output; raise a bare one without it.
        raise subprocess.TimeoutExpired(command[:3], kwargs.get("timeout") or 0) from None
    return result.returncode, _scrub(result.stdout), _scrub(result.stderr)


def _run_probe(*args: str, timeout: int = RUN_TIMEOUT) -> list[dict[str, Any]]:
    """Run one probe phase to completion and return its messages; fail on a non-zero exit."""
    returncode, stdout, stderr = _run_scrubbed(
        _probe_command(*args), input=_PROBE, timeout=timeout
    )
    if returncode != 0:
        pytest.fail(f"probe {args[:2]} exited {returncode}: {stderr[-3000:]}")
    return _messages(stdout)


def _message(messages: list[dict[str, Any]], marker: str) -> dict[str, Any]:
    found = [m for m in messages if m.get("marker") == marker]
    assert found, _scrub(f"the probe printed no {marker!r} marker: {messages}")
    return found[-1]


# The client-agent image has no `kill` binary, so signals go through the container's python.
_SIGKILL_SCRIPT = "import os, signal, sys; os.kill(int(sys.argv[1]), signal.SIGKILL)"
# Exit 0 while the pid lives; exit 3 when it is gone or a zombie (killed, not yet reaped).
_ALIVE_SCRIPT = """
import os, sys
pid = int(sys.argv[1])
try:
    os.kill(pid, 0)
except ProcessLookupError:
    sys.exit(3)
try:
    with open(f"/proc/{pid}/stat") as handle:
        state = handle.read().rsplit(")", 1)[1].split()[0]
except FileNotFoundError:
    sys.exit(3)
sys.exit(3 if state == "Z" else 0)
"""
_started: list["_Background"] = []


def _container_python(script: str, pid: int) -> tuple[int, str, str]:
    return _run_scrubbed(
        ["docker", "exec", CONTAINER, "python", "-c", script, str(pid)], timeout=30
    )


def _pid_alive(pid: int) -> bool:
    returncode, _, stderr = _container_python(_ALIVE_SCRIPT, pid)
    if returncode not in (0, 3):
        pytest.fail(f"could not check probe pid {pid}: exit {returncode}: {stderr}")
    return returncode == 0


class _Background:
    """A probe phase that runs until the test kills its process inside the container."""

    def __init__(self, *args: str) -> None:
        self.messages: list[dict[str, Any]] = []
        self.stderr: list[str] = []
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self.proc = subprocess.Popen(
            _probe_command(*args),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert self.proc.stdin is not None
        self.proc.stdin.write(_PROBE)
        self.proc.stdin.close()
        self.pid: int | None = None
        _started.append(self)
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            if line.startswith(MESSAGE_PREFIX):
                message = json.loads(line[len(MESSAGE_PREFIX) :])
                if message.get("marker") == "pid":
                    self.pid = int(message["pid"])
                self._queue.put(message)
        self._queue.put(None)

    def _read_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self.stderr.append(_scrub(line))

    def wait_for(self, marker: str, timeout: float = RUN_TIMEOUT) -> dict[str, Any]:
        """Return the first message with ``marker``; fail when the probe exits or times out."""
        while True:
            try:
                message = self._queue.get(timeout=timeout)
            except queue.Empty:
                pytest.fail(_scrub(f"no {marker!r} marker within {timeout} s: {self.messages}"))
            if message is None:
                self.proc.wait(timeout=30)
                pytest.fail(
                    f"the probe exited {self.proc.returncode} before {marker!r}: "
                    f"{''.join(self.stderr)[-3000:]}"
                )
            self.messages.append(message)
            if message.get("marker") == marker:
                return message

    def kill(self) -> None:
        """SIGKILL the probe inside the container, as a crash would; fail unless it is gone."""
        if self.pid is None:
            pytest.fail("the probe printed no pid, so it cannot be killed")
        returncode, _, stderr = _container_python(_SIGKILL_SCRIPT, self.pid)
        if returncode != 0:
            pytest.fail(f"kill of probe pid {self.pid} exited {returncode}: {stderr}")
        deadline = time.monotonic() + 15
        while _pid_alive(self.pid):
            if time.monotonic() > deadline:
                pytest.fail(f"probe pid {self.pid} still runs 15 s after SIGKILL")
            time.sleep(0.5)
        self._reap()

    def stop(self) -> None:
        """Best-effort finalizer: SIGKILL the probe if it may still run; never raise."""
        try:
            if self.pid is not None and self.proc.poll() is None:
                _container_python(_SIGKILL_SCRIPT, self.pid)
        except (OSError, subprocess.TimeoutExpired):
            pass
        self._reap()

    def _reap(self) -> None:
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)


@pytest.fixture(autouse=True)
def _stop_probes() -> Iterator[None]:
    """Kill every background probe a test started, whether the test passed or failed."""
    yield
    while _started:
        _started.pop().stop()


def _cell(text: str) -> str:
    return " ".join(_scrub(text).split()).replace("|", "\\|")[:4000]


@pytest.fixture(scope="module", autouse=True)
def resume_proof() -> Iterator[None]:
    """Write specs/proof/adk-resume-after.md after the module, whatever the outcomes."""
    yield
    if _prerequisite_skip:
        not_run = ("skipped", _prerequisite_skip[-1])
    else:
        not_run = (
            "fail",
            "not run" + (f": {_prerequisite_failure[-1]}" if _prerequisite_failure else ""),
        )
    lines = [
        "# ADK resume gate: results",
        "",
        "Written by `platform/tests/infrastructure/test_integration_adk_resume.py` (REQ-016-12).",
        "Scenarios 1 and 2 decide the gate.",
        "",
        "| # | scenario | result | evidence |",
        "|---|---|---|---|",
    ]
    for number, name in SCENARIOS.items():
        result, evidence = _results.get(number, not_run)
        lines.append(f"| {number} | {name} | {result} | {_cell(evidence)} |")
    PROOF_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROOF_PATH.write_text("\n".join(lines) + "\n")


@contextmanager
def _scenario(number: int) -> Iterator[dict[str, Any]]:
    """Record the outcome and evidence of one scenario for the proof file."""
    evidence: dict[str, Any] = {}
    try:
        yield evidence
    except BaseException as exc:
        message = _scrub(str(exc).splitlines()[0]) if str(exc) else type(exc).__name__
        _results[number] = ("fail", f"{message}; {json.dumps(evidence, default=str)}")
        raise
    _results[number] = ("pass", json.dumps(evidence, default=str))


@pytest.fixture
def adk_stack(project_root: Path) -> None:
    """Skip unless client-agent and admin-db run; fail when a required setting is missing."""
    try:
        _check_stack(project_root)
    except pytest.skip.Exception as exc:
        _prerequisite_skip.append(_scrub(str(exc).splitlines()[0]) if str(exc) else "skipped")
        raise
    except BaseException as exc:
        _prerequisite_failure.append(
            _scrub(str(exc).splitlines()[0]) if str(exc) else type(exc).__name__
        )
        raise


def _check_stack(project_root: Path) -> None:
    for name in (CONTAINER, DB_CONTAINER):
        status = _container_status(name)
        if status != "running":
            # A stopped or absent container is no stack to test against: skip, with the reason.
            pytest.skip(f"The {name} container is not running (status {status!r})")
    secrets = _env_secrets(project_root)
    _known_secrets[:] = list(secrets.values())
    missing = [name for name in ENV_NAMES if name not in secrets]
    if missing:
        pytest.fail(f"platform/.env does not set: {', '.join(missing)}")
    preflight = _message(_run_probe("0", "preflight", "none", timeout=60), "preflight")
    if preflight["missing"]:
        pytest.fail(f"the {CONTAINER} environment does not set: {', '.join(preflight['missing'])}")


@pytest.fixture
def session_id(adk_stack: None):
    """A unique ADK session ID; the cleanup phase removes what the scenario made."""
    created: list[str] = []

    def _new(scenario: str) -> str:
        created.append(scenario)
        return value

    value = f"adk-resume-{uuid.uuid4()}"
    yield _new
    # Stop any probe still running before its session and items are deleted.
    while _started:
        _started.pop().stop()
    for scenario in created:
        try:
            _run_scrubbed(_probe_command(scenario, "cleanup", value), input=_PROBE, timeout=RUN_TIMEOUT)
        except subprocess.TimeoutExpired:
            pytest.fail(f"cleanup of scenario {scenario} timed out after {RUN_TIMEOUT} s")


def _report(scenario: str, session: str) -> dict[str, Any]:
    return _message(_run_probe(scenario, "report", session), "report")


def _steps(report: dict[str, Any], step: str) -> list[dict[str, Any]]:
    return [s for s in report["steps"] if s["step"] == step]


def _agent_invocations(report: dict[str, Any]) -> set[str]:
    return {e["invocation_id"] for e in report["events"] if e["author"] != "user"}


def test_approval_wait_resumes_after_kill_without_rerunning_the_step_before(session_id):
    """Covers REQ-016-12: scenario 1, a LongRunningFunctionTool approval wait, killed, approved."""
    with _scenario(1) as evidence:
        session = session_id("1")
        first = _Background("1", "start", session)
        try:
            invocation_id = first.wait_for("invocation")["invocation_id"]
            first.wait_for("paused")
        finally:
            first.kill()

        resumed = _run_probe("1", "resume", session, invocation_id)
        report = _report("1", session)
        done = _message(resumed, "run_done")
        evidence.update(
            invocation_id=invocation_id,
            resumed_invocations=done["invocation_ids"],
            step_one=len(_steps(report, "step_one")),
            approve=len(_steps(report, "approve")),
            step_two=len(_steps(report, "step_two")),
        )

        assert done["invocation_ids"] == [invocation_id]
        assert done["final"] is not None and done["final"]["text"] == "done"
        assert evidence["step_one"] == 1, "the step before the approval ran again"
        assert evidence["approve"] == 1, "the approval call ran again"
        assert evidence["step_two"] == 1, "the run did not continue after the approval"
        assert _agent_invocations(report) == {invocation_id}


def test_slow_tool_killed_halfway_resumes_with_its_idempotency_key_and_no_second_job(session_id):
    """Covers REQ-016-12: scenario 2, a 30 s tool killed halfway, then resumed."""
    with _scenario(2) as evidence:
        session = session_id("2")
        first = _Background("2", "start", session)
        try:
            invocation_id = first.wait_for("invocation")["invocation_id"]
            first.wait_for("halfway")
        finally:
            first.kill()

        resumed = _run_probe("2", "resume", session, invocation_id)
        report = _report("2", session)
        done = _message(resumed, "run_done")
        starts = _steps(report, "slow_job_start")
        items = report["deeplynx"]["items"]
        evidence.update(
            invocation_id=invocation_id,
            resumed_invocations=done["invocation_ids"],
            prepare=len(_steps(report, "prepare")),
            slow_job_starts=len(starts),
            call_ids=sorted({s["call_id"] for s in starts}),
            idempotency_keys=sorted({str(s["sdk_key"]) for s in starts}),
            jobs=len(report["jobs"]),
            deeplynx_items=[i["id"] for i in items],
        )

        assert done["invocation_ids"] == [invocation_id]
        assert done["final"] is not None and done["final"]["text"] == "done"
        assert evidence["prepare"] == 1, "the finished step before the slow tool ran again"
        assert len(starts) == 2, f"expected the killed call and its resume, got {starts}"
        assert len(evidence["call_ids"]) == 1, "the resume used a new function call id"
        assert {s["invocation_id"] for s in starts} == {invocation_id}
        assert len({s["key"] for s in starts}) == 1
        assert {s["sdk_key"] for s in starts} == {f"{starts[0]['key']}:slow-job.json"}
        assert len(report["jobs"]) == 1, f"a second job was made: {report['jobs']}"
        assert len(_steps(report, "slow_job_done")) == 1
        assert len(items) == 1, f"a second DeepLynx item was made: {items}"
        assert items[0]["idempotency_key"] == starts[0]["sdk_key"]
        assert _agent_invocations(report) == {invocation_id}


def test_failed_step_replan_is_stored_in_the_session_events(session_id):
    """Covers REQ-016-12: scenario 3, a step fails and the agent replans."""
    with _scenario(3) as evidence:
        session = session_id("3")
        _run_probe("3", "start", session)
        # The report runs in a new process, so the events come from the database session service.
        report = _report("3", session)

        events = report["events"]
        failed = next(
            i
            for i, e in enumerate(events)
            if any(
                name == "flaky_step" and resp.get("status") == "error"
                for name, _, resp in e["responses"]
            )
        )
        replan = next(
            (i for i, e in enumerate(events) if i > failed and "REPLAN" in e["text"]),
            None,
        )
        evidence.update(events=len(events), failure_event=failed, replan_event=replan)

        assert replan is not None, f"no replan event after the failure: {events}"
        assert [c[0] for c in events[replan]["calls"]] == ["fallback_step"]
        assert any(
            name == "fallback_step" for e in events[replan + 1 :] for name, _, _ in e["responses"]
        ), "the replanned step has no response in the session"
        assert len(_steps(report, "flaky_step")) == 1
        assert len(_steps(report, "fallback_step")) == 1


def test_forced_compaction_keeps_every_artifact_and_tool_call_id_in_the_llm_request(session_id):
    """Covers REQ-016-12: scenario 4, compaction forced mid-run by a tiny input window."""
    with _scenario(4) as evidence:
        session = session_id("4")
        _run_probe("4", "start", session)
        report = _report("4", session)

        call_ids: list[str] = []
        artifact_ids: list[str] = []
        requests = 0
        compacted = 0
        lost: list[str] = []
        for step in report["steps"]:
            if step["step"] == "model_call":
                call_ids.append(step["call_id"])
            elif step["step"] == "produce_artifact":
                artifact_ids.append(step["artifact_id"])
            elif step["step"] == "llm_request":
                requests += 1
                sent = step["contents_json"]
                compacted += "[reference only]" in sent
                lost += [f"{requests}:{i}" for i in call_ids + artifact_ids if i not in sent]
        evidence.update(
            llm_requests=requests,
            compacted_requests=compacted,
            tool_call_ids=len(call_ids),
            artifact_ids=len(artifact_ids),
            lost=lost,
        )

        assert not lost, f"LlmRequests lost ids {lost}"
        assert len(artifact_ids) == 4
        assert requests == 5
        assert compacted >= 1, "no LlmRequest was compacted; the forced compaction did not run"


def test_artifact_saved_twice_gives_two_items_and_two_generated_edges_without_resume_duplicate(
    session_id,
):
    """Covers REQ-016-12: scenario 5, two saves of one artifact, killed after the second save."""
    with _scenario(5) as evidence:
        session = session_id("5")
        first = _Background("5", "start", session)
        try:
            invocation_id = first.wait_for("invocation")["invocation_id"]
            first.wait_for("saved_second")
        finally:
            first.kill()

        resumed = _run_probe("5", "resume", session, invocation_id)
        report = _report("5", session)
        saves = _steps(report, "save_report")
        dl = report["deeplynx"]
        item_ids = sorted(i["id"] for i in dl["items"])
        generated = sorted(dl.get("generated", []))
        evidence.update(
            invocation_id=invocation_id,
            save_versions=[s["version"] for s in saves],
            record_id=dl.get("record_id"),
            deeplynx_items=item_ids,
            generated_edges=generated,
            raw_edges=dl.get("raw_edges"),
        )

        assert _message(resumed, "run_done")["invocation_ids"] == [invocation_id]
        assert evidence["save_versions"] == [0, 1, 1], f"unexpected saves: {saves}"
        assert len(item_ids) == 2, f"expected two DeepLynx items, got {dl['items']}"
        assert sorted(i["version"] for i in dl["items"]) == [0, 1]
        assert generated == sorted([dl["record_id"], i] for i in item_ids), (
            f"expected one generated edge from the record to each item, got {generated}; "
            f"raw edges of the record: {json.dumps(dl.get('raw_edges'), default=str)}"
        )
        assert _agent_invocations(report) == {invocation_id}
