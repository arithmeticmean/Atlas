"""User store port."""

from abc import ABC, abstractmethod

from service.models import User


class UserStore(ABC):
    @abstractmethod
    async def add(self, user: User) -> None:
        """ """

    @abstractmethod
    async def get(self, email: str) -> User | None:
        """Return the user with this email, or ``None``."""

    @abstractmethod
    async def get_by_id(self, user_id: str) -> User | None:
        """Return the user with this id, or ``None`` (for member listings)."""

    @abstractmethod
    async def list_all(self) -> list[User]:
        """Every account, oldest first.

        The caller is responsible for narrowing this to what the requester may
        see -- see ``service.core.directory``.
        """
