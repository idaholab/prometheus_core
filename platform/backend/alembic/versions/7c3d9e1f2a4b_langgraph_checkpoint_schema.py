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

"""langgraph checkpoint schema

Revision ID: 7c3d9e1f2a4b
Revises: 32cad357c0e5
Create Date: 2026-10-29 12:00:00.000000

The ``langgraph`` role owns the ``langgraph`` schema only. LangGraph's AsyncPostgresSaver
creates its checkpoint tables there on first use (``search_path = langgraph``). The role
gets nothing in ``public``: PUBLIC loses its default USAGE there, and ``admin``, the database
owner, keeps its access.

"""

import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7c3d9e1f2a4b"
down_revision: Union[str, Sequence[str], None] = "32cad357c0e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    if conn.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'langgraph'")).first() is None:
        password = (os.getenv("LANGGRAPH_DB_PASSWORD") or "").strip()
        if not password:
            raise RuntimeError("LANGGRAPH_DB_PASSWORD must be set to create the langgraph database role")
        # CREATE ROLE takes no bind parameters, so the server quotes the password (%L).
        create_role = conn.execute(
            sa.text("SELECT format('CREATE ROLE langgraph LOGIN PASSWORD %L', CAST(:password AS text))"),
            {"password": password},
        ).scalar_one()
        conn.exec_driver_sql(create_role)
    op.execute("CREATE SCHEMA IF NOT EXISTS langgraph AUTHORIZATION langgraph")
    op.execute("ALTER ROLE langgraph SET search_path = langgraph")
    # The role holds no direct privilege on public; postgres:16 gives it USAGE through PUBLIC.
    op.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")


def downgrade() -> None:
    """Downgrade schema."""
    # CASCADE: the checkpoint tables AsyncPostgresSaver created on first use live in this schema.
    op.execute("DROP SCHEMA IF EXISTS langgraph CASCADE")
    op.execute("GRANT USAGE ON SCHEMA public TO PUBLIC")
    op.execute("DROP ROLE IF EXISTS langgraph")
