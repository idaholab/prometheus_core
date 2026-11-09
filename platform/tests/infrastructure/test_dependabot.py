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

"""Static checks of .github/dependabot.yml against the repository."""

import subprocess
from fnmatch import fnmatch
from pathlib import Path

import pytest
import yaml


@pytest.fixture(scope="module")
def repo_root(project_root: Path) -> Path:
    """The repository root, one level above platform/."""
    return project_root.parent


@pytest.fixture(scope="module")
def dependabot_config(repo_root: Path) -> dict:
    """.github/dependabot.yml, parsed."""
    return yaml.safe_load((repo_root / ".github" / "dependabot.yml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dependabot_uv_dirs(dependabot_config: dict) -> list[str]:
    """Every directory listed in a uv entry of dependabot.yml, in order."""
    dirs = []
    for update in dependabot_config["updates"]:
        if update["package-ecosystem"] == "uv":
            dirs += update.get("directories", [update.get("directory")])
    return dirs


def test_dependabot_lists_every_uv_lock(repo_root: Path, dependabot_uv_dirs: list[str]):
    """Each tracked uv.lock's directory is in exactly one uv entry, and nothing else is."""
    out = subprocess.run(
        ["git", "ls-files", "--", "uv.lock", "*/uv.lock"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    lock_dirs = {"/" + str(Path(name).parent).removeprefix(".") for name in out.splitlines()}
    assert lock_dirs, "No tracked uv.lock files found"

    duplicates = sorted({d for d in dependabot_uv_dirs if dependabot_uv_dirs.count(d) > 1})
    assert not duplicates, f"Listed more than once in dependabot.yml: {duplicates}"
    missing = sorted(lock_dirs - set(dependabot_uv_dirs))
    assert not missing, f"Has a uv.lock but isn't in dependabot.yml's uv entries: {missing}"
    stale = sorted(set(dependabot_uv_dirs) - lock_dirs)
    assert not stale, f"In dependabot.yml's uv entries but has no uv.lock: {stale}"


def test_dependabot_exclude_paths_match_a_tracked_file(repo_root: Path, dependabot_config: dict):
    """Each exclude-paths pattern excludes a file under its entry's directories.

    GitHub's documentation says the patterns are relative to the entry's directory,
    but Dependabot matches them against the path from the repository root. A pattern
    written the documented way, such as "docker-compose.deeplynx.yml" for the
    "/platform" directory, matches nothing, and Dependabot goes on to update the file
    it was meant to skip. Written as "**/docker-compose.deeplynx.yml" it works under
    both readings.
    """
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=repo_root, check=True, capture_output=True, text=True
    ).stdout.splitlines()

    checked = 0
    for update in dependabot_config["updates"]:
        patterns = update.get("exclude-paths", [])
        dirs = update.get("directories", [update.get("directory")])
        for pattern in patterns:
            # fnmatch's "*" also crosses "/", looser than Dependabot's matcher, so
            # a pass here is necessary but not sufficient; the plain-filename
            # mistake this guards against fails it
            matches = [
                name
                for name in tracked
                if fnmatch(name, pattern.lstrip("/")) and any(name.startswith(d.strip("/") + "/") for d in dirs)
            ]
            assert matches, (
                f"exclude-paths '{pattern}' of the {update['package-ecosystem']} entry for "
                f"{dirs} matches no tracked file under them. Dependabot matches it against "
                f"the path from the repository root, so write it as '**/<name>' or "
                f"'<directory>/<name>'"
            )
            checked += 1
    assert checked, "No exclude-paths found in dependabot.yml"
