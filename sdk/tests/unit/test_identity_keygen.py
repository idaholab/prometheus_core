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

"""Unit tests for prometheus_api.agent.identity_keygen."""

from __future__ import annotations

import stat

import pytest

from prometheus_api.agent.identity_keygen import generate_keypair, main


def test_generate_keypair_returns_pem_strings():
    private_pem, public_pem = generate_keypair(key_size=2048)
    assert private_pem.startswith("-----BEGIN PRIVATE KEY-----")
    assert public_pem.startswith("-----BEGIN PUBLIC KEY-----")


def test_generate_keypair_rejects_weak_key_size():
    with pytest.raises(ValueError, match="2048"):
        generate_keypair(key_size=1024)


def test_generate_keypair_produces_a_matching_pair():
    """The public key derived from the private key must match the one returned."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    private_pem, public_pem = generate_keypair(key_size=2048)
    private_key = load_pem_private_key(private_pem.encode(), password=None)
    derived_public_pem = (
        private_key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    assert derived_public_pem == public_pem


def test_generate_keypair_default_size_is_4096():
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    private_pem, _ = generate_keypair()
    private_key = load_pem_private_key(private_pem.encode(), password=None)
    assert private_key.key_size == 4096


def test_main_prints_env_snippet_to_stdout(capsys):
    rc = main(["--key-size", "2048"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "USER_IDENTITY_PRIVATE_KEY=" in out
    assert "USER_IDENTITY_PUBLIC_KEY=" in out


def test_main_writes_key_files(tmp_path):
    out_dir = tmp_path / "keys"
    rc = main(["--key-size", "2048", "--out-dir", str(out_dir)])
    assert rc == 0

    private_path = out_dir / "identity_private.pem"
    public_path = out_dir / "identity_public.pem"
    assert private_path.is_file()
    assert public_path.is_file()
    assert private_path.read_text().startswith("-----BEGIN PRIVATE KEY-----")
    assert public_path.read_text().startswith("-----BEGIN PUBLIC KEY-----")


def test_main_private_key_file_is_owner_only(tmp_path):
    out_dir = tmp_path / "keys"
    main(["--key-size", "2048", "--out-dir", str(out_dir)])

    mode = stat.S_IMODE((out_dir / "identity_private.pem").stat().st_mode)
    assert mode == stat.S_IRUSR | stat.S_IWUSR


def test_main_refuses_to_overwrite_without_force(tmp_path):
    out_dir = tmp_path / "keys"
    assert main(["--key-size", "2048", "--out-dir", str(out_dir)]) == 0
    assert main(["--key-size", "2048", "--out-dir", str(out_dir)]) == 1


def test_main_overwrites_with_force(tmp_path):
    out_dir = tmp_path / "keys"
    assert main(["--key-size", "2048", "--out-dir", str(out_dir)]) == 0
    assert main(["--key-size", "2048", "--out-dir", str(out_dir), "--force"]) == 0
