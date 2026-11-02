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

"""The Context passed to actions: where speccheck runs, the config, the output and the environment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from speccheck import config as config_module
from speccheck import specs as specs_module
from speccheck.config import Config
from speccheck.output import Output
from speccheck.specs import SpecSet


@dataclass
class Context:
    """Everything an action needs."""

    cwd: Path
    """Where speccheck runs; relative paths on the command line and in messages are relative to it."""
    output: Output
    """Where to print."""
    env: Mapping[str, str]
    """The environment, for the CI context."""
    config_path: str | None = None
    """`--config`, or None to look for one."""
    _config: Config | None = field(default=None, repr=False)
    """The config, once loaded."""

    def config(self) -> Config:
        """The config, loaded on first use; a ConfigError if it is missing or invalid."""
        if self._config is None:
            self._config = config_module.load(config_module.find(self.config_path, self.cwd))
        return self._config

    def specs(self) -> SpecSet:
        """The config's spec folder, read and format-checked."""
        config = self.config()
        return specs_module.load(config.specs_dir, self.cwd, config.prefix, config.require_index)
