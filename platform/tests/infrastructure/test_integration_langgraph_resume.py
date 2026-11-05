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

"""Stack test: a LangGraph run on AsyncPostgresSaver resumes after a kill -9.

Each test runs a probe script (``_PROBE`` below) inside the already-running container of the
``artifact-debug-agent`` compose service with ``docker exec -i <container> python -u -``. The
containers have no fixed name, so the test finds the ``artifact-debug-agent`` and ``admin-db``
containers by their compose project and service labels (the ``container_id`` fixture).
The probe builds a small ``LangGraphPrometheusAgent`` whose LLM client is scripted (it calls
each planned tool once, then answers ``done``; no LLM) and runs it through the agent's real
``_execute``. So the checkpointer is the agent's own ``AsyncPostgresSaver`` on
``LANGGRAPH_CHECKPOINT_DB_URL`` (the ``langgraph`` schema of admin-db), the ``thread_id`` is
the task ID, and ``save_artifact`` writes to the real DeepLynx with the ``DEEPLYNX_*``
service account of the container.

Each tool appends one line per run to ``/tmp/lg-resume-<scenario>-<thread>.jsonl`` in the
container, so the test can count the steps that ran again. A test starts the probe, waits
for a marker line, kills the probe process inside the container with ``kill -9``, then runs
it again on the same ``thread_id``. A ``report`` run reads the checkpoint back and queries
DeepLynx, and the test counts the checkpoint rows of the thread in admin-db with ``psql``.

The test never starts, stops or rebuilds a container, so it does not use the
``docker_compose_up`` fixture. When Docker, ``artifact-debug-agent`` or ``admin-db`` does
not answer, the test skips with the reason (the stack phase reports a skip as a failure). A
running stack that lacks a required .env name or container variable fails the test. A
``cleanup`` run in a ``finally`` removes the checkpoint rows, DeepLynx items, artifact
registry keys and files that the probe made.
"""

import json
import os
import queue
import re
import subprocess
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest


pytestmark = pytest.mark.integration

# Compose service names; langgraph_stack resolves each one to its container ID in _containers.
SERVICE = "artifact-debug-agent"
DB_SERVICE = "admin-db"
_containers: dict[str, str] = {}
ENV_NAMES = (
    "LANGGRAPH_DB_PASSWORD",
    "DEEPLYNX_BASE_URL",
    "DEEPLYNX_KEY",
    "DEEPLYNX_SECRET",
    "DEEPLYNX_ORG_ID",
    "DEEPLYNX_PROJECT_ID",
)
MESSAGE_PREFIX = "@@ "
RUN_TIMEOUT = 180
KILL_TIMEOUT = 15
SLOW_FILE = "slow-job.json"
# <ws>/prometheus_core/platform/tests/infrastructure/<this file> -> <ws>/specs/proof/.
PROOF_PATH = Path(__file__).resolve().parents[4] / "specs" / "proof" / "langgraph-resume-after.md"
SCENARIOS = {
    1: "HITL approval interrupt, kill while it waits, resume with approve",
    2: "slow tool (30 s), kill halfway, resume with ainvoke(None)",
}
_results: dict[int, tuple[str, str]] = {}
_prerequisite_failure: list[str] = []
_prerequisite_skip: list[str] = []

