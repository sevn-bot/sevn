"""Features section config tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sevn.config.workspace_config import parse_workspace_config


def test_second_brain_fetch_allow_domains_must_be_list() -> None:
    with pytest.raises(ValidationError):
        parse_workspace_config(
            {
                "schema_version": 1,
                "second_brain": {"enabled": True, "fetch": {"allow_domains": "not-a-list"}},
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            },
        )


def test_second_brain_paths_vault_accepts_relative_path() -> None:
    doc = parse_workspace_config(
        {
            "schema_version": 1,
            "gateway": {"token": "x"},
            "second_brain": {"paths": {"vault": "obsidian/alex_AI"}},
        },
    )
    assert doc.second_brain.paths.vault == "obsidian/alex_AI"


@pytest.mark.parametrize("vault", ["../escape", "/abs/path"])
def test_second_brain_paths_vault_rejects_invalid(vault: str) -> None:
    with pytest.raises(ValidationError):
        parse_workspace_config(
            {
                "schema_version": 1,
                "gateway": {"token": "x"},
                "second_brain": {"paths": {"vault": vault}},
            },
        )


def test_second_brain_paths_wiki_alias_read() -> None:
    doc = parse_workspace_config(
        {
            "schema_version": 1,
            "gateway": {"token": "x"},
            "second_brain": {"paths": {"wiki": "obsidian/from_wiki"}},
        },
    )
    assert doc.second_brain.paths.vault == "obsidian/from_wiki"
