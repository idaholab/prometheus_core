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

import os
import stat
from pathlib import Path

import pytest

from platformctl.system import envfile


def test_parse_dotenv_rules():
    text = "\ufeff# comment\nA=1\nexport B=two words # trailing\nC=\"quoted $HOME\"\nD='single'\nE=\n\nF=x\r\n"
    assert envfile.parse(text) == {"A": "1", "B": "two words", "C": "quoted $HOME", "D": "single", "E": "", "F": "x"}


def test_parse_multiline_and_escapes():
    text = 'KEY="line1\nline2"\nQ="say \\"hi\\"\\nnext"\nS=\'it\'\n'
    parsed = envfile.parse(text)
    assert parsed["KEY"] == "line1\nline2"
    assert parsed["Q"] == 'say "hi"\nnext'
    assert parsed["S"] == "it"


@pytest.mark.parametrize("text", ["not a pair\n", "1BAD=x\n", "A=1\n=x\n"])
def test_parse_error_names_the_line_not_its_text(text):
    with pytest.raises(envfile.EnvFileError) as info:
        envfile.parse(text)
    assert "line" in str(info.value)
    assert "pair" not in str(info.value).split("line", 1)[1].split(":", 1)[0]


def test_parse_unterminated_quote_hides_the_value():
    with pytest.raises(envfile.EnvFileError) as info:
        envfile.parse('SECRET="abc\n')
    assert "abc" not in str(info.value)


def test_unquote_unterminated_single_line():
    with pytest.raises(envfile.EnvFileError, match="unterminated"):
        envfile._unquote('"abc', 3)


def test_escaped_quote_then_unterminated():
    with pytest.raises(envfile.EnvFileError, match="unterminated"):
        envfile._unquote('"abc\\"', 1)


def test_read(tmp_path: Path):
    path = tmp_path / ".env"
    path.write_text("A=1\n")
    assert envfile.read(path) == {"A": "1"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", ""),
        ("plain-1.2/x", "plain-1.2/x"),
        ("two words", "'two words'"),
        ("it's", '"it\'s"'),
        ("a\nb", '"a\\nb"'),
        ('say "x"', "'say \"x\"'"),
        ("has$dollar", "'has$dollar'"),
        ("a;b", "a;b"),
    ],
)
def test_format(value, expected):
    assert envfile._format(value) == expected


def test_formatted_values_round_trip():
    values = {"A": "two words", "B": "it's", "C": "a\nb", "D": 'say "x"', "E": "has$dollar", "F": ""}
    text = envfile.update_text("", values)
    assert envfile.parse(text) == values


def test_update_text_sets_in_place_and_appends():
    text = "# head\nA=1\nexport B=2\n#C=old\nA_OTHER=x\n"
    updated = envfile.update_text(text, {"A": "9", "B": "8", "C": "new"})
    assert updated == "# head\nA=9\nB=8\n#C=old\nA_OTHER=x\nC=new\n"


def test_update_text_without_trailing_newline():
    assert envfile.update_text("A=1", {"B": "2"}) == "A=1\nB=2\n"


def test_update_text_from_nothing():
    assert envfile.update_text("", {"A": "1"}) == "A=1\n"


def test_write_atomic_new_file_is_0600(tmp_path: Path):
    path = tmp_path / ".env"
    envfile.write_atomic(path, "A=1\n")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text() == "A=1\n"


def test_write_atomic_keeps_mode(tmp_path: Path):
    path = tmp_path / ".env"
    path.write_text("A=1\n")
    path.chmod(0o640)
    envfile.write_atomic(path, "A=2\n")
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert [p.name for p in tmp_path.iterdir()] == [".env"]


def test_write_atomic_writes_through_a_symlink(tmp_path: Path):
    real = tmp_path / "real.env"
    real.write_text("A=1\n")
    link = tmp_path / ".env"
    link.symlink_to(real)
    envfile.write_atomic(link, "A=2\n")
    assert link.is_symlink()
    assert real.read_text() == "A=2\n"


def test_write_atomic_cleans_up_when_the_replace_fails(tmp_path: Path, monkeypatch):
    path = tmp_path / ".env"

    def boom(*_):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        envfile.write_atomic(path, "A=1\n")
    assert list(tmp_path.iterdir()) == []


def test_update_creates_then_edits(tmp_path: Path):
    path = tmp_path / ".env"
    envfile.update(path, {"A": "1"})
    envfile.update(path, {"A": "2", "B": "3"})
    assert envfile.read(path) == {"A": "2", "B": "3"}


def test_update_text_with_every_key_already_present_appends_nothing():
    assert envfile.update_text("A=1\nB=2\n", {"A": "3"}) == "A=3\nB=2\n"


def test_write_atomic_failure_after_the_temp_file_is_gone_is_still_clean(tmp_path: Path, monkeypatch):
    path = tmp_path / ".env"
    real_unlink = os.unlink

    def replace_then_fail(src, dst):
        real_unlink(src)  # the temp file vanished before cleanup
        raise OSError("gone")

    monkeypatch.setattr(os, "replace", replace_then_fail)
    with pytest.raises(OSError, match="gone"):
        envfile.write_atomic(path, "A=1\n")
