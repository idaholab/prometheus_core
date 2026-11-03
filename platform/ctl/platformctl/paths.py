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

"""Where things are.

Two paths, never derived from the current directory: the platform root (from this
tool's own location) and, separately, the agent folder being acted on. Nothing
assumes an agent is under `platform/agents/`
(plans/platformctl/design.md, "Agents in other repositories").
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# platform/ctl/platformctl/paths.py -> platform/
PLATFORM_ROOT = Path(__file__).resolve().parents[2]
"""The platform folder, found from this file's location and never from the current directory."""


@dataclass(frozen=True)
class Paths:
    """The two folders the tool knows: the platform it belongs to and the agent folder it acts on."""

    root: Path
    """The platform folder."""
    agent: Path | None = None
    """The agent folder being acted on, or None."""

    @classmethod
    def default(cls, agent: str | Path | None = None) -> Paths:
        """The paths for this run, with an optional agent folder resolved to an absolute path."""
        return cls(PLATFORM_ROOT, Path(agent).resolve() if agent else None)

    @property
    def env(self) -> Path:
        """The platform's `.env`."""
        return self.root / ".env"

    @property
    def env_example(self) -> Path:
        """The platform's `.env.example`."""
        return self.root / ".env.example"

    @property
    def compose_base(self) -> Path:
        """The base `docker-compose.yml`."""
        return self.root / "docker-compose.yml"

    @property
    def entry_file(self) -> Path:
        """The generated compose entry file."""
        return self.root / "docker-compose.platform.yml"

    @property
    def platform_env(self) -> Path:
        """The generated `.platform.env` of derived values."""
        return self.root / ".platform.env"

    @property
    def agents_file(self) -> Path:
        """The generated `docker-compose.agents.yml`."""
        return self.root / "docker-compose.agents.yml"

    @property
    def override_file(self) -> Path:
        """The user's optional `docker-compose.override.yml`."""
        return self.root / "docker-compose.override.yml"

    @property
    def shim(self) -> Path:
        """The `platformctl` shim."""
        return self.root / "platformctl"

    @property
    def sdk(self) -> Path:
        """The repository's `sdk/` folder, next to `platform/`."""
        return self.root.parent / "sdk"

    @property
    def llm_configs(self) -> Path:
        """The SDK's LLM profiles, one YAML each."""
        return self.sdk / "prometheus_api" / "llm_configs"
