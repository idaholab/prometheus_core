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

"""`python -m speccheck`."""

import sys

if __name__ == "__main__" and sys.version_info < (3, 10):
    # Checked before the imports below: on 3.9 they fail with "No module named 'tomli'"
    sys.exit(
        f"speccheck needs Python 3.10+; this is {sys.version_info[0]}.{sys.version_info[1]}. Try `uv tool install`"
    )

from speccheck.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
