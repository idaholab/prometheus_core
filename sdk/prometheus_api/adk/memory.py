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
"""Procedural memory per role for ADK runs, stored in ``adk.procedures``.

A procedure is the ordered list of tool calls one successful run of a skill made. It is keyed by
``(role, task_signature)``, where the role is the ADK app name and the task signature is
``"<skill_id>:<sorted top-level param names, comma-separated>"``. The skill ID comes from the
session state key ``skill_id``; the param names come from the first user message of the run, which
``AdkPrometheusAgent`` sends as the params JSON object.

The commit gate reads the session state key ``execution_status``, which the provenance plugin
writes when it closes the run's execution record (``succeeded``, ``failed`` or ``cancelled``).
Only ``succeeded`` stores a procedure; ``failed`` counts a failure on an existing procedure and
never inserts one; any other value stores nothing.
"""

import json
import logging
import os
import uuid
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from google.adk.events.event import Event
from google.adk.memory.base_memory_service import BaseMemoryService, SearchMemoryResponse
from google.adk.memory.memory_entry import MemoryEntry
from google.adk.sessions.session import Session
from google.genai import types
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

logger = logging.getLogger(__name__)

SKILL_ID_STATE_KEY = "skill_id"
EXECUTION_STATUS_STATE_KEY = "execution_status"
SEARCH_LIMIT = 3
_COMMITTED_INVOCATIONS_MAX = 1024

_JSON = JSON().with_variant(JSONB(), "postgresql")


