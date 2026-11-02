"""``pairing.start`` (plan 0055 D1). Owner only; owner tickets need a loopback session."""

from __future__ import annotations

from sevn.config import Settings
from sevn.contracts.errors import ProtocolError
from sevn.contracts.methods import PairingStartParams, PairingStartResult
from sevn.identity import pairing
from sevn.protocol.registry import Ctx, method


def _without_ticket(result: dict[str, object]) -> dict[str, object]:
    """The op log's copy: the ticket, its code and the QR URI are shown once only."""
    return {**result, "ticket": "", "short_code": "", "qr_uri": ""}


def is_loopback(ctx: Ctx) -> bool:
    """Whether the session is a loopback owner session. Unknown means no (fail closed)."""
    return getattr(ctx, "loopback", False) is True


@method(
    "pairing.start",
    params=PairingStartParams,
    result=PairingStartResult,
    mutating=True,
    scope="owner",
    stored=_without_ticket,
)
async def pairing_start(ctx: Ctx, params: PairingStartParams) -> PairingStartResult:
    if params.scope == "owner" and not is_loopback(ctx):
        raise ProtocolError("forbidden", "owner tickets need a loopback owner session")
    ticket = await pairing.start(
        identity=ctx.hub.identity,
        http=Settings.load().http,
        scope=params.scope,
        name=params.name,
        direct_url=params.direct_url,
    )
    return PairingStartResult(
        ticket=ticket.ticket,
        qr_uri=ticket.qr_uri,
        short_code=ticket.short_code,
        expires_at=ticket.expires_at,
    )
