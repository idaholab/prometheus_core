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

"""Coverage for the evaluation CLI's run dispatch and its rich-less report path."""

import json
import sys

from evals import __main__ as cli
from evals import run as eval_run


def _saved_report(tmp_path, complete):
    path = tmp_path / "report.json"
    path.write_text(json.dumps({
        "questions": 1, "engines": ["deepagent"], "complete": complete,
        "records": [{"id": "q1", "engine": "deepagent", "status": "completed",
                     "status_match": True, "provenance_ok": True}],
        "aggregate": {"deepagent": {"n": 1, "status_match": 1, "provenance_ok": 1}},
    }))
    return path


def test_report_without_rich_falls_back_to_plain_text_and_flags_partial(
    tmp_path, monkeypatch, capsys
):
    # A None entry in sys.modules makes `from evals.console import ...` raise ImportError.
    monkeypatch.setitem(sys.modules, "evals.console", None)

    assert cli.main(["report", str(_saved_report(tmp_path, complete=False))]) == 0

    out = capsys.readouterr().out
    assert "OSTI evaluation: 1 question(s), engines: deepagent" in out
    assert "Every question passed." in out
    assert "(This report is partial: the run did not finish.)" in out


def test_report_without_rich_omits_the_partial_note_for_a_complete_run(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setitem(sys.modules, "evals.console", None)

    assert cli.main(["report", str(_saved_report(tmp_path, complete=True))]) == 0

    out = capsys.readouterr().out
    assert "OSTI evaluation: 1 question(s)" in out and "partial" not in out


def test_run_command_forwards_the_remaining_arguments(monkeypatch):
    seen = []

    def fake_main(argv):
        seen.append(argv)
        return 7

    monkeypatch.setattr(eval_run, "main", fake_main)

    assert cli.main(["run", "--limit", "2", "--no-judge"]) == 7
    assert seen == [["--limit", "2", "--no-judge"]]
