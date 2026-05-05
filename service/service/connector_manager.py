"""Manage persistent connectors: CRUD, health check, and on-demand sync.

A connector is a stored :class:`~models.Connector` (type + config + sync
state). This service turns one into a :class:`~service.connectors.Source` to
run a sync (fetch -> store, reusing ``ConnectorService``) or a health probe,
and records the last-sync outcome on the row.
"""

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from models import Connector
from service.connectors import (
    ConnectorService,
    GoogleDriveSource,
    ImportResult,
    Source,
    UrlSource,
)
from storage.store import ConnectorStore

logger = logging.getLogger(__name__)

ConnectorStoreUoW = Callable[[], AbstractAsyncContextManager[ConnectorStore]]


class ConnectorError(Exception):
    """Base class for connector-management failures."""


class UnknownConnector(ConnectorError):
    """No connector with the given id."""


class InvalidConnectorConfig(ConnectorError):
    """The type/config combination is not valid."""


@dataclass(slots=True)
class SyncResult:
    connector_id: str
    status: str  # "ok" | "partial" | "error"
    imported: int
    errors: int
    detail: str
    results: list[ImportResult]


class ConnectorManager:
    def __init__(
        self,
        *,
        store_uow: ConnectorStoreUoW,
        importer: ConnectorService,
    ) -> None:
        self._store_uow = store_uow
        self._importer = importer

    async def create(
        self,
        *,
        project_id: str,
        type: str,
        name: str,
        config: dict[str, Any],
    ) -> Connector:
        _validate(type, config)
        now = datetime.now(UTC)
        connector = Connector(
            id=uuid.uuid4().hex,
            project_id=project_id,
            type=type,
            name=name,
            config=config,
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        async with self._store_uow() as store:
            await store.add(connector)
        return connector

    async def list(self, *, project_id: str) -> list[Connector]:
        async with self._store_uow() as store:
            return await store.list(project_id)

    async def get(self, connector_id: str, *, project_id: str) -> Connector:
        async with self._store_uow() as store:
            connector = await store.get(connector_id)
        # A connector owned by another project reads as "unknown" -- callers
        # never learn a foreign connector exists.
        if connector is None or connector.project_id != project_id:
            raise UnknownConnector(connector_id)
        return connector

    async def update(
        self,
        connector_id: str,
        *,
        project_id: str,
        name: str | None = None,
        config: dict[str, Any] | None = None,
        enabled: bool | None = None,
    ) -> Connector:
        async with self._store_uow() as store:
            connector = await store.get(connector_id)
            if connector is None or connector.project_id != project_id:
                raise UnknownConnector(connector_id)
            if name is not None:
                connector.name = name
            if config is not None:
                _validate(connector.type, config)
                connector.config = config
            if enabled is not None:
                connector.enabled = enabled
            connector.updated_at = datetime.now(UTC)
            await store.save(connector)
        return connector

    async def delete(self, connector_id: str, *, project_id: str) -> None:
        async with self._store_uow() as store:
            connector = await store.get(connector_id)
            if connector is None or connector.project_id != project_id:
                return  # unknown/foreign: nothing to delete (idempotent)
            await store.delete(connector_id)

    async def health(
        self, connector_id: str, *, project_id: str
    ) -> tuple[bool, str]:
        connector = await self.get(connector_id, project_id=project_id)
        return await _source_for(connector).check_health()

    async def sync(self, connector_id: str, *, project_id: str) -> SyncResult:
        connector = await self.get(connector_id, project_id=project_id)
        try:
            results = await self._importer.import_from(
                _source_for(connector), project_id=project_id
            )
        except Exception as exc:
            await self._record(connector_id, "error", str(exc))
            return SyncResult(connector_id, "error", 0, 0, str(exc), [])

        errors = sum(1 for r in results if r.status == "error")
        imported = len(results) - errors
        if errors == 0:
            status = "ok"
        elif imported == 0:
            status = "error"
        else:
            status = "partial"
        detail = f"{imported} imported, {errors} error(s)"
        await self._record(connector_id, status, detail)
        logger.info("connector %s synced: %s", connector_id, detail)
        return SyncResult(
            connector_id, status, imported, errors, detail, results
        )

    async def _record(
        self, connector_id: str, status: str, detail: str
    ) -> None:
        now = datetime.now(UTC)
        async with self._store_uow() as store:
            connector = await store.get(connector_id)
            if connector is None:
                return
            connector.last_synced_at = now
            connector.last_sync_status = status
            connector.last_sync_detail = detail
            connector.updated_at = now
            await store.save(connector)


def _validate(connector_type: str, config: dict[str, Any]) -> None:
    if connector_type == "url":
        urls = config.get("urls")
        if (
            not isinstance(urls, list)
            or not urls
            or not all(isinstance(u, str) and u for u in urls)
        ):
            raise InvalidConnectorConfig(
                "url connector requires config.urls: "
                "a non-empty list of strings"
            )
    elif connector_type == "google_drive":
        if not config.get("access_token"):
            raise InvalidConnectorConfig(
                "google_drive requires config.access_token"
            )
        file_ids = config.get("file_ids")
        if (
            not isinstance(file_ids, list)
            or not file_ids
            or not all(isinstance(f, str) and f for f in file_ids)
        ):
            raise InvalidConnectorConfig(
                "google_drive requires config.file_ids: "
                "a non-empty list of strings"
            )
    else:
        raise InvalidConnectorConfig(
            f"unknown connector type: {connector_type!r}"
        )


def _source_for(connector: Connector) -> Source:
    if connector.type == "url":
        return UrlSource(list(connector.config["urls"]))
    if connector.type == "google_drive":
        base = connector.config.get("base_url")
        if base:
            return GoogleDriveSource(
                access_token=connector.config["access_token"],
                file_ids=list(connector.config["file_ids"]),
                base_url=base,
            )
        return GoogleDriveSource(
            access_token=connector.config["access_token"],
            file_ids=list(connector.config["file_ids"]),
        )
    raise InvalidConnectorConfig(
        f"unknown connector type: {connector.type!r}"
    )
