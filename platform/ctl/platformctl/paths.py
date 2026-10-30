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


@dataclass(frozen=True)
class Paths:
    root: Path
    agent: Path | None = None

    @classmethod
    def default(cls, agent: str | Path | None = None) -> Paths:
        return cls(PLATFORM_ROOT, Path(agent).resolve() if agent else None)

    @property
    def env(self) -> Path:
        return self.root / ".env"

    @property
    def env_example(self) -> Path:
        return self.root / ".env.example"

    @property
    def compose_base(self) -> Path:
        return self.root / "docker-compose.yml"

    @property
    def entry_file(self) -> Path:
        return self.root / "docker-compose.platform.yml"

    @property
    def platform_env(self) -> Path:
        return self.root / ".platform.env"

    @property
    def agents_file(self) -> Path:
        return self.root / "docker-compose.agents.yml"

    @property
    def override_file(self) -> Path:
        return self.root / "docker-compose.override.yml"

    @property
    def shim(self) -> Path:
        return self.root / "platformctl"

    @property
    def sdk(self) -> Path:
        return self.root.parent / "sdk"