# The in-container probe. It reads its arguments as: scenario phase thread_id.
# Every line it prints for the test starts with "@@ " and is one JSON object.
_PROBE = r'''
import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import AIMessage

from prometheus_api.langgraph import (
    LangGraphPrometheusAgent,
    PrometheusChatModel,
    PrometheusContext,
    save_artifact,
)
from prometheus_api.llm_client import AsyncLLMClient, ChatResponse
from prometheus_api.llm_client.tools import ToolCall
from prometheus_api.storage_client.async_client import AsyncStorageClient
from prometheus_api.storage_client.connection import ConnectionConfig

SCENARIO, PHASE, THREAD_ID = sys.argv[1], sys.argv[2], sys.argv[3]
CONVERSATION_ID = f"conv-{THREAD_ID}"
BASE = f"/tmp/lg-resume-{SCENARIO}-{THREAD_ID}"
STEPS = Path(f"{BASE}.jsonl")
LEDGER = Path(f"{BASE}.jobs.jsonl")
SLOW_FILE = "slow-job.json"
SKILL = {"1": "approval_plan", "2": "slow_plan"}.get(SCENARIO, "none")
REQUIRED = ("LANGGRAPH_CHECKPOINT_DB_URL", "DEEPLYNX_BASE_URL", "DEEPLYNX_KEY",
            "DEEPLYNX_SECRET", "DEEPLYNX_ORG_ID", "DEEPLYNX_PROJECT_ID")
# Compose passes DEEPLYNX_DATA_SOURCE_ID="" when .env leaves it unset, and
# ConnectionConfig.from_env reads an empty value as int(""); drop it so it is unset.
if not (os.getenv("DEEPLYNX_DATA_SOURCE_ID") or "").strip():
    os.environ.pop("DEEPLYNX_DATA_SOURCE_ID", None)


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


@tool
def step_one(runtime: ToolRuntime[PrometheusContext]) -> str:
    """The step before the approval."""
    log_step("step_one", call_id=runtime.tool_call_id)
    return "step one finished"


@tool
def approve(runtime: ToolRuntime[PrometheusContext]) -> str:
    """The step that needs a human approval."""
    log_step("approve", call_id=runtime.tool_call_id)
    return "approved step finished"


@tool
def step_two(runtime: ToolRuntime[PrometheusContext]) -> str:
    """The step after the approval."""
    log_step("step_two", call_id=runtime.tool_call_id)
    return "step two finished"


@tool
def prepare(runtime: ToolRuntime[PrometheusContext]) -> str:
    """The step before the slow job."""
    log_step("prepare", call_id=runtime.tool_call_id)
    return "prepared"


@tool
async def slow_job(runtime: ToolRuntime[PrometheusContext]) -> str:
    """Submit one job keyed by thread and tool call, save slow-job.json, and wait 30 s."""
    call_id = runtime.tool_call_id
    key = f"{runtime.context.thread_id}:{call_id}"
    log_step("slow_job_start", call_id=call_id, key=key)
    jobs = [job for job in read_jsonl(LEDGER) if job["key"] == key]
    if jobs:
        job_id = jobs[0]["job_id"]
    else:
        job_id = f"job-{len(read_jsonl(LEDGER)) + 1}"
        with LEDGER.open("a") as handle:
            handle.write(json.dumps({"key": key, "job_id": job_id}) + "\n")
        log_step("job_created", key=key, job_id=job_id)
    saved = await save_artifact(
        runtime, SLOW_FILE, json.dumps({"job_id": job_id}).encode(), "application/json"
    )
    log_step("slow_job_saved", item_id=saved.item_id, version=saved.version)
    await asyncio.sleep(15)
    say(marker="halfway")
    await asyncio.sleep(15)
    log_step("slow_job_done", job_id=job_id)
    return f"{job_id} finished"


TOOLS = {"1": [step_one, approve, step_two], "2": [prepare, slow_job]}
PLANS = {"1": ["step_one", "approve", "step_two"], "2": ["prepare", "slow_job"]}


# ---- the scripted LLM client -------------------------------------------------------------


class ScriptedClient(AsyncLLMClient):
    """Calls each planned tool once, in order, then answers "done".

    The reply depends only on the tool results already in the messages, so a run that
    starts over calls the first tool again.
    """

    def __init__(self, plan: list[str]):
        # No config: the client never reaches a provider.
        self._plan = plan

    async def chat(self, text_or_messages, model=None, trace_tags=None, **kwargs):
        names = {
            call["id"]: call["function"]["name"]
            for message in text_or_messages
            for call in message.get("tool_calls") or []
        }
        answered = {
            names.get(message.get("tool_call_id"))
            for message in text_or_messages
            if message.get("role") == "tool"
        }
        for name in self._plan:
            if name not in answered:
                call_id = f"call-{name}-{os.getpid()}"
                log_step("model_call", name=name, call_id=call_id)
                call = ToolCall(id=call_id, name=name, arguments={})
                return ChatResponse("", "default", "resolved", None, {}, (call,), "tool_calls")
        log_step("model_answer")
        return ChatResponse("done", "default", "resolved", None, {}, (), "stop")

    async def aclose(self) -> None:
        return None


# ---- the agent ---------------------------------------------------------------------------


class ProbeAgent(LangGraphPrometheusAgent):
    def __init__(self) -> None:
        super().__init__(agent_name="LangGraph Resume Probe")
        self.approval_tools = frozenset({"approve"}) if SCENARIO == "1" else frozenset()
        self.agent_card_dict = {"skills": [{"id": SKILL, "name": SKILL}]}

    def skill_tools(self):
        return {SKILL: TOOLS[SCENARIO]}

    def llm_client(self, context, **kwargs):
        return ScriptedClient(PLANS[SCENARIO])

    async def storage_config(self):
        return ConnectionConfig.from_env()


class RecordingQueue:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def enqueue_event(self, event: Any) -> None:
        self.events.append(event)


CONTEXT = SimpleNamespace(task_id=THREAD_ID, context_id=CONVERSATION_ID, current_task=None)
CONFIG = {"configurable": {"thread_id": THREAD_ID}}


async def graph_state(agent: ProbeAgent):
    saver = await agent.checkpointer()
    graph = agent.build_graph(SKILL, PrometheusChatModel(client=ScriptedClient([])), saver)
    return await graph.aget_state(CONFIG)


async def run(agent: ProbeAgent) -> None:
    saver = await agent.checkpointer()
    say(marker="saver", type=type(saver).__name__)
    params: dict[str, Any] = {"skill_id": SKILL}
    if PHASE == "resume":
        state = await graph_state(agent)
        say(marker="before_resume", next=list(state.next), interrupts=len(state.interrupts))
        if SCENARIO == "1":
            params["approved"] = True
    result = await agent._execute(params, CONTEXT, RecordingQueue())
    say(marker="run_done", result=result)
    if SCENARIO == "1" and PHASE == "start":
        # The run paused on the approval interrupt; hold the process so the test can kill it.
        say(marker="paused")
        await asyncio.sleep(600)
    await agent.close_checkpointer()


async def deeplynx_items(agent: ProbeAgent) -> list[dict[str, Any]]:
    if SCENARIO != "2":
        return []
    key = f"{agent._producer_agent_id}/{THREAD_ID}/{SLOW_FILE}"
    filters = [{"filter": "properties", "operator": "KEY_VALUE",
                "json": json.dumps({"artifact_key": key})}]
    async with AsyncStorageClient(ConnectionConfig.from_env()) as dl:
        page = await dl.search.advanced_query(
            filters=filters, project_ids=[dl.config.project_id], page=1, page_size=500
        )
    return [
        {"id": i.id, "version": i.properties.get("version"),
         "idempotency_key": i.properties.get("idempotency_key")}
        for i in page.items
    ]


async def main() -> None:
    say(marker="pid", pid=os.getpid())
    if PHASE == "preflight":
        say(marker="preflight", missing=[n for n in REQUIRED if not (os.getenv(n) or "").strip()])
        return
    agent = ProbeAgent()
    if PHASE in ("start", "resume"):
        await run(agent)
        return
    if PHASE == "report":
        state = await graph_state(agent)
        messages = state.values.get("messages") or []
        final = next((m.text for m in reversed(messages) if isinstance(m, AIMessage) and m.text), None)
        say(
            marker="report",
            next=list(state.next),
            final_text=final,
            steps=read_jsonl(STEPS),
            jobs=read_jsonl(LEDGER),
            items=await deeplynx_items(agent),
        )
        await agent.close_checkpointer()
        return
    if PHASE == "cleanup":
        saver = await agent.checkpointer()
        await saver.adelete_thread(THREAD_ID)
        await agent.close_checkpointer()
        items = await deeplynx_items(agent)
        async with AsyncStorageClient(ConnectionConfig.from_env()) as dl:
            for item in items:
                await dl.items.delete(item["id"])
        registry = agent.artifact_registry
        client = registry.redis_client
        if client is not None:
            client.delete(
                registry._hash_key(CONVERSATION_ID),
                registry._name_map_key(CONVERSATION_ID),
                registry._order_key(CONVERSATION_ID),
            )
        for path in (STEPS, LEDGER):
            path.unlink(missing_ok=True)
        say(marker="cleaned", deleted_items=[item["id"] for item in items])
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


# Masked values of ENV_NAMES, filled by langgraph_stack, that _scrub removes from any text.
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


def _container(service: str) -> str:
    """Return the container ID that langgraph_stack resolved for ``service``."""
    return _containers.get(service, service)


def _container_status(container: str) -> str:
    try:
        return subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Status}}", container],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"Docker is not available: {type(exc).__name__}")


def _probe_command(*args: str) -> list[str]:
    return ["docker", "exec", "-i", _container(SERVICE), "python", "-u", "-", *args]


def _messages(stdout: str) -> list[dict[str, Any]]:
    return [json.loads(line[len(MESSAGE_PREFIX) :]) for line in stdout.splitlines() if line.startswith(MESSAGE_PREFIX)]


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
    returncode, stdout, stderr = _run_scrubbed(_probe_command(*args), input=_PROBE, timeout=timeout)
    if returncode != 0:
        pytest.fail(f"probe {args[:2]} exited {returncode}: {stderr[-3000:]}")
    return _messages(stdout)


def _message(messages: list[dict[str, Any]], marker: str) -> dict[str, Any]:
    found = [m for m in messages if m.get("marker") == marker]
    assert found, _scrub(f"the probe printed no {marker!r} marker: {messages}")
    return found[-1]


def _checkpoint_rows(thread_id: str) -> int:
    """Count the rows of ``thread_id`` in langgraph.checkpoints of admin-db."""
    returncode, stdout, stderr = _run_scrubbed(
        [
            "docker",
            "exec",
            "-i",
            _container(DB_SERVICE),
            "psql",
            "-U",
            "admin",
            "-d",
            "admin",
            "-v",
            "ON_ERROR_STOP=1",
            "-tA",
            "-v",
            f"thread={thread_id}",
        ],
        input="SELECT count(*) FROM langgraph.checkpoints WHERE thread_id = :'thread';\n",
        timeout=30,
    )
    if returncode != 0:
        pytest.fail(f"psql in {DB_SERVICE} exited {returncode}: {stderr[-3000:]}")
    return int(stdout.strip())


# Signals go through the container's python, so the image needs no `kill` binary.
# Exit 3 when the pid is already gone, so a probe that exited on its own is no kill failure.
_SIGKILL_SCRIPT = """
import os, signal, sys
try:
    os.kill(int(sys.argv[1]), signal.SIGKILL)
except ProcessLookupError:
    sys.exit(3)
"""
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
    return _run_scrubbed(["docker", "exec", _container(SERVICE), "python", "-c", script, str(pid)], timeout=30)


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
                    f"the probe exited {self.proc.returncode} before {marker!r}: {''.join(self.stderr)[-3000:]}"
                )
            self.messages.append(message)
            if message.get("marker") == marker:
                return message

    def kill(self) -> None:
        """SIGKILL the probe inside the container, as a crash would; fail unless it is gone.

        A probe that already exited needs no kill: return quietly, so the error that the
        probe exited with (raised by ``wait_for``) is the one the test reports.
        """
        if self.proc.poll() is not None:
            self._reap()
            return
        if self.pid is None:
            pytest.fail("the probe printed no pid, so it cannot be killed")
        returncode, _, stderr = _container_python(_SIGKILL_SCRIPT, self.pid)
        if returncode == 3:
            self._reap()
            return
        if returncode != 0:
            pytest.fail(f"kill of probe pid {self.pid} exited {returncode}: {stderr}")
        # docker exec returns when the killed process exits; wait for that once, bounded.
        try:
            self.proc.wait(timeout=KILL_TIMEOUT)
        except subprocess.TimeoutExpired:
            pytest.fail(f"docker exec of probe pid {self.pid} still runs {KILL_TIMEOUT} s after SIGKILL")
        if _pid_alive(self.pid):
            pytest.fail(f"probe pid {self.pid} still runs in {SERVICE} after SIGKILL")

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
    """Write specs/proof/langgraph-resume-after.md after the module, whatever the outcomes."""
    yield
    if _prerequisite_skip:
        not_run = ("skipped", _prerequisite_skip[-1])
    else:
        not_run = (
            "fail",
            "not run" + (f": {_prerequisite_failure[-1]}" if _prerequisite_failure else ""),
        )
    lines = [
        "# LangGraph resume after kill -9: results",
        "",
        "Written by `platform/tests/infrastructure/test_integration_langgraph_resume.py`.",
        "The probe runs `LangGraphPrometheusAgent` on `AsyncPostgresSaver` in `artifact-debug-agent`.",
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
def langgraph_stack(project_root: Path, container_id) -> None:
    """Skip unless artifact-debug-agent and admin-db run; fail when a setting is missing."""
    try:
        _check_stack(project_root, container_id)
    except pytest.skip.Exception as exc:
        _prerequisite_skip.append(_scrub(str(exc).splitlines()[0]) if str(exc) else "skipped")
        raise
    except BaseException as exc:
        _prerequisite_failure.append(_scrub(str(exc).splitlines()[0]) if str(exc) else type(exc).__name__)
        raise


def _check_stack(project_root: Path, container_id) -> None:
    for service in (SERVICE, DB_SERVICE):
        try:
            _containers[service] = container_id(service)
        except FileNotFoundError as exc:
            pytest.skip(f"Docker is not available: {type(exc).__name__}")
        status = _container_status(_container(service))
        if status != "running":
            # A stopped or absent container is no stack to test against: skip, with the reason.
            pytest.skip(f"The {service} container is not running (status {status!r})")
    secrets = _env_secrets(project_root)
    _known_secrets[:] = list(secrets.values())
    missing = [name for name in ENV_NAMES if name not in secrets]
    if missing:
        pytest.fail(f"platform/.env does not set: {', '.join(missing)}")
    preflight = _message(_run_probe("0", "preflight", "none", timeout=60), "preflight")
    if preflight["missing"]:
        pytest.fail(f"the {SERVICE} environment does not set: {', '.join(preflight['missing'])}")


@pytest.fixture
def thread_id(langgraph_stack: None):
    """A unique thread ID; the cleanup phase removes what the scenario made."""
    created: list[str] = []

    def _new(scenario: str) -> str:
        created.append(scenario)
        return value

    value = f"lg-resume-{uuid.uuid4()}"
    yield _new
    # Stop any probe still running before its checkpoints and items are deleted.
    while _started:
        _started.pop().stop()
    for scenario in created:
        try:
            _run_scrubbed(_probe_command(scenario, "cleanup", value), input=_PROBE, timeout=RUN_TIMEOUT)
        except subprocess.TimeoutExpired:
            pytest.fail(f"cleanup of scenario {scenario} timed out after {RUN_TIMEOUT} s")


def _report(scenario: str, thread: str) -> dict[str, Any]:
    return _message(_run_probe(scenario, "report", thread), "report")


def _steps(report: dict[str, Any], step: str) -> list[dict[str, Any]]:
    return [s for s in report["steps"] if s["step"] == step]


def test_approval_interrupt_resumes_after_kill_without_rerunning_a_finished_step(thread_id):
    """Scenario 1: step_one, an approval interrupt on approve, kill -9 while it waits, approve."""
    with _scenario(1) as evidence:
        thread = thread_id("1")
        first = _Background("1", "start", thread)
        try:
            saver = first.wait_for("saver")["type"]
            paused = first.wait_for("run_done")["result"]
            first.wait_for("paused")
        finally:
            first.kill()

        resumed = _run_probe("1", "resume", thread)
        before = _message(resumed, "before_resume")
        done = _message(resumed, "run_done")
        report = _report("1", thread)
        evidence.update(
            thread_id=thread,
            saver=saver,
            paused_result=paused,
            before_resume=before,
            resumed_result=done["result"],
            final_text=report["final_text"],
            checkpoint_rows=_checkpoint_rows(thread),
            step_one=len(_steps(report, "step_one")),
            approve=len(_steps(report, "approve")),
            step_two=len(_steps(report, "step_two")),
        )

        assert saver == "AsyncPostgresSaver"
        assert evidence["step_one"] == 1, "the step before the approval ran again"
        assert paused == {"status": "input_required"}
        assert before["interrupts"] == 1, "the resumed probe found no pending approval interrupt"
        assert evidence["checkpoint_rows"] > 0, "admin-db holds no checkpoint of the thread"
        assert evidence["approve"] == 1, "the approved step did not run exactly once"
        assert evidence["step_two"] == 1, "the run did not continue after the approval"
        assert done["result"] == {"status": "success", "result": "done"}
        assert report["final_text"] == "done"
        assert report["next"] == []


def test_slow_tool_killed_halfway_resumes_with_one_call_id_one_job_and_one_item(thread_id):
    """Scenario 2: prepare, then a 30 s slow_job killed halfway, resumed with ainvoke(None)."""
    with _scenario(2) as evidence:
        thread = thread_id("2")
        first = _Background("2", "start", thread)
        try:
            saver = first.wait_for("saver")["type"]
            first.wait_for("halfway")
        finally:
            first.kill()

        resumed = _run_probe("2", "resume", thread)
        before = _message(resumed, "before_resume")
        done = _message(resumed, "run_done")
        report = _report("2", thread)
        starts = _steps(report, "slow_job_start")
        call_ids = sorted({s["call_id"] for s in starts})
        items = report["items"]
        evidence.update(
            thread_id=thread,
            saver=saver,
            before_resume=before,
            resumed_result=done["result"],
            final_text=report["final_text"],
            checkpoint_rows=_checkpoint_rows(thread),
            prepare=len(_steps(report, "prepare")),
            slow_job_starts=len(starts),
            call_ids=call_ids,
            jobs=report["jobs"],
            deeplynx_items=items,
        )

        assert saver == "AsyncPostgresSaver"
        assert evidence["prepare"] == 1, "the finished step before the slow tool ran again"
        assert before["interrupts"] == 0 and before["next"], (
            f"the resumed probe found no unfinished checkpoint to continue with ainvoke(None): {before}"
        )
        assert evidence["checkpoint_rows"] > 0, "admin-db holds no checkpoint of the thread"
        assert len(starts) == 2, f"expected the killed call and its resume, got {starts}"
        assert len(call_ids) == 1, f"the resume used a new tool call id: {call_ids}"
        assert {s["key"] for s in starts} == {f"{thread}:{call_ids[0]}"}
        assert len(report["jobs"]) == 1, f"a second job was made: {report['jobs']}"
        assert len(_steps(report, "slow_job_done")) == 1
        assert len(items) == 1, f"a second DeepLynx item was made: {items}"
        assert items[0]["idempotency_key"] == f"{thread}:{call_ids[0]}:{SLOW_FILE}"
        assert {s["item_id"] for s in _steps(report, "slow_job_saved")} == {items[0]["id"]}
        assert done["result"] == {"status": "success", "result": "done"}
        assert report["final_text"] == "done"