def _procedures_table(schema: str | None) -> Table:
    return Table(
        "procedures",
        MetaData(schema=schema),
        Column("id", Uuid, primary_key=True),
        Column("role", Text, nullable=False),
        Column("task_signature", Text, nullable=False),
        Column("steps", _JSON, nullable=False),
        Column("successes", Integer, nullable=False, default=0),
        Column("failures", Integer, nullable=False, default=0),
        Column("required_tools", _JSON, nullable=False, default=list),
        Column("updated_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint("role", "task_signature"),
    )


def _run_events(session: Session) -> list[Event]:
    """Return the events of the session's latest invocation."""
    if not session.events:
        return []
    invocation_id = session.events[-1].invocation_id
    return [event for event in session.events if event.invocation_id == invocation_id]


def _param_names(events: list[Event]) -> list[str]:
    """Return the sorted top-level keys of the params JSON in the run's first user message."""
    for event in events:
        if event.author != "user" or event.content is None:
            continue
        text = "".join(part.text or "" for part in event.content.parts or [])
        try:
            params = json.loads(text)
        except ValueError:
            return []
        return sorted(params) if isinstance(params, dict) else []
    return []


def _tool_steps(events: list[Event]) -> list[str]:
    """Return the run's tool-call names in call order."""
    return [call.name for event in events for call in event.get_function_calls() if call.name]


def _score(successes: int, failures: int) -> float:
    return successes / (successes + failures + 1)


class PrometheusMemoryService(BaseMemoryService):
    """ADK memory service that stores successful tool sequences per role.

    Storage is SQLAlchemy async on ``db_url`` or ``engine``, defaulting to ``ADK_SESSION_DB_URL``.
    On SQLite the service creates its ``procedures`` table; on Postgres it uses ``adk.procedures``,
    which the admin-db migration owns.
    """

    def __init__(
        self,
        db_url: str | None = None,
        *,
        engine: AsyncEngine | None = None,
        tools: Iterable[str] = (),
    ) -> None:
        if engine is None:
            url = db_url or (os.getenv("ADK_SESSION_DB_URL") or "").strip()
            if not url:
                raise ValueError(
                    "PrometheusMemoryService needs db_url, engine or ADK_SESSION_DB_URL"
                )
            engine = create_async_engine(url)
        self._engine = engine
        self._is_sqlite = engine.dialect.name == "sqlite"
        self._table = _procedures_table(None if self._is_sqlite else "adk")
        self._table_ready = not self._is_sqlite
        self._tools = frozenset(tools)
        # The most recent committed invocation IDs, bounded so a long-lived service does not grow.
        self._committed_invocations: OrderedDict[str, None] = OrderedDict()

    def set_tools(self, tools: Iterable[str]) -> None:
        """Set the tool names of the calling agent; search drops procedures needing others."""
        self._tools = frozenset(tools)

    async def _ensure_table(self) -> None:
        if self._table_ready:
            return
        async with self._engine.begin() as conn:
            await conn.run_sync(self._table.metadata.create_all)
        self._table_ready = True

    async def add_session_to_memory(self, session: Session) -> None:
        """Count the session's latest run against its procedure, behind the commit gate."""
        status = session.state.get(EXECUTION_STATUS_STATE_KEY)
        skill_id = session.state.get(SKILL_ID_STATE_KEY)
        events = _run_events(session)
        if status not in ("succeeded", "failed") or not skill_id or not events:
            return
        invocation_id = events[-1].invocation_id
        if invocation_id in self._committed_invocations:
            return
        task_signature = f"{skill_id}:{','.join(_param_names(events))}"
        now = datetime.now(UTC)
        table = self._table
        await self._ensure_table()
        async with self._engine.begin() as conn:
            if status == "succeeded":
                steps = _tool_steps(events)
                required_tools = sorted(set(steps))
                insert = sqlite_insert if self._is_sqlite else postgresql_insert
                statement = insert(table).values(
                    id=uuid.uuid4(),
                    role=session.app_name,
                    task_signature=task_signature,
                    steps=steps,
                    successes=1,
                    failures=0,
                    required_tools=required_tools,
                    updated_at=now,
                )
                await conn.execute(
                    statement.on_conflict_do_update(
                        index_elements=[table.c.role, table.c.task_signature],
                        set_={
                            "steps": steps,
                            "required_tools": required_tools,
                            "successes": table.c.successes + 1,
                            "updated_at": now,
                        },
                    )
                )
            else:
                await conn.execute(
                    update(table)
                    .where(
                        table.c.role == session.app_name,
                        table.c.task_signature == task_signature,
                    )
                    .values(failures=table.c.failures + 1, updated_at=now)
                )
        self._committed_invocations[invocation_id] = None
        while len(self._committed_invocations) > _COMMITTED_INVOCATIONS_MAX:
            self._committed_invocations.popitem(last=False)
        logger.debug(f"Counted a {status} run of '{task_signature}' for role '{session.app_name}'")

    async def search_memory(
        self, *, app_name: str, user_id: str, query: str
    ) -> SearchMemoryResponse:
        """Return the role's top procedures whose required tools the calling agent has.

        Procedures are shared per role, so ``user_id`` and ``query`` do not narrow the result.
        """
        await self._ensure_table()
        table = self._table
        async with self._engine.connect() as conn:
            rows = (await conn.execute(select(table).where(table.c.role == app_name))).all()
        usable = [row for row in rows if set(row.required_tools) <= self._tools]
        usable.sort(key=lambda row: _score(row.successes, row.failures), reverse=True)
        return SearchMemoryResponse(memories=[_memory_entry(row) for row in usable[:SEARCH_LIMIT]])

    async def add_memory(
        self,
        *,
        app_name: str,
        user_id: str,
        memories: Sequence[MemoryEntry],
        custom_metadata: Mapping[str, object] | None = None,
    ) -> None:
        """Agents never write facts to memory."""
        raise NotImplementedError("PrometheusMemoryService stores procedures only")


def _memory_entry(row: Any) -> MemoryEntry:
    procedure = {
        "task_signature": row.task_signature,
        "steps": row.steps,
        "required_tools": row.required_tools,
        "successes": row.successes,
        "failures": row.failures,
    }
    return MemoryEntry(
        id=str(row.id),
        author=row.role,
        timestamp=row.updated_at.isoformat(),
        content=types.Content(role="model", parts=[types.Part(text=json.dumps(procedure))]),
        custom_metadata=procedure,
    )
