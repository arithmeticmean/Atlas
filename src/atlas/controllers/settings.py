"""The instance's settings, for admins.

Secrets are write-only: a response says only which ones are set. Saving tries
changed providers with a real call first, unless ``check_providers`` is off.
"""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from atlas.controllers._common import (
    CurrentCaller,
    ResponseModel,
    Services,
    problems,
)
from atlas.core.providers.factory import ModelKind

router = APIRouter(prefix="/system/settings", tags=["settings"])


class SettingsResponse(ResponseModel):
    values: dict[str, Any]
    secrets_set: list[str]


class SettingsTest(BaseModel):
    """With an empty body, tests the settings in use."""

    values: dict[str, Any] = Field(default_factory=dict)
    # A secret left out keeps its value; null or "" clears it.
    secrets: dict[str, str | None] = Field(default_factory=dict)


class SettingsCheck(SettingsTest):
    kind: ModelKind | None = Field(
        default=None, description="test one model; both if omitted"
    )


class SettingsUpdate(SettingsTest):
    confirm_reindex: bool = Field(
        default=False,
        description="required to change the embedding model",
    )
    check_providers: bool = True


class ProviderCheck(ResponseModel):
    ok: bool
    detail: str


class ProviderResponse(ResponseModel):
    key: str
    name: str
    supports_embeddings: bool
    needs_api_key: bool
    needs_base_url: bool
    default_base_url: str | None


class ModelsRequest(BaseModel):
    provider: str
    kind: ModelKind = "chat"
    # Optional: without it, the saved key is used for its own endpoint.
    api_key: str | None = Field(default=None, repr=False)
    base_url: str | None = None


class ModelsResponse(BaseModel):
    models: list[str]


class SettingsTestResponse(BaseModel):
    ok: bool
    chat: ProviderCheck | None
    embeddings: ProviderCheck | None


@router.get("", responses=problems(401, 403))
async def get_settings(
    services: Services, caller: CurrentCaller
) -> SettingsResponse:
    view = await services.settings.view(caller)
    return SettingsResponse.model_validate(view)


@router.patch("", responses=problems(401, 403, 422))
async def update_settings(
    services: Services, caller: CurrentCaller, body: SettingsUpdate
) -> SettingsResponse:
    view = await services.settings.update(
        caller,
        values=body.values,
        secrets=body.secrets,
        confirm_reindex=body.confirm_reindex,
        check_providers=body.check_providers,
    )
    return SettingsResponse.model_validate(view)


@router.post("/test", responses=problems(401, 403, 422))
async def test_settings(
    services: Services, caller: CurrentCaller, body: SettingsCheck
) -> SettingsTestResponse:
    """Try settings with real provider calls, without saving them."""
    checks = await services.settings.test(
        caller, values=body.values, secrets=body.secrets, kind=body.kind
    )
    chat, embeddings = checks.get("chat"), checks.get("embedding")
    return SettingsTestResponse(
        ok=all(check.ok for check in checks.values()),
        chat=ProviderCheck.model_validate(chat) if chat else None,
        embeddings=(
            ProviderCheck.model_validate(embeddings) if embeddings else None
        ),
    )


@router.get("/providers", responses=problems(401, 403))
async def list_providers(
    services: Services, caller: CurrentCaller
) -> list[ProviderResponse]:
    """Every provider, and which fields the settings form should ask for."""
    providers = await services.settings.providers(caller)
    return [ProviderResponse.model_validate(p) for p in providers]


@router.post("/models", responses=problems(401, 403, 422, 502))
async def list_models(
    services: Services, caller: CurrentCaller, body: ModelsRequest
) -> ModelsResponse:
    """The models a provider offers. A key sent here is not saved."""
    models = await services.settings.models(
        caller,
        provider=body.provider,
        kind=body.kind,
        api_key=body.api_key,
        base_url=body.base_url,
    )
    return ModelsResponse(models=models)
