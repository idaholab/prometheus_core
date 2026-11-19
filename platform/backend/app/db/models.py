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

"""ORM models for the admin plane: local + auto-provisioned OIDC users, OIDC
provider configuration, and RS256 signing keys. Also the platform's
organization/project/group/RBAC tables (identity-plane schema below these).

Alembic migrations under ``backend/alembic/`` are generated from these models
and are the source of truth for the deployed schema; tests instead call
``app.db.create_all_for_tests()`` against an in-memory SQLite engine and skip
Alembic entirely (see ``tests/conftest.py``).

Secrets at rest: ``OidcProvider.client_secret_encrypted`` and
``SigningKey.private_key_encrypted`` are Fernet-encrypted blobs (see
``app/crypto.py``) -- the plaintext never round-trips through these column
names; encrypt/decrypt at the call site, not in the model.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    JSON,
    LargeBinary,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    # Uuid (not the Postgres-specific dialect type) so the same model works
    # against both admin-db (Postgres, production) and the in-memory SQLite
    # engine tests use (see app/db.py::create_all_for_tests, tests/conftest.py).
    return mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)


class User(Base):
    """A platform account -- created locally by an admin, via the first-run
    setup wizard, or auto-provisioned on a successful OIDC login.

    Local accounts: ``provider="credentials"``, ``password_hash`` set,
    ``external_subject`` NULL. OIDC accounts: ``provider`` is the owning
    ``OidcProvider.provider_id``, ``password_hash`` NULL, ``external_subject``
    is the IdP's ``sub`` claim. The unique constraint on
    ``(provider, external_subject)`` is what makes OIDC login idempotent --
    a returning user resolves to the same row every time.
    """

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("provider", "external_subject", name="uq_users_provider_subject"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    provider: Mapped[str] = mapped_column(String(255), nullable=False, default="credentials")
    external_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OidcProvider(Base):
    """Admin-configured generic-OIDC identity provider.

    ``provider_id`` is the URL slug used in ``GET /api/auth/login/{provider_id}``
    and ``GET /api/auth/callback/{provider_id}``, and is what gets stored in
    ``User.provider`` for accounts created through this provider. Renaming it
    after users exist would orphan their ``User.provider`` value -- the admin
    UI should treat it as immutable after creation.
    """

    __tablename__ = "oidc_providers"

    id: Mapped[uuid.UUID] = _uuid_pk()
    provider_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    issuer_url: Mapped[str] = mapped_column(String(512), nullable=False)
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    client_secret_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    scopes: Mapped[str] = mapped_column(String(512), nullable=False, default="openid profile email")
    default_role: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Organization(Base):
    """A tenant: the top-level grouping of users, projects, and groups, tied
    to the OIDC provider its members authenticate through.

    ``classification_ceiling_id`` (DBML FK to ``classification_levels``) is
    omitted -- that table is not implemented yet; see the schema plan."""

    __tablename__ = "organizations"
    __table_args__ = (UniqueConstraint("deeplynx_organization_id", name="uq_organizations_deeplynx_organization_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    oidc_provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("oidc_providers.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(String(3000), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    deeplynx_organization_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrganizationUser(Base):
    """Membership: a ``User`` belongs to an ``Organization``. Composite PK --
    no synthetic ``id`` column, matching the DBML."""

    __tablename__ = "organization_users"
    __table_args__ = (PrimaryKeyConstraint("user_id", "organization_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Project(Base):
    """A project within an ``Organization``.

    ``classification_level_id`` (DBML FK to ``classification_levels``) is
    omitted -- that table is not implemented yet; see the schema plan."""

    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_projects_organization_name"),
        UniqueConstraint("deeplynx_project_id", name="uq_projects_deeplynx_project_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(String(3000), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    deeplynx_project_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Group(Base):
    """A named group of users within an ``Organization``, grantable roles via
    ``ProjectGroupRole``."""

    __tablename__ = "groups"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_groups_organization_name"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GroupUser(Base):
    """Membership: a ``Group`` contains an ``OrganizationUser`` (i.e. a user
    already confirmed to belong to that group's organization). Composite PK
    and composite FK, matching the DBML's verbose column names verbatim."""

    __tablename__ = "group_users"
    __table_args__ = (
        PrimaryKeyConstraint("group_id", "organization_users_organization_id", "organization_users_user_id"),
        ForeignKeyConstraint(
            ["organization_users_user_id", "organization_users_organization_id"],
            ["organization_users.user_id", "organization_users.organization_id"],
        ),
        Index(
            "ix_group_users_org_user",
            "organization_users_user_id",
            "organization_users_organization_id",
        ),
    )

    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id"), nullable=False)
    organization_users_organization_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False)
    organization_users_user_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Resource(Base):
    """A kind of thing RBAC permissions are granted against (e.g. "project",
    "dataset"). Paired with an ``Action`` via ``Permission`` to form a grantable
    permission."""

    __tablename__ = "resources"
    __table_args__ = (UniqueConstraint("name", name="uq_resources_name"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Action(Base):
    """An operation that can be performed on a ``Resource`` (e.g. "read",
    "write"). Paired with a ``Resource`` via ``Permission`` to form a grantable
    permission."""

    __tablename__ = "actions"
    __table_args__ = (UniqueConstraint("name", name="uq_actions_name"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Permission(Base):
    """A grantable permission: performing a given ``Action`` on a given
    ``Resource``. Granted to ``Role``s via ``RolePermission``."""

    __tablename__ = "permissions"
    __table_args__ = (UniqueConstraint("resource_id", "action_id", name="uq_permissions_resource_action"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    action_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actions.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Role(Base):
    """A named, grantable bundle of ``Permission``s, scoped to either an
    ``Organization`` or a ``Project`` (or neither, for a platform-wide role).

    The uniqueness guarantee on ``(organization_id, project_id, name)`` is
    weaker than it looks: Postgres treats NULLs as distinct, so this alone
    does not prevent duplicate platform-wide role names (both scope columns
    NULL). Matches the DBML's own index as specified; not strengthened with
    partial indexes."""

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("organization_id", "project_id", "name", name="uq_roles_scope_name"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(String(3000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RolePermission(Base):
    """Grants a ``Permission`` to a ``Role``."""

    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_id", name="uq_role_permissions_role_permission"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"), nullable=False)
    permission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("permissions.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrganizationUserRole(Base):
    """Grants a ``Role`` to an ``OrganizationUser`` (a user confirmed to
    belong to that role's organization). Composite PK and composite FK,
    matching the DBML's verbose column names verbatim (same pattern as
    ``GroupUser``)."""

    __tablename__ = "organization_user_roles"
    __table_args__ = (
        PrimaryKeyConstraint("role_id", "organization_users_organization_id", "organization_users_user_id"),
        ForeignKeyConstraint(
            ["organization_users_user_id", "organization_users_organization_id"],
            ["organization_users.user_id", "organization_users.organization_id"],
        ),
        Index(
            "ix_organization_user_roles_org_user",
            "organization_users_user_id",
            "organization_users_organization_id",
        ),
    )

    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"), nullable=False)
    organization_users_organization_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False)
    organization_users_user_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectUserRole(Base):
    """Grants a ``Role`` to a ``User`` within a ``Project``. Composite PK,
    matching the DBML."""

    __tablename__ = "project_user_roles"
    __table_args__ = (PrimaryKeyConstraint("project_id", "user_id", "role_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectGroupRole(Base):
    """Grants a ``Role`` to a ``Group`` within a ``Project``. Composite PK,
    matching the DBML."""

    __tablename__ = "project_group_roles"
    __table_args__ = (PrimaryKeyConstraint("project_id", "group_id", "role_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id"), nullable=False, index=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SigningKey(Base):
    """An RS256 keypair for the multi-user identity plane (see
    ``prometheus_api.agent.identity`` and ``app/identity.py``).

    At most one row has ``is_active=True`` at a time -- that is the key
    ``mint_for_user`` signs new tokens with. Retired keys (``retired_at`` set)
    stay in the table and keep appearing in ``GET /.well-known/jwks.json``
    until an admin decides they're safe to delete, so tokens minted before a
    rotation remain verifiable until they naturally expire.
    """

    __tablename__ = "signing_keys"

    id: Mapped[uuid.UUID] = _uuid_pk()
    kid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    private_key_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    public_key_pem: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
