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

"""FinalResult -> A2A wire format. The only shape translation between the
runtime core and the A2A executor."""

import json

from research_agent.core.events import FinalResult


def result_to_a2a_json(result: FinalResult) -> str:
    # Emit the same key set for every status so consumers can handle one stable
    # response shape.
    payload = result.model_dump(mode="json")
    payload["agent"] = "OSTI Research Agent"  # Preserve the public A2A field.
    return json.dumps(payload, indent=2, default=str)
