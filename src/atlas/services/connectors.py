"""Connectors: configured sources that feed a project's documents.

Secrets (an access token) are kept in the connector's config for now --
there is no separate secrets column -- and never returned: ``ConnectorView``
is what leaves this service, with secrets left out.

A sync runs inside the request for now and imports through
``DocumentService.upload``, the same path as an upload. Running it in the
background with a history of runs needs a sync-runs table.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from atlas.models.base import utcnow
from atlas.models.connector import Connector
from atlas.repository.base import Paged, PageRequest
from atlas.repository.uow import UnitOfWork, UnitOfWorkFactory
from atlas.services.access import Caller, load_project
from atlas.services.documents import DocumentService
from atlas.services.errors import Busy, NotFound
from atlas.services.sources import (
    SOURCE_TYPES,
    Fetched,
    SourceType,
    build_source,
    source_type,
)

# A sync still "running" after this long was interrupted; allow a new one.
_STALE_SYNC = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class ConnectorView:
    """A connector with its secrets left out."""

    id: str
    project_id: str
    type: str
    name: str
    config: dict[str, Any]
    secrets_set: list[str]
    enabled: bool
    last_synced_at: datetime | None
    last_sync_status: str | None
    last_sync_detail: str | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class SyncError:
    item: str
    message: str


@dataclass(slots=True)
class SyncResult:
    status: Literal["succeeded", "partial", "failed"] = "succeeded"
    imported: int = 0
    unchanged: int = 0
    failed: int = 0
    errors: list[SyncError] = field(default_factory=list)

    def add_failure(self, item: str, message: str) -> None:
        self.failed += 1
        self.errors.append(SyncError(item, message))

    def settle(self) -> None:
        if self.failed:
            succeeded = self.imported + self.unchanged
            self.status = "partial" if succeeded else "failed"

    @property
    def summary(self) -> str:
        return (
            f"{self.imported} imported, {self.unchanged} unchanged, "
            f"{self.failed} failed"
        )


def _split_secrets(
    connector: Connector,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The connector's config, as (public values, secrets)."""
    names = source_type(connector.type).secret_fields
    public = {k: v for k, v in connector.config.items() if k not in names}
    secrets = {
        k: connector.config[k] for k in names if connector.config.get(k)
    }
    return public, secrets


def _view(connector: Connector) -> ConnectorView:
    public, secrets = _split_secrets(connector)
    return ConnectorView(
        id=connector.id,
        project_id=connector.project_id,
        type=connector.type,
        name=connector.name,
        config=public,
        secrets_set=list(secrets),
        enabled=connector.enabled,
        last_synced_at=connector.last_synced_at,
        last_sync_status=connector.last_sync_status,
        last_sync_detail=connector.last_sync_detail,
        created_at=connector.created_at,
        updated_at=connector.updated_at,
    )


async def _connector(
    uow: UnitOfWork, caller: Caller, project_id: str, connector_id: str
) -> Connector:
    await load_project(uow, caller, project_id, admin=True)
    connector = await uow.connectors.get_in_project(project_id, connector_id)
    if connector is None:
        raise NotFound("connector not found", code="connector_not_found")
    return connector


