"""Connector store port (persistent connector definitions + sync state)."""

from abc import ABC, abstractmethod

from service.models import Connector


class ConnectorStore(ABC):
    @abstractmethod
    async def add(self, connector: Connector) -> None:
        """Insert a new connector."""

    @abstractmethod
    async def get(self, connector_id: str) -> Connector | None:
        """Return the connector, or ``None`` if it does not exist."""

    @abstractmethod
    async def list(self, project_id: str) -> list[Connector]:
        """Return one project's connectors (newest first)."""

    @abstractmethod
    async def save(self, connector: Connector) -> None:
        """Persist changes to an existing connector (update in place)."""

    @abstractmethod
    async def delete(self, connector_id: str) -> None:
        """Remove a connector (no error if absent)."""
