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

"""What actions need from a place the platform runs."""

from __future__ import annotations

from abc import ABC, abstractmethod

# Capabilities a target may declare; an action needing one the target lacks fails clearly.
PASSTHROUGH = "passthrough"
"""Capability: run raw tool commands (`compose --`)."""
YOUR_AGENTS = "your_agents"
"""Capability: find and restart the developer's own agent containers."""
FOREGROUND = "foreground"
"""Capability: run in the foreground with the terminal."""


class UnsupportedError(RuntimeError):
    """The target can't do what the command asked."""


class Target(ABC):
    """A place the platform runs, and what actions can ask of it."""

    name: str = ""
    capabilities: frozenset[str] = frozenset()

    def require(self, capability: str, command: str) -> None:
        """Raise `UnsupportedError` unless the target has the capability the command needs."""
        if capability not in self.capabilities:
            raise UnsupportedError(f"`{command}` is not supported on target `{self.name}`")

    @abstractmethod
    def generate(self) -> dict[str, str]:
        """Write the generated files; return name -> path."""

    @abstractmethod
    def service_url(self, service: str) -> str | None:
        """The host URL for checks, or None when the service has no published port."""
