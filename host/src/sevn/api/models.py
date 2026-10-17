"""Model catalog method (D5, D10)."""

from __future__ import annotations

from sevn.contracts.methods import ModelInfo, ModelsListParams, ModelsListResult
from sevn.protocol.registry import Ctx, method
from sevn.runtime.models import list_models


@method("models.list", params=ModelsListParams, result=ModelsListResult, mutating=False)
async def models_list(_ctx: Ctx, _params: ModelsListParams) -> ModelsListResult:
    found = await list_models()
    return ModelsListResult(
        models=[ModelInfo(id=item.id, provider=item.provider, name=item.name) for item in found]
    )
