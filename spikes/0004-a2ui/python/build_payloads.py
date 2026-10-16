"""Write the S3 sample payloads with a2ui-core.

D2 payloads share one basic-catalog id. D3: ``sevn.SecretField`` carries
name, label, help, and link, and the p3 data model has no ``value`` key.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from a2ui.core.basic_catalog import BasicCatalog
from a2ui.core.basic_catalog.v0_9.components import (
    ButtonComponent,
    ChoicePickerComponent,
    ColumnComponent,
    DateTimeInputComponent,
    TextComponent,
    TextFieldComponent,
)
from a2ui.core.catalog.catalog import Catalog
from a2ui.core.processing.message_processor import (
    MessageProcessor,
    MessageProcessorOptions,
)
from a2ui.core.schema.v0_9.server_to_client import (
    CreateSurface,
    CreateSurfaceMessage,
    UpdateComponents,
    UpdateComponentsMessage,
    UpdateDataModel,
    UpdateDataModelMessage,
)
from a2ui.core.validation import STRICT_VALIDATION
from pydantic import BaseModel

PAYLOAD_DIR = Path(__file__).resolve().parents[1] / "payloads"
SEVN_CATALOG_ID = "https://sevn.bot/a2ui/catalog.json"
BASIC_CATALOG_ID = BasicCatalog("v0.9.1").catalog_id


def dump(model: BaseModel) -> dict[str, Any]:
    dumped = model.model_dump(by_alias=True, exclude_none=True, mode="json")
    if not isinstance(dumped, dict):
        raise TypeError("A2UI model dump must be an object")
    return dumped


def basic(model: type[BaseModel], payload: dict[str, Any]) -> dict[str, Any]:
    return dump(model.model_validate(payload))


def create_surface(surface_id: str) -> dict[str, Any]:
    return dump(
        CreateSurfaceMessage(
            create_surface=CreateSurface(
                surface_id=surface_id,
                catalog_id=BASIC_CATALOG_ID,
            )
        )
    )


def update_components(
    surface_id: str, components: list[dict[str, Any]]
) -> dict[str, Any]:
    return dump(
        UpdateComponentsMessage(
            update_components=UpdateComponents(
                surface_id=surface_id,
                components=components,
            )
        )
    )


def update_data(surface_id: str, path: str, value: Any) -> dict[str, Any]:
    return dump(
        UpdateDataModelMessage(
            update_data_model=UpdateDataModel(
                surface_id=surface_id,
                path=path,
                value=value,
            )
        )
    )


def _string_prop(description: str) -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "description": description}


def sevn_catalog() -> dict[str, Any]:
    binding = {
        "type": "object",
        "additionalProperties": False,
        "required": ["path"],
        "properties": {
            "path": {
                "type": "string",
                "description": "JSON Pointer into the surface data model.",
            }
        },
    }
    return {
        "catalogId": SEVN_CATALOG_ID,
        "protocolVersion": "v0.9",
        "components": {
            "sevn.SecretField": {
                "type": "object",
                "additionalProperties": False,
                "description": (
                    "Masked secret input. The value is not part of the schema "
                    "and must not enter the data model."
                ),
                "required": ["name", "label", "help", "link"],
                "properties": {
                    "name": _string_prop("Secret name handed back with the action."),
                    "label": _string_prop("Field label."),
                    "help": _string_prop("Help text shown beside the field."),
                    "link": _string_prop(
                        "Link the operator can open, for example a provider page."
                    ),
                },
            },
            "sevn.ApprovalCard": {
                "type": "object",
                "additionalProperties": False,
                "description": "Approve or deny a pending action.",
                "required": ["title"],
                "properties": {
                    "title": _string_prop("What the operator is approving.")
                },
            },
            "sevn.AssistCard": {
                "type": "object",
                "additionalProperties": False,
                "description": "Offers the Open Computer panel action.",
                "required": ["prompt"],
                "properties": {
                    "prompt": _string_prop("Short prompt shown on the card.")
                },
            },
            "Table": {
                "type": "object",
                "additionalProperties": False,
                "description": "Renders a data-model list as table rows.",
                "required": ["rows"],
                "properties": {"rows": binding},
            },
        },
        "functions": {},
    }


def p1_form() -> dict[str, Any]:
    surface = "p1-form"
    components = [
        basic(
            ColumnComponent,
            {
                "id": "root",
                "component": "Column",
                "children": ["email", "choice", "when", "submit"],
            },
        ),
        basic(
            TextFieldComponent,
            {
                "id": "email",
                "component": "TextField",
                "label": "Email",
                "value": {"path": "/email"},
            },
        ),
        basic(
            ChoicePickerComponent,
            {
                "id": "choice",
                "component": "ChoicePicker",
                "label": "Plan",
                "variant": "mutuallyExclusive",
                "options": [
                    {"label": "Daily", "value": "daily"},
                    {"label": "Weekly", "value": "weekly"},
                ],
                "value": {"path": "/choice"},
            },
        ),
        basic(
            DateTimeInputComponent,
            {
                "id": "when",
                "component": "DateTimeInput",
                "label": "When",
                "enableDate": True,
                "value": {"path": "/when"},
            },
        ),
        basic(
            ButtonComponent,
            {
                "id": "submit",
                "component": "Button",
                "child": "submit-label",
                "action": {
                    "event": {
                        "name": "submit",
                        "context": {
                            "email": {"path": "/email"},
                            "when": {"path": "/when"},
                            "choice": {"path": "/choice"},
                        },
                    }
                },
            },
        ),
        basic(
            TextComponent,
            {
                "id": "submit-label",
                "component": "Text",
                "text": "Submit",
                "variant": "h5",
            },
        ),
    ]
    return {
        "messages": [
            create_surface(surface),
            update_components(surface, components),
            update_data(surface, "/", {"email": "", "when": "", "choice": []}),
        ]
    }


def p2_table_update() -> dict[str, Any]:
    surface = "p2-table-update"
    components = [
        {
            "id": "root",
            "component": "Table",
            "rows": {"path": "/rows"},
        }
    ]
    return {
        "messages": [
            create_surface(surface),
            update_components(surface, components),
            update_data(
                surface,
                "/rows",
                [
                    {"item": "Ada", "qty": 1},
                    {"item": "Grace", "qty": 2},
                ],
            ),
        ],
        "update": [
            update_data(
                surface,
                "/rows",
                [
                    {"item": "Ada", "qty": 9},
                    {"item": "Grace", "qty": 2},
                    {"item": "Lin", "qty": 3},
                ],
            )
        ],
    }


def p3_secret() -> dict[str, Any]:
    surface = "p3-secret"
    return {
        "messages": [
            create_surface(surface),
            update_components(
                surface,
                [
                    {
                        "id": "root",
                        "component": "sevn.SecretField",
                        "name": "opencode_api_key",
                        "label": "OpenCode API key",
                        "help": "Stored securely, never shown to your bot",
                        "link": "https://opencode.ai/auth",
                    }
                ],
            ),
        ]
    }


def p4_approval() -> dict[str, Any]:
    surface = "p4-approval"
    return {
        "messages": [
            create_surface(surface),
            update_components(
                surface,
                [
                    {
                        "id": "root",
                        "component": "sevn.ApprovalCard",
                        "title": "Deploy the host",
                    }
                ],
            ),
        ]
    }


def p5_assist() -> dict[str, Any]:
    surface = "p5-assist"
    return {
        "messages": [
            create_surface(surface),
            update_components(
                surface,
                [
                    {
                        "id": "root",
                        "component": "sevn.AssistCard",
                        "prompt": "The computer is waiting",
                    }
                ],
            ),
        ]
    }


def _messages(doc: dict[str, Any]) -> list[dict[str, Any]]:
    messages = [msg for msg in doc["messages"] if isinstance(msg, dict)]
    extra = doc.get("update") or []
    if isinstance(extra, list):
        messages.extend(msg for msg in extra if isinstance(msg, dict))
    return messages


def _catalog_ids(messages: list[dict[str, Any]]) -> set[str]:
    found: set[str] = set()
    for message in messages:
        create = message.get("createSurface")
        if isinstance(create, dict) and isinstance(create.get("catalogId"), str):
            found.add(create["catalogId"])
    return found


def check(catalog_doc: dict[str, Any], payloads: dict[str, dict[str, Any]]) -> None:
    sevn = Catalog.from_json(catalog_doc, protocol_version="v0.9")
    basic_catalog = BasicCatalog("v0.9.1")
    components = [*basic_catalog.components.values(), *sevn.components.values()]
    functions = [*basic_catalog.functions.values(), *sevn.functions.values()]
    for name, doc in payloads.items():
        messages = deepcopy(_messages(doc))
        catalog_ids = {
            basic_catalog.catalog_id,
            sevn.catalog_id,
            *_catalog_ids(messages),
        }
        catalogs = [
            Catalog(catalog_id, "v0.9", components=components, functions=functions)
            for catalog_id in sorted(catalog_ids)
            if catalog_id
        ]
        try:
            MessageProcessor(
                catalogs,
                options=MessageProcessorOptions(validation_config=STRICT_VALIDATION),
            ).process_messages(messages)
        except Exception as exc:
            raise SystemExit(f"{name} failed catalog validation: {exc}") from exc


def write_payloads() -> None:
    catalog_doc = sevn_catalog()
    payloads = {
        "p1-form": p1_form(),
        "p2-table-update": p2_table_update(),
        "p3-secret": p3_secret(),
        "p4-approval": p4_approval(),
        "p5-assist": p5_assist(),
    }
    check(catalog_doc, payloads)
    PAYLOAD_DIR.mkdir(parents=True, exist_ok=True)
    documents: dict[str, dict[str, Any]] = {"sevn_catalog": catalog_doc, **payloads}
    for name, doc in documents.items():
        path = PAYLOAD_DIR / f"{name}.json"
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    write_payloads()
