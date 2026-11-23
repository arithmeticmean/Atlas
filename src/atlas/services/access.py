"""Who is calling, and what they may do.

Instance roles: ``owner`` (one), ``admin``, ``member``. Project roles:
``admin`` (manages the project) and ``member`` (uses it). The instance owner
and admins act as admins of every project, without a membership row.
"""

from dataclasses import dataclass
from typing import Literal

from atlas.models.project import Project
from atlas.models.user import UserRole
from atlas.repository.uow import UnitOfWork
from atlas.services.errors import NotFound, PermissionDenied

# A caller's role on one project. "owner" means "through their instance
# role", which outranks any membership.
EffectiveRole = Literal["owner", "admin", "member"]


@dataclass(frozen=True, slots=True)
class Caller:
    """Read from the access token on every request; no database lookup."""

    user_id: str
    role: UserRole

    @property
    def is_instance_admin(self) -> bool:
        return self.role in ("owner", "admin")


def require_instance_admin(caller: Caller) -> None:
    if not caller.is_instance_admin:
        raise PermissionDenied("requires an instance admin")


def require_owner(caller: Caller) -> None:
    if caller.role != "owner":
        raise PermissionDenied("requires the instance owner")


async def load_project(
    uow: UnitOfWork,
    caller: Caller,
    project_id: str,
    *,
    admin: bool = False,
) -> tuple[Project, EffectiveRole]:
    """The project and the caller's role on it.

    A project the caller is not in reads as missing (404), so its existence
    is not revealed. ``admin=True`` additionally requires managing it (403).
    """
    project = await uow.projects.get(project_id)
    role: EffectiveRole | None = None
    if project is not None:
        if caller.is_instance_admin:
            role = "owner"
        elif member := await uow.members.find(project_id, caller.user_id):
            role = member.role
    if project is None or role is None:
        raise NotFound("project not found", code="project_not_found")
    if admin and role == "member":
        raise PermissionDenied("requires a project admin")
    return project, role
