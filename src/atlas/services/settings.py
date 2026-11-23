"""The instance's settings, stored in the database and changed live.

``current`` is an immutable snapshot. An update validates the new values,
tries changed providers with a real call, commits, then swaps the snapshot, so
work already running finishes on the values it started with.
"""

import asyncio
import logging
from typing import Any, NamedTuple

from pydantic import SecretStr, ValidationError

from atlas.config import (
    SECRET_FIELDS,
    BootstrapSettings,
    InstanceSettings,
    MasterKey,
    Settings,
)
from atlas.core.providers.factory import (
    PROVIDERS,
    ModelKind,
    ProviderHealth,
    ProviderInfo,
    check_chat_model,
    check_embeddings,
    endpoint_for,
    list_models,
)
from atlas.models.settings import StoredSettings
from atlas.repository.uow import UnitOfWorkFactory
from atlas.services.access import Caller, require_instance_admin
from atlas.services.ai import AIRuntime
from atlas.services.errors import InvalidInput
from atlas.services.validation import invalid, summary

logger = logging.getLogger(__name__)

_EMBEDDING_FIELDS = ("embedding_provider", "embedding_model")
_CHECKS = {"chat": check_chat_model, "embedding": check_embeddings}
_KINDS: tuple[ModelKind, ...] = ("chat", "embedding")
_SECRETS = frozenset(SECRET_FIELDS)
# A saved key must never follow its endpoint to a new provider or address.
_ENDPOINT_KEYS = (
    ("llm_provider", "llm_base_url", "llm_api_key"),
    ("embedding_provider", "embedding_base_url", "embedding_api_key"),
)
# Changing any of these means talking to a model differently.
_PROVIDER_FIELDS = (
    *_EMBEDDING_FIELDS,
    *SECRET_FIELDS,
    "llm_provider",
    "llm_model",
    "llm_thinking",
    "llm_base_url",
    "embedding_base_url",
    "ollama_base_url",
    "fake_embedding_dim",
)


class SettingsView(NamedTuple):
    """Settings safe to show: secrets only say whether they are set."""

    values: dict[str, Any]
    secrets_set: list[str]


