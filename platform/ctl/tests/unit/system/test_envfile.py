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
    """Quotes are stripped, `$` is not expanded, and comments, `export`, a BOM and CRLF are handled.

    Covers REQ-002-09.
    """
    text = "\ufeff# comment\nA=1\nexport B=two words # trailing\nC=\"quoted $HOME\"\nD='single'\nE=\n\nF=x\r\n"
    assert envfile.parse(text) == {"A": "1", "B": "two words", "C": "quoted $HOME", "D": "single", "E": "", "F": "x"}


def test_parse_multiline_and_escapes():
    """Multi-line values and escaped quotes in double quotes parse.

    Covers REQ-002-09.
    """
    text = 'KEY="line1\nline2"\nQ="say \\"hi\\"\\nnext"\nS=\'it\'\n'
    parsed = envfile.parse(text)
    assert parsed["KEY"] == "line1\nline2"
    assert parsed["Q"] == 'say "hi"\nnext'
    assert parsed["S"] == "it"


@pytest.mark.parametrize("text", ["not a pair\n", "1BAD=x\n", "A=1\n=x\n"])
def test_parse_error_names_the_line_not_its_text(text):
    """Parse error names the line not its text.

    Covers REQ-002-10, BEH-002-03.
    """
    with pytest.raises(envfile.EnvFileError) as info:
        envfile.parse(text)
    assert "line" in str(info.value)
    assert "pair" not in str(info.value).split("line", 1)[1].split(":", 1)[0]


def test_parse_unterminated_quote_hides_the_value():
    """Parse unterminated quote hides the value.

    Covers REQ-002-10, BEH-002-03.
    """
    with pytest.raises(envfile.EnvFileError) as info:
        envfile.parse('SECRET="abc\n')
    assert "abc" not in str(info.value)


def test_unquote_unterminated_single_line():
    """An unterminated quote is an error."""
    with pytest.raises(envfile.EnvFileError, match="unterminated"):
        envfile._unquote('"abc', 3)


def test_escaped_quote_then_unterminated():
    """A quote that is only escaped doesn't close the value."""
    with pytest.raises(envfile.EnvFileError, match="unterminated"):
        envfile._unquote('"abc\\"', 1)


def test_read(tmp_path: Path):
    """`read` parses the file at a path."""
    path = tmp_path / ".env"
    path.write_text("A=1\n")
    assert envfile.read(path) == {"A": "1"}


def test_read_a_file_that_is_not_utf8_hides_the_offset(tmp_path: Path):
    """A decode error names the offset of the bad byte, so the error doesn't carry it.

    Covers REQ-002-10.
    """
    path = tmp_path / ".env"
    path.write_bytes(b"A=\xff\xfe\n")
    with pytest.raises(envfile.EnvFileError, match="not valid UTF-8") as info:
        envfile.read(path)
    assert "position" not in str(info.value) and "0xff" not in str(info.value)


def test_read_a_file_that_cannot_be_read(tmp_path: Path, monkeypatch):
    """An unreadable file (a mode-000 `.env`, a folder) is an `EnvFileError`, not an `OSError`.

    Covers REQ-002-10.
    """

    def refuse(self, *args, **kwargs):
        """Fail like a file without read permission."""
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "read_text", refuse)
    with pytest.raises(envfile.EnvFileError, match=r"can't be read \(Permission denied\)"):
        envfile.read(tmp_path / ".env")


def test_read_an_oserror_without_a_message(tmp_path: Path, monkeypatch):
    """An `OSError` with no `strerror` is named by its type."""

    def refuse(self, *args, **kwargs):
        """Fail with a bare OSError."""
        raise OSError

    monkeypatch.setattr(Path, "read_text", refuse)
    with pytest.raises(envfile.EnvFileError, match=r"can't be read \(OSError\)"):
        envfile.read(tmp_path / ".env")


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
    """Values are quoted only when they need it.

    Covers REQ-002-14.
    """
    assert envfile._format(value) == expected


