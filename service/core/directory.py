"""Who a given caller is allowed to see in the user directory.

The Members page lets a moderator add an existing account to a project, which
means offering a list to pick from. That list is narrowed here rather than in
the route, because the rule is a policy decision and deserves to be stated
once, in one place:

* the **instance owner** administers every project, so they see every account;
* a **project moderator** sees the people in the projects they moderate --
  which reveals nothing new, since they could already enumerate exactly those
  people by listing each of those projects' members;
* anyone else sees nobody, because they cannot add members anywhere.

The deliberate consequence of the middle rule: an account that belongs to no
project (created by a plain, non-project invite) is invisible to project
moderators. They fall back to issuing an invite, which is harmless -- the
account simply gets joined a different way.
"""

from dataclasses import dataclass

from service.core.auth import Principal
from service.models import User
from service.storage.store import ProjectStore, UserStore

_MODERATOR_ROLES = ("owner", "admin")


@dataclass(frozen=True, slots=True)
class DirectoryEntry:
    """One pickable account. Deliberately minimal: enough to recognise a
    person and add them, and nothing about their credentials or status."""

    user_id: str
    email: str
    username: str


async def visible_users(
    *,
    principal: Principal,
    users: UserStore,
    projects: ProjectStore,
) -> list[DirectoryEntry]:
    """The accounts ``principal`` may see, alphabetically by email."""
    if principal.role == "owner":
        found: list[User] = await users.list_all()
    else:
        visible_ids = await _ids_in_moderated_projects(principal, projects)
        if not visible_ids:
            return []
        found = [u for u in await users.list_all() if u.id in visible_ids]

    return sorted(
        (
            DirectoryEntry(
                user_id=u.id, email=u.email, username=u.username
            )
            for u in found
        ),
        key=lambda e: e.email.lower(),
    )


async def _ids_in_moderated_projects(
    principal: Principal, projects: ProjectStore
) -> set[str]:
    """Every user id appearing in a project this caller moderates."""
    ids: set[str] = set()
    for project in await projects.list_for_user(principal.user_id):
        membership = await projects.get_member(project.id, principal.user_id)
        if membership is None or membership.role not in _MODERATOR_ROLES:
            continue
        for member in await projects.list_members(project.id):
            ids.add(member.user_id)
    return ids