class ConnectorService:
    def __init__(
        self, *, uow: UnitOfWorkFactory, documents: DocumentService
    ) -> None:
        self._uow = uow
        self._documents = documents

    @staticmethod
    def list_types() -> list[SourceType]:
        return list(SOURCE_TYPES.values())

    async def test_config(
        self,
        caller: Caller,
        project_id: str,
        *,
        type: str,
        config: dict[str, Any],
        secrets: dict[str, str],
    ) -> tuple[bool, str]:
        """Try a configuration without saving it."""
        async with self._uow() as uow:
            await load_project(uow, caller, project_id, admin=True)
        return await build_source(type, {**config, **secrets}).check()

    async def create(
        self,
        caller: Caller,
        project_id: str,
        *,
        type: str,
        name: str,
        config: dict[str, Any],
        secrets: dict[str, str],
    ) -> ConnectorView:
        settings = {**config, **secrets}
        build_source(type, settings)  # validates
        async with self._uow() as uow:
            await load_project(uow, caller, project_id, admin=True)
            connector = await uow.connectors.add(
                Connector(
                    project_id=project_id,
                    type=type,
                    name=name,
                    config=settings,
                )
            )
        return _view(connector)

    async def list_connectors(
        self, caller: Caller, project_id: str, page: PageRequest
    ) -> Paged[ConnectorView]:
        async with self._uow() as uow:
            await load_project(uow, caller, project_id, admin=True)
            connectors = await uow.connectors.page_for_project(
                project_id, page
            )
        return connectors.map(_view)

    async def get(
        self, caller: Caller, project_id: str, connector_id: str
    ) -> ConnectorView:
        async with self._uow() as uow:
            return _view(
                await _connector(uow, caller, project_id, connector_id)
            )

    async def update(
        self,
        caller: Caller,
        project_id: str,
        connector_id: str,
        *,
        name: str | None = None,
        config: dict[str, Any] | None = None,
        secrets: dict[str, str] | None = None,
        enabled: bool | None = None,
    ) -> ConnectorView:
        """A secret not sent keeps its stored value."""
        async with self._uow() as uow:
            connector = await _connector(uow, caller, project_id, connector_id)
            public, stored_secrets = _split_secrets(connector)
            settings = {
                **(config if config is not None else public),
                **stored_secrets,
                **(secrets or {}),
            }
            build_source(connector.type, settings)  # validates
            connector.config = settings
            if name is not None:
                connector.name = name
            if enabled is not None:
                connector.enabled = enabled
        return _view(connector)

    async def delete(
        self,
        caller: Caller,
        project_id: str,
        connector_id: str,
        *,
        delete_documents: bool = False,
    ) -> None:
        if delete_documents:
            raise NotImplementedError(
                "documents do not record which connector imported them yet"
            )
        async with self._uow() as uow:
            connector = await _connector(uow, caller, project_id, connector_id)
            await uow.connectors.delete(connector)

    async def test(
        self, caller: Caller, project_id: str, connector_id: str
    ) -> tuple[bool, str]:
        async with self._uow() as uow:
            connector = await _connector(uow, caller, project_id, connector_id)
        return await build_source(connector.type, connector.config).check()

    async def sync(
        self, caller: Caller, project_id: str, connector_id: str
    ) -> SyncResult:
        """Import everything the source currently has. Unchanged files are
        recognised by their bytes and not imported twice."""
        connector = await self._start_sync(caller, project_id, connector_id)
        result = SyncResult()
        try:
            source = build_source(connector.type, connector.config)
            async for item in source.fetch():
                await self._import_item(caller, project_id, item, result)
            result.settle()
        except Exception as exc:
            result.status = "failed"
            result.errors.append(SyncError("", str(exc)))
        finally:
            await self._finish_sync(connector.id, result)
        return result

    async def _start_sync(
        self, caller: Caller, project_id: str, connector_id: str
    ) -> Connector:
        async with self._uow() as uow:
            connector = await _connector(uow, caller, project_id, connector_id)
            started = connector.last_synced_at
            if (
                connector.last_sync_status == "running"
                and started
                and utcnow() - started < _STALE_SYNC
            ):
                raise Busy(
                    "a sync is already running", code="sync_in_progress"
                )
            connector.last_sync_status = "running"
            connector.last_synced_at = utcnow()
        return connector

    async def _import_item(
        self,
        caller: Caller,
        project_id: str,
        item: Fetched,
        result: SyncResult,
    ) -> None:
        if item.content is None:
            result.add_failure(item.name, item.error or "no content")
            return
        with item.content as content:
            try:
                _, created = await self._documents.upload(
                    caller,
                    project_id,
                    filename=item.name,
                    mime_type=item.mime_type,
                    content=content,
                )
            except Exception as exc:
                result.add_failure(item.name, str(exc))
                return
        if created:
            result.imported += 1
        else:
            result.unchanged += 1

    async def _finish_sync(
        self, connector_id: str, result: SyncResult
    ) -> None:
        async with self._uow() as uow:
            connector = await uow.connectors.get(connector_id)
            if connector is None:
                return
            connector.last_sync_status = result.status
            connector.last_sync_detail = result.summary
            connector.last_synced_at = utcnow()
