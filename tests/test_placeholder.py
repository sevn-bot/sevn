from __future__ import annotations


def test_import_sevn() -> None:
    """Importing the package must succeed."""
    import sevn

    assert sevn.__name__ == "sevn"
