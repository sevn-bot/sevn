"""Test JSON Schema export matches checked-in schema."""

import json
from pathlib import Path

import jsonschema

from sevn.docs.about.model import export_json_schema


def find_schema_file():
    """Find about-docs.schema.json by walking up from test file."""
    current = Path(__file__).resolve()
    # Walk up from tests/ to repo root
    for parent in current.parents:
        schema_path = parent / "about-sevn.bot" / "_docsys" / "about-docs.schema.json"
        if schema_path.exists():
            return schema_path
    raise FileNotFoundError("about-docs.schema.json not found; expected at about-sevn.bot/_docsys/")


def test_export_matches_checked_in_schema():
    schema_file = find_schema_file()
    with open(schema_file) as f:
        checked_in = json.load(f)
    exported = export_json_schema()
    assert exported == checked_in, (
        f"Exported schema does not match {schema_file}. Run `make about-docs-schema` to regenerate."
    )


def test_exported_schema_is_meta_valid():
    exported = export_json_schema()
    jsonschema.Draft202012Validator.check_schema(exported)
    # If no exception, the schema is valid per JSON Schema spec.
