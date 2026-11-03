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
"""The oldest Python the tool runs on, as (major, minor)."""


def refuse(argv, code, message, hint):
    """Report a refusal before the tool can start: one JSON object with `--json`, else two lines on stderr.

    This runs on any Python from 3.9, so it uses only the standard library and no 3.10 syntax. The
    object has the same fields as every other `--json` failure (`design.md`, "JSON contract"); the
    platform's version is unknown here.
    """
    import json

    if "--json" in list(argv)[: list(argv).index("--") if "--" in argv else len(argv)]:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        body = {
            "schema_version": 1,
            "command": "",
            "ok": False,
            "platform": {"root": root, "project": "prometheus_platform", "version": "unknown"},
            "error": {"code": code, "message": message, "hint": hint, "check": ""},
        }
        sys.stdout.write(json.dumps(body, indent=2, sort_keys=True) + "\n")
    else:
        sys.stderr.write(f"{message}\n{hint}\n")
    return 1


def main(argv=None):
    """Check the Python version and the user, then hand over to `cli.main`; return the exit code."""
    argv = sys.argv[1:] if argv is None else argv
    if sys.version_info < MIN_PYTHON:
        need = "{}.{}".format(*MIN_PYTHON)
        have = "{}.{}".format(*sys.version_info[:2])
        return refuse(
            argv,
            "config_invalid",
            f"platformctl needs Python {need} or newer, but this is Python {have}.",
            "Run it through ./platformctl, which finds a newer Python, or set PLATFORMCTL_PYTHON.",
        )
    if os.environ.get("SUDO_USER"):
        return refuse(
            argv,
            "config_invalid",
            "platformctl: don't run it with sudo. It would leave .env and the generated files owned by root.",
            "Run it as yourself; if Docker needs the docker group, see ./platformctl doctor.",
        )

    from platformctl import cli

    return cli.main(argv)


if __name__ == "__main__":
    sys.exit(main())
