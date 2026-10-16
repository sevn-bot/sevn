"""Deterministic JSON Schema for frames, methods, and events (D18)."""

from __future__ import annotations

import json
from typing import cast

from pydantic import BaseModel

from sevn.contracts.errors import ErrorBody
from sevn.contracts.events import EVENTS, EventSpec
from sevn.contracts.frames import FRAME_MODELS
from sevn.contracts.methods import METHODS, MethodSpec


def build_schema() -> dict[str, object]:
    document: dict[str, object] = {
        "$defs": _definitions(),
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "events": {
            spec.name: {"durable": spec.durable}
            for spec in sorted(EVENTS.values(), key=_event_name)
        },
        "methods": {
            spec.name: {
                "mutating": spec.mutating,
                "params": spec.params.__name__,
                "result": spec.result.__name__,
            }
            for spec in sorted(METHODS.values(), key=_method_name)
        },
        "oneOf": [{"$ref": f"#/$defs/{model.__name__}"} for model in FRAME_MODELS],
        "title": "Frame",
    }
    return _stable(document)


def _definitions() -> dict[str, object]:
    defs: dict[str, object] = {}
    for model in (*FRAME_MODELS, ErrorBody, *_method_models()):
        schema = cast("dict[str, object]", model.model_json_schema())
        nested = schema.pop("$defs", None)
        if isinstance(nested, dict):
            extra = cast("dict[str, object]", nested)
            for key, value in extra.items():
                defs.setdefault(key, value)
        defs[model.__name__] = schema
    return defs


def _method_models() -> list[type[BaseModel]]:
    models: list[type[BaseModel]] = []
    for spec in METHODS.values():
        models.append(spec.params)
        models.append(spec.result)
    return models


def _method_name(spec: MethodSpec) -> str:
    return spec.name


def _event_name(spec: EventSpec) -> str:
    return spec.name


def _stable(document: dict[str, object]) -> dict[str, object]:
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"))
    loaded = json.loads(encoded)
    if not isinstance(loaded, dict):
        raise RuntimeError("schema root must be an object")
    return cast("dict[str, object]", loaded)