class SettingsService:
    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        bootstrap: BootstrapSettings,
        master_key: MasterKey,
        ai: AIRuntime,
    ) -> None:
        self._uow = uow
        self._ai = ai
        self._bootstrap = bootstrap
        self._master_key = master_key
        self._instance: InstanceSettings | None = None
        self._current: Settings | None = None

    @property
    def current(self) -> Settings:
        if self._current is None:
            raise RuntimeError("settings are not loaded yet")
        return self._current

    async def load(self) -> Settings:
        """Read the settings at startup, creating defaults on first run."""
        async with self._uow() as uow:
            stored = await uow.settings.load()
            values, encrypted = dict(stored.values), dict(stored.secrets)
        for field, token in encrypted.items():
            if (secret := self._master_key.decrypt(token)) is None:
                logger.warning("%s must be entered again", field)
            else:
                values[field] = secret
        return self._apply(InstanceSettings.model_validate(values))

    async def view(self, caller: Caller) -> SettingsView:
        require_instance_admin(caller)
        return self._view(self._loaded)

    async def providers(self, caller: Caller) -> list[ProviderInfo]:
        require_instance_admin(caller)
        return list(PROVIDERS.values())

    async def models(
        self,
        caller: Caller,
        *,
        provider: str,
        kind: ModelKind,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> list[str]:
        """What a provider offers, to choose from instead of typing a name.
        A key entered here is used for this request and not saved."""
        require_instance_admin(caller)
        return await list_models(
            settings=self.current,
            provider=provider,
            kind=kind,
            api_key=api_key,
            base_url=base_url,
        )

    async def test(
        self,
        caller: Caller,
        *,
        values: dict[str, Any] | None = None,
        secrets: dict[str, str | None] | None = None,
        kind: ModelKind | None = None,
    ) -> dict[ModelKind, ProviderHealth]:
        """Try settings with real provider calls, without saving them:
        one model, or both."""
        require_instance_admin(caller)
        candidate = self._merge(values or {}, secrets or {})
        kinds = [kind] if kind else list(_KINDS)
        return await _check(self._compose(candidate), kinds)

    async def update(
        self,
        caller: Caller,
        *,
        values: dict[str, Any] | None = None,
        secrets: dict[str, str | None] | None = None,
        confirm_reindex: bool = False,
        check_providers: bool = True,
    ) -> SettingsView:
        """Change settings. A secret set to ``None`` or ``""`` is cleared,
        and one left out keeps its value. Changing the embedding model
        replaces every stored vector, so it needs ``confirm_reindex``. A
        changed provider must answer a real call unless ``check_providers``
        is off."""
        require_instance_admin(caller)
        updated = self._merge(values or {}, secrets or {})
        if not confirm_reindex and _differs(
            updated, self._loaded, _EMBEDDING_FIELDS
        ):
            raise InvalidInput(
                "changing the embedding model reindexes every document",
                code="reindex_required",
            )
        providers_changed = _differs(updated, self._loaded, _PROVIDER_FIELDS)
        if providers_changed and check_providers:
            # Only what changed: a broken embedding model must not stop
            # someone from saving a working chat model.
            composed = self._compose(updated)
            before = self.current
            changed: list[ModelKind] = [
                kind
                for kind in _KINDS
                if endpoint_for(settings=composed, kind=kind)
                != endpoint_for(settings=before, kind=kind)
            ]
            checks = await _check(composed, changed)
            failed: dict[str, str] = {
                k: h.detail for k, h in checks.items() if not h.ok
            }
            if failed:
                raise InvalidInput(
                    summary(failed),
                    code="provider_check_failed",
                    fields=failed,
                )
        async with self._uow() as uow:
            self._store(updated, await uow.settings.load())
        await self._ai.apply(self._apply(updated), reconnect=providers_changed)
        return self._view(updated)

    @property
    def _loaded(self) -> InstanceSettings:
        if self._instance is None:
            raise RuntimeError("settings are not loaded yet")
        return self._instance

    def _merge(
        self, values: dict[str, Any], secrets: dict[str, str | None]
    ) -> InstanceSettings:
        editable = InstanceSettings.model_fields.keys() - _SECRETS
        unknown = (values.keys() - editable) | (secrets.keys() - _SECRETS)
        if unknown:
            raise InvalidInput(
                "Some of these settings aren't recognised.",
                code="unknown_setting",
            )
        for provider_field, url_field, key_field in _ENDPOINT_KEYS:
            moved = [
                field
                for field in (provider_field, url_field)
                if field in values
                and values[field] != getattr(self._loaded, field)
            ]
            if (
                moved
                and getattr(self._loaded, key_field) is not None
                and key_field not in secrets
            ):
                message = "Enter the API key again for this connection."
                raise InvalidInput(
                    message,
                    code="api_key_required",
                    fields={key_field: message},
                )
        cleared = {field: value or None for field, value in secrets.items()}
        try:
            return InstanceSettings.model_validate(
                {**dict(self._loaded), **values, **cleared}
            )
        except ValidationError as exc:
            raise invalid(exc, code="invalid_settings") from exc

    def _store(self, instance: InstanceSettings, row: StoredSettings) -> None:
        row.values = _public_values(instance)
        row.secrets = {
            field: self._master_key.encrypt(secret.get_secret_value())
            for field in SECRET_FIELDS
            if (secret := _secret(instance, field)) is not None
        }

    def _apply(self, instance: InstanceSettings) -> Settings:
        self._instance = instance
        self._current = self._compose(instance)
        return self._current

    def _compose(self, instance: InstanceSettings) -> Settings:
        return Settings.compose(
            self._bootstrap, instance, jwt_secret=self._master_key.jwt_secret
        )

    @staticmethod
    def _view(instance: InstanceSettings) -> SettingsView:
        return SettingsView(
            values=_public_values(instance),
            secrets_set=[
                field
                for field in SECRET_FIELDS
                if _secret(instance, field) is not None
            ],
        )


async def _check(
    settings: Settings, kinds: list[ModelKind]
) -> dict[ModelKind, ProviderHealth]:
    results = await asyncio.gather(
        *(_CHECKS[kind](settings=settings) for kind in kinds)
    )
    return dict(zip(kinds, results, strict=True))


def _differs(
    first: InstanceSettings, second: InstanceSettings, fields: tuple[str, ...]
) -> bool:
    return any(getattr(first, f) != getattr(second, f) for f in fields)


def _public_values(instance: InstanceSettings) -> dict[str, Any]:
    return instance.model_dump(mode="json", exclude=set(_SECRETS))


def _secret(instance: InstanceSettings, field: str) -> SecretStr | None:
    value: SecretStr | None = getattr(instance, field)
    return value
