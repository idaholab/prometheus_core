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

"""The ``orchestration`` package must stay liftable into the SDK.

It may import the standard library, third-party packages, ``prometheus_api``
and itself, but no client-agent module and no Valkey client.
"""

import ast
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "orchestration"
FORBIDDEN = {
    "orchestrator",
    "conversation_store",
    "task_graph",
    "workflow_library",
    "runtime",
    "tool_discovery",
    "capability_cache",
    "file_upload_handler",
    "redis",
}


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_orchestration_package_imports_no_client_agent_module() -> None:
    sources = sorted(PACKAGE_DIR.glob("**/*.py"))
    assert sources, "orchestration package not found"
    offenders = {str(path.relative_to(PACKAGE_DIR)): sorted(_imported_roots(path) & FORBIDDEN) for path in sources}
    assert {name: roots for name, roots in offenders.items() if roots} == {}