def test_formatted_values_round_trip():
    """Whatever `update_text` writes, `parse` reads back unchanged.

    Covers REQ-002-14.
    """
    values = {"A": "two words", "B": "it's", "C": "a\nb", "D": 'say "x"', "E": "has$dollar", "F": ""}
    text = envfile.update_text("", values)
    assert envfile.parse(text) == values


def test_update_text_sets_in_place_and_appends():
    """Update text sets in place and appends.

    Covers REQ-002-14.
    """
    text = "# head\nA=1\nexport B=2\n#C=old\nA_OTHER=x\n"
    updated = envfile.update_text(text, {"A": "9", "B": "8", "C": "new"})
    assert updated == "# head\nA=9\nB=8\n#C=old\nA_OTHER=x\nC=new\n"


def test_update_text_without_trailing_newline():
    """Update text without trailing newline."""
    assert envfile.update_text("A=1", {"B": "2"}) == "A=1\nB=2\n"


def test_update_text_from_nothing():
    """Updating empty text writes the keys."""
    assert envfile.update_text("", {"A": "1"}) == "A=1\n"


def test_write_atomic_new_file_is_0600(tmp_path: Path):
    """Write atomic new file is 0600.

    Covers REQ-002-11.
    """
    path = tmp_path / ".env"
    envfile.write_atomic(path, "A=1\n")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text() == "A=1\n"


def test_write_atomic_keeps_mode(tmp_path: Path):
    """Rewriting a file keeps its mode and leaves no temporary file.

    Covers REQ-002-11, REQ-002-12.
    """
    path = tmp_path / ".env"
    path.write_text("A=1\n")
    path.chmod(0o640)
    envfile.write_atomic(path, "A=2\n")
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert [p.name for p in tmp_path.iterdir()] == [".env"]


def test_write_atomic_writes_through_a_symlink(tmp_path: Path):
    """Write atomic writes through a symlink.

    Covers REQ-002-13.
    """
    real = tmp_path / "real.env"
    real.write_text("A=1\n")
    link = tmp_path / ".env"
    link.symlink_to(real)
    envfile.write_atomic(link, "A=2\n")
    assert link.is_symlink()
    assert real.read_text() == "A=2\n"


def test_write_atomic_cleans_up_when_the_replace_fails(tmp_path: Path, monkeypatch):
    """Write atomic cleans up when the replace fails.

    Covers REQ-002-12.
    """
    path = tmp_path / ".env"

    def boom(*_):
        """Fail like a full disk."""
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        envfile.write_atomic(path, "A=1\n")
    assert list(tmp_path.iterdir()) == []


def test_update_creates_then_edits(tmp_path: Path):
    """`update` creates the file, then edits it in place.

    Covers REQ-002-14.
    """
    path = tmp_path / ".env"
    envfile.update(path, {"A": "1"})
    envfile.update(path, {"A": "2", "B": "3"})
    assert envfile.read(path) == {"A": "2", "B": "3"}


def test_update_text_with_every_key_already_present_appends_nothing():
    """Update text with every key already present appends nothing."""
    assert envfile.update_text("A=1\nB=2\n", {"A": "3"}) == "A=3\nB=2\n"


def test_write_atomic_failure_after_the_temp_file_is_gone_is_still_clean(tmp_path: Path, monkeypatch):
    """Write atomic failure after the temp file is gone is still clean.

    Covers REQ-002-12.
    """
    path = tmp_path / ".env"
    real_unlink = os.unlink

    def replace_then_fail(src, dst):
        """Delete the temporary file, then fail."""
        real_unlink(src)  # the temp file vanished before cleanup
        raise OSError("gone")

    monkeypatch.setattr(os, "replace", replace_then_fail)
    with pytest.raises(OSError, match="gone"):
        envfile.write_atomic(path, "A=1\n")
