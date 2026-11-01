"""Open lanes must be distinguishable to jev (WV F2).

Spawn currently stores ``title`` and ``summary`` as ``""``, so target
criteria is ``" — "`` and the router state has no agent ids. Lanes then
show the raw agent id.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fakes.fake_jev import FakeJev
from support.chat import connected, load_modules, mint_id, ok, request

_TRIP = "plan a trip to Lisbon"
_INVOICE = "also fix my invoice script"
_BLANK = " \u2014 "


def _install(script: list[dict[str, object]]) -> FakeJev:
    from sevn.decisions.jev import use_client

    fake = FakeJev(script=script)
    use_client(fake)
    return fake


def _clear() -> None:
    from sevn.decisions.jev import use_client

    use_client(None)


async def _create_bot(client: object) -> dict[str, object]:
    frame, _earlier = await request(
        client,
        "bots.create",
        {"name": "Nimbus", "op_id": mint_id("op_")},
    )
    return ok(frame)


async def _send(client: object, bot_id: object, text: str) -> dict[str, object]:
    frame, _earlier = await request(
        client,
        "messages.send",
        {"bot_id": bot_id, "text": text, "op_id": mint_id("op_")},
    )
    return ok(frame)


def _tokens(text: str) -> set[str]:
    words = {word.strip(".,!?").lower() for word in text.replace("\u2014", " ").split()}
    return {word for word in words if len(word) >= 4}


def _mentions(label: str, own: str, other: str) -> bool:
    distinctive = _tokens(own) - _tokens(other)
    folded = label.lower()
    return any(token in folded for token in distinctive)


async def test_open_lanes_are_distinguishable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lisbon and invoice lanes have titles, criteria, and ids jev can tell apart."""
    load_modules("sevn.api.bots", "sevn.api.messages", "sevn.api.agents")
    _install(
        [
            {"message.intent": ("new_request", 0.95), "message.target_agent": ("none", 0.9)},
            {"message.intent": ("new_request", 0.95), "message.target_agent": ("none", 0.9)},
        ]
    )
    try:
        async with connected(tmp_path, monkeypatch) as (_host, client):
            bot = await _create_bot(client)
            trip = await _send(client, bot["id"], _TRIP)
            invoice = await _send(client, bot["id"], _INVOICE)
            trip_id = str(trip["agent_id"])
            invoice_id = str(invoice["agent_id"])
            listed, _earlier = await request(client, "agents.list", {"bot_id": bot["id"]})
            agents = ok(listed)["agents"]
            assert isinstance(agents, list)
            by_id = {str(item["id"]): item for item in agents if isinstance(item, dict)}
            _clear()
            follow = _install(
                [
                    {
                        "message.intent": ("follow_up", 0.95),
                        "message.target_agent": (trip_id, 0.93),
                    }
                ]
            )
            await _send(client, bot["id"], "make it 4 days")
            assert follow.requests
            request_state = follow.requests[-1].state
            state = request_state if isinstance(request_state, str) else json.dumps(request_state)
            question = follow.requests[-1].questions["message.target_agent"]
            assert isinstance(question, dict)
            criteria = question.get("criteria")
            assert isinstance(criteria, dict)
            problems = _identity_problems(
                by_id,
                trip_id,
                invoice_id,
                criteria,
                state,
            )
            assert problems == [], "; ".join(problems)
    finally:
        _clear()


def _identity_problems(
    by_id: dict[str, dict[str, object]],
    trip_id: str,
    invoice_id: str,
    criteria: dict[str, object],
    state: str,
) -> list[str]:
    problems: list[str] = []
    expected = ((trip_id, _TRIP, _INVOICE), (invoice_id, _INVOICE, _TRIP))
    for agent_id, own, other in expected:
        row = by_id.get(agent_id)
        if not isinstance(row, dict):
            problems.append(f"{agent_id} missing from agents.list")
            continue
        title = str(row.get("title") or "")
        summary = str(row.get("summary") or "")
        label = f"{title} {summary}"
        if title == "" or summary == "":
            problems.append(f"{agent_id} title={title!r} summary={summary!r}")
        elif title == agent_id or not _mentions(label, own, other):
            problems.append(f"{agent_id} label {label!r} does not name its request")
        value = criteria.get(agent_id)
        if value != f"{title} \u2014 {summary}" or value == _BLANK:
            problems.append(f"{agent_id} criteria {value!r}")
        elif isinstance(value, str) and not _mentions(value, own, other):
            problems.append(f"{agent_id} criteria {value!r} does not name its request")
        if agent_id not in state:
            problems.append(f"{agent_id} missing from router state {state!r}")
    if _TRIP not in state or _INVOICE not in state:
        problems.append(f"router state dropped user text {state!r}")
    return problems
