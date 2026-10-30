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

from __future__ import annotations

import pytest

from platformctl.targets import SUPPORTED, check_name
from platformctl.targets.base import UnsupportedError


def test_check_name():
    assert SUPPORTED == ("compose",)
    assert check_name("compose") == "compose"
    with pytest.raises(UnsupportedError, match="k3d` is not supported yet"):
        check_name("k3d")
    with pytest.raises(UnsupportedError, match="unknown target `nope`"):
        check_name("nope")
