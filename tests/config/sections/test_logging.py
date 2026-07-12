"""Logging section parse-time cross-field validators."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sevn.config.workspace_config import parse_workspace_config


def test_logging_r2_archive_mode_requires_bucket_ref_ok() -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            "logging": {
                "archive_mode": "r2",
                "cloud": {"r2": {"bucket_ref": "${SECRET:encrypted_file:logs.r2.bucket}"}},
            },
        },
    )
    assert cfg.logging is not None
    assert cfg.logging.archive_mode == "r2"
    assert cfg.logging.cloud is not None
    assert cfg.logging.cloud.r2 is not None


def test_logging_r2_archive_mode_missing_bucket_ref_fails() -> None:
    with pytest.raises(ValidationError, match=r"logging\.cloud\.r2\.bucket_ref"):
        parse_workspace_config(
            {
                "schema_version": 1,
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
                "logging": {"archive_mode": "r2"},
            },
        )


def test_logging_gcs_archive_mode_requires_bucket_ref_ok() -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            "logging": {
                "archive_mode": "gcs",
                "cloud": {"gcs": {"bucket_ref": "${SECRET:encrypted_file:logs.gcs.bucket}"}},
            },
        },
    )
    assert cfg.logging is not None
    assert cfg.logging.archive_mode == "gcs"


def test_logging_gcs_archive_mode_missing_bucket_ref_fails() -> None:
    with pytest.raises(ValidationError, match=r"logging\.cloud\.gcs\.bucket_ref"):
        parse_workspace_config(
            {
                "schema_version": 1,
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
                "logging": {"archive_mode": "gcs", "cloud": {"gcs": {}}},
            },
        )
