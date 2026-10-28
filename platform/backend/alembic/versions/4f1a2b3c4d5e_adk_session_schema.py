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

"""adk session schema

Revision ID: 4f1a2b3c4d5e
Revises: 32cad357c0e5
Create Date: 2026-10-27 12:00:00.000000

The ``adk`` role owns the ``adk`` schema only. ADK's DatabaseSessionService creates its
session tables there on first use (``search_path = adk``); PrometheusMemoryService uses
``adk.procedures``. The role gets no grant on the admin-plane tables in ``public``.

"""

import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "4f1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = "32cad357c0e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    if conn.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'adk'")).first() is None:
        password = (os.getenv("ADK_DB_PASSWORD") or "").strip()
        if not password:
            raise RuntimeError("ADK_DB_PASSWORD must be set to create the adk database role")
        # CREATE ROLE takes no bind parameters, so the server quotes the password (%L).
        create_role = conn.execute(
            sa.text("SELECT format('CREATE ROLE adk LOGIN PASSWORD %L', CAST(:password AS text))"),
            {"password": password},
        ).scalar_one()
        conn.exec_driver_sql(create_role)
    op.execute("CREATE SCHEMA IF NOT EXISTS adk AUTHORIZATION adk")
    op.execute("ALTER ROLE adk SET search_path = adk")
    op.execute("REVOKE ALL ON SCHEMA public FROM adk")
    op.create_table(
        "procedures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("task_signature", sa.Text(), nullable=False),
        sa.Column("steps", postgresql.JSONB(), nullable=False),
        sa.Column("successes", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("failures", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("required_tools", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role", "task_signature"),
        schema="adk",
    )
    op.execute("ALTER TABLE adk.procedures OWNER TO adk")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("procedures", schema="adk")
    # CASCADE: the session tables ADK created on first use live in this schema too.
    op.execute("DROP SCHEMA IF EXISTS adk CASCADE")
    op.execute("DROP ROLE IF EXISTS adk")
