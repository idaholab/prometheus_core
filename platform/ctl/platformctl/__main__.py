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

"""Check the Python version and the user, then hand over to the CLI.

This module must parse on Python 3.9 (no 3.10+ syntax, and `cli` is imported
only after the version check), so even a wrong interpreter gets a clear message
instead of a SyntaxError.
"""

import os
import sys

MIN_PYTHON = (3, 10)


def main(argv=None):
    if sys.version_info < MIN_PYTHON:
        need = "{}.{}".format(*MIN_PYTHON)
        have = "{}.{}".format(*sys.version_info[:2])
        sys.stderr.write(
            f"platformctl needs Python {need} or newer, but this is Python {have}.\n"
            "Run it through ./platformctl, which finds a newer Python, or set PLATFORMCTL_PYTHON.\n"
        )
        return 1
    if os.environ.get("SUDO_USER"):
        sys.stderr.write(
            "platformctl: don't run it with sudo. It would leave .env and the generated files owned by root.\n"
            "Run it as yourself; if Docker needs the docker group, see ./platformctl doctor.\n"
        )
        return 1

    from platformctl import cli

    return cli.main(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    sys.exit(main())
