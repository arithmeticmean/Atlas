"""SQLAlchemy adapter for the ConnectorStore port."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Connector
from storage.sql.models import Connector as OrmConnector
from storage.store.connector import ConnectorStore


class SqlConnectorStore(ConnectorStore):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, connector: Connector) -> None:
        self._session.add(_to_orm(connector))
        await self._session.flush()

    async def get(self, connector_id: str) -> Connector | None:
        row = await self._session.get(OrmConnector, connector_id)
        return _to_domain(row) if row is not None else None

    async def list(self, project_id: str) -> list[Connector]:
        rows = (
            await self._session.execute(
                select(OrmConnector)
                .where(OrmConnector.project_id == project_id)
                .order_by(OrmConnector.created_at.desc())
            )
        ).scalars().all()
        return [_to_domain(row) for row in rows]

    async def save(self, connector: Connector) -> None:
        row = await self._session.get(OrmConnector, connector.id)
        if row is None:
            raise LookupError(f"connector {connector.id!r} not found")
        row.name = connector.name
        row.config = connector.config
        row.enabled = connector.enabled
        row.updated_at = connector.updated_at
        row.last_synced_at = connector.last_synced_at
        row.last_sync_status = connector.last_sync_status
        row.last_sync_detail = connector.last_sync_detail
        await self._session.flush()

    async def delete(self, connector_id: str) -> None:
        row = await self._session.get(OrmConnector, connector_id)
        if row is not None:
            await self._session.delete(row)
            await self._session.flush()


def _to_orm(c: Connector) -> OrmConnector:
    return OrmConnector(
        id=c.id,
        project_id=c.project_id,
        type=c.type,
        name=c.name,
        config=c.config,
        enabled=c.enabled,
        created_at=c.created_at,
        updated_at=c.updated_at,
        last_synced_at=c.last_synced_at,
        last_sync_status=c.last_sync_status,
        last_sync_detail=c.last_sync_detail,
    )


def _to_domain(row: OrmConnector) -> Connector:
    return Connector(
        id=row.id,
        project_id=row.project_id,
        type=row.type,
        name=row.name,
        config=dict(row.config),
        enabled=row.enabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_synced_at=row.last_synced_at,
        last_sync_status=row.last_sync_status,
        last_sync_detail=row.last_sync_detail,
    )
