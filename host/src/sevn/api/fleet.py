"""Fleet dashboard methods (plan fleet-dashboards)."""

from __future__ import annotations

from sevn.contracts.methods import FleetOverviewParams
from sevn.domain.fleet import FleetOverview, overview
from sevn.protocol.registry import Ctx, method


@method("fleet.overview", params=FleetOverviewParams, result=FleetOverview, mutating=False)
async def fleet_overview(_ctx: Ctx, params: FleetOverviewParams) -> FleetOverview:
    return await overview(bot_id=params.bot_id)
