"""Payload contracts for spike S3.

W2.R removed the ``green after W2`` xfail markers. These cases run as ordinary
pytest tests. Payloads are JSON objects at ``spikes/0004-a2ui/payloads/<id>.json``
with camelCase A2UI v0.9 messages. ``p2-table-update`` also has a non-empty
``update`` list. ``sevn_catalog.json`` is a catalog document whose components
include ``sevn.SecretField``, ``sevn.ApprovalCard``, ``sevn.AssistCard``, and
``Table``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from a2ui.core.basic_catalog import BasicCatalog
from a2ui.core.catalog.catalog import Catalog
from a2ui.core.processing.message_processor import (
    MessageProcessor,
    MessageProcessorOptions,
)
from a2ui.core.validation import STRICT_VALIDATION

PAYLOAD_DIR = Path(__file__).resolve().parents[2] / "payloads"
PAYLOAD_IDS = (
    "p1-form",
    "p2-table-update",
    "p3-secret",
    "p4-approval",
    "p5-assist",
)
SEVN_COMPONENTS = ("sevn.SecretField", "sevn.ApprovalCard", "sevn.AssistCard", "Table")


def _load_json(name: str) -> Any:
    path = PAYLOAD_DIR / name
    assert path.is_file(), f"missing {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _payload(payload_id: str) -> dict[str, Any]:
    doc = _load_json(f"{payload_id}.json")
    assert isinstance(doc, dict), f"{payload_id} must be an object"
    messages = doc.get("messages")
    assert isinstance(messages, list) and messages, (
        f"{payload_id} messages must be a non-empty list"
    )
    return doc


def _messages(doc: dict[str, Any], *, include_update: bool) -> list[dict[str, Any]]:
    messages = [msg for msg in doc["messages"] if isinstance(msg, dict)]
    if include_update:
        extra = doc.get("update") or []
        assert isinstance(extra, list)
        messages.extend(msg for msg in extra if isinstance(msg, dict))
    return messages


def _components(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for message in messages:
        update = message.get("updateComponents")
        if not isinstance(update, dict):
            continue
        components = update.get("components")
        if isinstance(components, list):
            found.extend(comp for comp in components if isinstance(comp, dict))
    return found


def _component_types(messages: list[dict[str, Any]]) -> set[str]:
    return {
        name
        for comp in _components(messages)
        if isinstance(name := comp.get("component"), str)
    }


def _sevn_catalog() -> Any:
    doc = _load_json("sevn_catalog.json")
    assert isinstance(doc, dict), "sevn_catalog.json must be an object"
    version = doc.get("protocolVersion") or "v0.9"
    assert isinstance(version, str) and version, (
        "sevn catalog protocolVersion must be a string"
    )
    catalog = Catalog.from_json(doc, protocol_version=version)
    for name in SEVN_COMPONENTS:
        assert name in catalog.components, f"sevn catalog is missing {name}"
    return catalog


def _catalog_ids(messages: list[dict[str, Any]]) -> set[str]:
    found: set[str] = set()
    for message in messages:
        create = message.get("createSurface")
        if isinstance(create, dict) and isinstance(create.get("catalogId"), str):
            found.add(create["catalogId"])
        for comp in _components([message]):
            if isinstance(comp.get("catalogId"), str):
                found.add(comp["catalogId"])
    return found


def _processor(messages: list[dict[str, Any]]) -> MessageProcessor:
    basic = BasicCatalog("v0.9.1")
    sevn = _sevn_catalog()
    components = [*basic.components.values(), *sevn.components.values()]
    functions = [*basic.functions.values(), *sevn.functions.values()]
    catalog_ids = {basic.catalog_id, sevn.catalog_id, *_catalog_ids(messages)}
    catalogs = [
        Catalog(catalog_id, "v0.9", components=components, functions=functions)
        for catalog_id in sorted(catalog_ids)
        if catalog_id
    ]
    return MessageProcessor(
        catalogs,
        options=MessageProcessorOptions(validation_config=STRICT_VALIDATION),
    )


def _assert_version(messages: list[dict[str, Any]]) -> None:
    assert messages, "payload has no messages"
    for message in messages:
        version = str(message.get("version", ""))
        assert version.startswith(("v0.9", "0.9")), f"expected v0.9.x, got {version}"


def _set_pointer(root: dict[str, Any], pointer: str, value: Any) -> dict[str, Any]:
    if pointer in ("", "/"):
        assert isinstance(value, dict), "data model root must be an object"
        return value
    parts = [
        part.replace("~1", "/").replace("~0", "~") for part in pointer.split("/")[1:]
    ]
    cursor = root
    for part in parts[:-1]:
        child = cursor.get(part)
        if not isinstance(child, dict):
            child = {}
            cursor[part] = child
        cursor = child
    cursor[parts[-1]] = value
    return root


def _data_model(messages: list[dict[str, Any]]) -> dict[str, Any]:
    model: dict[str, Any] = {}
    for message in messages:
        update = message.get("updateDataModel")
        if not isinstance(update, dict):
            continue
        path = update.get("path") if isinstance(update.get("path"), str) else "/"
        model = _set_pointer(model, path, update.get("value"))
    return model


def _list_lengths(node: object, path: str = "") -> dict[str, int]:
    found: dict[str, int] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            found.update(_list_lengths(value, f"{path}/{key}"))
    elif isinstance(node, list):
        found[path or "/"] = len(node)
        for index, value in enumerate(node):
            found.update(_list_lengths(value, f"{path}/{index}"))
    return found


def _leaves(node: object, path: str = "") -> dict[str, str]:
    if isinstance(node, dict):
        found: dict[str, str] = {}
        for key, value in node.items():
            found.update(_leaves(value, f"{path}/{key}"))
        return found
    if isinstance(node, list):
        found = {}
        for index, value in enumerate(node):
            found.update(_leaves(value, f"{path}/{index}"))
        return found
    if isinstance(node, str):
        return {path: node}
    if isinstance(node, bool) or node is None:
        return {}
    if isinstance(node, (int, float)):
        return {path: str(node)}
    return {}


def _assert_shape(payload_id: str, doc: dict[str, Any]) -> None:
    messages = _messages(doc, include_update=False)
    types = _component_types(_messages(doc, include_update=True))
    if payload_id == "p1-form":
        assert "TextField" in types
        assert "Button" in types
        assert types & {"ChoicePicker", "Select"}, types
        assert types & {"DateTimeInput", "DatePicker"}, types
        choices = [
            comp
            for comp in _components(messages)
            if comp.get("component") in {"ChoicePicker", "Select"}
        ]
        assert choices, "p1 needs a choice component in the initial messages"
        options = choices[0].get("options")
        assert isinstance(options, list) and options, (
            "p1 choice options must be a non-empty list"
        )
        first = options[0]
        assert (
            isinstance(first, dict)
            and isinstance(first.get("value"), str)
            and first["value"]
        )
    elif payload_id == "p2-table-update":
        update = doc.get("update")
        assert isinstance(update, list) and update, (
            "p2 update must be a non-empty message list"
        )
        assert "Table" in _component_types(messages), (
            "Table must exist before the incremental update"
        )
        before = _data_model(messages)
        after = _data_model(_messages(doc, include_update=True))
        before_lists = _list_lengths(before)
        grown = [
            path
            for path, length in _list_lengths(after).items()
            if before_lists.get(path, 0) >= 1 and length >= before_lists[path] + 1
        ]
        assert grown, "p2 update must append to an existing data-model list"
        before_leaves = _leaves(before)
        changed = [
            path
            for path, previous in before_leaves.items()
            if path in _leaves(after) and _leaves(after)[path] != previous
        ]
        assert changed, "p2 update must change an existing data-model value"
    elif payload_id == "p3-secret":
        assert "sevn.SecretField" in types
        fields = [
            comp
            for comp in _components(messages)
            if comp.get("component") == "sevn.SecretField"
        ]
        assert fields, "sevn.SecretField must be in the initial messages"
        for key in ("name", "label", "help", "link"):
            value = fields[0].get(key)
            assert isinstance(value, str) and value, (
                f"sevn.SecretField {key} must be a string"
            )
    elif payload_id == "p4-approval":
        assert "sevn.ApprovalCard" in types
    elif payload_id == "p5-assist":
        assert "sevn.AssistCard" in types


def _assert_no_value_key(node: object, path: str) -> None:
    if isinstance(node, dict):
        assert "value" not in node, f"data model has key 'value' at {path or '/'}"
        for key, child in node.items():
            _assert_no_value_key(child, f"{path}/{key}")
    elif isinstance(node, list):
        for index, child in enumerate(node):
            _assert_no_value_key(child, f"{path}/{index}")


@pytest.mark.parametrize("payload_id", PAYLOAD_IDS)
def test_payload_validates(payload_id: str) -> None:
    doc = _payload(payload_id)
    messages = _messages(doc, include_update=True)
    _assert_version(messages)
    _assert_shape(payload_id, doc)
    basic_names = set(BasicCatalog("v0.9.1").components)
    missing = [
        name
        for name in _component_types(messages)
        if name not in basic_names and name not in _sevn_catalog().components
    ]
    assert not missing, f"no schema for {missing}"
    try:
        _processor(messages).process_messages(messages)
    except Exception as exc:
        raise AssertionError(f"{payload_id} failed catalog validation: {exc}") from exc


def test_secret_payload_has_no_value_field() -> None:
    doc = _payload("p3-secret")
    messages = _messages(doc, include_update=True)
    assert "sevn.SecretField" in _component_types(messages)
    for message in messages:
        update = message.get("updateDataModel")
        if not isinstance(update, dict):
            continue
        pointer = update.get("path") if isinstance(update.get("path"), str) else "/"
        for segment in pointer.split("/"):
            assert segment.replace("~1", "/").replace("~0", "~") != "value", pointer
        _assert_no_value_key(update.get("value"), pointer)
    _assert_no_value_key(_data_model(messages), "")
