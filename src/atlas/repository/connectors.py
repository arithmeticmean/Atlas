from sqlalchemy import select

from atlas.models.connector import Connector
from atlas.repository.base import CrudRepository, Paged, PageRequest


class ConnectorRepository(CrudRepository[Connector]):
    model = Connector

    async def get_in_project(
        self, project_id: str, connector_id: str
    ) -> Connector | None:
        """Scoped by project in the query: another project's connector reads
        as missing."""
        rows = await self.session.scalars(
            select(Connector).where(
                Connector.id == connector_id,
                Connector.project_id == project_id,
            )
        )
        return rows.first()

    async def page_for_project(
        self, project_id: str, page: PageRequest
    ) -> Paged[Connector]:
        return await self._page(
            select(Connector)
            .where(Connector.project_id == project_id)
            .order_by(Connector.created_at.desc(), Connector.id),
            page,
        )
